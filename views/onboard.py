"""Onboard: analyse a resume against a target role for a readiness score, the skills that
are there and missing, and what to fix on the resume."""

import streamlit as st

from piq import charts, formatter, journey, services
from piq.ui import current_student, page_header, run_agent, set_student, show_last_run

CONFIRM = "onboard_confirm"  # a submission waiting for "Replace their profile"
DELETE = "onboard_delete"  # the delete dialog is open
NEXT = (
    ("badge", "Enter your USN and the role you are aiming for."),
    ("upload_file", "Upload your resume, or pick a sample to try the app."),
    (
        "fact_check",
        "The profile agent reads it and a critic checks the result. You get a readiness "
        "score, the skills to work on and fixes for the resume.",
    ),
)


def _roles(profile: services.StudentProfile | None, key: str) -> tuple[list[str], int]:
    """The domain picker (outside the form, so the role list follows it at once) and the
    roles it offers. A student whose domain is locked keeps it."""
    lock = services.locked_domain(st.session_state.get("student_id")) if profile else None
    domains = list(services.domains())
    if lock:
        domain = lock.domain
        st.markdown(formatter.locked_md(domain.name, lock.since))
    else:
        current = services.domain_of_role(profile.target_role).id if profile else domains[0].id
        index = next((i for i, d in enumerate(domains) if d.id == current), 0)
        domain = st.selectbox(
            "Career domain", domains, index=index, format_func=lambda d: d.name, key=key
        )
    roles = services.domain_roles(domain.id)
    role_index = roles.index(profile.target_role) if profile and profile.target_role in roles else 0
    return roles, role_index


def _form(profile: services.StudentProfile | None, key: str) -> None:
    """The resume form; a valid submission runs the profile agent and opens the profile."""
    roles, role_index = _roles(profile, key)
    with st.form(f"onboard_{key}", border=False):
        usn = st.text_input(
            "USN (required)",
            value=(current_student() or {}).get("usn", ""),
            placeholder="For example 1DB22CS001",
        )
        role = st.selectbox("Target role", roles, index=role_index)
        st.caption("Use one: upload your resume, or pick a sample to try the app.")
        upload = st.file_uploader("Resume file", type=["pdf", "docx", "txt"])
        sample = st.selectbox(
            "…or use a sample resume", ["—", *services.sample_resumes()], key="onboard_sample"
        )
        submitted = st.form_submit_button(
            "Analyse resume", type="primary", icon=":material/fact_check:"
        )
    _confirm_replace()
    if not submitted:
        return
    try:
        usn = services.normalise_usn(usn)
        if upload:
            text = services.read_resume(upload.name, upload.getvalue())
        elif sample != "—":
            text = services.load_sample(sample)
        else:
            raise services.ServiceError("Upload a resume or pick a sample.")
        owner = services.usn_owner(usn)
    except (services.ServiceError, services.ResumeError) as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return
    if owner and owner["id"] != st.session_state.get("student_id"):
        st.session_state[CONFIRM] = {
            "usn": usn,
            "role": role,
            "text": text,
            "name": owner["name"],
            "owner_role": owner["target_role"],
        }
        st.rerun()
    _analyse(usn, role, text)


def _analyse(usn: str, role: str, text: str) -> None:
    result = run_agent("Profile agent", lambda ev: services.onboard(usn, role, text, ev))
    if result:
        journey.record_student(result[0])  # telemetry, for the faculty dashboard; best-effort
        journey.preload_next_steps(result[0])  # roadmap, quiz and voice, in the background
        set_student(result[0], keep_runs=("Profile agent",), fresh=True)
        st.rerun()


def _confirm_replace() -> None:
    """A USN typed for a new student that belongs to someone else: say whose it is, and save
    only on an explicit yes (saving would replace that student's profile and name)."""
    pending = st.session_state.get(CONFIRM)
    if not pending:
        return
    st.warning(
        formatter.usn_taken_md(pending["usn"], pending["name"], pending["owner_role"]),
        icon=":material/warning:",
    )
    with st.container(horizontal=True):
        replace = st.button("Replace their profile", type="primary", icon=":material/sync:")
        cancel = st.button("Cancel")
    if cancel:
        st.session_state.pop(CONFIRM)
        st.rerun()
    if replace:
        st.session_state.pop(CONFIRM)
        _analyse(pending["usn"], pending["role"], pending["text"])


def _close_delete() -> None:
    st.session_state.pop(DELETE, None)


# Open while the session flag is set, so a full rerun does not close it half-way; dismissing
# it (X, Esc, a click outside) clears the flag.
@st.dialog("Delete student", icon=":material/delete:", on_dismiss=_close_delete)
def _delete(student: dict) -> None:
    """Delete only after the USN is typed: the history cannot be brought back."""
    st.markdown(formatter.delete_warning_md(student["usn"], student["name"]))
    typed = st.text_input("Type the USN to confirm", placeholder=student["usn"])
    if st.button("Delete for good", type="primary", icon=":material/delete_forever:"):
        try:
            services.delete_student(student["id"], typed)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        _close_delete()
        set_student(None)
        st.switch_page("views/home.py")


def _readiness_card(profile: services.StudentProfile) -> None:
    score = profile.readiness_score
    domain = services.domain_of_role(profile.target_role)
    with st.container(border=True):
        st.subheader(formatter.md_escape(profile.name), anchor=False)
        st.markdown(formatter.syllabus_line(domain.name, profile.target_role))
        # A row even on a phone: the ring is a picture of the number beside it.
        with st.container(horizontal=True, vertical_alignment="center", gap="large"):
            st.metric(
                "Readiness",
                f"{score}/100",
                help=(
                    "How much of the target role's skill list the resume names in words. "
                    "Skills the syllabus tests count double; tools count once."
                ),
                width="content",
            )
            st.vega_lite_chart(
                spec=charts.readiness_ring_spec(score),
                width="content",
                alt=f"Readiness {score} out of 100",
            )
        st.caption(formatter.readiness_summary(profile))
        st.markdown("**On the resume**")
        st.markdown(
            formatter.skill_chips(profile.matched_skills, present=True) or ":gray[None yet.]"
        )
        st.markdown("**Missing for this role**")
        st.markdown(
            formatter.skill_chips(profile.missing_skills, present=False)
            or ":gray[None: the resume shows every skill this role needs.]"
        )
        st.markdown("**Topics you will practise**")
        st.html(formatter.topic_chips_html(services.focus_topics(profile.target_role)))
        st.caption(
            "Your plans and quizzes use these; the Quiz page offers the rest of your domain."
        )


def _resume_card(profile: services.StudentProfile) -> None:
    with st.container(border=True):
        st.subheader("From the resume", anchor=False)
        st.markdown(f"**Education**  \n{formatter.md_escape(profile.education)}")
        for title, items in (("Projects", profile.projects), ("Internships", profile.internships)):
            st.markdown(f"**{title}**  \n{formatter.list_md(items, 'None listed.')}")
        st.markdown(f"**Resume fixes**  \n{formatter.fixes_md(profile.resume_feedback)}")


profile = services.current_profile(st.session_state.get("student_id"))

page_header(
    "Onboard",
    "Analyse a resume against a target role: readiness, the skills it shows and lacks, and "
    "what to fix.",
)

if profile is None:
    form_col, next_col = st.columns([2, 3], gap="medium")
    with form_col, st.container(border=True):
        st.subheader("New student", anchor=False)
        _form(None, "new")
    with next_col, st.container(border=True):
        st.subheader("What happens next", anchor=False)
        for n, (icon, text) in enumerate(NEXT, 1):
            st.markdown(f":primary[:material/{icon}:] **{n}.** {text}")
else:
    # A returning student came to read their profile, so it leads (first on a phone) and
    # re-profiling waits behind one click.
    readiness_col, resume_col = st.columns(2, gap="medium")
    with readiness_col:
        _readiness_card(profile)
    with resume_col:
        _resume_card(profile)
        show_last_run("Profile agent")
        with st.expander("Re-profile with a new resume", icon=":material/refresh:"):
            _form(profile, "again")
        if st.button("Delete this student", type="tertiary", icon=":material/delete:"):
            st.session_state[DELETE] = True
        if st.session_state.get(DELETE) and (student := current_student()):
            _delete(student)
