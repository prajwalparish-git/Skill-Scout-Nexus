"""The Project space and project ideas over HTTP (piq/project_ideas.py): the student's
projects, ideas derived from GitHub repositories (metadata only, from GitHub's official Search
API), "Start this project" (status Idea) and "More like this". Students in computing domains."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from piq import db, project_ideas
from piq.services import ServiceError
from server_auth import require_student

router = APIRouter(tags=["projects"])


def _call[T](work: Callable[[], T]) -> T:
    """ServiceError -> 400 (the reason is safe to show)."""
    try:
        return work()
    except ServiceError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/projects")
def projects(sid: str = Depends(require_student)) -> dict:
    return {
        "projects": [
            {
                "id": p["id"],
                "name": p["name"],
                "status": p["status"],
                "tech": p["tech"],
                "repo_url": p["repo_url"],
                "on_resume": bool(p["on_resume"]),
                "updated_at": p["updated_at"],
            }
            for p in db.projects(sid)
        ]
    }


@router.get("/api/project-ideas")
def latest(sid: str = Depends(require_student)) -> dict:
    """The newest ideas (or null), and what the next suggestion would search for."""

    def work() -> dict:
        profile = project_ideas.student_profile(sid)
        return {
            "set": project_ideas.latest(sid),
            "topics": project_ideas.topics(profile),
            "gaps": project_ideas.gaps(profile),
        }

    return _call(work)


@router.post("/api/project-ideas")
def suggest(sid: str = Depends(require_student)) -> dict:
    """New ideas from the student's skill gaps, derived from the repositories found."""
    return {"set": _call(lambda: project_ideas.suggest(sid))}


@router.post("/api/project-ideas/{set_id}/{index}/start")
def start(set_id: int, index: int, sid: str = Depends(require_student)) -> dict:
    """Put an idea in the Project space with status Idea."""
    return {"project_id": _call(lambda: project_ideas.start(sid, set_id, index))}


@router.post("/api/project-ideas/{set_id}/{index}/more")
def more(set_id: int, index: int, sid: str = Depends(require_student)) -> dict:
    """New ideas around one idea: the topics of the repositories it was built from."""
    return {"set": _call(lambda: project_ideas.more_like(sid, set_id, index))}
