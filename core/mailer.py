"""Email for account codes: Gmail SMTP in the background, a local outbox file otherwise.

With SMTP_EMAIL and SMTP_APP_PASSWORD in .env (a Google App Password: Google Account ->
Security -> 2-Step Verification -> App passwords), each message goes out through
smtp.gmail.com: port 587 with STARTTLS, or 465 with implicit TLS (SMTP_PORT). Sending runs on
a small thread pool (MAIL_WORKERS), so a page moves on at once instead of waiting for the SMTP
handshake.

Without them (a fresh clone, a laptop demo), nothing is asked for on screen: the message is
appended to MAIL_OUTBOX_PATH (default data/.mail_outbox.log, git-ignored) and the page says
the code went to the local outbox. A send that fails (wrong App Password, no network) also
lands there, and the failure is logged as its type and the server's reply only: the password
never appears in a log, an exception or the page.

Welcome emails (an organization's new students, core/org_provisioning.py) also go to the outbox
when SMTP works (`also_outbox`): the admin can then hand a student their details if the email
is lost. That file holds temporary passwords in plain text, like the emails themselves; it is
git-ignored, and every one of those passwords must be changed at first sign-in.
"""

import html
import logging
import smtplib
import ssl
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Literal

from piq.config import (
    AUTH_CODE_TTL_S,
    BRAND_COLOR,
    MAIL_BATCH,
    MAIL_WORKERS,
    ORG_WELCOME_CODE_TTL_S,
    SMTP_TIMEOUT_S,
    settings,
)

log = logging.getLogger("core.mailer")
Channel = Literal["smtp", "outbox"]
Purpose = Literal["login", "recover", "verify"]
APP_NAME = "Skill Scout Nexus"
SECRET_ROWS = ("Temporary password", "9-digit code")  # shown large and monospaced
_SUBJECTS = {
    "login": f"Your {APP_NAME} sign-in code",
    "recover": f"Your {APP_NAME} account recovery code",
    "verify": f"Confirm your {APP_NAME} organization admin email",
}
_INTROS = {
    "login": "Use this code to finish signing in.",
    "recover": "Use this code to set a new password and recover your account.",
    "verify": "Use this code to confirm your email and finish setting up your organization.",
}

_executor: ThreadPoolExecutor | None = None
_futures: list[Future] = []
_lock = threading.Lock()


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str


def configured() -> bool:
    s = settings()
    return bool(s.smtp_email and s.smtp_app_password)


def code_message(to: str, name: str, code: str, purpose: Purpose) -> Message:
    """The plain-text and HTML email for a code shown as XXX-XXX-XXX (`code` is formatted)."""
    minutes = AUTH_CODE_TTL_S // 60
    intro = _INTROS[purpose]
    text = (
        f"Hello {name},\n\n{intro}\n\n    {code}\n\n"
        f"It expires in {minutes} minutes and works once. If you did not ask for it, ignore "
        f"this email: your password has not changed.\n\n{APP_NAME}"
    )
    body = f"""<!doctype html>
<html><body style="font-family:system-ui,sans-serif;color:#1f2a2c;max-width:480px">
<p>Hello {html.escape(name)},</p>
<p>{html.escape(intro)}</p>
<p style="font-size:28px;font-weight:700;letter-spacing:4px;font-family:monospace">{code}</p>
<p>It expires in {minutes} minutes and works once. If you did not ask for it, ignore this
email: your password has not changed.</p>
<p style="color:#5b6b6e">{APP_NAME}</p>
</body></html>"""
    return Message(to, _SUBJECTS[purpose], text, body)


def welcome_message(
    to: str,
    *,
    name: str,
    org_name: str,
    admin_name: str,
    main_domain: str,
    subdomain: str,
    target_role: str,
    password: str,
    code: str,
    reset: bool = False,
) -> Message:
    """The email an organization's student gets: where they study, their login email, a
    temporary password and the 9-digit code (`code` is formatted XXX-XXX-XXX) that finishes
    their first sign-in. `reset`: an admin sent new details to an existing account."""
    lead = (
        f"{admin_name} at {org_name} has reset your {APP_NAME} password."
        if reset
        else f"{admin_name} at {org_name} has set up your {APP_NAME} account."
    )
    subject = (
        f"Your new {APP_NAME} sign-in details from {org_name}"
        if reset
        else f"Your {org_name} account on {APP_NAME}"
    )
    steps = (
        f"1. Open {APP_NAME} and choose Student / Learner access.\n"
        "2. Sign in with your login email and the temporary password.\n"
        "3. Enter the 9-digit code when asked.\n"
        "4. Choose a password of your own when the app offers to."
    )
    rows = (
        ("Organization", org_name),
        ("Administrator", admin_name),
        ("Domain", f"{main_domain} / {subdomain}"),
        ("Target role", target_role),
        ("Login email", to),
        ("Temporary password", password),
        ("9-digit code", code),
    )
    days = ORG_WELCOME_CODE_TTL_S // 86400
    text = (
        f"Hello {name},\n\n{lead}\n\n"
        + "\n".join(f"  {label}: {value}" for label, value in rows)
        + f"\n\n{steps}\n\nThe password is temporary and the code works for {days} days. "
        f"Do not share either.\n\n{APP_NAME}"
    )
    secret = ";font-family:monospace;font-size:16px"
    cells = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#5b6b6e">{html.escape(label)}</td>'
        f'<td style="padding:6px 0;font-weight:600{secret if label in SECRET_ROWS else ""}">'
        f"{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    steps_html = "".join(f"<li>{html.escape(line[3:])}</li>" for line in steps.splitlines())
    body = f"""<!doctype html>
<html><body style="margin:0;font-family:system-ui,sans-serif;color:#1f2a2c">
<div style="max-width:520px;margin:0 auto">
<div style="background:{BRAND_COLOR};color:#fff;padding:16px 20px;font-size:18px;font-weight:700">
{APP_NAME}</div>
<div style="padding:20px">
<p>Hello {html.escape(name)},</p>
<p>{html.escape(lead)}</p>
<table style="border-collapse:collapse">{cells}</table>
<ol style="padding-left:20px">{steps_html}</ol>
<p style="color:#5b6b6e">The password is temporary and the code works for
{days} days. Do not share either.</p>
</div></div></body></html>"""
    return Message(to, subject, text, body)


def _email(msg: Message, sender: str) -> EmailMessage:
    email = EmailMessage()
    email["From"], email["To"], email["Subject"] = f"{APP_NAME} <{sender}>", msg.to, msg.subject
    email.set_content(msg.text)
    email.add_alternative(msg.html, subtype="html")
    return email


@contextmanager
def _connection() -> Iterator[smtplib.SMTP]:
    """A logged-in SMTP connection (port 587 STARTTLS, or 465 implicit TLS)."""
    s = settings()
    context = ssl.create_default_context()
    if s.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            s.smtp_host, 465, timeout=SMTP_TIMEOUT_S, context=context
        )
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_S)
    with server:
        if s.smtp_port != 465:
            server.starttls(context=context)
        server.login(s.smtp_email, s.smtp_app_password)
        yield server


def write_outbox(msg: Message, note: str = "") -> None:
    """Append the message to the local outbox (developers read the code there)."""
    path = settings().mail_outbox_path
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    entry = f"--- {stamp} to {msg.to}: {msg.subject}{f' ({note})' if note else ''}\n{msg.text}\n\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as e:
        log.warning("mail outbox %s could not be written: %s", path, type(e).__name__)


def _deliver_batch(msgs: Sequence[Message], *, logged: bool = False) -> Channel:
    """Send every message over ONE connection. A message the server refuses, or all that are
    left when the connection fails, go to the local outbox instead (unless `logged`: they are
    there already); only the reply is logged, never the credentials."""
    done = 0
    try:
        with _connection() as server:
            sender = settings().smtp_email
            for msg in msgs:
                try:
                    server.send_message(_email(msg, sender))
                except smtplib.SMTPException as e:
                    log.warning("mail: %s refused (%s)", msg.subject, type(e).__name__)
                    if not logged:
                        write_outbox(msg, "SMTP refused it")
                done += 1
    except (smtplib.SMTPException, OSError) as e:
        reason = f"{type(e).__name__}: {str(e)[:200]}"
        log.warning("mail: SMTP failed (%s); the rest went to the local outbox", reason)
        for msg in msgs[done:]:
            if not logged:
                write_outbox(msg, "SMTP failed")
        return "outbox"
    log.info("mail: %d message(s) sent by SMTP", len(msgs))
    return "smtp"


def send_many(msgs: Sequence[Message], *, also_outbox: bool = False) -> Channel:
    """Queue every message and return at once, as `send` does for one: "smtp" when they are on
    their way, "outbox" when SMTP is not set up and they were written to the local outbox
    instead. The queue works in batches of MAIL_BATCH, each over one connection, so hundreds of
    welcome emails do not each pay for a login. `also_outbox`: write each to the outbox too."""
    if not msgs:
        return "outbox" if not configured() else "smtp"
    logged = also_outbox or not configured()
    if logged:
        for msg in msgs:
            write_outbox(msg)
    if not configured():
        return "outbox"
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(MAIL_WORKERS, thread_name_prefix="mail")
        _futures[:] = [f for f in _futures if not f.done()]
        for i in range(0, len(msgs), MAIL_BATCH):
            batch = list(msgs[i : i + MAIL_BATCH])
            _futures.append(_executor.submit(_deliver_batch, batch, logged=logged))
    return "smtp"


def send(msg: Message, *, also_outbox: bool = False) -> Channel:
    """Queue `msg` and return at once: "smtp" when it is on its way, "outbox" when SMTP is not
    set up and it was written to the local outbox instead. `also_outbox`: write it there even
    when SMTP is set up."""
    return send_many([msg], also_outbox=also_outbox)


def wait_idle(timeout: float = 30.0) -> None:
    """Wait for queued messages (tests; a clean shutdown)."""
    with _lock:
        pending = list(_futures)
    wait(pending, timeout=timeout)


def reset() -> None:
    """Finish queued messages and drop the pool (tests)."""
    global _executor
    with _lock:
        executor, _executor = _executor, None
        _futures.clear()
    if executor is not None:
        executor.shutdown(wait=True)
