"""Hands-free voice interviews over HTTP (piq/handsfree.py): the rules, starting a run,
transcribing a spoken answer (16 kHz mono 16-bit WAV), noting a fallback, and the spoken
question's audio.

There is no open text-to-speech endpoint: audio is only for questions this server produced. The
interview turn route synthesises the question (core/speech_router.py), registers it here and
hands the page a short-lived token; the clip route serves the cached clip for that token and
never synthesises anything itself.
"""

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from core import speech_router
from piq import handsfree
from piq.config import HANDSFREE_MAX_AUDIO_BYTES
from piq.services import ServiceError
from routers.auth import require_student

router = APIRouter(prefix="/api/handsfree", tags=["handsfree"])

CLIP_TTL_S = 3600
TRANSCRIBE_MAX, TRANSCRIBE_WINDOW_S = 60, 3600  # per student
_clips: dict[str, tuple[str, str, float]] = {}  # token -> (student, text, expires)
_clips_lock = threading.Lock()
_calls: dict[str, list[float]] = {}
_calls_lock = threading.Lock()


def call[T](work: Callable[[], T]) -> T:
    try:
        return work()
    except handsfree.HandsfreeForbidden as e:
        raise HTTPException(403, str(e)) from e
    except handsfree.HandsfreeLimit as e:
        raise HTTPException(409, str(e)) from e
    except ServiceError as e:
        raise HTTPException(400, str(e)) from e


def speech_for(student_id: str, text: str) -> dict:
    """The spoken question for a turn: a clip URL when a server voice made one, otherwise the
    browser speaks the text. The same text is always on screen."""
    sp = speech_router.synthesize(text)
    if not sp.audio:
        return {"browser": True, "text": sp.text, "source": sp.source}
    token = secrets.token_urlsafe(18)
    now = time.time()
    with _clips_lock:
        for k in [k for k, v in _clips.items() if v[2] < now]:
            del _clips[k]
        _clips[token] = (student_id, sp.text, now + CLIP_TTL_S)
    return {
        "url": f"/api/handsfree/clip/{token}",
        "mime": sp.mime_type,
        "text": sp.text,
        "source": sp.source,
    }


def transcribe_throttle(sid: str = Depends(require_student)) -> str:
    now = time.monotonic()
    with _calls_lock:
        recent = [t for t in _calls.get(sid, []) if now - t < TRANSCRIBE_WINDOW_S]
        if len(recent) >= TRANSCRIBE_MAX:
            _calls[sid] = recent
            raise HTTPException(429, "Too many recordings. Try again later.")
        _calls[sid] = [*recent, now]
    return sid


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_index: int = Field(ge=0, lt=handsfree.MAX_QUESTIONS)
    input: str = Field(max_length=20)
    reason: str = Field(max_length=60)


@router.get("/rules")
def rules() -> dict:
    """The rules every student gets, shown before starting."""
    return {**asdict(handsfree.rules()), "reasons": list(handsfree.REASONS)}


@router.post("/runs")
def start(sid: str = Depends(require_student)) -> dict:
    run_id, r = handsfree.start(sid)
    return {"run_id": run_id, "rules": asdict(r)}


@router.post("/runs/{run_id}/transcribe")
async def transcribe(
    run_id: str,
    question_index: Annotated[int, Form(ge=0, lt=handsfree.MAX_QUESTIONS)],
    attempt_no: Annotated[int, Form(ge=1, le=10)],
    audio: Annotated[UploadFile, File()],
    input: Annotated[str, Form(max_length=20)] = "voice",
    sid: str = Depends(transcribe_throttle),
) -> dict:
    data = await audio.read(HANDSFREE_MAX_AUDIO_BYTES + 1)
    out = call(
        lambda: handsfree.transcribe(
            sid, run_id, question_index, attempt_no, data, input_mode=input
        )
    )
    return asdict(out)


@router.post("/runs/{run_id}/note")
def note(run_id: str, body: NoteRequest, sid: str = Depends(require_student)) -> dict:
    call(lambda: handsfree.note(sid, run_id, body.question_index, body.input, body.reason))
    return {"ok": True}


@router.post("/runs/{run_id}/finish")
def finish(run_id: str, sid: str = Depends(require_student)) -> dict:
    return call(lambda: handsfree.finish(sid, run_id))


@router.get("/clip/{token}")
def clip(token: str, sid: str = Depends(require_student)) -> Response:
    """The cached audio of a question this server spoke for this student; never synthesises."""
    with _clips_lock:
        found = _clips.get(token)
    if not found or found[0] != sid or found[2] < time.time():
        raise HTTPException(404, "Not found.")
    sp = speech_router.get_cached_speech(found[1])
    if sp is None or not sp.audio:
        raise HTTPException(404, "Not found.")
    return Response(sp.audio, media_type=sp.mime_type, headers={"Cache-Control": "private"})
