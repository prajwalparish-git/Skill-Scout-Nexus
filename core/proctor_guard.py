"""Live Webcam & Strict Tab-Switch Proctoring Guard for Skill Scout Nexus.

Responsibilities:
1. Streamlit HTML/JS component (st.components.v1.html):
   - Injects hidden proctoring script into the browser for Quiz and Voice Interview pages.
   - Tab-Switch & Window Blur: Listens to visibilitychange and window.onblur.
     Triggers a loud JS AudioContext beep (880Hz) and increments strike counter in session_state.
   - Copy/Paste Lock: Disables contextmenu (right-click), copy, cut, paste, and dragstart
     on both current iframe and parent window document.
   - Webcam Presence Check: Requests navigator.mediaDevices.getUserMedia({video: true}).
     Draws frames to a hidden canvas every 3s. Checks average brightness and motion.
     If camera is completely black or static for >5 seconds, triggers a CAMERA_ABSENT warning.
2. 3-Strike Rule (ProctorState: clean -> warned -> breached, one object per session):
   - The third strike adds the PROCTOR_BREACH flag.
   - Persists PROCTOR_BREACH to database via database/crud.py (QuizAttempt or voice session).
   - Force-submits the test.
3. Clean warning banners displayed in Streamlit UI.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import streamlit as st
import streamlit.components.v1 as components
from streamlit.runtime.scriptrunner import get_script_run_ctx

from database import crud
from database.connection import DatabaseManager

log = logging.getLogger("core.proctor_guard")

MAX_PROCTOR_STRIKES = 3
FLAG_TAB_SWITCH = "TAB_SWITCH"
FLAG_WINDOW_BLUR = "WINDOW_BLUR"
FLAG_CAMERA_ABSENT = "CAMERA_ABSENT"
FLAG_PROCTOR_BREACH = "PROCTOR_BREACH"

STATE_KEY = "proctor_state"  # the session's ProctorState (piq.ui.PER_STUDENT_KEYS)

Phase = Literal["clean", "warned", "breached"]


@dataclass(frozen=True)
class ProctorState:
    """One assessment's proctoring, as an explicit state machine.

    clean --strike / camera notice--> warned --strike #MAX_PROCTOR_STRIKES--> breached
    Any phase --reset_proctor_state()--> clean. "Breached" is derived from the strike count,
    so a breach without its strikes (or the reverse) cannot be represented.
    """

    strikes: int = 0
    flags: tuple[str, ...] = ()  # first-seen order, no repeats
    warning: str | None = None
    seen_events: frozenset[str] = frozenset()  # query-param events already counted

    @property
    def phase(self) -> Phase:
        if self.strikes >= MAX_PROCTOR_STRIKES:
            return "breached"
        return "warned" if self.strikes or self.warning else "clean"

    def _flagged(self, *new: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*self.flags, *new]))

    def with_strike(self, reason: str, detail: str = "") -> ProctorState:
        strikes = self.strikes + 1
        if strikes >= MAX_PROCTOR_STRIKES:
            return replace(
                self,
                strikes=strikes,
                flags=self._flagged(reason, FLAG_PROCTOR_BREACH),
                warning=(
                    f"3 strikes reached ({reason}). Assessment force-submitted due to proctor "
                    "breach."
                ),
            )
        desc = f" ({detail})" if detail else ""
        return replace(
            self,
            strikes=strikes,
            flags=self._flagged(reason),
            warning=(
                f"Proctoring warning: {reason}{desc}. Strike {strikes}/{MAX_PROCTOR_STRIKES}."
            ),
        )

    def with_camera_warning(self, detail: str) -> ProctorState:
        """A camera notice: flagged and shown, but not a strike."""
        return replace(
            self,
            flags=self._flagged(FLAG_CAMERA_ABSENT),
            warning=f"CAMERA_ABSENT: {detail}. Please ensure your face is visible.",
        )

    def with_event_seen(self, event: str) -> ProctorState:
        return replace(self, seen_events=self.seen_events | {event})


# Only for bare mode (no Streamlit session: plain unit tests and scripts). A real session
# always keeps its own state in st.session_state, so one student's strikes can never reach
# another session through this module.
_bare_state = ProctorState()


def _in_session() -> bool:
    return get_script_run_ctx(suppress_warning=True) is not None


def _load() -> ProctorState:
    if _in_session():
        state = st.session_state.get(STATE_KEY)
        return state if isinstance(state, ProctorState) else ProctorState()
    return _bare_state


def _save(state: ProctorState) -> ProctorState:
    global _bare_state
    if _in_session():
        st.session_state[STATE_KEY] = state
    else:
        _bare_state = state
    return state


@dataclass(frozen=True)
class ProctorGuardStatus:
    strikes: int
    is_breached: bool
    warning: str | None
    flags: list[str] = field(default_factory=list)


def proctor_state() -> ProctorState:
    """This session's proctoring state (clean until the first strike or notice)."""
    return _load()


def init_proctor_state() -> None:
    """Start this session's proctoring state if it has none (a no-op otherwise)."""
    _save(_load())


def reset_proctor_state() -> None:
    """Reset proctor strikes, flags, and warnings for a new test."""
    _save(ProctorState())


def get_strikes() -> int:
    return _load().strikes


def is_breached() -> bool:
    return _load().phase == "breached"


def get_warning() -> str | None:
    return _load().warning


def get_proctor_flags() -> list[str]:
    return list(_load().flags)


get_flags = get_proctor_flags  # Alias


def record_strike(reason: str = FLAG_TAB_SWITCH, detail: str = "") -> int:
    """Count one strike; the MAX_PROCTOR_STRIKES-th one breaches. Returns the strike count."""
    return _save(_load().with_strike(reason, detail)).strikes


def record_camera_warning(detail: str = "Webcam absent or black/static for >5s") -> None:
    """Record a camera absence warning without triggering a strike."""
    _save(_load().with_camera_warning(detail))


def save_proctor_breach_to_db(
    student_id: int,
    assessment_type: Literal["quiz", "critic_quiz", "voice"],
    *,
    stream: str = "Engineering",
    domain: str = "General",
    score: int = 0,
    total: int = 5,
    role: str = "Candidate",
    db: DatabaseManager | None = None,
) -> Any:
    """Push PROCTOR_BREACH flag directly to the database (QuizAttempt or VoiceInterviewSession)."""
    flags = list(dict.fromkeys([*get_proctor_flags(), FLAG_PROCTOR_BREACH]))
    if assessment_type in ("quiz", "critic_quiz"):
        return crud.save_quiz_attempt(
            student_id=student_id,
            stream=stream,
            domain=domain,
            score=score,
            total_questions=total,
            critique_notes=("[TEST TERMINATED: Force-submitted due to 3 strikes / PROCTOR_BREACH]"),
            proctor_flags=flags,
            db=db,
        )
    else:
        return crud.save_voice_session(
            student_id=student_id,
            role=role,
            audio_transcript="[TEST TERMINATED: Force-submitted due to PROCTOR_BREACH]",
            rubric_score=0,
            verbal_clarity_score=0.0,
            relevance_score=0.0,
            feedback=(
                "Assessment terminated prematurely due to repeated proctoring violations "
                "(PROCTOR_BREACH)."
            ),
            proctor_flags=flags,
            db=db,
        )


def proctor_html_component(page_type: str = "assessment") -> str:
    """Generate self-contained HTML/JS proctoring guard."""
    template = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { margin: 0; padding: 0; overflow: hidden; background: transparent; }
  #proctor-video, #proctor-canvas { display: none; }
</style>
</head>
<body>
<video id="proctor-video" autoplay playsinline muted></video>
<canvas id="proctor-canvas" width="64" height="48"></canvas>
<script>
(function() {
  const pageType = __PAGE_TYPE__;
  const targets = [document];
  const winTargets = [window];
  try {
    if (window.parent && window.parent.document) {
      targets.push(window.parent.document);
      winTargets.push(window.parent);
    }
  } catch(e) {
    console.warn("[ProctorGuard] Parent document cross-origin restricted:", e);
  }

  // --- 1. AudioContext Beep ---
  function playBeep() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(880, ctx.currentTime); // 880 Hz loud beep
      gain.gain.setValueAtTime(0.5, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.55);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.6);
    } catch(err) {
      console.warn("[ProctorGuard] AudioContext beep error:", err);
    }
  }

  // --- 2. Report Violation to Parent URL & postMessage ---
  let lastReported = 0;
  function reportViolation(type, detail) {
    const now = Date.now();
    if (now - lastReported < 1500) return; // Debounce rapid bursts
    lastReported = now;

    playBeep();

    try {
      if (window.parent) {
        window.parent.postMessage({
          type: "PROCTOR_VIOLATION",
          event: type,
          detail: detail,
          timestamp: now
        }, "*");

        const parentUrl = new URL(window.parent.location.href);
        const curStrikes = parseInt(parentUrl.searchParams.get("proctor_strikes") || "0", 10);
        let nextStrikes = curStrikes;
        if (type === "TAB_SWITCH" || type === "WINDOW_BLUR") {
          nextStrikes += 1;
        }
        parentUrl.searchParams.set("proctor_event", type + ":" + now);
        parentUrl.searchParams.set("proctor_strikes", nextStrikes.toString());
        if (parentUrl.href !== window.parent.location.href) {
          window.parent.location.href = parentUrl.href;
        }
      }
    } catch(err) {
      console.error("[ProctorGuard] Reporting error:", err);
    }
  }

  // --- 3. Copy / Paste / ContextMenu Lock ---
  function blockEvent(e) {
    e.preventDefault();
    e.stopPropagation();
    return false;
  }
  targets.forEach(doc => {
    ["contextmenu", "copy", "cut", "paste", "dragstart"].forEach(evtName => {
      doc.addEventListener(evtName, blockEvent, true);
    });
  });

  // --- 4. Tab-Switch & Window Blur Listeners ---
  targets.forEach(doc => {
    doc.addEventListener("visibilitychange", function() {
      if (doc.visibilityState === "hidden") {
        reportViolation("TAB_SWITCH", "Tab switched or browser minimized");
      }
    }, true);
  });

  winTargets.forEach(win => {
    win.addEventListener("blur", function() {
      reportViolation("WINDOW_BLUR", "Browser window lost focus");
    }, true);
  });

  // --- 5. Webcam Presence Check ---
  const video = document.getElementById("proctor-video");
  const canvas = document.getElementById("proctor-canvas");
  const ctx = canvas ? canvas.getContext("2d") : null;
  let streamReady = false;
  let prevFrame = null;
  let inactiveDuration = 0;
  const CHECK_MS = 3000;

  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    navigator.mediaDevices.getUserMedia({ video: { width: 120, height: 90 } })
      .then(stream => {
        video.srcObject = stream;
        video.play().catch(e => console.warn("Video play error:", e));
        streamReady = true;
      })
      .catch(err => {
        console.warn("[ProctorGuard] Camera permission denied or device absent:", err);
        reportViolation("CAMERA_ABSENT", "Webcam access denied or unavailable");
      });
  } else {
    reportViolation("CAMERA_ABSENT", "navigator.mediaDevices not supported");
  }

  if (ctx) {
    setInterval(function() {
      if (!streamReady || video.readyState < 2) {
        inactiveDuration += CHECK_MS;
        if (inactiveDuration >= 5000) {
          reportViolation("CAMERA_ABSENT", "Webcam stream absent or not ready");
        }
        return;
      }

      try {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const d = img.data;
        let sumBrightness = 0;
        let diffMotion = 0;
        const count = d.length / 4;

        for (let i = 0; i < d.length; i += 4) {
          const r = d[i], g = d[i+1], b = d[i+2];
          sumBrightness += (r + g + b) / 3;
          if (prevFrame) {
            diffMotion += Math.abs(r - prevFrame[i]);
            diffMotion += Math.abs(g - prevFrame[i+1]);
            diffMotion += Math.abs(b - prevFrame[i+2]);
          }
        }

        const avgBrightness = sumBrightness / count;
        const avgMotion = prevFrame ? (diffMotion / (count * 3)) : 10;
        prevFrame = new Uint8ClampedArray(d);

        // Heuristic: pitch black (< 12) or frozen static (< 0.4 difference)
        const isDead = (avgBrightness < 12) || (prevFrame && avgMotion < 0.4);
        if (isDead) {
          inactiveDuration += CHECK_MS;
        } else {
          inactiveDuration = 0;
        }

        if (inactiveDuration >= 5000) {
          reportViolation("CAMERA_ABSENT", "Webcam black or static for >5s");
        }
      } catch(e) {
        console.warn("[ProctorGuard] Analysis error:", e);
      }
    }, CHECK_MS);
  }
})();
</script>
</body>
</html>"""
    return template.replace("__PAGE_TYPE__", json.dumps(page_type))


def render_proctor_guard(
    page_type: str = "assessment",
    on_breach: Callable[[], None] | None = None,
) -> ProctorGuardStatus:
    """Inject hidden proctoring script, read incoming strike events, and handle breach callbacks."""
    # Process query param events if sent by the JS component (each one counts once)
    raw_event = st.query_params.get("proctor_event")
    if raw_event and raw_event not in _load().seen_events:
        _save(_load().with_event_seen(raw_event))
        event_type = raw_event.split(":")[0] if ":" in raw_event else raw_event
        if event_type in (FLAG_TAB_SWITCH, FLAG_WINDOW_BLUR):
            record_strike(event_type, "Tab switched or window blur detected")
        elif event_type == FLAG_CAMERA_ABSENT:
            record_camera_warning("Webcam feed is inactive, black, or static")
        with contextlib.suppress(Exception):
            del st.query_params["proctor_event"]

    # Check 3-strike rule
    if is_breached() and on_breach:
        on_breach()

    # Inject invisible iframe component (0 height, 0 width)
    components.html(proctor_html_component(page_type), height=0, width=0)

    return ProctorGuardStatus(
        strikes=get_strikes(),
        is_breached=is_breached(),
        warning=get_warning(),
        flags=get_proctor_flags(),
    )


def render_warning_banner() -> None:
    """Display a clean Streamlit warning banner for strikes, camera warnings, or proctor breach."""
    if is_breached():
        st.error(
            "🚨 **PROCTOR BREACH:** Maximum strikes reached (3/3). This assessment has been "
            "flagged and force-submitted.",
            icon=":material/gavel:",
        )
    elif get_strikes() > 0:
        strikes = get_strikes()
        st.warning(
            f"⚠️ **PROCTOR WARNING:** Strike {strikes}/{MAX_PROCTOR_STRIKES} recorded. "
            "Tab-switching, minimizing the window, or losing focus is strictly prohibited. "
            "3 strikes will automatically submit your assessment.",
            icon=":material/warning:",
        )
    elif warning := get_warning():
        st.warning(f"⚠️ **PROCTOR NOTICE:** {warning}", icon=":material/videocam_off:")
