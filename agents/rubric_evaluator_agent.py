"""Rubric Evaluator Agent for Skill Scout Nexus (Step 5 Voice Interview Architecture).

Responsibilities:
- Transcribes student audio responses (via Groq Whisper API or direct text transcription).
- Evaluates candidate answers using the standardized 0-15 point rubric:
    1. Content Knowledge & Technical Relevancy (0-5 points)
    2. Verbal Clarity & Structure (STAR format) (0-5 points)
    3. Confidence & Professional Demeanor (0-5 points)
- Detects and flags suspicious gaps:
    - Long silence duration or excessively terse replies
    - Off-topic hallucinations or deflection
    - Keyword stuffing without substantive logical progression
- Returns detailed structured feedback and concrete actionable suggestions for improvement.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from core import transcribe_router
from piq import llm
from piq.config import settings

log = logging.getLogger("agents.rubric_evaluator_agent")


class RubricBreakdown(BaseModel):
    content_knowledge: int = Field(
        ge=0, le=5, description="Technical accuracy, factual depth, domain correctness (0-5)"
    )
    verbal_clarity_star: int = Field(
        ge=0, le=5, description="Structure, logical coherence, STAR format adherence (0-5)"
    )
    confidence_demeanor: int = Field(
        ge=0, le=5, description="Delivery confidence, articulate tone, professional demeanor (0-5)"
    )
    total_score: int = Field(ge=0, le=15, description="Combined score out of 15")


class SuspiciousGapFlags(BaseModel):
    excessive_silence_or_terse: bool = Field(
        default=False,
        description="Response is unusually brief (< 20 words) or contains empty pauses",
    )
    off_topic_hallucination: bool = Field(
        default=False, description="Candidate deflected or talked about unrelated topics"
    )
    keyword_stuffing_without_depth: bool = Field(
        default=False, description="Repeated buzzwords without explaining mechanisms or metrics"
    )
    flag_details: list[str] = Field(default_factory=list, description="Specific warnings flagged")


class RubricEvaluationResult(BaseModel):
    question_asked: str
    transcribed_response: str
    rubric: RubricBreakdown
    performance_tier: Literal["Excellent", "Proficient", "Needs Improvement", "Unsatisfactory"]
    strengths: list[str] = Field(min_length=1, description="Tangible strengths demonstrated")
    areas_for_improvement: list[str] = Field(
        min_length=1, description="Actionable points to improve score"
    )
    exemplary_model_answer: str = Field(description="High-scoring model response in STAR format")
    gap_flags: SuspiciousGapFlags = Field(default_factory=SuspiciousGapFlags)


def transcribe_audio_with_whisper(
    audio_bytes: bytes,
    filename: str = "response.wav",
    api_key: str | None = None,
) -> str:
    """Transcribes audio: Groq Whisper, then Gemini, then faster-whisper on this machine
    (offline). Returns "" when none can (the student types instead). core/transcribe_router.py
    holds the tiers; the name is kept for its callers.
    """
    cfg = settings()
    if not audio_bytes:
        return ""
    if cfg.mock_mode:
        log.info("Transcription: mock mode returns a canned answer.")
        return (
            "In our previous project, I led the migration of our monolithic checkout system "
            "to asynchronous message queues. When traffic surged, the database previously locked "
            "up. "
            "I introduced Redis caching and a RabbitMQ worker pool, which stabilized response "
            "times "
            "under 120 milliseconds with zero dropped orders."
        )
    result = transcribe_router.transcribe(audio_bytes, filename, api_key=api_key)
    if not result.text:
        log.info("No transcriber answered (%s); the student types instead.", result.detail)
    return result.text


def _detect_suspicious_gaps(question: str, answer_text: str) -> SuspiciousGapFlags:
    """Heuristic rule-based check for silence, brevity, and blatant off-topic deflection."""
    words = re.findall(r"\b\w+\b", answer_text.lower())
    flags: list[str] = []

    # 1. Brevity / Terse flag
    is_terse = len(words) < 22
    if is_terse:
        flags.append(f"Answer is very brief ({len(words)} words); lacked technical elaboration.")

    # 2. Vague filler / deflection
    vague_phrases = ["i don't know", "no idea", "not sure", "pass", "skip question", "whatever"]
    deflected = any(p in answer_text.lower() for p in vague_phrases) and len(words) < 30
    if deflected:
        flags.append("Candidate explicitly passed or gave non-substantive filler.")

    # 3. Off-topic check (question keywords vs answer)
    q_words = {
        w
        for w in re.findall(r"\b\w{4,}\b", question.lower())
        if w not in {"what", "how", "would", "your", "tell", "time"}
    }
    a_words = set(words)
    overlap = q_words.intersection(a_words)
    is_off_topic = len(overlap) == 0 and len(words) >= 15
    if is_off_topic:
        flags.append("Answer shares almost zero core topic vocabulary with the interview question.")

    # 4. Keyword stuffing check (same word repeated > 10% of total words)
    from collections import Counter

    counts = Counter(words)
    stuffing = any(
        count > 6 and (count / len(words)) > 0.12 for w, count in counts.items() if len(w) > 3
    )
    if stuffing:
        flags.append("Repetitive keyword clustering detected without progressive STAR structure.")

    return SuspiciousGapFlags(
        excessive_silence_or_terse=is_terse,
        off_topic_hallucination=is_off_topic or deflected,
        keyword_stuffing_without_depth=stuffing,
        flag_details=flags,
    )


class _RawRubricPayload(BaseModel):
    content_knowledge: int = Field(ge=0, le=5)
    verbal_clarity_star: int = Field(ge=0, le=5)
    confidence_demeanor: int = Field(ge=0, le=5)
    strengths: list[str] = Field(min_length=1)
    areas_for_improvement: list[str] = Field(min_length=1)
    exemplary_model_answer: str


def _heuristic_evaluation(
    question: str, answer_text: str, gap_flags: SuspiciousGapFlags
) -> RubricEvaluationResult:
    """Deterministic 0-15 scoring from length, STAR markers and the gap flags: mock mode, and
    the fallback when no AI provider can evaluate."""
    word_count = len(answer_text.split())
    c_score = 4 if word_count > 40 else (3 if word_count > 20 else 2)
    s_score = (
        4
        if any(
            star in answer_text.lower() for star in ["because", "result", "then", "led", "impact"]
        )
        else 3
    )
    d_score = 4 if not gap_flags.excessive_silence_or_terse else 2
    total = c_score + s_score + d_score

    tier: Literal["Excellent", "Proficient", "Needs Improvement", "Unsatisfactory"] = (
        "Excellent" if total >= 13 else ("Proficient" if total >= 10 else "Needs Improvement")
    )

    return RubricEvaluationResult(
        question_asked=question,
        transcribed_response=answer_text,
        rubric=RubricBreakdown(
            content_knowledge=c_score,
            verbal_clarity_star=s_score,
            confidence_demeanor=d_score,
            total_score=total,
        ),
        performance_tier=tier,
        strengths=[
            "Addressed the core scenario directly with relevant domain terminology.",
            "Demonstrated clear understanding of operational constraints.",
        ],
        areas_for_improvement=[
            "Explicitly quantify measurable business or technical outcomes (metrics, % "
            "latency reduction, ROI).",
            "Strictly follow the STAR framework (Situation -> Task -> Action -> Result).",
        ],
        exemplary_model_answer=(
            "In my previous project [Situation], we faced a similar challenge [Task]. "
            "I engineered an automated mitigation pipeline and verified input edge cases "
            "[Action]. "
            "As a result, system uptime remained at 99.98% with zero compliance violations "
            "[Result]."
        ),
        gap_flags=gap_flags,
    )


def evaluate_rubric_answer(
    question: str,
    answer_text: str,
    stream: str = "Engineering",
    target_role: str = "Software Engineer",
    student_id: str | None = None,
) -> RubricEvaluationResult:
    """Evaluates an interview response using the 0-15 point rubric.

    Args:
        question: The interview question asked.
        answer_text: Candidate's transcribed or typed answer.
        stream: Student stream (Engineering, Commerce, Law, Management).
        target_role: Target career role.
        student_id: Optional tracking identifier.

    Returns:
        RubricEvaluationResult with 0-15 breakdown, flags, and model answer.
    """
    cfg = settings()
    gap_flags = _detect_suspicious_gaps(question, answer_text)

    # Mock mode: the deterministic evaluator. Live: the AI router picks a provider.
    if cfg.mock_mode:
        return _heuristic_evaluation(question, answer_text, gap_flags)

    # LLM Evaluator Call
    system_prompt = (
        "You are an elite executive interviewer and campus placement evaluator. "
        "Score the candidate's interview response against a standardized 0-15 rubric:\n"
        "- Content Knowledge & Technical Relevancy (0-5 points): Depth of facts, domain accuracy.\n"
        "- Verbal Clarity & Structure (STAR format) (0-5 points): "
        "Situation, Task, Action, Result coherence.\n"
        "- Confidence & Professional Demeanor (0-5 points): "
        "Articulate phrasing, composure, professional tone.\n\n"
        "Provide constructive strengths, concrete areas for improvement, and a concise 80-120 "
        "word model answer."
    )

    user_prompt = (
        f"Stream: {stream} | Role: {target_role}\n"
        f"Interview Question: {question}\n\n"
        f"Candidate Answer:\n{answer_text}\n\n"
        "Evaluate strictly and output a _RawRubricPayload."
    )

    try:
        raw, _ = llm.call(
            _RawRubricPayload,
            agent="evaluator",
            system=system_prompt,
            user=user_prompt,
            context={"role": target_role, "stream": stream},
            student_id=student_id,
            size="small",
            temperature=0.2,
        )

        total = raw.content_knowledge + raw.verbal_clarity_star + raw.confidence_demeanor
        tier_val: Literal["Excellent", "Proficient", "Needs Improvement", "Unsatisfactory"] = (
            "Excellent"
            if total >= 13
            else (
                "Proficient"
                if total >= 10
                else ("Needs Improvement" if total >= 7 else "Unsatisfactory")
            )
        )

        return RubricEvaluationResult(
            question_asked=question,
            transcribed_response=answer_text,
            rubric=RubricBreakdown(
                content_knowledge=raw.content_knowledge,
                verbal_clarity_star=raw.verbal_clarity_star,
                confidence_demeanor=raw.confidence_demeanor,
                total_score=total,
            ),
            performance_tier=tier_val,
            strengths=raw.strengths,
            areas_for_improvement=raw.areas_for_improvement,
            exemplary_model_answer=raw.exemplary_model_answer,
            gap_flags=gap_flags,
        )
    except Exception as e:
        log.warning("LLM Rubric evaluation failed, using fallback evaluator: %s", e)
        # The heuristic, not this function again: a second LLM failure would recurse forever.
        return _heuristic_evaluation(question, answer_text, gap_flags)
