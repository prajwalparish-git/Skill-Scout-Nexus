"""A student's own settings. Defaults save AI quota: nothing is generated ahead of time unless the
student turns it on (and the server allows it with PRELOAD=true)."""

import json

from piq import db
from piq.config import settings
from piq.services import ServiceError

DEFAULTS: dict[str, bool] = {
    "preload": False,  # write the roadmap, next quiz and voice questions in the background
    "login_alerts": True,  # email me when my account is signed in on a new device
}


def get(student_id: str) -> dict[str, bool]:
    raw = db.prefs(student_id)
    try:
        saved = json.loads(raw) if raw else {}
    except ValueError:
        saved = {}
    return {k: bool(saved.get(k, v)) for k, v in DEFAULTS.items()}


def update(student_id: str, changes: dict) -> dict[str, bool]:
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise ServiceError(f"Unknown setting: {', '.join(sorted(unknown))}.")
    if not all(isinstance(v, bool) for v in changes.values()):
        raise ServiceError("Settings are on or off.")
    merged = {**get(student_id), **changes}
    db.save_prefs(student_id, json.dumps(merged))
    return merged


def preload_on(student_id: str | None) -> bool:
    """Speculative generation for this student: the server allows it and they turned it on."""
    return bool(student_id) and settings().preload and get(student_id)["preload"]  # type: ignore[arg-type]
