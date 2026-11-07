"""Streamlit helpers shared by the views: signing in (and staying signed in across reloads),
the visible agent loop and the design system's components (page header, empty state, stat
cards, chips, badges)."""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from piq import accounts, formatter, journey, orgs, services
from piq.config import SESSION_COOKIE, SESSION_TTL_S, STATIC_DIR
from piq.graph import CriticRejected, OnEvent
from piq.llm import LLMError
from piq.resume import ResumeError
from piq.schemas import StudentProfile

PER_STUDENT_KEYS = (
    "quiz",
    "quiz_result",
    "quiz_run",
    "quiz_run_result",
    "quiz_topic",
    "built_resume",
    "quiz_blanks",
    "interview",
    "snapshot",
    "onboard_delete",
    # the six-step journey's pages
    "scan",
    "roadmap_gaps",
    "roadmap_unsaved",
    "cq_batch",
    "cq_grade",
    "voice_q",
    "voice_result",
    "voice_text",
)
RUN_PREFIX = "run:"  # session key prefix for persisted agent step logs
AUTH_PREFIX = "auth_"  # the sign-in page's keys, dropped once signed in
ORG_PREFIX = "org_"  # the admin portal's keys, dropped when the admin signs out
ADMIN = "admin_org_id"  # the signed-in organization admin's organization (None: not an admin)
ADMIN_ORG = "admin_org"  # that organization (schemas.Organization), refreshed every run
FAILED = formatter.FAILED
USER_ERRORS = (CriticRejected, LLMError, services.ServiceError, ResumeError)


def set_student(
    student_id: str | None, keep_runs: tuple[str, ...] = (), *, fresh: bool = False
) -> None:
    """Make `student_id` current. On a change, drop the previous student's quiz, interview and
    agent step logs, except the logs of `keep_runs` (labels) already made for the new student.
    `fresh`: drop them even for the same student (a new profile makes their open quiz and
    interview stale)."""
    if fresh or student_id != st.session_state.get("student_id"):
        kept = {RUN_PREFIX + label for label in keep_runs}
        for k in list(st.session_state):
            if k in PER_STUDENT_KEYS or (str(k).startswith(RUN_PREFIX) and k not in kept):
                del st.session_state[k]
    st.session_state["student_id"] = student_id


# --- signing in and staying signed in -----------------------------------------------------------

TOKEN = "session_token"  # this browser's session token
COOKIE_SET = "cookie_set"  # a cookie change for the browser, written on the next render
SUSPENDED_NOTICE = "auth_suspended"  # the sign-in page says why a student was signed out
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def _cookie_token() -> str | None:
    try:
        token = st.context.cookies.get(SESSION_COOKIE)
    except Exception:  # no browser behind the session (tests, bare mode)
        return None
    return token if isinstance(token, str) and _TOKEN_RE.match(token) else None


def _restore_from_cookie() -> None:
    """A browser that reloads (F5) or comes back within SESSION_TTL_S is signed in again from
    its cookie: as a student (where they left off is loaded into the session, journey.snapshot)
    or as an organization admin. A token that is neither (expired, signed out elsewhere) is
    forgotten in this browser too."""
    if st.session_state.get("student_id") is not None or st.session_state.get(ADMIN) is not None:
        return
    if not (token := _cookie_token()):
        return
    if restored := accounts.session_student(token):
        st.session_state[TOKEN] = token
        set_student(restored, fresh=True)
        st.session_state["snapshot"] = journey.snapshot(restored)
    elif (org_id := orgs.session_admin(token)) is not None:
        st.session_state[TOKEN] = token
        st.session_state[ADMIN] = org_id
    else:
        st.session_state[COOKIE_SET] = ""


def signed_in_admin() -> orgs.Organization | None:
    """The signed-in organization admin's organization, refreshed every run; None when no admin
    is signed in. Tried before signed_in_student, so a cookie restores whoever it belongs to."""
    _restore_from_cookie()
    org_id = st.session_state.get(ADMIN)
    if org_id is None:
        st.session_state[ADMIN_ORG] = None
        return None
    try:
        org = orgs.organization(org_id)
    except services.ServiceError:  # the organization no longer exists
        st.session_state.pop(ADMIN, None)
        st.session_state[ADMIN_ORG] = None
        return None
    st.session_state[ADMIN_ORG] = org
    return org


def current_admin() -> orgs.Organization | None:
    """The signed-in admin's organization (the admin portal page reads it; never a form)."""
    return st.session_state.get(ADMIN_ORG)


def signed_in_student() -> dict | None:
    """The signed-in student's row, refreshed every run; None to show the sign-in page.
    A browser that reloads (F5) or comes back within SESSION_TTL_S is signed in again from its
    cookie (see _restore_from_cookie). A suspended account is signed out."""
    _restore_from_cookie()
    sid = st.session_state.get("student_id")
    row = services.student_row(sid)
    if row is not None and row["account_status"] == "suspended":
        accounts.end_session(st.session_state.pop(TOKEN, None))
        st.session_state[COOKIE_SET] = ""
        st.session_state[SUSPENDED_NOTICE] = True
        set_student(None)
        row = None
    if row is None:
        if sid is not None:  # the account was deleted
            set_student(None)
        st.session_state["student"] = None
        return None
    st.session_state["student"] = dict(row)
    return st.session_state["student"]


def sign_in(student_id: str) -> None:
    """Start a session for the student (and remember this browser), then show their journey."""
    _drop_admin()
    st.session_state.pop(PW_LATER, None)  # the password banner shows again for this student
    token = accounts.create_session(student_id)
    st.session_state[TOKEN] = token
    st.session_state[COOKIE_SET] = token
    set_student(student_id, fresh=True)
    st.session_state["snapshot"] = journey.snapshot(student_id)
    for key in [k for k in st.session_state if str(k).startswith(AUTH_PREFIX)]:
        del st.session_state[key]


def _drop_admin() -> None:
    for key in [k for k in st.session_state if str(k).startswith(ORG_PREFIX)]:
        del st.session_state[key]
    st.session_state.pop(ADMIN, None)
    st.session_state[ADMIN_ORG] = None


def sign_in_admin(org_id: int) -> None:
    """Start an admin session for the organization (and remember this browser)."""
    set_student(None)
    st.session_state.pop("snapshot", None)
    st.session_state["student"] = None
    token = orgs.create_session(org_id)
    st.session_state[TOKEN] = token
    st.session_state[COOKIE_SET] = token
    st.session_state[ADMIN] = org_id
    for key in [k for k in st.session_state if str(k).startswith(AUTH_PREFIX)]:
        del st.session_state[key]


def sign_out() -> None:
    """End this browser's session, student's or admin's (button callback): the cookie goes on
    the next render."""
    token = st.session_state.pop(TOKEN, None)
    accounts.end_session(token)
    orgs.end_session(token)
    _drop_admin()
    set_student(None)
    st.session_state.pop("snapshot", None)
    st.session_state["student"] = None
    st.session_state[COOKIE_SET] = ""


def flush_cookie() -> None:
    """Write a pending cookie change in the browser: a session token after sign-in, or an
    expired cookie after sign-out. A token-only value (checked) and fixed attributes, so the
    script cannot be steered by input."""
    if COOKIE_SET not in st.session_state:
        return
    token = st.session_state.pop(COOKIE_SET)
    value, age = (token, SESSION_TTL_S) if token and _TOKEN_RE.match(token) else ("", 0)
    st.html(
        "<script>document.cookie = "
        + json.dumps(f"{SESSION_COOKIE}={value}; Path=/; Max-Age={age}; SameSite=Strict")
        + " + (location.protocol === 'https:' ? '; Secure' : '');</script>",
        unsafe_allow_javascript=True,
    )


def account_sidebar(student: dict) -> None:
    """Who is signed in, the organization they belong to, and the way out."""
    with st.sidebar:
        st.markdown(
            f":material/account_circle: **{formatter.md_escape(student['name'])}**  \n"
            f":gray[@{formatter.md_escape(student['username'])}]"
        )
        if student.get("org_name"):
            st.markdown(
                formatter.org_badge_md(
                    student["org_name"], student.get("main_domain"), student.get("subdomain")
                )
            )
        st.button("Sign out", icon=":material/logout:", on_click=sign_out, key="sign_out")


def admin_sidebar(org: orgs.Organization) -> None:
    """Which organization the admin runs, and the way out."""
    with st.sidebar:
        st.markdown(
            f":material/apartment: **{formatter.md_escape(org.short_name)}**  \n"
            f":gray[Organization admin: {formatter.md_escape(org.admin_name)}]  \n"
            f":gray[{formatter.md_escape(org.org_code)}]"
        )
        st.button("Sign out", icon=":material/logout:", on_click=sign_out, key="sign_out")


PW_LATER = "pw_banner_later"  # the student chose "Not now" for this session


@st.dialog("Choose your own password", icon=":material/key:")
def _change_password(student: dict) -> None:
    with st.form("change_password", border=False):
        current = st.text_input("Temporary password", type="password", key="pw_current")
        left, right = st.columns(2)
        new = left.text_input("New password", type="password", key="pw_new")
        again = right.text_input("Repeat it", type="password", key="pw_again")
        st.caption("At least 8 characters, with letters and digits.")
        go = st.form_submit_button("Save password", type="primary", icon=":material/lock_reset:")
    if go:
        try:
            accounts.change_password(student["id"], current, new, again)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.toast("Your password was changed.", icon=":material/check_circle:")
        st.rerun()


def password_banner(student: dict) -> None:
    """An organization's student signed in with a temporary password: an optional banner to
    choose their own. "Not now" hides it until they sign in again."""
    if not student.get("must_change_password") or st.session_state.get(PW_LATER):
        return
    with st.container(border=True):
        st.markdown(
            ":primary[:material/key:] **Your password is temporary.** Choose one of your own "
            "so only you know it. You can keep working and do this later."
        )
        with st.container(horizontal=True):
            change = st.button("Change password", type="primary", key="pw_change")
            later = st.button("Not now", type="tertiary", key="pw_later")
    if later:
        st.session_state[PW_LATER] = True
        st.rerun()
    if change:
        _change_password(student)


def org_progress_card(student_id: str | None) -> None:
    """An organization's student: where they stand against its pass marks, stage by stage,
    and what is next. Nothing for an individual learner."""
    me = current_student()
    if not me or me.get("org_id") is None:  # an individual learner: no query, no card
        return
    progress = orgs.student_progress(student_id)
    if progress is None:
        return
    row = progress.row
    with st.container(border=True):
        st.markdown(
            formatter.org_badge_md(progress.org.name, row.main_domain or row.stream, row.subdomain)
        )
        left, right = st.columns([3, 2], vertical_alignment="center")
        left.subheader(progress.headline, anchor=False)
        left.caption(formatter.md_escape(progress.next_step))
        with right:
            status_badge(*formatter.TIER_BADGE[progress.tier])
            if progress.percentile is not None:
                st.caption(f"Ahead of {progress.percentile}% of your batch on readiness.")
        step_bars(progress.steps)


def step_bars(steps) -> None:  # type: ignore[no-untyped-def]
    """A journey checklist as progress bars: an icon and the stage's name, then what was done or
    what is left (state in words and icons, never colour alone)."""
    for step in steps:
        icon = "check_circle" if step.done else "radio_button_unchecked"
        st.progress(
            step.progress,
            text=f":material/{icon}: **{formatter.md_escape(step.label)}**: "
            f"{formatter.md_escape(step.detail)}",
        )


def current_student() -> dict | None:
    """The signed-in student's row (id, name, username, email, target_role, readiness_score)."""
    return st.session_state.get("student")


def sidebar_context(mock_mode: bool, ai: str = "", engine: str = "") -> None:
    """Under the student picker: their readiness at a glance, a quiet badge naming who
    answers (mock mode, the AI provider in use, or the offline rules) and, last, the
    engine line: AI, records and preloader (journey.engine_status)."""
    with st.sidebar:
        if student := current_student():
            score = student["readiness_score"] or 0
            st.progress(score / 100, text=f"Readiness {score}/100")
        if mock_mode:
            st.badge(
                "Mock mode",
                icon=":material/science:",
                color="gray",
                help="Answers come from built-in samples; no AI service is called.",
            )
        elif ai == "Offline rules":  # quiet on purpose: the student can keep working as usual
            st.badge(
                "Built-in answers",
                icon=":material/offline_bolt:",
                color="gray",
                help="Answers come from the question bank and built-in rules until an AI "
                "service is reachable again.",
            )
        elif ai:
            st.badge(
                f"AI: {ai}",
                icon=":material/cloud_done:",
                color="gray",
                help="The first healthy provider answers; others take over if it fails.",
            )
        if engine:  # small print at the foot: for whoever runs the demo, not the student
            st.caption(f":material/memory: {formatter.md_escape(engine)}")


def no_profile_card(key: str = "need_profile") -> None:
    """A signed-in student with no profile yet: two ways to start, never a broken page."""
    sid = st.session_state.get("student_id")
    with st.container(border=True, gap="small"):
        st.subheader("Start with your resume", anchor=False, icon=":material/upload_file:")
        st.markdown(
            "This page works from your skill gaps. Scan your resume to find them, or start "
            "now with every skill your target role asks for and scan later."
        )
        with st.container(horizontal=True):
            scan = st.button(
                "Scan your resume first",
                type="primary",
                icon=":material/document_scanner:",
                key=f"{key}_scan",
            )
            bench = st.button(
                "Start with stream benchmark skills",
                icon=":material/checklist:",
                key=f"{key}_bench",
            )
    if scan:
        st.switch_page("views/onboard.py")
    if bench and sid:
        try:
            services.benchmark_profile(sid)
        except services.ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
            return
        st.rerun()


def require_profile() -> tuple[str, StudentProfile]:
    """The signed-in student and their profile. Without a profile, a guided card offers a
    resume scan or the role's benchmark skills, and the page stops (app.py has already sent
    anyone not signed in to the sign-in page)."""
    sid = st.session_state.get("student_id")
    profile = services.current_profile(sid)
    if not profile:
        no_profile_card()
        st.stop()
    return sid, profile


def _rejected(events: list[str]) -> bool:
    return any(m.startswith("critic rejected") for m in events)


def _failed(events: list[str]) -> bool:
    return any(m.startswith(FAILED) for m in events)


def _step(parent: DeltaGenerator, step: formatter.TrailStep) -> None:
    """One step of the critic trail. Steps are native timeline steps (icon column and a
    connecting line); each carries a line of content, because an empty step ends the line."""
    state = "error" if step.failed else "complete"
    box = parent.status(f"**{step.title}**", type="step", state=state, expanded=True)
    if step.reasons:  # the critic's own words, at the step title's size
        lines = [f":small[{r}]" for r in step.reasons]
        box.markdown(lines[0] if len(lines) == 1 else "\n".join(f"- {line}" for line in lines))
    if step.note:
        box.caption(step.note)


def run_agent[T](label: str, fn: Callable[[OnEvent], T]) -> T | None:
    """Run an agent call inside a live status box that shows every generate/critic step.

    The step log (including a failure) is also kept in session state: views call
    `st.rerun()` after saving, which would otherwise wipe the only visible evidence
    of the critic loop. Returns None after showing a user-facing error.
    """
    events: list[str] = []
    with st.status(label, expanded=True) as box:

        def on_event(msg: str) -> None:
            events.append(msg)
            _step(box, formatter.trail_steps(events)[-1])

        try:
            out = fn(on_event)
        except USER_ERRORS as e:
            events.append(f"{FAILED}{e}")
            _step(box, formatter.trail_steps(events)[-1])
            box.update(label=f"{label} — failed", state="error")
            st.error(formatter.critic_text(str(e)))
            return None
        finally:
            st.session_state[RUN_PREFIX + label] = events
        box.update(label=f"{label} — done", state="complete", expanded=_rejected(events))
    return out


def show_last_run(label: str) -> None:
    """Re-render the step log of the last `run_agent(label, ...)`.

    Expanded when it contained a retry or a failure, so neither goes unnoticed.
    """
    events = st.session_state.get(RUN_PREFIX + label)
    if events:
        failed = _failed(events)
        with st.status(
            f"{label} — last run{' failed' if failed else ''}",
            state="error" if failed else "complete",
            expanded=failed or _rejected(events),
        ) as box:
            for step in formatter.trail_steps(events):
                _step(box, step)


# --- design-system components -------------------------------------------------------


@dataclass(frozen=True)
class Stat:
    label: str
    value: str
    delta: str | None = None
    help: str | None = None
    delta_color: str = "normal"  # "off" for a change that is neither good nor bad
    delta_arrow: str = "auto"  # "off" for a note under the value that is not a change


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return (STATIC_DIR / "app.css").read_text(encoding="utf-8")


def load_css() -> None:
    """Add static/app.css (what the theme cannot express) once per run, before the page."""
    st.html(f"<style>{_stylesheet()}</style>")


def page_header(
    title: str,
    purpose: str,
    action: str | None = None,
    *,
    icon: str | None = None,
    key: str | None = None,
) -> bool:
    """Every page opens with its title, one plain sentence of purpose (Markdown: escape any
    dynamic part) and optionally its primary action, under the sentence so nothing is
    squeezed on a phone. Returns True when the action is clicked."""
    st.title(title, anchor=False)
    st.markdown(f":gray[{purpose}]")
    return bool(action) and st.button(action, type="primary", icon=icon, key=key)


def empty_state(
    icon: str, title: str, body: str, action: str | None = None, *, key: str | None = None
) -> bool:
    """An empty screen as an invitation: what is missing and the one next step."""
    with st.container(border=True, gap="small"):
        st.subheader(title, anchor=False, icon=f":material/{icon}:")
        st.markdown(body)
        return bool(action) and st.button(action, type="primary", key=key)


def stat_row(stats: Sequence[Stat]) -> None:
    """Equal-height stat cards in one row; they stack on phones."""
    for column, s in zip(st.columns(len(stats)), stats, strict=True):
        column.metric(
            s.label,
            s.value,
            s.delta,
            delta_color=s.delta_color,
            delta_arrow=s.delta_arrow,
            help=s.help,
            border=True,
            height="stretch",
        )


def topic_chip(topic: str) -> None:
    st.html(formatter.topic_chip_html(topic))


def status_badge(state: str, text: str) -> None:
    icon, color = formatter.STATUS[state]
    st.badge(text, icon=f":material/{icon}:", color=color)
