"""A student's own Google Drive: a "Skill Scout Nexus" folder with "Certificates" and "Resumes".

Plain httpx against Google's REST endpoints (no google-api-python-client). Only the drive.file
scope is ever requested, so the app sees only the files it created, never the rest of a
student's Drive; a sign-in that grants anything else is refused and revoked.

- OAuth: authorization code with PKCE (S256) and a single-use state. Only the state's SHA-256 is
  stored, with the verifier encrypted, and it expires after STATE_TTL_S. The state is bound to the
  student who started it, and to the redirect URI used (one of the two configured, never input).
- The refresh token is stored encrypted (core/secretbox.py, bound to the student). The access
  token lives in memory only. Neither is ever logged.
- The client follows no redirects, ignores proxy variables, and talks only to Google's fixed
  hosts below (tests swap the client for an httpx.MockTransport).

Off unless settings().drive_enabled (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, DRIVE_TOKEN_KEY).
"""

import base64
import contextlib
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import uuid
from functools import lru_cache
from typing import Literal
from urllib.parse import urlencode

import httpx

from core import secretbox
from piq import db
from piq.config import settings

log = logging.getLogger("core.drive")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT, CERTIFICATES, RESUMES = "Skill Scout Nexus", "Certificates", "Resumes"
STATE_TTL_S = 600
MAX_DOWNLOAD_BYTES = 6 * 1024 * 1024
_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")

Ui = Literal["web", "streamlit"]
Kind = Literal["certificates", "resumes"]


class DriveError(Exception):
    """Something the student should read: a short reason, never a token or a raw reply."""


class DriveDisabled(DriveError):
    def __init__(self) -> None:
        super().__init__("Google Drive is not set up on this server.")


class NotConnected(DriveError):
    """The student has no Drive connected (or it was disconnected: connect again)."""


@lru_cache
def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20.0, connect=5.0)
    )


def enabled() -> bool:
    return settings().drive_enabled


def _require_enabled() -> None:
    if not enabled():
        raise DriveDisabled()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _request(method: str, url: str, **kw: object) -> httpx.Response:
    try:
        return _client().request(method, url, **kw)  # type: ignore[arg-type]
    except httpx.HTTPError as e:
        raise DriveError("Google Drive is not answering right now. Try again shortly.") from e


# --- signing in ----------------------------------------------------------------------------------


def redirect_uri(ui: Ui) -> str:
    s = settings()
    return s.google_redirect_uri if ui == "web" else s.google_streamlit_redirect_uri


def start(student_id: str, ui: Ui) -> str:
    """The Google sign-in address for this student (only the drive.file scope)."""
    _require_enabled()
    if ui not in ("web", "streamlit"):
        raise DriveError("Unknown app.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 characters: within PKCE's 43-128
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    uri = redirect_uri(ui)
    db.save_drive_state(
        _sha(state),
        student_id,
        secretbox.seal(verifier, student_id=student_id, purpose="pkce"),
        uri,
        ui,
        time.time() + STATE_TTL_S,
    )
    params = {
        "client_id": settings().google_client_id,
        "redirect_uri": uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def finish(state: str | None, code: str | None, *, signed_in: str, ui: Ui) -> None:
    """Complete a sign-in: the state must be known, unexpired, unused, started by this student
    in this app, and Google must grant exactly the drive.file scope with a refresh token."""
    _require_enabled()
    row = db.take_drive_state(_sha(state or "")) if state else None
    if row is None or row["expires_at"] < time.time():
        raise DriveError("That Google sign-in has expired or was already used. Connect again.")
    if row["student_id"] != signed_in or row["return_to"] != ui:
        raise DriveError("That Google sign-in was started elsewhere. Connect again from here.")
    if not code:
        raise DriveError("Google did not finish the sign-in. Connect again.")
    try:
        verifier = secretbox.open_(row["verifier_enc"], student_id=signed_in, purpose="pkce")
    except secretbox.SecretError as e:
        raise DriveError("That Google sign-in cannot be completed. Connect again.") from e
    s = settings()
    r = _request(
        "POST",
        TOKEN_URL,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": row["redirect_uri"],
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
    )
    if r.status_code != 200:
        log.info("drive: the token exchange was refused (HTTP %s)", r.status_code)
        raise DriveError("Google refused the sign-in. Connect again.")
    data = r.json()
    granted = set(str(data.get("scope", "")).split())
    if granted != {SCOPE}:
        _revoke(data.get("refresh_token") or data.get("access_token") or "")
        raise DriveError(
            "Google granted different access than this app asks for, so nothing was saved."
        )
    refresh = data.get("refresh_token")
    if not refresh:
        raise DriveError(
            "Google did not give lasting access. Remove Skill Scout Nexus from your Google "
            "account's third-party access, then connect again."
        )
    db.save_drive_account(
        signed_in, secretbox.seal(refresh, student_id=signed_in, purpose="refresh"), SCOPE
    )
    _remember(signed_in, data.get("access_token", ""), int(data.get("expires_in", 0)))
    ensure_folders(signed_in)


# --- access tokens (memory only) ------------------------------------------------------------

_tokens: dict[str, tuple[str, float]] = {}
_tokens_lock = threading.Lock()


def _remember(student_id: str, token: str, expires_in: int) -> None:
    if token:
        with _tokens_lock:
            _tokens[student_id] = (token, time.time() + max(0, expires_in - 60))


def _forget(student_id: str) -> None:
    with _tokens_lock:
        _tokens.pop(student_id, None)


def _access_token(student_id: str) -> str:
    with _tokens_lock:
        cached = _tokens.get(student_id)
    if cached and cached[1] > time.time():
        return cached[0]
    row = db.drive_account(student_id)
    if row is None:
        raise NotConnected("Connect your Google Drive first.")
    try:
        refresh = secretbox.open_(
            row["refresh_token_enc"], student_id=student_id, purpose="refresh"
        )
    except secretbox.SecretError as e:  # the server's key changed: start again
        db.delete_drive_account(student_id)
        raise NotConnected("Your Google Drive needs to be connected again.") from e
    s = settings()
    r = _request(
        "POST",
        TOKEN_URL,
        data={
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
    )
    if r.status_code == 400 and r.json().get("error") == "invalid_grant":
        db.delete_drive_account(student_id)  # access was removed in the Google account
        _forget(student_id)
        raise NotConnected("Your Google Drive was disconnected in Google. Connect it again.")
    if r.status_code != 200:
        raise DriveError("Google Drive is not answering right now. Try again shortly.")
    data = r.json()
    _remember(student_id, data["access_token"], int(data.get("expires_in", 0)))
    return data["access_token"]


def _api(
    student_id: str,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    **kw: object,
) -> httpx.Response:
    """An authorised Drive call; a 401 (an expired token) is retried once with a fresh one."""
    for attempt in range(2):
        auth = {"Authorization": f"Bearer {_access_token(student_id)}", **(headers or {})}
        r = _request(method, url, headers=auth, **kw)
        if r.status_code != 401 or attempt:
            return r
        _forget(student_id)
    return r


# --- folders -------------------------------------------------------------------------------------


def _create_folder(student_id: str, name: str, parent: str | None) -> str:
    body: dict = {"name": name, "mimeType": FOLDER_MIME}
    if parent:
        body["parents"] = [parent]
    r = _api(student_id, "POST", FILES_URL, params={"fields": "id"}, json=body)
    if r.status_code != 200:
        raise DriveError("Could not create the folder in Google Drive.")
    return r.json()["id"]


def _usable(student_id: str, folder_id: str) -> bool:
    if not folder_id or not _FILE_ID.match(folder_id):
        return False
    r = _api(student_id, "GET", f"{FILES_URL}/{folder_id}", params={"fields": "id,trashed"})
    return r.status_code == 200 and not r.json().get("trashed", False)


def ensure_folders(student_id: str) -> dict[str, str]:
    """The three folders' ids, creating any the student deleted or trashed."""
    _require_enabled()
    row = db.drive_account(student_id)
    if row is None:
        raise NotConnected("Connect your Google Drive first.")
    root, certs, resumes = row["root_id"], row["certs_id"], row["resumes_id"]
    if not _usable(student_id, root):
        root = _create_folder(student_id, ROOT, None)
        certs = resumes = ""
    if not _usable(student_id, certs):
        certs = _create_folder(student_id, CERTIFICATES, root)
    if not _usable(student_id, resumes):
        resumes = _create_folder(student_id, RESUMES, root)
    if (root, certs, resumes) != (row["root_id"], row["certs_id"], row["resumes_id"]):
        db.set_drive_folders(student_id, root, certs, resumes)
    return {"root": root, "certificates": certs, "resumes": resumes}


# --- files ---------------------------------------------------------------------------------------


def upload(student_id: str, kind: Kind, name: str, data: bytes) -> dict[str, str]:
    """A PDF into Certificates or Resumes: its {id, link}."""
    folder = ensure_folders(student_id)[kind]
    boundary = f"ssn-{uuid.uuid4().hex}"
    meta = json.dumps({"name": name, "parents": [folder], "mimeType": "application/pdf"})
    body = (
        (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/pdf\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    r = _api(
        student_id,
        "POST",
        UPLOAD_URL,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        params={"uploadType": "multipart", "fields": "id,webViewLink"},
        content=body,
    )
    if r.status_code != 200:
        raise DriveError("Could not save the file to Google Drive.")
    out = r.json()
    return {"id": out["id"], "link": out.get("webViewLink", "")}


def download(student_id: str, file_id: str) -> bytes:
    if not _FILE_ID.match(file_id or ""):
        raise DriveError("That Drive file cannot be found.")
    r = _api(student_id, "GET", f"{FILES_URL}/{file_id}", params={"alt": "media"})
    if r.status_code != 200:
        raise DriveError("That file is no longer in your Google Drive.")
    if len(r.content) > MAX_DOWNLOAD_BYTES:
        raise DriveError("That Drive file is larger than a certificate can be.")
    return r.content


def trash(student_id: str, file_id: str) -> None:
    """Move a file the app made to the student's Drive trash (recoverable there)."""
    if _FILE_ID.match(file_id or ""):
        _api(student_id, "PATCH", f"{FILES_URL}/{file_id}", json={"trashed": True})


# --- status and disconnecting ---------------------------------------------------------------------


def connected(student_id: str | None) -> bool:
    return bool(student_id) and enabled() and db.drive_account(student_id) is not None


def status(student_id: str | None) -> dict:
    """What the Settings card shows: never a token."""
    row = db.drive_account(student_id) if student_id and enabled() else None
    return {
        "enabled": enabled(),
        "connected": row is not None,
        "folder_link": f"https://drive.google.com/drive/folders/{row['root_id']}"
        if row is not None and row["root_id"]
        else "",
    }


def _revoke(token: str) -> None:
    if token:
        try:
            _client().post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            log.info("drive: revoking at Google failed; the token is deleted here anyway")


def disconnect(student_id: str) -> None:
    """Revoke the app's access at Google (best effort) and delete the token here."""
    row = db.drive_account(student_id)
    if row is not None:
        with contextlib.suppress(secretbox.SecretError):  # a token we cannot read: delete only
            _revoke(
                secretbox.open_(row["refresh_token_enc"], student_id=student_id, purpose="refresh")
            )
    db.delete_drive_account(student_id)
    _forget(student_id)
