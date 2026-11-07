"""Step 2, resume scan: read a resume against a target role and diagnose the skill gaps
(agents/resume_parser_agent.py). Each scan is recorded for the faculty dashboard."""

import streamlit as st

from piq import formatter, journey
from piq.services import ServiceError
from piq.ui import Stat, page_header, require_profile, stat_row

SCAN = "scan"  # the last Scan, per student (piq.ui.PER_STUDENT_KEYS)

page_header(
    "Resume scan and skill gaps",
    "Check a resume against a target role: the required skills it names in words, the ones "
    "it is missing, and the qualification and stream it shows.",
)
sid, _ = require_profile()
me = journey.student(sid)

with st.container(border=True):
    streams = journey.streams()
    stream = st.pills("Stream", streams, default=me.stream if me.stream in streams else streams[0])
    stream = stream or me.stream  # a click on the selected pill clears it
    domains = journey.domains_in(stream) or journey.domains_in(me.stream)
    names = [name for _, name in domains]
    domain_id, _ = st.selectbox(
        "Career domain",
        domains,
        index=names.index(me.domain) if me.domain in names else 0,
        format_func=lambda d: d[1],
    )
    roles = journey.roles_in(domain_id)
    role = st.selectbox(
        "Target role", roles, index=roles.index(me.target_role) if me.target_role in roles else 0
    )
    source = st.segmented_control(
        "Resume", ["Upload a file", "Use a sample"], default="Upload a file", key="scan_source"
    )
    upload = sample = None
    if source == "Use a sample":
        sample = st.selectbox("Sample resume", journey.sample_names())
    else:
        upload = st.file_uploader(
            "Resume (PDF, DOCX or TXT, up to 5 MB)", type=["pdf", "docx", "txt"]
        )
    if st.button("Scan resume", type="primary", icon=":material/document_scanner:"):
        try:
            if sample:
                name, data = sample, journey.read_sample(sample)
            else:
                name, data = (upload.name, upload.getvalue()) if upload else ("", b"")
            with st.spinner("Reading the resume"):
                st.session_state[SCAN] = journey.scan_resume(sid, name, data, role)
            journey.preload_next_steps(sid)  # roadmap, quiz and voice, in the background
        except ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")

scan: journey.Scan | None = st.session_state.get(SCAN)
if scan is None:  # a new session (reload, or back after signing out): the last saved scan
    saved = journey.saved_scan(sid)
    if saved is None:
        st.caption("No scan yet. Pick the role, add a resume and press Scan resume.")
        st.stop()
    st.subheader(f"Your last saved scan: {saved.match_percentage:.0f}% match", anchor=False)
    found, missing = st.columns(2, gap="medium")
    with found, st.container(border=True, height="stretch"):
        st.markdown("**:material/check_circle: Found in the resume**")
        st.markdown(
            "\n".join(f"- {formatter.md_escape(s)}" for s in saved.matched) or ":gray[None.]"
        )
    with missing, st.container(border=True, height="stretch"):
        st.markdown("**:material/cancel: Missing: your skill gaps**")
        st.markdown(
            "\n".join(f"- {formatter.md_escape(s)}" for s in saved.missing) or ":gray[None.]"
        )
    if saved.missing and st.button(
        "Build a 7-day roadmap for these gaps", icon=":material/route:", key="saved_roadmap"
    ):
        st.session_state["roadmap_gaps"] = list(saved.missing)
        st.switch_page("views/roadmap.py")
    st.stop()

a = scan.analysis
st.subheader(f"{formatter.md_escape(a.target_role)}: {a.match_percentage:.0f}% match", anchor=False)
stat_row(
    [
        Stat("Role match", f"{a.match_percentage:.0f}%"),
        Stat("Required skills found", f"{len(a.matched_skills)} of {len(a.required_skills)}"),
        Stat("Skill gaps", str(len(a.missing_gap_skills))),
        Stat("Qualification", a.degree.code if a.degree else "Not found"),
    ]
)
st.markdown(
    f":gray[Detected qualification and stream: {formatter.md_escape(a.detected_stream or 'none')}. "
    f"Read {a.extracted_text_length:,} characters from {formatter.md_escape(a.filename)}.]"
)

found, missing = st.columns(2, gap="medium")
with found, st.container(border=True, height="stretch"):
    st.markdown("**:material/check_circle: Found in the resume**")
    st.markdown(
        "\n".join(f"- {formatter.md_escape(s)}" for s in a.matched_skills)
        or ":gray[None of the required skills is named.]"
    )
with missing, st.container(border=True, height="stretch"):
    st.markdown("**:material/cancel: Missing: your skill gaps**")
    st.markdown(
        "\n".join(f"- {formatter.md_escape(s)}" for s in a.missing_gap_skills)
        or ":gray[Nothing missing: every required skill is named.]"
    )

if not scan.saved:
    st.warning(
        "This scan could not be saved for the faculty dashboard. Your result above is complete.",
        icon=":material/cloud_off:",
    )
if a.missing_gap_skills and st.button(
    "Build a 7-day roadmap for these gaps", icon=":material/route:"
):
    st.session_state["roadmap_gaps"] = list(a.missing_gap_skills)
    st.switch_page("views/roadmap.py")
