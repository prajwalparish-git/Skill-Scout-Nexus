"""Accounts: sign-up, sign-in with a 9-digit email code, recovery and sessions.

Pages call this module; it validates input, applies core/auth.py's rules, stores state through
piq/db.py (local only, never synced) and emails codes with core/mailer.py. Errors are
services.ServiceError with a message safe to show, and none of them tells a stranger whether an
account exists: a wrong username and a wrong password read the same, and recovery always
answers "if that account exists, a code is on its way".

Sign-up ends with a code emailed to the account, which proves the email. After that, signing
in takes only the password, unless something looks off: the email was never confirmed (an
organization's student on their welcome code), or there were CODE_AFTER_FAILURES wrong tries in a
row on the account or in that browser; then the code is asked as well. Five wrong passwords or
codes in a row lock the account for 15 minutes; a code expires after 10 minutes or 5 wrong tries.
A session is a random token: the browser keeps it in a cookie, the database keeps only its
SHA-256, with the device it is on (piq/devices.py). A sign-in on a device the account has not used
before is emailed to the student, who can see and sign out every device.

In local mode (settings().local_mode: no email, no cloud database) the install has one student
and the password alone signs in: there is nobody to email a code to.

An organization's students (piq/orgs.py) arrive with a temporary password and a 9-digit welcome
code from their email. The code is a normal sign-in code with a longer life
(ORG_WELCOME_CODE_TTL_S), so signing in with the temporary password does not replace it with a
new email: the student types the one they already have. A suspended account never signs in, and
a student with a temporary password is offered a new one (change_password).
"""

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from core import auth, mailer
from piq import db, prefs, syllabus
from piq.config import (
    AUTH_CODE_MAX_ATTEMPTS,
    AUTH_CODE_RESEND_S,
    AUTH_CODE_TTL_S,
    CODE_AFTER_FAILURES,
    EMAIL_MAX,
    EMAIL_RE,
    PASSWORD_MAX,
    PASSWORD_MIN,
    SESSION_TOUCH_S,
    SESSION_TTL_S,
    USERNAME_RE,
    settings,
)
from piq.devices import Device
from piq.services import ServiceError

log = logging.getLogger("piq.accounts")
Purpose = Literal["login", "recover"]
WRONG_LOGIN = "That username or email and password do not match an account."
WRONG_CODE = "That code is not right, or it has expired. Check the latest email, or send a new one."
SUSPENDED = "This account is suspended. Please contact your organization's admin."
LOCAL_ONE = "This copy runs on one computer for one student: sign in with its account."
clock: Callable[[], float] = time.time  # tests move time forward


@dataclass(frozen=True)
class Pending:
    """A code is on its way. `student_id` is None when recovery was asked for an unknown
    account: the page looks the same, and the code check simply always fails."""

    student_id: str | None
    purpose: Purpose
    sent_to: str  # masked, e.g. "a***@gmail.com"
    outbox: bool  # True: SMTP is not set up, the code is in data/.mail_outbox.log
    welcome: bool = False  # the code is the one in the organization's welcome email


def event(
    kind: str,
    *,
    student_id: str | None = None,
    identifier: str = "",
    device: Device | None = None,
    detail: str = "",
) -> None:
    """Note a sign-in event for the operations view; never lets a sign-in fail."""
    d = device or Device()
    try:
        db.log_auth_event(
            clock(),
            kind,
            student_id=student_id,
            identifier=(identifier or "").strip().lower(),
            ip=d.ip,
            user_agent=d.user_agent,
            location=d.location,
            detail=detail,
        )
    except Exception:
        log.exception("auth event %s could not be recorded", kind)


# --- validation ---------------------------------------------------------------------------------


def normalise_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ServiceError(
            "Choose a username of 3-20 lower-case letters or digits (dots, - and _ allowed)."
        )
    return username


def normalise_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > EMAIL_MAX or not EMAIL_RE.match(email):
        raise ServiceError("Enter a valid email address.")
    return email


def check_password(password: str, confirm: str, username: str = "", email: str = "") -> None:
    if password != confirm:
        raise ServiceError("The two passwords are different.")
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ServiceError(f"Use a password of {PASSWORD_MIN}-{PASSWORD_MAX} characters.")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise ServiceError("Use both letters and digits in the password.")
    lowered = password.lower()
    if (username and username in lowered) or (email and email.split("@")[0] in lowered):
        raise ServiceError("Keep your username and email out of the password.")


# --- codes --------------------------------------------------------------------------------------


def _locked(student_id: str) -> auth.Lockout:
    row = db.credentials(student_id)
    return auth.Lockout(row["failures"], row["locked_until"]) if row else auth.Lockout()


def _refuse_if_locked(student_id: str) -> None:
    wait = _locked(student_id).remaining(clock())
    if wait:
        minutes = max(1, round(wait / 60))
        raise ServiceError(f"Too many wrong attempts. Try again in about {minutes} minute(s).")


def _fail(student_id: str) -> None:
    """One more wrong password or code; the fifth in a row locks the account."""
    if db.credentials(student_id) is None:
        return  # no password, no lockout to keep (the demo account)
    after = _locked(student_id).after_failure(clock())
    db.set_lockout(student_id, after.failures, after.locked_until)


def _welcome_live(live: sqlite3.Row | None, now: float) -> bool:
    """A sign-in code issued with the longer welcome life that has not expired yet."""
    return (
        live is not None
        and now < live["expires_at"]
        and live["expires_at"] - live["sent_at"] > AUTH_CODE_TTL_S
    )


def _send_code(student: sqlite3.Row, purpose: Purpose, *, force: bool = True) -> Pending:
    """Make, store (hashed) and email a new code. `force=False` keeps a code sent less than
    AUTH_CODE_RESEND_S ago (a double click must not flood the inbox) and an unexpired welcome
    code (the student already has it by email)."""
    now = clock()
    live = db.auth_code(student["id"], purpose)
    sent_to = auth.mask_email(student["email"] or "")
    if not force and _welcome_live(live, now) and purpose == "login":
        return Pending(student["id"], purpose, sent_to, not mailer.configured(), welcome=True)
    if not force and live and now - live["sent_at"] < AUTH_CODE_RESEND_S:
        return Pending(student["id"], purpose, sent_to, not mailer.configured())
    code, salt = auth.new_code(), auth.new_salt()
    pepper = settings().auth_pepper
    db.save_code(
        student["id"],
        purpose,
        auth.hash_code(code, salt, pepper=pepper),
        salt,
        now + AUTH_CODE_TTL_S,
        now,
    )
    msg = mailer.code_message(student["email"], student["name"], auth.format_code(code), purpose)
    channel = mailer.send(msg)
    return Pending(student["id"], purpose, sent_to, channel == "outbox")


def resend_code(pending: Pending) -> Pending:
    """A new code for the same step (the old one stops working)."""
    student = db.student(pending.student_id) if pending.student_id else None
    if student is None or not student["email"]:
        return pending  # unknown account in recovery: nothing to send, nothing to reveal
    live = db.auth_code(student["id"], pending.purpose)
    if live and clock() - live["sent_at"] < AUTH_CODE_RESEND_S:
        raise ServiceError(f"Wait {AUTH_CODE_RESEND_S} seconds before asking for another code.")
    return _send_code(student, pending.purpose)


def verify_code(pending: Pending, typed: str) -> str:
    """The student id once the typed code matches; ServiceError otherwise (and the attempt
    counts toward both the code's limit and the account lockout)."""
    sid = pending.student_id
    if sid is None:
        raise ServiceError(WRONG_CODE)
    _refuse_if_locked(sid)
    row = db.auth_code(sid, pending.purpose)
    ok = (
        row is not None
        and clock() < row["expires_at"]
        and row["attempts"] < AUTH_CODE_MAX_ATTEMPTS
        and auth.verify_code(typed, row["salt"], row["code_hash"], pepper=settings().auth_pepper)
    )
    if not ok:
        if row is not None:
            db.count_code_attempt(sid, pending.purpose)
            if row["attempts"] + 1 >= AUTH_CODE_MAX_ATTEMPTS:
                db.delete_code(sid, pending.purpose)  # void: a new code has to be sent
        _fail(sid)
        event("code_wrong", student_id=sid)
        raise ServiceError(WRONG_CODE)
    db.delete_code(sid, pending.purpose)  # works once
    if db.credentials(sid) is not None:
        db.set_lockout(sid, 0, 0.0)
    db.mark_signed_in(sid)  # an invited student is now active
    db.set_email_verified(sid)  # the code reached that inbox
    return sid


# --- sign-up, sign-in, recovery -----------------------------------------------------------------


def sign_up(
    name: str,
    username: str,
    email: str,
    password: str,
    confirm: str,
    target_role: str,
    *,
    device: Device | None = None,
) -> Pending | str:
    """Create the account and email the code that confirms the address (and signs them in).
    In local mode there is no email: the account is made (only if there is none yet) and its id
    returned, signed in at once."""
    if settings().local_mode and db.student_count() > 0:
        raise ServiceError(LOCAL_ONE)
    name = (name or "").strip()
    if not 1 <= len(name) <= 120:
        raise ServiceError("Enter your name (up to 120 characters).")
    username, email = normalise_username(username), normalise_email(email)
    check_password(password, confirm, username, email)
    if target_role not in syllabus.role_skills():
        raise ServiceError("Choose the role you are aiming for.")
    if db.student_by_username(username) is not None:
        raise ServiceError("That username is taken; choose another.")
    if db.email_taken(email):
        raise ServiceError("That email already has an account: sign in, or recover it.")
    pw = auth.hash_password(password, pepper=settings().auth_pepper)
    try:
        sid = db.create_student(name, username, target_role, email=email, password_hash=pw)
    except sqlite3.IntegrityError as e:  # taken between the check and the insert
        raise ServiceError("That username or email was just taken; try another.") from e
    if settings().local_mode:
        db.set_email_verified(sid)
        return sid
    event("sign_up_started", student_id=sid, identifier=username, device=device)
    return _send_code(db.student(sid), "login")  # type: ignore[arg-type]


def start_login(
    identifier: str, password: str, *, risky: bool = False, device: Device | None = None
) -> Pending | str:
    """The password. Right, and nothing looks off: the student id (sign them in). Right, but the
    email was never confirmed, or there were CODE_AFTER_FAILURES wrong tries in a row on the
    account (or `risky`: in this browser): a code goes to the account's email (step 2)."""
    student = db.student_by_login(identifier) if (identifier or "").strip() else None
    cred = db.credentials(student["id"]) if student else None
    if student is not None and cred is not None:
        _refuse_if_locked(student["id"])
    stored = cred["password_hash"] if cred else None
    sid = student["id"] if student else None
    if not auth.verify_password(password or "", stored, pepper=settings().auth_pepper):
        if sid is not None:
            _fail(sid)
        event("sign_in_failed", student_id=sid, identifier=identifier, device=device)
        raise ServiceError(WRONG_LOGIN)
    if not student["email"]:  # type: ignore[index]
        raise ServiceError(WRONG_LOGIN)
    if student["account_status"] == "suspended":  # type: ignore[index]
        raise ServiceError(SUSPENDED)  # said only after the password was right
    needs_code = not settings().local_mode and (
        not student["email_verified"]  # type: ignore[index]
        or cred["failures"] >= CODE_AFTER_FAILURES  # type: ignore[index]
        or risky
    )
    if needs_code:
        reason = "email not confirmed" if not student["email_verified"] else "after wrong tries"  # type: ignore[index]
        event("code_required", student_id=sid, identifier=identifier, device=device, detail=reason)
        return _send_code(student, "login", force=False)  # type: ignore[arg-type]
    db.set_lockout(sid, 0, 0.0)  # type: ignore[arg-type]
    db.mark_signed_in(sid)  # type: ignore[arg-type]
    return sid  # type: ignore[return-value]


def start_recovery(identifier: str) -> Pending:
    """Email a recovery code to the account with this email or username. The answer is the
    same whether or not it exists."""
    student = db.student_by_login(identifier) if (identifier or "").strip() else None
    usable = (
        student is not None
        and student["email"]
        and student["account_status"] != "suspended"
        and db.credentials(student["id"])
    )
    if not usable or _locked(student["id"]).remaining(clock()):  # type: ignore[index]
        # unknown, passwordless or locked: the same answer, and nothing is sent
        guess = identifier.strip().lower() if "@" in (identifier or "") else ""
        return Pending(None, "recover", auth.mask_email(guess), not mailer.configured())
    return _send_code(student, "recover", force=False)  # type: ignore[arg-type]


def finish_recovery(pending: Pending, typed: str, password: str, confirm: str) -> str:
    """Check the code, set the new password, sign the student out everywhere else; returns
    the student id (the page signs them in here)."""
    student = db.student(pending.student_id) if pending.student_id else None
    if student is not None:
        check_password(password, confirm, student["username"], student["email"] or "")
    sid = verify_code(pending, typed)
    db.set_password(sid, auth.hash_password(password, pepper=settings().auth_pepper))
    db.set_must_change_password(sid, False)  # they just chose one
    db.delete_sessions(sid)
    return sid


def change_password(student_id: str, current: str, password: str, confirm: str) -> None:
    """A signed-in student sets a password of their own (the first sign-in banner, for an
    organization's student with a temporary one). The current password must be right; a wrong
    one counts toward the lockout like a wrong sign-in."""
    student = db.student(student_id)
    cred = db.credentials(student_id) if student else None
    if student is None or cred is None:
        raise ServiceError("This account has no password to change.")
    _refuse_if_locked(student_id)
    if not auth.verify_password(
        current or "", cred["password_hash"], pepper=settings().auth_pepper
    ):
        _fail(student_id)
        raise ServiceError("Your current password is not right.")
    if password == current:
        raise ServiceError("Choose a password different from the temporary one.")
    check_password(password, confirm, student["username"], student["email"] or "")
    db.set_password(student_id, auth.hash_password(password, pepper=settings().auth_pepper))
    db.set_must_change_password(student_id, False)


# --- sessions -----------------------------------------------------------------------------------


def create_session(student_id: str, device: Device | None = None) -> str:
    """A new session token for the browser cookie (only its hash is stored), on `device`. The
    first sign-in on a device the account has not used before is emailed to the student."""
    now = clock()
    d = device or Device()
    token = auth.new_session_token()
    first = d.hash and db.known_device_count(student_id) == 0
    db.create_session(
        auth.token_hash(token),
        student_id,
        now + SESSION_TTL_S,
        device_hash=d.hash,
        user_agent=d.user_agent,
        ip=d.ip,
        location=d.location,
        now=now,
    )
    event("sign_up" if first else "sign_in", student_id=student_id, device=device)
    if d.hash and db.remember_device(student_id, d.hash, now):
        event("new_device", student_id=student_id, device=device, detail=d.describe())
        _alert_new_device(student_id, d, now, signed_up=bool(first))
    return token


def _alert_new_device(student_id: str, d: Device, now: float, *, signed_up: bool) -> None:
    student = db.student(student_id)
    if settings().local_mode or not student or not student["email"]:
        return
    if not prefs.get(student_id)["login_alerts"]:
        return
    msg = mailer.new_device_message(
        student["email"],
        name=student["name"],
        browser=d.browser,
        os=d.os,
        ip=d.ip,
        location=d.location,
        when=time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(now)),
        signed_up=signed_up,
    )
    mailer.send(msg)


def session_student(token: str | None) -> str | None:
    """The student a cookie's token signs in, or None (missing, unknown or expired)."""
    if not token or len(token) > 128:
        return None
    token_hash = auth.token_hash(token)
    now = clock()
    sid = db.session_student(token_hash, now)
    student = db.student(sid) if sid else None
    if not student or student["account_status"] == "suspended":
        return None
    db.touch_session(token_hash, now, SESSION_TOUCH_S)
    return sid


def end_session(token: str | None, device: Device | None = None) -> None:
    if token:
        sid = db.session_student(auth.token_hash(token), clock())
        db.delete_session(auth.token_hash(token))
        if sid:
            event("sign_out", student_id=sid, device=device)


def sessions(student_id: str, current_token: str | None) -> list[dict]:
    """The student's signed-in devices, the current one marked."""
    current = auth.token_hash(current_token) if current_token else ""
    out = []
    for r in db.student_sessions(student_id, clock()):
        d = Device(user_agent=r["user_agent"])
        out.append(
            {
                "id": r["token_hash"][:16],
                "browser": d.browser,
                "os": d.os,
                "ip": r["ip"],
                "location": r["location"],
                "created_at": r["created_at"],
                "last_seen": r["last_seen"] or None,
                "current": r["token_hash"] == current,
            }
        )
    return out


def end_session_id(student_id: str, session_id: str, device: Device | None = None) -> bool:
    """Sign one of the student's devices out (its id is the start of the session's hash)."""
    if len(session_id) < 8:
        return False
    for r in db.student_sessions(student_id, clock()):
        if r["token_hash"].startswith(session_id):
            done = db.delete_student_session(student_id, r["token_hash"])
            if done:
                event("device_signed_out", student_id=student_id, device=device)
            return done
    return False


def end_other_sessions(student_id: str, current_token: str, device: Device | None = None) -> int:
    n = db.delete_other_sessions(student_id, auth.token_hash(current_token))
    if n:
        event("other_devices_signed_out", student_id=student_id, device=device, detail=str(n))
    return n
