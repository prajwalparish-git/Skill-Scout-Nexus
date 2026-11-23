"""Contributed questions: placed students, alumni and professionals add to the open question bank.

Anyone signed in may contribute: a contributor account (piq/accounts.sign_up_contributor: name,
email, company joined, batch year, nothing else) or a student. A contribution is a multiple-
choice question with its answer and an explanation, or an open question with a model answer,
for the aptitude, technical or HR round. It is published under CC BY 4.0, which the author
accepts on the form (recorded per question).

The same rules as interview posts (piq/experiences.py): the same daily and pending limits,
personal data removed and abuse refused (piq/experience_checks.py), copied text flagged, the
live name screen, and nothing appears until a person approves it (the author's organization
admin, else the operations view). Multiple-choice questions also pass the bank's own checks
(piq/question_bank.problems) and, in live mode, the critic agent; its verdict is a flag for the
moderator. Approved multiple-choice questions join the quiz bank; open ones the general-practice
interviews. Credit is opt-in: an author is "an anonymous contributor" unless they choose a
display name, which then shows on their questions and in "Top contributors this season".
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from piq import agents, db, experience_checks, open_questions, question_bank, syllabus
from piq.checks import text_hash
from piq.config import (
    DIFFICULTIES,
    EXPERIENCE_DAILY_MAX,
    EXPERIENCE_PENDING_MAX,
    EXPERIENCE_QUESTION_MAX,
    EXPERIENCE_QUESTION_MIN,
    settings,
)
from piq.experience_checks import ExperienceRejected
from piq.graph import CriticRejected
from piq.llm import LLMError
from piq.schemas import QuizSet
from piq.services import ServiceError

log = logging.getLogger("piq.contributions")
OPS = "ops"
LICENCE = "CC-BY-4.0"
LICENCE_NOTE = (
    "You publish your question under the Creative Commons Attribution 4.0 licence (CC BY 4.0): "
    "anyone may use and adapt it with credit. Write it yourself; do not copy it from a book, "
    "a website or a test paper."
)
ROUNDS = {"aptitude": "Aptitude", "technical": "Technical", "hr": "HR"}
APTITUDE_TOPICS = ("Aptitude", "Reasoning")
HR_TOPIC = "HR"
EXPLANATION_MIN, MODEL_ANSWER_MIN, MODEL_ANSWER_MAX = 10, 80, 2000
DISPLAY_NAME_MIN, DISPLAY_NAME_MAX = 3, 40
ANONYMOUS = "an anonymous contributor"
LEADERBOARD_SIZE = 10


class ContributionLimit(ServiceError):
    """Too many contributions for now (the API answers 429)."""


@dataclass(frozen=True)
class Contributed:
    id: int
    status: str
    removed: list[str]
    flags: list[str]


def topics(round_: str) -> list[str]:
    """The topics a round's questions can be filed under."""
    if round_ == "aptitude":
        return list(APTITUDE_TOPICS)
    if round_ == "hr":
        return [HR_TOPIC]
    return sorted(t for t in syllabus.all_topics() if t not in APTITUDE_TOPICS)


def _text(value: object, what: str, own: list[str], found: set[str], low: int, high: int) -> str:
    text = experience_checks.clean_text(str(value or ""), what, own, found)
    if len(experience_checks.meaningful(text)) < low:
        raise ExperienceRejected(f"{what}: write at least {low} characters in your own words.")
    if len(text) > high:
        raise ExperienceRejected(f"{what}: keep it under {high} characters.")
    return text


def clean(form: Mapping, own: list[str]) -> tuple[dict, list[str], list[str]]:
    """(the cleaned question, flags for the moderator, kinds of personal data removed). Raises
    ExperienceRejected with the reason (safe to show)."""
    if form.get("licence_accepted") is not True:
        raise ExperienceRejected("Tick the box to publish your question under CC BY 4.0.")
    round_ = str(form.get("round", ""))
    if round_ not in ROUNDS:
        raise ExperienceRejected("Choose the round: aptitude, technical or HR.")
    kind = str(form.get("kind", ""))
    if kind not in ("mcq", "open"):
        raise ExperienceRejected("Choose multiple choice or an open question.")
    if round_ == "hr" and kind == "mcq":
        raise ExperienceRejected("HR questions are open questions, with a model answer.")
    topic = str(form.get("topic", "") or (HR_TOPIC if round_ == "hr" else ""))
    if topic not in topics(round_):
        raise ExperienceRejected(f"Choose a topic for the {ROUNDS[round_]} round.")
    difficulty = str(form.get("difficulty", ""))
    if difficulty not in DIFFICULTIES:
        raise ExperienceRejected("Choose easy, medium or hard.")
    found: set[str] = set()
    text = _text(
        form.get("text"), "The question", own, found, EXPERIENCE_QUESTION_MIN,
        EXPERIENCE_QUESTION_MAX,
    )  # fmt: skip
    q: dict = {
        "kind": kind,
        "round": round_,
        "topic": topic,
        "difficulty": difficulty,
        "text": text,
        "options": [],
        "correct_index": None,
        "explanation": "",
        "model_answer": "",
    }
    if kind == "mcq":
        options = [
            experience_checks.clean_text(str(o or ""), "An option", own, found)
            for o in form.get("options") or []
        ]
        correct = form.get("correct_index")
        if len(options) != 4 or correct not in (0, 1, 2, 3):
            raise ExperienceRejected("Give four options and mark the correct one.")
        q["options"], q["correct_index"] = options, correct
        q["explanation"] = _text(
            form.get("explanation"), "The explanation", own, found, EXPLANATION_MIN,
            EXPERIENCE_QUESTION_MAX,
        )  # fmt: skip
        if why := question_bank.problems(_bank_row(q)):
            raise ExperienceRejected(f"The question cannot be used: {why}.")
    else:
        q["model_answer"] = _text(
            form.get("model_answer"), "The model answer", own, found, MODEL_ANSWER_MIN,
            MODEL_ANSWER_MAX,
        )  # fmt: skip
    flags = experience_checks.copy_signals(text)
    for part in (q["explanation"], q["model_answer"], *q["options"]):
        flags += [f"answer: {s}" for s in experience_checks.copy_signals(part)]
    if bad := open_questions.forbidden_in(" ".join([text, q["explanation"], q["model_answer"]])):
        flags.append(f"mentions {', '.join(bad)}: check it is the author's own words")
    if found:
        flags.append(f"personal data removed automatically: {', '.join(sorted(found))}")
    return q, flags, sorted(found)


def _bank_row(q: Mapping) -> dict:
    """A multiple-choice contribution as a bank row (piq/question_bank.py)."""
    return {
        "question": q["text"],
        **{f"option_{c}": o for c, o in zip("abcd", q["options"], strict=False)},
        "correct_option": "ABCD"[q["correct_index"]] if q["correct_index"] in (0, 1, 2, 3) else "",
        "explanation": q["explanation"],
        "bloom_level": "apply",
    }


def _critic(q: dict, student_id: str) -> list[str]:
    """Live mode: the critic agent checks a multiple-choice question has one right answer that
    its explanation supports. Its verdict is a flag; a person decides."""
    if q["kind"] != "mcq":
        return []
    if settings().mock_mode:
        return ["critic check not run (mock mode): check the answer yourself"]
    quiz = QuizSet(
        topic=q["topic"],
        difficulty=q["difficulty"],
        questions=[question_bank.as_question(_bank_row(q))],
    )
    try:
        reasons = agents.verify_quiz(
            {"topic": q["topic"], "difficulty": q["difficulty"], "student_id": student_id}, quiz
        )
    except (LLMError, CriticRejected) as e:
        log.info("critic unavailable for a contribution (%s)", e)
        return ["critic unavailable: check the answer yourself"]
    return [f"critic: {r}" for r in reasons] or ["critic: the answer checks out"]


def _screen(q: dict, student_id: str) -> tuple[dict, list[str]]:
    """Live mode: the name screen may replace names the regexes missed (never add words)."""
    if settings().mock_mode:
        return q, []
    texts = [q["text"], q["explanation"] or q["model_answer"] or q["text"]]
    try:
        out = agents.screen_experience(
            {"company": "", "round": ROUNDS[q["round"]], "questions": texts, "tip": "",
             "student_id": student_id}
        )  # fmt: skip
    except (LLMError, CriticRejected) as e:
        log.info("contribution screening unavailable (%s)", e)
        return q, ["automatic name screening unavailable"]
    q = {**q, "text": out.questions[0]}
    if q["explanation"]:
        q["explanation"] = out.questions[1]
    elif q["model_answer"]:
        q["model_answer"] = out.questions[1]
    return q, [f"AI screen: {f}" for f in out.flags]


def submit(student_id: str, form: Mapping) -> Contributed:
    """Clean, check and keep a contribution pending for its moderator."""
    student = db.student(student_id)
    if student is None:
        raise ServiceError("Sign in first.")
    since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    if db.contributions_since(student_id, since) >= EXPERIENCE_DAILY_MAX:
        raise ContributionLimit(
            f"You can contribute up to {EXPERIENCE_DAILY_MAX} questions a day. Try again tomorrow."
        )
    if db.contributions_pending(student_id) >= EXPERIENCE_PENDING_MAX:
        raise ContributionLimit(
            f"You have {EXPERIENCE_PENDING_MAX} questions waiting for review; wait for those first."
        )
    own = experience_checks.own_identity(student["name"], student["username"], student["email"])
    try:
        q, flags, removed = clean(form, own)
    except ExperienceRejected as e:
        raise ServiceError(str(e)) from e
    q, screened = _screen(q, student_id)
    h = text_hash(q["text"])
    if question_bank.get(h) is not None or any(
        text_hash(x["text"]) == h for x in open_questions.interview_questions()
    ):
        raise ServiceError("This question is already in the question bank.")
    if db.contribution_hash_taken(h):
        raise ServiceError("This question has already been contributed.")
    flags = [*flags, *screened, *_critic(q, student_id)]
    db.ensure_contributor(student_id)
    cid = db.add_contribution(
        {
            "author_id": student_id,
            "org_id": student["org_id"],
            "kind": q["kind"],
            "round": q["round"],
            "topic": q["topic"],
            "difficulty": q["difficulty"],
            "text": q["text"],
            "options_json": json.dumps(q["options"]),
            "correct_index": q["correct_index"],
            "explanation": q["explanation"],
            "model_answer": q["model_answer"],
            "licence_accepted_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "flags": json.dumps(flags),
            "content_hash": h,
        }
    )
    return Contributed(cid, "pending", removed, flags)


# --- moderation ---------------------------------------------------------------------------------


def _moderates(moderator: int | str, row: Mapping) -> bool:
    if moderator == OPS:
        return row["org_id"] is None
    return row["org_id"] is not None and row["org_id"] == moderator


def _out(row: Mapping, reveal: bool = True) -> dict:
    out = {
        "id": row["id"],
        "kind": row["kind"],
        "round": row["round"],
        "topic": row["topic"],
        "difficulty": row["difficulty"],
        "text": row["text"],
        "options": json.loads(row["options_json"] or "[]"),
        "licence": row["licence"],
        "status": row["status"],
        "created_at": row["created_at"],
    }
    if reveal:
        out |= {
            "correct_index": row["correct_index"],
            "explanation": row["explanation"],
            "model_answer": row["model_answer"],
        }
    return out


def review_queue(moderator: int | str) -> list[dict]:
    rows = db.contributions_to_review(None if moderator == OPS else int(moderator))
    return [{**_out(r), "flags": json.loads(r["flags"] or "[]")} for r in rows]


def review(moderator: int | str, contribution_id: int, approve: bool, reason: str = "") -> None:
    row = db.contribution(contribution_id)
    if row is None or not _moderates(moderator, row):
        raise ServiceError("That question is not one you moderate.")
    if row["status"] not in ("pending", "hidden"):
        raise ServiceError("That question has already been reviewed.")
    reason = " ".join((reason or "").split())[:300]
    if not approve and not reason:
        raise ServiceError("Say why the question is rejected; the author sees the reason.")
    by = OPS if moderator == OPS else f"org:{moderator}"
    db.review_contribution(
        contribution_id, "approved" if approve else "rejected", by, "" if approve else reason
    )
    question_bank.clear_cache()  # other processes notice by the bank's version check


# --- the author's view, credit and the leaderboard ----------------------------------------------


def mine(student_id: str) -> list[dict]:
    return [
        {**_out(r), "reject_reason": r["reject_reason"]} for r in db.contributions_of(student_id)
    ]


def credit_name(opt_in: bool | int, display_name: str) -> str:
    return display_name if opt_in and display_name else ANONYMOUS


def set_credit(student_id: str, opt_in: bool, display_name: str) -> dict:
    """Opt in to credit with a display name (no email, phone, link or handle; no abuse), or out:
    then every question shows as an anonymous contributor's."""
    name = " ".join((display_name or "").split())
    if opt_in:
        cleaned, kinds = experience_checks.scrub(name)
        if kinds or cleaned != name:
            raise ServiceError("Use a display name without contact details, links or handles.")
        if experience_checks.abusive(name):
            raise ServiceError("Choose a different display name.")
        if not DISPLAY_NAME_MIN <= len(name) <= DISPLAY_NAME_MAX:
            raise ServiceError(
                f"A display name has {DISPLAY_NAME_MIN}-{DISPLAY_NAME_MAX} characters."
            )
    db.set_contributor_credit(student_id, opt_in, name if opt_in else "")
    question_bank.clear_cache()
    return profile(student_id)


def season_start(today: date | None = None) -> date:
    """The placement season runs from 1 July to 30 June."""
    today = today or date.today()
    return date(today.year if today.month >= 7 else today.year - 1, 7, 1)


def leaderboard(today: date | None = None) -> dict:
    start = season_start(today)
    rows = db.top_contributors(start.isoformat(), LEADERBOARD_SIZE)
    return {
        "season": f"{start.year}-{str(start.year + 1)[2:]}",
        "since": start.isoformat(),
        "top": [{"name": r["display_name"], "approved": r["approved"]} for r in rows],
    }


def profile(student_id: str) -> dict:
    row = db.contributor(student_id)
    student = db.student(student_id)
    approved = db.approved_contribution_count(student_id)
    return {
        "kind": student["account_kind"] if student else "student",
        "company_joined": row["company_joined"] if row else "",
        "credit_opt_in": bool(row and row["credit_opt_in"]),
        "display_name": row["display_name"] if row else "",
        "shown_as": credit_name(
            bool(row and row["credit_opt_in"]), row["display_name"] if row else ""
        ),
        "approved": approved,
        "badge": "Thank you for contributing" if approved else "",
    }


# --- what approved contributions feed -------------------------------------------------------------


def bank_rows() -> list[dict]:
    """Approved multiple-choice contributions as bank rows, filed under their syllabus topic
    (piq/question_bank.py reads these with the open bank)."""
    out = []
    for r in db.approved_contributions("mcq"):
        q = {
            "text": r["text"],
            "options": json.loads(r["options_json"]),
            "correct_index": r["correct_index"],
            "explanation": r["explanation"],
        }
        out.append(
            {
                **_bank_row(q),
                "syllabus_topic": r["topic"],
                "topic": f"Contributed_{r['topic']}",
                "difficulty": r["difficulty"],
                "source": "contrib",
                "licence": LICENCE,
                "modified": "0",
                "by": credit_name(r["credit_opt_in"], r["display_name"]),
            }
        )
    return out


def interview_questions(round_: str) -> list[dict]:
    """Approved open contributions for a round, shaped like piq/open_questions.py's."""
    return [
        {
            "id": f"contrib-{r['id']}",
            "round": r["round"],
            "subtopic": r["topic"],
            "text": r["text"],
            "model_answer": r["model_answer"],
            "source": "contrib",
            "licence": LICENCE,
            "by": credit_name(r["credit_opt_in"], r["display_name"]),
        }
        for r in db.approved_contributions("open")
        if r["round"] == round_
    ]
