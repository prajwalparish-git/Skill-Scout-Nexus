"""Contribute a question to the open bank (piq/contributions.py): a multiple-choice question with
its answer and explanation, or an open question with a model answer, published under CC BY 4.0;
your contributions and their status; opt-in credit; the season's top contributors."""

import streamlit as st

from piq import contributions, formatter, services
from piq.ui import page_header

STATUS = {
    "pending": ":blue-badge[Waiting for review]",
    "approved": ":green-badge[Published]",
    "rejected": ":red-badge[Not published]",
    "hidden": ":orange-badge[Hidden]",
}
LETTERS = "ABCD"
DONE = "contrib_done"  # personal data kinds removed from the last contribution

page_header(
    "Contribute a question",
    "Placed students, alumni and professionals: add an aptitude, technical or HR question with "
    "its answer, in your own words. A moderator checks it, then it helps every student practise. "
    "Published under CC BY 4.0; anonymous unless you choose a display name.",
)
sid = st.session_state.get("student_id")
if not sid:
    st.stop()


def _form() -> None:
    if (removed := st.session_state.pop(DONE, None)) is not None:
        note = f" Removed automatically: {', '.join(removed)}." if removed else ""
        st.success(f"Thanks! Waiting for a moderator's approval.{note}", icon=":material/check:")
    c1, c2, c3 = st.columns(3)
    round_ = c1.selectbox(
        "Round", list(contributions.ROUNDS), format_func=contributions.ROUNDS.__getitem__,
        key="contrib_round",
    )  # fmt: skip
    topic = c2.selectbox("Topic", contributions.topics(round_), key=f"contrib_topic_{round_}")
    difficulty = c3.selectbox(
        "Difficulty", ["easy", "medium", "hard"], index=1, format_func=str.title,
        key="contrib_difficulty",
    )  # fmt: skip
    kinds = ["open"] if round_ == "hr" else ["mcq", "open"]
    kind = (
        st.segmented_control(
            "Kind",
            kinds,
            default=kinds[0],
            format_func={"mcq": "Multiple choice", "open": "Open question"}.__getitem__,
            key=f"contrib_kind_{round_}",
        )
        or kinds[0]
    )
    with st.form("contrib_form", clear_on_submit=True):
        text = st.text_area("Question", height=90, max_chars=1000)
        options, correct, explanation, model_answer = [], None, "", ""
        if kind == "mcq":
            cols = st.columns(2)
            options = [cols[j % 2].text_input(f"Option {LETTERS[j]}") for j in range(4)]
            correct = st.radio(
                "Correct option", range(4), format_func=LETTERS.__getitem__, horizontal=True,
                index=None,
            )  # fmt: skip
            explanation = st.text_area("Explanation", height=80, max_chars=1000)
        else:
            model_answer = st.text_area(
                "Model answer (at least 80 characters)", height=140, max_chars=2000
            )
        st.info(f"**Licence: CC BY 4.0.** {contributions.LICENCE_NOTE}", icon=":material/license:")
        accepted = st.checkbox("I wrote this question myself and publish it under CC BY 4.0.")
        sent = st.form_submit_button("Send for review", type="primary", icon=":material/send:")
    if sent:
        form = {
            "kind": kind,
            "round": round_,
            "topic": topic,
            "difficulty": difficulty,
            "text": text,
            "options": options,
            "correct_index": correct,
            "explanation": explanation,
            "model_answer": model_answer,
            "licence_accepted": accepted,
        }
        try:
            c = contributions.submit(sid, form)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.session_state[DONE] = c.removed
        st.rerun()


def _mine() -> None:
    st.subheader("My contributions", anchor=False)
    rows = contributions.mine(sid)
    if not rows:
        st.caption("Nothing yet.")
    for c in rows:
        reason = (
            f"  \n:gray[Moderator: {formatter.md_escape(c['reject_reason'])}]"
            if c["reject_reason"]
            else ""
        )
        st.markdown(
            f"{STATUS[c['status']]} :gray[{contributions.ROUNDS[c['round']]} · "
            f"{formatter.md_escape(c['topic'])} · {c['difficulty']} · {c['licence']}]  \n"
            f"{formatter.md_escape(c['text'])}{reason}"
        )


def _credit() -> None:
    p = contributions.profile(sid)
    with st.container(border=True):
        st.markdown("**How you are credited**")
        if p["badge"]:
            st.markdown(f":green-badge[:material/military_tech: {p['badge']}]")
        st.markdown(
            f"{p['approved']} approved question{'s' if p['approved'] != 1 else ''}. "
            f"Shown as **{formatter.md_escape(p['shown_as'])}**."
        )
        with st.form("contrib_credit", border=False):
            opt = st.checkbox("Credit me by a display name", value=p["credit_opt_in"])
            name = st.text_input("Display name", value=p["display_name"], max_chars=40)
            st.caption(
                "Off by default: you are 'an anonymous contributor' until you choose a name."
            )
            if st.form_submit_button("Save"):
                try:
                    contributions.set_credit(sid, opt, name)
                    st.toast("Saved.", icon=":material/check:")
                    st.rerun()
                except services.ServiceError as e:
                    st.error(formatter.md_escape(str(e)), icon=":material/error:")


def _board() -> None:
    board = contributions.leaderboard()
    with st.container(border=True):
        st.markdown(f"**:material/emoji_events: Top contributors this season ({board['season']})**")
        if not board["top"]:
            st.caption("No credited contributions yet this season. Be the first.")
        for n, t in enumerate(board["top"], 1):
            st.markdown(f"{n}. {formatter.md_escape(t['name'])} · :gray[{t['approved']} approved]")
        st.caption("Only contributors who chose to be credited are listed.")


left, right = st.columns([3, 2], gap="large")
with left:
    _form()
    _mine()
with right:
    _credit()
    _board()
