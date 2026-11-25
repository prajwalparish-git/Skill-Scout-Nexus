"""Proctoring over HTTP (piq/proctoring.py): the student's policy, starting an attempt after
consent, the page's event batches (also its heartbeat), finishing, and the student's own record.

Only event kinds and times are accepted: every body forbids extra fields, so no image, video or
landmark can be sent. In Safe Exam Browser mode each request must carry SEB's Config Key hash,
checked against the PUBLIC URL the browser asked for (APP_URL + path + query), not the address
this server sees behind Render or the Next.js proxy.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from core import proctoring as rules
from piq import proctoring
from piq.config import settings
from piq.services import ServiceError
from routers.auth import require_student, session_id

router = APIRouter(prefix="/api/proctor", tags=["proctoring"])

HEARTBEAT_S = 30
STARTS_MAX, STARTS_WINDOW_S = 30, 3600  # attempts a student may start per hour
_starts: dict[str, list[float]] = {}
_starts_lock = threading.Lock()


def start_throttle(sid: str = Depends(require_student)) -> str:
    now = time.monotonic()
    with _starts_lock:
        recent = [t for t in _starts.get(sid, []) if now - t < STARTS_WINDOW_S]
        if len(recent) >= STARTS_MAX:
            _starts[sid] = recent
            raise HTTPException(429, "Too many tests started. Try again later.")
        _starts[sid] = [*recent, now]
    return sid


def seb_proof(request: Request) -> proctoring.SebProof:
    """The SEB header and the public URL of this request."""
    return proctoring.SebProof(
        request.headers.get(rules.SEB_HEADER),
        rules.public_url(settings().app_url, request.url.path, request.url.query),
    )


def call[T](work: Callable[[], T]) -> T:
    """piq.proctoring's refusals as HTTP: 409 proctoring required, 403 not yours / no SEB."""
    try:
        return work()
    except proctoring.ProctorRequired as e:
        raise HTTPException(409, str(e)) from e
    except proctoring.ProctorForbidden as e:
        raise HTTPException(403, str(e)) from e
    except ServiceError as e:
        raise HTTPException(400, str(e)) from e


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRequest(Strict):
    kind: Literal["quiz", "interview"]
    label: str = Field("", max_length=proctoring.LABEL_MAX)
    camera: Literal["on", "unavailable"]
    camera_note: str = Field("", max_length=200)
    consent: bool


class Event(Strict):
    kind: str = Field(max_length=32)
    at_s: float = Field(ge=0, le=rules.MAX_DURATION_S)
    duration_s: float | None = Field(None, ge=0, le=rules.MAX_DURATION_S)


class EventBatch(Strict):
    events: list[Event] = Field(default_factory=list, max_length=rules.MAX_BATCH)


@router.get("/policy")
def policy(request: Request) -> dict:
    """What the student's tests require; guests get practice."""
    p = proctoring.policy(session_id(request))
    return {
        **asdict(p),
        "max_strikes": rules.MAX_STRIKES,
        "heartbeat_s": HEARTBEAT_S,
        "clear": sorted(k for k, t in rules.CATALOGUE.items() if t.severity == "clear"),
    }


@router.post("/attempts")
def start(body: StartRequest, request: Request, sid: str = Depends(start_throttle)) -> dict:
    attempt_id = call(
        lambda: proctoring.start(
            sid,
            body.kind,
            body.label,
            camera=body.camera,
            consent=body.consent,
            camera_note=body.camera_note,
            seb=seb_proof(request),
        )
    )
    return {"attempt_id": attempt_id, "strikes": 0, "max_strikes": rules.MAX_STRIKES}


@router.post("/attempts/{attempt_id}/events")
def events(
    attempt_id: str, body: EventBatch, request: Request, sid: str = Depends(require_student)
) -> dict:
    progress = call(
        lambda: proctoring.record(
            sid,
            attempt_id,
            [(e.kind, e.at_s, e.duration_s) for e in body.events],
            seb=seb_proof(request),
        )
    )
    return asdict(progress)


@router.post("/attempts/{attempt_id}/finish")
def finish(attempt_id: str, sid: str = Depends(require_student)) -> dict:
    call(lambda: proctoring.finish(sid, attempt_id))
    return asdict(call(lambda: proctoring.attempt(sid, attempt_id)))


@router.get("/attempts")
def mine(sid: str = Depends(require_student)) -> list[dict]:
    """The student's own proctoring record (the same their organization's admin sees)."""
    return [asdict(a) for a in proctoring.history(sid)]


@router.get("/attempts/{attempt_id}")
def one(attempt_id: str, sid: str = Depends(require_student)) -> dict:
    return asdict(call(lambda: proctoring.attempt(sid, attempt_id)))
