"""What an organization's admin sees, computed (pure: student rows in, plain data out).

Built on piq/cohort.py's StudentRow, one per student of one organization (orgs.py cuts them out
of everyone else's before they get here). Code computes every number; nothing is asked of an LLM.

* The organization's two pass marks (`Cutoffs`: an average quiz score in % and an average voice
  rubric score out of 15) define who is **ready**, the funnel's last two stages and the
  shortlist. Averages, not best attempts: a lucky retake does not clear a student.
* A readiness **tier** for the directory: Ready (both pass marks met), At Risk (nothing assessed
  yet, or readiness under NEARLY_READY_AT), In Progress otherwise.
* The **funnel** is strict: a student counts at a stage only after every earlier stage, in the
  order of the placement journey, so the bars can only shrink.
* The **360 view** of one student from their telemetry history: skills, plan progress, every
  quiz and every voice session.
* The **shortlist** for a placement drive, as a CSV safe to open in a spreadsheet and an
  executive summary PDF for recruiters.
"""

import csv
import io
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from piq import cohort
from piq.cohort import StudentRow
from piq.config import ACTIVE_WITHIN_DAYS, NEARLY_READY_AT, VOICE_RUBRIC_MAX

TIERS = ("Ready", "In Progress", "At Risk")
MOMENTUM_STAGES = ("Placement Ready", "On Track", "Falling Behind", "Stalled")
Group = Literal["main_domain", "subdomain"]
FUNNEL_STAGES = ("Enrolled", "Resume scanned", "Plan active", "Quiz passed", "Voice cleared")


@dataclass(frozen=True)
class LearnerMomentum:
    stage: str
    badge: str
    icon: str
    reason: str
    pending_tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cutoffs:
    quiz_pct: float  # average quiz score (%) that counts as passed
    voice_score: float  # average voice rubric score (out of VOICE_RUBRIC_MAX) that counts


def meets_quiz(r: StudentRow, c: Cutoffs) -> bool:
    return r.quiz_average is not None and r.quiz_average >= c.quiz_pct


def meets_voice(r: StudentRow, c: Cutoffs) -> bool:
    return r.rubric_average is not None and r.rubric_average >= c.voice_score


def is_ready(r: StudentRow, c: Cutoffs) -> bool:
    return meets_quiz(r, c) and meets_voice(r, c)


def tier(r: StudentRow, c: Cutoffs) -> str:
    if is_ready(r, c):
        return "Ready"
    if r.readiness is None or r.readiness < NEARLY_READY_AT:
        return "At Risk"
    return "In Progress"


def is_active(r: StudentRow, now: datetime) -> bool:
    return r.last_active is not None and now - r.last_active <= timedelta(days=ACTIVE_WITHIN_DAYS)


def calculate_learner_momentum(
    student: object,
    c: Cutoffs | None = None,
    now: datetime | None = None,
    plan_percent: int | None = None,
) -> LearnerMomentum:
    """Categorize a student into one of 4 momentum stages:
    * 🟢 Placement Ready: Resume scanned, >70% plan done, cutoffs cleared.
    * 🔵 On Track: Active in the last 3 days, making study plan progress.
    * 🟡 Falling Behind: Active, but <30% plan done or failing quiz cutoffs.
    * 🔴 Stalled: Provisioned, but 0 activity in the last 5 days.
    """
    now = now or datetime.now(UTC)
    c = c or Cutoffs(70.0, 9.0)

    # If student is passed as username or student id string/int:
    if isinstance(student, (int, str)):
        from database import crud

        sess = crud.student_session(str(student))
        if sess is not None:
            c360 = candidate_360(sess)
            qs = sess.quiz_attempts
            vs = sess.interviews
            stamps = [q.timestamp for q in qs] + [v.timestamp for v in vs]
            q_avg = _mean(q.score / q.total_questions * 100 for q in qs) if qs else None
            v_avg = _mean(v.rubric_score for v in vs) if vs else None
            t_done = sum(len(p.completed_tasks) for p in sess.plans)
            r = StudentRow(
                username=sess.profile.username,
                name=sess.profile.name,
                stream=sess.profile.stream,
                department=sess.profile.department or "",
                target_role=sess.profile.target_role,
                resume_match=c360.match_percent,
                missing_skills=c360.missing,
                quizzes=len(qs),
                quiz_average=q_avg,
                voice_sessions=len(vs),
                rubric_average=v_avg,
                rubric_best=max((v.rubric_score for v in vs), default=None),
                proctor_flags=sum(len(v.proctor_flags) for v in vs),
                plans=len(sess.plans),
                tasks_done=t_done,
                last_active=max(stamps, default=None),
                readiness=sess.profile.readiness_score,
                band="Ready" if meets_quiz(student, c) else "Needs work",  # type: ignore[arg-type]
            )
            plan_percent = c360.plan_percent
            student = r

    r_match = getattr(student, "resume_match", None)
    resume_scanned = r_match is not None
    q_avg = getattr(student, "quiz_average", None)
    quiz_cleared = q_avg is not None and q_avg >= c.quiz_pct
    v_avg = getattr(student, "rubric_average", None)
    voice_cleared = v_avg is not None and v_avg >= c.voice_score
    tasks_done = getattr(student, "tasks_done", 0)
    num_plans = getattr(student, "plans", 0)
    last_active = getattr(student, "last_active", None)

    if plan_percent is None:
        if num_plans > 0:
            plan_percent = min(100, round(tasks_done / (num_plans * 7) * 100))
        elif tasks_done > 0:
            plan_percent = min(100, round(tasks_done / 7 * 100))
        else:
            plan_percent = 0

    # 1. 🟢 Placement Ready: Resume scanned, >70% plan done, cutoffs cleared
    if resume_scanned and plan_percent > 70 and quiz_cleared and voice_cleared:
        return LearnerMomentum(
            stage="Placement Ready",
            badge="🟢 Placement Ready",
            icon="🟢",
            reason="Resume scanned, >70% study plan done, and all cutoffs cleared.",
            pending_tasks=(),
        )

    # 2. 🔴 Stalled: Provisioned, but 0 activity in the last 5 days
    if last_active is None or (now - last_active) >= timedelta(days=5):
        tasks = []
        if not resume_scanned:
            tasks.append("Scan latest resume against target role")
        if tasks_done == 0 or plan_percent < 30:
            tasks.append("Begin and complete Week 1 study roadmap tasks")
        if not quiz_cleared:
            tasks.append(f"Pass domain quizzes (cutoff: {c.quiz_pct:g}%)")
        if not voice_cleared:
            tasks.append(
                f"Complete mock voice interviews (cutoff: {c.voice_score:g}/{VOICE_RUBRIC_MAX})"
            )
        days_inact = (now - last_active).days if last_active else 0
        reason = (
            "Provisioned, but no activity yet."
            if last_active is None
            else f"No activity for {days_inact} days (>= 5 days)."
        )
        return LearnerMomentum(
            stage="Stalled",
            badge="🔴 Stalled",
            icon="🔴",
            reason=reason,
            pending_tasks=tuple(tasks),
        )

    # 3. 🟡 Falling Behind: Active, but <30% plan done or failing quiz cutoffs
    if plan_percent < 30 or not quiz_cleared:
        tasks = []
        if not resume_scanned:
            tasks.append("Scan latest resume against target role")
        if plan_percent < 30:
            tasks.append("Complete pending daily tasks to reach 30%+ study plan completion")
        if not quiz_cleared:
            tasks.append(f"Retake quizzes to clear the {c.quiz_pct:g}% pass mark")
        if not voice_cleared:
            tasks.append(
                f"Practise voice interview to meet {c.voice_score:g}/{VOICE_RUBRIC_MAX}"
            )
        reasons = []
        if plan_percent < 30:
            reasons.append(f"study plan completion is {plan_percent}% (<30%)")
        if not quiz_cleared:
            reasons.append(f"quiz average is below {c.quiz_pct:g}% pass mark")
        return LearnerMomentum(
            stage="Falling Behind",
            badge="🟡 Falling Behind",
            icon="🟡",
            reason="Active, but " + " and ".join(reasons) + ".",
            pending_tasks=tuple(tasks),
        )

    # 4. 🔵 On Track: Active in the last 3 days, making study plan progress
    tasks = []
    if plan_percent <= 70:
        tasks.append("Continue daily study plan tasks towards 70%+ milestone")
    if not voice_cleared:
        tasks.append(f"Clear voice interview pass mark ({c.voice_score:g}/{VOICE_RUBRIC_MAX})")
    return LearnerMomentum(
        stage="On Track",
        badge="🔵 On Track",
        icon="🔵",
        reason="Active in the last 3 days and making steady study plan progress.",
        pending_tasks=tuple(tasks),
    )


def momentum_mix(
    rows: Sequence[StudentRow], c: Cutoffs, now: datetime | None = None
) -> list[tuple[str, int]]:
    now = now or datetime.now(UTC)
    counts = Counter(
        calculate_learner_momentum(r, c, now).stage
        for r in rows
        if r.account_status != "suspended"
    )
    return [(s, counts[s]) for s in MOMENTUM_STAGES]


def _mean(values: Iterable[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 1) if kept else None


# --- the overview -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Kpis:
    enrolled: int
    active: int  # a quiz or voice session in the last ACTIVE_WITHIN_DAYS days
    avg_resume_match: float | None  # %, over students who scanned
    avg_quiz: float | None  # %, over students who took a quiz
    avg_voice: float | None  # out of VOICE_RUBRIC_MAX, over students who did a session
    ready: int  # meeting both pass marks


def kpis(rows: Sequence[StudentRow], c: Cutoffs, now: datetime | None = None) -> Kpis:
    now = now or datetime.now(UTC)
    return Kpis(
        enrolled=len(rows),
        active=sum(is_active(r, now) for r in rows),
        avg_resume_match=_mean(r.resume_match for r in rows),
        avg_quiz=_mean(r.quiz_average for r in rows),
        avg_voice=_mean(r.rubric_average for r in rows),
        ready=sum(is_ready(r, c) for r in rows),
    )


@dataclass(frozen=True)
class FunnelStage:
    label: str
    count: int
    of_enrolled: float  # 0..1
    of_previous: float  # 0..1 (1 for the first stage)


def funnel(rows: Sequence[StudentRow], c: Cutoffs) -> list[FunnelStage]:
    """Enrolled -> Resume scanned -> Plan active (a task ticked) -> Quiz passed -> Voice cleared.
    Each stage keeps only the students who cleared every stage before it."""
    checks = (
        lambda r: True,
        lambda r: r.resume_match is not None,
        lambda r: r.tasks_done > 0,
        lambda r: meets_quiz(r, c),
        lambda r: meets_voice(r, c),
    )
    survivors = list(rows)
    out: list[FunnelStage] = []
    previous = len(survivors)
    total = len(survivors)
    for label, check in zip(FUNNEL_STAGES, checks, strict=True):
        survivors = [r for r in survivors if check(r)]
        out.append(
            FunnelStage(
                label,
                len(survivors),
                len(survivors) / total if total else 0.0,
                len(survivors) / previous if previous else 0.0,
            )
        )
        previous = len(survivors)
    return out


def funnel_takeaway(stages: Sequence[FunnelStage]) -> str:
    """The funnel in a sentence: how many cleared everything, and where most dropped out."""
    first, last = stages[0], stages[-1]
    if not first.count:
        return "No students are enrolled yet"
    drops = [
        (b.of_previous, b.label)
        for a, b in zip(stages, stages[1:], strict=False)
        if b.count < a.count
    ]
    where = f"; the biggest drop is at {min(drops)[1].lower()}" if drops else ""
    return f"{last.count} of {first.count} students cleared every stage{where}"


def group_label(r: StudentRow, by: Group) -> str:
    domain = r.main_domain or r.stream or "Unassigned"
    if by == "main_domain":
        return domain
    return f"{domain} / {r.subdomain}" if r.subdomain else f"{domain} / -"


def performance(
    rows: Sequence[StudentRow], by: Group = "main_domain"
) -> list[tuple[str, int, float, str]]:
    """(group, students, average readiness, detail) for the groups with an assessed student,
    best first: the input of charts.stream_readiness (the same bars, by domain or subdomain)."""
    groups: dict[str, list[StudentRow]] = defaultdict(list)
    for r in rows:
        groups[group_label(r, by)].append(r)
    out = []
    for label, members in groups.items():
        score = _mean(m.readiness for m in members)
        if score is None:
            continue
        match, quiz, voice = (
            _mean(m.resume_match for m in members),
            _mean(m.quiz_average for m in members),
            _mean(m.rubric_average for m in members),
        )

        def part(name: str, value: float | None, unit: str) -> str:
            return f"{name} {value:g}{unit}" if value is not None else f"{name} -"

        detail = ", ".join(
            [
                part("match", match, "%"),
                part("quiz", quiz, "%"),
                part("voice", voice, f"/{VOICE_RUBRIC_MAX}"),
            ]
        )
        out.append((label, len(members), score, detail))
    return sorted(out, key=lambda t: (-t[2], t[0]))


def performance_takeaway(perf: Sequence[tuple[str, int, float, str]]) -> str:
    if not perf:
        return "No group has an assessed student yet"
    top = perf[0]
    if len(perf) == 1:
        return f"{top[0]} averages {top[2]:.0f}/100"
    low = perf[-1]
    return f"{top[0]} leads at {top[2]:.0f}/100; {low[0]} trails at {low[2]:.0f}/100"


def gap_matrix(
    rows: Sequence[StudentRow], by: Group = "main_domain", top: int = 10
) -> list[tuple[str, str, int, int]]:
    """The skills most often missing, by group, for a heatmap: (skill, group, students missing
    it, students scanned in the group). Only the `top` skills overall, each in every group that
    has a scanned student, so an empty cell is a real zero."""
    scanned = [r for r in rows if r.resume_match is not None]
    overall = Counter(skill for r in scanned for skill in set(r.missing_skills))
    skills = [s for s, _ in sorted(overall.items(), key=lambda kv: (-kv[1], kv[0].lower()))][:top]
    sizes: Counter[str] = Counter(group_label(r, by) for r in scanned)
    missing: Counter[tuple[str, str]] = Counter(
        (skill, group_label(r, by)) for r in scanned for skill in set(r.missing_skills)
    )
    return [(s, g, missing[(s, g)], sizes[g]) for s in skills for g in sorted(sizes)]


# --- the directory ------------------------------------------------------------------------------


def filter_rows(
    rows: Sequence[StudentRow],
    c: Cutoffs,
    *,
    query: str = "",
    main_domains: Sequence[str] = (),
    subdomains: Sequence[str] = (),
    statuses: Sequence[str] = (),
    tiers: Sequence[str] = (),
) -> list[StudentRow]:
    """The directory's filters; an empty one lets everything through. `query` matches name,
    username, email, role and subdomain (any case)."""
    q = query.strip().lower()
    out = []
    for r in rows:
        hay = f"{r.name} {r.username} {r.email} {r.target_role} {r.subdomain}".lower()
        if q and q not in hay:
            continue
        if main_domains and (r.main_domain or r.stream) not in main_domains:
            continue
        if subdomains and r.subdomain not in subdomains:
            continue
        if statuses and r.account_status not in statuses:
            continue
        if tiers and tier(r, c) not in tiers:
            continue
        out.append(r)
    return out


def directory_rows(rows: Sequence[StudentRow], c: Cutoffs) -> list[dict[str, object]]:
    """The directory table: one record per student (the first column is the username, the key
    the portal selects by)."""
    return [
        {
            "Username": r.username,
            "Name": r.name,
            "Email": r.email,
            "Main domain": r.main_domain or r.stream,
            "Subdomain": r.subdomain,
            "Target role": r.target_role,
            "Status": r.account_status,
            "Momentum Status": calculate_learner_momentum(r, c).badge,
            "Tier": tier(r, c),
            "Readiness": r.readiness,
            "Resume match (%)": r.resume_match,
            "Quiz average (%)": r.quiz_average,
            f"Voice average (/{VOICE_RUBRIC_MAX})": r.rubric_average,
        }
        for r in rows
    ]


# --- one student, in full -----------------------------------------------------------------------


class _Plan(Protocol):
    week_number: int
    plan_data: dict
    completed_tasks: list[str]


@dataclass(frozen=True)
class PlanProgress:
    week: int
    done: int
    total: int

    @property
    def percent(self) -> int:
        return min(100, round(self.done / self.total * 100)) if self.total else 0


@dataclass(frozen=True)
class QuizEntry:
    when: datetime
    skill: str
    difficulty: str
    score: int
    total: int
    notes: str

    @property
    def percent(self) -> float:
        return round(self.score / self.total * 100, 1)


@dataclass(frozen=True)
class TopicStat:
    skill: str
    attempts: int
    percent: float  # of all questions asked on it


@dataclass(frozen=True)
class VoiceEntry:
    when: datetime
    role: str
    rubric: int
    content: float
    clarity: float
    confidence: float
    flags: tuple[str, ...]
    transcript: str
    feedback: str


@dataclass(frozen=True)
class Candidate360:
    matched: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    match_percent: float | None = None
    plans: tuple[PlanProgress, ...] = ()
    quizzes: tuple[QuizEntry, ...] = ()
    topics: tuple[TopicStat, ...] = ()
    voices: tuple[VoiceEntry, ...] = field(default=())

    @property
    def plan_percent(self) -> int | None:
        """Tasks ticked across every week's plan, as a share of all their tasks."""
        total = sum(p.total for p in self.plans)
        return min(100, round(sum(p.done for p in self.plans) / total * 100)) if total else None


_SKILL_NOTE = re.compile(r"Skill: (.+?)\. Difficulty: (\w+)")


def plan_progress(p: _Plan) -> PlanProgress:
    """Tasks ticked of a week's plan. The total is the plan's micro-tasks; a plan that does not
    list them (the demo cohort's) counts its seven days."""
    days = p.plan_data.get("days") or []
    total = sum(len(d.get("micro_tasks", [])) for d in days if isinstance(d, dict))
    return PlanProgress(p.week_number, len(p.completed_tasks), total or 7)


def candidate_360(session) -> Candidate360:  # type: ignore[no-untyped-def]
    """From database/crud.py's StudentSession (duck-typed: this module never imports the
    database layer). Quizzes are listed newest first, as the admin reads them."""
    resume = session.resume
    quizzes = []
    for q in session.quiz_attempts:
        m = _SKILL_NOTE.search(q.critique_notes or "")
        skill, difficulty = (m.group(1), m.group(2)) if m else (q.domain, "-")
        quizzes.append(
            QuizEntry(
                q.timestamp, skill, difficulty, q.score, q.total_questions, q.critique_notes or ""
            )
        )
    asked: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # attempts, correct, total
    for q in quizzes:
        a = asked[q.skill]
        a[0], a[1], a[2] = a[0] + 1, a[1] + q.score, a[2] + q.total
    topics = sorted(
        (TopicStat(s, a[0], round(a[1] / a[2] * 100, 1)) for s, a in asked.items() if a[2]),
        key=lambda t: (t.percent, t.skill),
    )
    voices = [
        VoiceEntry(
            v.timestamp,
            v.role,
            v.rubric_score,
            v.relevance_score,
            v.verbal_clarity_score,
            round(cohort.confidence_score(v), 1),
            tuple(v.proctor_flags),
            v.audio_transcript,
            v.feedback,
        )
        for v in session.interviews
    ]
    return Candidate360(
        matched=tuple(resume.matched_skills) if resume else (),
        missing=tuple(resume.missing_skills) if resume else (),
        match_percent=round(float(resume.match_percentage), 1) if resume else None,
        plans=tuple(plan_progress(p) for p in session.plans),
        quizzes=tuple(reversed(quizzes)),
        topics=tuple(topics),
        voices=tuple(reversed(voices)),
    )


# --- the placement drive ------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveFilter:
    """A placement drive's criteria; an empty list lets every domain through."""

    main_domains: tuple[str, ...] = ()
    subdomains: tuple[str, ...] = ()
    min_quiz: float = 0.0  # average quiz score, %
    min_voice: float = 0.0  # average voice rubric, out of VOICE_RUBRIC_MAX

    def describe(self) -> str:
        where = ", ".join(self.main_domains) or "all domains"
        if self.subdomains:
            where += f" ({', '.join(self.subdomains)})"
        return (
            f"{where}; quiz average at least {self.min_quiz:g}%; "
            f"voice average at least {self.min_voice:g}/{VOICE_RUBRIC_MAX}"
        )


def shortlist(rows: Sequence[StudentRow], f: DriveFilter) -> list[StudentRow]:
    """Students who meet the criteria, best readiness first. A student with no quiz (or voice)
    result cannot meet a minimum above zero."""
    out = []
    for r in rows:
        if f.main_domains and (r.main_domain or r.stream) not in f.main_domains:
            continue
        if f.subdomains and r.subdomain not in f.subdomains:
            continue
        if f.min_quiz > 0 and not (r.quiz_average is not None and r.quiz_average >= f.min_quiz):
            continue
        if f.min_voice > 0 and not (
            r.rubric_average is not None and r.rubric_average >= f.min_voice
        ):
            continue
        if r.account_status == "suspended":
            continue
        out.append(r)
    return sorted(out, key=lambda r: (-(r.readiness or 0), r.name.lower()))


SHORTLIST_COLUMNS = (
    ("Name", lambda r: r.name),
    ("Email", lambda r: r.email),
    ("Main domain", lambda r: r.main_domain or r.stream),
    ("Subdomain", lambda r: r.subdomain),
    ("Target role", lambda r: r.target_role),
    ("Readiness (/100)", lambda r: r.readiness),
    ("Resume match (%)", lambda r: r.resume_match),
    ("Quiz average (%)", lambda r: r.quiz_average),
    (f"Voice average (/{VOICE_RUBRIC_MAX})", lambda r: r.rubric_average),
    (f"Voice best (/{VOICE_RUBRIC_MAX})", lambda r: r.rubric_best),
    ("Proctor flags", lambda r: r.proctor_flags),
    ("Proctor breach", lambda r: "BREACH" if r.proctor_flags > 0 else "CLEARED"),
)


def shortlist_csv(rows: Sequence[StudentRow]) -> bytes:
    """The placement shortlist: UTF-8 with a BOM, every text cell protected from formula
    injection (cohort._cell)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([name for name, _ in SHORTLIST_COLUMNS])
    for r in rows:
        w.writerow([cohort._cell(get(r)) for _, get in SHORTLIST_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")


@dataclass(frozen=True)
class Summary:
    """The facts of the executive summary (the PDF only lays them out)."""

    org_name: str
    org_type: str
    location: str
    batch: str
    generated: str
    cutoffs: Cutoffs
    kpis: Kpis
    funnel: tuple[FunnelStage, ...]
    by_domain: tuple[tuple[str, int, float, str], ...]
    criteria: str
    shortlisted: tuple[StudentRow, ...]
    total_shortlisted: int


def executive_summary(
    org, rows: Sequence[StudentRow], c: Cutoffs, f: DriveFilter, today: datetime | None = None
) -> Summary:  # type: ignore[no-untyped-def]
    today = today or datetime.now(UTC)
    chosen = shortlist(rows, f)
    return Summary(
        org_name=org.name,
        org_type=org.org_type,
        location=org.location,
        batch=org.academic_batch,
        generated=today.strftime("%d %B %Y"),
        cutoffs=c,
        kpis=kpis(rows, c, today),
        funnel=tuple(funnel(rows, c)),
        by_domain=tuple(performance(rows, "main_domain")),
        criteria=f.describe(),
        shortlisted=tuple(chosen[:25]),
        total_shortlisted=len(chosen),
    )


def _fmt(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:g}{unit}"


# --- progress: one student against the pass marks, and the batch around them --------------------


@dataclass(frozen=True)
class Step:
    """One stage of the placement journey, for a checklist with a progress bar."""

    label: str
    done: bool
    progress: float  # 0..1
    detail: str


def journey_steps(r: StudentRow, c: Cutoffs) -> list[Step]:
    """Resume scanned, plan started, quiz pass mark, voice pass mark: how far a student is on
    each, in the words the student and their admin both read."""

    def toward(value: float | None, mark: float, unit: str, noun: str) -> Step:
        got = 0.0 if value is None else value
        share = 1.0 if mark <= 0 else min(1.0, got / mark)
        shown = f"average {value:g}{unit}" if value is not None else "none yet"
        return Step(
            noun, value is not None and value >= mark, share, f"{shown}; pass mark {mark:g}{unit}"
        )

    return [
        Step(
            "Resume scanned",
            r.resume_match is not None,
            1.0 if r.resume_match is not None else 0.0,
            f"{r.resume_match:g}% match with the target role"
            if r.resume_match is not None
            else "scan the resume against the target role",
        ),
        Step(
            "Study plan started",
            r.tasks_done > 0,
            1.0 if r.tasks_done else 0.0,
            f"{r.tasks_done} task(s) ticked off"
            if r.tasks_done
            else "tick off day 1 of the roadmap",
        ),
        toward(r.quiz_average, c.quiz_pct, "%", "Quiz pass mark"),
        toward(r.rubric_average, c.voice_score, f"/{VOICE_RUBRIC_MAX}", "Voice pass mark"),
    ]


def percentile(rows: Sequence[StudentRow], r: StudentRow, minimum: int = 5) -> int | None:
    """The share (0-99) of the other students whose readiness is lower than this student's; None
    when they have none or the batch is too small (under `minimum`) for it to say anything."""
    if r.readiness is None or len(rows) < minimum:
        return None
    others = [o for o in rows if o.username != r.username]
    if not others:
        return None
    below = sum((o.readiness if o.readiness is not None else -1) < r.readiness for o in others)
    return min(99, round(below / len(others) * 100))


def tier_mix(rows: Sequence[StudentRow], c: Cutoffs) -> list[tuple[str, int]]:
    counts = Counter(tier(r, c) for r in rows if r.account_status != "suspended")
    return [(t, counts[t]) for t in TIERS]


def top_performers(rows: Sequence[StudentRow], n: int = 5) -> list[StudentRow]:
    assessed = [r for r in rows if r.readiness is not None and r.account_status != "suspended"]
    return sorted(assessed, key=lambda r: (-(r.readiness or 0), r.name.lower()))[:n]


def needs_attention(
    rows: Sequence[StudentRow], c: Cutoffs, now: datetime | None = None, n: int = 5
) -> list[tuple[StudentRow, str]]:
    """Students who are not ready and most need a nudge, lowest readiness first, each with the
    reason in words: not started, gone quiet, or low."""
    now = now or datetime.now(UTC)
    out = []
    for r in rows:
        if r.account_status == "suspended" or is_ready(r, c):
            continue
        if r.last_active is None and r.readiness is None:
            reason = "Has not started yet" + (" (invited)" if r.account_status == "invited" else "")
        elif r.last_active is not None and not is_active(r, now):
            reason = f"No quiz or voice session for {(now - r.last_active).days} days"
        elif r.readiness is not None and r.readiness < NEARLY_READY_AT:
            reason = f"Readiness {r.readiness:.0f}/100, under {NEARLY_READY_AT}"
        else:
            continue
        out.append((r, reason))
    return sorted(
        out, key=lambda t: (t[0].readiness if t[0].readiness is not None else -1, t[0].name)
    )[:n]


PROGRESS_COLUMNS = (
    ("Name", lambda r, c: r.name),
    ("Email", lambda r, c: r.email),
    ("Main domain", lambda r, c: r.main_domain or r.stream),
    ("Subdomain", lambda r, c: r.subdomain),
    ("Target role", lambda r, c: r.target_role),
    ("Account", lambda r, c: r.account_status),
    ("Tier", lambda r, c: tier(r, c)),
    ("Readiness (/100)", lambda r, c: r.readiness),
    ("Resume match (%)", lambda r, c: r.resume_match),
    ("Quizzes taken", lambda r, c: r.quizzes),
    ("Quiz average (%)", lambda r, c: r.quiz_average),
    ("Quiz pass mark met", lambda r, c: "Yes" if meets_quiz(r, c) else "No"),
    ("Voice sessions", lambda r, c: r.voice_sessions),
    (f"Voice average (/{VOICE_RUBRIC_MAX})", lambda r, c: r.rubric_average),
    ("Voice pass mark met", lambda r, c: "Yes" if meets_voice(r, c) else "No"),
    ("Proctor flags", lambda r, c: r.proctor_flags),
    ("Plan tasks done", lambda r, c: r.tasks_done),
    ("Last active (UTC)", lambda r, c: r.last_active.strftime("%Y-%m-%d") if r.last_active else ""),
    ("Missing skills", lambda r, c: "; ".join(r.missing_skills)),
)


def progress_report_csv(rows: Sequence[StudentRow], c: Cutoffs) -> bytes:
    """The whole batch's progress, one row per student, UTF-8 with a BOM; text cells are
    protected from formula injection."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([name for name, _ in PROGRESS_COLUMNS])
    for r in rows:
        w.writerow([cohort._cell(get(r, c)) for _, get in PROGRESS_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")


# --- PDFs ---------------------------------------------------------------------------------------


class _Report:
    """A small A4 report: title, headings, lines and tables in the product's colours. Text goes
    through resume_builder.pdf_safe (the built-in fonts are Latin-1 only)."""

    def __init__(self) -> None:
        from fpdf import FPDF

        from piq.resume_builder import pdf_safe

        self._safe = pdf_safe
        self.pdf = FPDF(format="A4")
        self.pdf.set_auto_page_break(True, margin=15)
        self.pdf.add_page()
        self.width = self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def title(self, text: str) -> None:
        self.pdf.set_font("Helvetica", "B", 18)
        self.pdf.set_text_color(26, 35, 38)
        self.pdf.cell(0, 10, self._safe(text), new_x="LMARGIN", new_y="NEXT")

    def heading(self, text: str) -> None:
        self.pdf.ln(3)
        self.pdf.set_font("Helvetica", "B", 12)
        self.pdf.set_text_color(13, 102, 112)
        self.pdf.cell(0, 8, self._safe(text), new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_text_color(26, 35, 38)

    def line(self, text: str, size: int = 10) -> None:
        self.pdf.set_font("Helvetica", "", size)
        self.pdf.set_text_color(26, 35, 38)
        self.pdf.multi_cell(self.width, 5.5, self._safe(text), new_x="LMARGIN", new_y="NEXT")

    def table(
        self, header: Sequence[str], body: Sequence[Sequence[str]], widths: Sequence[int]
    ) -> None:
        self.pdf.set_font("Helvetica", "", 9)
        with self.pdf.table(col_widths=tuple(widths), text_align="LEFT", line_height=6) as t:
            head = t.row()
            for h in header:
                head.cell(self._safe(h))
            for record in body:
                row = t.row()
                for cell in record:
                    row.cell(self._safe(cell))

    def bytes(self) -> bytes:
        return bytes(self.pdf.output())


def executive_summary_pdf(s: Summary) -> bytes:
    """One or two pages for a company's recruiters: who the organization is, how its students
    are doing, and who clears the drive's criteria."""
    p = _Report()
    p.title(f"{s.org_name} - Placement Shortlist")
    about = " | ".join(
        x for x in (s.org_type, s.location, f"Batch {s.batch}" if s.batch else "") if x
    )
    p.line(f"Organization: {s.org_name}  |  {about}  |  Generated {s.generated}", 10)
    p.line(
        f"Cutoffs Used: Quiz > {s.cutoffs.quiz_pct:g}%, "
        f"Voice > {s.cutoffs.voice_score:g}/{VOICE_RUBRIC_MAX}",
        10,
    )

    k = s.kpis
    p.heading("Where the batch stands")
    p.table(
        ["Enrolled", "Active (14 days)", "Avg resume match", "Avg quiz", "Avg voice", "Ready"],
        [
            [
                str(k.enrolled),
                str(k.active),
                _fmt(k.avg_resume_match, "%"),
                _fmt(k.avg_quiz, "%"),
                _fmt(k.avg_voice, f"/{VOICE_RUBRIC_MAX}"),
                str(k.ready),
            ]
        ],
        [15, 18, 20, 15, 16, 16],
    )
    p.line(
        f"Ready means an average quiz score of at least {s.cutoffs.quiz_pct:g}% and an average "
        f"voice rubric score of at least {s.cutoffs.voice_score:g}/{VOICE_RUBRIC_MAX}."
    )

    p.heading("Readiness funnel")
    p.table(
        ["Stage", "Students", "Of enrolled"],
        [[st.label, str(st.count), f"{st.of_enrolled:.0%}"] for st in s.funnel],
        [50, 25, 25],
    )

    if s.by_domain:
        p.heading("By main domain")
        p.table(
            ["Domain", "Students", "Readiness", "Parts"],
            [[d, str(n), f"{r:.0f}/100", detail] for d, n, r, detail in s.by_domain],
            [30, 18, 22, 80],
        )

    p.heading("Shortlist")
    p.line(f"Criteria: {s.criteria}.")
    more = " (top 25 shown)." if s.total_shortlisted > 25 else "."
    p.line(f"{s.total_shortlisted} student(s) meet them{more}")
    if s.shortlisted:
        p.table(
            ["Name", "Domain", "Target role", "Quiz", "Voice", "Readiness", "Proctor Breach"],
            [
                [
                    r.name,
                    f"{r.main_domain or r.stream} / {r.subdomain}".strip(" /"),
                    r.target_role,
                    _fmt(r.quiz_average, "%"),
                    _fmt(r.rubric_average, f"/{VOICE_RUBRIC_MAX}"),
                    _fmt(r.readiness),
                    "BREACH" if r.proctor_flags > 0 else "CLEARED",
                ]
                for r in s.shortlisted
            ],
            [30, 32, 40, 14, 15, 17, 22],
        )
    return p.bytes()


def student_report_pdf(
    org, r: StudentRow, d: Candidate360, c: Cutoffs, today: datetime | None = None
) -> bytes:  # type: ignore[no-untyped-def]
    """One student's progress report (for the student, their parents or a mentor): where they
    study, how they stand against the pass marks, their skills, plan, quizzes and voice
    sessions."""
    today = today or datetime.now(UTC)
    p = _Report()
    p.title("Student progress report")
    p.line(f"{org.name}  -  generated {today.strftime('%d %B %Y')}", 11)
    p.heading(r.name)
    p.line(
        f"{r.main_domain or r.stream} / {r.subdomain or '-'}  |  target role: {r.target_role}  |  "
        f"account: {r.account_status}  |  tier: {tier(r, c)}"
    )
    p.heading("Against the pass marks")
    steps = journey_steps(r, c)
    p.table(
        ["Stage", "Result", "Met"],
        [[s.label, s.detail, "Yes" if s.done else "Not yet"] for s in steps],
        [42, 110, 22],
    )
    ready = "yes" if is_ready(r, c) else "not yet"
    p.line(f"Readiness: {_fmt(r.readiness)}/100. Placement ready: {ready}.")
    if d.plans:
        p.heading("Study plan")
        p.table(
            ["Week", "Tasks done", "Of"],
            [[str(w.week), str(w.done), str(w.total)] for w in d.plans],
            [30, 40, 30],
        )
    if d.matched or d.missing:
        p.heading("Skills")
        p.line("On the resume: " + (", ".join(d.matched) or "none"))
        p.line("Still to build: " + (", ".join(d.missing) or "none"))
    if d.quizzes:
        p.heading("Quizzes (latest first)")
        p.table(
            ["Date", "Skill", "Level", "Score"],
            [
                [
                    q.when.strftime("%d %b %Y"),
                    q.skill,
                    q.difficulty,
                    f"{q.score}/{q.total} ({q.percent:g}%)",
                ]
                for q in d.quizzes[:12]
            ],
            [30, 70, 24, 40],
        )
    if d.voices:
        p.heading("Voice sessions (latest first)")
        p.table(
            ["Date", "Total", "Content", "Clarity", "Confidence", "Flags"],
            [
                [
                    v.when.strftime("%d %b %Y"),
                    f"{v.rubric}/{VOICE_RUBRIC_MAX}",
                    f"{v.content:g}/5",
                    f"{v.clarity:g}/5",
                    f"{v.confidence:g}/5",
                    str(len(v.flags)),
                ]
                for v in d.voices[:8]
            ],
            [28, 24, 24, 24, 28, 20],
        )
    return p.bytes()
