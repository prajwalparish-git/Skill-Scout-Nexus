"""The agents. Each generation task runs through the critic graph in piq/graph.py.

Agents read inputs and return validated models; they never write domain tables
(callers persist results). They do write agent_logs via piq.llm.
"""

import hashlib
import json
import threading

from piq import checks, llm, prompts, syllabus
from piq.config import (
    DIFFICULTY_DOWN_BELOW,
    DIFFICULTY_UP_AT,
    INTERVIEW_MAX_TURNS,
    QUIZ_SIZE,
)
from piq.graph import OnEvent, Task, run_or_raise
from piq.schemas import (
    AnswerEvaluation,
    BulletRewrite,
    InterviewTurn,
    ProfileExtraction,
    Question,
    QuestionVerdict,
    QuizCritique,
    QuizSet,
    StudentProfile,
    WeeklyPlan,
)


def _feedback(reasons: list[str]) -> str:
    if not reasons:
        return ""
    bullets = "\n".join(f"- {r}" for r in reasons)
    return f"\n\nYour previous attempt was REJECTED for these reasons. Fix all of them:\n{bullets}"


def roles() -> dict[str, dict[str, str | None]]:
    """role -> {required skill -> syllabus topic or null}."""
    return syllabus.role_skills()


def missing_topics(profile: StudentProfile) -> set[str]:
    req = roles().get(profile.target_role, {})
    return {t for s in profile.missing_skills if (t := req.get(s))}


# --- Profile Agent -------------------------------------------------------------


def _profile_gen(inp: dict, reasons: list[str], _prev: object) -> tuple[ProfileExtraction, int]:
    required = list(roles()[inp["target_role"]])
    user = (
        f"Target role: {inp['target_role']}\nRequired skills: {json.dumps(required)}\n\n"
        f"Resume:\n{inp['resume_text'][:12000]}{_feedback(reasons)}"
    )
    ctx = {**inp, "required_skills": required}
    return llm.call(
        ProfileExtraction,
        agent="profile",
        system=prompts.PROFILE,
        user=user,
        context=ctx,
        size="small",
        temperature=0.1,
        student_id=inp.get("student_id"),
    )


PROFILE_TASK = Task(
    "profile",
    _profile_gen,
    lambda inp, out: checks.check_profile(out, list(roles()[inp["target_role"]])),
)


def create_profile(
    resume_text: str,
    target_role: str,
    on_event: OnEvent | None = None,
    student_id: str | None = None,
) -> StudentProfile:
    if target_role not in roles():
        raise ValueError(f"unknown target role {target_role!r}")
    inp = {"resume_text": resume_text, "target_role": target_role, "student_id": student_id}
    ext: ProfileExtraction = run_or_raise(PROFILE_TASK, inp, on_event)
    skill_topics = roles()[target_role]
    required = list(skill_topics)
    canon = {s.lower(): s for s in required}
    claimed = sorted({canon[s.lower()] for s in ext.matched_skills})
    # Strict: a skill counts only if the resume names it (or an alias) in words. The model may
    # infer a skill from context; the student still has to write it for a recruiter or an ATS.
    words, aliases = checks.tokens(resume_text), syllabus.skill_aliases()
    matched = [s for s in claimed if checks.evidenced(s, words, aliases.get(s, ()))]
    unnamed = [s for s in claimed if s not in matched]
    feedback = list(ext.resume_feedback)
    if unnamed:
        feedback = [
            *feedback[:4],
            f"Name {', '.join(unnamed)} in words, inside the project or job where you used "
            "them: the profile counts only skills the resume states.",
        ]
    return StudentProfile(
        **ext.model_dump(exclude={"matched_skills", "resume_feedback"}),
        matched_skills=matched,
        resume_feedback=feedback,
        target_role=target_role,
        missing_skills=[s for s in required if s not in matched],
        readiness_score=checks.readiness_score(skill_topics, matched),
    )


# --- Planner Agent -------------------------------------------------------------


def _planner_gen(inp: dict, reasons: list[str], _prev: object) -> tuple[WeeklyPlan, int]:
    w = inp["weakness"]
    weak = set(checks.weak_topics(w))
    table = "\n".join(
        f"- {t}: weakness {v:.2f}{' WEAK' if t in weak else ''}"
        f"{f', recent quiz avg {inp["scores"][t]}%' if t in inp['scores'] else ', no quiz yet'}"
        for t, v in sorted(w.items(), key=lambda kv: -kv[1])
    )
    prev = inp["previous_minutes"]
    user = (
        f"Week number: {inp['week_no']}\nTarget role: {inp['target_role']}\n"
        f"Missing skills: {', '.join(inp['missing_skills']) or 'none'}\n\n"
        f"Topic weakness:\n{table}\n\n"
        f"Previous week minutes per topic: {json.dumps(prev) if prev else 'none (first week)'}"
        f"{_feedback(reasons)}"
    )
    return llm.call(
        WeeklyPlan,
        agent="planner",
        system=prompts.PLANNER,
        user=user,
        context=inp,
        student_id=inp["student_id"],
        temperature=0.3,
    )


PLANNER_TASK = Task(
    "planner",
    _planner_gen,
    lambda inp, out: checks.check_plan(out, inp["week_no"], inp["weakness"]),
)


def planner_inputs(
    profile: StudentProfile,
    scores: dict[str, float],
    week_no: int,
    previous: WeeklyPlan | None = None,
    student_id: str | None = None,
) -> dict:
    topics = syllabus.tracked_topics(profile.target_role, scores)
    return {
        "student_id": student_id,
        "week_no": week_no,
        "target_role": profile.target_role,
        "missing_skills": profile.missing_skills,
        "scores": {t: s for t, s in scores.items() if t in topics},
        "weakness": checks.topic_weakness(scores, missing_topics(profile), topics),
        "previous_minutes": previous.minutes_by_topic() if previous else None,
    }


def plan_week(
    profile: StudentProfile,
    scores: dict[str, float],
    week_no: int,
    previous: WeeklyPlan | None = None,
    student_id: str | None = None,
    on_event: OnEvent | None = None,
) -> WeeklyPlan:
    inp = planner_inputs(profile, scores, week_no, previous, student_id)
    return run_or_raise(PLANNER_TASK, inp, on_event)


# --- Quiz Agent + LLM critic ---------------------------------------------------


def suggest_difficulty(last_score: float | None, current: str = "medium") -> str:
    order = ["easy", "medium", "hard"]
    if last_score is None:
        return current
    i = order.index(current)
    if last_score >= DIFFICULTY_UP_AT:
        i = min(i + 1, 2)
    elif last_score < DIFFICULTY_DOWN_BELOW:
        i = max(i - 1, 0)
    return order[i]


def _ask_questions(
    inp: dict, count: int, avoid: list[str], note: str, first: bool
) -> tuple[QuizSet, int]:
    existing = "\n".join(f"- {q}" for q in avoid[:20]) or "none"
    area = f"Syllabus area: {inp['area']}\n" if inp.get("area") else ""
    user = (
        f"{area}Topic: {inp['topic']}\nDifficulty: {inp['difficulty']}\n"
        f"Number of questions: {count}\n\n"
        f"Existing questions (do not repeat or paraphrase):\n{existing}{note}"
    )
    return llm.call(
        QuizSet,
        agent="quiz",
        system=prompts.QUIZ,
        user=user,
        context={**inp, "count": count, "previous": avoid, "first_attempt": first},
        student_id=inp["student_id"],
        temperature=0.8,
    )


def _quiz_gen(inp: dict, reasons: list[str], previous: QuizSet | None) -> tuple[QuizSet, int]:
    issues = checks.question_issues(reasons) if previous else None
    if not issues:  # first attempt, or a set-level problem: generate the whole quiz
        return _ask_questions(inp, inp["count"], inp["previous"], _feedback(reasons), not reasons)
    # Only some questions failed: regenerate just those and keep the approved ones.
    bad = sorted(i for i in issues if i < len(previous.questions))
    rejected = "\n".join(f"- {previous.questions[i].text} -> {'; '.join(issues[i])}" for i in bad)
    note = (
        f"\n\nWrite {len(bad)} replacement question(s). These were rejected; "
        f"avoid the same problems:\n{rejected}"
    )
    avoid = [q.text for q in previous.questions] + inp["previous"]
    fresh, log_id = _ask_questions(inp, len(bad), avoid, note, first=False)
    questions = list(previous.questions)
    for i, q in zip(bad, fresh.questions, strict=False):
        questions[i] = q
    return previous.model_copy(update={"questions": questions}), log_id


# Critic verdicts keyed by exact question content: each question is judged once, so a
# retry only pays for the replacements. Shared across sessions (a verdict does not depend
# on the student), bounded, and lock-protected for Streamlit's threads.
_VERDICTS: dict[str, QuestionVerdict] = {}
_VERDICTS_MAX = 2000
_VERDICTS_LOCK = threading.Lock()


def clear_verdict_cache() -> None:
    with _VERDICTS_LOCK:
        _VERDICTS.clear()


def _verdict_key(topic: str, q: Question) -> str:
    raw = json.dumps([topic, q.text, q.options, q.correct_index])
    return hashlib.sha1(raw.encode()).hexdigest()


def _critique(inp: dict, quiz: QuizSet, pending: list[int], keys: list[str]) -> None:
    listing = "\n\n".join(
        f"[{n}] {quiz.questions[i].text}\n"
        + "\n".join(f"  {j}. {o}" for j, o in enumerate(quiz.questions[i].options))
        + f"\n  marked correct: {quiz.questions[i].correct_index}"
        for n, i in enumerate(pending)
    )
    critique, _ = llm.call(
        QuizCritique,
        agent="critic",
        system=prompts.CRITIC,
        user=f"Topic: {quiz.topic}\n\n{listing}",
        context={"count": len(pending)},
        student_id=inp["student_id"],
        temperature=0.0,
    )
    # Use the reply only if its numbering is unambiguous: exactly 0..n-1 or 1..n, each once.
    # A gap, a duplicate or a stray number makes any mapping a guess, and a guessed verdict
    # would be cached against the wrong question; unjudged questions count as rejected.
    indices = [v.index for v in critique.verdicts]
    n = len(pending)
    if len(set(indices)) != len(indices) or set(indices) not in (
        set(range(n)),
        set(range(1, n + 1)),
    ):
        return
    shift = 0 if 0 in indices else 1  # tolerate 1-based numbering
    by_index = {v.index - shift: v for v in critique.verdicts}
    with _VERDICTS_LOCK:
        for n, i in enumerate(pending):
            if (v := by_index.get(n)) is not None:
                _VERDICTS[keys[i]] = v
        while len(_VERDICTS) > _VERDICTS_MAX:
            _VERDICTS.pop(next(iter(_VERDICTS)))


def verify_quiz(inp: dict, quiz: QuizSet) -> list[str]:
    reasons = checks.check_quiz(
        quiz, inp["topic"], inp["difficulty"], inp["count"], inp["previous"]
    )
    if reasons:  # deterministic failures: skip the paid LLM check
        return reasons
    keys = [_verdict_key(quiz.topic, q) for q in quiz.questions]
    with _VERDICTS_LOCK:
        pending = [i for i, k in enumerate(keys) if k not in _VERDICTS]
    if pending:
        _critique(inp, quiz, pending, keys)
    with _VERDICTS_LOCK:
        verdicts = [_VERDICTS.get(k) for k in keys]
    return [
        checks.question_reason(
            i, "the critic gave no verdict" if v is None else v.reason or "invalid"
        )
        for i, v in enumerate(verdicts)
        if v is None or not v.valid
    ]


QUIZ_TASK = Task("quiz", _quiz_gen, verify_quiz)


def quiz_inputs(
    topic: str,
    difficulty: str,
    previous: list[str],
    count: int = QUIZ_SIZE,
    student_id: str | None = None,
    area: str | None = None,
) -> dict:
    """`area`: the domain and role the topic belongs to (e.g. "Electronics & Communication,
    for an Embedded Systems & Firmware Engineer"), so a topic name is read in its field."""
    return {
        "topic": topic,
        "difficulty": difficulty,
        "count": count,
        "previous": previous,
        "student_id": student_id,
        "area": area,
    }


def make_quiz(
    topic: str,
    difficulty: str,
    previous: list[str],
    count: int = QUIZ_SIZE,
    student_id: str | None = None,
    on_event: OnEvent | None = None,
    area: str | None = None,
) -> QuizSet:
    inp = quiz_inputs(topic, difficulty, previous, count, student_id, area)
    return run_or_raise(QUIZ_TASK, inp, on_event)


# --- Interview Agent + answer evaluator ----------------------------------------


def _profile_brief(p: StudentProfile) -> str:
    return (
        f"Candidate: {p.name}; target role: {p.target_role}; education: {p.education}\n"
        f"Skills: {', '.join(p.skills)}\nProjects: {'; '.join(p.projects) or 'none listed'}\n"
        f"Internships: {'; '.join(p.internships) or 'none'}"
    )


def _interview_gen(inp: dict, reasons: list[str], _prev: object) -> tuple[InterviewTurn, int]:
    hist = "\n".join(f"Q: {h['question']}\nA: {h['answer']}" for h in inp["history"]) or "none"
    past = "\n".join(f"Q: {h['question']}\nA: {h['answer'][:300]}" for h in inp["past"][:5])
    user = (
        f"{inp['brief']}\n\nEarlier sessions (memory):\n{past or 'none'}\n\n"
        f"This session so far:\n{hist}\n\n"
        f"Turn {len(inp['history']) + 1} of {inp['max_turns']}.{_feedback(reasons)}"
    )
    system = prompts.INTERVIEWER.format(interview_type=inp["interview_type"])
    if inp.get("focus"):
        system += f"\nThis track covers: {inp['focus']}. Keep every question within it."
    return llm.call(
        InterviewTurn,
        agent="interviewer",
        system=system,
        user=user,
        context=inp,
        student_id=inp["student_id"],
        temperature=0.7,
    )


INTERVIEW_TASK = Task(
    "interviewer", _interview_gen, lambda inp, out: checks.check_turn(out, inp["asked"])
)


def next_question(
    profile: StudentProfile,
    interview_type: str,
    history: list[dict],
    past: list[dict],
    student_id: str | None = None,
    on_event: OnEvent | None = None,
    focus: str = "",
) -> InterviewTurn:
    """`focus`: what a domain interview track covers (data/interview_tracks.json)."""
    inp = {
        "brief": _profile_brief(profile),
        "interview_type": interview_type,
        "focus": focus,
        "history": history,
        "past": past,
        "asked": [h["question"] for h in history + past],
        "max_turns": INTERVIEW_MAX_TURNS,
        "student_id": student_id,
    }
    turn: InterviewTurn = run_or_raise(INTERVIEW_TASK, inp, on_event)
    # Turn bookkeeping is a fact, not a judgment: enforce it in code.
    return turn.model_copy(
        update={
            "is_followup": turn.is_followup and bool(history),
            "is_final": turn.is_final or len(history) + 1 >= INTERVIEW_MAX_TURNS,
        }
    )


def evaluate_answer(
    profile: StudentProfile,
    interview_type: str,
    question: str,
    answer: str,
    student_id: str | None = None,
) -> AnswerEvaluation:
    user = (
        f"{_profile_brief(profile)}\nInterview type: {interview_type}\n\n"
        f"Question: {question}\nAnswer: {answer}"
    )
    ev, _ = llm.call(
        AnswerEvaluation,
        agent="evaluator",
        system=prompts.EVALUATOR,
        user=user,
        context={"question": question, "answer": answer},
        student_id=student_id,
        temperature=0.2,
    )
    return ev


# --- Resume bullet polish -------------------------------------------------------------


def _bullet_gen(inp: dict, reasons: list[str], _prev: object) -> tuple[BulletRewrite, int]:
    user = f"Target role: {inp['role']}\nOriginal bullet: {inp['text']}{_feedback(reasons)}"
    return llm.call(
        BulletRewrite,
        agent="bullet",
        system=prompts.BULLET,
        user=user,
        context=inp,
        size="small",
        temperature=0.3,
        student_id=inp.get("student_id"),
    )


BULLET_TASK = Task(
    "bullet", _bullet_gen, lambda inp, out: checks.check_bullet(inp["text"], out.bullet)
)


def enhance_bullet(
    text: str, role: str, on_event: OnEvent | None = None, student_id: str | None = None
) -> str:
    """One bullet in XYZ form, with no number the student did not write."""
    inp = {"text": text, "role": role, "student_id": student_id}
    out: BulletRewrite = run_or_raise(BULLET_TASK, inp, on_event)
    return out.bullet.strip().lstrip("-*• ").strip()
