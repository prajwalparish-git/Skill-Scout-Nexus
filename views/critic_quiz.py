"""Step 4, critic-checked quiz: multiple-choice questions on one skill, each checked by a critic
before the student sees it (agents/critic_quiz_agent.py); the score is recorded."""

import streamlit as st

from core import proctor_guard
from piq import formatter, journey
from piq.config import (
    CRITIC_QUIZ_DEFAULT,
    CRITIC_QUIZ_DEFAULT_DIFFICULTY,
    CRITIC_QUIZ_SIZES,
    DIFFICULTIES,
)
from piq.services import ServiceError
from piq.ui import Stat, page_header, require_profile, stat_row, status_badge

BATCH, GRADE, ROUND = "cq_batch", "cq_grade", "cq_round"  # piq.ui.PER_STUDENT_KEYS

page_header(
    "Critic-checked quiz",
    "Questions on one skill. A generator writes them and a critic checks each for sound facts, "
    "exactly one right answer and fair options before you see it; a rejected question is "
    "rewritten, and the verified question bank fills any gap.",
)
sid, _ = require_profile()
skills = journey.quiz_skills(sid)  # the gaps first: the first one is quizzed ahead of time

with st.form("cq_setup", border=True):
    skill = st.selectbox(
        "Skill", skills, help="Your skill gaps come first, then the role's other skills."
    )
    left, right = st.columns(2)
    difficulty = left.segmented_control(
        "Difficulty",
        DIFFICULTIES,
        default=CRITIC_QUIZ_DEFAULT_DIFFICULTY,
        format_func=str.capitalize,
    )
    count = right.segmented_control("Questions", CRITIC_QUIZ_SIZES, default=CRITIC_QUIZ_DEFAULT)
    if st.form_submit_button("Generate quiz", type="primary", icon=":material/quiz:"):
        try:
            proctor_guard.reset_proctor_state()  # a new quiz starts with no strikes
            with st.spinner("Writing questions and checking each one"):
                st.session_state[BATCH] = journey.critic_quiz(
                    sid,
                    skill or "",
                    difficulty or CRITIC_QUIZ_DEFAULT_DIFFICULTY,
                    count or CRITIC_QUIZ_DEFAULT,
                )
            st.session_state[GRADE] = None
            st.session_state[ROUND] = st.session_state.get(ROUND, 0) + 1
        except ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")

batch = st.session_state.get(BATCH)
if batch is None:
    st.caption("No quiz yet. Pick a skill and press Generate quiz.")
    st.stop()

with st.container(border=True):
    if batch.source == "critic_generated":
        status_badge("done", f"Critic approved after {batch.attempts} attempt(s)")
    else:
        status_badge("info", "From the verified question bank")
    st.markdown(
        "\n".join(f"- :small[{formatter.md_escape(n)}]" for n in batch.critic_notes)
        or ":gray[No notes.]"
    )

grade: journey.QuizGrade | None = st.session_state.get(GRADE)
n = st.session_state.get(ROUND, 0)

if grade is None:
    proctor_guard.render_proctor_guard(page_type="critic_quiz")
    proctor_guard.render_warning_banner()
    if proctor_guard.is_breached():
        answers = [st.session_state.get(f"cq{n}_{i}") for i in range(len(batch.questions))]
        st.session_state[GRADE] = grade = journey.grade_quiz(
            sid, batch, answers, proctor_flags=[proctor_guard.FLAG_PROCTOR_BREACH]
        )
        st.rerun()

if grade is None:  # the form gives no rerun per answer: write the next set as the quiz opens
    journey.preload_next_quiz(sid, batch)
with st.form(f"cq_answers_{n}", border=False):
    answers: list[int | None] = []
    for i, q in enumerate(batch.questions):
        answers.append(
            st.radio(
                f"**{i + 1}.** {formatter.md_escape(q.text)}",
                range(4),
                format_func=lambda j, q=q: formatter.md_escape(journey.option_label(q, j)),
                index=None,
                key=f"cq{n}_{i}",
                disabled=grade is not None,
            )
        )
    submitted = st.form_submit_button(
        "Submit answers", type="primary", icon=":material/grading:", disabled=grade is not None
    )
if submitted:
    try:
        st.session_state[GRADE] = grade = journey.grade_quiz(sid, batch, answers)
        st.rerun()
    except ServiceError as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")

if grade is None:
    st.stop()

if proctor_guard.is_breached():
    st.error(
        "🚨 **PROCTOR BREACH:** This quiz was force-submitted due to 3 proctoring violations "
        "(tab switching, window blur, or camera absence).",
        icon=":material/gavel:",
    )

skipped = sum(st.session_state.get(f"cq{n}_{i}") is None for i in range(grade.total))
stat_row(
    [
        Stat("Score", f"{grade.score}/{grade.total}"),
        Stat("Percent", f"{grade.percent}%"),
        Stat("Skipped", str(skipped)),
    ]
)
for i, (q, ok) in enumerate(zip(batch.questions, grade.correct, strict=True)):
    with st.container(border=True):
        status_badge("done" if ok else "error", "Correct" if ok else "Not correct")
        st.markdown(f"**{i + 1}.** {formatter.md_escape(q.text)}")
        st.markdown(
            f"Answer: **{formatter.md_escape(journey.option_label(q, q.correct_index))}**  \n"
            f":gray[{formatter.md_escape(q.explanation)}]"
        )
if not grade.saved:
    st.warning(
        "This result could not be saved for the faculty dashboard.", icon=":material/cloud_off:"
    )
