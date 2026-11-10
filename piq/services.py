"""Controllers: every operation the UI performs, as plain functions over agents + db.

Views call these (plus formatter and ui) and nothing below them. Each function validates
its input, runs the agents, persists the result and returns typed state, so every user
flow is testable without Streamlit. `ServiceError` messages are safe to show to users.
"""

import csv
import json
import math
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, model_validator

from piq import agents, checks, db, degrees, question_bank, resume_builder, scorecard, syllabus
from piq.config import (
    BULLET_MAX_CHARS,
    CRITERION_WEAK_BELOW,
    DATA_DIR,
    DEFAULT_SAMPLE,
    DIFFICULTIES,
    EMAIL_RE,
    INSTANT_QUIZ_SIZE,
    INTERVIEW_TIPS,
    INTERVIEW_TYPES,
    PROJECT_STATUSES,
    QUIZ_BANK_SHARE,
    QUIZ_BATCH,
    QUIZ_MAX_PER_TOPIC,
    QUIZ_MAX_TOTAL,
    RECENT_DAYS,
    RESULTS_DIR,
    RESUME_MASTERY_AT,
    RESUME_REVIEW_DAYS,
    TIMEZONE,
    TREND_STEP,
    USERNAME_RE,
    WEAK_THRESHOLD,
)
from piq.graph import OnEvent
from piq.resume import ResumeError as ResumeError  # re-exported: views catch it via services
from piq.resume import extract_text
from piq.schemas import (
    AnswerEvaluation,
    InterviewTurn,
    Question,
    QuizSet,
    StudentProfile,
    WeeklyPlan,
)
from piq.syllabus import Domain

URL_RE = re.compile(r"^https?://[^\s<>()\[\]\"'`]+$")
SAMPLES_DIR = DATA_DIR / "sample_resumes"
MAX_ANSWER_CHARS = 4000


class ServiceError(ValueError):
    """Invalid input or state for the requested operation."""


def _require_profile(student_id: str | None) -> StudentProfile:
    profile = current_profile(student_id)
    if profile is None:
        raise ServiceError("Onboard this student first.")
    return profile


# --- syllabus: the student's domain and topics ---------------------------------------


@dataclass(frozen=True)
class LockedDomain:
    domain: Domain
    since: str  # UTC timestamp of the first saved resume (an organization's student: of joining)
    by: str | None = None  # the organization that placed the student in this domain, if any


@dataclass(frozen=True)
class StudentSyllabus:
    """What a student studies: their role's domain, the topics tracked for them (focus topics
    plus domain topics they chose to quiz) and the rest of the domain."""

    domain: Domain
    role: str
    focus: list[str]
    tracked: list[str]
    others: list[str]
    locked: LockedDomain | None

    @property
    def area(self) -> str:
        """How a quiz names the field a topic belongs to."""
        return f"{self.domain.name}, for a {self.role}"


def domains() -> tuple[Domain, ...]:
    return syllabus.domains()


def domain_roles(domain_id: str) -> list[str]:
    try:
        return syllabus.roles_in(domain_id)
    except KeyError as e:
        raise ServiceError(f"Unknown domain {domain_id!r}.") from e


def domain_of_role(role: str) -> Domain:
    return syllabus.domain_of_role(role)


def focus_topics(role: str) -> list[str]:
    return syllabus.focus_topics(role)


def locked_domain(student_id: str | None) -> LockedDomain | None:
    """The domain a student's first saved resume fixed, or None (nothing saved yet)."""
    row = db.first_resume_domain(student_id) if student_id else None
    if row is None:
        return None
    if row["org_name"]:  # an organization's student: the domain it assigned, until it moves them
        return LockedDomain(
            syllabus.domain_of_role(row["target_role"]), row["created_at"], by=row["org_name"]
        )
    try:
        return LockedDomain(syllabus.domain(row["domain_id"]), row["created_at"])
    except KeyError:  # a domain since removed from the catalog no longer locks anything
        return None


def student_syllabus(
    student_id: str | None, profile: StudentProfile, scores: Mapping[str, float] | None = None
) -> StudentSyllabus:
    """`scores`: the student's recent topic averages when the caller already read them."""
    if scores is None:
        scores = db.topic_performance(student_id) if student_id else {}
    role = profile.target_role
    tracked = syllabus.tracked_topics(role, scores)
    return StudentSyllabus(
        domain=syllabus.domain_of_role(role),
        role=role,
        focus=syllabus.focus_topics(role),
        tracked=tracked,
        others=syllabus.other_topics(role, tracked),
        locked=locked_domain(student_id),
    )


def weakness_for(profile: StudentProfile, scores: Mapping[str, float]) -> dict[str, float]:
    """Weakness of every topic tracked for this student (see syllabus.tracked_topics)."""
    topics = syllabus.tracked_topics(profile.target_role, scores)
    return checks.topic_weakness(dict(scores), agents.missing_topics(profile), topics)


# --- students & onboarding -----------------------------------------------------


def student_row(student_id: str | None) -> sqlite3.Row | None:
    """The account (id, name, username, email, target_role, readiness_score), or None."""
    return db.student(student_id) if student_id else None


def delete_student(student_id: str | None, confirm_username: str | None) -> None:
    """Delete an account and (by cascade) all of its history, only when `confirm_username` is
    its username: a slip of the finger must not cost a semester of data."""
    student = student_row(student_id)
    if student is None:
        raise ServiceError("This account no longer exists.")
    if (confirm_username or "").strip().lower() != student["username"]:
        raise ServiceError("That is not this account's username; nothing was deleted.")
    db.delete_student(student["id"])


def list_students() -> list[sqlite3.Row]:
    return db.list_students()


def current_profile(student_id: str | None) -> StudentProfile | None:
    return db.latest_profile(student_id) if student_id else None


def target_roles() -> list[str]:
    return list(agents.roles())


@lru_cache(maxsize=1)
def sample_resumes() -> tuple[str, ...]:
    """The bundled sample files; they ship with the app, so the folder is listed once."""
    return tuple(sorted(p.name for p in SAMPLES_DIR.glob("*.txt")))


def default_sample() -> str:
    """The sample the home page offers first: DEFAULT_SAMPLE, or the first file without it.
    (Alphabetical order would change the demo every time a sample is added.)"""
    names = sample_resumes()
    return DEFAULT_SAMPLE if DEFAULT_SAMPLE in names else names[0]


def load_sample(name: str) -> str:
    if name not in sample_resumes():  # also blocks path traversal: only listed files load
        raise ServiceError(f"Unknown sample resume {name!r}.")
    return (SAMPLES_DIR / name).read_text(encoding="utf-8")


def read_resume(filename: str, data: bytes) -> str:
    """Uploaded file -> text; raises resume.ResumeError (a ValueError) with a user message."""
    return extract_text(filename, data)


def generate_candidate_id(name: str = "") -> str:
    """A unique username for a candidate who has no account (the API's resume builder)."""
    slug = re.sub(r"[^a-z0-9]", "", (name or "").lower())[:4] or "cand"
    return f"{slug}{uuid.uuid4().hex[:6]}"


def onboard(
    student_id: str, target_role: str, resume_text: str, on_event: OnEvent | None = None
) -> tuple[str, StudentProfile]:
    """Profile a signed-in student's resume against a role (it becomes their target role)."""
    if student_row(student_id) is None:
        raise ServiceError("Sign in first.")
    if target_role not in agents.roles():
        raise ServiceError(f"Unknown target role {target_role!r}.")
    if not resume_text.strip():
        raise ServiceError("The resume is empty.")
    lock = locked_domain(student_id)
    if lock and syllabus.domain_of_role(target_role).id != lock.domain.id:
        raise ServiceError(
            f"This student's domain is locked to {lock.domain.name}: choose one of its roles."
        )
    profile = agents.create_profile(resume_text, target_role, on_event)
    return db.save_profile(student_id, profile), profile


def benchmark_profile(student_id: str) -> StudentProfile:
    """Start without a resume: the target role's whole skill list becomes the gaps, so the
    roadmap, quizzes and interviews can begin at once; a resume scan later replaces it."""
    student = student_row(student_id)
    if student is None:
        raise ServiceError("Sign in first.")
    profile = starting_profile(student["name"], student["target_role"])
    db.save_profile(student_id, profile)
    return profile


def starting_profile(name: str, role: str, education: str = "") -> StudentProfile:
    """The profile of someone who has not scanned a resume: every skill the role asks for is a
    gap. Pure: the benchmark start, and what an organization's students are created with."""
    skill_topics = agents.roles().get(role)
    if skill_topics is None:
        raise ServiceError(f"Unknown target role {role!r}.")
    return StudentProfile(
        name=name,
        education=education,
        skills=[],
        projects=[],
        internships=[],
        matched_skills=[],
        resume_feedback=["Upload your resume to measure the skills you already have."],
        target_role=role,
        missing_skills=list(skill_topics),
        readiness_score=checks.readiness_score(skill_topics, []),
    )


def onboard_candidate(
    name: str,
    target_role: str,
    resume_text: str,
    candidate_id: str | None = None,
    on_event: OnEvent | None = None,
) -> tuple[str, StudentProfile]:
    """Onboard someone without an account (the API's resume builder): `candidate_id` is a
    username, made up from the name when absent."""
    username = (candidate_id or "").strip().lower() or generate_candidate_id(name)
    if not USERNAME_RE.match(username):
        raise ServiceError("A candidate id is 3-20 lower-case letters, digits, dots, - or _.")
    if target_role not in agents.roles():
        raise ServiceError(f"Unknown target role {target_role!r}.")
    row = db.student_by_username(username)
    sid = (
        row["id"] if row else db.create_student(name.strip() or "Candidate", username, target_role)
    )
    return onboard(sid, target_role, resume_text, on_event)


# --- weekly plan ---------------------------------------------------------------


@dataclass(frozen=True)
class PlanOverview:
    plans: list[WeeklyPlan]
    scores: dict[str, float]
    weakness: dict[str, float]
    next_week: int
    done: dict[int, set[int]]  # week_no -> days marked done


def plan_overview(student_id: str, profile: StudentProfile | None = None) -> PlanOverview:
    """`profile`: the student's current profile when the caller already loaded it."""
    profile = profile or _require_profile(student_id)
    with_progress = db.plans_with_progress(student_id)
    plans = [p for p, _ in with_progress]
    scores = db.topic_performance(student_id)
    weakness = weakness_for(profile, scores)
    return PlanOverview(
        plans=plans,
        scores={t: s for t, s in scores.items() if t in weakness},
        weakness=weakness,
        next_week=plans[-1].week_no + 1 if plans else 1,
        done={p.week_no: days for p, days in with_progress},
    )


def set_days_done(student_id: str, week_no: int, days: Iterable[int]) -> set[int]:
    """Mark exactly `days` (1-7) of a week done; returns them."""
    chosen = set(days)
    if not chosen <= set(range(1, 8)):
        raise ServiceError("Days run from 1 to 7.")
    if week_no < 1:
        raise ServiceError("Weeks start at 1.")
    db.set_days_done(student_id, week_no, chosen)
    return chosen


def generate_next_plan(student_id: str, on_event: OnEvent | None = None) -> WeeklyPlan:
    profile = _require_profile(student_id)
    ov = plan_overview(student_id, profile)
    previous = ov.plans[-1] if ov.plans else None
    plan = agents.plan_week(profile, ov.scores, ov.next_week, previous, student_id, on_event)
    db.save_plan(student_id, plan)
    return plan


# --- quizzes -------------------------------------------------------------------


@dataclass(frozen=True)
class QuizResult:
    quiz: QuizSet
    chosen: list[int | None]
    score_pct: float
    next_difficulty: str

    @property
    def correct(self) -> int:
        return sum(
            a == q.correct_index for q, a in zip(self.quiz.questions, self.chosen, strict=True)
        )


@dataclass(frozen=True)
class QuizSetup:
    """What the quiz setup shows: the student's tracked topics with their weakness, the rest
    of their domain to choose from, and each topic's latest attempt."""

    weakness: dict[str, float]  # tracked topics only
    last: dict[str, tuple[float, str]]  # topic -> (score %, difficulty) of the latest quiz
    others: list[str] = field(default_factory=list)  # the rest of the domain
    focus: list[str] = field(default_factory=list)  # the role's focus topics

    @property
    def topics(self) -> list[str]:
        """Tracked topics weakest first (ties keep the syllabus order), then the others."""
        return sorted(self.weakness, key=lambda t: -self.weakness[t]) + list(self.others)

    def suggested(self, topic: str) -> str:
        """The difficulty after the latest quiz on `topic` (medium before the first)."""
        last = self.last.get(topic)
        return agents.suggest_difficulty(*last) if last else "medium"


def quiz_setup(student_id: str, profile: StudentProfile | None = None) -> QuizSetup:
    """`profile`: the student's current profile when the caller already loaded it. One query
    gives every topic's weakness and suggested difficulty."""
    profile = profile or _require_profile(student_id)
    stats = db.topic_stats(student_id)
    scores = {t: s["avg_pct"] for t, s in stats.items()}
    weakness = weakness_for(profile, scores)
    return QuizSetup(
        weakness=weakness,
        last={t: (s["last_pct"], s["last_difficulty"]) for t, s in stats.items()},
        others=syllabus.other_topics(profile.target_role, weakness),
        focus=syllabus.focus_topics(profile.target_role),
    )


def quiz_key(quiz: QuizSet) -> str:
    """A stable id for one quiz's answer widgets, so a new quiz never shows old answers."""
    return checks.text_hash(quiz.questions[0].text)


def _check_quiz_params(topic: str, difficulty: str | None = None) -> None:
    if topic not in syllabus.all_topics():
        raise ServiceError(f"Unknown topic {topic!r}.")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        raise ServiceError(f"Unknown difficulty {difficulty!r}.")


def suggested_difficulty(student_id: str, topic: str) -> str:
    _check_quiz_params(topic)
    last = db.last_attempt(student_id, topic)
    if last is None:
        return "medium"
    return agents.suggest_difficulty(last["score_pct"], last["difficulty"])


def start_quiz(
    student_id: str, topic: str, difficulty: str, on_event: OnEvent | None = None
) -> QuizSet:
    _require_profile(student_id)
    _check_quiz_params(topic, difficulty)
    previous = db.asked_questions(student_id, topic)
    return agents.make_quiz(topic, difficulty, previous, student_id=student_id, on_event=on_event)


def submit_quiz(student_id: str, quiz: QuizSet, chosen: list[int | None]) -> QuizResult:
    if len(chosen) != len(quiz.questions):
        raise ServiceError("The answers do not match the quiz.")
    if any(a is not None and a not in range(4) for a in chosen):
        raise ServiceError("Invalid answer choice.")
    pct = db.save_quiz_attempt(student_id, quiz, list(chosen))
    return QuizResult(quiz, list(chosen), pct, agents.suggest_difficulty(pct, quiz.difficulty))


# --- instant quizzes: straight from the question bank, no LLM call ------------------------


def instant_quiz(
    topic: str,
    difficulty: str,
    count: int = INSTANT_QUIZ_SIZE,
    student_id: str | None = None,
) -> QuizSet:
    """Up to `count` bank questions on `topic` at `difficulty`. With a student: only topics of
    their domain, and none they have answered before. Raises when the bank has none left."""
    _check_quiz_params(topic, difficulty)
    if not 1 <= count <= QUIZ_MAX_PER_TOPIC:
        raise ServiceError(f"Choose 1 to {QUIZ_MAX_PER_TOPIC} questions.")
    seen: list[str] = []
    if student_id:
        profile = _require_profile(student_id)
        if topic not in syllabus.domain_of_role(profile.target_role).topics:
            raise ServiceError(f"{topic} is not in your domain's syllabus.")
        seen = db.asked_questions(student_id, topic)
    seed = f"{student_id or 'guest'}|{topic}|{difficulty}|{len(seen)}|{uuid.uuid4().hex}"
    questions = question_bank.draw(topic, difficulty, count, seen, seed)
    if not questions:
        raise ServiceError(
            f"The question bank has no new {difficulty} {topic} questions. Try another "
            "difficulty or topic."
        )
    return QuizSet(topic=topic, difficulty=difficulty, questions=questions)


def grade_instant_quiz(
    student_id: str | None, topic: str, difficulty: str, answers: Sequence[tuple[str, int | None]]
) -> QuizResult:
    """Grade (question id, chosen option or None) pairs against the bank. With a student the
    attempt is saved, so their weakness, plan and next difficulty follow it."""
    _check_quiz_params(topic, difficulty)
    if not answers or len(answers) > QUIZ_MAX_PER_TOPIC:
        raise ServiceError("Send between 1 and 50 answers.")
    questions = []
    for question_id, _ in answers:
        found = question_bank.get(question_id)
        if found is None or found[:2] != (topic, difficulty):
            raise ServiceError("An answer does not match a question of this quiz.")
        questions.append(found[2])
    if len({question_bank.qid(q) for q in questions}) != len(questions):
        raise ServiceError("A question is answered twice.")
    quiz = QuizSet(topic=topic, difficulty=difficulty, questions=questions)
    chosen = [c for _, c in answers]
    if student_id is None:
        if any(c is not None and c not in range(4) for c in chosen):
            raise ServiceError("Invalid answer choice.")
        right = sum(c == q.correct_index for q, c in zip(questions, chosen, strict=True))
        pct = round(100 * right / len(questions), 1)
        return QuizResult(quiz, chosen, pct, agents.suggest_difficulty(pct, difficulty))
    _require_profile(student_id)
    return submit_quiz(student_id, quiz, chosen)


# --- quizzes over several topics and difficulties -------------------------------------


def mix_from_handles(low: int, high: int) -> dict[str, int]:
    """A two-handle slider over 0-100 -> difficulty shares that always add up to 100:
    easy below the first handle, medium between them, hard above the second."""
    low, high = sorted((int(low), int(high)))
    if low < 0 or high > 100:
        raise ServiceError("The difficulty mix runs from 0% to 100%.")
    return {"easy": low, "medium": high - low, "hard": 100 - high}


def split_by_mix(n: int, mix: Mapping[str, int]) -> dict[str, int]:
    """`n` questions shared by the mix's percentages (largest remainder, so the parts add up
    to n exactly; a tie in remainders goes to medium, then easy, then hard)."""
    exact = {d: n * mix.get(d, 0) / 100 for d in DIFFICULTIES}
    counts = {d: math.floor(v) for d, v in exact.items()}
    tie_order = {"medium": 0, "easy": 1, "hard": 2}
    by_remainder = sorted(DIFFICULTIES, key=lambda d: (-(exact[d] - counts[d]), tie_order[d]))
    for d in by_remainder[: n - sum(counts.values())]:
        counts[d] += 1
    return counts


@dataclass(frozen=True)
class QuizSpec:
    """A quiz as the student set it up: questions per topic and the difficulty mix (%)."""

    counts: dict[str, int]
    mix: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def parts(self) -> list[tuple[str, str, int]]:
        """(topic, difficulty, questions) for each non-empty part, topic by topic, easy to
        hard: a topic's last part is its hardest, which its next suggestion is based on."""
        return [
            (topic, d, k)
            for topic, n in self.counts.items()
            for d, k in split_by_mix(n, self.mix).items()
            if k
        ]

    @property
    def batches(self) -> int:
        """Generation calls this quiz needs (each checked by the critic)."""
        return sum(math.ceil(k / QUIZ_BATCH) for *_, k in self.parts())


def quiz_spec(
    counts: Mapping[str, int], mix: Mapping[str, int], allowed: Iterable[str]
) -> QuizSpec:
    """Validate a quiz setup: 1-QUIZ_MAX_PER_TOPIC questions per chosen topic, at most
    QUIZ_MAX_TOTAL in all, topics from `allowed`, a mix of whole percentages adding to 100."""
    allowed = set(allowed)
    if not counts:
        raise ServiceError("Choose at least one topic.")
    unknown = [t for t in counts if t not in allowed]
    if unknown:
        raise ServiceError(f"Not in your syllabus: {', '.join(unknown)}.")
    for topic, n in counts.items():
        if not 1 <= int(n) <= QUIZ_MAX_PER_TOPIC:
            raise ServiceError(f"{topic}: choose 1 to {QUIZ_MAX_PER_TOPIC} questions.")
    total = sum(int(n) for n in counts.values())
    if total > QUIZ_MAX_TOTAL:
        raise ServiceError(
            f"That is {total} questions; one quiz holds at most {QUIZ_MAX_TOTAL}. "
            "Lower some topics or take two quizzes."
        )
    shares = {d: int(mix.get(d, 0)) for d in DIFFICULTIES}
    if set(mix) - set(DIFFICULTIES) or any(v < 0 for v in shares.values()):
        raise ServiceError("The difficulty mix has only easy, medium and hard, each 0% or more.")
    if sum(shares.values()) != 100:
        raise ServiceError("The difficulty mix must add up to 100%.")
    return QuizSpec({t: int(n) for t, n in counts.items()}, shares)


class QuizRun(BaseModel):
    """A generated quiz of one or more parts (one topic at one difficulty each), kept in
    st.session_state between reruns."""

    parts: list[QuizSet]

    @property
    def questions(self) -> list[tuple[QuizSet, Question]]:
        """Every question in order, with the part it belongs to."""
        return [(p, q) for p in self.parts for q in p.questions]

    @property
    def total(self) -> int:
        return sum(len(p.questions) for p in self.parts)

    @property
    def key(self) -> str:
        """Fresh widget keys per quiz, so a new quiz never shows old answers."""
        return checks.text_hash("".join(q.text for _, q in self.questions[:3]))


def bank_share(n: int) -> int:
    """How many of a part's `n` questions may come from the question bank."""
    return math.floor(n * QUIZ_BANK_SHARE)


def start_quiz_run(student_id: str, spec: QuizSpec, on_event: OnEvent | None = None) -> QuizRun:
    """Each part takes up to `bank_share(n)` unseen questions from the local question bank;
    the rest are generated in batches of up to QUIZ_BATCH questions, each through the critic.
    Generated questions come first, so the critic's numbering matches the quiz's within a
    part's first batch. Nothing repeats a question the student has seen on the topic or one
    already in this quiz. Raises like start_quiz when a batch cannot be approved."""
    profile = _require_profile(student_id)
    syl = student_syllabus(student_id, profile)
    spec = quiz_spec(spec.counts, spec.mix, syl.domain.topics)
    seen: dict[str, list[str]] = {}  # topic -> texts the student saw before, plus this quiz's
    plan = []
    for topic, difficulty, n in spec.parts():
        if topic not in seen:
            seen[topic] = db.asked_questions(student_id, topic)
        banked = question_bank.draw(
            topic,
            difficulty,
            bank_share(n),
            seen[topic],
            seed=f"{student_id}|{topic}|{len(seen[topic])}",
        )
        seen[topic] += [q.text for q in banked]
        plan.append((topic, difficulty, n, banked))
    parts: list[QuizSet] = []
    batch = 0
    batches = sum(math.ceil((n - len(b)) / QUIZ_BATCH) for _, _, n, b in plan)
    for topic, difficulty, n, banked in plan:
        if banked and on_event:
            on_event(f"{len(banked)} {difficulty} {topic} questions from the question bank")
        questions: list[Question] = []
        while len(questions) < n - len(banked):
            k = min(QUIZ_BATCH, n - len(banked) - len(questions))
            batch += 1
            if on_event and batches > 1:
                on_event(f"Batch {batch} of {batches}: {k} {difficulty} {topic} questions")
            made = agents.make_quiz(
                topic,
                difficulty,
                seen[topic],
                count=k,
                student_id=student_id,
                on_event=on_event,
                area=syl.area,
            )
            questions += made.questions
            seen[topic] += [q.text for q in made.questions]
        parts.append(QuizSet(topic=topic, difficulty=difficulty, questions=questions + banked))
    return QuizRun(parts=parts)


@dataclass(frozen=True)
class Outcome:
    """Answers in one slice of a quiz (a topic, a difficulty or a thinking level)."""

    label: str
    correct: int
    wrong: int
    skipped: int

    @property
    def total(self) -> int:
        return self.correct + self.wrong + self.skipped

    @property
    def pct(self) -> float:
        return round(100 * self.correct / self.total, 1) if self.total else 0.0


@dataclass(frozen=True)
class Mistake:
    n: int  # the question's number in the quiz, from 1
    topic: str
    difficulty: str
    question: Question
    chosen: int | None


BLOOM_ORDER = ("remember", "understand", "apply", "analyze")


@dataclass(frozen=True)
class QuizRunResult:
    run: QuizRun
    chosen: list[int | None]  # one per question, in quiz order
    run_id: int

    def _rows(self) -> list[tuple[int, QuizSet, Question, int | None]]:
        return [
            (i, p, q, a)
            for i, ((p, q), a) in enumerate(zip(self.run.questions, self.chosen, strict=True), 1)
        ]

    @property
    def total(self) -> int:
        return self.run.total

    @property
    def correct(self) -> int:
        return sum(a == q.correct_index for *_, q, a in self._rows())

    @property
    def skipped(self) -> int:
        return sum(a is None for a in self.chosen)

    @property
    def wrong(self) -> int:
        return self.total - self.correct - self.skipped

    @property
    def score_pct(self) -> float:
        return round(100 * self.correct / self.total, 1)

    def breakdown(self, by: str) -> list[Outcome]:
        """Outcomes per "topic" (quiz order), "difficulty" (easy to hard) or "bloom" (the
        question's thinking level, remember to analyze); only slices with questions."""
        key: Callable[[QuizSet, Question], str] = {
            "topic": lambda p, q: p.topic,
            "difficulty": lambda p, q: p.difficulty,
            "bloom": lambda p, q: q.bloom_level,
        }[by]
        tally: dict[str, Counter] = defaultdict(Counter)
        for _, p, q, a in self._rows():
            state = "skipped" if a is None else "correct" if a == q.correct_index else "wrong"
            tally[key(p, q)][state] += 1
        order = {
            "topic": list(dict.fromkeys(p.topic for p in self.run.parts)),
            "difficulty": list(DIFFICULTIES),
            "bloom": list(BLOOM_ORDER),
        }[by]
        return [
            Outcome(k, tally[k]["correct"], tally[k]["wrong"], tally[k]["skipped"])
            for k in order
            if k in tally
        ]

    def grid(self) -> dict[tuple[str, str], Outcome]:
        """(topic, difficulty) -> outcome, for every part."""
        out = {}
        for p in self.run.parts:
            rows = [(q, a) for _, pp, q, a in self._rows() if pp is p]
            correct = sum(a == q.correct_index for q, a in rows)
            skipped = sum(a is None for _, a in rows)
            out[(p.topic, p.difficulty)] = Outcome(
                f"{p.topic} · {p.difficulty}", correct, len(rows) - correct - skipped, skipped
            )
        return out

    def mistakes(self) -> list[Mistake]:
        """Every question answered wrong or left blank, in quiz order."""
        return [
            Mistake(i, p.topic, p.difficulty, q, a)
            for i, p, q, a in self._rows()
            if a != q.correct_index
        ]

    @property
    def next_difficulty(self) -> dict[str, str]:
        """Each topic's suggested next difficulty: from its hardest part in this quiz (the
        part saved last, which the Quiz page reads next time)."""
        out = {}
        for (topic, difficulty), o in self.grid().items():
            out[topic] = agents.suggest_difficulty(o.pct, difficulty)
        return out


def submit_quiz_run(student_id: str, run: QuizRun, chosen: Sequence[int | None]) -> QuizRunResult:
    if len(chosen) != run.total:
        raise ServiceError("The answers do not match the quiz.")
    if any(a is not None and a not in range(4) for a in chosen):
        raise ServiceError("Invalid answer choice.")
    chosen = list(chosen)
    parts, start = [], 0
    for p in run.parts:
        parts.append((p, chosen[start : start + len(p.questions)]))
        start += len(p.questions)
    run_id = db.save_quiz_run(student_id, parts)
    return QuizRunResult(run, chosen, run_id)


# --- interviews ----------------------------------------------------------------


class AnsweredTurn(BaseModel):
    question: str
    answer: str
    evaluation: AnswerEvaluation


InterviewPhase = Literal["asking", "awaiting_question", "finished"]


class InterviewSession(BaseModel):
    """Typed state of one mock interview, kept in st.session_state between reruns (and sent
    back and forth by the Next.js app).

    Its `phase` is a small state machine:
      asking --answer_question--> awaiting_question --continue_interview--> asking
      asking --answer to the final question--> finished
    `current` is the question awaiting an answer. It is None after an answer is saved
    until `continue_interview` succeeds, so a failed follow-up can be retried without
    re-answering (and without saving the same turn twice). A finished session never holds
    an open question (validated).
    """

    session_id: str
    interview_type: str
    past: list[dict]  # earlier sessions' Q/A: the interviewer's memory
    history: list[AnsweredTurn] = []
    current: InterviewTurn | None = None
    done: bool = False

    @model_validator(mode="after")
    def _finished_has_no_open_question(self) -> Self:
        if self.done and self.current is not None:
            raise ValueError("A finished interview has no open question.")
        return self

    @property
    def phase(self) -> InterviewPhase:
        if self.done:
            return "finished"
        return "asking" if self.current is not None else "awaiting_question"

    @property
    def average(self) -> float | None:
        if not self.history:
            return None
        return round(sum(t.evaluation.overall for t in self.history) / len(self.history), 2)

    def qa(self) -> list[dict]:
        return [{"question": t.question, "answer": t.answer} for t in self.history]


@dataclass(frozen=True)
class InterviewSummary:
    """A finished session in numbers, computed from its evaluations (no LLM call)."""

    averages: dict[str, float]  # rubric criterion -> mean score (0-5) over the answers
    strongest: str
    weakest: str
    tips: dict[str, str]  # each criterion below CRITERION_WEAK_BELOW -> its fixed tip


def interview_summary(session: InterviewSession) -> InterviewSummary:
    """Average each criterion over the session's answers; ties keep the rubric order."""
    if not session.history:
        raise ServiceError("This session has no answers yet.")
    criteria = list(session.history[0].evaluation.scores)
    averages = {
        c: round(sum(t.evaluation.scores[c] for t in session.history) / len(session.history), 2)
        for c in criteria
    }
    return InterviewSummary(
        averages=averages,
        strongest=max(criteria, key=lambda c: averages[c]),
        weakest=min(criteria, key=lambda c: averages[c]),
        tips={c: INTERVIEW_TIPS[c] for c in criteria if averages[c] < CRITERION_WEAK_BELOW},
    )


@dataclass(frozen=True)
class InterviewTrack:
    name: str
    focus: str
    group: str  # the domain's name, the degree set's label, or "General"


@lru_cache(maxsize=1)
def _tracks_data() -> dict:
    return json.loads((DATA_DIR / "interview_tracks.json").read_text(encoding="utf-8"))


def interview_tracks(profile: StudentProfile | None) -> list[InterviewTrack]:
    """The tracks a student can choose: their domain's five, any their degree adds (for
    example BCA, MCA, MSc or MSE), then the generic HR, Technical and Project types."""
    data = _tracks_data()
    out: list[InterviewTrack] = []
    if profile is not None:
        domain = syllabus.domain_of_role(profile.target_role)
        for t in data["domains"].get(domain.id, []):
            out.append(InterviewTrack(t["name"], t["focus"], domain.name))
        degree = degrees.parse(profile.education or "")
        for extra in data.get("degree_tracks", {}).values():
            if degree and degree.code in extra["degrees"]:
                out += [
                    InterviewTrack(t["name"], t["focus"], extra["label"]) for t in extra["tracks"]
                ]
    seen = {t.name for t in out}
    out += [InterviewTrack(t, "", "General") for t in INTERVIEW_TYPES if t not in seen]
    return out


def _track_focus(profile: StudentProfile, name: str) -> str:
    track = next((t for t in interview_tracks(profile) if t.name == name), None)
    if track is None:
        raise ServiceError(f"Unknown interview type {name!r}.")
    return track.focus


def start_interview(
    student_id: str, interview_type: str, on_event: OnEvent | None = None
) -> InterviewSession:
    """`interview_type`: a generic type or one of the student's tracks (interview_tracks)."""
    profile = _require_profile(student_id)
    focus = _track_focus(profile, interview_type)
    session_id = uuid.uuid4().hex
    past = db.past_turns(student_id, exclude_session=session_id)
    first = agents.next_question(
        profile, interview_type, [], past, student_id, on_event, focus=focus
    )
    return InterviewSession(
        session_id=session_id, interview_type=interview_type, past=past, current=first
    )


def answer_question(student_id: str, session: InterviewSession, answer: str) -> InterviewSession:
    """Evaluate and save the answer to `session.current`; returns state with current=None."""
    if session.phase != "asking" or session.current is None:
        raise ServiceError("There is no open question in this session.")
    answer = (answer or "").strip()
    if not answer:
        raise ServiceError("Type an answer first.")
    if len(answer) > MAX_ANSWER_CHARS:
        raise ServiceError(f"Answers are limited to {MAX_ANSWER_CHARS} characters.")
    profile = _require_profile(student_id)
    q = session.current.question
    ev = agents.evaluate_answer(profile, session.interview_type, q, answer, student_id)
    db.save_turn(student_id, session.session_id, session.interview_type, q, answer, ev)
    return session.model_copy(
        update={
            "history": [*session.history, AnsweredTurn(question=q, answer=answer, evaluation=ev)],
            "current": None,
            "done": session.current.is_final,
        }
    )


def continue_interview(
    student_id: str, session: InterviewSession, on_event: OnEvent | None = None
) -> InterviewSession:
    """Ask the next question after an answered turn."""
    if session.phase != "awaiting_question":
        raise ServiceError("This session is not waiting for a new question.")
    profile = _require_profile(student_id)
    nxt = agents.next_question(
        profile,
        session.interview_type,
        session.qa(),
        session.past,
        student_id,
        on_event,
        focus=_track_focus(profile, session.interview_type),
    )
    return session.model_copy(update={"current": nxt})


# --- dashboard -----------------------------------------------------------------


@dataclass(frozen=True)
class TopicMastery:
    """One topic on the dashboard: its quiz scores, weakness now and which way it moves."""

    topic: str
    scores: list[float]  # attempt order, oldest first
    weakness: float  # as the next plan sees it (checks.topic_weakness)
    trend: str  # "improving", "steady", "slipping", or "new" with fewer than two quizzes


def score_trend(scores: Sequence[float]) -> str:
    """The latest score against the mean of up to three before it."""
    if len(scores) < 2:
        return "new"
    before = scores[-4:-1]
    change = scores[-1] - sum(before) / len(before)
    if change >= TREND_STEP:
        return "improving"
    return "slipping" if change <= -TREND_STEP else "steady"


def _field(row: Mapping, key: str, default: object = None) -> object:
    """A column of a sqlite3.Row or a dict that may lack it (rows from older queries)."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def topic_mastery(profile: StudentProfile, attempts: Sequence[Mapping]) -> list[TopicMastery]:
    """Every tracked topic, weakest first, from quiz_history rows (oldest first): the same
    last-three average db.topic_performance takes (weighted by questions), computed here so
    the dashboard needs no extra query. Topics outside the student's domain are left out."""
    scores: dict[str, list[float]] = defaultdict(list)
    sizes: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for a in attempts:
        pct = float(a["score_pct"])
        scores[a["topic"]].append(pct)
        total = _field(a, "total")
        correct = _field(a, "correct")
        sizes[a["topic"]].append((correct, total) if total else (pct, 100))
    recent = {
        t: round(100 * sum(c for c, _ in s[-3:]) / sum(n for _, n in s[-3:]), 1)
        for t, s in sizes.items()
    }
    weakness = weakness_for(profile, recent)
    ranked = sorted(weakness, key=lambda t: -weakness[t])
    return [TopicMastery(t, scores[t], weakness[t], score_trend(scores[t])) for t in ranked]


@dataclass(frozen=True)
class Dashboard:
    profile: StudentProfile
    quiz_history: list[sqlite3.Row]
    plans_done: list[tuple[WeeklyPlan, set[int]]]  # each plan and its days marked done
    sessions: list[sqlite3.Row]
    agent_stats: list[sqlite3.Row]
    rejections: list[sqlite3.Row]
    readiness: list[sqlite3.Row]  # (created_at, readiness_score) per profile, oldest first
    syllabus: StudentSyllabus | None = None
    runs: list[sqlite3.Row] = field(default_factory=list)  # multi-part quizzes, newest first
    accuracy: list[sqlite3.Row] = field(default_factory=list)  # topic x difficulty totals

    @property
    def answered(self) -> tuple[int, int]:
        """(correct, total) over every question the student has answered."""
        return sum(r["correct"] for r in self.accuracy), sum(r["total"] for r in self.accuracy)

    @property
    def quizzes_taken(self) -> int:
        """Quizzes as the student took them: a multi-part quiz counts once."""
        runs = {_field(a, "run_id") for a in self.quiz_history} - {None}
        return len(runs) + sum(1 for a in self.quiz_history if _field(a, "run_id") is None)

    @property
    def plans(self) -> list[WeeklyPlan]:
        return [p for p, _ in self.plans_done]

    @property
    def streak(self) -> "Streak":
        return study_streak(self.quiz_history, self.sessions)

    @property
    def mastery(self) -> list[TopicMastery]:
        return topic_mastery(self.profile, self.quiz_history)


def dashboard(student_id: str, profile: StudentProfile | None = None) -> Dashboard:
    """`profile`: the student's current profile when the caller already loaded it."""
    profile = profile or _require_profile(student_id)
    try:
        history = db.quiz_history(student_id)
        return Dashboard(
            profile=profile,
            quiz_history=history,
            plans_done=db.plans_with_progress(student_id),
            sessions=db.interview_history(student_id),
            agent_stats=db.agent_stats(),
            rejections=db.recent_rejections(),
            readiness=db.readiness_history(student_id),
            syllabus=student_syllabus(student_id, profile, {a["topic"]: 0 for a in history}),
            runs=db.quiz_runs(student_id),
            accuracy=db.accuracy_grid(student_id),
        )
    except sqlite3.Error as e:
        raise ServiceError(
            "Your progress could not be read. Reload the page, and restart the app if it "
            "keeps failing."
        ) from e


# --- evaluation ----------------------------------------------------------------


def evaluation_summary() -> dict | None:
    """The last run_eval summary, or None if there is none (or it is unreadable)."""
    try:
        return json.loads((RESULTS_DIR / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- home: today's focus ----------------------------------------------------------


@dataclass(frozen=True)
class NextAction:
    """Today's focus: one next step chosen by rules (no LLM), why, and where to do it."""

    label: str  # the step, e.g. "Take a medium OS quiz"
    reason: str  # one plain sentence
    cta: str  # what the button does, e.g. "Open Weekly plan"
    page: str  # the view that does it
    icon: str  # Material Symbols name
    topic: str | None = None  # preselected on the Quiz page
    difficulty: str | None = None


@dataclass(frozen=True)
class ChecklistItem:
    label: str
    done: bool


@dataclass(frozen=True)
class Activity:
    at: datetime  # UTC
    text: str  # plain words built from topics, numbers and fixed vocabulary
    topic: str | None = None


@dataclass(frozen=True)
class HomeOverview:
    profile: StudentProfile
    weakness: dict[str, float]
    next_action: NextAction
    checklist: list[ChecklistItem]
    recent: list[Activity]
    streak: "Streak"
    week_done: tuple[int, int] | None  # (latest week, days marked done), None before week 1


@dataclass(frozen=True)
class Streak:
    """Study activity by day on the student's calendar: quizzes and interview sessions."""

    current: int  # consecutive active days ending today (or yesterday, before today's study)
    longest: int
    days: dict[date, int]  # day -> how many quizzes and sessions


def activity_days(timestamps: Iterable[str], tz: str = TIMEZONE) -> Counter[date]:
    """SQLite UTC timestamps -> activity count per day in the student's time zone (UTC
    midnight is 05:30 in India, so the UTC date would be wrong for a third of the day)."""
    zone = ZoneInfo(tz)
    return Counter(utc(t).astimezone(zone).date() for t in timestamps)


def streaks(days: Iterable[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive active days. The current run may end today or
    yesterday: a streak is not broken until a whole day passes without study."""
    active = set(days)
    longest = run = 0
    previous = None
    for day in sorted(active):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest, previous = max(longest, run), day
    end = today if today in active else today - timedelta(days=1)
    current = 0
    while end - timedelta(days=current) in active:
        current += 1
    return current, longest


def study_streak(
    attempts: Sequence[Mapping], sessions: Sequence[Mapping], today: date | None = None
) -> Streak:
    """Streaks from rows the caller already has (quiz_history, interview_history), so no
    extra query: an interview session counts on the day it started."""
    days = activity_days([a["attempted_at"] for a in attempts] + [s["started"] for s in sessions])
    today = today or datetime.now(ZoneInfo(TIMEZONE)).date()
    current, longest = streaks(days, today)
    return Streak(current, longest, dict(days))


def utc(timestamp: str) -> datetime:
    """A SQLite CURRENT_TIMESTAMP string (UTC, no zone) as an aware datetime."""
    return datetime.fromisoformat(timestamp).replace(tzinfo=UTC)


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def _difficulty_after(last: Mapping | None) -> str:
    return agents.suggest_difficulty(last["score_pct"], last["difficulty"]) if last else "medium"


def decide_next_action(
    profile: StudentProfile | None,
    latest_plan: Mapping | None,
    weakness: Mapping[str, float],
    attempts: Sequence[Mapping],
    sessions: int,
    now: datetime,
) -> NextAction:
    """The next step of the loop profile -> plan -> quiz -> adapt, first match wins:
    no profile; no plan; a weak topic not quizzed lately (weakest first); no interview yet;
    a plan at least RECENT_DAYS old with new scores since; else practise the weakest topic.
    `attempts` are quiz_history rows, oldest first."""
    if profile is None:
        return NextAction(
            "Onboard with your resume",
            "PlacementIQ starts from your resume: it finds the skills your target role needs.",
            "Open Onboard",
            "views/onboard.py",
            "upload_file",
        )
    if latest_plan is None:
        return NextAction(
            "Generate your week 1 plan",
            "A plan turns your weakest topics into seven days of practice.",
            "Open Weekly plan",
            "views/plan.py",
            "calendar_month",
        )
    last = {a["topic"]: a for a in attempts}  # oldest first, so the latest one wins
    cutoff = now - timedelta(days=RECENT_DAYS)
    for topic in sorted(weakness, key=lambda t: -weakness[t]):
        if weakness[topic] <= WEAK_THRESHOLD:
            break
        if topic not in last or utc(last[topic]["attempted_at"]) < cutoff:
            difficulty = _difficulty_after(last.get(topic))
            why = (
                "you have not taken a quiz on it yet"
                if topic not in last
                else f"it has had no quiz in the last {RECENT_DAYS} days"
            )
            return NextAction(
                f"Take {_article(difficulty)} {difficulty} {topic} quiz",
                f"{topic} is one of your weak topics and {why}.",
                "Set up this quiz",
                "views/quiz.py",
                "quiz",
                topic,
                difficulty,
            )
    if sessions == 0:
        return NextAction(
            "Try a mock interview",
            "Interviews test explaining what you know; you get feedback on every answer.",
            "Open Mock interview",
            "views/interview.py",
            "record_voice_over",
        )
    planned = utc(latest_plan["created_at"])
    since = sum(1 for a in attempts if utc(a["attempted_at"]) > planned)
    if planned <= cutoff and since:
        week = latest_plan["week_no"]
        scores = f"{since} quiz score{'s' if since != 1 else ''}"
        return NextAction(
            f"Generate your week {week + 1} plan",
            f"Your week {week} plan is {(now - planned).days} days old and {scores} came in "
            "since; the planner moves minutes to the topics that need them.",
            "Open Weekly plan",
            "views/plan.py",
            "calendar_month",
        )
    topic = max(weakness, key=lambda t: weakness[t])
    difficulty = _difficulty_after(last.get(topic))
    return NextAction(
        f"Practise {topic} with {_article(difficulty)} {difficulty} quiz",
        f"{topic} is your weakest topic; another quiz shows whether it is improving.",
        "Set up this quiz",
        "views/quiz.py",
        "quiz",
        topic,
        difficulty,
    )


def _checklist(
    profile: StudentProfile | None, latest_plan: Mapping | None, quizzes: int, sessions: int
) -> list[ChecklistItem]:
    return [
        ChecklistItem("Onboard with a resume", profile is not None),
        ChecklistItem("Generate a weekly plan", latest_plan is not None),
        ChecklistItem("Take a quiz", quizzes > 0),
        ChecklistItem("Try a mock interview", sessions > 0),
    ]


def _recent(
    latest_plan: Mapping | None, attempts: Sequence[Mapping], sessions: Sequence[Mapping]
) -> list[Activity]:
    # A quiz of several parts (topics and difficulties) is one line, not one per part.
    runs: dict[object, list[Mapping]] = defaultdict(list)
    for a in attempts:
        runs[_field(a, "run_id") or ("single", id(a))].append(a)
    quizzes = sorted(runs.values(), key=lambda parts: parts[-1]["attempted_at"])[-3:]
    items = []
    for parts in quizzes:
        a = parts[-1]
        if len(parts) == 1:
            text = f"Scored {a['score_pct']:.0f}% on a {a['difficulty']} {a['topic']} quiz"
            items.append(Activity(utc(a["attempted_at"]), text, a["topic"]))
            continue
        total = sum(_field(p, "total", 0) or 0 for p in parts)
        correct = sum(_field(p, "correct", 0) or 0 for p in parts)
        topics = list(dict.fromkeys(p["topic"] for p in parts))
        pct = 100 * correct / total if total else 0
        named = ", ".join(topics[:3]) + (f" and {len(topics) - 3} more" if len(topics) > 3 else "")
        text = f"Scored {pct:.0f}% on a {total}-question quiz: {named}"
        items.append(
            Activity(utc(a["attempted_at"]), text, topics[0] if len(topics) == 1 else None)
        )
    items += [
        Activity(
            utc(s["started"]),
            f"Averaged {s['avg_overall']:.1f}/5 in a {s['interview_type']} interview",
        )
        for s in sessions[-2:]
    ]
    if latest_plan:
        items.append(
            Activity(utc(latest_plan["created_at"]), f"Planned week {latest_plan['week_no']}")
        )
    return sorted(items, key=lambda i: i.at, reverse=True)[:4]


def home(
    student_id: str, profile: StudentProfile | None = None, now: datetime | None = None
) -> HomeOverview:
    """Everything the Home page shows, read in five queries."""
    profile = profile or _require_profile(student_id)
    try:
        latest = db.latest_plan(student_id)
        attempts = db.quiz_history(student_id)
        sessions = db.interview_history(student_id)
        scores = db.topic_performance(student_id)
    except sqlite3.Error as e:
        raise ServiceError(
            "Your progress could not be read. Reload the page, and restart the app if it "
            "keeps failing."
        ) from e
    weakness = weakness_for(profile, scores)
    action = decide_next_action(
        profile, latest, weakness, attempts, len(sessions), now or datetime.now(UTC)
    )
    return HomeOverview(
        profile=profile,
        weakness=weakness,
        next_action=action,
        checklist=_checklist(profile, latest, len(attempts), len(sessions)),
        recent=_recent(latest, attempts, sessions),
        streak=study_streak(attempts, sessions),
        week_done=(latest["week_no"], latest["days_done"]) if latest else None,
    )


def next_action(student_id: str | None) -> NextAction:
    """Today's focus for this student; see decide_next_action."""
    profile = current_profile(student_id)
    if profile is None:
        return decide_next_action(None, None, {}, [], 0, datetime.now(UTC))
    return home(student_id, profile).next_action


# --- resume builder: versions, domain lock and what to add next ---------------------


@dataclass(frozen=True)
class ResumeVersion:
    n: int  # from 1
    created_at: str  # UTC
    domain_id: str
    target_role: str
    resume: dict
    ats_score: int


def resume_history(student_id: str | None) -> list[ResumeVersion]:
    if not student_id:
        return []
    return [
        ResumeVersion(
            i, v["created_at"], v["domain_id"], v["target_role"], v["resume"], v["ats_score"]
        )
        for i, v in enumerate(db.resume_versions(student_id), 1)
    ]


def save_resume(
    student_id: str | None,
    domain_id: str,
    resume: dict,
    on_event: OnEvent | None = None,
) -> tuple[str, int]:
    """Save a built resume as the student's next version and re-profile them from it (their
    readiness follows the resume). Without a student, a new one is created from it. The
    first version locks the domain. Returns (student id, version number)."""
    role = resume.get("target_role", "")
    if role not in domain_roles(domain_id):
        raise ServiceError(f"{role!r} is not a role in this domain.")
    if not str(resume.get("full_name", "")).strip():
        raise ServiceError("Enter your full name.")
    email = str((resume.get("form") or {}).get("email", "")).strip()
    if not EMAIL_RE.match(email):
        raise ServiceError("Enter a valid email address.")
    check_resume_dates(resume)
    text = resume_builder.resume_text(resume)
    if student_id:
        lock = locked_domain(student_id)
        if lock and lock.domain.id != domain_id:
            raise ServiceError(f"Your domain is locked to {lock.domain.name}; choose a role in it.")
        if student_row(student_id) is None:
            raise ServiceError("This student no longer exists.")
        sid, _ = onboard(student_id, role, text, on_event)
    else:
        sid, _ = onboard_candidate(resume["full_name"], role, text, on_event=on_event)
    ats = resume_builder.evaluate_ats_compatibility(resume, role)
    db.save_resume_version(sid, domain_id, role, resume, ats.score)
    return sid, len(db.resume_versions(sid))


def enhance_bullet(text: str, role: str, on_event: OnEvent | None = None) -> str:
    """One resume bullet rewritten in XYZ form by the LLM; numbers are never invented."""
    text = (text or "").strip()
    if len(text) < 5:
        raise ServiceError("Write a few words about what you did first.")
    if len(text) > BULLET_MAX_CHARS:
        raise ServiceError(f"A bullet is limited to {BULLET_MAX_CHARS} characters.")
    if resume_builder.get_role_info(role) is None and role not in syllabus.role_skills():
        raise ServiceError(f"Unknown role {role!r}.")
    return agents.enhance_bullet(text, role, on_event)


def check_resume_dates(resume: Mapping) -> None:
    """Every work date reads as a month and no entry ends before it starts; every education
    year is a year. Raises ServiceError naming the entry."""
    parse = resume_builder.parse_month
    for e in resume_builder.experience_entries(resume):
        name = resume_builder.job_label(e)
        start, end = e.get("start", ""), "" if e.get("current") else e.get("end", "")
        for value in (start, end):
            if value and parse(value) is None:
                raise ServiceError(
                    f"{name}: write dates like 'Jun 2024' or '2024-06' (got {value!r})."
                )
        if not start:
            raise ServiceError(f"{name}: add the month you started.")
        if end and parse(end) < parse(start):
            raise ServiceError(f"{name}: the end date is before the start date.")
    for e in resume_builder.education_entries(resume):
        for value in (e.get("start", ""), e.get("end", "")):
            if value and not re.fullmatch(r"(19|20)\d\d", str(value).strip()):
                raise ServiceError(
                    f"{degrees.entry_label(e)}: write years as four digits, e.g. 2026."
                )
        if e.get("start") and e.get("end") and int(e["end"]) < int(e["start"]):
            raise ServiceError(f"{degrees.entry_label(e)}: the end year is before the start.")


DEGREE_STATUSES = degrees.STATUSES


def degree_codes() -> list[str]:
    """Every qualification a student can list, lowest level first."""
    return degrees.codes()


def degree_label(code: str) -> str:
    return degrees.label(code)


def roles_for_degree(code: str, specialization: str, status: str) -> list[degrees.RoleFit]:
    """Catalog roles one degree qualifies for (completed: now; pursuing: on completion)."""
    if code not in degrees.codes():
        raise ServiceError(f"Unknown degree {code!r}.")
    if status not in degrees.STATUSES:
        raise ServiceError(f"Status must be one of {', '.join(degrees.STATUSES)}.")
    entry = {"degree": code, "specialization": specialization.strip(), "status": status}
    return degrees.roles_for([entry])


def education_from_text(text: str) -> dict:
    """A form entry from a free-text education line (the profile's): the degree it names and
    the branch after "in", or the whole line as an "Other" qualification."""
    d = degrees.parse(text)
    if d is None:
        return {"degree": "Other", "specialization": text.strip(), "status": "Completed"}
    m = re.search(r"\bin\s+([^,(|;]+)", text)
    return {"degree": d.code, "specialization": m[1].strip() if m else "", "status": "Completed"}


@dataclass(frozen=True)
class MasteredTopic:
    topic: str
    pct: float  # recent quiz average
    quizzes: int
    skills: list[str]  # the role's skills under this topic that the resume does not show


@dataclass(frozen=True)
class ResumeAdvice:
    """What to put on the resume next, from evidence: quiz mastery, finished projects, the
    role's keywords still missing, and how long since the last version."""

    last_saved: datetime | None
    review_on: date | None  # the last version's day plus RESUME_REVIEW_DAYS
    quizzes_since: int
    plan_days_since: int
    mastered: list[MasteredTopic]
    missing_keywords: list[str]
    projects_to_add: list[str]

    def due(self, today: date) -> bool:
        return self.review_on is not None and today >= self.review_on


def resume_advice(student_id: str, profile: StudentProfile | None = None) -> ResumeAdvice:
    profile = profile or _require_profile(student_id)
    versions = resume_history(student_id)
    latest = versions[-1] if versions else None
    if latest:
        on_resume = {s.lower() for s in latest.resume["skills"]}
    else:
        on_resume = {s.lower() for s in [*profile.skills, *profile.matched_skills]}

    history = db.quiz_history(student_id)
    attempts_by_topic = Counter(a["topic"] for a in history)
    mastered = []
    for topic, pct in db.topic_performance(student_id).items():
        if pct < RESUME_MASTERY_AT or attempts_by_topic[topic] < 2:
            continue
        skills = [
            s
            for s in syllabus.skills_for_topic(profile.target_role, topic)
            if s.lower() not in on_resume
        ]
        if skills:
            mastered.append(MasteredTopic(topic, pct, attempts_by_topic[topic], skills))

    since = latest.created_at if latest else None
    missing = (
        resume_builder.evaluate_ats_compatibility(
            latest.resume, latest.target_role
        ).missing_keywords
        if latest
        else []
    )
    titles = {p["title"].lower() for p in latest.resume["projects"]} if latest else set()
    done = [
        p["name"]
        for p in db.projects(student_id)
        if p["status"] == "Done" and p["name"].lower() not in titles
    ]
    saved = utc(since) if since else None
    local = saved.astimezone(ZoneInfo(TIMEZONE)).date() if saved else None
    return ResumeAdvice(
        last_saved=saved,
        review_on=local + timedelta(days=RESUME_REVIEW_DAYS) if local else None,
        quizzes_since=sum(1 for a in history if since and a["attempted_at"] >= since),
        plan_days_since=db.plan_days_done_since(student_id, since) if since else 0,
        mastered=sorted(mastered, key=lambda m: -m.pct),
        missing_keywords=missing,
        projects_to_add=done,
    )


# --- project space -------------------------------------------------------------------


def has_project_space(profile: StudentProfile | None) -> bool:
    """Computing domains get a Project space (a GitHub-style list of repositories)."""
    return profile is not None and syllabus.domain_of_role(profile.target_role).code_space


@dataclass(frozen=True)
class ProjectSpace:
    projects: list[sqlite3.Row]
    updates: list[sqlite3.Row]  # newest first
    activity: dict[date, int]  # updates per day on the student's calendar


def project_space(student_id: str) -> ProjectSpace:
    updates = db.project_updates(student_id)
    return ProjectSpace(
        db.projects(student_id), updates, dict(activity_days(u["created_at"] for u in updates))
    )


def save_project(
    student_id: str,
    *,
    name: str,
    summary: str = "",
    tech: str = "",
    repo_url: str = "",
    status: str = "In progress",
    readme: str = "",
    on_resume: bool = True,
    project_id: int | None = None,
) -> int:
    name, repo_url = name.strip(), repo_url.strip()
    if not 1 <= len(name) <= 80:
        raise ServiceError("A project needs a name of up to 80 characters.")
    if repo_url and (len(repo_url) > 300 or not URL_RE.match(repo_url)):
        raise ServiceError("The repository link must be a web address starting with https://.")
    if status not in PROJECT_STATUSES:
        raise ServiceError(f"Unknown status {status!r}.")
    if len(summary) > 1500 or len(tech) > 200 or len(readme) > 8000:
        raise ServiceError(
            "Keep highlights under 1,500 characters, the stack under 200 and the README "
            "under 8,000."
        )
    fields = {
        "name": name,
        "summary": summary.strip(),
        "tech": ", ".join(t.strip() for t in tech.split(",") if t.strip()),
        "repo_url": repo_url,
        "status": status,
        "readme": readme.strip(),
        "on_resume": bool(on_resume),
    }
    try:
        return db.save_project(student_id, fields, project_id)
    except sqlite3.IntegrityError as e:
        raise ServiceError(f"You already have a project called {name!r}.") from e


def delete_project(student_id: str, project_id: int) -> None:
    db.delete_project(student_id, project_id)


def log_project_update(student_id: str, project_id: int, note: str) -> None:
    note = note.strip()
    if not 1 <= len(note) <= 300:
        raise ServiceError("Describe the update in up to 300 characters.")
    if not db.add_project_update(student_id, project_id, note):
        raise ServiceError("That project no longer exists.")


def resume_projects(student_id: str | None) -> list[dict]:
    """Projects marked for the resume, as resume projects: each highlight line a bullet."""
    if not student_id:
        return []
    return [
        {
            "title": p["name"],
            "tech": p["tech"],
            "bullets": [ln.strip("-*• ").strip() for ln in p["summary"].splitlines() if ln.strip()],
        }
        for p in db.projects(student_id)
        if p["on_resume"]
    ]


# --- evaluation scorecard --------------------------------------------------------------


def _csv_rows(name: str) -> list[dict]:
    try:
        with (RESULTS_DIR / name).open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def evaluation_scorecard(summary: Mapping | None = None) -> scorecard.Scorecard | None:
    """The last evaluation judged on the advanced parameters (piq/scorecard.py), from
    summary.json and the per-case CSVs run_eval writes next to it."""
    summary = summary if summary is not None else evaluation_summary()
    if summary is None:
        return None
    return scorecard.build(
        summary, _csv_rows("cases.csv"), _csv_rows("questions.csv"), _csv_rows("interviews.csv")
    )
