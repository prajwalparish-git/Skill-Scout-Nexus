"""Quiz: one or more topics of the student's syllabus, a number of questions for each and a
mix of easy, medium and hard. Every batch is checked by a critic before the student sees it;
the result breaks down by topic, difficulty and thinking level, and each topic's score sets
its next difficulty and counts toward next week's plan."""

from collections import Counter
from functools import partial

import streamlit as st

from core import proctor_guard
from database import crud
from piq import charts, formatter, services
from piq.config import DEFAULT_MIX, QUIZ_MAX_PER_TOPIC, QUIZ_MAX_TOTAL, QUIZ_SIZE, settings
from piq.ui import Stat, page_header, require_profile, run_agent, show_last_run, stat_row

BLANKS = "quiz_blanks"  # question numbers left blank at the last submit
RUN, RESULT = "quiz_run", "quiz_run_result"
NEXT = (
    (
        "fact_check",
        "A critic checks every batch of questions first. A flawed one is rewritten, and the "
        "trail shows why.",
    ),
    ("checklist", "Answer the questions, then submit. A blank counts as wrong."),
    (
        "monitoring",
        "Your result breaks down by topic, difficulty and thinking level, with every mistake "
        "explained.",
    ),
    (
        "autorenew",
        "Each topic's score sets its next difficulty and its weakness in next week's plan.",
    ),
)


def _counts(sid: str, chosen: list[str]) -> dict[str, int]:
    """Questions per chosen topic, three inputs to a row (they stack on a phone)."""
    counts = {}
    for start in range(0, len(chosen), 3):
        row = chosen[start : start + 3]
        for column, topic in zip(st.columns(3, gap="small"), row, strict=False):
            counts[topic] = int(
                column.number_input(
                    topic,
                    min_value=1,
                    max_value=QUIZ_MAX_PER_TOPIC,
                    value=QUIZ_SIZE,
                    step=1,
                    key=f"quiz_n_{sid}_{topic}",
                )
            )
    return counts


def _mix(setup: services.QuizSetup, chosen: list[str]) -> dict[str, int]:
    """The difficulty mix as one two-handle slider, so the three shares always add to 100%:
    it starts at the level most chosen topics are suggested."""
    suggested = Counter(setup.suggested(t) for t in chosen).most_common(1)[0][0]
    low, high = st.slider(
        "Difficulty mix",
        min_value=0,
        max_value=100,
        value=DEFAULT_MIX[suggested],
        step=5,
        format="%d%%",
        key=f"quiz_mix_{suggested}",  # a new suggestion starts from its own default
        help="Easy below the left handle, medium between the handles, hard above the right.",
    )
    mix = services.mix_from_handles(low, high)
    st.markdown(f":gray-badge[:material/tune: {formatter.mix_md(mix)}]")
    with st.expander("Why this mix", icon=":material/recommend:"):
        st.markdown(f"Most of these topics are suggested at **{suggested}**.")
        for t in chosen:
            st.markdown(formatter.suggestion_md(t, setup.last.get(t), setup.suggested(t)))
    return mix


def _setup(sid: str, profile: services.StudentProfile) -> None:
    setup = services.quiz_setup(sid, profile)
    domain = services.domain_of_role(profile.target_role)
    key = f"quiz_topics_{sid}"
    if (preset := st.session_state.pop("quiz_topic", None)) in setup.topics:  # from Home
        st.session_state[key] = [preset]
    st.session_state.setdefault(key, setup.topics[:1])

    setup_col, next_col = st.columns([3, 2], gap="medium")
    with setup_col, st.container(border=True):
        st.subheader("Set up a quiz", anchor=False)
        st.markdown(formatter.syllabus_line(domain.name, profile.target_role))
        chosen = st.pills(
            "Topics",
            setup.topics,
            selection_mode="multi",
            format_func=lambda t: formatter.topic_pick_label(t, setup.weakness.get(t)),
            key=key,
            wrap=True,
        )
        st.caption(
            "Your topics come first, weakest first; the rest of your domain follows. "
            "0% weak is strong, 100% weak needs the most practice."
        )
        if not chosen:
            st.info("Choose at least one topic.", icon=":material/info:")
            return
        st.markdown(f"**Questions per topic** :gray[(1 to {QUIZ_MAX_PER_TOPIC} each)]")
        counts = _counts(sid, chosen)
        total = sum(counts.values())
        st.progress(
            min(total / QUIZ_MAX_TOTAL, 1.0), text=f"{total} of at most {QUIZ_MAX_TOTAL} questions"
        )
        mix = _mix(setup, chosen)
        try:
            spec = services.quiz_spec(counts, mix, domain.topics)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.dataframe(formatter.spec_table(spec.parts()), width="stretch")
        st.caption(formatter.spec_note(spec.total, spec.batches, settings().mock_mode))
        if st.button("Generate quiz", type="primary", icon=":material/quiz:"):
            run = run_agent("Quiz agent", lambda ev: services.start_quiz_run(sid, spec, ev))
            if run:
                st.session_state[RUN] = run
                st.rerun()
        show_last_run("Quiz agent")  # keeps a failed generation visible
    with next_col, st.container(border=True):
        st.subheader("What happens next", anchor=False)
        for n, (icon, text) in enumerate(NEXT, 1):
            st.markdown(f":primary[:material/{icon}:] **{n}.** {text}")


def _take(sid: str, run: services.QuizRun) -> None:
    proctor_guard.render_proctor_guard(page_type="quiz")
    proctor_guard.render_warning_banner()

    if proctor_guard.is_breached():
        chosen = [st.session_state.get(f"{run.key}-{i}") for i in range(1, run.total + 1)]
        st.session_state.pop(BLANKS, None)
        st.session_state[RESULT] = services.submit_quiz_run(sid, run, chosen)
        try:
            profile = services.current_profile(sid)
            syl = services.student_syllabus(sid, profile)
            t = crud.get_student(profile.username) if profile else None
            if t:
                score = sum(
                    a == q.correct_index
                    for (*_, q), a in zip(run.questions, chosen, strict=False)
                    if a is not None
                )
                crud.save_quiz_attempt(
                    student_id=t.id,
                    stream=getattr(syl.domain, "stream", "Engineering"),
                    domain=syl.domain.name,
                    score=score,
                    total_questions=run.total,
                    critique_notes=(
                        "[TEST TERMINATED: Force-submitted due to 3 strikes / PROCTOR_BREACH]"
                    ),
                    proctor_flags=[proctor_guard.FLAG_PROCTOR_BREACH],
                )
        except Exception:
            pass
        st.session_state.pop(RUN, None)
        st.rerun()

    topics = list(dict.fromkeys(p.topic for p in run.parts))
    st.subheader(f"{formatter.run_title(topics)} · {run.total} questions", anchor=False)
    show_last_run("Quiz agent")
    st.caption("Pick one answer for each question, then submit; nothing is marked until you do.")
    key = run.key  # fresh widget keys per quiz: no stale answers
    with st.form(f"quiz-{key}", border=False):
        chosen, n, shown = [], 0, None
        for part in run.parts:
            if part.topic != shown:
                st.markdown(f"#### {formatter.md_escape(part.topic)}")
                shown = part.topic
            for q in part.questions:
                n += 1
                with st.container(border=True):
                    chosen.append(
                        st.radio(
                            f"**Q{n}.** :gray[{part.difficulty}] {formatter.md_escape(q.text)}",
                            range(4),
                            format_func=lambda j, q=q: formatter.md_escape(q.options[j]),
                            index=None,
                            key=f"{key}-{n}",
                        )
                    )
        submitted = st.form_submit_button("Submit", type="primary", icon=":material/done_all:")
    anyway = False
    if blanks := st.session_state.get(BLANKS):
        st.warning(formatter.blanks_md(blanks), icon=":material/warning:")
        anyway = st.button("Submit anyway", icon=":material/done_all:")
    if submitted or anyway:
        missing = [i for i, a in enumerate(chosen, 1) if a is None]
        if missing and not anyway:  # keep the quiz and say which questions are blank
            st.session_state[BLANKS] = missing
            st.rerun()
        st.session_state.pop(BLANKS, None)
        st.session_state[RESULT] = services.submit_quiz_run(sid, run, chosen)
        st.session_state.pop(RUN)
        st.rerun()


BREAKDOWNS = (
    ("topic", "By topic", "Questions per topic: right, wrong and left blank."),
    ("difficulty", "By difficulty", "How you did at each level you attempted."),
    (
        "bloom",
        "By thinking level",
        "Each question's level of thinking (Bloom's taxonomy): remember a fact, understand an "
        "idea, apply it to a case, or analyse a situation.",
    ),
)


def _review(result: services.QuizRunResult) -> None:
    if proctor_guard.is_breached():
        st.error(
            "🚨 **PROCTOR BREACH:** This quiz was force-submitted due to 3 proctoring violations "
            "(tab switching, window blur, or camera absence).",
            icon=":material/gavel:",
        )
    topics = list(dict.fromkeys(p.topic for p in result.run.parts))
    with st.container(border=True):
        st.subheader(f"{formatter.run_title(topics)}: your result", anchor=False)
        stat_row(
            [
                Stat("Score", f"{result.score_pct:.0f}%"),
                Stat("Correct", f"{result.correct}/{result.total}"),
                Stat("Wrong", str(result.wrong)),
                Stat("Left blank", str(result.skipped)),
            ]
        )
        st.markdown(
            formatter.run_result_md(result.correct, result.wrong, result.skipped, result.total)
        )
        st.markdown(formatter.next_difficulty_md(result.next_difficulty))
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button("New quiz", type="primary", icon=":material/restart_alt:"):
                proctor_guard.reset_proctor_state()
                st.session_state.pop(RESULT)
                st.rerun()
            st.page_link(
                "views/plan.py", label="Open Weekly plan", icon=":material/calendar_month:"
            )
            today = formatter.local_today()
            st.download_button(
                "Download review (.md)",
                partial(  # built only when clicked
                    formatter.run_notes,
                    result.run.parts,
                    result.chosen,
                    result.score_pct,
                    today,
                ),
                file_name=f"placementiq-quiz-{today:%Y%m%d}.md",
                mime="text/markdown",
                icon=":material/download:",
                type="tertiary",
                on_click="ignore",
            )

    st.subheader("Where the marks went", anchor=False)
    tabs = st.tabs([title for _, title, _ in BREAKDOWNS] + ["Topic × difficulty"])
    for tab, (by, title, about) in zip(tabs, BREAKDOWNS, strict=False):
        outcomes = result.breakdown(by)
        with tab:
            st.caption(about)
            st.vega_lite_chart(
                spec=charts.outcome_bars_spec(formatter.outcome_rows(outcomes)),
                width="stretch",
                alt=formatter.outcome_alt(title, outcomes),
            )
    with tabs[-1]:
        st.caption("Right answers out of questions, for every topic at every level you took.")
        st.dataframe(formatter.grid_table(result.grid()), width="stretch")

    mistakes = result.mistakes()
    st.subheader(f"Your mistakes ({len(mistakes)})", anchor=False)
    if not mistakes:
        st.success("Every answer is right.", icon=":material/verified:")
    for m in mistakes:
        st.container(border=True).markdown(
            formatter.mistake_md(m.n, m.topic, m.difficulty, m.question, m.chosen)
        )
    with st.expander(f"All {result.total} questions", icon=":material/list:"):
        for n, ((part, q), a) in enumerate(
            zip(result.run.questions, result.chosen, strict=True), 1
        ):
            st.markdown(formatter.mistake_md(n, part.topic, part.difficulty, q, a))


page_header(
    "Quiz",
    "Pick one or more topics, how many questions each and the mix of easy, medium and hard. "
    "A critic checks every question before you see it; your scores set the next difficulty "
    "and next week's plan.",
)
sid, profile = require_profile()

if result := st.session_state.get(RESULT):
    _review(result)
elif run := st.session_state.get(RUN):
    _take(sid, run)
else:
    _setup(sid, profile)
