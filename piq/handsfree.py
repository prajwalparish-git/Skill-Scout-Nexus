"""Hands-free voice interviews: the same rules for every student, frozen onto each run when it
starts, enforced here (not only in the browser): how many spoken attempts a question gets, how
long an answer may be, and the answer format (16 kHz mono 16-bit WAV). Each answer's input
(voice, push-to-talk, typed) and the reason for any fallback are recorded; no audio is kept.

Used by server_handsfree.py and the interview turn route.
"""

import io
import json
import secrets
import struct
import time
import wave
from dataclasses import asdict, dataclass

from piq import db
from piq.config import (
    HANDSFREE_MAX_ANSWER_S,
    HANDSFREE_MAX_AUDIO_BYTES,
    HANDSFREE_NO_SPEECH_S,
    HANDSFREE_RETRIES,
    HANDSFREE_REVIEW_S,
    HANDSFREE_SAMPLE_RATE,
    HANDSFREE_SILENCE_S,
    HANDSFREE_THINK_S,
    HANDSFREE_TYPED_MAX_S,
    settings,
)
from piq.services import ServiceError

MAX_QUESTIONS = 20  # far above an interview's five: a bound for the index, not a rule
DURATION_GRACE_S = 2.0  # the browser stops at the max; encoding may add a moment
INPUTS = ("voice", "push_to_talk", "typed")
# Why a student answered other than hands-free (fixed texts: nothing free-form is stored).
REASONS = (
    "microphone unavailable",
    "microphone denied",
    "voice detection unavailable",
    "transcription unavailable",
    "no speech detected",
    "chose to type",
)
_now = time.time  # tests move the clock


class HandsfreeForbidden(ServiceError):
    """Not this student's run."""


class HandsfreeLimit(ServiceError):
    """A rule of the run says no (no attempts left, the run is over)."""


@dataclass(frozen=True)
class Rules:
    think_s: float
    max_answer_s: float
    silence_s: float
    retries: int
    review_s: float
    typed_max_s: float
    no_speech_s: float
    sample_rate: int


def rules() -> Rules:
    """The rules every student gets (piq/config.py)."""
    return Rules(
        think_s=HANDSFREE_THINK_S,
        max_answer_s=HANDSFREE_MAX_ANSWER_S,
        silence_s=HANDSFREE_SILENCE_S,
        retries=HANDSFREE_RETRIES,
        review_s=HANDSFREE_REVIEW_S,
        typed_max_s=HANDSFREE_TYPED_MAX_S,
        no_speech_s=HANDSFREE_NO_SPEECH_S,
        sample_rate=HANDSFREE_SAMPLE_RATE,
    )


@dataclass(frozen=True)
class Transcribed:
    text: str  # "" when no transcriber could (the student types instead)
    source: str
    retries_left: int
    fallback: str  # "transcription unavailable" when text is ""
    duration_s: float


def wav_duration(data: bytes, rule: Rules) -> float:
    """The answer's length in seconds, when it is a WAV in the run's format; ServiceError
    otherwise (another rate, stereo, compressed, or not a WAV at all)."""
    if len(data) > HANDSFREE_MAX_AUDIO_BYTES:
        raise ServiceError("That recording is too large.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            rate, channels, width, frames = (
                w.getframerate(),
                w.getnchannels(),
                w.getsampwidth(),
                w.getnframes(),
            )
            comp = w.getcomptype()
    except (wave.Error, EOFError, RuntimeError, ValueError, struct.error) as e:
        # a malformed or truncated file: the wave module raises any of these
        raise ServiceError("Send the answer as a WAV recording.") from e
    if comp != "NONE" or rate != rule.sample_rate or channels != 1 or width != 2:
        raise ServiceError(
            f"Answers must be {rule.sample_rate // 1000} kHz mono 16-bit WAV "
            f"(this one is {rate} Hz, {channels} channel(s), {width * 8}-bit)."
        )
    seconds = frames / rate
    if seconds > rule.max_answer_s + DURATION_GRACE_S:
        raise ServiceError(f"An answer can be at most {int(rule.max_answer_s)} seconds.")
    return round(seconds, 2)


def start(student_id: str) -> tuple[str, Rules]:
    """A new run with today's rules frozen onto it."""
    run_id = secrets.token_urlsafe(18)
    r = rules()
    db.create_handsfree_run(run_id, student_id, json.dumps(asdict(r)), _now())
    return run_id, r


def _own(student_id: str, run_id: str):
    row = db.handsfree_run(run_id) if run_id else None
    if row is None or row["student_id"] != student_id:
        raise HandsfreeForbidden("That hands-free interview is not yours.")
    return row


def run_rules(row) -> Rules:
    return Rules(**json.loads(row["rules_json"]))


def _check_index(question_index: int) -> None:
    if not 0 <= question_index < MAX_QUESTIONS:
        raise ServiceError("Unknown question.")


def _spoken_attempts(run_id: str, question_index: int) -> int:
    return sum(
        1
        for a in db.handsfree_answers(run_id)
        if a["question_index"] == question_index and a["input"] != "typed"
    )


def _transcribe(audio: bytes) -> tuple[str, str]:
    """(text, source): the canned answer in mock mode, else core/transcribe_router.py."""
    if settings().mock_mode:
        from agents.rubric_evaluator_agent import transcribe_audio_with_whisper

        return transcribe_audio_with_whisper(audio, "answer.wav"), "mock"
    from core import transcribe_router

    t = transcribe_router.transcribe(audio, "answer.wav")
    return t.text, t.source


def transcribe(
    student_id: str,
    run_id: str,
    question_index: int,
    attempt_no: int,
    audio: bytes,
    *,
    input_mode: str = "voice",
) -> Transcribed:
    """Transcribe one spoken attempt, within the run's rules: attempt 1, then at most
    `retries` more, in order; the format and length checked."""
    row = _own(student_id, run_id)
    r = run_rules(row)
    _check_index(question_index)
    if row["ended_at"] is not None:
        raise HandsfreeLimit("This hands-free interview is over.")
    if input_mode not in ("voice", "push_to_talk"):
        raise ServiceError("Unknown way of answering.")
    used = _spoken_attempts(run_id, question_index)
    if attempt_no != used + 1 or attempt_no > 1 + r.retries:
        raise HandsfreeLimit(
            "No spoken attempts left for this question."
            if used >= 1 + r.retries
            else "Answer attempts go in order."
        )
    seconds = wav_duration(audio, r)
    text, source = _transcribe(audio)
    text = " ".join(text.split())
    fallback = "" if text else "transcription unavailable"
    db.add_handsfree_answer(
        run_id, question_index, attempt_no, input_mode, fallback, seconds, source, _now()
    )
    return Transcribed(text, source, 1 + r.retries - attempt_no, fallback, seconds)


def note(student_id: str, run_id: str, question_index: int, input_mode: str, reason: str) -> None:
    """Record that a question was answered by push-to-talk or typing, and why."""
    row = _own(student_id, run_id)
    _check_index(question_index)
    if input_mode not in ("push_to_talk", "typed"):
        raise ServiceError("Unknown way of answering.")
    if reason not in REASONS:
        raise ServiceError("Unknown reason.")
    if row["ended_at"] is not None:
        raise HandsfreeLimit("This hands-free interview is over.")
    db.add_handsfree_answer(run_id, question_index, 0, input_mode, reason, None, "", _now())


def link(student_id: str, run_id: str, session_id: str) -> None:
    _own(student_id, run_id)
    db.link_handsfree_run(run_id, session_id)


def finish(student_id: str, run_id: str) -> dict:
    """End the run; how the questions were answered."""
    _own(student_id, run_id)
    db.end_handsfree_run(run_id, _now())
    return summary(run_id)


def summary(run_id: str) -> dict:
    """Per question the way it was finally answered: {voice, push_to_talk, typed, reasons}."""
    last: dict[int, tuple[str, str]] = {}
    for a in db.handsfree_answers(run_id):
        last[a["question_index"]] = (a["input"], a["fallback_reason"])
    counts = {k: 0 for k in INPUTS}
    reasons: list[str] = []
    for mode, reason in last.values():
        counts[mode] += 1
        if reason:
            reasons.append(reason)
    return {**counts, "reasons": sorted(set(reasons))}
