"""Company interview experiences: our own bank, reported by students in their own words.

Nothing is copied from any website. A post is cleaned (piq/experience_checks.py), screened in
live mode (names only, never new text), and stays pending until a person approves it: the
poster's organization admin, or the operations view for an individual learner. Approved posts
are visible to every signed-in student under a label worked out when shown (never the poster's
name): "a <college> student, <year>" once at least LABEL_MIN_POSTERS of that batch have approved
posts, otherwise "a student, <year>".

Practice keeps reported and AI material apart: reported MCQs become a quiz and reported open
questions a mock interview (asked word for word); "AI practice in the style of a company" is
always marked source "ai" and never stored as reported. Company practice scores never touch the
syllabus topics' quiz history, levels or weekly plan.
"""

import json
import logging
import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from piq import agents, db, experience_checks, question_bank, services, syllabus
from piq.config import (
    EXPERIENCE_DAILY_MAX,
    EXPERIENCE_PENDING_MAX,
    EXPERIENCE_ROUNDS,
    LABEL_MIN_POSTERS,
    REPORTS_TO_HIDE,
    settings,
)
from piq.experience_checks import ExperienceRejected
from piq.graph import CriticRejected, OnEvent
from piq.llm import LLMError
from piq.schemas import Question
from piq.services import ServiceError

log = logging.getLogger("piq.experiences")
OPS = "ops"  # the operations view: moderates individual learners' posts (org_id NULL)
QUIZ_ROUNDS = {"aptitude": "Aptitude", "coding": "DSA"}  # AI practice topic per quiz round
INTERVIEW_ROUNDS = ("hr", "group_discussion", "technical")
AI_LABEL = "AI practice, not reported by a student"


class ExperienceLimit(ServiceError):
    """Too many posts for now (the API answers 429)."""


# --- submitting --------------------------------------------------------------------------


@dataclass(frozen=True)
class Submitted:
    id: int
    status: str
    removed: list[str]  # kinds of personal data taken out, shown to the poster


def _org_short(org_id: int | None) -> str:
    row = db.organization(org_id) if org_id else None
    if row is None:
        return ""
    name = row["name"]
    return name.split(" - ")[0].split(",")[0].strip() or name


def submit(student_id: str, form: Mapping) -> Submitted:
    """Clean a post and keep it pending for its moderator. Raises ServiceError (with the reason
    a post was refused) or ExperienceLimit."""
    student = db.student(student_id)
    if student is None:
        raise ServiceError("Sign in first.")
    since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    if db.experience_posts_since(student_id, since) >= EXPERIENCE_DAILY_MAX:
        raise ExperienceLimit(
            f"You can share up to {EXPERIENCE_DAILY_MAX} interviews a day. Try again tomorrow."
        )
    if db.experience_pending_count(student_id) >= EXPERIENCE_PENDING_MAX:
        raise ExperienceLimit(
            f"You have {EXPERIENCE_PENDING_MAX} posts waiting for review; wait for those first."
        )
    own = experience_checks.own_identity(student["name"], student["username"], student["email"])
    try:
        cleaned = experience_checks.clean_submission(form, own)
    except ExperienceRejected as e:
        raise ServiceError(str(e)) from e
    questions, tip, flags = _screen(student_id, cleaned)
    content_hash = experience_checks.content_hash(
        cleaned.company_slug, [q["text"] for q in questions]
    )
    if db.experience_hash_taken(content_hash):
        raise ServiceError("These questions have already been shared for this company.")
    org_id = student["org_id"]
    batch = str(student["batch_year"] or "").strip()[:4] or cleaned.interview_month[:4]
    exp_id = db.add_experience(
        {
            "student_id": student_id,
            "org_id": org_id,
            "org_short": _org_short(org_id),
            "batch_year": batch,
            "show_college": int(cleaned.show_college),
            "company_slug": cleaned.company_slug,
            "company_name": cleaned.company_name,
            "role": cleaned.role,
            "round": cleaned.round,
            "interview_month": cleaned.interview_month,
            "tip": tip,
            "flags": json.dumps(flags),
            "content_hash": content_hash,
        },
        questions,
    )
    return Submitted(exp_id, "pending", cleaned.removed)


def _screen(
    student_id: str, cleaned: experience_checks.Cleaned
) -> tuple[list[dict], str, list[str]]:
    """Live mode: the screener may replace names the regexes missed and add flags (it can never
    add text: checks.check_screen). MOCK_MODE: the deterministic cleaning alone."""
    flags = list(cleaned.flags)
    if settings().mock_mode:
        return cleaned.questions, cleaned.tip, flags
    try:
        out = agents.screen_experience(
            {
                "company": cleaned.company_name,
                "round": EXPERIENCE_ROUNDS[cleaned.round],
                "questions": [q["text"] for q in cleaned.questions],
                "tip": cleaned.tip,
                "student_id": student_id,
            }
        )
    except (LLMError, CriticRejected) as e:
        log.info("experience screening unavailable (%s); deterministic cleaning only", e)
        return cleaned.questions, cleaned.tip, [*flags, "automatic name screening unavailable"]
    questions = [{**q, "text": t} for q, t in zip(cleaned.questions, out.questions, strict=True)]
    return questions, out.tip, [*flags, *(f"AI screen: {f}" for f in out.flags)]


def my_posts(student_id: str) -> list[dict]:
    rows = db.experiences_of(student_id)
    qs = db.experience_questions([r["id"] for r in rows])
    return [
        {
            "id": r["id"],
            "company": r["company_name"],
            "role": r["role"],
            "round": r["round"],
            "interview_month": r["interview_month"],
            "status": r["status"],
            "reject_reason": r["reject_reason"],
            "questions": len(qs[r["id"]]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# --- labels -----------------------------------------------------------------------------------


def label(row: Mapping, batch_sizes: Mapping[tuple[int, str], int]) -> str:
    """Who shared a post, without naming them: the college only when they allowed it and
    at least LABEL_MIN_POSTERS of their batch have approved posts (a small batch could
    otherwise point at one person)."""
    year = row["batch_year"] or row["interview_month"][:4]
    big_enough = batch_sizes.get((row["org_id"], row["batch_year"]), 0) >= LABEL_MIN_POSTERS
    if row["org_id"] and row["show_college"] and row["org_short"] and big_enough:
        return f"a {row['org_short']} student, {year}"
    return f"a student, {year}"


# --- moderation -------------------------------------------------------------------------------


def _moderates(moderator: int | str, row: Mapping) -> bool:
    if moderator == OPS:
        return row["org_id"] is None
    return row["org_id"] is not None and row["org_id"] == moderator


def review_queue(moderator: int | str) -> list[dict]:
    """Posts waiting for this moderator (an organization id, or OPS), oldest first, with the
    automated flags and the label they would show."""
    rows = db.experiences_to_review(None if moderator == OPS else int(moderator))
    qs = db.experience_questions([r["id"] for r in rows])
    sizes = db.approved_posters_by_batch()
    return [
        {
            "id": r["id"],
            "company": r["company_name"],
            "company_slug": r["company_slug"],
            "known_company": not r["company_slug"].startswith("x-"),
            "role": r["role"],
            "round": r["round"],
            "interview_month": r["interview_month"],
            "tip": r["tip"],
            "status": r["status"],
            "flags": json.loads(r["flags"] or "[]"),
            "label": label(r, sizes),
            "questions": [_question(q, reveal=True) for q in qs[r["id"]]],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def review(
    moderator: int | str,
    experience_id: int,
    approve: bool,
    reason: str = "",
    company: str | None = None,
) -> None:
    """Approve or reject one post this moderator is responsible for (refused otherwise)."""
    row = db.experience(experience_id)
    if row is None or not _moderates(moderator, row):
        raise ServiceError("That post is not one you moderate.")
    if row["status"] not in ("pending", "hidden"):
        raise ServiceError("That post has already been reviewed.")
    reason = " ".join((reason or "").split())[:300]
    if not approve and not reason:
        raise ServiceError("Say why the post is rejected; the student sees the reason.")
    fixed = None
    if company and company.strip():
        try:
            slug, name, _ = experience_checks.normalise_company(company)
        except ExperienceRejected as e:
            raise ServiceError(str(e)) from e
        fixed = (slug, name)
    by = OPS if moderator == OPS else f"org:{moderator}"
    db.review_experience(
        experience_id, "approved" if approve else "rejected", by, "" if approve else reason, fixed
    )


def report(student_id: str, experience_id: int) -> int:
    """A signed-in student reports a published post; enough reports hide it for review."""
    row = db.experience(experience_id)
    if row is None or row["status"] != "approved":
        raise ServiceError("Only published posts can be reported.")
    if row["student_id"] == student_id:
        raise ServiceError("You cannot report your own post.")
    return db.report_experience(experience_id, student_id, REPORTS_TO_HIDE)


# --- browsing ---------------------------------------------------------------------------------


def _question(q: Mapping, reveal: bool) -> dict:
    out = {"kind": q["kind"], "text": q["text"]}
    if q["kind"] == "mcq":
        out["options"] = json.loads(q["options_json"] or "[]")
        if reveal:
            out["correct_index"] = q["correct_index"]
            out["explanation"] = q["explanation"]
    return out


def companies_overview() -> list[dict]:
    """Every known company and any with approved posts: counts per round, careers link."""
    out: dict[str, dict] = {
        c["slug"]: {
            "slug": c["slug"],
            "name": c["name"],
            "careers_url": c.get("careers_url", ""),
            "posts": 0,
            "questions": 0,
            "rounds": {},
        }
        for c in experience_checks.companies()
    }
    for r in db.approved_experience_counts():
        c = out.setdefault(
            r["company_slug"],
            {
                "slug": r["company_slug"],
                "name": r["company_name"],
                "careers_url": "",
                "posts": 0,
                "questions": 0,
                "rounds": {},
            },
        )
        c["posts"] += r["posts"]
        c["questions"] += r["questions"]
        c["rounds"][r["round"]] = {"posts": r["posts"], "questions": r["questions"]}
    return sorted(out.values(), key=lambda c: (-c["posts"], c["name"].lower()))


def company_detail(slug: str, round_: str | None = None) -> dict:
    """A company's approved posts (newest interview first), labelled, never named."""
    if round_ is not None and round_ not in EXPERIENCE_ROUNDS:
        raise ServiceError("Unknown round.")
    known = experience_checks.company(slug)
    rows = db.approved_experiences(slug, round_)
    if known is None and not rows and not db.approved_experiences(slug):
        raise ServiceError("No such company.")
    overview = next((c for c in companies_overview() if c["slug"] == slug), None)
    qs = db.experience_questions([r["id"] for r in rows])
    sizes = db.approved_posters_by_batch()
    return {
        "slug": slug,
        "name": known["name"] if known else (rows[0]["company_name"] if rows else slug),
        "careers_url": (known or {}).get("careers_url", ""),
        "rounds": (overview or {}).get("rounds", {}),
        "posts": [
            {
                "id": r["id"],
                "label": label(r, sizes),
                "role": r["role"],
                "round": r["round"],
                "interview_month": r["interview_month"],
                "tip": r["tip"],
                "questions": [_question(q, reveal=True) for q in qs[r["id"]]],
            }
            for r in rows
        ],
    }


# --- practice -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PracticeQuiz:
    company: str
    round: str
    source: str  # "reported" (students' questions) or "ai" (AI practice, never reported)
    questions: list[tuple[str, Question]]  # (id, question)
    label: str = ""
    notes: list[str] = field(default_factory=list)


def _company_name(slug: str) -> str:
    known = experience_checks.company(slug)
    if known:
        return known["name"]
    rows = db.approved_experiences(slug)
    if not rows:
        raise ServiceError("No such company.")
    return rows[0]["company_name"]


def reported_quiz(slug: str, round_: str, count: int = 10) -> PracticeQuiz:
    """Approved multiple-choice questions students reported for this company and round."""
    name = _company_name(slug)
    rows = db.approved_company_questions(slug, round_, "mcq")
    if not rows:
        raise ServiceError(
            f"No multiple-choice {EXPERIENCE_ROUNDS.get(round_, round_)} questions have been "
            f"reported for {name} yet. Try the AI practice instead."
        )
    picked = random.Random(uuid.uuid4().hex).sample(rows, min(count, len(rows)))
    questions = [(question_bank.qid(q), q) for q in map(_as_question, picked)]
    return PracticeQuiz(name, round_, "reported", questions, "Reported by students")


REPORTED_NOTE = "As reported by the student who was asked it."


def _as_question(row: Mapping) -> Question:
    """A reported MCQ (an experience_questions row) as a quiz question; its id is the usual
    text hash, so grading finds it again."""
    return Question(
        text=row["text"],
        options=json.loads(row["options_json"]),
        correct_index=row["correct_index"],
        explanation=row["explanation"] or REPORTED_NOTE,
        bloom_level="understand",
    )


def ai_topic(student_id: str, round_: str) -> str:
    if round_ in QUIZ_ROUNDS:
        return QUIZ_ROUNDS[round_]
    profile = services.current_profile(student_id)
    focus = syllabus.focus_topics(profile.target_role) if profile else []
    return focus[0] if focus else "DSA"


def ai_quiz(student_id: str, slug: str, round_: str, count: int = 5) -> PracticeQuiz:
    """AI practice in the style of a company's round: the usual generator and critic on the
    round's topic. Always labelled AI, never stored as reported."""
    if round_ in ("hr", "group_discussion"):
        raise ServiceError("HR and group discussion rounds are practised as a mock interview.")
    if round_ not in EXPERIENCE_ROUNDS:
        raise ServiceError("Unknown round.")
    name = _company_name(slug)
    topic = ai_topic(student_id, round_)
    made = agents.make_quiz(
        topic,
        "medium",
        db.asked_questions(student_id, topic),
        count=count,
        student_id=student_id,
        area=f"{name}-style {EXPERIENCE_ROUNDS[round_]} round "
        "(AI practice, not reported questions)",
    )
    db.save_generated(
        _ai_key(slug, round_), "medium", made.questions, "mock" if settings().mock_mode else "ai"
    )
    return PracticeQuiz(
        name,
        round_,
        "ai",
        [(question_bank.qid(q), q) for q in made.questions],
        AI_LABEL,
        [f"Written by AI on {topic}, in the style of a {name} {EXPERIENCE_ROUNDS[round_]} round."],
    )


def _ai_key(slug: str, round_: str) -> str:
    return f"company:{slug}:{round_}"[:60]


def grade_practice(
    student_id: str,
    slug: str,
    round_: str,
    source: str,
    answers: Sequence[tuple[str, int | None]],
) -> dict:
    """Grade a company practice quiz. Recorded in company_practice only: no syllabus topic's
    quiz history, level, weakness or plan changes."""
    if source not in ("reported", "ai"):
        raise ServiceError("Unknown practice source.")
    if not answers or len(answers) > 30:
        raise ServiceError("Send between 1 and 30 answers.")
    if source == "reported":
        known = {
            question_bank.qid(_as_question(r)): r
            for r in db.approved_company_questions(slug, round_, "mcq")
        }
    review = []
    correct = 0
    for qid, chosen in answers:
        if chosen is not None and chosen not in range(4):
            raise ServiceError("Invalid answer choice.")
        if source == "reported":
            row = known.get(qid)
            if row is None:
                raise ServiceError("An answer does not match a question of this practice.")
            right, explanation = row["correct_index"], row["explanation"]
        else:
            found = db.generated(qid)
            if found is None or found[0] != _ai_key(slug, round_):
                raise ServiceError("An answer does not match a question of this practice.")
            right, explanation = found[2].correct_index, found[2].explanation
        correct += chosen == right
        review.append(
            {
                "id": qid,
                "chosen": chosen,
                "correct_index": right,
                "is_correct": chosen == right,
                "explanation": explanation or REPORTED_NOTE,
            }
        )
    db.save_company_practice(student_id, slug, round_, source, correct, len(answers))
    return {
        "correct": correct,
        "total": len(answers),
        "score_pct": round(100 * correct / len(answers), 1),
        "review": review,
        "source": source,
    }


def interview_practice(
    student_id: str, slug: str, round_: str, on_event: OnEvent | None = None
) -> services.InterviewSession:
    """A mock interview for a company's round: the open questions students reported, asked word
    for word, then the AI interviewer closes in that company's style. With none reported, it
    is AI practice from the start."""
    if round_ not in EXPERIENCE_ROUNDS:
        raise ServiceError("Unknown round.")
    name = _company_name(slug)
    reported = [r["text"] for r in db.approved_company_questions(slug, round_, "open")]
    random.Random(uuid.uuid4().hex).shuffle(reported)
    label = EXPERIENCE_ROUNDS[round_]
    focus = (
        f"a {name} {label} interview round for a fresher; keep to what such a round covers, "
        f"and never claim a question is one {name} asks"
    )
    return services.start_interview(
        student_id,
        f"Company practice - {name} ({label})",
        on_event,
        script=reported,
        focus=focus,
    )
