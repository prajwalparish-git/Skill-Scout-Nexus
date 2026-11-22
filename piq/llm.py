"""The only module that talks to an LLM.

`call()` = JSON mode + Pydantic validation + one repair retry + agent_logs row.

Which provider answers is Layer 3's job (core/ai_router.py): Groq, Gemini or a local Ollama,
with key pools, circuit breakers and a prompt cache. When none can answer, the offline tier
(piq/offline.py, built from data/) answers instead, silently, unless AI_OFFLINE_FALLBACK=false
(the evaluation), in which case the failure is raised: `RateLimited` when every provider that
was tried is out of quota, else `LLMError`. In MOCK_MODE the response comes from `piq.mock`
without touching the network. Either way the output goes through the same validation, and
only a validated answer is stored in the prompt cache.

A student's own local model (core/local_ai.py) is passed to the router for their calls. In
MOCK_MODE it answers first when the student prefers it, and the mock answers are the fallback.
"""

import json
import logging
import time
from typing import Literal

from pydantic import BaseModel, ValidationError

from core import ai_router, local_ai
from piq import db, mock, offline
from piq.config import settings

Size = Literal["large", "small"]
log = logging.getLogger("piq.llm")
OFFLINE = "offline"  # agent_logs.model_used for an answer from the offline tier


class LLMError(RuntimeError):
    pass


class RateLimited(LLMError):
    """Every provider tried is out of quota, and the offline tier is turned off."""

    def __init__(self, retry_after: float | None, provider: str = "") -> None:
        self.retry_after = retry_after
        hint = f"Try again in about {retry_after:.0f} s." if retry_after else "Try again shortly."
        who = f"{provider} free-tier" if provider else "Free-tier"
        super().__init__(f"{who} rate limit reached. {hint}")


def _offline(agent: str, context: dict, down: ai_router.AllProvidersDown) -> str:
    """The deterministic answer for `agent`, or the providers' failure when it has none."""
    try:
        return json.dumps(offline.respond(agent, context))
    except Exception as e:  # an agent the offline tier does not cover (agents/ has its own)
        raise LLMError(f"No AI provider answered and {agent} has no offline answer: {down}") from e


def call[T: BaseModel](
    schema: type[T],
    *,
    agent: str,
    system: str,
    user: str,
    context: dict,
    size: Size = "large",
    temperature: float = 0.4,
    student_id: str | None = None,
) -> tuple[T, int]:
    """Return (validated output, agent_logs row id). `context` feeds MOCK_MODE only."""
    model = "mock" if settings().mock_mode else ""  # live: the router names it per answer
    local = local_ai.for_student(student_id)
    mock_local = model == "mock" and local is not None and local.preferred
    messages = [
        {
            "role": "system",
            "content": f"{system}\n\nRespond with one JSON object matching this JSON Schema:\n"
            f"{json.dumps(schema.model_json_schema())}",
        },
        {"role": "user", "content": user},
    ]
    request = [dict(m) for m in messages]  # the cache key: the first attempt, not a repair
    t0 = time.perf_counter()
    tok_in = tok_out = 0
    error = ""
    used = model or "none"  # what agent_logs.model_used records
    try:
        for attempt in range(3 if mock_local else 2):
            content = ""
            i = o = 0
            done = None
            if mock_local and attempt < 2:  # their model, then one repair; then mock answers
                done = ai_router.try_local(local, messages, temperature=temperature, agent=agent)
                if done:
                    content, i, o, used = done.text, done.tokens_in, done.tokens_out, done.label
            if model == "mock" and done is None:
                content, used = json.dumps(mock.respond(agent, context)), "mock"
            elif model != "mock":
                try:
                    done = ai_router.complete(
                        messages, size=size, temperature=temperature, agent=agent, local=local
                    )
                    content, i, o, used = done.text, done.tokens_in, done.tokens_out, done.label
                except ai_router.InvalidJson as e:  # the provider's words tell what to fix
                    error = f"The provider rejected the output as invalid JSON: {e}"
                except ai_router.AllProvidersDown as e:
                    if not settings().offline_fallback:
                        if e.rate_limited:
                            who = " and ".join(ai_router.LABELS[p] for p in e.failures)
                            raise RateLimited(e.retry_after, who) from e
                        raise LLMError(str(e)) from e
                    log.info("%s: no provider answered (%s); offline tier answers", agent, e)
                    content, used = _offline(agent, context, e), OFFLINE
            tok_in, tok_out = tok_in + i, tok_out + o
            if content:
                try:
                    out = schema.model_validate_json(content)
                    break
                except ValidationError as e:
                    error = str(e)
            log.warning("%s: invalid output (attempt %d): %s", agent, attempt + 1, error[:300])
            messages += [
                {"role": "assistant", "content": content or "(invalid JSON)"},
                {
                    "role": "user",
                    "content": f"That output failed validation:\n{error}\n"
                    "Return the corrected JSON object only.",
                },
            ]
        else:
            raise LLMError(f"{agent}: output failed validation twice: {error[:500]}")
    except LLMError as e:  # a failed call still cost time and tokens: log it, marked failed
        latency = int((time.perf_counter() - t0) * 1000)
        db.log_call(agent, used, tok_in, tok_out, latency, student_id, failed=str(e))
        raise
    if model != "mock" and used != OFFLINE:
        ai_router.remember(request, content, used, size=size, temperature=temperature, agent=agent)
    latency = int((time.perf_counter() - t0) * 1000)
    log_id = db.log_call(agent, used, tok_in, tok_out, latency, student_id)
    return out, log_id
