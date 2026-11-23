"""Contributed questions over HTTP (piq/contributions.py): contribute, see your own, choose how
you are credited, the season's top contributors; and the operations view's moderation of
contributions from contributors and individual learners.

Anyone signed in may contribute (a contributor account or a student). Every question is published
under CC BY 4.0, accepted on the form; nothing appears until a person approves it.
"""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from piq import contributions
from piq.config import EXPERIENCE_QUESTION_MAX
from piq.services import ServiceError
from server_auth import require_member, require_ops
from server_companies import submit_throttle

router = APIRouter(prefix="/api/contribute", tags=["contribute"])
ops_router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(require_ops)])


def _call[T](work: Callable[[], T]) -> T:
    """ServiceError -> 400 (the reason is safe to show), ContributionLimit -> 429."""
    try:
        return work()
    except contributions.ContributionLimit as e:
        raise HTTPException(429, str(e)) from e
    except ServiceError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/options")
def options() -> dict:
    """What the form offers: rounds, their topics, the licence note (public)."""
    return {
        "rounds": contributions.ROUNDS,
        "topics": {r: contributions.topics(r) for r in contributions.ROUNDS},
        "licence": contributions.LICENCE,
        "licence_note": contributions.LICENCE_NOTE,
    }


@router.get("/leaderboard")
def leaderboard() -> dict:
    """Top contributors this season: opted-in display names only (public)."""
    return contributions.leaderboard()


@router.get("/me")
def me(sid: str = Depends(require_member)) -> dict:
    return {
        "profile": contributions.profile(sid),
        "contributions": contributions.mine(sid),
        "leaderboard": contributions.leaderboard(),
    }


class ContributionIn(BaseModel):
    kind: Literal["mcq", "open"]
    round: str = Field(max_length=20)
    topic: str = Field("", max_length=80)
    difficulty: str = Field(max_length=10)
    text: str = Field(max_length=EXPERIENCE_QUESTION_MAX + 200)
    options: list[str] = Field(default_factory=list, max_length=4)
    correct_index: int | None = None
    explanation: str = Field("", max_length=EXPERIENCE_QUESTION_MAX + 200)
    model_answer: str = Field("", max_length=contributions.MODEL_ANSWER_MAX + 200)
    licence_accepted: bool = False


@router.post("", dependencies=[Depends(submit_throttle)])
def contribute(body: ContributionIn, sid: str = Depends(require_member)) -> dict:
    """Cleaned, checked, then pending until a moderator approves it."""
    c = _call(lambda: contributions.submit(sid, body.model_dump()))
    return {"id": c.id, "status": c.status, "removed": c.removed}


class CreditIn(BaseModel):
    credit_opt_in: bool
    display_name: str = Field("", max_length=80)


@router.post("/credit")
def credit(body: CreditIn, sid: str = Depends(require_member)) -> dict:
    """Be credited by a display name, or stay an anonymous contributor (the default)."""
    return _call(lambda: contributions.set_credit(sid, body.credit_opt_in, body.display_name))


class ReviewIn(BaseModel):
    approve: bool
    reason: str = Field("", max_length=300)


@ops_router.get("/contributions")
def ops_queue() -> dict:
    return {"contributions": contributions.review_queue(contributions.OPS)}


@ops_router.post("/contributions/{contribution_id}/review")
def ops_review(contribution_id: int, body: ReviewIn) -> dict:
    _call(
        lambda: contributions.review(contributions.OPS, contribution_id, body.approve, body.reason)
    )
    return {"contributions": contributions.review_queue(contributions.OPS)}
