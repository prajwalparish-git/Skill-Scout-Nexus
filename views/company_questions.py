"""Company questions: interview questions students reported from their own interviews, by
company and round, in their own words (nothing copied from any website). Browse approved posts,
practise them (reported multiple-choice questions as a quiz, open ones as a mock interview), or
practise with AI questions in a company's style, always marked as AI. Share your own interview:
it is cleaned of personal details and appears once a moderator approves it."""

from datetime import date

import streamlit as st

from piq import experience_checks, experiences, formatter, services
from piq.config import EXPERIENCE_MAX_QUESTIONS, EXPERIENCE_ROUNDS
from piq.ui import page_header, require_profile, run_agent

QUIZ = "cq_quiz"  # (company slug, PracticeQuiz) being taken
RESULT = "cq_result"  # (PracticeQuiz, graded) just submitted
SHARED = "cq_shared"  # the last post shared: (id, removed kinds)
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


def _take(sid: str, slug: str, quiz: experiences.PracticeQuiz) -> None:
    ai = quiz.source == "ai"
    badge = (
        ":violet-badge[:material/smart_toy: AI practice, not reported by a student]"
        if ai
        else ":orange-badge[:material/person: Reported by students]"
    )
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
        )
    if st.button("Back to browsing", type="primary", icon=":material/arrow_back:"):
        st.session_state.pop(RESULT)
        st.rerun()


def _browse(sid: str) -> None:
    overview = experiences.companies_overview()
    by_slug = {c["slug"]: c for c in overview}
    slug = st.selectbox(
        "Company",
        list(by_slug),
        format_func=lambda s: f"{by_slug[s]['name']} · {by_slug[s]['posts']} posts",
        key="cq_company",
    )
    rounds = list(EXPERIENCE_ROUNDS)
    round_ = st.segmented_control(
        "Round", rounds, format_func=EXPERIENCE_ROUNDS.__getitem__, key="cq_round"
    )
    detail = experiences.company_detail(slug, round_)
    c = by_slug[slug]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(_rounds_line(c["rounds"]))
        if c["careers_url"]:
            st.link_button("Official careers page", c["careers_url"], icon=":material/open_in_new:")
    if round_:
        _practice(sid, slug, round_, experiences.company_detail(slug, round_))
    else:
        st.caption("Choose a round to practise it.")
    if not detail["posts"]:
        st.info(
            "No approved posts here yet. Interviewed with them? Share it in the next tab.",
            icon=":material/forum:",
        )
    for p in detail["posts"]:
        _post(sid, p)


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
        questions = []
        for i in range(n):
            with st.container(border=True):
                text = st.text_area(f"Question {i + 1}", height=70, key=f"cq_q_{i}")
                with st.expander("Multiple choice? Add the four options"):
                    opts = [
                        st.text_input(f"Option {LETTERS[j]}", key=f"cq_o_{i}_{j}") for j in range(4)
                    ]
                    correct = st.selectbox(
                        "Correct option",
                        list(range(4)),
                        index=None,
                        format_func=LETTERS.__getitem__,
                        key=f"cq_c_{i}",
                    )
                    explanation = st.text_input("Why (optional)", key=f"cq_e_{i}")
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
            f"{p['interview_month']} · {p['questions']} questions{reason}"
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
        _browse(sid)
    with share_tab:
        _share(sid, bool(student and student["org_id"]))
    with mine_tab:
        _mine(sid)
