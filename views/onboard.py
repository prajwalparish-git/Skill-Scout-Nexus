"""Onboard. Signed out, two ways in: Student / Learner access (sign in with a password then a
9-digit code from email, create an account, or recover one) and Organization admin access
(sign in, create an organization, or recover the admin account).
Signed in: analyse a resume against a target role for a readiness score, the skills that are
there and missing, and what to fix."""

from collections.abc import Callable

import streamlit as st

from piq import accounts, charts, formatter, journey, orgs, services
from piq.config import CONSENT_TEXT, ORG_TYPES
from piq.ui import (
    SUSPENDED_NOTICE,
    count_wrong_try,
    current_device,
    current_student,
    page_header,
    risky_browser,
    run_agent,
    set_student,
    show_last_run,
    sign_in,
    sign_in_admin,
)

DELETE = "onboard_delete"  # the delete dialog is open
PENDING = "auth_pending"  # accounts.Pending: a code is on its way (ui.AUTH_PREFIX keys)
ADMIN_PENDING = "auth_admin_pending"  # orgs.AdminPending: the admin's code is on its way
NOTICE = "auth_notice"  # a message for the next run of the sign-in page
NEXT = (
    ("upload_file", "Upload your resume, or pick a sample to try the app."),
    (
        "fact_check",
        "The profile agent reads it and a critic checks the result. You get a readiness "
        "score, the skills to work on and fixes for the resume.",
    ),
    ("route", "Your roadmap, first quiz and voice questions are prepared while you read it."),
)


# --- signed out ---------------------------------------------------------------------------------


def _roles_for(role: str | None, key: str) -> tuple[list[str], int]:
    """A domain picker (outside any form, so the role list follows it at once) and its roles."""
    domains = list(services.domains())
    current = services.domain_of_role(role).id if role else domains[0].id
    index = next((i for i, d in enumerate(domains) if d.id == current), 0)
    domain = st.selectbox(
        "Career domain", domains, index=index, format_func=lambda d: d.name, key=key
    )
    roles = services.domain_roles(domain.id)
    return roles, roles.index(role) if role in roles else 0


def _start_code_step(action: Callable[[], accounts.Pending | str]) -> None:
    """Run a sign-in step: a student id signs them in at once (the password was enough, or
    local mode), a Pending asks for the emailed code."""
    try:
        result = action()
    except services.ServiceError as e:
        if str(e) == accounts.WRONG_LOGIN:
            count_wrong_try()
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return
    if isinstance(result, str):
        sign_in(result)
    else:
        st.session_state[PENDING] = result
    st.rerun()


def _sign_in_tab() -> None:
    with st.form("auth_login", border=False):
        who = st.text_input("Username or email", autocomplete="username", key="auth_who")
        password = st.text_input(
            "Password", type="password", autocomplete="current-password", key="auth_pw"
        )
        go = st.form_submit_button("Sign in", type="primary", icon=":material/login:")
    if go:
        _start_code_step(
            lambda: accounts.start_login(
                who, password, risky=risky_browser(), device=current_device()
            )
        )


def _sign_up_tab() -> None:
    roles, index = _roles_for(None, "auth_domain")
    with st.form("auth_signup", border=False):
        name = st.text_input("Your name", autocomplete="name", key="auth_su_name")
        left, right = st.columns(2)
        username = left.text_input(
            "Username", help="3-20 lower-case letters or digits.", key="auth_su_user"
        )
        email = right.text_input("Email", autocomplete="email", key="auth_su_email")
        role = st.selectbox("Target role", roles, index=index, key="auth_su_role")
        left, right = st.columns(2)
        password = left.text_input(
            "Password", type="password", autocomplete="new-password", key="auth_su_pw"
        )
        confirm = right.text_input(
            "Repeat it", type="password", autocomplete="new-password", key="auth_su_pw2"
        )
        st.caption("At least 8 characters, with letters and digits.")
        consent = st.checkbox(CONSENT_TEXT, value=False, key="auth_su_consent")
        go = st.form_submit_button("Create account", type="primary", icon=":material/person_add:")
    if go and not consent:
        st.error("Tick the consent box to create an account.", icon=":material/error:")
        return
    if go:
        _start_code_step(
            lambda: accounts.sign_up(
                name, username, email, password, confirm, role or "", device=current_device()
            )
        )


def _recover_tab() -> None:
    with st.form("auth_recover", border=False):
        who = st.text_input("Your account's email or username", key="auth_rec_who")
        st.caption("We email a 9-digit code; with it you set a new password.")
        go = st.form_submit_button("Send recovery code", type="primary", icon=":material/key:")
    if go:
        _start_code_step(lambda: accounts.start_recovery(who))


def _code_step(pending: accounts.Pending) -> None:
    """Step 2: the 9-digit code (and, to recover, the new password)."""
    recovering = pending.purpose == "recover"
    st.subheader(
        "Set a new password" if recovering else "Check your email",
        anchor=False,
        icon=":material/mark_email_read:",
    )
    where = f" to **{formatter.md_escape(pending.sent_to)}**" if pending.sent_to != "***" else ""
    if pending.welcome:
        st.markdown(
            "Enter the **9-digit code from your welcome email**. It works once, for seven days "
            "from when your organization set up your account. Lost it? Send a new code."
        )
    else:
        st.markdown(
            (
                f"If that account exists, we sent a 9-digit code{where}. "
                if recovering
                else f"We sent a 9-digit code{where}. "
            )
            + "It works once, for 10 minutes."
        )
    if pending.outbox:
        st.caption(
            ":material/inbox: Dev/offline mode: the 9-digit code was delivered to the local "
            "outbox (data/.mail_outbox.log). Add SMTP_EMAIL and SMTP_APP_PASSWORD to .env to "
            "email it."
        )
    with st.form("auth_code", border=False):
        typed = st.text_input(
            "9-digit code", max_chars=11, placeholder="123-456-789", key="auth_code"
        )
        if recovering:
            left, right = st.columns(2)
            password = left.text_input("New password", type="password", key="auth_new_pw")
            confirm = right.text_input("Repeat it", type="password", key="auth_new_pw2")
        go = st.form_submit_button(
            "Set password and sign in" if recovering else "Verify and sign in",
            type="primary",
            icon=":material/verified_user:",
        )
    with st.container(horizontal=True):
        again = st.button("Send a new code", icon=":material/refresh:", key="auth_resend")
        back = st.button("Back", type="tertiary", key="auth_back")
    if back:
        st.session_state.pop(PENDING, None)
        st.rerun()
    if again:
        try:
            st.session_state[PENDING] = accounts.resend_code(pending)
            st.toast("A new code is on its way.", icon=":material/mail:")
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
    if go:
        try:
            if recovering:
                sid = accounts.finish_recovery(pending, typed, password, confirm)
            else:
                sid = accounts.verify_code(pending, typed)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        sign_in(sid)
        st.rerun()


def _admin_sign_in_tab() -> None:
    with st.form("auth_admin_login", border=False):
        email = st.text_input("Admin email", autocomplete="username", key="auth_ad_email")
        password = st.text_input(
            "Password", type="password", autocomplete="current-password", key="auth_ad_pw"
        )
        go = st.form_submit_button(
            "Admin sign in", type="primary", icon=":material/admin_panel_settings:"
        )
    if not go:
        return
    try:
        result = orgs.admin_sign_in(email, password)
    except services.ServiceError as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return
    if result.pending is not None:  # the address was never confirmed: a code first
        st.session_state[ADMIN_PENDING] = result.pending
    else:
        sign_in_admin(result.org_id)  # type: ignore[arg-type]
    st.rerun()


def _create_org_tab() -> None:
    with st.form("auth_org_create", border=False):
        left, right = st.columns(2)
        name = left.text_input("Organization name", key="auth_org_name")
        code = right.text_input(
            "Organization code",
            help="A short code such as ACME-BLR-2027: capital letters, digits, hyphens.",
            key="auth_org_code",
        )
        org_type = left.selectbox("Institution type", ORG_TYPES, key="auth_org_type")
        domain = right.text_input(
            "Official domain", placeholder="dbit.co.in", key="auth_org_domain"
        )
        location = left.text_input("Location", placeholder="City, State", key="auth_org_loc")
        batch = right.text_input("Batch year", placeholder="2026-2027", key="auth_org_batch")
        admin_name = left.text_input("Admin full name", autocomplete="name", key="auth_org_admin")
        email = right.text_input("Admin email", autocomplete="email", key="auth_org_email")
        password = left.text_input(
            "Admin password", type="password", autocomplete="new-password", key="auth_org_pw"
        )
        confirm = right.text_input(
            "Repeat it", type="password", autocomplete="new-password", key="auth_org_pw2"
        )
        st.caption(
            "At least 8 characters, with letters and digits. We email a 9-digit code to the admin "
            "email to confirm it."
        )
        go = st.form_submit_button(
            "Create organization", type="primary", icon=":material/apartment:"
        )
    if not go:
        return
    try:
        pending = orgs.create_organization(
            org_code=code,
            name=name,
            org_type=org_type or "",
            official_domain=domain,
            location=location,
            academic_batch=batch,
            admin_name=admin_name,
            admin_email=email,
            password=password,
            confirm=confirm,
        )
    except services.ServiceError as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return
    st.session_state[ADMIN_PENDING] = pending
    st.rerun()


def _admin_recover_tab() -> None:
    with st.form("auth_admin_recover", border=False):
        email = st.text_input("Admin email", autocomplete="email", key="auth_ad_rec_email")
        st.caption(
            "We will send a 9-digit code to this administrator address to set a new password."
        )
        go = st.form_submit_button(
            "Send recovery code", type="primary", icon=":material/lock_reset:"
        )
    if not go:
        return
    try:
        pending = orgs.start_admin_recovery(email)
    except services.ServiceError as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return
    st.session_state[ADMIN_PENDING] = pending
    st.rerun()


def _admin_code_step(pending: orgs.AdminPending) -> None:
    """The organization admin's 9-digit code (confirming admin email or password recovery)."""
    recovering = getattr(pending, "purpose", "verify") == "recover"
    st.subheader(
        "Reset admin password" if recovering else "Confirm the admin email",
        anchor=False,
        icon=":material/lock_reset:" if recovering else ":material/mark_email_read:",
    )
    st.markdown(
        f"We sent a 9-digit code to **{formatter.md_escape(pending.sent_to)}**. It works once, "
        "for 10 minutes."
    )
    if pending.outbox:
        st.caption(
            ":material/inbox: Dev/offline mode: the 9-digit code was delivered to the local "
            "outbox (data/.mail_outbox.log). Add SMTP_EMAIL and SMTP_APP_PASSWORD to .env to "
            "email it."
        )
    with st.form("auth_admin_code", border=False):
        typed = st.text_input(
            "9-digit code", max_chars=11, placeholder="123-456-789", key="auth_ad_code"
        )
        if recovering:
            left, right = st.columns(2)
            password = left.text_input(
                "New password", type="password", autocomplete="new-password", key="auth_ad_new_pw"
            )
            confirm = right.text_input(
                "Repeat it", type="password", autocomplete="new-password", key="auth_ad_new_pw2"
            )
        go = st.form_submit_button(
            "Set password and open portal" if recovering else "Verify and open the portal",
            type="primary",
            icon=":material/verified_user:",
        )
    with st.container(horizontal=True):
        again = st.button("Send a new code", icon=":material/refresh:", key="auth_ad_resend")
        back = st.button("Back", type="tertiary", key="auth_ad_back")
    if back:
        st.session_state.pop(ADMIN_PENDING, None)
        st.rerun()
    if again:
        try:
            st.session_state[ADMIN_PENDING] = orgs.resend_admin_code(pending)
            st.toast("A new code is on its way.", icon=":material/mail:")
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
    if go:
        try:
            if recovering:
                org_id = orgs.finish_admin_recovery(pending, typed, password, confirm)
            else:
                org_id = orgs.verify_admin(pending, typed)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.session_state.pop(ADMIN_PENDING, None)
        sign_in_admin(org_id)
        st.rerun()


def _signed_out() -> None:
    page_header(
        "Welcome to Skill Scout Nexus",
        "Sign in to pick up your placement journey where you left it: profile, roadmap, "
        "quizzes and voice practice. Organizations manage their students from the admin portal.",
    )
    _, middle, _ = st.columns([1, 3, 1])
    with middle, st.container(border=True):
        if note := st.session_state.pop(NOTICE, None):
            st.success(note, icon=":material/check_circle:")
        if st.session_state.pop(SUSPENDED_NOTICE, None):
            st.warning(accounts.SUSPENDED, icon=":material/block:")
        pending: accounts.Pending | None = st.session_state.get(PENDING)
        admin_pending: orgs.AdminPending | None = st.session_state.get(ADMIN_PENDING)
        if admin_pending is not None:
            _admin_code_step(admin_pending)
        elif pending is not None:
            _code_step(pending)
        else:
            students, admins = st.tabs(
                [
                    ":material/school: Student / Learner access",
                    ":material/apartment: Organization admin access",
                ]
            )
            with students:
                signin, signup, recover = st.tabs(["Sign in", "Create account", "Recover account"])
                with signin:
                    _sign_in_tab()
                with signup:
                    _sign_up_tab()
                with recover:
                    _recover_tab()
            with admins:
                admin_in, create, recover_admin = st.tabs(
                    ["Admin sign in", "Create organization", "Recover admin account"]
                )
                with admin_in:
                    _admin_sign_in_tab()
                with create:
                    _create_org_tab()
                with recover_admin:
                    _admin_recover_tab()


# --- signed in: the profile -------------------------------------------------------------------


def _roles(profile: services.StudentProfile | None, key: str) -> tuple[list[str], int]:
    """The domain picker and the roles it offers. A student whose domain is locked keeps it."""
    sid = st.session_state.get("student_id")
    lock = services.locked_domain(sid) if profile else None
    if lock:
        st.markdown(formatter.locked_md(lock.domain.name, lock.since, lock.by))
        roles = services.domain_roles(lock.domain.id)
        return roles, roles.index(profile.target_role) if profile.target_role in roles else 0
    role = profile.target_role if profile else (current_student() or {}).get("target_role")
    return _roles_for(role, key)


def _form(profile: services.StudentProfile | None, key: str) -> None:
    """The resume form; a valid submission runs the profile agent and opens the profile."""
    roles, role_index = _roles(profile, key)
    with st.form(f"onboard_{key}", border=False):
        role = st.selectbox("Target role", roles, index=role_index)
        st.caption("Use one: upload your resume, or pick a sample to try the app.")
        upload = st.file_uploader("Resume file", type=["pdf", "docx", "txt"])
        sample = st.selectbox(
            "…or use a sample resume", ["—", *services.sample_resumes()], key="onboard_sample"
        )
        consent = st.checkbox(
            CONSENT_TEXT,
            value=False,
            key=f"onboard_consent_{key}",
            help="Needed for your own file. A sample resume holds no personal data.",
        )
        submitted = st.form_submit_button(
            "Analyse resume", type="primary", icon=":material/fact_check:"
        )
    if not submitted:
        return
    if upload and not consent:
        st.error(
            "Tick the consent box to analyse your own resume (a sample needs no consent).",
            icon=":material/error:",
        )
        return
    try:
        if upload:
            text = services.read_resume(upload.name, upload.getvalue())
        elif sample != "—":
            text = services.load_sample(sample)
        else:
            raise services.ServiceError("Upload a resume or pick a sample.")
    except (services.ServiceError, services.ResumeError) as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return
    _analyse(role, text)


def _analyse(role: str, text: str) -> None:
    sid = st.session_state["student_id"]
    result = run_agent("Profile agent", lambda ev: services.onboard(sid, role, text, ev))
    if result:
        journey.record_student(sid)  # telemetry, for the student's own history; best-effort
        journey.preload_next_steps(sid)  # roadmap, quiz and voice, in the background
        set_student(sid, keep_runs=("Profile agent",), fresh=True)
        st.rerun()


def _close_delete() -> None:
    st.session_state.pop(DELETE, None)


# Open while the session flag is set, so a full rerun does not close it half-way; dismissing
# it (X, Esc, a click outside) clears the flag.
@st.dialog("Delete account", icon=":material/delete:", on_dismiss=_close_delete)
def _delete(student: dict) -> None:
    """Delete only after the username is typed: the history cannot be brought back."""
    st.markdown(formatter.delete_warning_md(student["username"], student["name"]))
    typed = st.text_input("Type your username to confirm", placeholder=student["username"])
    if st.button("Delete for good", type="primary", icon=":material/delete_forever:"):
        try:
            services.delete_student(student["id"], typed)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        _close_delete()
        from piq.ui import sign_out  # the session went with the account; clear the browser too

        sign_out()
        st.session_state[NOTICE] = "Your account and its history were deleted."
        st.rerun()


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


def _signed_in(student: dict) -> None:
    profile = services.current_profile(student["id"])
    page_header(
        "Onboard",
        "Analyse a resume against a target role: readiness, the skills it shows and lacks, and "
        "what to fix.",
    )
    if profile is None:
        form_col, next_col = st.columns([2, 3], gap="medium")
        with form_col, st.container(border=True):
            st.subheader("Your resume", anchor=False)
            _form(None, "new")
        with next_col, st.container(border=True):
            st.subheader("What happens next", anchor=False)
            for n, (icon, text) in enumerate(NEXT, 1):
                st.markdown(f":primary[:material/{icon}:] **{n}.** {text}")
        return
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
        if st.button("Delete my account", type="tertiary", icon=":material/delete:"):
            st.session_state[DELETE] = True
        if st.session_state.get(DELETE):
            _delete(student)


if (me := current_student()) is None:
    _signed_out()
else:
    _signed_in(me)
