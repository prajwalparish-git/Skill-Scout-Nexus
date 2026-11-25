"""The developer console (/ops): everything happening in the app, and the tools to run it.

Opened with DEV_SECRET: POST /api/auth/ops-login (or DEV_SECRET as the password on the normal
sign-in, routers/auth.py); while DEV_SECRET is empty there is no way in. Every route here needs
that sign-in (the HttpOnly `ssn_ops` cookie). The overview is read-only: accounts, sign-in
events, live sessions with their devices, AI usage, the providers, the database and its cloud
sync. The rest (piq/ops_admin.py) manages the curated data files through validated CSV uploads,
inspects and backs up the databases, reads the server log and the mail outbox, clears caches
and unlocks, signs out or suspends accounts. Every change is recorded as an `ops_action` sign-in
event. API keys, passwords and tokens are never returned, only whether they are set.
"""

import platform
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel

from core import ai_router, mailer, ops_logs
from database import crud
from piq import accounts, db, devices, journey, ops_admin, question_bank
from piq.config import settings
from routers.auth import OPS_COOKIE, device, ops_session_count, require_ops, revoke_all_ops

router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(require_ops)])

CSV = "text/csv; charset=utf-8"


def _audit(request: Request, response: Response, action: str, detail: str = "") -> None:
    """Record a change made from the console (shown with the sign-in events)."""
    accounts.event(
        "ops_action",
        identifier="developer-console",
        device=device(request, response),
        detail=f"{action}{f': {detail}' if detail else ''}"[:400],
    )


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read(ops_admin.CSV_MAX_BYTES + 1)
    if len(data) > ops_admin.CSV_MAX_BYTES:
        raise HTTPException(413, "The file is larger than 10 MB.")
    return data


def _file(content: bytes | str, name: str, media_type: str = CSV) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _device(ua: str) -> dict:
    return {"browser": devices.browser(ua), "os": devices.os_name(ua)}


def _sync() -> dict:
    try:
        s = crud.sync_status()
    except Exception as e:  # telemetry unavailable: say so instead of failing the page
        return {"error": type(e).__name__}
    return {
        "cloud_configured": s.cloud_configured,
        "state": s.state,
        "pending": s.pending,
        "set_aside": s.set_aside,
        "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
    }


@router.get("/overview")
def overview() -> dict:
    s = settings()
    now = time.time()
    students = db.ops_students()
    events = db.auth_events(300)
    since = now - 24 * 3600
    kinds: dict[str, int] = {}
    for e in events:
        if e["at"] >= since:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    sessions = db.all_sessions(now)
    return {
        "generated_at": now,
        "totals": {
            "students": len(students),
            "verified": sum(1 for r in students if r["email_verified"]),
            "live_sessions": len(sessions),
            "quiz_attempts": sum(r["quizzes"] or 0 for r in students),
            "events_24h": kinds,
        },
        "students": [
            {
                "name": r["name"],
                "username": r["username"],
                "email": r["email"],
                "role": r["target_role"],
                "readiness": r["readiness_score"],
                "created_at": r["created_at"],
                "status": r["account_status"],
                "verified": bool(r["email_verified"]),
                "organization": r["org_id"] is not None,
                "sessions": r["sessions"],
                "last_sign_in": r["last_sign_in"],
                "quizzes": r["quizzes"],
                "failures": r["failures"] or 0,
                "locked": bool(r["locked_until"] and r["locked_until"] > now),
            }
            for r in students
        ],
        "events": [
            {
                "at": e["at"],
                "kind": e["kind"],
                "who": e["username"] or e["identifier"],
                "ip": e["ip"],
                "location": e["location"],
                "detail": e["detail"],
                **_device(e["user_agent"]),
            }
            for e in events
        ],
        "sessions": [
            {
                "username": r["username"],
                "created_at": r["created_at"],
                "last_seen": r["last_seen"] or None,
                "ip": r["ip"],
                "location": r["location"],
                **_device(r["user_agent"]),
            }
            for r in sessions
        ],
        "ai_usage": [dict(r) for r in db.agent_usage()],
        "providers": [asdict(p) for p in ai_router.status()],
        "system": {
            "mode": "local (one student, no email)" if s.local_mode else "online",
            "mock_mode": s.mock_mode,
            "engine": journey.engine_status().line,
            "models": {"large": s.model_large, "small": s.model_small},
            "mail": "SMTP" if mailer.configured() else "local outbox file",
            "app_url": s.app_url,
            "preload_allowed": s.preload,
            "question_bank": question_bank.size(),
            "database": str(s.db_path),
            "sync": _sync(),
            "python": platform.python_version(),
            "platform": platform.platform(terse=True),
        },
    }


# --- console session ----------------------------------------------------------------------------


@router.post("/logout-all")
def logout_all(request: Request, response: Response) -> dict:
    """Sign every developer-console session out, this one included."""
    _audit(request, response, "logout_all")
    count = revoke_all_ops()
    response.delete_cookie(OPS_COOKIE, path="/")
    return {"revoked": count}


# --- question banks -----------------------------------------------------------------------------

AppendMode = Literal["append", "replace"]
MergeMode = Literal["merge", "replace"]


@router.get("/questions/stats")
def questions_stats() -> dict:
    return ops_admin.question_stats()


@router.get("/questions/mcq/template")
def mcq_template() -> Response:
    return _file(ops_admin.mcq_template_csv(), "mcq_template.csv")


@router.get("/questions/mcq/export")
def mcq_export() -> Response:
    return _file(ops_admin.export_mcq_csv(), f"mcq_bank-{_stamp()}.csv")


@router.post("/questions/mcq/preview")
def mcq_preview(
    file: Annotated[UploadFile, File()], mode: Annotated[AppendMode, Form()] = "append"
) -> dict:
    return ops_admin.preview_mcq_csv(_read_upload(file), mode)


@router.post("/questions/mcq/import")
def mcq_import(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    mode: Annotated[AppendMode, Form()] = "append",
) -> dict:
    out = ops_admin.import_mcq_csv(_read_upload(file), mode)
    _audit(request, response, "mcq_import", f"{mode}, {out['imported']} rows")
    return out


@router.get("/questions/interview/template")
def interview_template() -> Response:
    return _file(ops_admin.interview_template_csv(), "interview_template.csv")


@router.post("/questions/interview/preview")
def interview_preview(
    file: Annotated[UploadFile, File()], mode: Annotated[AppendMode, Form()] = "append"
) -> dict:
    return ops_admin.preview_interview_csv(_read_upload(file), mode)


@router.post("/questions/interview/import")
def interview_import(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    mode: Annotated[AppendMode, Form()] = "append",
) -> dict:
    out = ops_admin.import_interview_csv(_read_upload(file), mode)
    _audit(request, response, "interview_import", f"{mode}, {out['imported']} questions")
    return out


# --- GitHub inspiration data --------------------------------------------------------------------


@router.get("/github/stats")
def github_stats() -> dict:
    return ops_admin.github_stats()


@router.get("/github/repos/template")
def repos_template() -> Response:
    return _file(ops_admin.github_repos_template_csv(), "github_repos_template.csv")


@router.get("/github/repos/export")
def repos_export() -> Response:
    return _file(ops_admin.export_github_repos_csv(), f"github_repos-{_stamp()}.csv")


@router.post("/github/repos/preview")
def repos_preview(
    file: Annotated[UploadFile, File()], mode: Annotated[MergeMode, Form()] = "merge"
) -> dict:
    return ops_admin.preview_github_repos_csv(_read_upload(file), mode)


@router.post("/github/repos/import")
def repos_import(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    mode: Annotated[MergeMode, Form()] = "merge",
) -> dict:
    out = ops_admin.import_github_repos_csv(_read_upload(file), mode)
    _audit(request, response, "github_repos_import", f"{mode}, {out['imported']} repos")
    return out


@router.get("/github/topics/template")
def topics_template() -> Response:
    return _file(ops_admin.github_topics_template_csv(), "github_topics_template.csv")


@router.get("/github/topics/export")
def topics_export() -> Response:
    return _file(ops_admin.export_github_topics_csv(), f"github_topics-{_stamp()}.csv")


@router.post("/github/topics/preview")
def topics_preview(
    file: Annotated[UploadFile, File()], mode: Annotated[MergeMode, Form()] = "merge"
) -> dict:
    return ops_admin.preview_github_topics_csv(_read_upload(file), mode)


@router.post("/github/topics/import")
def topics_import(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    mode: Annotated[MergeMode, Form()] = "merge",
) -> dict:
    out = ops_admin.import_github_topics_csv(_read_upload(file), mode)
    _audit(request, response, "github_topics_import", f"{mode}, {out['imported']} skills")
    return out


@router.get("/github/orgs/template")
def orgs_template() -> Response:
    return _file(ops_admin.company_orgs_template_csv(), "company_orgs_template.csv")


@router.get("/github/orgs/export")
def orgs_export() -> Response:
    return _file(ops_admin.export_company_orgs_csv(), f"company_orgs-{_stamp()}.csv")


@router.post("/github/orgs/preview")
def orgs_preview(
    file: Annotated[UploadFile, File()], mode: Annotated[MergeMode, Form()] = "merge"
) -> dict:
    return ops_admin.preview_company_orgs_csv(_read_upload(file), mode)


@router.post("/github/orgs/import")
def orgs_import(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    mode: Annotated[MergeMode, Form()] = "merge",
) -> dict:
    out = ops_admin.import_company_orgs_csv(_read_upload(file), mode)
    _audit(request, response, "company_orgs_import", f"{mode}, {out['imported']} orgs")
    return out


# --- databases ----------------------------------------------------------------------------------

Which = Literal["app", "telemetry"]


@router.get("/db/overview")
def db_overview() -> dict:
    return ops_admin.db_overview()


@router.get("/db/table")
def db_table(
    which: Which,
    table: Annotated[str, Query(max_length=128)],
    limit: Annotated[int, Query(ge=1, le=ops_admin.BROWSE_MAX)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str, Query(max_length=200)] = "",
) -> dict:
    return ops_admin.browse_table(which, table, limit, offset, search)


class MaintenanceIn(BaseModel):
    action: ops_admin.Maintenance


@router.post("/db/maintenance")
def db_maintenance(body: MaintenanceIn, request: Request, response: Response) -> dict:
    _audit(request, response, "db_maintenance", body.action)
    return ops_admin.db_maintenance(body.action)


@router.get("/db/backup/{which}")
def db_backup(which: Which, request: Request, response: Response) -> Response:
    data = ops_admin.db_backup_bytes(which)
    _audit(request, response, "db_backup", which)
    return _file(data, f"{which}-backup-{_stamp()}.db", "application/vnd.sqlite3")


# --- logs and the mail outbox -------------------------------------------------------------------


@router.get("/logs")
def logs(
    level: Annotated[str, Query(max_length=10)] = "",
    logger: Annotated[str, Query(max_length=100)] = "",
    search: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=ops_logs.MAX_RECORDS)] = 200,
) -> dict:
    records = ops_logs.query_logs(level or None, logger or None, search or None, limit)
    return {"records": records, "capacity": ops_logs.MAX_RECORDS, "levels": ops_logs.LEVELS}


@router.get("/logs/download")
def logs_download() -> Response:
    return _file(ops_logs.export_text(), f"server-{_stamp()}.log", "text/plain; charset=utf-8")


@router.post("/logs/clear")
def logs_clear(request: Request, response: Response) -> dict:
    cleared = ops_logs.clear_logs()
    _audit(request, response, "logs_clear", f"{cleared} records")
    return {"cleared": cleared}


@router.get("/mail-outbox")
def mail_outbox(tail: Annotated[int, Query(ge=1, le=5000)] = 200) -> dict:
    return ops_admin.read_mail_outbox(tail)


@router.post("/mail-outbox/clear")
def mail_outbox_clear(request: Request, response: Response) -> dict:
    out = ops_admin.clear_mail_outbox()
    _audit(request, response, "mail_outbox_clear", f"{out['cleared_bytes']} bytes")
    return out


# --- settings, caches, organizations and accounts -----------------------------------------------


@router.get("/settings")
def developer_settings() -> dict:
    return ops_admin.developer_settings_summary(ops_session_count())


class CacheIn(BaseModel):
    target: ops_admin.CacheTarget


@router.post("/cache/clear")
def cache_clear(body: CacheIn, request: Request, response: Response) -> dict:
    out = ops_admin.clear_cache(body.target)
    _audit(request, response, "cache_clear", body.target)
    return out


@router.post("/smtp/test")
def smtp_test(request: Request, response: Response) -> dict:
    out = ops_admin.test_smtp_connection()
    _audit(request, response, "smtp_test", "ok" if out["ok"] else "failed")
    return out


@router.get("/orgs")
def organizations() -> dict:
    return {"organizations": ops_admin.list_organizations_ops()}


@router.post("/students/{username}/unlock")
def student_unlock(username: str, request: Request, response: Response) -> dict:
    out = ops_admin.unlock_student(username)
    _audit(request, response, "student_unlock", username)
    return out


@router.post("/students/{username}/revoke-sessions")
def student_revoke(username: str, request: Request, response: Response) -> dict:
    out = ops_admin.revoke_student_sessions(username)
    _audit(request, response, "student_revoke_sessions", f"{username}, {out['revoked']}")
    return out


class StatusIn(BaseModel):
    status: Literal["active", "suspended"]


@router.post("/students/{username}/status")
def student_status(username: str, body: StatusIn, request: Request, response: Response) -> dict:
    out = ops_admin.set_student_status_ops(username, body.status)
    _audit(request, response, "student_status", f"{username} -> {body.status}")
    return out
