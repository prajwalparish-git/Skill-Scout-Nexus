"""Company interview experiences over HTTP (piq/experiences.py): browse, share, report,
practise; and the operations view's moderation of individual learners' posts.

Students' posts are their own words, never copied from another site, and appear only once a
person approves them. Browsing never returns a poster's name: only a label. Organization admins
moderate their own students' posts in the Streamlit admin portal (it has no web API).
"""

import threading
import time
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from piq import experiences
from piq.config import (
    EXPERIENCE_MAX_QUESTIONS,
    EXPERIENCE_QUESTION_MAX,
    EXPERIENCE_TEXT_MAX,
    EXPERIENCE_TIP_MAX,
)
from piq.services import ServiceError
from server_auth import require_ops, require_student, session_id

router = APIRouter(tags=["companies"])
ops_router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(require_ops)])

SUBMIT_MAX, SUBMIT_WINDOW_S = 10, 600  # posts per client address per window (its own bucket)
_posts: dict[str, list[float]] = {}
_posts_lock = threading.Lock()


def _address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def submit_throttle(request: Request) -> None:
    now, who = time.monotonic(), _address(request)
    with _posts_lock:
        recent = [t for t in _posts.get(who, []) if now - t < SUBMIT_WINDOW_S]
        if len(recent) >= SUBMIT_MAX:
            _posts[who] = recent
            raise HTTPException(429, "Too many posts from this network. Try again later.")
        _posts[who] = [*recent, now]


def _call[T](work: Callable[[], T]) -> T:
    """ServiceError -> 400 (the reason is safe to show), ExperienceLimit -> 429."""
    try:
        return work()
    except experiences.ExperienceLimit as e:
        raise HTTPException(429, str(e)) from e
    except ServiceError as e:
        raise HTTPException(400, str(e)) from e


# --- browse ----------------------------------------------------------------------------------


@router.get("/api/companies")
def companies(request: Request) -> dict:
    """Companies with approved posts per round (names and counts only: what guests see too)."""
    return {"companies": experiences.companies_overview(), "signed_in": bool(session_id(request))}


@router.get("/api/companies/{slug}")
def company(slug: str, round: str | None = None, sid: str = Depends(require_student)) -> dict:
    """A company's approved posts, labelled ('a student, 2026'), never named."""
    return _call(lambda: experiences.company_detail(slug, round or None))


# --- share, mine, report -----------------------------------------------------------------------


class QuestionIn(BaseModel):
    kind: Literal["open", "mcq"] = "open"
    text: str = Field(max_length=EXPERIENCE_QUESTION_MAX + 200)
    options: list[str] = Field(default_factory=list, max_length=4)
    correct_index: int | None = None
    explanation: str = Field("", max_length=EXPERIENCE_QUESTION_MAX)


class ExperienceIn(BaseModel):
    company: str = Field(max_length=EXPERIENCE_TEXT_MAX + 40)
    role: str = Field(max_length=EXPERIENCE_TEXT_MAX + 40)
    round: str = Field(max_length=30)
    interview_month: str = Field(max_length=10)
    tip: str = Field("", max_length=EXPERIENCE_TIP_MAX + 200)
    show_college: bool = True
    questions: list[QuestionIn] = Field(min_length=1, max_length=EXPERIENCE_MAX_QUESTIONS)


@router.post("/api/experiences", dependencies=[Depends(submit_throttle)])
def share(body: ExperienceIn, sid: str = Depends(require_student)) -> dict:
    """Share an interview: cleaned, then pending until a moderator approves it."""
    form = body.model_dump()
    s = _call(lambda: experiences.submit(sid, form))
    return {"id": s.id, "status": s.status, "removed": s.removed}


@router.get("/api/experiences/mine")
def mine(sid: str = Depends(require_student)) -> dict:
    return {"posts": experiences.my_posts(sid)}


@router.post("/api/experiences/{experience_id}/report")
def report(experience_id: int, sid: str = Depends(require_student)) -> dict:
    """Report a published post; enough reports hide it until its moderator looks again."""
    return {"reports": _call(lambda: experiences.report(sid, experience_id))}


# --- practice ----------------------------------------------------------------------------------


@router.get("/api/companies/{slug}/practice")
def practice(
    slug: str,
    round: str,
    source: Literal["reported", "ai"] = "reported",
    sid: str = Depends(require_student),
) -> dict:
    """A practice quiz without its answers. `reported`: students' MCQs for this company;
    `ai`: AI practice in its style, always labelled so and never stored as reported."""
    if source == "reported":
        q = _call(lambda: experiences.reported_quiz(slug, round))
    else:
        q = _call(lambda: experiences.ai_quiz(sid, slug, round))
    return {
        "company": q.company,
        "round": q.round,
        "source": q.source,
        "label": q.label,
        "notes": q.notes,
        "questions": [{"id": i, "text": x.text, "options": x.options} for i, x in q.questions],
    }


class PracticeAnswer(BaseModel):
    id: str = Field(max_length=64)
    choice: int | None = None


class PracticeSubmit(BaseModel):
    round: str = Field(max_length=30)
    source: Literal["reported", "ai"]
    answers: list[PracticeAnswer] = Field(min_length=1, max_length=30)


@router.post("/api/companies/{slug}/practice/submit")
def practice_submit(slug: str, body: PracticeSubmit, sid: str = Depends(require_student)) -> dict:
    """Graded into company practice only: syllabus topics, levels and the plan are unchanged."""
    answers = [(a.id, a.choice) for a in body.answers]
    return _call(lambda: experiences.grade_practice(sid, slug, body.round, body.source, answers))


# --- moderation by the operations view (individual learners' posts) ---------------------------


class ReviewIn(BaseModel):
    approve: bool
    reason: str = Field("", max_length=300)
    company: str = Field("", max_length=EXPERIENCE_TEXT_MAX)


@ops_router.get("/experiences")
def ops_queue() -> dict:
    return {"posts": experiences.review_queue(experiences.OPS)}


@ops_router.post("/experiences/{experience_id}/review")
def ops_review(experience_id: int, body: ReviewIn) -> dict:
    _call(
        lambda: experiences.review(
            experiences.OPS, experience_id, body.approve, body.reason, body.company or None
        )
    )
    return {"posts": experiences.review_queue(experiences.OPS)}
