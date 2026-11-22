"""Mock interview: a written interview of up to INTERVIEW_MAX_TURNS questions; vague answers
get a follow-up, every answer gets scored feedback, and a critic checks each question."""

from functools import partial

import streamlit as st

from piq import formatter, services
from piq.config import INTERVIEW_MAX_TURNS, INTERVIEW_TYPES
from piq.ui import page_header, require_profile, run_agent, show_last_run

INTERVIEWER, STUDENT, FEEDBACK = (
    ":material/record_voice_over:",
    ":material/person:",
    ":material/grading:",
)
TYPE_HINTS = {
    "HR": "Motivation, teamwork and how you handle situations, told with examples.",
    "Technical": "Core concepts for your target role, explained in your own words.",
    "Project": "The projects on your resume: design choices, problems and results.",
}
NEXT = (
    (
        "fact_check",
        f"The interviewer asks up to {INTERVIEW_MAX_TURNS} questions, each checked by a critic "
        "first. A vague answer gets a follow-up.",
    ),
    ("edit_note", "Type each answer as you would say it."),
    (
        "grading",
        "Every answer is scored for relevance, depth, structure and clarity, with a model "
        "answer to compare.",
    ),
)


def _setup(sid: str) -> None:
    setup_col, next_col = st.columns([3, 2], gap="medium")
    with setup_col, st.container(border=True):
        st.subheader("Start a mock interview", anchor=False)
        kind = st.radio(
            "Interview type", INTERVIEW_TYPES, captions=[TYPE_HINTS[t] for t in INTERVIEW_TYPES]
        )
        if st.button("Start session", type="primary", icon=":material/play_arrow:"):
            session = run_agent(
                "Interview agent", lambda ev: services.start_interview(sid, kind, ev)
            )
            if session:
                st.session_state["interview"] = session
                st.rerun()
        show_last_run("Interview agent")
    with next_col, st.container(border=True):
        st.subheader("What happens next", anchor=False)
        for n, (icon, text) in enumerate(NEXT, 1):
            st.markdown(f":primary[:material/{icon}:] **{n}.** {text}")


def _feedback(turn: services.AnsweredTurn, latest: bool) -> None:
    with st.chat_message("Feedback", avatar=FEEDBACK):
        st.markdown(formatter.feedback_title(turn.evaluation))
        st.html(formatter.criteria_html(turn.evaluation.scores))
        with st.expander("Strengths, what to improve and a model answer", expanded=latest):
            st.markdown(formatter.evaluation_md(turn.evaluation))


page_header(
    "Mock interview",
    f"A written interview of up to {INTERVIEW_MAX_TURNS} questions. Vague answers get a "
    "follow-up, every answer gets scored feedback, and a critic checks each question first.",
)
sid, _ = require_profile()
session: services.InterviewSession | None = st.session_state.get("interview")

if session is None:
    _setup(sid)
    st.stop()

value, words = formatter.interview_progress(
    len(session.history), session.current is not None, INTERVIEW_MAX_TURNS
)
st.subheader(f"{session.interview_type} interview", anchor=False)
st.progress(value, text=words)


def _source_badge(question: str) -> str:
    """Company practice: whether a question was reported by a student or written by the AI."""
    if not session.script:
        return ""
    if question in session.script:
        return ":orange-badge[:material/person: Reported by a student]  \n"
    return ":violet-badge[:material/smart_toy: AI question, not reported]  \n"


for i, turn in enumerate(session.history):
    st.chat_message("Interviewer", avatar=INTERVIEWER).markdown(
        _source_badge(turn.question) + formatter.md_escape(turn.question)
    )
    st.chat_message("You", avatar=STUDENT).markdown(formatter.md_escape(turn.answer))
    _feedback(turn, latest=i == len(session.history) - 1)

if session.done:
    st.success(
        f"Session complete — average {session.average:.1f}/5 over {len(session.history)} "
        "questions.",
        icon=":material/task_alt:",
    )
    summary = services.interview_summary(session)
    with st.container(border=True):
        st.subheader("Session summary", anchor=False)
        st.caption("Each criterion's average over your answers in this session.")
        st.html(formatter.criteria_html(summary.averages))
        st.markdown(formatter.summary_md(summary.averages, summary.strongest, summary.weakest))
        st.markdown("**What to work on**")
        st.markdown(formatter.tips_md(summary.tips))
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("New session", type="primary", icon=":material/restart_alt:"):
            st.session_state.pop("interview")
            st.rerun()
        today = formatter.local_today()
        turns = [(t.question, t.answer, t.evaluation) for t in session.history]
        st.download_button(
            "Download feedback (.md)",
            partial(  # built only when clicked
                formatter.interview_notes, session.interview_type, turns, today, summary.tips
            ),
            file_name=f"placementiq-{session.interview_type.lower()}-interview-{today:%Y%m%d}.md",
            mime="text/markdown",
            icon=":material/download:",
            type="tertiary",
            on_click="ignore",
        )
    st.stop()

if session.current is None:  # the answer is saved; only the follow-up question failed
    with st.chat_message("Interviewer", avatar=INTERVIEWER):
        show_last_run("Interview agent")
        if st.button("Retry next question", type="primary", icon=":material/refresh:"):
            nxt = run_agent(
                "Interview agent", lambda ev: services.continue_interview(sid, session, ev)
            )
            if nxt:
                st.session_state["interview"] = nxt
                st.rerun()
    st.stop()

with st.chat_message("Interviewer", avatar=INTERVIEWER):
    if badge := _source_badge(session.current.question):
        st.markdown(badge)
    st.markdown(formatter.question_md(session.current))
    show_last_run("Interview agent")  # how the critic checked this question
if answer := st.chat_input("Your answer"):
    st.chat_message("You", avatar=STUDENT).markdown(
        formatter.md_escape(answer)
    )  # shown while scored
    answered = run_agent("Evaluator", lambda _: services.answer_question(sid, session, answer))
    if answered is None:
        st.stop()
    st.session_state["interview"] = answered
    if not answered.done:
        nxt = run_agent(
            "Interview agent", lambda ev: services.continue_interview(sid, answered, ev)
        )
        if nxt:
            st.session_state["interview"] = nxt
    st.rerun()
