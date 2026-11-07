"""Controllers for the six-step placement journey's agent pages and the faculty dashboard.

Steps 2 to 5 run the agents/ package (resume scanner, 7-day roadmap, critic-checked quiz, voice
assessment); every result is recorded in the telemetry layer (database/crud.py), which step 6
reads back for the whole cohort. Views call this module, never agents/, core/ or database/.

Agents degrade on their own (the AI router, question bank, curated roadmaps, rubric heuristics),
so a result always comes back. Telemetry is best-effort: a write that fails is logged and
reported as `saved=False`, never raised, so a storage problem never costs a student a result.
Bad input raises services.ServiceError with a message safe to show.

Steps 3 to 5 are preloaded (core/preloader.py): a scan or onboarding starts the roadmap, the
first quiz and the voice questions in the background, so the pages take a finished result
instead of generating one. Preloading is best-effort too: it never raises, and a page that
finds nothing preloaded generates as before.
"""

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agents.critic_quiz_agent import GeneratedMCQ, QuizBatch, bank_quiz
from agents.resume_parser_agent import ResumeAnalysisResult, parse_resume
from agents.rubric_evaluator_agent import (
    RubricEvaluationResult,
    evaluate_rubric_answer,
    transcribe_audio_with_whisper,
)
from agents.study_planner_agent import SevenDayRoadmap, build_fallback_roadmap
from agents.voice_interview_agent import (
    CATEGORIES,
    STREAMS,
    Category,
    VoiceInterviewQuestion,
    bank_stream,
)
from core import ai_router, preloader, speech_router
from core.speech_router import Speech
from database import crud
from database.connection import get_manager
from piq import cohort, db, syllabus
from piq.config import CRITIC_QUIZ_SIZES, DIFFICULTIES, settings
from piq.services import MAX_ANSWER_CHARS, SAMPLES_DIR, ServiceError, sample_resumes

log = logging.getLogger("piq.journey")
VOICE_STREAMS = STREAMS  # the agent's scenario banks (CATEGORIES too, for the voice page)


# --- who and where ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Student:
    id: str  # piq's student id
    username: str
    name: str
    target_role: str
    domain: str  # domain name
    stream: str
    email: str | None = None
    # An organization's student: telemetry mirrors where the admin placed them (all None for an
    # individual learner, whose telemetry row then keeps whatever it has).
    org_code: str | None = None
    main_domain: str | None = None
    subdomain: str | None = None
    account_status: str = "active"


def student(student_id: str | None) -> Student:
    row = db.student(student_id) if student_id else None
    if row is None:
        raise ServiceError("Sign in first.")
    d = syllabus.domain_of_role(row["target_role"])
    stream = syllabus.stream_of(d.id)
    return Student(
        row["id"],
        row["username"],
        row["name"],
        row["target_role"],
        d.name,
        stream,
        row["email"],
        row["org_code"],
        row["main_domain"],
        row["subdomain"],
        row["account_status"],
    )


def streams() -> list[str]:
    """Every academic stream the catalog's domains belong to, in catalog order."""
    return list(dict.fromkeys(syllabus.stream_of(d.id) for d in syllabus.domains()))


def domains_in(stream: str) -> list[tuple[str, str]]:
    """(domain id, name) of the stream's domains."""
    return [(d.id, d.name) for d in syllabus.domains() if syllabus.stream_of(d.id) == stream]


def roles_in(domain_id: str) -> list[str]:
    try:
        return list(syllabus.domain(domain_id).roles)
    except KeyError as e:
        raise ServiceError(f"Unknown domain {domain_id!r}.") from e


def voice_stream(stream: str) -> str:
    """The agent's scenario bank for a catalog stream (one without its own bank: Engineering)."""
    return bank_stream(stream)


# --- telemetry: best-effort -------------------------------------------------------------------


def _telemetry_id(s: Student) -> int:
    if s.org_code and crud.get_organization(s.org_code) is None:
        _record_org_row(db.organization_by_code(s.org_code))  # its students need it to exist
    row = crud.save_student(
        s.username,
        s.name,
        s.stream,
        s.target_role,
        email=s.email,
        department=s.domain,
        org_code=s.org_code,
        main_domain=s.main_domain,
        subdomain=s.subdomain,
        account_status=s.account_status if s.org_code else None,
    )
    return row.id


def _record_org_row(org) -> None:  # type: ignore[no-untyped-def]
    crud.save_organization(
        org["org_code"],
        org["name"],
        org["org_type"],
        org["admin_name"],
        org["admin_email"],
        official_domain=org["official_domain"],
        contact_phone=org["contact_phone"],
        location=org["location"],
        academic_batch=org["academic_batch"],
        quiz_cutoff_pct=org["quiz_cutoff_pct"],
        voice_cutoff_score=org["voice_cutoff_score"],
    )


def record_organization(org_id: int) -> bool:
    """Create or update the organization's telemetry profile (never its admin's password); it
    then reaches the cloud copy with the rest. Best-effort, like every telemetry write."""
    try:
        org = db.organization(org_id)
        if org is None:
            return False
        _record_org_row(org)
        return True
    except Exception:
        log.exception("telemetry: could not record organization %s", org_id)
        return False


def record_students(student_ids: list[str]) -> int:
    """Telemetry profiles for these students (an organization's new students, so the admin
    portal lists them before their first activity); returns how many were recorded."""
    return sum(record_student(sid) for sid in student_ids)


def record_student(student_id: str) -> bool:
    """Create or update the student's telemetry profile (after onboarding)."""
    try:
        _telemetry_id(student(student_id))
        return True
    except Exception:
        log.exception("telemetry: could not record student %s", student_id)
        return False


def telemetry_backend() -> str:
    """Where records live, for the faculty page: always this machine's SQLite file, and the
    state of the cloud copy (Supabase) when one is configured."""
    try:
        st = crud.sync_status()
    except Exception:
        log.exception("telemetry: status unavailable")
        return "Unavailable"
    if not st.cloud_configured:
        return "SQLite"
    if st.state == "offline":
        return f"SQLite; cloud offline, {st.pending} waiting (retry in {st.retry_in_s:.0f} s)"
    if st.pending:
        return f"SQLite; syncing {st.pending} to the cloud"
    note = f", {st.set_aside} set aside" if st.set_aside else ""
    return f"SQLite + cloud copy, up to date{note}"


def cloud_configured() -> bool:
    try:
        return get_manager().cloud_configured
    except Exception:
        return False


def start_sync() -> None:
    """Push whatever is waiting to the cloud copy, in the background (on start-up)."""
    try:
        get_manager().sync.kick()
    except Exception:
        log.exception("telemetry: could not start the cloud sync")


# --- step 2: resume scan ----------------------------------------------------------------------


@dataclass(frozen=True)
class Scan:
    analysis: ResumeAnalysisResult
    saved: bool


def sample_names() -> tuple[str, ...]:
    return sample_resumes()


def read_sample(name: str) -> bytes:
    if name not in sample_resumes():
        raise ServiceError(f"Unknown sample {name!r}.")
    return (SAMPLES_DIR / name).read_bytes()


def scan_resume(student_id: str, filename: str, data: bytes, role: str) -> Scan:
    s = student(student_id)
    if not data:
        raise ServiceError("Upload a resume or pick a sample first.")
    if role not in syllabus.role_skills():
        raise ServiceError(f"Unknown target role {role!r}.")
    try:
        analysis = parse_resume(data, role, filename=filename)
    except ValueError as e:  # ResumeError: unreadable, too large, unsupported type
        raise ServiceError(str(e)) from e
    if not analysis.raw_text.strip():
        raise ServiceError("No text could be read from that file. Try a PDF with real text.")
    try:
        sid = _telemetry_id(s)
        crud.save_resume_analysis(
            sid, analysis.matched_skills, analysis.missing_gap_skills, analysis.match_percentage
        )
        saved = True
    except Exception:
        log.exception("telemetry: could not save the resume scan for %s", s.username)
        saved = False
    return Scan(analysis, saved)


def latest_gaps(student_id: str) -> tuple[list[str], str]:
    """The skills to work on and where they came from: the latest resume scan, else the
    profile from onboarding."""
    s = student(student_id)
    try:
        t = crud.get_student(s.username)
        latest = crud.latest_resume_analysis(t.id) if t else None
    except Exception:
        log.exception("telemetry: could not read the latest scan for %s", s.username)
        latest = None
    if latest is not None:
        return list(latest.missing_skills), "your latest resume scan"
    profile = db.latest_profile(s.id)
    return (list(profile.missing_skills) if profile else []), "your onboarding profile"


@dataclass(frozen=True)
class SavedScan:
    """The latest resume scan as saved (the scanner page shows it after a reload)."""

    matched: tuple[str, ...]
    missing: tuple[str, ...]
    match_percentage: float


@dataclass(frozen=True)
class Snapshot:
    """Where a student left off, read in one go from telemetry when they sign in or come back
    (piq/ui.py keeps it in st.session_state for the session)."""

    scan: SavedScan | None = None
    roadmap_week: int | None = None  # the latest week
    tasks_done: int = 0
    tasks_total: int = 0
    quizzes: int = 0
    last_quiz: tuple[int, int] | None = None  # (score, total)
    voice_sessions: int = 0
    last_voice: int | None = None  # rubric score, 0-15


def snapshot(student_id: str) -> Snapshot:
    """Everything the journey has saved for the student; an empty Snapshot when telemetry is
    unavailable or they have done nothing yet (never raises for a valid student)."""
    s = student(student_id)
    try:
        session = crud.student_session(s.username)
    except Exception:
        log.exception("telemetry: could not read the snapshot for %s", s.username)
        return Snapshot()
    if session is None:
        return Snapshot()
    r = session.resume
    scan = (
        SavedScan(tuple(r.matched_skills), tuple(r.missing_skills), r.match_percentage)
        if r
        else None
    )
    week = done = total = 0
    if session.plans:
        latest = session.plans[-1]
        try:
            plan = SevenDayRoadmap.model_validate(latest.plan_data)
            week, done = latest.week_number, len(latest.completed_tasks)
            total = sum(len(d.micro_tasks) for d in plan.days)
        except ValueError:
            pass
    q, v = session.quiz_attempts, session.interviews
    return Snapshot(
        scan=scan,
        roadmap_week=week or None,
        tasks_done=done,
        tasks_total=total,
        quizzes=len(q),
        last_quiz=(q[-1].score, q[-1].total_questions) if q else None,
        voice_sessions=len(v),
        last_voice=v[-1].rubric_score if v else None,
    )


def saved_scan(student_id: str) -> SavedScan | None:
    return snapshot(student_id).scan


def role_skills(role: str) -> list[str]:
    return list(syllabus.role_skills().get(role, {}))


def quiz_skills(student_id: str) -> list[str]:
    """The skills the quiz page offers, in order: the gaps, then the role's other skills."""
    gaps, _ = latest_gaps(student_id)
    return list(dict.fromkeys([*gaps, *role_skills(student(student_id).target_role)]))


# --- preloading: the next steps, written in the background ------------------------------------


def preload_next_steps(student_id: str) -> list[str]:
    """After onboarding or a scan: start the roadmap, the first quiz and the voice questions
    with exactly the inputs those pages preselect. Returns the task keys started; never
    raises (a page with nothing preloaded generates as before)."""
    try:
        s = student(student_id)
        gaps, _ = latest_gaps(student_id)
        matched = [k for k in role_skills(s.target_role) if k not in gaps]
        return preloader.get_preloader().trigger_post_resume_preload(
            s.id, s.stream, s.target_role, matched, gaps
        )
    except Exception:
        log.exception("preload: could not start the next steps for %s", student_id)
        return []


def preload_next_quiz(student_id: str, batch: QuizBatch) -> list[str]:
    """While a quiz is open: write the next set on the same skill, difficulty and size."""
    try:
        s = student(student_id)
        return preloader.get_preloader().trigger_quiz_next_batch_preload(
            s.id, s.target_role, [batch.topic_or_skill], batch.difficulty, len(batch.questions)
        )
    except Exception:
        log.exception("preload: could not start the next quiz for %s", student_id)
        return []


def next_category(category: Category) -> Category:
    return CATEGORIES[(CATEGORIES.index(category) + 1) % len(CATEGORIES)]


def preload_next_voice(student_id: str, stream: str, category: Category) -> list[str]:
    """While a voice question is open: ready the next type's question and synthesise it."""
    try:
        s = student(student_id)
        return preloader.get_preloader().preload_voice_question(
            s.id, s.target_role, stream, next_category(category), speak=True
        )
    except Exception:
        log.exception("preload: could not start the next voice question for %s", student_id)
        return []


# --- step 3: 7-day roadmap --------------------------------------------------------------------


@dataclass(frozen=True)
class Roadmap:
    week: int
    plan: SevenDayRoadmap
    done: frozenset[str] = field(default_factory=frozenset)  # task keys "d<day>:<n>"


def task_key(day: int, n: int) -> str:
    return f"d{day}:{n}"


def roadmaps(student_id: str) -> list[Roadmap]:
    """The student's saved roadmaps, oldest week first ([] if telemetry is unavailable)."""
    s = student(student_id)
    try:
        t = crud.get_student(s.username)
        plans = crud.study_plans(t.id) if t else []
    except Exception:
        log.exception("telemetry: could not read roadmaps for %s", s.username)
        return []
    out = []
    for p in plans:
        try:
            plan = SevenDayRoadmap.model_validate(p.plan_data)
        except ValueError:  # a plan saved by something else: not a 7-day roadmap
            continue
        out.append(_upgrade(s, t.id, Roadmap(p.week_number, plan, frozenset(p.completed_tasks))))  # type: ignore[union-attr]
    return out


def _upgrade(s: Student, telemetry_id: int, r: Roadmap) -> Roadmap:
    """A provisional week (the curated plan saved because the student asked before the
    personalised one was ready) becomes the personalised one as soon as it is, unless a task is
    already ticked. Until then the preloader is kept writing it. Never waits, never raises."""
    if not r.plan.is_provisional or r.done:
        return r
    plan = r.plan
    gaps = plan.addressed_gaps
    key = preloader.roadmap_key(s.id, plan.target_role, plan.target_stream, gaps)
    p = preloader.get_preloader()
    try:
        ready = p.take_ready(key)
        if not isinstance(ready, SevenDayRoadmap):
            p.submit(
                key,
                lambda: preloader.make_roadmap(s.id, plan.target_role, plan.target_stream, gaps),
            )
            return r
        crud.save_study_plan(telemetry_id, r.week, ready.model_dump())
    except Exception:
        log.exception("preload: could not upgrade week %s for %s", r.week, s.username)
        return r
    log.info("roadmap week %s for %s: provisional plan upgraded", r.week, s.username)
    return Roadmap(r.week, ready)


def build_roadmap(student_id: str, gaps: list[str]) -> tuple[Roadmap, bool]:
    """A new 7-day roadmap for the gaps, saved as the next week: the preloaded one when it is
    ready, the curated one when it is still being written, else written now."""
    s = student(student_id)
    gaps = preloader.clean_skills(gaps)
    plan = preloader.get_preloader().get_or_wait(
        preloader.roadmap_key(s.id, s.target_role, s.stream, gaps),
        lambda: build_fallback_roadmap(gaps, s.target_role, s.stream).model_copy(
            update={"is_provisional": True}  # upgraded by roadmaps() once the real one lands
        ),
        on_miss=lambda: preloader.make_roadmap(s.id, s.target_role, s.stream, gaps),
    )
    weeks = [r.week for r in roadmaps(student_id)]
    week = max(weeks, default=0) + 1
    try:
        crud.save_study_plan(_telemetry_id(s), week, plan.model_dump())
        saved = True
    except Exception:
        log.exception("telemetry: could not save the roadmap for %s", s.username)
        saved = False
    return Roadmap(week, plan), saved


def set_tasks_done(student_id: str, week: int, done: set[str]) -> bool:
    """Replace the week's completed tasks with `done`."""
    s = student(student_id)
    try:
        t = crud.get_student(s.username)
        plan = (
            next((p for p in crud.study_plans(t.id) if p.week_number == week), None) if t else None
        )
        if plan is None:
            return False
        crud.save_study_plan(t.id, week, plan.plan_data, sorted(done))
        return True
    except Exception:
        log.exception("telemetry: could not save progress for %s", s.username)
        return False


# --- step 4: critic-checked quiz --------------------------------------------------------------


@dataclass(frozen=True)
class QuizGrade:
    score: int
    total: int
    correct: tuple[bool, ...]
    saved: bool

    @property
    def percent(self) -> int:
        return round(self.score / self.total * 100) if self.total else 0


def critic_quiz(student_id: str, skill: str, difficulty: str, count: int) -> QuizBatch:
    s = student(student_id)
    skill = skill.strip()
    if not skill:
        raise ServiceError("Pick a skill to be quizzed on.")
    if difficulty not in DIFFICULTIES:
        raise ServiceError(f"Difficulty must be one of {', '.join(DIFFICULTIES)}.")
    if count not in CRITIC_QUIZ_SIZES:
        raise ServiceError(f"A quiz has {', '.join(map(str, CRITIC_QUIZ_SIZES))} questions.")
    # Preloaded: at once. Still being checked: the verified bank now (the checked set is kept
    # for the next request). Nothing preloaded: the generator-critic loop runs now.
    still_writing = "The checked questions were still being written; these are from the bank."
    return preloader.get_preloader().get_or_wait(
        preloader.quiz_key(s.id, s.target_role, skill, difficulty, count),
        lambda: bank_quiz(skill, s.target_role, difficulty, count, [still_writing]),
        on_miss=lambda: preloader.make_quiz(s.id, s.target_role, skill, difficulty, count),
    )


def grade_quiz(student_id: str, batch: QuizBatch, answers: list[int | None]) -> QuizGrade:
    """Mark the answers (None = skipped) and record the attempt."""
    s = student(student_id)
    if len(answers) != len(batch.questions):
        raise ServiceError("Answer every question, or leave it blank to skip it.")
    correct = tuple(a == q.correct_index for a, q in zip(answers, batch.questions, strict=True))
    score, total = sum(correct), len(correct)
    notes = (
        f"Skill: {batch.topic_or_skill}. Difficulty: {batch.difficulty}. "
        f"Source: {batch.source.replace('_', ' ')}, attempts: {batch.attempts}. "
        + " ".join(batch.critic_notes)
    )
    try:
        crud.save_quiz_attempt(_telemetry_id(s), s.stream, s.domain, score, total, notes)
        saved = True
    except Exception:
        log.exception("telemetry: could not save the quiz for %s", s.username)
        saved = False
    return QuizGrade(score, total, correct, saved)


def option_label(q: GeneratedMCQ, i: int) -> str:
    return f"{'ABCD'[i]}. {q.options[i]}"


# --- step 5: proctored voice assessment -------------------------------------------------------


@dataclass(frozen=True)
class VoiceQuestion:
    question: VoiceInterviewQuestion
    speech: Speech


def voice_question(student_id: str, stream: str, category: Category | None) -> VoiceQuestion:
    s = student(student_id)
    if category is not None and category not in CATEGORIES:
        raise ServiceError(f"Question type must be one of {', '.join(CATEGORIES)}.")
    p = preloader.get_preloader()

    def ask() -> VoiceInterviewQuestion:  # a bank pick: instant, so it is also the fallback
        return preloader.make_voice_question(s.target_role, stream, category)

    q = p.get_or_wait(preloader.voice_key(s.id, s.target_role, stream, category), ask)
    # Audio still being synthesised: the browser voice now, never a second paid request.
    speech = p.get_or_wait(
        preloader.audio_key(q.question_text),
        lambda: speech_router.synthesize(q.question_text, network=False),
        on_miss=lambda: speech_router.synthesize(q.question_text),
    )
    return VoiceQuestion(q, speech)


def browser_speech_html(text: str) -> str:
    """The browser-voice player for a question ElevenLabs did not speak."""
    return speech_router.browser_speech_html(text)


def transcribe(audio: bytes) -> str:
    """The spoken answer as text; '' when no transcriber is available (the student types)."""
    return transcribe_audio_with_whisper(audio) if audio else ""


@dataclass(frozen=True)
class VoiceResult:
    evaluation: RubricEvaluationResult
    saved: bool


def assess_answer(student_id: str, question: VoiceInterviewQuestion, answer: str) -> VoiceResult:
    s = student(student_id)
    answer = answer.strip()
    if not answer:
        raise ServiceError("Record or type an answer first.")
    if len(answer) > MAX_ANSWER_CHARS:
        raise ServiceError(f"Keep the answer under {MAX_ANSWER_CHARS} characters.")
    result = evaluate_rubric_answer(
        question.question_text, answer, question.stream, s.target_role, student_id=s.id
    )
    r = result.rubric
    feedback = "\n".join(
        [f"Tier: {result.performance_tier}."]
        + [f"Strength: {x}" for x in result.strengths]
        + [f"Improve: {x}" for x in result.areas_for_improvement]
    )
    try:
        crud.save_voice_session(
            _telemetry_id(s),
            s.target_role,
            f"Q: {question.question_text}\nA: {answer}",
            r.total_score,
            r.verbal_clarity_star,
            r.content_knowledge,
            feedback,
            result.gap_flags.flag_details,
        )
        saved = True
    except Exception:
        log.exception("telemetry: could not save the voice session for %s", s.username)
        saved = False
    return VoiceResult(result, saved)


# --- step 6: the faculty dashboard ------------------------------------------------------------


@dataclass(frozen=True)
class CohortView:
    snapshot: crud.Cohort | None  # None: telemetry unavailable
    rows: list[cohort.StudentRow]
    error: str = ""


def cohort_view(cloud: bool = False, org_code: str | None = None) -> CohortView:
    """This machine's records (instant), or with `cloud` every machine's, from the cloud copy.
    `org_code`: only that organization's students."""
    try:
        snap = crud.cohort(source="cloud" if cloud else "local", org_code=org_code)
    except Exception as e:
        log.exception("telemetry: could not read the cohort (%s)", "cloud" if cloud else "local")
        where = "The cloud copy" if cloud else "Telemetry"
        return CohortView(None, [], f"{where} is unavailable: {type(e).__name__}.")
    return CohortView(snap, cohort.student_rows(snap))


def student_history(username: str) -> crud.StudentSession | None:
    """Everything recorded for one student (resume, plans, quizzes, interviews), or None when
    nothing is. Raises when telemetry is unavailable: the caller says so."""
    return crud.student_session(username)


def active_ai() -> str:
    """The provider that answers next ('Gemini', ..., 'Offline rules', 'Mock mode')."""
    return ai_router.active_provider()


@dataclass(frozen=True)
class ServiceStatus:
    ai: list[ai_router.ProviderStatus]
    active_ai: str
    voice: str
    voice_detail: str
    telemetry: str


@dataclass(frozen=True)
class EngineStatus:
    active_ai: str  # as active_ai(): the sidebar badge
    ai: str
    db: str
    preloader: str

    @property
    def line(self) -> str:
        return f"AI: {self.ai} · DB: {self.db} · Preloader: {self.preloader}"


def _db_engine() -> str:
    try:
        sync = crud.sync_status()
    except Exception:
        log.exception("telemetry: status unavailable")
        return "unavailable"
    if not sync.cloud_configured:
        return "local WAL"
    host = urlsplit(settings().database_url).hostname or ""
    cloud = "Supabase" if host.endswith("supabase.com") else "cloud"
    if sync.state == "offline":
        return f"local WAL + {cloud} sync (offline, {sync.pending} waiting)"
    waiting = f" ({sync.pending} waiting)" if sync.pending else ""
    return f"local WAL + {cloud} sync{waiting}"


def engine_status() -> EngineStatus:
    """The sidebar footer, from one router check per run: who answers (and over how many
    keys), where records go, and the preloader. Keys are counted, never shown or asked for."""
    if settings().mock_mode:
        active, ai = "Mock mode", "mock mode"
    else:
        ready = next((p for p in ai_router.status() if p.state == "ready"), None)
        if ready is None:
            active, ai = "Offline rules", "built-in answers"
        else:
            active = ready.label
            ai = f"{ready.label} LB ({ready.keys} keys)" if ready.keys > 1 else ready.label
    return EngineStatus(active, ai, _db_engine(), preloader.get_preloader().status().label)


def service_status() -> ServiceStatus:
    """Which provider answers now, which are paused or off: Layer 3 made visible."""
    why = speech_router.elevenlabs_unavailable()
    return ServiceStatus(
        ai=ai_router.status(),
        active_ai=ai_router.active_provider(),
        voice=speech_router.active_voice(),
        voice_detail=why or "Ready",
        telemetry=telemetry_backend(),
    )
