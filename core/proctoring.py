"""Proctoring rules, shared by the API (server_proctor.py) and the Streamlit pages: which events
exist, which count as strikes, how strikes add up, and how an event reads for a person.

Fairness: only clear-cut events are strikes (switching tab or window, leaving fullscreen, a
second face, a phone). Soft signals (no face, looking away, out of frame, low light, the
camera) are kept "for review" and never strike or fail anyone: they misfire with glasses, a
disability, a poor camera, or someone looking away to think.

The server decides an event's severity from its kind; what a browser says about it is ignored.
Only events and times are stored, never video, images or landmarks. No Streamlit import here.
"""

import hashlib
import hmac
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Severity = Literal["clear", "review"]
Mode = Literal["off", "required", "seb"]
Kind = Literal["quiz", "interview"]

MAX_STRIKES = 3  # the third strike ends the attempt (the Streamlit guard's 3-strike rule)
STRIKE_MERGE_S = 3.0  # clear events this close together are one incident: one strike
MAX_EVENTS = 300  # per attempt
MAX_BATCH = 50  # per request
HEARTBEAT_GAP_S = 90.0  # no word from the page for longer: REPORTING_GAP (for review)
MAX_DURATION_S = 4 * 3600
MODES: tuple[Mode, ...] = ("off", "required", "seb")
KINDS: tuple[Kind, ...] = ("quiz", "interview")
CAMERA_STATES = ("on", "unavailable")
FLAG_PROCTOR_BREACH = "PROCTOR_BREACH"


@dataclass(frozen=True)
class EventType:
    code: str
    severity: Severity
    label: str  # how it reads for the student and the admin, e.g. "looked away"


CATALOGUE: dict[str, EventType] = {
    e.code: e
    for e in (
        EventType("TAB_HIDDEN", "clear", "switched to another tab or app"),
        EventType("WINDOW_BLUR", "clear", "the test window lost focus"),
        EventType("FULLSCREEN_EXIT", "clear", "left fullscreen"),
        EventType("SECOND_FACE", "clear", "a second face was seen"),
        EventType("PHONE_VISIBLE", "clear", "a phone was seen"),
        EventType("NO_FACE", "review", "no face in view"),
        EventType("LOOKED_AWAY", "review", "looked away"),
        EventType("OUT_OF_FRAME", "review", "moved out of the frame"),
        EventType("LOW_LIGHT", "review", "the lighting was too dark"),
        EventType("CAMERA_LOST", "review", "the camera stopped"),
        EventType("CAMERA_UNAVAILABLE", "review", "camera checks were skipped"),
        EventType("PASTE_BLOCKED", "review", "a paste was blocked"),
        EventType("REPORTING_GAP", "review", "the page stopped reporting"),
    )
}
CLIENT_KINDS = frozenset(CATALOGUE) - {"REPORTING_GAP"}  # that one only the server notices

CONSENT_TEXT = (
    "This test is proctored. While it runs, the app checks that you stay on this tab, in "
    "fullscreen, without copying or pasting, and (when you allow the camera) that one face is "
    "in view, no phone is visible, the lighting is adequate and you face the screen. The camera "
    "is analysed only inside your browser: no video, image or sound ever leaves your device. "
    "Only events and their times are stored, such as 'looked away 14s at 03:42'. Switching tab "
    "or window, leaving fullscreen, a second face or a phone are strikes, and 3 strikes submit "
    "the test. Everything else is only noted for a person to review and never fails you. You "
    "and your organization's admin can see the record; it is deleted with your account."
)


class ProctorRuleError(ValueError):
    """An event or setting the rules do not accept."""


def event_type(code: str) -> EventType:
    found = CATALOGUE.get(code)
    if found is None:
        raise ProctorRuleError("Unknown proctoring event.")
    return found


def mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return (
        f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
        if s >= 3600
        else f"{s // 60:02d}:{s % 60:02d}"
    )


def describe(code: str, at_s: float, duration_s: float | None = None) -> str:
    """ "looked away 14s at 03:42"."""
    label = event_type(code).label
    took = f" {int(duration_s)}s" if duration_s and duration_s >= 1 else ""
    return f"{label}{took} at {mmss(at_s)}"


@dataclass(frozen=True)
class Scored:
    """One incoming event after the rules: its severity and whether it is a new strike."""

    code: str
    severity: Severity
    at_s: float
    duration_s: float | None
    strike: bool


def score_events(
    events: Iterable[tuple[str, float, float | None]],
    *,
    strikes: int,
    last_clear_at: float | None,
    elapsed_s: float,
) -> tuple[list[Scored], int, float | None]:
    """Apply the rules to a batch of (code, at_s, duration_s), oldest first. A clear event is a
    strike unless another clear event came within STRIKE_MERGE_S before it (one incident), and
    none count after the MAX_STRIKES-th. Times are clamped to [0, elapsed + 5 s], so a page
    cannot place events in the future. Returns (scored, strikes, last_clear_at)."""
    out: list[Scored] = []
    clean = []
    for code, at_s, duration_s in events:
        t = event_type(code)
        at = min(max(0.0, float(at_s)), elapsed_s + 5.0)
        took = None if duration_s is None else min(max(0.0, float(duration_s)), MAX_DURATION_S)
        clean.append((t, at, took))
    for t, at, took in sorted(clean, key=lambda x: x[1]):
        strike = False
        if t.severity == "clear":
            fresh = last_clear_at is None or at - last_clear_at > STRIKE_MERGE_S
            if fresh and strikes < MAX_STRIKES:
                strikes += 1
                strike = True
            last_clear_at = at if last_clear_at is None else max(last_clear_at, at)
        out.append(Scored(t.code, t.severity, at, took, strike))
    return out, strikes, last_clear_at


def warning_for(strikes: int, latest: str | None) -> str | None:
    """What the student is told after a strike."""
    if strikes >= MAX_STRIKES:
        return f"{MAX_STRIKES} strikes: the test is being submitted."
    if strikes and latest:
        return f"Strike {strikes} of {MAX_STRIKES}: {event_type(latest).label}."
    return None


def telemetry_flags(clear_codes: Sequence[str], breached: bool) -> list[str]:
    """What goes into the telemetry proctor_flags: only clear-cut codes (and the breach), so a
    review signal can never read as a breach anywhere."""
    codes = [c for c in dict.fromkeys(clear_codes) if event_type(c).severity == "clear"]
    return codes + ([FLAG_PROCTOR_BREACH] if breached else [])


# --- Safe Exam Browser ----------------------------------------------------------------------

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEB_HEADER = "X-SafeExamBrowser-ConfigKeyHash"


def parse_seb_keys(text: str) -> list[str]:
    """Config Keys (64 hex characters each, from SEB's Config Tool), one per line or comma."""
    keys = [k.strip().lower() for k in re.split(r"[\s,]+", text or "") if k.strip()]
    bad = [k for k in keys if not _HEX64.match(k)]
    if bad:
        raise ProctorRuleError("A Config Key is 64 hexadecimal characters (from SEB Config Tool).")
    return list(dict.fromkeys(keys))


def public_url(app_url: str, path: str, query: str = "") -> str:
    """The address the browser (and so SEB) asked for: the public APP_URL with the request's
    path and query, never the internal address behind Render or the Next.js proxy."""
    url = app_url.rstrip("/") + "/" + path.lstrip("/")
    return f"{url}?{query}" if query else url


def seb_hash(url: str, config_key: str) -> str:
    """SEB's X-SafeExamBrowser-ConfigKeyHash: SHA-256 of the absolute URL (no fragment) followed
    by the Config Key, in lower-case hex."""
    return hashlib.sha256((url.split("#", 1)[0] + config_key).encode()).hexdigest()


def seb_ok(sent_hash: str | None, url: str, keys: Sequence[str]) -> bool:
    """True when the header matches one of the organization's Config Keys for this URL."""
    sent = (sent_hash or "").strip().lower()
    if not _HEX64.match(sent):
        return False
    return any(hmac.compare_digest(sent, seb_hash(url, k)) for k in keys)
