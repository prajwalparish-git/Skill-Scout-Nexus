"""Proctored attempts (core/proctoring.py's rules applied): what a student's organization
requires, starting an attempt after consent (in Safe Exam Browser when required), recording the
page's events, finishing, and the record the student and their admin can read.

Used by routers/proctor.py, the quiz and interview routes, and frontend assessments alike.
"""

import secrets
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core import proctoring as rules
from piq import db
from piq.services import ServiceError

LABEL_MAX = 120
_now = time.time  # tests move the clock


class ProctorRequired(ServiceError):
    """The organization requires proctoring and this request has no live attempt."""


class ProctorForbidden(ServiceError):
    """Not this student's attempt, or Safe Exam Browser is required and not proven."""


@dataclass(frozen=True)
class Policy:
    mode: str  # practice | required | seb
    required: bool
    seb: bool
    consent_text: str = rules.CONSENT_TEXT


@dataclass(frozen=True)
class SebProof:
    """What the request carried: the X-SafeExamBrowser-ConfigKeyHash header and the public URL
    the browser asked for (core.proctoring.public_url)."""

    header: str | None
    url: str


@dataclass(frozen=True)
class EventView:
    kind: str
    severity: str  # clear | review
    strike: bool
    at_s: float
    duration_s: float | None
    text: str  # "looked away 14s at 03:42"


@dataclass(frozen=True)
class AttemptView:
    id: str
    kind: str
    label: str
    mode: str
    camera: str
    camera_note: str
    started: str  # ISO, UTC
    duration_s: float
    strikes: int
    breached: bool
    finished: bool
    clear: list[EventView] = field(default_factory=list)
    review: list[EventView] = field(default_factory=list)


@dataclass(frozen=True)
class Progress:
    strikes: int
    breached: bool
    warning: str | None


def policy(student_id: str | None) -> Policy:
    """Practice unless the student's organization requires proctoring (guests: practice)."""
    row = db.student(student_id) if student_id else None
    mode, _ = db.organization_proctoring(row["org_id"] if row else None)
    if mode == "seb":
        return Policy("seb", True, True)
    if mode == "required":
        return Policy("required", True, False)
    return Policy("practice", False, False)


def _check_seb(student_id: str, proof: SebProof | None) -> None:
    row = db.student(student_id)
    _, keys = db.organization_proctoring(row["org_id"] if row else None)
    parsed = rules.parse_seb_keys(keys)
    if not parsed or proof is None or not rules.seb_ok(proof.header, proof.url, parsed):
        raise ProctorForbidden(
            "Your organization requires Safe Exam Browser for tests. Open this test with the "
            ".seb file your organization gave you."
        )


def start(
    student_id: str,
    kind: str,
    label: str,
    *,
    camera: str,
    consent: bool,
    camera_note: str = "",
    seb: SebProof | None = None,
) -> str:
    """A new attempt's id, after consent (and, when required, Safe Exam Browser)."""
    if kind not in rules.KINDS:
        raise ServiceError("Unknown kind of test.")
    if camera not in rules.CAMERA_STATES:
        raise ServiceError("Unknown camera state.")
    if not consent:
        raise ServiceError("Read and accept what the proctoring checks before you start.")
    p = policy(student_id)
    if p.seb:
        _check_seb(student_id, seb)
    attempt_id = secrets.token_urlsafe(18)
    now = _now()
    note = camera_note.strip()[:200] if camera == "unavailable" else ""
    db.create_proctor_attempt(
        attempt_id,
        student_id,
        kind,
        " ".join(label.split())[:LABEL_MAX] or kind,
        p.mode,
        camera,
        note,
        now,
    )
    if camera == "unavailable":
        db.record_proctor_events(
            attempt_id,
            [("CAMERA_UNAVAILABLE", "review", False, 0.0, None)],
            strikes=0,
            last_clear_at=None,
            breached=False,
            now=now,
        )
    return attempt_id


def _own(student_id: str, attempt_id: str):
    row = db.proctor_attempt(attempt_id) if attempt_id else None
    if row is None or row["student_id"] != student_id:
        raise ProctorForbidden("That proctored attempt is not yours.")
    return row


def record(
    student_id: str,
    attempt_id: str,
    events: Iterable[tuple[str, float, float | None]],
    *,
    seb: SebProof | None = None,
    check_gap: bool = True,
) -> Progress:
    """Store a batch of the page's events (an empty batch is a heartbeat) and return the
    strikes so far. The server decides severity and strikes; review events never strike."""
    row = _own(student_id, attempt_id)
    if row["mode"] == "seb":
        _check_seb(student_id, seb)
    batch = list(events)
    if len(batch) > rules.MAX_BATCH:
        raise ServiceError("Too many events at once.")
    if any(code not in rules.CLIENT_KINDS for code, _, _ in batch):
        raise ServiceError("Unknown proctoring event.")
    now = _now()
    elapsed = now - row["started_at"]
    if row["ended_at"] is not None:  # a late beacon after submit: kept out, never an error
        return Progress(row["strikes"], bool(row["breached"]), None)
    gap = now - row["last_seen"]
    if check_gap and gap > rules.HEARTBEAT_GAP_S:
        batch.append(("REPORTING_GAP", row["last_seen"] - row["started_at"], gap))
    if db.proctor_event_count(attempt_id) + len(batch) > rules.MAX_EVENTS:
        raise ServiceError("This attempt has recorded as many events as it can.")
    try:
        scored, strikes, last_clear = rules.score_events(
            batch, strikes=row["strikes"], last_clear_at=row["last_clear_at"], elapsed_s=elapsed
        )
    except rules.ProctorRuleError as e:
        raise ServiceError(str(e)) from e
    breached = bool(row["breached"]) or strikes >= rules.MAX_STRIKES
    db.record_proctor_events(
        attempt_id,
        [(s.code, s.severity, s.strike, s.at_s, s.duration_s) for s in scored],
        strikes=strikes,
        last_clear_at=last_clear,
        breached=breached,
        now=now,
    )
    latest = next((s.code for s in reversed(scored) if s.strike), None)
    return Progress(strikes, breached, rules.warning_for(strikes, latest))


def require(student_id: str | None, attempt_id: str | None, kind: str):
    """For a quiz submit or interview turn: the live attempt it names, checked; None when there
    is none and the organization does not require one (practice)."""
    if not student_id:
        return None
    if not attempt_id:
        if policy(student_id).required:
            raise ProctorRequired("This test is proctored: start it from the proctoring check.")
        return None
    row = _own(student_id, attempt_id)
    if row["kind"] != kind:
        raise ProctorForbidden("That proctored attempt is for another kind of test.")
    if row["ended_at"] is not None and policy(student_id).required:
        raise ProctorRequired("That proctored attempt is over. Start the test again.")
    return row


def finish(
    student_id: str,
    attempt_id: str,
    *,
    quiz_run_id: int | None = None,
    interview_session_id: str | None = None,
) -> list[str]:
    """End the attempt, link what it proctored, and return its telemetry flags (clear-cut codes
    and PROCTOR_BREACH only)."""
    _own(student_id, attempt_id)
    db.finish_proctor_attempt(
        attempt_id, _now(), quiz_run_id=quiz_run_id, interview_session_id=interview_session_id
    )
    return flags(attempt_id)


def flags(attempt_id: str) -> list[str]:
    row = db.proctor_attempt(attempt_id)
    if row is None:
        return []
    clear = [e["kind"] for e in db.proctor_events(attempt_id) if e["severity"] == "clear"]
    return rules.telemetry_flags(clear, bool(row["breached"]))


def _view(row) -> AttemptView:
    events = [
        EventView(
            e["kind"],
            e["severity"],
            bool(e["strike"]),
            e["at_s"],
            e["duration_s"],
            rules.describe(e["kind"], e["at_s"], e["duration_s"]),
        )
        for e in db.proctor_events(row["id"])
    ]
    end = row["ended_at"] or row["last_seen"]
    return AttemptView(
        id=row["id"],
        kind=row["kind"],
        label=row["label"],
        mode=row["mode"],
        camera=row["camera"],
        camera_note=row["camera_note"],
        started=datetime.fromtimestamp(row["started_at"], UTC).isoformat(timespec="seconds"),
        duration_s=round(max(0.0, end - row["started_at"]), 1),
        strikes=row["strikes"],
        breached=bool(row["breached"]),
        finished=row["ended_at"] is not None,
        clear=[e for e in events if e.severity == "clear"],
        review=[e for e in events if e.severity == "review"],
    )


def history(student_id: str, limit: int = 50) -> list[AttemptView]:
    """The student's proctored attempts, newest first, events split into clear and review."""
    return [_view(r) for r in db.proctor_attempts(student_id, limit)]


def attempt(student_id: str, attempt_id: str) -> AttemptView:
    return _view(_own(student_id, attempt_id))


def set_org_mode(org_id: int, mode: str, seb_config_keys: str = "") -> None:
    """The organization's setting: off, required, or required in Safe Exam Browser (which needs
    at least one Config Key)."""
    if mode not in rules.MODES:
        raise ServiceError("Choose off, required, or required with Safe Exam Browser.")
    try:
        keys = rules.parse_seb_keys(seb_config_keys)
    except rules.ProctorRuleError as e:
        raise ServiceError(str(e)) from e
    if mode == "seb" and not keys:
        raise ServiceError("Add the Config Key of your Safe Exam Browser file first.")
    db.set_organization_proctoring(org_id, mode, "\n".join(keys))


def telemetry_for(attempts: Sequence[str]) -> list[str]:
    """Telemetry flags for several attempts together (an interview with several turns)."""
    out: list[str] = []
    for a in attempts:
        out.extend(flags(a))
    return list(dict.fromkeys(out))
