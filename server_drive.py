"""Google Drive over HTTP (core/drive.py): connect, the OAuth callback, disconnect, and copying
certificates. Only while the server has GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and
DRIVE_TOKEN_KEY; otherwise every route but the status answers 404 and the app hides Drive.

The callback redirects only to fixed paths of the app (never to an address from the request),
and completes a sign-in only for the signed-in student who started it.
"""

from collections.abc import Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from core import drive
from piq import services
from piq.config import settings
from piq.services import ServiceError
from server_auth import require_student, session_id

router = APIRouter(prefix="/api/drive", tags=["drive"])


def require_drive() -> None:
    if not drive.enabled():
        raise HTTPException(404, "Not found.")


def _call[T](work: Callable[[], T]) -> T:
    try:
        return work()
    except drive.DriveDisabled as e:
        raise HTTPException(404, "Not found.") from e
    except drive.NotConnected as e:
        raise HTTPException(409, str(e)) from e
    except (drive.DriveError, ServiceError) as e:
        raise HTTPException(400, str(e)) from e


@router.get("")
def status(request: Request) -> dict:
    """{enabled, connected, folder_link}: never a token."""
    return drive.status(session_id(request))


@router.post("/connect", dependencies=[Depends(require_drive)])
def connect(sid: str = Depends(require_student)) -> dict:
    """The Google sign-in address (the drive.file scope only)."""
    return {"url": _call(lambda: drive.start(sid, "web"))}


@router.get("/callback", dependencies=[Depends(require_drive)])
def callback(
    request: Request, state: str = "", code: str = "", error: str = ""
) -> RedirectResponse:
    """Where Google sends the student back. Always ends on the app's Settings page."""

    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{settings().app_url}/settings?{urlencode(params)}", 303)

    if error:  # the student declined on Google's page
        return back(drive="error", reason="Google Drive was not connected.")
    try:
        drive.finish(state, code, signed_in=session_id(request) or "", ui="web")
    except drive.DriveError as e:
        return back(drive="error", reason=str(e))
    return back(drive="connected")


@router.post("/disconnect", dependencies=[Depends(require_drive)])
def disconnect(sid: str = Depends(require_student)) -> dict:
    drive.disconnect(sid)
    return drive.status(sid)


@router.post("/backup-certificates", dependencies=[Depends(require_drive)])
def backup_certificates(sid: str = Depends(require_student)) -> dict:
    """Copy every certificate not yet in Drive there."""
    return {"copied": _call(lambda: services.backup_certificates(sid))}


@router.post("/certificates/{cert_id}/retry", dependencies=[Depends(require_drive)])
def retry_certificate(cert_id: int, sid: str = Depends(require_student)) -> dict:
    return {"in_drive": _call(lambda: services.retry_certificate_drive(sid, cert_id))}
