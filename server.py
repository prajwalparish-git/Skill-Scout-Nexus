"""HTTP API for the Next.js frontend (frontend/): a thin FastAPI layer over piq.services.

Every route calls services and serialises what they return; no business logic lives here.
Routes are plain `def`s (FastAPI runs them in its thread pool), so the code stays synchronous.
The interview route streams server-sent events: each critic step as it happens, then the
approved question. Questions are not streamed token by token, because the critic checks each
one before the student sees it.

Run: uvicorn server:app --port 8000   (the frontend reads NEXT_PUBLIC_API_URL)
"""

import json
import logging
import os
import queue
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from dotenv import dotenv_values
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from piq import (
    db,
    formatter,
    graph,
    llm,
    question_bank,
    resume_builder,
    services,
    study_library,
    syllabus,
)
from piq.config import INSTANT_QUIZ_SIZE, QUIZ_MAX_PER_TOPIC, ROOT
from piq.services import InterviewSession, ServiceError
from server_auth import authorize, owner, require_student
from server_auth import router as auth_router
from server_ops import router as ops_router

log = logging.getLogger("server")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create the database and load the catalog and question bank once, before any request
    (FastAPI only takes an async lifespan; nothing else here is async)."""
    db.init_db()
    syllabus.catalog()
    question_bank.size()
    yield


DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def cors_origins() -> list[str]:
    """FRONTEND_ORIGINS from the environment, else from .env, else the local Next.js app.
    Read without loading .env into os.environ: the middleware is built at import, before
    settings() runs."""
    raw = (
        os.getenv("FRONTEND_ORIGINS")
        or dotenv_values(os.getenv("PIQ_DOTENV", ROOT / ".env")).get("FRONTEND_ORIGINS")
        or DEFAULT_ORIGINS
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="Skill Scout Nexus API", version="1.0", lifespan=_lifespan)
app.include_router(auth_router)
app.include_router(ops_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,  # the session cookie, when the app calls the API from another origin
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Content-Disposition"],  # the PDF's file name, read by the browser
)


@app.exception_handler(ServiceError)
def _service_error(_: Request, e: ServiceError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(llm.RateLimited)
def _rate_limited(_: Request, e: llm.RateLimited) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=429)


@app.exception_handler(llm.LLMError)
def _llm_error(_: Request, e: llm.LLMError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=502)


@app.exception_handler(graph.CriticRejected)
def _rejected(_: Request, e: graph.CriticRejected) -> JSONResponse:
    return JSONResponse({"detail": f"The critic rejected every attempt: {e}"}, status_code=502)


def _rows(rows: list) -> list[dict]:
    return [dict(r) for r in rows]


def _student(candidate_id: str) -> services.StudentProfile:
    profile = services.current_profile(candidate_id)
    if profile is None:
        raise HTTPException(404, "No such candidate, or not onboarded yet.")
    return profile


# --- catalog and students ----------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "bank_questions": question_bank.size()}


@app.get("/api/catalog")
def catalog() -> dict:
    """Domains (topics, roles with ATS keywords) and the qualifications a resume can list."""
    counts = question_bank.counts()
    domains = []
    for d in syllabus.catalog()["domains"]:
        domains.append(
            {
                "id": d["id"],
                "name": d["name"],
                "icon": d.get("icon", "work"),
                "description": d.get("description", ""),
                "topics": [{"name": t, "bank": counts.get(t, {})} for t in d["topics"]],
                "roles": d["roles"],
            }
        )
    return {
        "domains": domains,
        "degrees": [{"code": c, "name": services.degree_label(c)} for c in services.degree_codes()],
        "statuses": list(services.DEGREE_STATUSES),
    }


@app.get("/api/library")
def library() -> dict:
    """Curated study books and GitHub repositories, with a role index to filter them by."""
    return study_library.payload()


@app.get("/api/roles-for-degree")
def roles_for_degree(degree: str, specialization: str = "", status: str = "Completed") -> list:
    return [asdict(f) for f in services.roles_for_degree(degree, specialization, status)]


# --- quizzes: instant, from the question bank ----------


@app.get("/api/quiz")
def quiz(
    request: Request,
    topic: str,
    difficulty: str = "medium",
    count: int = INSTANT_QUIZ_SIZE,
    candidate_id: str | None = None,
) -> dict:
    """Bank questions without their answers: the submit route grades them. A guest names no
    student; naming one needs that student's session."""
    authorize(request, candidate_id)
    q = services.instant_quiz(topic, difficulty, count, candidate_id or None)
    return {
        "topic": q.topic,
        "difficulty": q.difficulty,
        "questions": [
            {"id": question_bank.qid(x), "text": x.text, "options": x.options} for x in q.questions
        ],
    }


class Answer(BaseModel):
    id: str
    choice: int | None = None


class QuizSubmission(BaseModel):
    candidate_id: str | None = None
    topic: str
    difficulty: str
    answers: list[Answer] = Field(min_length=1, max_length=QUIZ_MAX_PER_TOPIC)


@app.post("/api/quiz/submit")
def quiz_submit(body: QuizSubmission, request: Request) -> dict:
    authorize(request, body.candidate_id)
    result = services.grade_instant_quiz(
        body.candidate_id or None,
        body.topic,
        body.difficulty,
        [(a.id, a.choice) for a in body.answers],
    )
    review = [
        {
            "id": question_bank.qid(q),
            "chosen": c,
            "correct_index": q.correct_index,
            "is_correct": c == q.correct_index,
            "explanation": q.explanation,
        }
        for q, c in zip(result.quiz.questions, result.chosen, strict=True)
    ]
    weakness = None
    if body.candidate_id:
        weakness = services.weakness_for(_student(body.candidate_id), _scores(body.candidate_id))
    return {
        "score_pct": result.score_pct,
        "correct": result.correct,
        "total": len(result.chosen),
        "next_difficulty": result.next_difficulty,
        "review": review,
        "weakness": weakness,
    }


def _scores(candidate_id: str) -> dict[str, float]:
    return db.topic_performance(candidate_id)


# --- plans and dashboard ----------


def _plan_payload(candidate_id: str) -> dict:
    ov = services.plan_overview(candidate_id, _student(candidate_id))
    latest = ov.plans[-1] if ov.plans else None
    return {
        "plan": latest.model_dump() if latest else None,
        "done": sorted(ov.done.get(latest.week_no, set())) if latest else [],
        "weakness": ov.weakness,
        "scores": ov.scores,
        "next_week": ov.next_week,
        "minutes_by_week": [{"week": p.week_no, "minutes": p.minutes_by_topic()} for p in ov.plans],
    }


@app.get("/api/plan/{candidate_id}", dependencies=[Depends(owner)])
def plan(candidate_id: str) -> dict:
    """The latest 7-day plan with its weakness table."""
    return _plan_payload(candidate_id)


@app.post("/api/plan/{candidate_id}/next", dependencies=[Depends(owner)])
def plan_next(candidate_id: str) -> dict:
    """Generate next week's plan (background lane: Groq key 2), checked by the critic."""
    _student(candidate_id)
    services.generate_next_plan(candidate_id)
    return _plan_payload(candidate_id)


class DaysDone(BaseModel):
    week_no: int
    days: list[int]


@app.post("/api/plan/{candidate_id}/done", dependencies=[Depends(owner)])
def plan_done(candidate_id: str, body: DaysDone) -> dict:
    _student(candidate_id)
    return {"done": sorted(services.set_days_done(candidate_id, body.week_no, body.days))}


@app.get("/api/dashboard/{candidate_id}", dependencies=[Depends(owner)])
def dashboard(candidate_id: str) -> dict:
    d = services.dashboard(candidate_id, _student(candidate_id))
    correct, total = d.answered
    streak = d.streak
    return {
        "profile": d.profile.model_dump(),
        "readiness": _rows(d.readiness),
        "quizzes_taken": d.quizzes_taken,
        "answered": {"correct": correct, "total": total},
        "streak": {"current": streak.current, "longest": streak.longest},
        "mastery": [asdict(m) for m in d.mastery],
        "quiz_history": _rows(d.quiz_history),
        "sessions": _rows(d.sessions),
    }


# --- interviews: server-sent events ----------


@app.get("/api/interview/tracks/{candidate_id}", dependencies=[Depends(owner)])
def interview_tracks(candidate_id: str) -> list[dict]:
    return [asdict(t) for t in services.interview_tracks(_student(candidate_id))]


class InterviewTurnRequest(BaseModel):
    candidate_id: str
    track: str | None = None  # to start a session
    session: dict | None = None  # the state returned by the last turn, to continue it
    answer: str | None = None


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream(work: Callable[[Callable[[str], None]], dict]) -> Iterator[str]:
    """Run `work(on_event)` in a thread; yield each event, then its result (or the error)."""
    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            events.put(("result", work(lambda msg: events.put(("step", msg)))))
        except ServiceError as e:
            events.put(("error", {"detail": str(e), "status": 400}))
        except ValidationError:
            events.put(
                ("error", {"detail": "The interview state sent is not valid.", "status": 400})
            )
        except llm.RateLimited as e:
            events.put(("error", {"detail": str(e), "status": 429}))
        except (llm.LLMError, graph.CriticRejected) as e:
            events.put(("error", {"detail": str(e), "status": 502}))
        except Exception:  # anything else still ends the stream, never leaves it hanging
            log.exception("a streamed request failed")
            events.put(("error", {"detail": "Something went wrong. Try again.", "status": 500}))
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()
    while (item := events.get()) is not None:
        yield _sse(*item)


def _session_payload(session: InterviewSession) -> dict:
    out = {"session": session.model_dump(), "average": session.average}
    if session.done and session.history:
        s = services.interview_summary(session)
        out["summary"] = asdict(s)
    return out


@app.post("/api/interview/turn")
def interview_turn(body: InterviewTurnRequest, request: Request) -> StreamingResponse:
    """Start a session (`track`), or answer the open question and get the next one
    (`session` + `answer`). Streams `step` events, then one `result` or `error` event."""
    authorize(request, body.candidate_id)
    _student(body.candidate_id)

    def work(on_event: Callable[[str], None]) -> dict:
        if body.session is None:
            if not body.track:
                raise ServiceError("Choose an interview track.")
            s = services.start_interview(body.candidate_id, body.track, on_event)
            return _session_payload(s)
        s = InterviewSession.model_validate(body.session)
        if s.current is not None:
            s = services.answer_question(body.candidate_id, s, body.answer or "")
            on_event("Answer scored by the evaluator")
        if not s.done:
            s = services.continue_interview(body.candidate_id, s, on_event)
        return _session_payload(s)

    return StreamingResponse(
        _stream(work),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- resume: local ATS audit, PDF, one LLM endpoint ----------


class ResumeInput(BaseModel):
    """The resume form, as resume_builder.build_ats_resume_data takes it."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    role_name: str
    skills: list[str] = []
    education: list[dict] = []
    experience: list[dict] = []
    project_title: str = ""
    project_tech: str = ""
    project_desc: str = ""
    certifications: list[str] = []


def _build(body: ResumeInput) -> dict:
    if resume_builder.get_role_info(body.role_name) is None:
        raise ServiceError(f"Unknown role {body.role_name!r}.")
    return resume_builder.build_ats_resume_data(
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        location=body.location,
        linkedin_url=body.linkedin_url,
        github_url=body.github_url,
        role_name=body.role_name,
        selected_skills=body.skills,
        custom_project_title=body.project_title,
        custom_project_tech=body.project_tech,
        custom_project_desc=body.project_desc,
        certifications=body.certifications,
        education=body.education,
        experience=body.experience,
        today=formatter.local_today(),
    )


@app.post("/api/resume/ats")
def resume_ats(body: ResumeInput) -> dict:
    """The ATS audit for the live score card (no LLM): score, keywords, verbs, degree fit."""
    res = _build(body)
    ats = resume_builder.evaluate_ats_compatibility(res, body.role_name)
    return {"ats": asdict(ats), "summary": res["summary"], "preview": res}


@app.post("/api/resume/build-pdf")
def resume_pdf(body: ResumeInput) -> Response:
    res = _build(body)
    services.check_resume_dates(res)
    pdf = resume_builder.generate_ats_pdf(res)
    name = formatter.resume_filename(res["full_name"], body.role_name)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class BulletRequest(BaseModel):
    text: str
    role: str


@app.post("/api/resume/enhance-bullet", dependencies=[Depends(require_student)])
def enhance_bullet(body: BulletRequest) -> dict:
    """One bullet in XYZ form (interactive lane: Groq key 1); numbers are never invented."""
    return {"bullet": services.enhance_bullet(body.text, body.role)}


class TasksWebhookPayload(BaseModel):
    student_id: str | None = None
    tasks: list[dict[str, Any]] | list[str] = Field(default_factory=list)
    week_no: int | None = None
    notes: str | None = None


@app.post("/api/webhooks/tasks")
def tasks_webhook(payload: TasksWebhookPayload) -> dict:
    """Mock webhook endpoint for integrating tasks with Zapier, Make, Google Tasks, etc."""
    count = len(payload.tasks)
    return {
        "status": "success",
        "message": f"Successfully received {count} task(s) for sync.",
        "tasks_received": count,
        "week_no": payload.week_no,
    }
