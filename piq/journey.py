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
    usn: str
    name: str
    target_role: str
    domain: str  # domain name
    stream: str


def student(student_id: str | None) -> Student:
    row = db.student(student_id) if student_id else None
    if row is None:
        raise ServiceError("Onboard this student first.")
    d = syllabus.domain_of_role(row["target_role"])
    return Student(
        row["id"], row["usn"], row["name"], row["target_role"], d.name, syllabus.stream_of(d.id)
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
    row = crud.save_student(s.usn, s.name, s.stream, s.target_role, department=s.domain)
    return row.id


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
        log.exception("telemetry: could not save the resume scan for %s", s.usn)
        saved = False
    return Scan(analysis, saved)


def latest_gaps(student_id: str) -> tuple[list[str], str]:
    """The skills to work on and where they came from: the latest resume scan, else the
    profile from onboarding."""
    s = student(student_id)
    try:
        t = crud.get_student(s.usn)
        latest = crud.latest_resume_analysis(t.id) if t else None
    except Exception:
        log.exception("telemetry: could not read the latest scan for %s", s.usn)
        latest = None
    if latest is not None:
        return list(latest.missing_skills), "your latest resume scan"
    profile = db.latest_profile(s.id)
    return (list(profile.missing_skills) if profile else []), "your onboarding profile"


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
        t = crud.get_student(s.usn)
        plans = crud.study_plans(t.id) if t else []
    except Exception:
        log.exception("telemetry: could not read roadmaps for %s", s.usn)
        return []
    out = []
    for p in plans:
        try:
            plan = SevenDayRoadmap.model_validate(p.plan_data)
        except ValueError:  # a plan saved by something else: not a 7-day roadmap
            continue
        out.append(Roadmap(p.week_number, plan, frozenset(p.completed_tasks)))
    return out


def build_roadmap(student_id: str, gaps: list[str]) -> tuple[Roadmap, bool]:
    """A new 7-day roadmap for the gaps, saved as the next week: the preloaded one when it is
    ready, the curated one when it is still being written, else written now."""
    s = student(student_id)
    gaps = preloader.clean_skills(gaps)
    plan = preloader.get_preloader().get_or_wait(
        preloader.roadmap_key(s.id, s.target_role, s.stream, gaps),
        lambda: build_fallback_roadmap(gaps, s.target_role, s.stream),
        on_miss=lambda: preloader.make_roadmap(s.id, s.target_role, s.stream, gaps),
    )
    weeks = [r.week for r in roadmaps(student_id)]
    week = max(weeks, default=0) + 1
    try:
        crud.save_study_plan(_telemetry_id(s), week, plan.model_dump())
        saved = True
    except Exception:
        log.exception("telemetry: could not save the roadmap for %s", s.usn)
        saved = False
    return Roadmap(week, plan), saved


def set_tasks_done(student_id: str, week: int, done: set[str]) -> bool:
    """Replace the week's completed tasks with `done`."""
    s = student(student_id)
    try:
        t = crud.get_student(s.usn)
        plan = (
            next((p for p in crud.study_plans(t.id) if p.week_number == week), None) if t else None
        )
        if plan is None:
            return False
        crud.save_study_plan(t.id, week, plan.plan_data, sorted(done))
        return True
    except Exception:
        log.exception("telemetry: could not save progress for %s", s.usn)
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
        log.exception("telemetry: could not save the quiz for %s", s.usn)
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
        log.exception("telemetry: could not save the voice session for %s", s.usn)
        saved = False
    return VoiceResult(result, saved)


# --- step 6: the faculty dashboard ------------------------------------------------------------


@dataclass(frozen=True)
class CohortView:
    snapshot: crud.Cohort | None  # None: telemetry unavailable
    rows: list[cohort.StudentRow]
    error: str = ""


def cohort_view(cloud: bool = False) -> CohortView:
    """This machine's records (instant), or with `cloud` every machine's, from the cloud copy."""
    try:
        snap = crud.cohort(source="cloud" if cloud else "local")
    except Exception as e:
        log.exception("telemetry: could not read the cohort (%s)", "cloud" if cloud else "local")
        where = "The cloud copy" if cloud else "Telemetry"
        return CohortView(None, [], f"{where} is unavailable: {type(e).__name__}.")
    return CohortView(snap, cohort.student_rows(snap))


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
