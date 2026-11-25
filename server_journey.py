"""Placement journey and evaluation HTTP API (Next.js frontend).

Thin FastAPI router over piq/journey.py and piq/services.py (evaluation_summary).
Connects resume scanning, 7-day study roadmaps, critic-checked quizzes,
proctored voice assessments, and benchmark evaluation results.
"""

import base64
import logging
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from agents.critic_quiz_agent import QuizBatch
from agents.voice_interview_agent import Category, VoiceInterviewQuestion
from piq import journey, proctoring, services, syllabus
from piq.config import (
    CRITIC_QUIZ_DEFAULT,
    CRITIC_QUIZ_DEFAULT_DIFFICULTY,
    CRITIC_QUIZ_SIZES,
    DIFFICULTIES,
    RESUME_MAX_BYTES,
    VOICE_DEFAULT_CATEGORY,
    VOICE_RUBRIC_MAX,
)
from server_auth import require_student, session_id

log = logging.getLogger("server.journey")

router = APIRouter(prefix="/api/journey", tags=["journey"])


# --- Schemas ------------------------------------------------------------------------------------


class BuildRoadmapRequest(BaseModel):
    gaps: list[str] = Field(default_factory=list)


class SetTasksRequest(BaseModel):
    done: list[str] = Field(default_factory=list)


class GenerateQuizRequest(BaseModel):
    skill: str = Field(min_length=1)
    difficulty: str = Field(default=CRITIC_QUIZ_DEFAULT_DIFFICULTY)
    count: int = Field(default=CRITIC_QUIZ_DEFAULT)


class GradeQuizRequest(BaseModel):
    batch: QuizBatch
    answers: list[int | None]
    attempt_id: str | None = None
    proctor_flags: list[str] = Field(default_factory=list)


class VoiceQuestionRequest(BaseModel):
    stream: str
    category: str | None = None
    custom_question: str | None = None


class AssessVoiceRequest(BaseModel):
    question: dict
    answer: str
    attempt_id: str | None = None
    proctor_flags: list[str] = Field(default_factory=list)


# --- Endpoints: Status & Metadata ---------------------------------------------------------------


@router.get("/status")
def journey_status() -> dict:
    """Telemetry backend, active AI provider, voice status, and preloader state."""
    eng = journey.engine_status()
    svc = journey.service_status()
    return {
        "ready": True,
        "engine": {
            "active_ai": eng.active_ai,
            "ai": eng.ai,
            "db": eng.db,
            "preloader": eng.preloader,
            "line": eng.line,
        },
        "services": {
            "active_ai": svc.active_ai,
            "voice": svc.voice,
            "voice_detail": svc.voice_detail,
            "telemetry": svc.telemetry,
            "ai_providers": [asdict(p) for p in svc.ai],
        },
    }


@router.get("/streams")
def journey_streams() -> dict:
    """Catalog streams, domains, and roles for navigation and setup."""
    all_streams = journey.streams()
    tree = []
    for s in all_streams:
        domains = []
        for d_id, d_name in journey.domains_in(s):
            domains.append({"id": d_id, "name": d_name, "roles": journey.roles_in(d_id)})
        tree.append({"stream": s, "domains": domains})
    return {
        "streams": all_streams,
        "tree": tree,
        "voice_streams": list(journey.VOICE_STREAMS),
        "categories": list(journey.CATEGORIES),
    }


@router.get("/samples")
def journey_samples() -> dict:
    """Sample resume filenames."""
    return {"samples": list(journey.sample_names())}


# --- Endpoints: Step 2 — Resume Scanner ---------------------------------------------------------


@router.get("/scan")
def journey_get_scan(sid: str = Depends(require_student)) -> dict:
    """Last saved resume scan and current skill gaps."""
    saved = journey.saved_scan(sid)
    gaps, origin = journey.latest_gaps(sid)
    me = journey.student(sid)
    return {
        "saved": asdict(saved) if saved else None,
        "gaps": gaps,
        "origin": origin,
        "target_role": me.target_role,
        "stream": me.stream,
        "domain": me.domain,
    }


@router.post("/scan")
def journey_post_scan(
    role: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    sample_name: Annotated[str | None, Form()] = None,
    sid: str = Depends(require_student),
) -> dict:
    """Parse and diagnose skill gaps from an uploaded resume or sample."""
    if sample_name:
        filename = sample_name
        data = journey.read_sample(sample_name)
    elif file is not None:
        filename = file.filename or "resume.pdf"
        data = file.file.read(RESUME_MAX_BYTES + 1)  # never read more than one byte past the cap
        if len(data) > RESUME_MAX_BYTES:
            raise HTTPException(400, "Resume file is too large (max 5 MB).")
    else:
        raise HTTPException(400, "Upload a resume or pick a sample first.")

    scan = journey.scan_resume(sid, filename, data, role)
    journey.preload_next_steps(sid)
    return {
        "analysis": asdict(scan.analysis),
        "saved": scan.saved,
    }


# --- Endpoints: Step 3 — 7-Day Study Roadmap ----------------------------------------------------


@router.get("/roadmaps")
def journey_get_roadmaps(sid: str = Depends(require_student)) -> dict:
    """Student's saved study roadmaps, latest gaps, and candidate role skills."""
    plans = journey.roadmaps(sid)
    gaps, origin = journey.latest_gaps(sid)
    me = journey.student(sid)
    role_skills = journey.role_skills(me.target_role)
    return {
        "roadmaps": [
            {
                "week": r.week,
                "plan": r.plan.model_dump(),
                "done": sorted(r.done),
            }
            for r in plans
        ],
        "gaps": gaps,
        "origin": origin,
        "role_skills": role_skills,
        "target_role": me.target_role,
        "stream": me.stream,
    }


@router.post("/roadmaps")
def journey_build_roadmap(body: BuildRoadmapRequest, sid: str = Depends(require_student)) -> dict:
    """Generate a 7-day study roadmap addressing the selected skill gaps."""
    if not body.gaps:
        raise HTTPException(400, "Choose at least one skill gap to address.")
    roadmap, saved = journey.build_roadmap(sid, body.gaps)
    return {
        "roadmap": {
            "week": roadmap.week,
            "plan": roadmap.plan.model_dump(),
            "done": sorted(roadmap.done),
        },
        "saved": saved,
    }


@router.post("/roadmaps/{week}/tasks")
def journey_set_tasks(
    week: int, body: SetTasksRequest, sid: str = Depends(require_student)
) -> dict:
    """Persist completed task keys for the given roadmap week."""
    ok = journey.set_tasks_done(sid, week, set(body.done))
    return {"ok": ok}


# --- Endpoints: Step 4 — Critic-Checked Quiz ----------------------------------------------------


@router.get("/critic-quiz/skills")
def journey_critic_quiz_skills(request: Request) -> dict:
    """Skills ordered by student gaps first, then role skills, with sizing options."""
    sid = session_id(request)
    if sid:
        skills = journey.quiz_skills(sid)
        me = journey.student(sid)
        target_role = me.target_role
    else:
        skills = [t for d in syllabus.catalog()["domains"] for t in d["topics"]]
        target_role = ""
    return {
        "skills": skills,
        "topics": skills,
        "sizes": list(CRITIC_QUIZ_SIZES),
        "difficulties": list(DIFFICULTIES),
        "default_size": CRITIC_QUIZ_DEFAULT,
        "default_difficulty": CRITIC_QUIZ_DEFAULT_DIFFICULTY,
        "target_role": target_role,
    }


@router.post("/critic-quiz/generate")
def journey_critic_quiz_generate(
    body: GenerateQuizRequest, sid: str = Depends(require_student)
) -> dict:
    """Generate a batch of critic-verified MCQs on a chosen skill."""
    batch = journey.critic_quiz(sid, body.skill, body.difficulty, body.count)
    journey.preload_next_quiz(sid, batch)
    return batch.model_dump()


@router.post("/critic-quiz/grade")
def journey_critic_quiz_grade(body: GradeQuizRequest, sid: str = Depends(require_student)) -> dict:
    """Mark answers and record attempt, integrating optional proctoring flags."""
    flags = list(body.proctor_flags)
    if body.attempt_id:
        try:
            proctoring.finish(sid, body.attempt_id)
            flags.extend(proctoring.telemetry_for([body.attempt_id]))
        except Exception:
            log.exception("proctoring finish failed for attempt %s", body.attempt_id)

    grade = journey.grade_quiz(sid, body.batch, body.answers, proctor_flags=flags)
    return {
        "score": grade.score,
        "total": grade.total,
        "correct": list(grade.correct),
        "percent": grade.percent,
        "saved": grade.saved,
    }


# --- Endpoints: Step 5 — Proctored Voice Assessment ---------------------------------------------


@router.post("/voice/question")
def journey_voice_question(body: VoiceQuestionRequest, sid: str = Depends(require_student)) -> dict:
    """Retrieve scenario question with spoken audio or browser TTS."""
    cat: Category | None = body.category if body.category in journey.CATEGORIES else None  # type: ignore[assignment]
    vq = journey.voice_question(sid, body.stream, cat, custom_question=body.custom_question)
    journey.preload_next_voice(sid, body.stream, cat or VOICE_DEFAULT_CATEGORY)

    audio_b64 = (
        base64.b64encode(vq.speech.audio_bytes).decode("ascii") if vq.speech.audio_bytes else None
    )
    return {
        "question": asdict(vq.question),
        "speech": {
            "audio_base64": audio_b64,
            "media_type": vq.speech.media_type,
            "voice": vq.speech.voice,
        },
        "browser_speech_html": journey.browser_speech_html(vq.question.question_text),
    }


@router.post("/voice/transcribe")
def journey_voice_transcribe(
    file: Annotated[UploadFile, File()], _: str = Depends(require_student)
) -> dict:
    """Transcribe spoken answer with Whisper."""
    content = file.file.read(RESUME_MAX_BYTES + 1)
    if len(content) > RESUME_MAX_BYTES:
        raise HTTPException(400, "Audio is too large.")
    text = journey.transcribe(content)
    return {"text": text}


@router.post("/voice/assess")
def journey_voice_assess(body: AssessVoiceRequest, sid: str = Depends(require_student)) -> dict:
    """Grade spoken/typed answer using 0-15 rubric evaluator agent."""
    flags = list(body.proctor_flags)
    if body.attempt_id:
        try:
            proctoring.finish(sid, body.attempt_id)
            flags.extend(proctoring.telemetry_for([body.attempt_id]))
        except Exception:
            log.exception("proctoring finish failed for voice attempt %s", body.attempt_id)

    q = VoiceInterviewQuestion(
        question_text=body.question.get("question_text", ""),
        target_role=body.question.get("target_role", ""),
        stream=body.question.get("stream", ""),
        category=body.question.get("category", "technical"),
        scenario_context=body.question.get("scenario_context", ""),
        expected_rubric_points=body.question.get("expected_rubric_points", []),
    )
    res = journey.assess_answer(sid, q, body.answer, proctor_flags=flags)
    return {
        "evaluation": asdict(res.evaluation),
        "saved": res.saved,
        "max_score": VOICE_RUBRIC_MAX,
    }


# --- Endpoints: Evaluation Benchmark Results ----------------------------------------------------


@router.get("/evaluation-results")
def journey_evaluation_results() -> dict:
    """Evaluation scorecard vs single-prompt baseline on frozen benchmark test cases."""
    summary = services.evaluation_summary()
    if summary is None:
        return {"summary": None, "scorecard": None, "metrics": []}

    card = services.evaluation_scorecard(summary)
    scorecard_data = None
    if card is not None:
        scorecard_data = {
            "overall_placementiq": card.overall("placementiq"),
            "overall_baseline": card.overall("baseline"),
            "head_to_head_placementiq": card.overall("placementiq", True),
            "head_to_head_baseline": card.overall("baseline", True),
            "groups": card.groups(),
            "parameters": [
                {
                    "key": p.key,
                    "name": p.name,
                    "group": p.group,
                    "what": p.what,
                    "method": p.method,
                    "unit": p.unit,
                    "higher_is_better": p.higher_is_better,
                    "weight": p.weight,
                    "baseline": p.baseline,
                    "placementiq": p.placementiq,
                    "baseline_score": p.baseline_score,
                    "placementiq_score": p.placementiq_score,
                    "note": p.note,
                }
                for p in card.parameters
            ],
        }

    params = scorecard_data.get("parameters", []) if scorecard_data else []
    return {
        "summary": summary,
        "scorecard": scorecard_data,
        "metrics": params,
    }
