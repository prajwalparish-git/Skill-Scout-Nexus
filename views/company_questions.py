"""Company questions: interview questions students reported from their own interviews, by
company and round, in their own words (nothing copied from any website). Browse approved posts,
practise them (reported multiple-choice questions as a quiz, open ones as a mock interview), or
practise with AI questions in a company's style, always marked as AI. Until students report a
company, practise by round from the open question bank, labelled general practice and never
claimed as that company's. Share your own interview: it is cleaned of personal details and
appears once a moderator approves it."""

from datetime import date

import pandas as pd
import streamlit as st

from piq import experience_checks, experiences, formatter, services
from piq.config import (
    EXPERIENCE_MAX_QUESTIONS,
    EXPERIENCE_ROUNDS,
    PROCESS_RESULTS,
    PROCESS_ROUND_TYPES,
)
from piq.ui import page_header, require_profile, run_agent

QUIZ = "cq_quiz"  # (company slug, PracticeQuiz) being taken
RESULT = "cq_result"  # (PracticeQuiz, graded) just submitted
SHARED = "cq_shared"  # the last post shared: (id, removed kinds)
PANEL_SHARED = "cq_panel_shared"  # shared from a company page's panel: removed kinds
LETTERS = "ABCD"


def _rounds_line(rounds: dict) -> str:
    if not rounds:
        return "No posts approved yet."
    return " · ".join(
        f"{EXPERIENCE_ROUNDS[r]} {v['posts']} post{'s' if v['posts'] != 1 else ''}"
        for r, v in rounds.items()
    )


def _post(sid: str, p: dict) -> None:
    with st.container(border=True):
        st.markdown(
            f":orange-badge[:material/person: Reported by {formatter.md_escape(p['label'])}] "
            f"**{formatter.md_escape(p['role'])}** · {EXPERIENCE_ROUNDS[p['round']]} round · "
            f"{p['interview_month']}"
        )
        for n, q in enumerate(p["questions"], 1):
            st.markdown(f"**Q{n}.** {formatter.md_escape(q['text'])}")
            if q["kind"] == "mcq":
                st.markdown(
                    "  \n".join(
                        f"{LETTERS[i]}. {formatter.md_escape(o)}"
                        for i, o in enumerate(q["options"])
                    )
                )
                with st.expander("Show the reported answer"):
                    st.markdown(
                        f"**{LETTERS[q['correct_index']]}.** "
                        + formatter.md_escape(q.get("explanation") or "")
                    )
        if p["tip"]:
            st.caption(f":material/lightbulb: Tip: {formatter.md_escape(p['tip'])}")
        with st.popover("Report", icon=":material/flag:"):
            st.caption(
                "Report abuse, personal details, or text copied from a website. Two reports hide "
                "the post until a moderator looks again."
            )
            if st.button("Report this post", key=f"cq_report_{p['id']}"):
                try:
                    experiences.report(sid, p["id"])
                    st.toast("Thanks: the post was reported.", icon=":material/flag:")
                except services.ServiceError as e:
                    st.error(formatter.md_escape(str(e)), icon=":material/error:")


def _practice(sid: str, slug: str, round_: str, detail: dict) -> None:
    """Practice for one company and round: reported material, and AI practice kept apart."""
    posts = [p for p in detail["posts"] if p["round"] == round_]
    mcqs = sum(q["kind"] == "mcq" for p in posts for q in p["questions"])
    opens = sum(q["kind"] == "open" for p in posts for q in p["questions"])
    st.markdown(f"**Practise the {EXPERIENCE_ROUNDS[round_]} round**")
    with st.container(horizontal=True):
        if st.button(
            f"Quiz: {mcqs} reported question{'s' if mcqs != 1 else ''}",
            icon=":material/quiz:",
            disabled=not mcqs,
            key="cq_rep_quiz",
        ):
            try:
                st.session_state[QUIZ] = (slug, experiences.reported_quiz(slug, round_))
                st.session_state.pop(RESULT, None)
                st.rerun()
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
        label = f"Mock interview: {opens} reported" if opens else "Mock interview (AI questions)"
        if st.button(label, icon=":material/record_voice_over:", key="cq_interview"):
            session = run_agent(
                "Interview agent", lambda ev: experiences.interview_practice(sid, slug, round_, ev)
            )
            if session:
                st.session_state["interview"] = session
                st.switch_page("views/interview.py")
        if round_ not in ("hr", "group_discussion") and st.button(
            "AI practice in this style", icon=":material/smart_toy:", key="cq_ai_quiz"
        ):
            quiz = run_agent("Quiz agent", lambda _: experiences.ai_quiz(sid, slug, round_))
            if quiz:
                st.session_state[QUIZ] = (slug, quiz)
                st.session_state.pop(RESULT, None)
                st.rerun()
    st.caption(
        "Reported questions are asked as students wrote them. AI practice is written by AI in "
        "the round's style: it is never presented as questions the company asked."
    )


BADGES = {
    "ai": ":violet-badge[:material/smart_toy: AI practice, not reported by a student]",
    "reported": ":orange-badge[:material/person: Reported by students]",
    "open": ":green-badge[:material/menu_book: General practice (open question bank)]",
}


def _open_quiz_button(sid: str, slug: str, round_: str, what: str, count: int) -> None:
    st.markdown(f"**{experiences.OPEN_ROUNDS[round_]}**")
    st.caption(what)
    if st.button(
        "Quiz", icon=":material/quiz:", key=f"cq_open_{round_}", disabled=not count, width="stretch"
    ):
        try:
            st.session_state[QUIZ] = (slug, experiences.open_quiz(sid, slug, round_))
            st.session_state.pop(RESULT, None)
            st.rerun()
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")


def _open_interview_button(sid: str, slug: str, round_: str, label: str) -> None:
    if st.button(
        label, icon=":material/record_voice_over:", key=f"cq_open_iv_{round_}", width="stretch"
    ):
        session = run_agent(
            "Interview agent", lambda ev: experiences.open_interview(sid, slug, round_, ev)
        )
        if session:
            st.session_state["interview"] = session
            st.switch_page("views/interview.py")


def _open_practice(sid: str, slug: str, practice: dict) -> None:
    """Practice by round from the open question bank: general practice, never the company's."""
    rounds = practice["rounds"]
    with st.container(border=True):
        st.markdown(BADGES["open"])
        st.markdown("**Practice by round**")
        st.caption(formatter.md_escape(practice["note"]))
        apt, tech, hr = st.columns(3, gap="small")
        with apt.container(border=True):
            what = f"{rounds['aptitude']:,} questions with worked answers"
            _open_quiz_button(sid, slug, "aptitude", what, rounds["aptitude"])
        with tech.container(border=True):
            what = f"{rounds['technical']:,} questions on your topics"
            _open_quiz_button(sid, slug, "technical", what, rounds["technical"])
            if practice["technical_interview"]:
                _open_interview_button(sid, slug, "technical", "Mock interview")
        with hr.container(border=True):
            st.markdown("**HR**")
            st.caption(f"{rounds['hr']} common questions with model answers")
            _open_interview_button(sid, slug, "hr", "Mock interview")
        with st.expander("Common HR questions with model answers", icon=":material/forum:"):
            for n, q in enumerate(practice["hr_questions"], 1):
                st.markdown(
                    f"**{n}. {formatter.md_escape(q['text'])}**  \n"
                    + formatter.md_escape(q["model_answer"])
                )
                if q["credit"]:
                    st.caption(f"Question: {q['credit']}. Model answer: our own.")
        st.page_link(
            "views/credits.py", label="Question sources & credits", icon=":material/license:"
        )


def _pattern(pattern: dict | None) -> None:
    """A test pattern only when taken from the company's own page, with that link."""
    if not pattern:
        return
    with st.container(border=True):
        st.markdown("**Test pattern (from the company's official page)**")
        st.markdown("\n".join(f"- {formatter.md_escape(x)}" for x in pattern["sections"]))
        st.link_button("Official source", pattern["source_url"], icon=":material/open_in_new:")


def _take(sid: str, slug: str, quiz: experiences.PracticeQuiz) -> None:
    badge = BADGES[quiz.source]
    st.subheader(f"{quiz.company} · {EXPERIENCE_ROUNDS[quiz.round]}", anchor=False)
    st.markdown(badge)
    for note in quiz.notes:
        st.caption(formatter.md_escape(note))
    with st.form(f"cq_quiz_{slug}_{quiz.round}_{quiz.source}", border=False):
        chosen = []
        for n, (qid, q) in enumerate(quiz.questions, 1):
            with st.container(border=True):
                chosen.append(
                    st.radio(
                        f"**Q{n}.** {formatter.md_escape(q.text)}",
                        range(4),
                        format_func=lambda j, q=q: formatter.md_escape(q.options[j]),
                        index=None,
                        key=f"cq_{qid}",
                    )
                )
        done = st.form_submit_button("Submit", type="primary", icon=":material/done_all:")
    if st.button("Back to browsing", icon=":material/arrow_back:"):
        st.session_state.pop(QUIZ)
        st.rerun()
    if done:
        answers = [(qid, c) for (qid, _), c in zip(quiz.questions, chosen, strict=True)]
        try:
            graded = experiences.grade_practice(sid, slug, quiz.round, quiz.source, answers)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.session_state[RESULT] = (quiz, graded)
        st.session_state.pop(QUIZ)
        st.rerun()


def _result(quiz: experiences.PracticeQuiz, graded: dict) -> None:
    st.subheader(
        f"{quiz.company} practice: {graded['correct']} of {graded['total']} right", anchor=False
    )
    st.caption(
        "Company practice is kept apart: it does not change your topic levels or weekly plan."
    )
    for n, ((_, q), r) in enumerate(zip(quiz.questions, graded["review"], strict=True), 1):
        mark = ":green[:material/check:]" if r["is_correct"] else ":red[:material/close:]"
        right = r["correct_index"]
        answer = f"{LETTERS[right]}. {formatter.md_escape(q.options[right])}"
        st.markdown(
            f"{mark} **Q{n}.** {formatter.md_escape(q.text)}  \n"
            f"Answer: **{answer}**  \n:gray[{formatter.md_escape(r['explanation'])}]"
            + (f"  \n:gray[Source: {formatter.md_escape(r['credit'])}]" if r.get("credit") else "")
        )
    if st.button("Back to browsing", type="primary", icon=":material/arrow_back:"):
        st.session_state.pop(RESULT)
        st.rerun()


def _browse(sid: str, in_org: bool) -> None:
    overview = experiences.companies_overview()
    by_slug = {c["slug"]: c for c in overview}
    slug = st.selectbox(
        "Company",
        list(by_slug),
        format_func=lambda s: f"{by_slug[s]['name']} · {by_slug[s]['counts_line']}",
        help="Practice questions are general practice from the open question bank, not "
        "questions asked at that company.",
        key="cq_company",
    )
    rounds = list(EXPERIENCE_ROUNDS)
    round_ = st.segmented_control(
        "Round", rounds, format_func=EXPERIENCE_ROUNDS.__getitem__, key="cq_round"
    )
    detail = experiences.company_detail(slug, round_, sid)
    c = by_slug[slug]
    has_reports = detail["reported"]  # questions or an interview process
    # Posts and practice on the left, this company's share panel on the right (Streamlit has no
    # sticky columns; on a narrow screen the panel follows the posts).
    left, right = st.columns([3, 2], gap="large")
    with right:
        _panel(sid, in_org, detail["name"])
    with left:
        _company(sid, slug, round_, detail, c, has_reports)


def _company(sid: str, slug: str, round_: str | None, detail: dict, c: dict, has_reports: bool):
    """A company's posts, its interview process and practice."""
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(_rounds_line(c["rounds"]))
        if c["careers_url"]:
            st.link_button("Official careers page", c["careers_url"], icon=":material/open_in_new:")
    _pattern(detail["test_pattern"])
    _process_summary(detail["process"])
    if not has_reports:
        st.info(
            "No student reports for this company yet. Until there are, practise by round from "
            "the open question bank. Interviewed with them? Share it in the next tab.",
            icon=":material/forum:",
        )
        _open_practice(sid, slug, detail["open_practice"])
        return
    if round_:
        _practice(sid, slug, round_, detail)
    else:
        st.caption("Choose a round to practise it.")
    if not detail["posts"]:
        st.info("No approved posts for this round yet.", icon=":material/forum:")
    else:
        st.markdown("**Reported by students**")
    for p in detail["posts"]:
        _post(sid, p)
    if st.toggle("More practice: general practice by round (open question bank)", key="cq_more"):
        _open_practice(sid, slug, detail["open_practice"])  # it holds an expander: no nesting


def _question_inputs(prefix: str, n: int) -> list[dict]:
    """`n` questions in the student's own words: open, or multiple choice with the four options,
    the correct one and why (inside a form)."""
    questions = []
    for i in range(n):
        with st.container(border=True):
            text = st.text_area(f"Question {i + 1}", height=70, key=f"{prefix}_q_{i}")
            with st.expander("Multiple choice? Add the four options"):
                opts = [
                    st.text_input(f"Option {LETTERS[j]}", key=f"{prefix}_o_{i}_{j}")
                    for j in range(4)
                ]
                correct = st.selectbox(
                    "Correct option",
                    list(range(4)),
                    index=None,
                    format_func=LETTERS.__getitem__,
                    key=f"{prefix}_c_{i}",
                )
                explanation = st.text_input("Why (optional)", key=f"{prefix}_e_{i}")
            mcq = all(o.strip() for o in opts)
            questions.append(
                {
                    "kind": "mcq" if mcq else "open",
                    "text": text,
                    "options": opts if mcq else [],
                    "correct_index": correct if mcq else None,
                    "explanation": explanation,
                }
            )
    return questions


ROUND_LABELS = {v: k for k, v in PROCESS_ROUND_TYPES.items()}
DIFFICULTY_LABELS = {"Easy": "easy", "Medium": "medium", "Hard": "hard"}


def _rounds_from(table: pd.DataFrame) -> list[dict]:
    """The rounds table as the API takes it: in the order of its # column, blank rows left out."""
    out = []
    for _, row in table.sort_values("#", na_position="last").iterrows():
        if not isinstance(row["Round"], str) or not row["Round"]:
            continue
        minutes = row["Minutes"]
        out.append(
            {
                "type": ROUND_LABELS.get(row["Round"], row["Round"]),
                "minutes": None if pd.isna(minutes) else int(minutes),
                "difficulty": DIFFICULTY_LABELS.get(row["Difficulty"], row["Difficulty"] or ""),
            }
        )
    return out


def _panel(sid: str, in_org: bool, company: str) -> None:
    """ "Interviewed at <Company>? Share your experience": the company is this page's; questions
    (section 1), the interview process (section 2), or both; cleaned and moderated like every
    post."""
    with st.container(border=True):
        st.markdown(f"**Interviewed at {formatter.md_escape(company)}? Share your experience**")
        st.caption(
            "In your own words; names and contact details are removed. A moderator approves it "
            "before anyone sees it, and you are shown only as 'a student' with your batch year."
        )
        if shared := st.session_state.pop(PANEL_SHARED, None):
            note = f" Removed automatically: {', '.join(shared)}." if shared else ""
            st.success(
                f"Thanks! Waiting for a moderator's approval.{note}", icon=":material/check:"
            )
        n = int(
            st.number_input(
                "1. Questions to add", min_value=0, max_value=EXPERIENCE_MAX_QUESTIONS, value=1,
                key="cqp_n",
            )
        )  # fmt: skip
        with_process = st.checkbox("2. Add my interview process", key="cqp_with_process")
        with st.form("cqp_form", border=False, clear_on_submit=True):
            st.text_input("Company", value=company, disabled=True, help="Fixed to this page.")
            role = st.text_input("Role", placeholder="e.g. Systems Engineer")
            month = st.text_input(
                "Interview month", value=date.today().strftime("%Y-%m"), help="YYYY-MM"
            )
            round_ = None
            questions: list[dict] = []
            if n:
                st.markdown("**1. Add a question**")
                round_ = st.selectbox(
                    "Round", list(EXPERIENCE_ROUNDS), format_func=EXPERIENCE_ROUNDS.__getitem__
                )
                questions = _question_inputs("cqp", n)
            rounds = pd.DataFrame()
            if with_process:
                st.markdown("**2. Your interview process**")
                st.caption("One row per round. Number them in order; minutes are optional.")
                rounds = st.data_editor(
                    pd.DataFrame(
                        {
                            "#": [1, 2, 3],
                            "Round": ["Online test", "Technical", "HR"],
                            "Minutes": [None, None, None],
                            "Difficulty": ["Medium", "Medium", "Easy"],
                        }
                    ),
                    num_rows="dynamic",
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "#": st.column_config.NumberColumn(min_value=1, max_value=8, step=1),
                        "Round": st.column_config.SelectboxColumn(
                            options=list(PROCESS_ROUND_TYPES.values()), required=True
                        ),
                        "Minutes": st.column_config.NumberColumn(
                            min_value=5, max_value=480, step=5
                        ),
                        "Difficulty": st.column_config.SelectboxColumn(
                            options=list(DIFFICULTY_LABELS), required=True
                        ),
                    },
                    key="cqp_rounds",
                )
                result = st.selectbox(
                    "Result", list(PROCESS_RESULTS), format_func=PROCESS_RESULTS.__getitem__
                )
                summary = st.text_area("A short summary", height=80, max_chars=600)
            tip = st.text_area("A tip for juniors (optional)", height=70)
            show_college = (
                st.checkbox("Show my college with my batch year", value=True) if in_org else False
            )
            sent = st.form_submit_button("Share", type="primary", icon=":material/send:")
        if sent:
            form = {
                "company": company,
                "role": role,
                "round": round_ or "",
                "interview_month": month,
                "tip": tip,
                "show_college": show_college,
                "questions": [q for q in questions if q["text"].strip()],
                "process": (
                    {"rounds": _rounds_from(rounds), "result": result, "summary": summary}
                    if with_process
                    else None
                ),
            }
            try:
                s = experiences.submit(sid, form)
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
                return
            st.session_state[PANEL_SHARED] = s.removed
            st.rerun()


def _round_text(r: dict) -> str:
    minutes = f" ({r['minutes']} min)" if r["minutes"] else ""
    return f"{r['label']}{minutes}, {r['difficulty']}"


def _process_summary(summary: dict) -> None:
    """ "Interview process (from N reports)"."""
    if not summary.get("reports"):
        return
    n = summary["reports"]
    with st.container(border=True):
        st.markdown(f"**:material/format_list_numbered: Interview process (from {n} report"
                    f"{'s' if n != 1 else ''})**")  # fmt: skip
        spread = summary["difficulty"]
        total = sum(spread.values()) or 1
        st.markdown(
            f"Most common round order: **{' → '.join(summary['common_order'])}** "
            f"({summary['common_order_reports']} of {n})  \n"
            f"Average number of rounds: **{summary['average_rounds']}**  \n"
            "Difficulty across all rounds: "
            + " · ".join(f"{d.title()} {round(100 * c / total)}%" for d, c in spread.items())
            + "  \nResults reported: "
            + " · ".join(f"{k} {v}" for k, v in summary["results"].items())
        )
        for s in summary["summaries"]:
            order = " → ".join(_round_text(r) for r in s["rounds"])
            st.markdown(
                f":orange-badge[:material/person: Reported by {formatter.md_escape(s['label'])}] "
                f"**{formatter.md_escape(s['role'])}** · {s['interview_month']} · "
                f"{s['result_label']}  \n:gray[{formatter.md_escape(order)}]"
                + (f"  \n{formatter.md_escape(s['summary'])}" if s["summary"] else "")
                + (f"  \n:gray[Tip: {formatter.md_escape(s['tip'])}]" if s["tip"] else "")
            )


def _share(sid: str, in_org: bool) -> None:
    if shared := st.session_state.pop(SHARED, None):
        removed = shared[1]
        note = f" Removed automatically: {', '.join(removed)}." if removed else ""
        st.success(
            f"Thanks! Your post is waiting for a moderator's approval.{note}",
            icon=":material/check_circle:",
        )
    st.caption(
        "Write the questions in your own words, as you remember them. Do not paste from websites, "
        "and leave out names and contact details (they are removed anyway). You are shown only as "
        "'a student' with your batch year"
        + (" (and your college, once enough of your batch have shared)." if in_org else ".")
    )
    n = int(
        st.number_input(
            "How many questions",
            min_value=1,
            max_value=EXPERIENCE_MAX_QUESTIONS,
            value=3,
            key="cq_n",
        )
    )
    with st.form("cq_share", border=False, clear_on_submit=True):
        c1, c2 = st.columns(2, gap="medium")
        company = c1.text_input(
            "Company",
            placeholder="e.g. TCS, Infosys, Zoho",
            help=f"Known: {', '.join(c['name'] for c in experience_checks.companies()[:12])}, ...",
        )
        role = c2.text_input("Role", placeholder="e.g. Systems Engineer")
        c3, c4 = st.columns(2, gap="medium")
        round_ = c3.selectbox(
            "Round", list(EXPERIENCE_ROUNDS), format_func=EXPERIENCE_ROUNDS.__getitem__
        )
        month = c4.text_input(
            "Month of the interview", value=date.today().strftime("%Y-%m"), help="YYYY-MM"
        )
        questions = _question_inputs("cq", n)
        tip = st.text_area("A tip for juniors (optional)", height=70)
        show_college = (
            st.checkbox("Show my college with my batch year", value=True) if in_org else False
        )
        sent = st.form_submit_button("Share my interview", type="primary", icon=":material/send:")
    if sent:
        form = {
            "company": company,
            "role": role,
            "round": round_,
            "interview_month": month,
            "tip": tip,
            "show_college": show_college,
            "questions": [q for q in questions if q["text"].strip()],
        }
        try:
            s = experiences.submit(sid, form)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.session_state[SHARED] = (s.id, s.removed)
        st.rerun()


STATUS = {
    "pending": ":blue-badge[Waiting for review]",
    "approved": ":green-badge[Published]",
    "rejected": ":red-badge[Not published]",
    "hidden": ":orange-badge[Hidden after reports]",
}


def _mine(sid: str) -> None:
    posts = experiences.my_posts(sid)
    if not posts:
        st.caption("You have not shared an interview yet.")
    for p in posts:
        reason = (
            f"  \n:gray[Moderator: {formatter.md_escape(p['reject_reason'])}]"
            if p["reject_reason"]
            else ""
        )
        st.markdown(
            f"{STATUS[p['status']]} **{formatter.md_escape(p['company'])}** · "
            f"{formatter.md_escape(p['role'])} · {EXPERIENCE_ROUNDS[p['round']]} · "
            f"{p['interview_month']} · {p['questions']} questions"
            f"{' · interview process' if p['process'] else ''}{reason}"
        )


page_header(
    "Company questions",
    "Interview questions students reported from their own interviews, in their own words, by "
    "company and round. Practise them, or practise with AI questions in a company's style "
    "(always marked AI). Nothing here is copied from another website.",
)
sid, profile = require_profile()
student = services.student_row(sid)

if result := st.session_state.get(RESULT):
    _result(*result)
elif taking := st.session_state.get(QUIZ):
    _take(sid, *taking)
else:
    browse_tab, share_tab, mine_tab = st.tabs(
        [
            ":material/apartment: Browse",
            ":material/edit_note: Share your interview",
            ":material/history: My posts",
        ]
    )
    with browse_tab:
        _browse(sid, bool(student and student["org_id"]))
    with share_tab:
        _share(sid, bool(student and student["org_id"]))
    with mine_tab:
        _mine(sid)
