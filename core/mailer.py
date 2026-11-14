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

Every message shares one branded layout (header with the logo, a card, a footer with the Terms
and Privacy links at APP_URL); the logo is the PNG static/brand/mark-email.png, attached inline.

Welcome emails (an organization's new students, core/org_provisioning.py) also go to the outbox
when SMTP works (`also_outbox`): the admin can then hand a student their details if the email
is lost. That file holds temporary passwords in plain text, like the emails themselves; it is
git-ignored, and every one of those passwords must be changed at first sign-in.
"""
# ruff: noqa: E501  (the HTML templates carry long inline-CSS lines)

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
    BRAND_DIR,
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
_TITLES = {
    "login": "Your sign-in code",
    "recover": "Recover your account",
    "verify": "Confirm your email",
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


LOGO_CID = "brandmark"
LOGO_PATH = BRAND_DIR / "mark-email.png"  # the brand mark as a PNG: Gmail and Outlook show no SVG
TAGLINE = "Adaptive placement-readiness coaching"
_FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

# Colours survive inversion: the dark-mode block repaints the surfaces, the brand band stays.
_STYLE = """
body{margin:0;padding:0}
@media (max-width:620px){.wrap{width:100%!important}.pad{padding-left:20px!important;padding-right:20px!important}
.code{font-size:24px!important;letter-spacing:2px!important}}
@media (prefers-color-scheme:dark){
.bg{background:#0E1A1B!important}.card{background:#16282A!important;border-color:#25393B!important}
.tx{color:#E7EFEF!important}.mu{color:#9DB2B4!important}.lk{color:#7FD0D6!important}
.codebox{background:#0E1A1B!important;border-color:#3A9AA1!important}.code{color:#F2FAFA!important}
.note{background:#1D3033!important;color:#C5D6D8!important}.rule{border-color:#25393B!important}}
"""


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _links() -> tuple[str, str, str]:
    base = settings().app_url
    return base, f"{base}/terms", f"{base}/privacy"


def _logo_cell() -> str:
    """The mark as an inline image when the PNG exists, else a plain monogram."""
    if LOGO_PATH.is_file():
        return (
            f'<img src="cid:{LOGO_CID}" width="40" height="40" alt="" '
            'style="display:block;border:0;border-radius:10px">'
        )
    return (
        '<div style="width:40px;height:40px;line-height:40px;border-radius:10px;text-align:center;'
        f'background:#ffffff;color:{BRAND_COLOR};font:700 20px {_FONT}">S</div>'
    )


def _code_block(value: str) -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:22px 0"><tr><td align="center" class="codebox" '
        f'style="background:#E9F5F6;border:2px dashed {BRAND_COLOR};border-radius:12px;'
        'padding:18px 12px">'
        f'<span class="code" style="font-family:{_MONO};font-size:34px;font-weight:700;'
        f'letter-spacing:5px;color:#0B3A3E">{_esc(value)}</span></td></tr></table>'
    )


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:26px 0 6px"><tr>'
        f'<td align="center" bgcolor="{BRAND_COLOR}" style="border-radius:10px">'
        f'<a href="{_esc(url)}" style="display:inline-block;padding:14px 28px;color:#ffffff;'
        f'font:600 16px {_FONT};text-decoration:none;border-radius:10px">{_esc(label)}</a>'
        "</td></tr></table>"
    )


def _note(text: str, lead: str = "Keep it private.") -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin-top:22px"><tr><td class="note" '
        'style="background:#F1F5F5;border-radius:10px;padding:12px 14px;color:#4A5C5E;'
        f'font:14px/1.5 {_FONT}"><strong>{_esc(lead)}</strong> {_esc(text)}</td></tr></table>'
    )


def _layout(*, title: str, preheader: str, body: str, notice: str) -> str:
    """The shared frame: brand band, card with the body, footer with the policy links."""
    base, terms, privacy = _links()
    support = settings().support_email
    support_html = (
        f' &middot; Need help? <a class="lk" href="mailto:{_esc(support)}" '
        f'style="color:{BRAND_COLOR}">{_esc(support)}</a>'
        if support
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{_esc(title)}</title><style>{_STYLE}</style></head>
<body class="bg" style="margin:0;padding:0;background:#EEF3F3">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{_esc(preheader)}</div>
<table role="presentation" class="bg" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#EEF3F3"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" class="wrap" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:100%">
<tr><td style="background:{BRAND_COLOR};border-radius:14px 14px 0 0;padding:20px 28px" class="pad">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="vertical-align:middle;padding-right:12px">{_logo_cell()}</td>
<td style="vertical-align:middle;color:#ffffff;font:700 20px {_FONT};letter-spacing:-0.2px">{APP_NAME}
<div style="font:400 12px {_FONT};opacity:.85;letter-spacing:0">{TAGLINE}</div></td></tr></table>
</td></tr>
<tr><td class="card pad" style="background:#ffffff;border:1px solid #DCE6E6;border-top:0;border-radius:0 0 14px 14px;padding:30px 28px 28px">
<h1 class="tx" style="margin:0 0 14px;color:#14282B;font:700 24px/1.25 {_FONT}">{_esc(title)}</h1>
<div class="tx" style="color:#26393C;font:16px/1.6 {_FONT}">{body}</div>
</td></tr>
<tr><td class="pad" style="padding:22px 28px 6px;text-align:center">
<p class="mu" style="margin:0 0 8px;color:#5F7274;font:13px/1.6 {_FONT}">{notice}</p>
<p class="mu" style="margin:0 0 8px;color:#5F7274;font:13px/1.6 {_FONT}">
<a class="lk" href="{_esc(base)}" style="color:{BRAND_COLOR}">{APP_NAME}</a> &middot;
<a class="lk" href="{_esc(terms)}" style="color:{BRAND_COLOR}">Terms</a> &middot;
<a class="lk" href="{_esc(privacy)}" style="color:{BRAND_COLOR}">Privacy</a>{support_html}</p>
<p class="mu" style="margin:0;color:#7A8C8E;font:12px/1.6 {_FONT}">By using {APP_NAME} you agree to the Terms and the Privacy Policy linked above.
This is an automated message: it is sent only when an account on {APP_NAME} needs it.</p>
</td></tr></table></td></tr></table></body></html>"""


def _text_footer(notice: str) -> str:
    base, terms, privacy = _links()
    support = settings().support_email
    lines = [
        "--",
        f"{APP_NAME}: {TAGLINE}",
        f"Terms: {terms}",
        f"Privacy: {privacy}",
    ]
    if support:
        lines.append(f"Need help? {support}")
    lines += ["", notice, f"By using {APP_NAME} you agree to the Terms and the Privacy Policy."]
    return "\n".join(lines)


def code_message(to: str, name: str, code: str, purpose: Purpose) -> Message:
    """The plain-text and HTML email for a code shown as XXX-XXX-XXX (`code` is formatted)."""
    minutes = AUTH_CODE_TTL_S // 60
    intro = _INTROS[purpose]
    security = f"It expires in {minutes} minutes and works once. Never share it with anyone."
    ignore = "If you did not ask for it, ignore this email: your password has not changed."
    notice = (
        f"You received this email because a code was requested for the {APP_NAME} account "
        "with this address."
    )
    text = (
        f"Hello {name},\n\n{intro}\n\n    {code}\n\n{security} {ignore}\n\n{_text_footer(notice)}"
    )
    body = (
        f'<p style="margin:0 0 12px">Hello {_esc(name)},</p><p style="margin:0">{_esc(intro)}</p>'
        f"{_code_block(code)}"
        f'<p style="margin:0">{_esc(ignore)}</p>{_note(security)}'
    )
    page = _layout(
        title=_TITLES[purpose],
        preheader=f"{intro} Your code expires in {minutes} minutes.",
        body=body,
        notice=_esc(notice),
    )
    return Message(to, _SUBJECTS[purpose], text, page)


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
        f"Open {APP_NAME} and choose Sign in.",
        "Enter your login email and the temporary password.",
        "Enter the 9-digit code when asked.",
        "Choose a password of your own when the app offers to.",
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
    security = f"The password is temporary and the code works for {days} days. Do not share either."
    notice = f"You received this email because {org_name} added you as a student on {APP_NAME}."
    text = (
        f"Hello {name},\n\n{lead}\n\n"
        + "\n".join(f"  {label}: {value}" for label, value in rows)
        + "\n\n"
        + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        + f"\n\nSign in: {settings().app_url}\n\n{security}\n\n{_text_footer(notice)}"
    )
    cells = "".join(
        f'<tr><td class="mu rule" style="padding:9px 14px 9px 0;color:#5F7274;font:14px {_FONT};'
        f'border-top:1px solid #E3EBEB;vertical-align:top" width="38%">{_esc(label)}</td>'
        f'<td class="tx rule" style="padding:9px 0;border-top:1px solid #E3EBEB;font:600 15px {_FONT}'
        f'{";" + _secret_style() if label in SECRET_ROWS else ""}">{_esc(value)}</td></tr>'
        for label, value in rows
    )
    steps_html = "".join(f'<li style="margin:0 0 6px">{_esc(s)}</li>' for s in steps)
    body = (
        f'<p style="margin:0 0 12px">Hello {_esc(name)},</p><p style="margin:0 0 18px">{_esc(lead)}</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{cells}</table>"
        f'<p style="margin:22px 0 8px;font-weight:700">Get started</p>'
        f'<ol style="margin:0;padding-left:20px">{steps_html}</ol>'
        f"{_button('Sign in to ' + APP_NAME, settings().app_url)}{_note(security)}"
    )
    page = _layout(
        title="Your account is ready" if not reset else "Your sign-in details were reset",
        preheader=f"{lead} Your login email, temporary password and code are inside.",
        body=body,
        notice=_esc(notice),
    )
    return Message(to, subject, text, page)


def new_device_message(
    to: str,
    *,
    name: str,
    browser: str,
    os: str,
    ip: str,
    location: str,
    when: str,
    signed_up: bool = False,
) -> Message:
    """A sign-in (or the sign-up) on a device the account had not used before."""
    lead = (
        f"Your {APP_NAME} account was created and signed in on this device."
        if signed_up
        else f"Your {APP_NAME} account was just signed in on a new device."
    )
    rows = (
        ("When", when),
        ("Browser", browser),
        ("Operating system", os),
        ("IP address", ip or "Unknown"),
        ("Location", location or "Unknown (approximate, from the network)"),
    )
    settings_url = f"{settings().app_url}/settings"
    act = (
        "If this was not you, reset your password now and sign that device out from "
        "Settings > Signed-in devices."
    )
    notice = (
        f"You received this email because a new device signed in to your {APP_NAME} account. "
        "You can turn these alerts off in Settings."
    )
    text = (
        f"Hello {name},\n\n{lead}\n\n"
        + "\n".join(f"  {label}: {value}" for label, value in rows)
        + f"\n\nIf this was you, there is nothing to do. {act}\n\nSettings: {settings_url}"
        + f"\n\n{_text_footer(notice)}"
    )
    cells = "".join(
        f'<tr><td class="mu rule" style="padding:9px 14px 9px 0;color:#5F7274;font:14px {_FONT};'
        f'border-top:1px solid #E3EBEB;vertical-align:top" width="38%">{_esc(label)}</td>'
        f'<td class="tx rule" style="padding:9px 0;border-top:1px solid #E3EBEB;font:600 15px {_FONT}">'
        f"{_esc(value)}</td></tr>"
        for label, value in rows
    )
    body = (
        f'<p style="margin:0 0 12px">Hello {_esc(name)},</p><p style="margin:0 0 18px">{_esc(lead)}</p>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{cells}</table>"
        '<p style="margin:20px 0 0">If this was you, there is nothing to do.</p>'
        f"{_button('Review signed-in devices', settings_url)}{_note(act, 'Not you?')}"
    )
    page = _layout(
        title="New sign-in to your account" if not signed_up else "Welcome: your account is ready",
        preheader=f"{browser} on {os}, {location or ip or 'unknown location'}, {when}.",
        body=body,
        notice=_esc(notice),
    )
    subject = (
        f"New sign-in to your {APP_NAME} account" if not signed_up else f"Welcome to {APP_NAME}"
    )
    return Message(to, subject, text, page)


def _secret_style() -> str:
    return f"font-family:{_MONO};font-size:16px;letter-spacing:.5px"


def nudge_message(
    to: str,
    *,
    name: str,
    org_name: str,
    pending_tasks: Sequence[str],
    momentum_stage: str = "Falling Behind",
) -> Message:
    """A polite reminder email for a student who is falling behind or stalled, containing their
    pending tasks and encouragement to get back on track."""
    subject = f"Get back on track with your {APP_NAME} placement preparation"
    task_items = list(pending_tasks) or ["Resume and complete your pending study plan roadmap"]
    task_lines = "\n".join(f"- {task}" for task in task_items)
    notice = f"You received this email because you are enrolled with {org_name} on {APP_NAME}."
    text = (
        f"Hello {name},\n\n"
        f"This is a friendly reminder from {org_name} regarding your placement preparation "
        f"on {APP_NAME}.\n\n"
        f"Our records show that your progress is currently {momentum_stage}. Consistent "
        f"preparation is key to clearing placement cutoffs and securing top roles.\n\n"
        f"Here are your recommended next steps to get back on track:\n"
        f"{task_lines}\n\n"
        f"Log in to {APP_NAME} today to continue your preparation: {settings().app_url}\n\n"
        f"Best regards,\n{org_name} Placement Team\n{APP_NAME}\n\n{_text_footer(notice)}"
    )
    items_html = "".join(f'<li style="margin:0 0 8px">{_esc(task)}</li>' for task in task_items)
    body = (
        f'<p style="margin:0 0 12px">Hello {_esc(name)},</p>'
        f'<p style="margin:0 0 12px">This is a friendly reminder from <strong>{_esc(org_name)}</strong> '
        f"about your placement preparation on {APP_NAME}.</p>"
        f'<p style="margin:0 0 16px">Your learning momentum is currently '
        f'<strong style="color:{BRAND_COLOR}">{_esc(momentum_stage)}</strong>. Steady daily practice '
        "is what clears company cutoffs.</p>"
        '<p style="margin:0 0 8px;font-weight:700">Your next steps</p>'
        f'<ul style="margin:0;padding-left:20px">{items_html}</ul>'
        f"{_button('Continue your preparation', settings().app_url)}"
        f'<p class="mu" style="margin:18px 0 0;color:#5F7274">Best regards,<br>'
        f"{_esc(org_name)} Placement Team</p>"
    )
    page = _layout(
        title="Time to get back on track",
        preheader=f"{org_name} placement team: your next steps are waiting on {APP_NAME}.",
        body=body,
        notice=_esc(notice),
    )
    return Message(to, subject, text, page)


def _email(msg: Message, sender: str) -> EmailMessage:
    email = EmailMessage()
    email["From"], email["To"], email["Subject"] = f"{APP_NAME} <{sender}>", msg.to, msg.subject
    email.set_content(msg.text)
    email.add_alternative(msg.html, subtype="html")
    if f"cid:{LOGO_CID}" in msg.html and LOGO_PATH.is_file():
        body = email.get_body(("html",))
        body.add_related(  # type: ignore[union-attr]
            LOGO_PATH.read_bytes(), "image", "png", cid=f"<{LOGO_CID}>", disposition="inline"
        )
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
