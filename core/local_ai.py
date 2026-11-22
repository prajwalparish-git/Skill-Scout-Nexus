"""A student's own AI model on this computer: Ollama, or LM Studio's OpenAI-compatible server.

Every AI call runs on the server (the Streamlit process or server.py), so the address a student
types is fetched BY THE SERVER. On a public server that would let anyone make it call addresses
of their choosing (server-side request forgery). So:

- the feature is off unless settings().local_ai (LOCAL_AI: auto = LOCAL_MODE, a one-student copy
  on a laptop; never on Render);
- an address may only name localhost, 127.0.0.1 or ::1, even when LOCAL_AI=true; localhost is
  rewritten to 127.0.0.1, so no DNS lookup or hosts file is ever consulted;
- redirects are never followed and proxy environment variables are ignored;
- connecting gives up after LOCAL_AI_CONNECT_TIMEOUT_S, so a model that is not running never
  makes a page hang.

Answers from a student's model are theirs alone: core/ai_router never puts them in the shared
prompt cache.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.ai_router import Completion, Messages, Ollama, ProviderError, breaker
from piq import db
from piq.config import (
    LOCAL_AI_CONNECT_TIMEOUT_S,
    LOCAL_AI_DEFAULT_URLS,
    LOCAL_AI_HOSTS,
    LOCAL_AI_LIST_TIMEOUT_S,
    LOCAL_AI_MAX_LIST_BYTES,
    LOCAL_AI_MODEL_MAX,
    LOCAL_AI_PROVIDERS,
    OLLAMA_TIMEOUT_S,
    settings,
)

NAME = "local"  # Completion.provider of an answer from a student's own model
MAX_ANSWER_BYTES = 4 * 1024 * 1024
DISABLED = (
    "Your own AI model works when Skill Scout Nexus runs on your laptop. This server cannot "
    "use one."
)
_BAD_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


class LocalAIError(ValueError):
    """A message safe to show: the setting is refused, or the model could not be reached."""


class LocalAIDisabled(LocalAIError):
    """This server does not allow students' local models (LOCAL_AI is off)."""

    def __init__(self) -> None:
        super().__init__(DISABLED)


def allowed() -> bool:
    return settings().local_ai


def _require_allowed() -> None:
    if not allowed():
        raise LocalAIDisabled()


def label(provider: str) -> str:
    return LOCAL_AI_PROVIDERS.get(provider, provider)


def normalize_url(provider: str, url: str | None) -> str:
    """The canonical base URL (scheme://127.0.0.1:port or scheme://[::1]:port), or LocalAIError.
    Only this computer's loopback addresses pass; an LM Studio address may end in /v1."""
    if provider not in LOCAL_AI_PROVIDERS:
        raise LocalAIError("Choose Ollama or LM Studio.")
    raw = (url or "").strip() or LOCAL_AI_DEFAULT_URLS[provider]
    if len(raw) > 200 or _BAD_CHARS.search(raw):
        raise LocalAIError("That address is not valid.")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as e:
        raise LocalAIError("That address is not valid.") from e
    if parts.scheme not in ("http", "https"):
        raise LocalAIError(
            "The address must start with http:// (for example http://127.0.0.1:11434)."
        )
    if "@" in parts.netloc or parts.query or parts.fragment:
        raise LocalAIError("Give just the address and port, with nothing else in it.")
    host = (parts.hostname or "").lower()
    if host not in LOCAL_AI_HOSTS:
        raise LocalAIError(
            "Only a model on this computer can be used: localhost, 127.0.0.1 or [::1]."
        )
    path = parts.path.rstrip("/")
    if path not in ("", "/v1") or (path == "/v1" and provider != "lmstudio"):
        raise LocalAIError("Give just the address and port, for example http://127.0.0.1:11434.")
    ip = "127.0.0.1" if host == "localhost" else host
    netloc = f"[{ip}]" if ":" in ip else ip
    if port is not None:
        netloc += f":{port}"
    return f"{parts.scheme}://{netloc}"


@lru_cache
def _client() -> httpx.Client:
    """No redirects, no proxy variables: a request goes to the address given, or nowhere."""
    return httpx.Client(follow_redirects=False, trust_env=False)


def _send(
    method: str,
    url: str,
    *,
    who: str,
    read_timeout: float,
    max_bytes: int,
    body: dict | None = None,
) -> tuple[int, Any]:
    """(status, parsed JSON or None). Every failure is a LocalAIError with a sentence to show."""
    timeout = httpx.Timeout(read_timeout, connect=LOCAL_AI_CONNECT_TIMEOUT_S)
    try:
        with _client().stream(method, url, json=body, timeout=timeout) as r:
            if 300 <= r.status_code < 400:
                raise LocalAIError(f"{who} answered with a redirect, which is not followed.")
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    raise LocalAIError(f"{who} sent more data than expected.")
            status = r.status_code
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # Windows: a closed port times out
        where = urlsplit(url)
        raise LocalAIError(
            f"Nothing is answering at {where.scheme}://{where.netloc}. Is {who} running?"
        ) from e
    except httpx.TimeoutException as e:
        raise LocalAIError(f"{who} took too long to answer.") from e
    except httpx.HTTPError as e:
        raise LocalAIError(f"Could not talk to {who} ({type(e).__name__}).") from e
    try:
        return status, json.loads(data) if data else None
    except ValueError:
        return status, None


def list_models(provider: str, base_url: str | None) -> list[str]:
    """The models the local server offers (Test connection). LocalAIError when it can't say."""
    _require_allowed()
    base = normalize_url(provider, base_url)
    who = label(provider)
    path = "/api/tags" if provider == "ollama" else "/v1/models"
    status, data = _send(
        "GET",
        base + path,
        who=who,
        read_timeout=LOCAL_AI_LIST_TIMEOUT_S,
        max_bytes=LOCAL_AI_MAX_LIST_BYTES,
    )
    if status != 200 or not isinstance(data, dict):
        raise LocalAIError(f"That address answered, but not like {who} (HTTP {status}).")
    items = data.get("models") if provider == "ollama" else data.get("data")
    key = "name" if provider == "ollama" else "id"
    names = {
        str(m.get(key))
        for m in items or []
        if isinstance(m, dict) and m.get(key) and len(str(m.get(key))) <= LOCAL_AI_MODEL_MAX
    }
    return sorted(names)[:200]


def _unfence(text: str) -> str:
    """LM Studio models often wrap JSON in a ```json fence: keep only what is inside."""
    m = _FENCE.match(text.strip())
    return m.group(1) if m else text


@dataclass(frozen=True)
class LocalModel:
    student_id: str
    provider: str
    base_url: str
    model: str
    preferred: bool

    name = NAME

    @property
    def label(self) -> str:
        return f"{NAME}:{self.model}"

    @property
    def breaker_key(self) -> str:
        return f"{NAME}:{self.student_id}"

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "preferred": self.preferred,
        }

    def complete(self, messages: Messages, *, temperature: float) -> Completion:
        """One answer from the student's model; ProviderError when it cannot give one."""
        who = label(self.provider)
        try:
            _require_allowed()  # the gate may have closed since the setting was saved
            base = normalize_url(self.provider, self.base_url)
            if self.provider == "ollama":
                status, data = _send(
                    "POST",
                    f"{base}/api/chat",
                    who=who,
                    read_timeout=OLLAMA_TIMEOUT_S,
                    max_bytes=MAX_ANSWER_BYTES,
                    body=Ollama.payload(messages, self.model),
                )
            else:
                status, data = _send(
                    "POST",
                    f"{base}/v1/chat/completions",
                    who=who,
                    read_timeout=OLLAMA_TIMEOUT_S,
                    max_bytes=MAX_ANSWER_BYTES,
                    body={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "stream": False,
                    },
                )
        except LocalAIError as e:
            raise ProviderError(str(e)) from e
        if status == 404:
            raise ProviderError(f"{who} does not have the model {self.model!r}.")
        if status >= 400 or not isinstance(data, dict):
            raise ProviderError(f"{who} could not answer (HTTP {status}).")
        try:
            if self.provider == "ollama":
                text = (data.get("message") or {}).get("content", "")
                tokens = int(data.get("prompt_eval_count", 0)), int(data.get("eval_count", 0))
            else:
                text = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage") or {}
                tokens = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError(f"{who} sent an answer this app could not read.") from e
        return Completion(_unfence(str(text)), *tokens, NAME, self.model)


def for_student(student_id: str | None) -> LocalModel | None:
    """The student's local model, when this server allows them and its saved address is still
    valid; else None."""
    if not student_id or not allowed():
        return None
    row = db.local_ai(student_id)
    if row is None:
        return None
    try:
        base = normalize_url(row["provider"], row["base_url"])
    except LocalAIError:
        return None
    return LocalModel(student_id, row["provider"], base, row["model"], bool(row["preferred"]))


def save(
    student_id: str, *, provider: str, base_url: str | None, model: str, preferred: bool
) -> LocalModel:
    _require_allowed()
    base = normalize_url(provider, base_url)
    model = (model or "").strip()
    if not 1 <= len(model) <= LOCAL_AI_MODEL_MAX or _BAD_CHARS.search(model.replace(" ", "")):
        raise LocalAIError("Choose a model (use Test connection to list them).")
    db.save_local_ai(student_id, provider, base, model, bool(preferred))
    saved = LocalModel(student_id, provider, base, model, bool(preferred))
    breaker(saved.breaker_key).success()  # a model they just started is tried at once
    return saved


def remove(student_id: str) -> None:
    _require_allowed()
    db.delete_local_ai(student_id)


def using_local(student_id: str | None) -> str | None:
    """The model name when the student's latest AI answer came from their own model."""
    if not student_id or not allowed():
        return None
    last = db.last_model_used(student_id) or ""
    return last.removeprefix(f"{NAME}:") if last.startswith(f"{NAME}:") else None
