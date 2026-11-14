"""The operations view: everything happening in the app on one page, for whoever runs it.

Opened by signing in with DEV_SECRET as the password (server_auth.py); while DEV_SECRET is
empty there is no way in. Read-only: accounts, sign-in events, live sessions with their devices,
AI usage per agent and model, the AI providers, the database and its cloud sync, and the mail
and preload settings. API keys and passwords are never included, only whether they are set.
"""

import platform
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends

from core import ai_router, mailer
from database import crud
from piq import db, devices, journey, question_bank
from piq.config import settings
from server_auth import require_ops

router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(require_ops)])


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
