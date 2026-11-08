"""Cohort analytics for the faculty dashboard (pure: telemetry rows in, plain data out).

From database/crud.py's Cohort snapshot: one readiness row per student (the placement
readiness report), per-stream summaries, score distributions, the rubric breakdown, the most
common skill gaps and the weekly quiz trend. Code computes every number here; nothing is
asked of an LLM. The CSV is safe to open in a spreadsheet (no formula injection).
"""

import csv
import io
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Protocol

from piq.config import (
    GAP_CHART_TOP,
    NEARLY_READY_AT,
    READINESS_WEIGHTS,
    READY_AT,
    VOICE_RUBRIC_MAX,
)

BANDS = ("Ready", "Nearly ready", "Needs work", "Not assessed")
ALL = "All streams"


# Structural types: the detached ORM rows of database/models.py satisfy them, and tests can pass
# plain objects. This module never imports SQLAlchemy.
class _Student(Protocol):
    id: int
    username: str
    name: str
    stream: str
    department: str | None
    target_role: str
    created_at: datetime


class _Resume(Protocol):
    student_id: int
    matched_skills: list[str]
    missing_skills: list[str]
    match_percentage: float


class _Plan(Protocol):
    student_id: int
    week_number: int
    plan_data: dict
    completed_tasks: list[str]


class _Quiz(Protocol):
    student_id: int
    stream: str
    domain: str
    score: int
    total_questions: int
    timestamp: datetime


class _Voice(Protocol):
    student_id: int
    role: str
    rubric_score: int
    verbal_clarity_score: float
    relevance_score: float
    proctor_flags: list[str]
    timestamp: datetime


class Snapshot(Protocol):
    students: list
    latest_resumes: dict
    plans: list
    quiz_attempts: list
    interviews: list


@dataclass(frozen=True)
class StudentRow:
    """One line of the placement readiness report."""

    username: str
    name: str
    stream: str
    department: str
    target_role: str
    resume_match: float | None
    missing_skills: tuple[str, ...]
    quizzes: int
    quiz_average: float | None  # %
    voice_sessions: int
    rubric_average: float | None  # out of VOICE_RUBRIC_MAX
    rubric_best: int | None
    proctor_flags: int
    plans: int
    tasks_done: int
    last_active: datetime | None
    readiness: float | None
    band: str
    # An organization's student: where the admin placed them (blank for an individual learner).
    email: str = ""
    main_domain: str = ""
    subdomain: str = ""
    account_status: str = "active"


@dataclass(frozen=True)
class StreamSummary:
    stream: str
    students: int
    readiness: float | None
    quiz_average: float | None
    resume_match: float | None
    rubric_average: float | None
    bands: dict[str, int] = field(default_factory=dict)


def _avg(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(mean(values), 1) if values else None


def readiness(
    resume_match: float | None, quiz_average: float | None, rubric_average: float | None
) -> float | None:
    """Weighted mean (0-100) of the parts a student has done; None when they have done none."""
    parts = {
        "resume": resume_match,
        "quiz": quiz_average,
        "voice": None if rubric_average is None else rubric_average / VOICE_RUBRIC_MAX * 100,
    }
    done = {k: v for k, v in parts.items() if v is not None}
    if not done:
        return None
    weight = sum(READINESS_WEIGHTS[k] for k in done)
    return round(sum(READINESS_WEIGHTS[k] * v for k, v in done.items()) / weight, 1)


def band(score: float | None) -> str:
    if score is None:
        return "Not assessed"
    if score >= READY_AT:
        return "Ready"
    return "Nearly ready" if score >= NEARLY_READY_AT else "Needs work"


def quiz_percent(q: _Quiz) -> float:
    return q.score / q.total_questions * 100


def confidence_score(v: _Voice) -> float:
    """The third rubric criterion: the total less the two stored ones (the table keeps two)."""
    return max(0.0, v.rubric_score - v.verbal_clarity_score - v.relevance_score)


def student_rows(c: Snapshot) -> list[StudentRow]:
    quizzes: dict[int, list[_Quiz]] = defaultdict(list)
    for q in c.quiz_attempts:
        quizzes[q.student_id].append(q)
    voices: dict[int, list[_Voice]] = defaultdict(list)
    for v in c.interviews:
        voices[v.student_id].append(v)
    plans: dict[int, list[_Plan]] = defaultdict(list)
    for p in c.plans:
        plans[p.student_id].append(p)

    rows = []
    for s in c.students:
        resume = c.latest_resumes.get(s.id)
        qs, vs, ps = quizzes[s.id], voices[s.id], plans[s.id]
        match = round(float(resume.match_percentage), 1) if resume else None
        quiz_avg = _avg(quiz_percent(q) for q in qs)
        rubric_avg = _avg(v.rubric_score for v in vs)
        score = readiness(match, quiz_avg, rubric_avg)
        stamps = [q.timestamp for q in qs] + [v.timestamp for v in vs]
        rows.append(
            StudentRow(
                username=s.username,
                name=s.name,
                stream=s.stream,
                department=s.department or "",
                target_role=s.target_role,
                resume_match=match,
                missing_skills=tuple(resume.missing_skills) if resume else (),
                quizzes=len(qs),
                quiz_average=quiz_avg,
                voice_sessions=len(vs),
                rubric_average=rubric_avg,
                rubric_best=max((v.rubric_score for v in vs), default=None),
                proctor_flags=(
                    sum(len(v.proctor_flags) for v in vs)
                    + sum(len(getattr(q, "proctor_flags", []) or []) for q in qs)
                ),
                plans=len(ps),
                tasks_done=sum(len(p.completed_tasks) for p in ps),
                last_active=max(stamps, default=None),
                readiness=score,
                band=band(score),
                email=getattr(s, "email", None) or "",
                main_domain=getattr(s, "main_domain", None) or "",
                subdomain=getattr(s, "subdomain", None) or "",
                account_status=getattr(s, "account_status", None) or "active",
            )
        )
    return rows


def streams(rows: Sequence[StudentRow]) -> list[str]:
    return sorted({r.stream for r in rows})


def in_stream(rows: Sequence[StudentRow], stream: str) -> list[StudentRow]:
    return list(rows) if stream == ALL else [r for r in rows if r.stream == stream]


def stream_summaries(rows: Sequence[StudentRow]) -> list[StreamSummary]:
    """Per stream, sorted by name: students, average readiness and its parts, and bands.
    Each average is over the students who have that part."""
    out = []
    for name in streams(rows):
        group = [r for r in rows if r.stream == name]
        out.append(
            StreamSummary(
                stream=name,
                students=len(group),
                readiness=_avg(r.readiness for r in group if r.readiness is not None),
                quiz_average=_avg(r.quiz_average for r in group if r.quiz_average is not None),
                resume_match=_avg(r.resume_match for r in group if r.resume_match is not None),
                rubric_average=_avg(
                    r.rubric_average for r in group if r.rubric_average is not None
                ),
                bands={b: n for b in BANDS if (n := sum(r.band == b for r in group))},
            )
        )
    return out


def _stream_of(c: Snapshot) -> dict[int, str]:
    return {s.id: s.stream for s in c.students}


def quiz_scores(c: Snapshot, stream: str = ALL) -> list[float]:
    """Every quiz attempt's score (%), for the distribution chart."""
    return [quiz_percent(q) for q in c.quiz_attempts if stream in (ALL, q.stream)]


def rubric_totals(c: Snapshot, stream: str = ALL) -> list[int]:
    of = _stream_of(c)
    return [v.rubric_score for v in c.interviews if stream in (ALL, of.get(v.student_id))]


def rubric_breakdown(c: Snapshot, stream: str = ALL) -> dict[str, float]:
    """Average of each rubric criterion (0-5) over the voice sessions; {} with none."""
    of = _stream_of(c)
    vs = [v for v in c.interviews if stream in (ALL, of.get(v.student_id))]
    if not vs:
        return {}
    return {
        "Content knowledge": round(mean(v.relevance_score for v in vs), 1),
        "Clarity and structure (STAR)": round(mean(v.verbal_clarity_score for v in vs), 1),
        "Confidence and demeanour": round(mean(confidence_score(v) for v in vs), 1),
    }


def skill_gaps(rows: Sequence[StudentRow], top: int = GAP_CHART_TOP) -> list[tuple[str, int]]:
    """The skills most students' latest resume scan found missing: (skill, students), most
    first, ties by name."""
    counts = Counter(skill for r in rows for skill in set(r.missing_skills))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:top]


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_quiz_trend(c: Snapshot, stream: str = ALL) -> list[tuple[date, float, int]]:
    """(Monday of the week, average quiz score %, attempts) for every week with attempts."""
    weeks: dict[date, list[float]] = defaultdict(list)
    for q in c.quiz_attempts:
        if stream in (ALL, q.stream):
            weeks[week_start(q.timestamp.date())].append(quiz_percent(q))
    return [(w, round(mean(v), 1), len(v)) for w, v in sorted(weeks.items())]


REPORT_COLUMNS = (
    ("Username", lambda r: r.username),
    ("Name", lambda r: r.name),
    ("Stream", lambda r: r.stream),
    ("Department", lambda r: r.department),
    ("Target role", lambda r: r.target_role),
    ("Readiness (/100)", lambda r: r.readiness),
    ("Band", lambda r: r.band),
    ("Resume match (%)", lambda r: r.resume_match),
    ("Quizzes taken", lambda r: r.quizzes),
    ("Quiz average (%)", lambda r: r.quiz_average),
    ("Voice sessions", lambda r: r.voice_sessions),
    (f"Voice rubric average (/{VOICE_RUBRIC_MAX})", lambda r: r.rubric_average),
    (f"Voice rubric best (/{VOICE_RUBRIC_MAX})", lambda r: r.rubric_best),
    ("Proctor flags", lambda r: r.proctor_flags),
    ("Study plans", lambda r: r.plans),
    ("Tasks completed", lambda r: r.tasks_done),
    ("Missing skills", lambda r: "; ".join(r.missing_skills)),
    (
        "Last active (UTC)",
        lambda r: r.last_active.strftime("%Y-%m-%d %H:%M") if r.last_active else "",
    ),
)


def _cell(value: object) -> object:
    """Blank for None; text a spreadsheet would run as a formula is prefixed with '."""
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def report_csv(rows: Sequence[StudentRow]) -> bytes:
    """The placement readiness report: one row per student, UTF-8 with a BOM so Excel reads
    names in any script correctly."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([name for name, _ in REPORT_COLUMNS])
    for r in rows:
        w.writerow([_cell(get(r)) for _, get in REPORT_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")


# --- what the faculty page shows --------------------------------------------------------------


def chart_streams(summaries: Sequence[StreamSummary]) -> list[tuple[str, int, float, str]]:
    """(stream, students, readiness, parts) for the streams with a readiness, for the chart."""

    def part(name: str, value: float | None, unit: str) -> str:
        return f"{name} {value:g}{unit}" if value is not None else f"{name} -"

    return [
        (
            s.stream,
            s.students,
            s.readiness,
            ", ".join(
                [
                    part("match", s.resume_match, "%"),
                    part("quiz", s.quiz_average, "%"),
                    part("voice", s.rubric_average, f"/{VOICE_RUBRIC_MAX}"),
                ]
            ),
        )
        for s in summaries
        if s.readiness is not None
    ]


def streams_takeaway(summaries: Sequence[StreamSummary]) -> str:
    ranked = sorted(
        (s for s in summaries if s.readiness is not None), key=lambda s: -(s.readiness or 0)
    )
    if not ranked:
        return "No stream has an assessed student yet"
    top = ranked[0]
    if len(ranked) == 1:
        return f"{top.stream} averages {top.readiness:.0f}/100"
    low = ranked[-1]
    return (
        f"{top.stream} leads at {top.readiness:.0f}/100; "
        f"{low.stream} trails at {low.readiness:.0f}/100"
    )


def gaps_takeaway(gaps: Sequence[tuple[str, int]], scanned: int) -> str:
    if not gaps:
        return "No skill gaps recorded yet"
    skill, n = gaps[0]
    return f"{skill} is missing for {n} of {scanned} scanned students"


def report_rows(rows: Sequence[StudentRow]) -> list[dict[str, object]]:
    """The report as records (column name -> value) for an on-screen table."""
    return [{name: get(r) for name, get in REPORT_COLUMNS} for r in rows]
