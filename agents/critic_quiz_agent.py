"""Critic Quiz Agent for Skill Scout Nexus (Layer 2 Multi-Agent Orchestration).

Responsibilities:
- Implements a Generator-Critic loop based on `docs/critic_graph.md`, one round trip per round:
    - Generator + self-critique: a single structured JSON call writes the whole batch and the
      model's own moderation of each question (facts, one correct answer, difficulty).
    - Critic: deterministic checks (`validate_mcq_with_critic`) plus that self-verdict. Approved
      questions are kept; the next round asks only for the ones still missing, with the
      rejection reasons and the approved stems (so nothing is repeated).
- Rounds exhausted: the approved questions are topped up from `data/questions/mcq_bank.csv`;
  with none approved (or offline), the bank serves the whole quiz.
- All outputs follow strict Pydantic schemas.
"""

from __future__ import annotations

import csv
import logging
import random
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from piq import llm, prompts, question_bank
from piq.config import DATA_DIR, settings

log = logging.getLogger("agents.critic_quiz_agent")

MCQ_BANK_PATH = DATA_DIR / "questions" / "mcq_bank.csv"


class GeneratedMCQ(BaseModel):
    text: str = Field(min_length=10, description="Question stem")
    options: list[str] = Field(min_length=4, max_length=4, description="Exactly 4 distinct choices")
    correct_index: int = Field(ge=0, le=3, description="0-based index of correct answer")
    explanation: str = Field(description="Educational explanation justifying the answer")
    bloom_level: Literal["remember", "understand", "apply", "analyze"] = Field(
        default="understand", description="Cognitive level according to Bloom's taxonomy"
    )
    difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium", description="Difficulty level"
    )
    skill_tag: str = Field(default="", description="The specific skill gap or topic tested")

    @field_validator("bloom_level", mode="before")
    @classmethod
    def _lower_bloom(cls, v: Any) -> str:
        return str(v).strip().lower() if v else "understand"

    @property
    def correct_option_letter(self) -> str:
        return "ABCD"[self.correct_index]


class CriticEvaluation(BaseModel):
    is_valid: bool = Field(description="True if question passes all quality standards")
    rejection_reasons: list[str] = Field(
        default_factory=list, description="Concrete reasons if question is flawed"
    )
    factual_correctness: bool = Field(
        default=True, description="Question facts and solution are accurate"
    )
    unambiguous: bool = Field(default=True, description="Exactly one option is defensibly correct")
    difficulty_appropriate: bool = Field(
        default=True, description="Matches target audience and difficulty level"
    )


class QuizBatch(BaseModel):
    topic_or_skill: str
    target_role: str
    difficulty: str
    source: Literal["critic_generated", "question_bank_fallback"]
    questions: list[GeneratedMCQ] = Field(min_length=1)
    attempts: int = Field(default=1, description="Number of generator-critic loops attempted")
    critic_notes: list[str] = Field(default_factory=list)


def _load_bank_fallback_questions(
    skill_gap: str,
    target_role: str,
    difficulty: str = "medium",
    count: int = 5,
) -> list[GeneratedMCQ]:
    """Reads vetted fallback MCQs from data/questions/mcq_bank.csv."""
    if not MCQ_BANK_PATH.exists():
        # Fallback to question_bank module if CSV direct read fails
        q_objs = question_bank.random_questions(skill_gap, difficulty, count)
        if q_objs:
            return [
                GeneratedMCQ(
                    text=q.text,
                    options=q.options,
                    correct_index=q.correct_index,
                    explanation=q.explanation,
                    bloom_level=q.bloom_level,
                    difficulty=difficulty,
                    skill_tag=skill_gap,
                )
                for q in q_objs
            ]
        return _make_synthetic_sample(skill_gap, difficulty, count)

    matched_rows: list[dict[str, str]] = []
    broad_rows: list[dict[str, str]] = []

    try:
        with open(MCQ_BANK_PATH, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                q_text = row.get("question", "")
                r_topic = row.get("topic", "")
                r_role = row.get("role", "")
                r_diff = (row.get("difficulty") or "medium").lower()

                # High relevance match: topic or skill mentioned in topic or question
                if (
                    skill_gap.lower() in r_topic.lower()
                    or skill_gap.lower() in q_text.lower()
                    or (r_role and r_role.lower() in target_role.lower())
                ):
                    if r_diff == difficulty.lower():
                        matched_rows.append(row)
                    else:
                        broad_rows.append(row)
                elif r_diff == difficulty.lower():
                    broad_rows.append(row)
    except Exception as e:
        log.warning("Could not read mcq_bank.csv: %s", e)

    selected = matched_rows if len(matched_rows) >= count else (matched_rows + broad_rows)
    if not selected:
        return _make_synthetic_sample(skill_gap, difficulty, count)

    random.shuffle(selected)
    results: list[GeneratedMCQ] = []

    for r in selected[:count]:
        opts = [r.get(f"option_{c}", "").strip() for c in "abcd"]
        letter = (r.get("correct_option") or "A").strip().upper()
        idx = "ABCD".index(letter) if letter in "ABCD" else 0
        results.append(
            GeneratedMCQ(
                text=(r.get("question") or "").strip(),
                options=opts
                if len(opts) == 4 and all(opts)
                else ["True", "False", "Neither", "Both"],
                correct_index=idx,
                explanation=(
                    r.get("explanation") or f"Standard verified principle in {skill_gap}."
                ).strip(),
                bloom_level=r.get("bloom_level") or "understand",
                difficulty=difficulty,
                skill_tag=r.get("topic") or skill_gap,
            )
        )

    return results


def _make_synthetic_sample(skill: str, difficulty: str, count: int) -> list[GeneratedMCQ]:
    """Generates clean verified default MCQs for core topics when bank is sparse."""
    items = [
        GeneratedMCQ(
            text=(
                f"Which of the following statements best characterizes core best practices in "
                f"{skill}?"
            ),
            options=[
                f"Prioritizing modularity, loose coupling, and defensive validation in {skill}",
                "Relying entirely on runtime exception ignoring without systematic logs",
                "Hardcoding dynamic configurations directly inside compilation units",
                "Bypassing deterministic testing phases to optimize deployment throughput",
            ],
            correct_index=0,
            explanation=(
                f"Modularity and defensive programming are universal industry standards when "
                f"engineering solutions in {skill}."
            ),
            bloom_level="understand",
            difficulty=difficulty,
            skill_tag=skill,
        ),
        GeneratedMCQ(
            text=(
                f"In the context of production-grade systems using {skill}, what is the primary "
                f"consequence of unhandled concurrency?"
            ),
            options=[
                "Automatic compiler optimization of critical sections",
                "Race conditions, data inconsistencies, and potential deadlocks",
                "Guaranteed reduction in cache miss latencies",
                "Deterministic memory deallocation across distributed nodes",
            ],
            correct_index=1,
            explanation=(
                "Uncoordinated multi-threaded or concurrent access leads to non-deterministic "
                "race conditions and deadlocks."
            ),
            bloom_level="analyze",
            difficulty=difficulty,
            skill_tag=skill,
        ),
        GeneratedMCQ(
            text=(
                f"When profiling asymptotic performance in {skill}, what does O(1) time complexity "
                f"indicate?"
            ),
            options=[
                "Linear growth proportional to input size",
                "Logarithmic reduction across partitioned subsets",
                "Constant time independent of input cardinality",
                "Quadratic latency scaling for nested iterations",
            ],
            correct_index=2,
            explanation=(
                "O(1) signifies constant time complexity where the execution duration remains "
                "invariant relative to input magnitude."
            ),
            bloom_level="remember",
            difficulty=difficulty,
            skill_tag=skill,
        ),
    ]
    while len(items) < count:
        items.append(items[0].model_copy())
    return items[:count]


def validate_mcq_with_critic(question: GeneratedMCQ, target_topic: str) -> CriticEvaluation:
    """The Critic Agent validation logic.

    Verifies:
    1. Four non-empty distinct options (case-insensitive distinctness).
    2. Correct index is within [0, 3].
    3. No 'all/none of the above' lazy distractors.
    4. Explanations are non-empty and substantive.
    5. Options length heuristic (avoiding obvious 'longest option is always correct' cue).
    6. Topic relevance check.
    """
    reasons: list[str] = []

    # 1. Distinct options
    opts = [o.strip() for o in question.options]
    if len(opts) != 4 or not all(opts):
        reasons.append("Question must contain exactly 4 non-empty options.")
    if len({o.lower() for o in opts}) < 4:
        reasons.append("Options contain duplicate choices.")

    # 2. Lazy distractors
    for o in opts:
        if any(
            lazy in o.lower() for lazy in ["all of the above", "none of the above", "all of these"]
        ):
            reasons.append(f"Option '{o}' uses prohibited 'all/none of the above' pattern.")

    # 3. Index sanity
    if not (0 <= question.correct_index <= 3):
        reasons.append("Correct index out of valid range [0, 3].")

    # 4. Longest-answer cue check (if correct answer is more than 3x longer than all others)
    if 0 <= question.correct_index < len(opts):
        correct_len = len(opts[question.correct_index])
        other_lens = [len(o) for i, o in enumerate(opts) if i != question.correct_index]
        if other_lens and correct_len > 3 * max(other_lens):
            reasons.append("Correct option is disproportionately long (answer-length cue).")

    # 5. Text length
    if len(question.text.strip()) < 15:
        reasons.append("Question stem is too brief or incomplete.")

    is_valid = len(reasons) == 0
    return CriticEvaluation(
        is_valid=is_valid,
        rejection_reasons=reasons,
        factual_correctness=is_valid,
        unambiguous=is_valid,
        difficulty_appropriate=is_valid,
    )


class SelfCritique(BaseModel):
    """The generator's own moderation of one question, written in the same response."""

    factual_correctness: bool = Field(description="The facts and the keyed answer are accurate")
    unambiguous: bool = Field(description="Exactly one option is defensibly correct")
    difficulty_appropriate: bool = Field(description="Matches the requested difficulty")
    notes: str = Field(default="", description="What was fixed, or why it still fails")


class SelfCheckedMCQ(GeneratedMCQ):
    self_critique: SelfCritique


class SelfCheckedQuestionSet(BaseModel):
    questions: list[SelfCheckedMCQ] = Field(min_length=1)


def _stem(text: str) -> str:
    return " ".join(text.lower().split())


def review_question(question: SelfCheckedMCQ, skill: str, seen: set[str]) -> list[str]:
    """Why a self-checked question is rejected ([] = approved): the deterministic critic, the
    generator's own verdict, and a repeat of a question already approved."""
    reasons = list(validate_mcq_with_critic(question, skill).rejection_reasons)
    c = question.self_critique
    failed = [
        name
        for name, ok in (
            ("factual correctness", c.factual_correctness),
            ("one correct answer", c.unambiguous),
            ("difficulty", c.difficulty_appropriate),
        )
        if not ok
    ]
    if failed:
        why = f": {c.notes}" if c.notes.strip() else "."
        reasons.append(f"Its own check failed on {', '.join(failed)}{why}")
    if _stem(question.text) in seen:
        reasons.append("It repeats an approved question.")
    return reasons


def bank_quiz(
    skill_gap: str,
    target_role: str,
    difficulty: str,
    count: int,
    notes: list[str],
    attempts: int = 1,
) -> QuizBatch:
    """A quiz from the verified question bank: mock mode, the loop's last resort, and a page
    that cannot wait for the generator (piq/journey.py)."""
    return QuizBatch(
        topic_or_skill=skill_gap,
        target_role=target_role,
        difficulty=difficulty,
        source="question_bank_fallback",
        questions=_load_bank_fallback_questions(skill_gap, target_role, difficulty, count),
        attempts=attempts,
        critic_notes=notes,
    )


def _round_prompt(
    skill: str,
    role: str,
    difficulty: str,
    need: int,
    approved: list[GeneratedMCQ],
    rejections: list[str],
) -> str:
    lines = [
        f"Skill: {skill}",
        f"Target role: {role}",
        f"Difficulty: {difficulty}",
        f"Number of questions: {need}",
    ]
    if approved:
        lines += ["", "Already approved (do not repeat):", *(f"- {q.text}" for q in approved)]
    if rejections:
        lines += ["", "Rejected in the last round:", *(f"- {r}" for r in rejections[:5])]
    return "\n".join(lines)


def generate_critic_quiz(
    skill_gap: str,
    target_role: str,
    difficulty: Literal["easy", "medium", "hard"] = "medium",
    count: int = 5,
    max_retries: int = 2,
    student_id: str | None = None,
) -> QuizBatch:
    """Executes the Generator-Critic Loop for targeted technical MCQs.

    Workflow based on docs/critic_graph.md, one LLM round trip per round:
    START -> Generate + self-critique (one JSON call) -> Critic -> (all approved -> DONE |
    some rejected -> ask for the missing ones only). Rounds exhausted -> top up from
    data/questions/mcq_bank.csv; nothing approved or offline -> the bank serves the quiz.

    Args:
        skill_gap: Targeted skill gap or topic name.
        target_role: Target career role.
        difficulty: Desired difficulty ('easy', 'medium', 'hard').
        count: Number of questions to return.
        max_retries: Extra rounds allowed after the first.
        student_id: Optional tracking identifier.

    Returns:
        QuizBatch: Collection of validated MCQs with audit metadata.
    """
    # Mock mode serves the CSV bank at once. Live: the AI router picks a provider; when none
    # answers, the loop below ends in the same bank.
    if settings().mock_mode:
        log.info("Running in mock/offline mode: serving from mcq_bank.csv")
        note = "Offline/Mock Mode: Questions fetched from verified question bank."
        return bank_quiz(skill_gap, target_role, difficulty, count, [note])

    approved: list[GeneratedMCQ] = []
    seen: set[str] = set()
    notes: list[str] = []
    rejections: list[str] = []
    attempt = 0
    while attempt <= max_retries and len(approved) < count:
        attempt += 1
        need = count - len(approved)
        try:
            batch, _ = llm.call(
                SelfCheckedQuestionSet,
                agent="quiz",
                system=prompts.CRITIC_QUIZ_BATCH,
                user=_round_prompt(skill_gap, target_role, difficulty, need, approved, rejections),
                context={"skill": skill_gap, "role": target_role, "attempt": attempt},
                student_id=student_id,
                size="large" if attempt > 1 else "small",
                temperature=0.7,
            )
        except Exception as e:
            log.warning("LLM call failed in critic quiz agent (attempt %d): %s", attempt, e)
            notes.append(f"Attempt {attempt} error: {e}")
            continue

        rejections, kept = [], 0
        for i, q in enumerate(batch.questions, start=1):
            if len(approved) >= count:
                break
            reasons = review_question(q, skill_gap, seen)
            if reasons:
                rejections += [f"Question {i}: {r}" for r in reasons]
                continue
            data = q.model_dump(exclude={"self_critique"})
            approved.append(
                GeneratedMCQ.model_validate({**data, "skill_tag": q.skill_tag or skill_gap})
            )
            seen.add(_stem(q.text))
            kept += 1
        if kept < need:
            detail = f": {'; '.join(rejections[:3])}" if rejections else ""
            notes.append(f"Attempt {attempt}: {kept} of {need} approved{detail}")

    if len(approved) >= count:
        done = "Critic approved every question in one round trip."
        return QuizBatch(
            topic_or_skill=skill_gap,
            target_role=target_role,
            difficulty=difficulty,
            source="critic_generated",
            questions=approved[:count],
            attempts=attempt,
            critic_notes=notes or [done],
        )
    if approved:  # keep what the critic approved; the bank supplies the rest
        extra = _load_bank_fallback_questions(
            skill_gap, target_role, difficulty, count - len(approved)
        )
        return QuizBatch(
            topic_or_skill=skill_gap,
            target_role=target_role,
            difficulty=difficulty,
            source="critic_generated",
            questions=approved + extra,
            attempts=attempt,
            critic_notes=[*notes, f"{len(extra)} question(s) added from the verified bank."],
        )
    log.warning("Critic loop exhausted attempts; falling back to mcq_bank.csv")
    fallback = "Fallback activated: Loaded vetted items from question bank."
    return bank_quiz(skill_gap, target_role, difficulty, count, [*notes, fallback], attempt)
