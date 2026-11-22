"""Proctoring in the Streamlit app: the same fair rules and records as the web app
(core/proctoring.py, piq/proctoring.py), with a two-way component (st.components.v2).

Before a proctored quiz or interview the component shows a pre-check (consent text, a local
camera preview, a lighting hint) and a "Start in fullscreen" button. While the test runs it
reports, without reloading the page:
- clear-cut strikes: switching tab, the window losing focus for 2 s or more, leaving fullscreen;
- for review only: low light and a stopped camera (today's brightness/motion check), and
  blocked pastes. The face/phone checks (MediaPipe) run in the web app only.

The server decides severity and strikes; the third strike breaches, and the page then submits.
No video or image leaves the browser. Practice tests are proctored only when the student opts
in; an organization can require it. Safe Exam Browser mode is for the web app.

(The guard this replaces reported through `window.parent.location`, which Streamlit's component
sandbox blocks, so its strikes were never recorded; and it counted any blur as a strike.)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import streamlit as st

from core import proctoring as rules
from piq import formatter, proctoring
from piq.services import ServiceError

MAX_PROCTOR_STRIKES = rules.MAX_STRIKES
FLAG_PROCTOR_BREACH = rules.FLAG_PROCTOR_BREACH
STATE_KEY = "proctor_state"  # {test key: attempt state}; cleared on sign-out (piq.ui)

Kind = Literal["quiz", "interview"]


@dataclass(frozen=True)
class Guard:
    """The open test's proctoring: inactive for an unproctored practice test."""

    active: bool
    attempt_id: str | None = None
    strikes: int = 0
    breached: bool = False
    warning: str | None = None


_ASSETS = Path(__file__).with_name("proctor_assets")  # the component's HTML, CSS and JS


def _asset(name: str) -> str:
    return (_ASSETS / name).read_text(encoding="utf-8")


_COMPONENT = st.components.v2.component(
    "ssn_proctor_guard",
    html=_asset("guard.html"),
    css=_asset("guard.css"),
    js=_asset("guard.js"),
)


def _states() -> dict:
    states = st.session_state.get(STATE_KEY)
    if not isinstance(states, dict):
        states = {}
        st.session_state[STATE_KEY] = states
    return states


def _on_start(sid: str, kind: Kind, label: str, key: str) -> None:
    payload = (st.session_state.get(f"proctor-ui-{key}") or {}).get("start") or {}
    camera = "on" if payload.get("camera") == "on" else "unavailable"
    try:
        attempt = proctoring.start(
            sid,
            kind,
            label,
            camera=camera,
            consent=True,
            camera_note=str(payload.get("note") or "")[:200],
        )
    except ServiceError as e:
        _states()[key] = {"error": str(e)}
        return
    _states()[key] = {
        "attempt_id": attempt,
        "strikes": 0,
        "breached": False,
        "warning": None,
        "camera_on": camera == "on",
        "started": time.time(),
    }


def _on_events(sid: str, key: str) -> None:
    state = _states().get(key) or {}
    events = (st.session_state.get(f"proctor-ui-{key}") or {}).get("events") or []
    if not state.get("attempt_id") or not isinstance(events, list):
        return
    batch = []
    for e in events[: rules.MAX_BATCH]:
        if isinstance(e, dict) and e.get("kind") in rules.CLIENT_KINDS:
            dur = e.get("duration_s")
            batch.append(
                (e["kind"], float(e.get("at_s") or 0), float(dur) if dur is not None else None)
            )
    try:
        p = proctoring.record(sid, state["attempt_id"], batch, check_gap=False)
    except ServiceError:
        return
    state.update(strikes=p.strikes, breached=p.breached, warning=p.warning)


def guard(sid: str, kind: Kind, label: str, *, key: str) -> Guard:
    """Proctoring for the open test `key` (one per quiz or question). Unproctored practice
    returns an inactive Guard. While a pre-check is still needed it is shown and the page stops
    here (st.stop), so the test appears only once the attempt has started."""
    p = proctoring.policy(sid)
    state = _states().get(key) or {}
    if not state.get("attempt_id"):
        if p.seb:
            st.error(
                "Your organization requires Safe Exam Browser for tests. Take this test in the "
                "web app, opened with the .seb file your organization gave you.",
                icon=":material/lock:",
            )
            st.stop()
        if not p.required and not st.toggle(
            "Proctor this test (practice for a proctored test; optional)",
            key=f"proctor-optin-{key}",
        ):
            return Guard(active=False)
        if p.required:
            st.info(
                "Your organization proctors this test. A short check runs before it starts.",
                icon=":material/shield:",
            )
        if err := state.get("error"):
            st.error(formatter.md_escape(err), icon=":material/error:")
        _COMPONENT(
            key=f"proctor-ui-{key}",
            data={"mode": "precheck", "consent_text": rules.CONSENT_TEXT},
            on_start_change=lambda: _on_start(sid, kind, label, key),
            on_events_change=lambda: None,
        )
        st.stop()
    _COMPONENT(
        key=f"proctor-ui-{key}",
        data={
            "mode": "running",
            "strikes": state["strikes"],
            "max": rules.MAX_STRIKES,
            "camera_on": state["camera_on"],
            "elapsed_s": round(time.time() - state["started"], 1),
        },
        on_start_change=lambda: None,
        on_events_change=lambda: _on_events(sid, key),
    )
    if state.get("warning") and not state["breached"]:
        st.warning(formatter.md_escape(state["warning"]), icon=":material/warning:")
    return Guard(
        True, state["attempt_id"], state["strikes"], state["breached"], state.get("warning")
    )


def finish(sid: str, key: str) -> list[str]:
    """End the test's attempt (after submit or breach): its telemetry flags (clear-cut codes
    and PROCTOR_BREACH only); [] for an unproctored test."""
    state = _states().pop(key, None) or {}
    if not state.get("attempt_id"):
        return []
    return proctoring.finish(sid, state["attempt_id"])


def drop(key: str) -> None:
    """Forget the test's attempt without finishing it (a new quiz replaced it)."""
    _states().pop(key, None)


def outcome_banner(flags: list[str]) -> None:
    """After a test: what proctoring recorded, in plain words."""
    if FLAG_PROCTOR_BREACH in flags:
        st.error(
            f"Submitted after {MAX_PROCTOR_STRIKES} proctoring strikes. Your proctoring record is "
            "in Settings.",
            icon=":material/gavel:",
        )
    elif flags:
        st.info("Proctored. Your proctoring record is in Settings.", icon=":material/shield:")


REVIEW_NOTE = (
    "For review only, never a strike: these misfire with glasses, a disability, a poor camera, "
    "or someone looking away to think."
)


def render_record(attempts: list[proctoring.AttemptView], *, for_admin: bool = False) -> None:
    """Each proctored attempt with its events, labelled Clear (strikes) or For review. The
    student and their organization's admin see the same record."""
    if not attempts:
        st.caption("No proctored tests yet.")
        return
    if not for_admin:
        st.caption(
            "What was recorded during your proctored tests: events and times only, never video "
            "or images. Your organization's admin sees the same record."
        )
    for a in attempts:
        mode = {"practice": "practice", "required": "required", "seb": "Safe Exam Browser"}
        verdict = (
            f":red-badge[Submitted after {a.strikes} strikes]"
            if a.breached
            else f":orange-badge[{a.strikes} strike{'s' if a.strikes != 1 else ''}]"
            if a.strikes
            else ":green-badge[No strikes]"
        )
        camera = " :blue-badge[Camera checks skipped]" if a.camera == "unavailable" else ""
        title = f"{'Quiz' if a.kind == 'quiz' else 'Interview'}: {a.label}"
        with st.expander(
            f"{a.started[:16].replace('T', ' ')} UTC · {title}",
            icon=":material/shield:",
            expanded=a.breached and for_admin,
        ):
            minutes = max(1, round(a.duration_s / 60))
            st.markdown(f"{verdict}{camera} · {mode[a.mode]} · about {minutes} min")
            if a.camera_note:
                st.caption(f"Camera: {formatter.md_escape(a.camera_note)}")
            if a.clear:
                st.markdown("**Clear (strikes)**")
                st.markdown(
                    "\n".join(
                        f"- {formatter.md_escape(e.text)}"
                        + ("" if e.strike else " :gray[(same incident, not another strike)]")
                        for e in a.clear
                    )
                )
            if a.review:
                st.markdown("**For review**")
                st.caption(REVIEW_NOTE)
                st.markdown("\n".join(f"- :gray[{formatter.md_escape(e.text)}]" for e in a.review))
            if not a.clear and not a.review:
                st.caption("Nothing was recorded.")
