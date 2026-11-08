"""Organizations: the main admin's account, and everything the admin portal does.

Two halves. First the admin's sign-in, built like piq/accounts.py (and sharing its clock, code
rules and lockout): creating an organization emails the admin a 9-digit code that proves the
address, and the admin then signs in with admin_email and password. Wrong passwords or codes
never say which half was wrong, and five in a row lock the account for 15 minutes.

Second the portal's operations, and ONE rule runs through all of them: every function takes the
`org_id` of the signed-in admin (piq/ui.py reads it from the session, never from a form) and
reaches a student only through `_own_student`, which finds the student by id AND organization.
A student of another organization, or none, is "not in your organization", the same words for
both, so the id of someone else's student tells an admin nothing. The SQL underneath
(piq/db.py org_*) carries `org_id` too, and the telemetry read is cut by organization code, so
a slip in one place cannot leak across tenants.

Errors are services.ServiceError with a message safe to show.
"""

import logging
import sqlite3
from dataclasses import dataclass, field, replace

from pydantic import ValidationError

from core import auth, mailer
from core import org_provisioning as prov
from piq import accounts, cohort, db, journey, org_insights, services, syllabus
from piq.config import (
    AUTH_CODE_MAX_ATTEMPTS,
    AUTH_CODE_RESEND_S,
    AUTH_CODE_TTL_S,
    DEMO_ORG_CODE,
    DEMO_ORG_PREFIX,
    SESSION_TTL_S,
    VOICE_RUBRIC_MAX,
    settings,
)
from piq.schemas import Organization, OrganizationForm
from piq.services import ServiceError

log = logging.getLogger("piq.orgs")
WRONG_ADMIN = "That admin email and password do not match an organization."
NOT_YOURS = "That student is not in your organization."
FIELD_NAMES = {
    "org_code": "Organization code",
    "name": "Organization name",
    "org_type": "Institution type",
    "official_domain": "Official domain",
    "admin_name": "Admin name",
    "admin_email": "Admin email",
    "contact_phone": "Contact phone",
    "location": "Location",
    "academic_batch": "Academic batch",
    "quiz_cutoff_pct": "Quiz cutoff (0-100)",
    "voice_cutoff_score": f"Voice cutoff (0-{VOICE_RUBRIC_MAX})",
}


@dataclass(frozen=True)
class AdminPending:
    """A code is on its way to the admin's email (creating an organization, or signing in
    before the address was confirmed)."""

    org_id: int | None
    sent_to: str  # masked
    outbox: bool  # True: SMTP is not set up, the code is in data/.mail_outbox.log
    purpose: str = "verify"


@dataclass(frozen=True)
class AdminLogin:
    """The result of the password step: signed in (`org_id`), or a code to enter first."""

    org_id: int | None = None
    pending: AdminPending | None = None


# --- the organization ---------------------------------------------------------------------------


def _form(**fields: object) -> OrganizationForm:
    try:
        return OrganizationForm(**fields)  # type: ignore[arg-type]
    except ValidationError as e:
        err = e.errors()[0]
        field_ = str(err["loc"][0]) if err["loc"] else ""
        msg = str(err["msg"])
        if err["type"] == "value_error":
            raise ServiceError(msg.removeprefix("Value error, ")) from e
        label = FIELD_NAMES.get(field_, field_ or "A field")
        if err["type"] == "literal_error":
            raise ServiceError("Choose an institution type from the list.") from e
        if err["type"] == "string_too_long":
            raise ServiceError(f"{label} is too long.") from e
        raise ServiceError(f"{label}: {msg}.") from e


def organization(org_id: int | None) -> Organization:
    row = db.organization(org_id)
    if row is None:
        raise ServiceError("This organization no longer exists.")
    return Organization(**{k: row[k] for k in row.keys()})  # noqa: SIM118 (sqlite3.Row)


def cutoffs(org: Organization) -> org_insights.Cutoffs:
    return org_insights.Cutoffs(org.quiz_cutoff_pct, org.voice_cutoff_score)


def is_demo(org: Organization | None) -> bool:
    return org is not None and org.org_code.startswith(DEMO_ORG_PREFIX)


def update_organization(org_id: int, **changes: object) -> Organization:
    """Edit the organization's profile and pass marks (not its code or login email)."""
    org = organization(org_id)
    values = org.model_dump(include=set(FIELD_NAMES)) | {
        k: v for k, v in changes.items() if k in db.ORG_EDITABLE
    }
    form = _form(**values)
    db.update_organization(org_id, form.model_dump())
    journey.record_organization(org_id)
    return organization(org_id)


# --- the admin's sign-in ------------------------------------------------------------------------


def _locked(row: sqlite3.Row) -> auth.Lockout:
    return auth.Lockout(row["admin_failures"], row["admin_locked_until"])


def _refuse_if_locked(row: sqlite3.Row) -> None:
    wait = _locked(row).remaining(accounts.clock())
    if wait:
        raise ServiceError(
            f"Too many wrong attempts. Try again in about {max(1, round(wait / 60))} minute(s)."
        )


def _fail(row: sqlite3.Row) -> None:
    after = _locked(row).after_failure(accounts.clock())
    db.set_admin_lockout(row["id"], after.failures, after.locked_until)


def _send_admin_code(
    row: sqlite3.Row, *, force: bool = True, purpose: mailer.Purpose = "verify"
) -> AdminPending:
    now = accounts.clock()
    live = db.admin_code(row["id"])
    sent_to = auth.mask_email(row["admin_email"])
    if not force and live and now - live["sent_at"] < AUTH_CODE_RESEND_S:
        return AdminPending(row["id"], sent_to, not mailer.configured(), purpose=purpose)
    code, salt = auth.new_code(), auth.new_salt()
    pepper = settings().auth_pepper
    db.save_admin_code(
        row["id"], auth.hash_code(code, salt, pepper=pepper), salt, now + AUTH_CODE_TTL_S, now
    )
    msg = mailer.code_message(
        row["admin_email"], row["admin_name"], auth.format_code(code), purpose
    )
    return AdminPending(row["id"], sent_to, mailer.send(msg) == "outbox", purpose=purpose)


def create_organization(
    *,
    org_code: str,
    name: str,
    org_type: str,
    official_domain: str,
    location: str,
    academic_batch: str,
    admin_name: str,
    admin_email: str,
    password: str,
    confirm: str,
    contact_phone: str = "",
) -> AdminPending:
    """Register an organization and its main admin, and email the 9-digit code that confirms
    the admin's address (the admin cannot sign in before). Nothing leaves this machine until
    then: the organization joins the cloud copy only once the code is entered."""
    form = _form(
        org_code=org_code,
        name=name,
        org_type=org_type,
        official_domain=official_domain,
        location=location,
        academic_batch=academic_batch,
        admin_name=admin_name,
        admin_email=admin_email,
        contact_phone=contact_phone,
    )
    accounts.check_password(password, confirm, "", form.admin_email)
    hashed = auth.hash_password(password, pepper=settings().auth_pepper)
    try:
        org_id = db.create_organization(form.model_dump(), hashed)
    except sqlite3.IntegrityError as e:
        if db.organization_by_code(form.org_code) is not None:
            raise ServiceError("That organization code is taken; choose another.") from e
        raise ServiceError("An organization already uses that admin email: sign in.") from e
    return _send_admin_code(db.organization_state(org_id))  # type: ignore[arg-type]


def admin_sign_in(email: str, password: str) -> AdminLogin:
    """The password step. Right and confirmed: signed in. Right but the address was never
    confirmed: a code is sent first."""
    row = db.organization_login(email) if (email or "").strip() else None
    if row is not None:
        _refuse_if_locked(row)
    stored = row["admin_password_hash"] if row else None
    if not auth.verify_password(password or "", stored, pepper=settings().auth_pepper):
        if row is not None:
            _fail(row)
        raise ServiceError(WRONG_ADMIN)
    if not row["admin_verified"]:  # type: ignore[index]
        return AdminLogin(pending=_send_admin_code(row, force=False))  # type: ignore[arg-type]
    if row["admin_failures"]:  # type: ignore[index]
        db.set_admin_lockout(row["id"], 0, 0.0)  # type: ignore[index]
    return AdminLogin(org_id=row["id"])  # type: ignore[index]


def resend_admin_code(pending: AdminPending) -> AdminPending:
    row = db.organization_state(pending.org_id) if pending.org_id else None
    if row is None:
        return pending
    live = db.admin_code(row["id"])
    if live and accounts.clock() - live["sent_at"] < AUTH_CODE_RESEND_S:
        raise ServiceError(f"Wait {AUTH_CODE_RESEND_S} seconds before asking for another code.")
    return _send_admin_code(row, purpose=pending.purpose)  # type: ignore[arg-type]


def start_admin_recovery(email: str) -> AdminPending:
    """Email a 9-digit recovery code to the admin of the organization with this admin email.
    The answer masks the email or returns a dummy pending for unknown emails (nothing leaked)."""
    clean_email = (email or "").strip().lower()
    row = db.organization_login(clean_email) if clean_email else None
    usable = row is not None and row["admin_email"] and not _locked(row).remaining(accounts.clock())
    if not usable:
        guess = clean_email if "@" in clean_email else ""
        return AdminPending(
            None, auth.mask_email(guess), not mailer.configured(), purpose="recover"
        )
    return _send_admin_code(row, force=False, purpose="recover")


def finish_admin_recovery(pending: AdminPending, typed: str, password: str, confirm: str) -> int:
    """Check the 9-digit code, set the new admin password, delete older admin sessions,
    and return the org_id so the admin is signed in."""
    org_id = pending.org_id
    if org_id is None:
        raise ServiceError(accounts.WRONG_CODE)
    row = db.organization_state(org_id)
    if row is None:
        raise ServiceError(accounts.WRONG_CODE)
    _refuse_if_locked(row)
    accounts.check_password(password, confirm, "", row["admin_email"])
    code = db.admin_code(org_id)
    now = accounts.clock()
    ok = (
        code is not None
        and now < code["expires_at"]
        and code["attempts"] < AUTH_CODE_MAX_ATTEMPTS
        and auth.verify_code(typed, code["salt"], code["code_hash"], pepper=settings().auth_pepper)
    )
    if not ok:
        if code is not None:
            db.count_admin_code_attempt(org_id)
            if code["attempts"] + 1 >= AUTH_CODE_MAX_ATTEMPTS:
                db.delete_admin_code(org_id)
        _fail(row)
        raise ServiceError(accounts.WRONG_CODE)
    db.delete_admin_code(org_id)
    new_hash = auth.hash_password(password, pepper=settings().auth_pepper)
    db.set_admin_password(org_id, new_hash)
    db.delete_admin_sessions(org_id)
    journey.record_organization(org_id)
    return org_id


def verify_admin(pending: AdminPending, typed: str) -> int:
    """The organization id once the typed code matches (the address is then confirmed and the
    organization is mirrored to telemetry); ServiceError otherwise, counted toward the code's
    limit and the lockout."""
    row = db.organization_state(pending.org_id) if pending.org_id else None
    if row is None:
        raise ServiceError(accounts.WRONG_CODE)
    _refuse_if_locked(row)
    code = db.admin_code(row["id"])
    now = accounts.clock()
    ok = (
        code is not None
        and now < code["expires_at"]
        and code["attempts"] < AUTH_CODE_MAX_ATTEMPTS
        and auth.verify_code(typed, code["salt"], code["code_hash"], pepper=settings().auth_pepper)
    )
    if not ok:
        if code is not None:
            db.count_admin_code_attempt(row["id"])
            if code["attempts"] + 1 >= AUTH_CODE_MAX_ATTEMPTS:
                db.delete_admin_code(row["id"])
        _fail(row)
        raise ServiceError(accounts.WRONG_CODE)
    db.delete_admin_code(row["id"])
    db.mark_admin_verified(row["id"])
    journey.record_organization(row["id"])
    return row["id"]


def create_session(org_id: int) -> str:
    """A new admin session token for the browser cookie (only its hash is stored)."""
    token = auth.new_session_token()
    db.create_admin_session(auth.token_hash(token), org_id, accounts.clock() + SESSION_TTL_S)
    return token


def session_admin(token: str | None) -> int | None:
    """The organization an admin cookie's token signs in, or None (missing, unknown, expired)."""
    if not token or len(token) > 128:
        return None
    org_id = db.admin_session_org(auth.token_hash(token), accounts.clock())
    return org_id if org_id is not None and db.organization(org_id) is not None else None


def end_session(token: str | None) -> None:
    if token:
        db.delete_admin_session(auth.token_hash(token))


def demo_admin() -> int:
    """The demo organization's id (the admin portal with a fictional multi-stream cohort),
    seeded on first use ("Try demo organization admin"). It has no usable password."""
    row = db.organization_by_code(DEMO_ORG_CODE)
    if row is None:
        from scripts.seed_cohort import main as seed_cohort  # a fictional organization

        seed_cohort([])
        row = db.organization_by_code(DEMO_ORG_CODE)
    if row is None:
        raise ServiceError("The demo organization could not be prepared.")
    return row["id"]


# --- the roster, with what each student has done ------------------------------------------------


@dataclass(frozen=True)
class OrgView:
    org: Organization
    rows: list[cohort.StudentRow]  # every student of the organization, roster order
    error: str = ""  # telemetry could not be read: the rows then carry no results
    snapshot: object | None = None  # the organization's telemetry (crud.Cohort), for trends


def _blank_row(s: sqlite3.Row) -> cohort.StudentRow:
    return cohort.StudentRow(
        username=s["username"],
        name=s["name"],
        stream=s["main_domain"] or "",
        department="",
        target_role=s["target_role"],
        resume_match=None,
        missing_skills=(),
        quizzes=0,
        quiz_average=None,
        voice_sessions=0,
        rubric_average=None,
        rubric_best=None,
        proctor_flags=0,
        plans=0,
        tasks_done=0,
        last_active=None,
        readiness=None,
        band="Not assessed",
    )


def _merge(s: sqlite3.Row, result: cohort.StudentRow | None) -> cohort.StudentRow:
    """The roster's account details (authoritative: the admin edits them here) over the
    student's results from telemetry."""
    return replace(
        result or _blank_row(s),
        name=s["name"],
        email=s["email"] or "",
        main_domain=s["main_domain"] or "",
        subdomain=s["subdomain"] or "",
        target_role=s["target_role"],
        account_status=s["account_status"],
    )


def overview(org_id: int) -> OrgView:
    """The organization's students, one row each: the roster (this machine's database) joined
    to their results (telemetry, cut by organization code in SQL). If telemetry cannot be read
    the roster still shows, with an error to say results are missing."""
    org = organization(org_id)
    roster = db.org_students(org_id)
    view = journey.cohort_view(org_code=org.org_code)
    results = {r.username: r for r in view.rows}
    rows = [_merge(s, results.get(s["username"])) for s in roster]
    return OrgView(org, rows, view.error, view.snapshot)


def _own_student(org_id: int, student_id: str) -> sqlite3.Row:
    row = db.org_student(org_id, student_id or "")
    if row is None:
        raise ServiceError(NOT_YOURS)
    return row


def student_id_of(org_id: int, username: str) -> str:
    """The id of one of this organization's students by username (the directory's key)."""
    for s in db.org_students(org_id):
        if s["username"] == username:
            return s["id"]
    raise ServiceError(NOT_YOURS)


@dataclass(frozen=True)
class Candidate:
    """The 360 view of one student."""

    account: dict
    row: cohort.StudentRow
    detail: org_insights.Candidate360
    error: str = ""


def candidate(org_id: int, student_id: str, view: OrgView | None = None) -> Candidate:
    """The 360 view of one of this organization's students. `view`: the overview the page has
    already read (it is only used when it is this organization's)."""
    s = _own_student(org_id, student_id)
    view = view if view is not None and view.org.id == org_id else overview(org_id)
    row = next(r for r in view.rows if r.username == s["username"])
    try:
        session = journey.student_history(s["username"])
    except Exception:
        log.exception("telemetry: could not read the history of %s", s["username"])
        return Candidate(
            dict(s), row, org_insights.Candidate360(), "Their results are unavailable."
        )
    detail = org_insights.candidate_360(session) if session else org_insights.Candidate360()
    return Candidate(dict(s), row, detail)


# --- provisioning -------------------------------------------------------------------------------


def preview_csv(org_id: int, data: bytes) -> prov.ParseResult:
    """The uploaded file as checked rows (Ready, Duplicate, Invalid Email, ...), duplicates of
    existing accounts included. Nothing is stored."""
    organization(org_id)
    parsed = prov.parse_csv(data)
    return prov.ParseResult(prov.check_database(parsed.rows), parsed.columns)


def provision_csv(org_id: int, data: bytes) -> prov.ProvisionResult:
    """Create an account for every Ready row of the file, email each student, and hand back the
    credentials once. A demo organization never sends mail (its address book is anyone's)."""
    org = organization(org_id)
    parsed = prov.parse_csv(data)
    return prov.provision(org, parsed.rows, send_email=not is_demo(org), now=accounts.clock())


def quick_add(
    org_id: int,
    *,
    name: str,
    email: str,
    main_domain: str,
    subdomain: str,
    target_role: str = "",
    phone: str = "",
    batch_year: str = "",
) -> prov.ProvisionResult:
    """One student through the same checks and the same account creation as the CSV."""
    org = organization(org_id)
    row = prov.check_database(
        [prov.build_row(1, name, email, main_domain, subdomain, target_role, phone, batch_year)]
    )[0]
    if not row.ready:
        raise ServiceError(f"{row.status}: {row.note}.")
    return prov.provision(org, [row], send_email=not is_demo(org), now=accounts.clock())


def reset_credentials(org_id: int, student_id: str) -> prov.Credential:
    """New temporary password and code, emailed and returned for the admin's one-time
    download; the old password stops working."""
    org = organization(org_id)
    s = _own_student(org_id, student_id)
    if s["account_status"] == "suspended":
        raise ServiceError("Reactivate this account before resetting its password.")
    return prov.reset_credentials(org, s, send_email=not is_demo(org), now=accounts.clock())


def reassign(
    org_id: int, student_id: str, main_domain: str, subdomain: str, target_role: str = ""
) -> prov.Mapped:
    """Move a student to another domain, subdomain or role. A student who has not scanned a
    resume gets the new role's benchmark skills as their starting profile; one who has keeps
    their profile until they scan again."""
    s = _own_student(org_id, student_id)
    mapped = prov.map_domain(main_domain, subdomain, target_role)
    if isinstance(mapped, str):
        raise ServiceError(mapped[0].upper() + mapped[1:] + ".")
    if not db.reassign_org_student(org_id, student_id, mapped.stream, subdomain, mapped.role):
        raise ServiceError(NOT_YOURS)
    profile = db.latest_profile(student_id)
    if profile is None or not (profile.matched_skills or profile.skills):
        education = prov.education_text(mapped.degree, subdomain, s["batch_year"] or "")
        db.save_profile(student_id, services.starting_profile(s["name"], mapped.role, education))
    journey.record_student(student_id)
    return mapped


def set_status(org_id: int, student_id: str, status: str) -> str:
    """Suspend (signs the student out everywhere) or reactivate. Returns the new status: a
    reactivated student who never changed the temporary password is 'invited' again."""
    s = _own_student(org_id, student_id)
    if status not in ("active", "suspended"):
        raise ServiceError("An account is either active or suspended.")
    if status == "active" and s["must_change_password"]:
        status = "invited"
    if not db.set_org_student_status(org_id, student_id, status):
        raise ServiceError(NOT_YOURS)
    journey.record_student(student_id)
    return status


def send_student_nudge(org_id: int, username: str) -> bool:
    """Send a personalized nudge email with pending tasks to a student."""
    org = organization(org_id)
    sid = student_id_of(org_id, username)
    cand = candidate(org_id, sid)
    acct, row, detail = cand.account, cand.row, cand.detail
    email = acct.get("email") or ""
    if not email:
        raise ServiceError(f"No email address on file for @{username}.")
    momentum = org_insights.calculate_learner_momentum(row, cutoffs(org))
    tasks = list(momentum.pending_tasks)
    if not tasks:
        if row.resume_match is None:
            tasks.append("Scan your latest resume against your target role")
        if detail.plans:
            for w in detail.plans:
                if w.done < w.total:
                    tasks.append(f"Complete week {w.week} tasks ({w.done}/{w.total} completed)")
        else:
            tasks.append("Generate and begin your 7-day study plan")
        if row.quiz_average is None or row.quiz_average < org.quiz_cutoff_pct:
            tasks.append(f"Take practice quizzes to reach the pass mark ({org.quiz_cutoff_pct}%)")
        if row.rubric_average is None or row.rubric_average < org.voice_cutoff_score:
            tasks.append(
                f"Complete mock voice interviews (cutoff: "
                f"{org.voice_cutoff_score}/{VOICE_RUBRIC_MAX})"
            )
    msg = mailer.nudge_message(
        to=email,
        name=acct.get("name") or username,
        org_name=org.name,
        pending_tasks=tasks,
        momentum_stage=momentum.stage,
    )
    mailer.send(msg)
    log.info("sent nudge email to %s for org %d", email, org_id)
    return True


# --- the placement drive ------------------------------------------------------------------------


@dataclass(frozen=True)
class Drive:
    shortlisted: list[cohort.StudentRow]
    csv: bytes = field(repr=False)
    pdf: bytes = field(repr=False)


def drive(org_id: int, criteria: org_insights.DriveFilter, view: OrgView | None = None) -> Drive:
    """Who clears a placement drive's criteria, as a CSV shortlist and an executive summary PDF
    for the recruiters. `view`: the overview the page has already read."""
    view = view if view is not None and view.org.id == org_id else overview(org_id)
    chosen = org_insights.shortlist(view.rows, criteria)
    summary = org_insights.executive_summary(view.org, view.rows, cutoffs(view.org), criteria)
    return Drive(
        chosen, org_insights.shortlist_csv(chosen), org_insights.executive_summary_pdf(summary)
    )


# --- the student's own view of their organization -----------------------------------------------


@dataclass(frozen=True)
class StudentProgress:
    """An organization's student against its pass marks, for their Home and Dashboard pages."""

    org: Organization
    row: cohort.StudentRow
    steps: list[org_insights.Step]
    tier: str
    percentile: int | None  # ahead of this share of the batch on readiness; None: batch too small
    headline: str
    next_step: str


def student_progress(student_id: str | None) -> StudentProgress | None:
    """None for an individual learner. Never names another student: only a percentile, and
    only once the batch has enough students for it to hide anyone."""
    s = db.student(student_id) if student_id else None
    if s is None or s["org_id"] is None:
        return None
    view = overview(s["org_id"])
    row = next((r for r in view.rows if r.username == s["username"]), None)
    if row is None:
        return None
    c = cutoffs(view.org)
    steps = org_insights.journey_steps(row, c)
    done = sum(x.done for x in steps)
    ready = org_insights.is_ready(row, c)
    pending = next((x for x in steps if not x.done), None)
    return StudentProgress(
        org=view.org,
        row=row,
        steps=steps,
        tier=org_insights.tier(row, c),
        percentile=org_insights.percentile(view.rows, row),
        headline=(
            "You meet your organization's pass marks."
            if ready
            else f"{done} of {len(steps)} stages cleared."
        ),
        next_step=(
            "Your organization can now shortlist you for placement drives."
            if pending is None
            else f"Next: {pending.label.lower()} ({pending.detail})."
        ),
    )


# --- small wrappers the pages use (views never import core/) ------------------------------------


def template_csv() -> bytes:
    """The sample student CSV to download."""
    return prov.template_csv()


def credentials_csv(creds: list[prov.Credential] | tuple[prov.Credential, ...]) -> bytes:
    """The one-time credentials file for the admin to hand out."""
    return prov.credentials_csv(creds)


def streams() -> list[str]:
    """The main domains an organization can place students in (the catalog's streams)."""
    return list(prov.streams())


def roles_for_stream(stream: str) -> list[str]:
    """The catalog roles of a stream, for the admin's role picker."""
    known = syllabus.role_skills()
    return [
        r
        for d in syllabus.domains()
        if syllabus.stream_of(d.id) == stream
        for r in d.roles
        if r in known
    ]


def mail_channel(org: Organization) -> str:
    """How an admin's welcome emails travel: "smtp" (queued to send), "outbox" (SMTP is not set
    up: written to data/.mail_outbox.log) or "demo" (the demo organization sends nothing)."""
    if is_demo(org):
        return "demo"
    return "smtp" if mailer.configured() else "outbox"


def student_report_pdf(org: Organization, cand: Candidate) -> bytes:
    """One student's progress report as a PDF (for the student, parents or a mentor)."""
    return org_insights.student_report_pdf(org, cand.row, cand.detail, cutoffs(org))
