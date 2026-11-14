"""Sign-in for the Next.js app: the accounts of piq/accounts.py behind HTTP routes.

Sign-up ends with a 9-digit code by email; signing in afterwards takes only the password, and the
code is asked as well when the email was never confirmed or after CODE_AFTER_FAILURES wrong tries
in a row (on the account, or in this browser). The session lives in an HttpOnly cookie, so page
scripts never see it. Between the steps the browser holds a signed `step` token (who is signing
in and why, never the code or the password): it cannot be forged for another account, and the
code is still checked against the account's attempt limit and lockout.

Every browser gets a random device id (another HttpOnly cookie): sessions record the device they
are on, a sign-in on a new one is emailed to the student, and the student can list and sign out
their devices. Routes that act for a student call `owner` / `authorize` / `require_student`; the
client's claim of an id is never trusted, only the session's.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from piq import accounts, db, devices, prefs, services
from piq.config import CODE_AFTER_FAILURES, DEVICE_COOKIE_TTL_S, SESSION_TTL_S, settings
from piq.services import ServiceError

COOKIE = "ssn_session"
DEVICE_COOKIE = "ssn_device"
OPS_COOKIE = "ssn_ops"
OPS_TTL_S = 12 * 3600
STEP_TTL_S = 3600  # how long the code page can stay open
RATE_MAX, RATE_WINDOW_S = 30, 600  # sign-in requests per client address per window
WRONG_WINDOW_S = 30 * 60  # wrong tries in a browser count toward asking the code for this long

router = APIRouter(prefix="/api/auth", tags=["auth"])

_process_key = secrets.token_bytes(32)  # used when AUTH_PEPPER is not set (steps die on restart)
_hits: dict[str, list[float]] = {}
_wrong: dict[str, tuple[int, float]] = {}
_ops: dict[str, float] = {}  # hash of an operations-view token -> expiry
_lock = threading.Lock()


# --- the step token -----------------------------------------------------------------------------


def _key() -> bytes:
    pepper = settings().auth_pepper
    return hashlib.sha256(b"step|" + pepper.encode()).digest() if pepper else _process_key


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(p: accounts.Pending) -> str:
    body = json.dumps(
        {
            "s": p.student_id,
            "p": p.purpose,
            "t": p.sent_to,
            "o": p.outbox,
            "w": p.welcome,
            "e": int(time.time()) + STEP_TTL_S,
        },
        separators=(",", ":"),
    ).encode()
    return f"{_b64(body)}.{_b64(hmac.new(_key(), body, hashlib.sha256).digest())}"


def unseal(token: str, purpose: str) -> accounts.Pending:
    expired = HTTPException(400, "That step has expired. Start again.")
    try:
        body_b64, sig_b64 = token.split(".")
        body = _unb64(body_b64)
        good = hmac.compare_digest(_unb64(sig_b64), hmac.new(_key(), body, hashlib.sha256).digest())
        data = json.loads(body)
    except (ValueError, TypeError):
        raise expired from None
    if not good or data.get("e", 0) < time.time() or data.get("p") != purpose:
        raise expired
    return accounts.Pending(data["s"], data["p"], data["t"], data["o"], data["w"])


def _step(p: accounts.Pending) -> dict:
    return {
        "step": seal(p),
        "sent_to": p.sent_to,
        "outbox": p.outbox,
        "welcome": p.welcome,
        "purpose": p.purpose,
    }


# --- cookies, devices and who is asking ---------------------------------------------------------


def _secure(request: Request) -> bool:
    forced = os.getenv("COOKIE_SECURE", "").strip().lower()
    if forced in {"1", "true", "yes"}:
        return True
    if forced in {"0", "false", "no"}:
        return False
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def _cookie(request: Request, response: Response, name: str, value: str, age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=age,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path="/",
    )


def device(request: Request, response: Response) -> devices.Device:
    """This browser as a Device; a browser without a device id is given one."""
    did = request.cookies.get(DEVICE_COOKIE)
    if not devices.valid_id(did):
        did = devices.new_id()
        _cookie(request, response, DEVICE_COOKIE, did, DEVICE_COOKIE_TTL_S)
    peer = request.client.host if request.client else ""
    return devices.from_headers(request.headers, did, peer)  # type: ignore[arg-type]


def _start_session(
    request: Request, response: Response, student_id: str, d: devices.Device
) -> dict:
    _cookie(request, response, COOKIE, accounts.create_session(student_id, d), SESSION_TTL_S)
    return {"student": public(student_id)}


def public(student_id: str) -> dict | None:
    row = db.student(student_id)
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "username": row["username"],
        "target_role": row["target_role"],
        "readiness_score": row["readiness_score"],
        "must_change_password": bool(row["must_change_password"]),
    }


def session_id(request: Request) -> str | None:
    return accounts.session_student(request.cookies.get(COOKIE))


def require_student(request: Request) -> str:
    sid = session_id(request)
    if sid is None:
        raise HTTPException(401, "Sign in to continue.")
    return sid


def authorize(request: Request, candidate_id: str | None) -> None:
    """When a request names a student, it must be the one signed in."""
    if candidate_id and require_student(request) != candidate_id:
        raise HTTPException(403, "That is not your account.")


def owner(request: Request, candidate_id: str) -> str:
    """Dependency for routes with a `{candidate_id}` path: only that student gets in."""
    authorize(request, candidate_id)
    return candidate_id


def _client(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def throttle(request: Request) -> None:
    """A coarse limit on sign-in requests per address (no email flooding, no code guessing at
    speed); the account lockout and each code's attempt limit are the precise guards."""
    now = time.monotonic()
    who = _client(request)
    with _lock:
        recent = [t for t in _hits.get(who, []) if now - t < RATE_WINDOW_S]
        if len(recent) >= RATE_MAX:
            _hits[who] = recent
            raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
        recent.append(now)
        _hits[who] = recent
        if len(_hits) > 5000:  # forget addresses that have gone quiet
            for k in [k for k, v in _hits.items() if not v or now - v[-1] >= RATE_WINDOW_S]:
                del _hits[k]


def _browser_key(request: Request) -> str:
    did = request.cookies.get(DEVICE_COOKIE)
    return did if devices.valid_id(did) else _client(request)


def _wrong_tries(key: str) -> int:
    with _lock:
        count, at = _wrong.get(key, (0, 0.0))
        return count if time.monotonic() - at < WRONG_WINDOW_S else 0


def _count_wrong(key: str) -> None:
    with _lock:
        count, at = _wrong.get(key, (0, 0.0))
        now = time.monotonic()
        _wrong[key] = ((count if now - at < WRONG_WINDOW_S else 0) + 1, now)


def _clear_wrong(key: str) -> None:
    with _lock:
        _wrong.pop(key, None)


def reset_throttle() -> None:
    with _lock:
        _hits.clear()
        _wrong.clear()
        _ops.clear()


# --- the operations view's sign-in --------------------------------------------------------------


def _ops_secret_matches(password: str) -> bool:
    secret = settings().dev_secret
    return bool(secret) and hmac.compare_digest(password.encode(), secret.encode())


def _start_ops(request: Request, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for k in [k for k, v in _ops.items() if v < now]:
            del _ops[k]
        _ops[hashlib.sha256(token.encode()).hexdigest()] = now + OPS_TTL_S
    _cookie(request, response, OPS_COOKIE, token, OPS_TTL_S)


def ops_signed_in(request: Request) -> bool:
    token = request.cookies.get(OPS_COOKIE) or ""
    with _lock:
        expiry = _ops.get(hashlib.sha256(token.encode()).hexdigest(), 0.0)
    return bool(token) and expiry > time.time()


def require_ops(request: Request) -> None:
    if not ops_signed_in(request):
        raise HTTPException(401, "Sign in to continue.")


# --- request bodies -----------------------------------------------------------------------------


class SignUp(BaseModel):
    name: str = Field(max_length=200)
    username: str = Field(max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    confirm: str = Field(max_length=200)
    target_role: str = Field(max_length=120)


class Login(BaseModel):
    identifier: str = Field(max_length=254)
    password: str = Field(max_length=200)


class Step(BaseModel):
    step: str = Field(max_length=2000)


class Code(Step):
    code: str = Field(max_length=32)


class Recover(BaseModel):
    identifier: str = Field(max_length=254)


class RecoverFinish(Code):
    password: str = Field(max_length=200)
    confirm: str = Field(max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(max_length=200)
    password: str = Field(max_length=200)
    confirm: str = Field(max_length=200)


class Prefs(BaseModel):
    preload: bool | None = None
    login_alerts: bool | None = None


# --- routes -------------------------------------------------------------------------------------


def _mode() -> dict:
    local = settings().local_mode
    return {"local": local, "signup_open": not local or db.student_count() == 0}


@router.get("/me")
def me(request: Request, response: Response) -> dict:
    """The signed-in student (or null: a visitor is not an error), and how this install signs
    in. Gives a new browser its device id."""
    device(request, response)
    sid = session_id(request)
    return {
        "student": public(sid) if sid else None,
        "mode": _mode(),
        "ops": ops_signed_in(request),
    }


@router.post("/signup", dependencies=[Depends(throttle)])
def signup(body: SignUp, request: Request, response: Response) -> dict:
    d = device(request, response)
    result = accounts.sign_up(
        body.name,
        body.username,
        body.email,
        body.password,
        body.confirm,
        body.target_role,
        device=d,
    )
    if isinstance(result, str):  # local mode: no email to confirm
        services.benchmark_profile(result)
        return _start_session(request, response, result, d)
    return _step(result)


@router.post("/login", dependencies=[Depends(throttle)])
def login(body: Login, request: Request, response: Response) -> dict:
    d = device(request, response)
    if body.identifier.strip() and _ops_secret_matches(body.password):
        _start_ops(request, response)
        accounts.event("ops_sign_in", identifier=body.identifier, device=d)
        return {"ops": True}
    key = _browser_key(request)
    risky = _wrong_tries(key) >= CODE_AFTER_FAILURES
    try:
        result = accounts.start_login(body.identifier, body.password, risky=risky, device=d)
    except ServiceError as e:
        if str(e) == accounts.WRONG_LOGIN:
            _count_wrong(key)
        raise
    if isinstance(result, str):
        _clear_wrong(key)
        return _start_session(request, response, result, d)
    return _step(result)


@router.post("/code", dependencies=[Depends(throttle)])
def code(body: Code, request: Request, response: Response) -> dict:
    d = device(request, response)
    sid = accounts.verify_code(unseal(body.step, "login"), body.code)
    _clear_wrong(_browser_key(request))
    if services.current_profile(sid) is None:
        services.benchmark_profile(sid)  # a new account starts on its role's skill list
    return _start_session(request, response, sid, d)


@router.post("/resend", dependencies=[Depends(throttle)])
def resend(body: Step, purpose: str = "login") -> dict:
    if purpose not in ("login", "recover"):
        raise ServiceError("Unknown step.")
    return _step(accounts.resend_code(unseal(body.step, purpose)))


@router.post("/recover", dependencies=[Depends(throttle)])
def recover(body: Recover) -> dict:
    return _step(accounts.start_recovery(body.identifier))


@router.post("/recover/finish", dependencies=[Depends(throttle)])
def recover_finish(body: RecoverFinish, request: Request, response: Response) -> dict:
    d = device(request, response)
    sid = accounts.finish_recovery(
        unseal(body.step, "recover"), body.code, body.password, body.confirm
    )
    _clear_wrong(_browser_key(request))
    return _start_session(request, response, sid, d)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    accounts.end_session(request.cookies.get(COOKIE), device(request, response))
    token = request.cookies.get(OPS_COOKIE) or ""
    with _lock:
        _ops.pop(hashlib.sha256(token.encode()).hexdigest(), None)
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(OPS_COOKIE, path="/")
    return {"ok": True}


@router.post("/password", dependencies=[Depends(throttle)])
def change_password(body: PasswordChange, sid: str = Depends(require_student)) -> dict:
    accounts.change_password(sid, body.current, body.password, body.confirm)
    return {"student": public(sid)}


@router.get("/sessions")
def list_sessions(request: Request, sid: str = Depends(require_student)) -> list[dict]:
    """The student's signed-in devices, newest activity first; `current` is this one."""
    return accounts.sessions(sid, request.cookies.get(COOKIE))


@router.post("/sessions/{session_id}/revoke")
def revoke_session(
    session_id: str, request: Request, response: Response, sid: str = Depends(require_student)
) -> list[dict]:
    if not accounts.end_session_id(sid, session_id, device(request, response)):
        raise HTTPException(404, "That device is already signed out.")
    return accounts.sessions(sid, request.cookies.get(COOKIE))


@router.post("/sessions/revoke-others")
def revoke_others(
    request: Request, response: Response, sid: str = Depends(require_student)
) -> list[dict]:
    accounts.end_other_sessions(sid, request.cookies.get(COOKIE) or "", device(request, response))
    return accounts.sessions(sid, request.cookies.get(COOKIE))


@router.get("/settings")
def get_settings(sid: str = Depends(require_student)) -> dict:
    return {"prefs": prefs.get(sid), "preload_allowed": settings().preload}


@router.post("/settings")
def save_settings(body: Prefs, sid: str = Depends(require_student)) -> dict:
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    return {"prefs": prefs.update(sid, changes), "preload_allowed": settings().preload}
