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
2. 3-Strike Rule:
   - When strikes >= 3, sets PROCTOR_BREACH flag.
   - Persists PROCTOR_BREACH to database via database/crud.py (QuizAttempt or voice session).
   - Force-submits the test.
3. Clean warning banners displayed in Streamlit UI.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import streamlit as st
import streamlit.components.v1 as components

from database import crud
from database.connection import DatabaseManager

log = logging.getLogger("core.proctor_guard")

MAX_PROCTOR_STRIKES = 3
FLAG_TAB_SWITCH = "TAB_SWITCH"
FLAG_WINDOW_BLUR = "WINDOW_BLUR"
FLAG_CAMERA_ABSENT = "CAMERA_ABSENT"
FLAG_PROCTOR_BREACH = "PROCTOR_BREACH"

# Session state keys
STRIKES_KEY = "proctor_strikes"
WARNING_KEY = "proctor_warning"
FLAGS_KEY = "proctor_flags"
BREACH_KEY = "proctor_breached"
EVENTS_KEY = "proctor_processed_events"

_fallback_state: dict[str, Any] = {
    STRIKES_KEY: 0,
    WARNING_KEY: None,
    FLAGS_KEY: [],
    BREACH_KEY: False,
    EVENTS_KEY: set(),
}


def _state_get(key: str, default: Any = None) -> Any:
    try:
        if key in st.session_state:
            return st.session_state[key]
    except Exception:
        pass
    return _fallback_state.get(key, default)


def _state_set(key: str, value: Any) -> None:
    _fallback_state[key] = value
    with contextlib.suppress(Exception):
        st.session_state[key] = value


@dataclass(frozen=True)
class ProctorGuardStatus:
    strikes: int
    is_breached: bool
    warning: str | None
    flags: list[str] = field(default_factory=list)


def init_proctor_state() -> None:
    """Initialize proctor state in Streamlit session_state if not present."""
    if _state_get(STRIKES_KEY) is None:
        _state_set(STRIKES_KEY, 0)
    if _state_get(FLAGS_KEY) is None:
        _state_set(FLAGS_KEY, [])
    if _state_get(BREACH_KEY) is None:
        _state_set(BREACH_KEY, False)
    if _state_get(EVENTS_KEY) is None:
        _state_set(EVENTS_KEY, set())


def reset_proctor_state() -> None:
    """Reset proctor strikes, flags, and warnings for a new test."""
    _state_set(STRIKES_KEY, 0)
    _state_set(WARNING_KEY, None)
    _state_set(FLAGS_KEY, [])
    _state_set(BREACH_KEY, False)
    _state_set(EVENTS_KEY, set())


def get_strikes() -> int:
    return int(_state_get(STRIKES_KEY, 0))


def is_breached() -> bool:
    return bool(_state_get(BREACH_KEY, False) or get_strikes() >= MAX_PROCTOR_STRIKES)


def get_warning() -> str | None:
    return _state_get(WARNING_KEY)


def get_proctor_flags() -> list[str]:
    return list(_state_get(FLAGS_KEY, []))


get_flags = get_proctor_flags  # Alias


def record_strike(reason: str = FLAG_TAB_SWITCH, detail: str = "") -> int:
    """Increment strike counter, add flag, and check 3-strike breach condition."""
    init_proctor_state()
    cur_strikes = get_strikes() + 1
    _state_set(STRIKES_KEY, cur_strikes)

    flags = get_proctor_flags()
    if reason not in flags:
        flags.append(reason)
        _state_set(FLAGS_KEY, flags)

    if cur_strikes >= MAX_PROCTOR_STRIKES:
        _state_set(BREACH_KEY, True)
        if FLAG_PROCTOR_BREACH not in flags:
            flags.append(FLAG_PROCTOR_BREACH)
            _state_set(FLAGS_KEY, flags)
        _state_set(
            WARNING_KEY,
            f"3 strikes reached ({reason}). Assessment force-submitted due to proctor breach.",
        )
    else:
        desc = f" ({detail})" if detail else ""
        _state_set(
            WARNING_KEY,
            f"Proctoring warning: {reason}{desc}. Strike {cur_strikes}/{MAX_PROCTOR_STRIKES}.",
        )
    return cur_strikes


def record_camera_warning(detail: str = "Webcam absent or black/static for >5s") -> None:
    """Record a camera absence warning without necessarily triggering an immediate strike."""
    init_proctor_state()
    flags = get_proctor_flags()
    if FLAG_CAMERA_ABSENT not in flags:
        flags.append(FLAG_CAMERA_ABSENT)
        _state_set(FLAGS_KEY, flags)
    _state_set(WARNING_KEY, f"CAMERA_ABSENT: {detail}. Please ensure your face is visible.")


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
    init_proctor_state()

    # Process query param events if sent by the JS component
    raw_event = st.query_params.get("proctor_event")
    if raw_event:
        processed = st.session_state[EVENTS_KEY]
        if raw_event not in processed:
            processed.add(raw_event)
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
