"""Streamlit helpers shared by the views: student selection, the visible agent loop and
the design system's components (page header, empty state, stat cards, chips, badges)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from piq import formatter, services
from piq.config import STATIC_DIR
from piq.graph import CriticRejected, OnEvent
from piq.llm import LLMError
from piq.resume import ResumeError
from piq.schemas import StudentProfile

NEW = "— new student —"
PER_STUDENT_KEYS = (
    "quiz",
    "quiz_result",
    "quiz_run",
    "quiz_run_result",
    "quiz_topic",
    "built_resume",
    "quiz_blanks",
    "interview",
    "onboard_confirm",
    "onboard_delete",
    # the six-step journey's pages
    "scan",
    "roadmap_gaps",
    "roadmap_unsaved",
    "cq_batch",
    "cq_grade",
    "voice_q",
    "voice_result",
    "voice_text",
)
RUN_PREFIX = "run:"  # session key prefix for persisted agent step logs
FAILED = formatter.FAILED
USER_ERRORS = (CriticRejected, LLMError, services.ServiceError, ResumeError)


def set_student(
    student_id: str | None, keep_runs: tuple[str, ...] = (), *, fresh: bool = False
) -> None:
    """Make `student_id` current. On a change, drop the previous student's quiz, interview and
    agent step logs, except the logs of `keep_runs` (labels) already made for the new student.
    `fresh`: drop them even for the same student (a new profile makes their open quiz and
    interview stale)."""
    if fresh or student_id != st.session_state.get("student_id"):
        kept = {RUN_PREFIX + label for label in keep_runs}
        for k in list(st.session_state):
            if k in PER_STUDENT_KEYS or (str(k).startswith(RUN_PREFIX) and k not in kept):
                del st.session_state[k]
    st.session_state["student_id"] = student_id


def student_selector() -> None:
    students = services.list_students()
    labels = {f"{s['usn']} — {s['name']}": s["id"] for s in students}
    ids = list(labels.values())
    current = st.session_state.get("student_id")
    index = ids.index(current) + 1 if current in ids else 0
    choice = st.sidebar.selectbox("Student", [NEW, *labels], index=index)
    set_student(labels.get(choice))
    # Refreshed on every run before the page renders, so pages reuse it instead of a query.
    selected = next((s for s in students if s["id"] == labels.get(choice)), None)
    st.session_state["student"] = dict(selected) if selected else None
    st.session_state["student_count"] = len(students)


def current_student() -> dict | None:
    """The selected student's row (id, name, usn, target_role, readiness_score), or None."""
    return st.session_state.get("student")


def student_count() -> int:
    """How many students the sidebar picker offers (counted by it on this run)."""
    return st.session_state.get("student_count", 0)


def sidebar_context(mock_mode: bool, ai: str = "", engine: str = "") -> None:
    """Under the student picker: their readiness at a glance, a quiet badge naming who
    answers (mock mode, the AI provider in use, or the offline rules) and, last, the
    engine line: AI, records and preloader (journey.engine_status)."""
    with st.sidebar:
        if student := current_student():
            score = student["readiness_score"] or 0
            st.progress(score / 100, text=f"Readiness {score}/100")
        if mock_mode:
            st.badge(
                "Mock mode",
                icon=":material/science:",
                color="gray",
                help="Answers come from built-in samples; no AI service is called.",
            )
        elif ai == "Offline rules":  # quiet on purpose: the student can keep working as usual
            st.badge(
                "Built-in answers",
                icon=":material/offline_bolt:",
                color="gray",
                help="Answers come from the question bank and built-in rules until an AI "
                "service is reachable again.",
            )
        elif ai:
            st.badge(
                f"AI: {ai}",
                icon=":material/cloud_done:",
                color="gray",
                help="The first healthy provider answers; others take over if it fails.",
            )
        if engine:  # small print at the foot: for whoever runs the demo, not the student
            st.caption(f":material/memory: {formatter.md_escape(engine)}")


def require_profile() -> tuple[str, StudentProfile]:
    """The selected student and their profile. Without one, an empty state says how to get
    one (the sidebar is hidden on a phone, so it names the button that opens it) and the
    page stops."""
    sid = st.session_state.get("student_id")
    profile = services.current_profile(sid)
    if not profile:
        body = (
            "Choose your name under **Student** in the sidebar (on a phone, open it with "
            ":material/keyboard_double_arrow_right: at the top left), or onboard a new "
            "student with a resume."
            if student_count()
            else "Nobody has onboarded yet. Analyse a resume to create the first profile."
        )
        if empty_state(
            "person_search", "No student selected", body, "Open Onboard", key="need_student"
        ):
            st.switch_page("views/onboard.py")
        st.stop()
    return sid, profile


def _rejected(events: list[str]) -> bool:
    return any(m.startswith("critic rejected") for m in events)


def _failed(events: list[str]) -> bool:
    return any(m.startswith(FAILED) for m in events)


def _step(parent: DeltaGenerator, step: formatter.TrailStep) -> None:
    """One step of the critic trail. Steps are native timeline steps (icon column and a
    connecting line); each carries a line of content, because an empty step ends the line."""
    state = "error" if step.failed else "complete"
    box = parent.status(f"**{step.title}**", type="step", state=state, expanded=True)
    if step.reasons:  # the critic's own words, at the step title's size
        lines = [f":small[{r}]" for r in step.reasons]
        box.markdown(lines[0] if len(lines) == 1 else "\n".join(f"- {line}" for line in lines))
    if step.note:
        box.caption(step.note)


def run_agent[T](label: str, fn: Callable[[OnEvent], T]) -> T | None:
    """Run an agent call inside a live status box that shows every generate/critic step.

    The step log (including a failure) is also kept in session state: views call
    `st.rerun()` after saving, which would otherwise wipe the only visible evidence
    of the critic loop. Returns None after showing a user-facing error.
    """
    events: list[str] = []
    with st.status(label, expanded=True) as box:

        def on_event(msg: str) -> None:
            events.append(msg)
            _step(box, formatter.trail_steps(events)[-1])

        try:
            out = fn(on_event)
        except USER_ERRORS as e:
            events.append(f"{FAILED}{e}")
            _step(box, formatter.trail_steps(events)[-1])
            box.update(label=f"{label} — failed", state="error")
            st.error(formatter.critic_text(str(e)))
            return None
        finally:
            st.session_state[RUN_PREFIX + label] = events
        box.update(label=f"{label} — done", state="complete", expanded=_rejected(events))
    return out


def show_last_run(label: str) -> None:
    """Re-render the step log of the last `run_agent(label, ...)`.

    Expanded when it contained a retry or a failure, so neither goes unnoticed.
    """
    events = st.session_state.get(RUN_PREFIX + label)
    if events:
        failed = _failed(events)
        with st.status(
            f"{label} — last run{' failed' if failed else ''}",
            state="error" if failed else "complete",
            expanded=failed or _rejected(events),
        ) as box:
            for step in formatter.trail_steps(events):
                _step(box, step)


# --- design-system components -------------------------------------------------------


@dataclass(frozen=True)
class Stat:
    label: str
    value: str
    delta: str | None = None
    help: str | None = None
    delta_color: str = "normal"  # "off" for a change that is neither good nor bad
    delta_arrow: str = "auto"  # "off" for a note under the value that is not a change


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return (STATIC_DIR / "app.css").read_text(encoding="utf-8")


def load_css() -> None:
    """Add static/app.css (what the theme cannot express) once per run, before the page."""
    st.html(f"<style>{_stylesheet()}</style>")


def page_header(
    title: str,
    purpose: str,
    action: str | None = None,
    *,
    icon: str | None = None,
    key: str | None = None,
) -> bool:
    """Every page opens with its title, one plain sentence of purpose (Markdown: escape any
    dynamic part) and optionally its primary action, under the sentence so nothing is
    squeezed on a phone. Returns True when the action is clicked."""
    st.title(title, anchor=False)
    st.markdown(f":gray[{purpose}]")
    return bool(action) and st.button(action, type="primary", icon=icon, key=key)


def empty_state(
    icon: str, title: str, body: str, action: str | None = None, *, key: str | None = None
) -> bool:
    """An empty screen as an invitation: what is missing and the one next step."""
    with st.container(border=True, gap="small"):
        st.subheader(title, anchor=False, icon=f":material/{icon}:")
        st.markdown(body)
        return bool(action) and st.button(action, type="primary", key=key)


def stat_row(stats: Sequence[Stat]) -> None:
    """Equal-height stat cards in one row; they stack on phones."""
    for column, s in zip(st.columns(len(stats)), stats, strict=True):
        column.metric(
            s.label,
            s.value,
            s.delta,
            delta_color=s.delta_color,
            delta_arrow=s.delta_arrow,
            help=s.help,
            border=True,
            height="stretch",
        )


def topic_chip(topic: str) -> None:
    st.html(formatter.topic_chip_html(topic))


def status_badge(state: str, text: str) -> None:
    icon, color = formatter.STATUS[state]
    st.badge(text, icon=f":material/{icon}:", color=color)
