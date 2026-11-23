"""Question sources and credits: where every practice question comes from, under which licence,
and what we changed (data/questions/sources.json; full licence texts in LICENSES.md)."""

import streamlit as st

from piq import formatter, open_questions, question_bank
from piq.ui import page_header

page_header(
    "Question sources & credits",
    "Where the practice questions come from, under which licence, and what we changed. Open "
    "questions are general practice: none is presented as asked at any company.",
)

page = open_questions.credits_page(question_bank.counts_by_source())
for s in page["sources"]:
    with st.container(border=True):
        st.markdown(f"**{formatter.md_escape(s['name'])}**")
        licence = (
            f"[{s['licence_name']}]({s['licence_url']})" if s["licence_url"] else s["licence_name"]
        )
        st.markdown(
            f"Licence: {licence} · {s['multiple_choice']:,} multiple-choice and "
            f"{s['interview']} interview questions in use"
        )
        st.caption(formatter.md_escape(s["attribution"]))
        if s["modifications"]:
            st.caption("Modified: " + formatter.md_escape("; ".join(s["modifications"])) + ".")
        if s["homepage"]:
            pinned = f" · pinned at `{s['commit'][:12]}`" if s["commit"] else ""
            st.markdown(f"[Source repository]({s['homepage']}){pinned}")

st.subheader("What is never used", anchor=False)
st.markdown(
    "No questions are taken from Quora, Medium, LinkedIn, Glassdoor, PracHub, LeetCode problem "
    "text or copyrighted books. On company pages, **Reported by students** marks students' own "
    "words, approved by a moderator; **General practice (open question bank)** marks questions "
    "from the sources above."
)
st.caption(
    "Full licence texts and attributions: data/questions/LICENSES.md in the project's repository. "
    "Every question records its source, its licence and whether we modified it."
)
