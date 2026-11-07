"""Layer 3, self-healing AI router: answer each LLM request as fast as the healthy providers
allow, and never fail the student.

Tiers, in AI_PROVIDERS order (default: speed first):
1. groq: the fastest cloud. A round-robin pool of keys (GROQ_API_KEYS, core/key_pool.py);
   a key that hits a 429 rests and the next key is tried at once. Timeout GROQ_TIMEOUT_S.
2. gemini: high-capacity cloud over REST, its own key pool (GEMINI_API_KEYS). GEMINI_TIMEOUT_S.
3. ollama: a local model. A 200 ms TCP ping first (offline: skipped at once), the model kept
   loaded (keep_alive -1) with a small context and answer budget for speed.
4. Then piq/llm.py's offline tier answers from data/ (question bank, role skills, tracks).

Each provider also sits behind a circuit breaker: errors that mean "this provider is down"
(network, timeouts, HTTP 5xx, a retired model) open it after ROUTER_FAILURE_THRESHOLD in a row,
and requests skip it until a cooldown passes. A provider with no key, or with every key
resting, is skipped without any network call.

Answers for plans, critiques and rubric evaluations are cached by request hash
(core/ai_cache.py): an identical request returns from memory without a call.

The router moves text only: piq/llm.py builds the messages, validates the JSON, repairs once,
logs the call and stores a validated answer in the cache.
"""

import logging
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urlsplit

import httpx

from core.ai_cache import PromptCache, request_key
from core.key_pool import KeyPoolManager
from piq.config import (
    AI_CACHE_AGENTS,
    OLLAMA_HEALTH_TTL_S,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_PING_TIMEOUT_S,
    OLLAMA_PROBE_TIMEOUT_S,
    OLLAMA_TEMPERATURE,
    OLLAMA_TIMEOUT_S,
    ROUTER_BROKEN_COOLDOWN_S,
    ROUTER_COOLDOWN_S,
    ROUTER_FAILURE_THRESHOLD,
    settings,
)

if TYPE_CHECKING:
    from groq import Groq

Size = Literal["large", "small"]
Messages = list[dict[str, str]]
State = Literal["ready", "paused", "off"]
log = logging.getLogger("core.ai_router")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LABELS = {"gemini": "Gemini", "groq": "Groq", "ollama": "Ollama (local)"}
CACHE = "cache"  # Completion.provider of an answer served from the prompt cache


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    provider: str
    model: str

    @property
    def label(self) -> str:
        """What agent_logs.model_used records, e.g. 'groq:openai/gpt-oss-120b'."""
        return f"{self.provider}:{self.model}"


class ProviderError(Exception):
    """The provider could not answer this request.

    `counts`: it says the provider is unwell (False for a request refused on its merits, or
    a key pool that is only resting). `rate_limited` / `retry_after`: quota and the hint.
    `cooldown`: open the breaker this long at once (a retired model will not heal soon)."""

    def __init__(
        self,
        message: str,
        *,
        counts: bool = True,
        rate_limited: bool = False,
        retry_after: float | None = None,
        cooldown: float | None = None,
    ) -> None:
        super().__init__(message)
        self.counts, self.rate_limited = counts, rate_limited
        self.retry_after, self.cooldown = retry_after, cooldown


class InvalidJson(Exception):
    """The provider answered but refused the model's output as invalid JSON: repairable."""


class AllProvidersDown(Exception):
    """No provider could answer. `failures`: the reason for each provider that was tried or is
    paused; `skipped`: providers left out because they are not set up or not reachable."""

    def __init__(
        self,
        failures: Mapping[str, str],
        skipped: Mapping[str, str],
        *,
        rate_limited: bool,
        retry_after: float | None,
    ) -> None:
        self.failures, self.skipped = dict(failures), dict(skipped)
        self.rate_limited, self.retry_after = rate_limited, retry_after
        if not failures:
            message = (
                "No AI provider is set up: add GROQ_API_KEYS, GEMINI_API_KEYS or "
                "OLLAMA_BASE_URL to .env."
            )
        elif len(failures) == 1:
            message = next(iter(failures.values()))
        else:
            message = "; ".join(f"{LABELS[k]}: {v}" for k, v in failures.items())
        super().__init__(message)


# --- circuit breaker --------------------------------------------------------------------------


class CircuitBreaker:
    """Closed (requests go through) -> open (skipped until a deadline) -> half-open (one trial
    decides). Thread-safe: Streamlit serves each session from its own thread."""

    def __init__(
        self,
        threshold: int = ROUTER_FAILURE_THRESHOLD,
        cooldown: float = ROUTER_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold, self.cooldown, self._clock = threshold, cooldown, clock
        self._lock = threading.Lock()
        self.failures = 0
        self.open_until = 0.0
        self.reason = ""
        self.rate_limited = False

    @property
    def state(self) -> Literal["closed", "open", "half-open"]:
        if not self.open_until:
            return "closed"
        return "open" if self._clock() < self.open_until else "half-open"

    def allow(self) -> bool:
        return self.state != "open"

    def retry_in(self) -> float:
        return max(0.0, self.open_until - self._clock()) if self.open_until else 0.0

    def success(self) -> None:
        with self._lock:
            self.failures, self.open_until, self.reason, self.rate_limited = 0, 0.0, "", False

    def failure(
        self,
        reason: str,
        *,
        retry_after: float | None = None,
        cooldown: float | None = None,
        rate_limited: bool = False,
    ) -> None:
        with self._lock:
            now = self._clock()
            half_open = bool(self.open_until) and now >= self.open_until
            self.failures += 1
            self.reason, self.rate_limited = reason, rate_limited
            if half_open or rate_limited or cooldown or self.failures >= self.threshold:
                wait = max(cooldown or self.cooldown, retry_after or 0.0)
                self.open_until = now + wait


# --- key pools --------------------------------------------------------------------------------

_pools: dict[str, KeyPoolManager] = {}
_pools_lock = threading.Lock()


def key_pool(provider: str, keys: tuple[str, ...]) -> KeyPoolManager:
    """The provider's pool for these keys (rebuilt when .env's keys change)."""
    with _pools_lock:
        pool = _pools.get(provider)
        if pool is None or pool.keys != tuple(dict.fromkeys(keys)):
            pool = _pools[provider] = KeyPoolManager(keys)
        return pool


def _all_resting(name: str, pool: KeyPoolManager, hint: float | None = None) -> ProviderError:
    """Every key is resting: say whether from rate limits (wait) or refusals (fix .env). The
    pool holds that state, so the provider's own breaker is left alone (counts=False)."""
    n = len(pool)
    which = "its key" if n == 1 else f"all {n} keys"
    reasons = {k.reason for k in pool.status() if not k.available}
    if reasons and all(r.startswith("refused") for r in reasons):
        return ProviderError(
            f"{name} refused {which}; check {name.upper()}_API_KEYS in .env", counts=False
        )
    return ProviderError(
        f"{name} free-tier rate limit reached on {which}",
        counts=False,
        rate_limited=True,
        retry_after=hint if hint is not None else (pool.retry_in() or None),
    )


# --- providers --------------------------------------------------------------------------------


class Provider(Protocol):
    name: str

    def unavailable(self) -> str:
        """Why this provider cannot take requests now ('' = it can)."""
        ...

    def model(self, size: Size) -> str: ...

    def complete(
        self, messages: Messages, *, size: Size, temperature: float, agent: str
    ) -> Completion: ...

    def detail(self) -> str:
        """One line for the status panel when the provider is ready."""
        ...


@lru_cache
def _http() -> httpx.Client:
    """One pooled client for Gemini and Ollama (tests swap in a MockTransport)."""
    return httpx.Client()


def _retry_after(headers: Mapping[str, str]) -> float | None:
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def _excerpt(r: httpx.Response) -> str:
    try:
        body = r.json()
        error = body.get("error") if isinstance(body, dict) else None
        text = error.get("message", "") if isinstance(error, dict) else str(error or body)
    except ValueError:
        text = r.text
    return " ".join(str(text).split())[:300]


def _keys_detail(pool: KeyPoolManager) -> str:
    n, ok = len(pool), pool.available_count()
    return "Ready" if n == 1 else f"Ready: {ok} of {n} keys available"


@lru_cache
def _groq_client(key: str, timeout: float) -> "Groq":
    from groq import Groq  # imported lazily so MOCK_MODE never needs network config

    # No SDK retries: a rate-limited key is skipped for the next one at once (core/key_pool).
    return Groq(api_key=key, max_retries=0, timeout=timeout)


class GroqProvider:
    name = "groq"

    def pool(self) -> KeyPoolManager:
        return key_pool(self.name, settings().groq_api_keys)

    def unavailable(self) -> str:
        s = settings()
        if not s.groq_api_keys:
            return "GROQ_API_KEYS is not set"
        return "" if s.model_large and s.model_small else "GROQ_MODEL_LARGE/SMALL are not set"

    def model(self, size: Size) -> str:
        s = settings()
        return s.model_large if size == "large" else s.model_small

    def detail(self) -> str:
        return _keys_detail(self.pool())

    def complete(
        self, messages: Messages, *, size: Size, temperature: float, agent: str
    ) -> Completion:
        import groq

        s, pool, model = settings(), self.pool(), self.model(size)
        keys = pool.order()
        if not keys:
            raise _all_resting("Groq", pool)
        hint: float | None = None
        for key in keys:
            t0 = time.perf_counter()
            try:
                r = _groq_client(key, s.groq_timeout_s).chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
            except groq.RateLimitError as e:
                hint = _retry_after(e.response.headers)
                pool.rate_limited(key, hint)
                log.info("%s: a Groq key is rate-limited; next key", agent)
                continue
            except (groq.AuthenticationError, groq.PermissionDeniedError):
                pool.refused(key, "refused by Groq")
                log.warning("%s: Groq refused a key; it rests for an hour", agent)
                continue
            except groq.NotFoundError as e:
                raise ProviderError(
                    f"Groq no longer serves model {model!r}. Update GROQ_MODEL_LARGE / "
                    "GROQ_MODEL_SMALL in .env (see console.groq.com/docs/models).",
                    cooldown=ROUTER_BROKEN_COOLDOWN_S,
                ) from e
            except groq.BadRequestError as e:
                # Groq rejects output that is not valid JSON in json_object mode: repairable.
                if "json_validate_failed" in str(e):
                    pool.success(key, time.perf_counter() - t0)
                    raise InvalidJson(str(e)) from e
                raise ProviderError(f"Groq rejected the request: {e}", counts=False) from e
            except groq.APITimeoutError as e:  # the model, not the key: move to the next tier
                raise ProviderError(f"Groq timed out after {s.groq_timeout_s:g} s") from e
            except groq.APIError as e:  # connection errors and HTTP 5xx
                raise ProviderError(f"Groq API error: {e}") from e
            pool.success(key, time.perf_counter() - t0)
            u = r.usage
            return Completion(
                r.choices[0].message.content or "",
                u.prompt_tokens,
                u.completion_tokens,
                self.name,
                model,
            )
        raise _all_resting("Groq", pool, hint)


class Gemini:
    name = "gemini"

    def pool(self) -> KeyPoolManager:
        return key_pool(self.name, settings().gemini_api_keys)

    def unavailable(self) -> str:
        s = settings()
        if not s.gemini_api_keys:
            return "GEMINI_API_KEYS is not set"
        return "" if s.gemini_model else "GEMINI_MODEL is not set"

    def model(self, size: Size) -> str:
        return settings().gemini_model

    def detail(self) -> str:
        return _keys_detail(self.pool())

    @staticmethod
    def body(messages: Messages, temperature: float) -> dict:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body: dict = {
            "contents": [
                {
                    "role": "model" if m["role"] == "assistant" else "user",
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
                if m["role"] != "system"
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def complete(
        self, messages: Messages, *, size: Size, temperature: float, agent: str
    ) -> Completion:
        s, pool = settings(), self.pool()
        keys = pool.order()
        if not keys:
            raise _all_resting("Gemini", pool)
        body, hint = self.body(messages, temperature), None
        for key in keys:
            t0 = time.perf_counter()
            try:
                r = _http().post(
                    GEMINI_URL.format(model=s.gemini_model),
                    json=body,
                    headers={"x-goog-api-key": key},
                    timeout=s.gemini_timeout_s,
                )
            except httpx.TimeoutException as e:
                raise ProviderError(f"Gemini timed out after {s.gemini_timeout_s:g} s") from e
            except httpx.HTTPError as e:
                raise ProviderError(f"Gemini is unreachable ({type(e).__name__})") from e
            if r.status_code == 429:
                hint = _retry_after(r.headers)
                pool.rate_limited(key, hint)
                log.info("%s: a Gemini key is rate-limited; next key", agent)
                continue
            if r.status_code in (401, 403):
                pool.refused(key, "refused by Gemini")
                log.warning("%s: Gemini refused a key: %s", agent, _excerpt(r))
                continue
            if r.status_code == 404:
                raise ProviderError(
                    f"Gemini does not serve model {s.gemini_model!r}. Update GEMINI_MODEL in .env "
                    "(see ai.google.dev/gemini-api/docs/models).",
                    cooldown=ROUTER_BROKEN_COOLDOWN_S,
                )
            if r.status_code == 400:
                raise ProviderError(f"Gemini rejected the request: {_excerpt(r)}", counts=False)
            if r.status_code >= 400:
                raise ProviderError(f"Gemini API error {r.status_code}: {_excerpt(r)}")
            pool.success(key, time.perf_counter() - t0)
            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:  # blocked by a safety filter: the request, not the service
                blocked = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
                raise ProviderError(f"Gemini returned no answer ({blocked})", counts=False)
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            usage = data.get("usageMetadata") or {}
            return Completion(
                text,
                int(usage.get("promptTokenCount", 0)),
                int(usage.get("candidatesTokenCount", 0)),
                self.name,
                s.gemini_model,
            )
        raise _all_resting("Gemini", pool, hint)


def _ping(base_url: str, timeout: float = OLLAMA_PING_TIMEOUT_S) -> bool:
    """Does anything accept TCP connections at the URL's host and port within `timeout`?"""
    parts = urlsplit(base_url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname or "localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


class Ollama:
    name = "ollama"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._checked: tuple[float, str, str, str] | None = None  # (when, url, model, reason)

    def model(self, size: Size) -> str:
        return settings().ollama_model

    def detail(self) -> str:
        return "Ready"

    def forget(self) -> None:
        self._checked = None

    def unavailable(self) -> str:
        s = settings()
        if not (s.ollama_base_url and s.ollama_model):
            return "OLLAMA_BASE_URL is not set"
        if not _ping(s.ollama_base_url):  # every request: refused at once, or 200 ms at most
            self.forget()
            return f"Ollama is not running at {s.ollama_base_url}"
        now, c = self._clock(), self._checked
        key = (s.ollama_base_url, s.ollama_model)
        if c and (c[1], c[2]) == key and now - c[0] < OLLAMA_HEALTH_TTL_S:
            return c[3]
        reason = self._probe(*key)
        self._checked = (now, *key, reason)
        return reason

    @staticmethod
    def _probe(base: str, model: str) -> str:
        try:
            r = _http().get(f"{base}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT_S)
            r.raise_for_status()
            names = {m.get("name", "") for m in r.json().get("models", [])}
        except (httpx.HTTPError, ValueError, AttributeError):
            return f"Ollama is not answering at {base}"
        wanted = {model, f"{model}:latest"}
        if not (names & wanted or any(n.split(":")[0] == model for n in names)):
            return f"Ollama has not pulled {model!r} (run: ollama pull {model})"
        return ""

    @staticmethod
    def payload(messages: Messages, model: str) -> dict:
        s = settings()
        return {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,  # stays loaded: no reload before the next request
            "options": {
                "num_ctx": s.ollama_num_ctx,
                "num_predict": s.ollama_num_predict,
                "temperature": OLLAMA_TEMPERATURE,
            },
        }

    def complete(
        self, messages: Messages, *, size: Size, temperature: float, agent: str
    ) -> Completion:
        s = settings()
        try:
            r = _http().post(
                f"{s.ollama_base_url}/api/chat",
                json=self.payload(messages, s.ollama_model),
                timeout=OLLAMA_TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            self.forget()  # the next request re-checks health instead of trusting the cache
            raise ProviderError(f"Ollama is unreachable ({type(e).__name__})") from e
        if r.status_code == 404:
            self.forget()
            raise ProviderError(
                f"Ollama has not pulled {s.ollama_model!r}", cooldown=ROUTER_COOLDOWN_S
            )
        if r.status_code >= 400:
            raise ProviderError(f"Ollama error {r.status_code}: {_excerpt(r)}")
        data = r.json()
        return Completion(
            (data.get("message") or {}).get("content", ""),
            int(data.get("prompt_eval_count", 0)),
            int(data.get("eval_count", 0)),
            self.name,
            s.ollama_model,
        )


PROVIDERS: dict[str, Provider] = {p.name: p for p in (GroqProvider(), Gemini(), Ollama())}
_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def breaker(name: str) -> CircuitBreaker:
    with _breakers_lock:
        return _breakers.setdefault(name, CircuitBreaker())


# --- the prompt cache -------------------------------------------------------------------------

_cache: PromptCache | None = None
_cache_lock = threading.Lock()


def prompt_cache() -> PromptCache:
    global _cache
    with _cache_lock:
        path = settings().ai_cache_path
        if _cache is None or _cache.path != path:
            _cache = PromptCache(path)
        return _cache


def _cacheable(agent: str) -> bool:
    return settings().ai_cache and agent in AI_CACHE_AGENTS


def cached(messages: Messages, *, size: Size, temperature: float, agent: str) -> Completion | None:
    """The stored answer to this exact request, or None."""
    if not _cacheable(agent):
        return None
    entry = prompt_cache().get(request_key(messages, size, temperature, agent))
    return Completion(entry.text, 0, 0, CACHE, entry.label) if entry else None


def remember(
    messages: Messages, text: str, label: str, *, size: Size, temperature: float, agent: str
) -> None:
    """Store an answer that passed validation (piq/llm.py calls this; never an invalid one)."""
    if _cacheable(agent) and not label.startswith(f"{CACHE}:"):
        prompt_cache().put(request_key(messages, size, temperature, agent), text, label)


def reset() -> None:
    """Close every breaker, empty the key pools, forget health checks and drop the in-memory
    cache (tests; or after fixing .env)."""
    global _cache
    with _breakers_lock:
        _breakers.clear()
    with _pools_lock:
        _pools.clear()
    with _cache_lock:
        _cache = None
    ollama = PROVIDERS.get("ollama")
    if isinstance(ollama, Ollama):
        ollama.forget()


# --- routing ----------------------------------------------------------------------------------


def complete(messages: Messages, *, size: Size, temperature: float, agent: str) -> Completion:
    """The cached answer, else the first healthy provider's. Raises InvalidJson (repairable;
    the provider is up) or AllProvidersDown."""
    hit = cached(messages, size=size, temperature=temperature, agent=agent)
    if hit:
        return hit
    failures: dict[str, str] = {}
    skipped: dict[str, str] = {}
    hints: list[float | None] = []
    limited = 0
    for name in settings().ai_providers:
        provider = PROVIDERS[name]
        why = provider.unavailable()
        if why:
            skipped[name] = why
            continue
        b = breaker(name)
        if not b.allow():
            failures[name] = f"paused after errors ({b.reason})"
            if b.rate_limited:
                limited += 1
                hints.append(b.retry_in())
            continue
        try:
            out = provider.complete(messages, size=size, temperature=temperature, agent=agent)
        except InvalidJson:
            b.success()  # it answered; the output just needs repair
            raise
        except ProviderError as e:
            if e.counts:
                b.failure(
                    str(e),
                    retry_after=e.retry_after,
                    cooldown=e.cooldown,
                    rate_limited=e.rate_limited,
                )
            failures[name] = str(e)
            if e.rate_limited:
                limited += 1
                hints.append(e.retry_after)
            log.info("%s: %s could not answer (%s); next tier", agent, name, e)
            continue
        b.success()
        return out
    known = [h for h in hints if h]
    raise AllProvidersDown(
        failures,
        skipped,
        rate_limited=bool(failures) and limited == len(failures),
        retry_after=min(known) if known else None,
    )


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    label: str
    state: State
    detail: str
    keys: int = 0  # API keys in the provider's round-robin pool (0: it has no pool)


def status() -> list[ProviderStatus]:
    """Every configured provider in routing order, for the sidebar and the faculty page."""
    out = []
    for name in settings().ai_providers:
        provider = PROVIDERS[name]
        why = provider.unavailable()
        b = breaker(name)
        pool = getattr(provider, "pool", None)
        keys = len(pool()) if pool else 0
        if why:
            out.append(ProviderStatus(name, LABELS[name], "off", why, keys))
        elif not b.allow():
            detail = f"Paused for {b.retry_in():.0f} s: {b.reason}"
            out.append(ProviderStatus(name, LABELS[name], "paused", detail, keys))
        elif pool and not pool().available_count():
            rest = pool().retry_in()
            detail = f"All keys resting after rate limits; back in {rest:.0f} s"
            out.append(ProviderStatus(name, LABELS[name], "paused", detail, keys))
        else:
            out.append(ProviderStatus(name, LABELS[name], "ready", provider.detail(), keys))
    return out


def active_provider() -> str:
    """Label of the provider the next request will try first, or 'Offline rules'."""
    if settings().mock_mode:
        return "Mock mode"
    ready = next((p for p in status() if p.state == "ready"), None)
    return ready.label if ready else "Offline rules"
