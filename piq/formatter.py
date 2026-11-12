"""Output layer: validated models / DB rows -> markdown and chart-ready DataFrames.

Pure functions, no Streamlit import, so every rendering decision is unit-testable.
"""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from piq import degrees, resume_builder, scorecard, syllabus
from piq.config import (
    BRAND_COLOR,
    DIFFICULTIES,
    DIFFICULTY_DOWN_BELOW,
    DIFFICULTY_UP_AT,
    PALETTE,
    TIMEZONE,
    TOPIC_PALETTE,
    VOICE_RUBRIC_MAX,
    WEAK_THRESHOLD,
)
from piq.schemas import (
    AnswerEvaluation,
    InterviewTurn,
    Question,
    QuizSet,
    StudentProfile,
    WeeklyPlan,
)

_CODE = re.compile(r"(```.*?```|`[^`\n]+`)", re.S)
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~$&=])")


def md_escape(text: str) -> str:
    """Show resume, LLM or user text literally wherever Streamlit renders Markdown.

    Inline `code` and fenced blocks are kept, so code in model answers stays readable
    (code is never interpreted as Markdown or HTML anyway).
    """
    parts = _CODE.split(text)
    return "".join(p if i % 2 else _MD_SPECIAL.sub(r"\\\1", p) for i, p in enumerate(parts))


# Every status shows an icon and words, never colour alone: state -> (icon, colour).
STATUS = {
    "done": ("check_circle", "green"),
    "todo": ("radio_button_unchecked", "gray"),
    "warning": ("warning", "yellow"),
    "error": ("error", "red"),
    "info": ("info", "blue"),
}


# An organization's readiness tiers (piq/org_insights.py) as status badges: state and words.
TIER_BADGE = {
    "Ready": ("done", "Ready"),
    "In Progress": ("info", "In progress"),
    "At Risk": ("warning", "At risk"),
}


def org_badge_md(org_name: str, main_domain: str | None, subdomain: str | None) -> str:
    """Which organization a student belongs to and where it placed them, for the sidebar and
    the progress card: 'Org name', then 'Commerce / Taxation & Audit'. Escaped."""
    where = " / ".join(x for x in (main_domain, subdomain) if x)
    place = f"  \n:gray[{md_escape(where)}]" if where else ""
    return f":material/apartment: **{md_escape(org_name)}**{place}"


def status_md(state: str, text: str) -> str:
    """An inline status badge in Markdown; `text` is escaped."""
    icon, color = STATUS[state]
    return f":{color}-badge[:material/{icon}: {md_escape(text)}]"


def _light_dark(light: str, dark: str) -> str:
    """A CSS colour that follows Streamlit's theme switch (it sets color-scheme on the app)."""
    return f"light-dark({light}, {dark})"


def topic_chip_html(topic: str) -> str:
    """A topic chip: the topic's colour as a dot next to its name (never colour alone)."""
    slot = syllabus.color_slot(topic)
    dot = (
        _light_dark(TOPIC_PALETTE["light"][slot], TOPIC_PALETTE["dark"][slot])
        if slot is not None and slot < len(TOPIC_PALETTE["light"])
        else "currentColor"
    )
    edge = _light_dark(PALETTE["light"]["hairline"], PALETTE["dark"]["hairline"])
    return (
        '<span style="display:inline-flex;align-items:center;gap:0.45em;padding:0.15em 0.7em;'
        f'border:1px solid {edge};border-radius:999px;font-size:0.875rem;line-height:1.5">'
        '<span aria-hidden="true" style="width:0.65em;height:0.65em;border-radius:50%;'
        f'background:{dot}"></span>{escape(topic)}</span>'
    )


_QUESTION_N = re.compile(r"\bquestion (\d+):")


def critic_text(msg: str) -> str:
    """A step or critic message for display: escaped, and the critic's 0-based
    "question N:" (a protocol checks.question_issues parses) shown as the quiz's "Q{N+1}:"."""
    return critic_plain(md_escape(msg))


def _bullets(items: Iterable[str], empty: str = "_none_") -> str:
    items = list(items)
    return "\n".join(f"- {md_escape(i)}" for i in items) if items else empty


# --- profile (Onboard) ----------------------------------------------------------------


def welcome_back_md(snap: Any) -> str:
    """Where a returning student left off (a journey.Snapshot), in one line."""
    parts = []
    if snap.scan:
        parts.append(f"last resume scan {snap.scan.match_percentage:.0f}% match")
    if snap.roadmap_week:
        parts.append(
            f"week {snap.roadmap_week} roadmap, {snap.tasks_done} of {snap.tasks_total} tasks done"
        )
    if snap.last_quiz:
        score, total = snap.last_quiz
        parts.append(f"{snap.quizzes} critic quiz(zes), last {score}/{total}")
    if snap.last_voice is not None:
        parts.append(
            f"{snap.voice_sessions} voice session(s), last {snap.last_voice}/{VOICE_RUBRIC_MAX}"
        )
    return "Welcome back. Where you left off: " + "; ".join(parts) + "."


def delete_warning_md(username: str, name: str) -> str:
    """What deleting an account costs, in plain words, before it happens."""
    return (
        f"This deletes the account **{md_escape(name)}** (@{md_escape(username)}) with every "
        "profile, plan, quiz and interview. It cannot be undone."
    )


def readiness_summary(p: StudentProfile) -> str:
    total = len(p.matched_skills) + len(p.missing_skills)
    role = md_escape(p.target_role)
    return (
        f"{len(p.matched_skills)} of the {total} skills {role} needs are named on the resume; "
        "skills the syllabus tests count double."
    )


def skill_chips(skills: Iterable[str], present: bool) -> str:
    """Skills as badges: a filled check for one on the resume, an empty circle for a
    missing one, so the difference never rests on colour alone."""
    state = "done" if present else "todo"
    return " ".join(status_md(state, s) for s in skills)


def list_md(items: Iterable[str], empty: str) -> str:
    return _bullets(items, f":gray[{empty}]")


def fixes_md(fixes: Iterable[str]) -> str:
    """Resume fixes as a to-do checklist. The boxes are grey: a list marker, not a control
    that looks clickable."""
    lines = [f":gray[:material/check_box_outline_blank:] {md_escape(f)}" for f in fixes]
    return "  \n".join(lines) or ":gray[Nothing to fix.]"


def plan_table(plan: WeeklyPlan) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Day": d.day,
                "Topic": d.topic,
                "Subtopics": ", ".join(d.subtopics),
                "Minutes": d.duration_min,
                "Goal": d.practice_goal,
            }
            for d in sorted(plan.days, key=lambda d: d.day)
        ]
    ).set_index("Day")


def plan_minutes(plans: Iterable[WeeklyPlan]) -> pd.DataFrame:
    """Rows = topics, columns = 'Week n', values = minutes. Feeds the week-vs-week chart."""
    data = {f"Week {p.week_no}": p.minutes_by_topic() for p in plans}
    topics = list(dict.fromkeys(t for minutes in data.values() for t in minutes))
    return pd.DataFrame(data, index=topics).fillna(0).astype(int)


# --- weekly plan -----------------------------------------------------------------------


def plan_summary(plan: WeeklyPlan) -> str:
    """One line under the week's title: the total and where most of it goes."""
    minutes = plan.minutes_by_topic()
    top = max(minutes, key=lambda t: minutes[t])
    return f"{sum(minutes.values())} minutes over {len(plan.days)} days, most of them on {top}."


def plan_csv(plan: WeeklyPlan) -> bytes:
    """The week as CSV (the table view's columns), with a BOM so Excel reads it as UTF-8."""
    return plan_table(plan).to_csv().encode("utf-8-sig")


def local_today(tz: str = TIMEZONE) -> date:
    """Today on the student's calendar."""
    return datetime.now(ZoneInfo(tz)).date()


def next_monday(today: date) -> date:
    """The default first day of an exported week: the coming Monday (today if it is one)."""
    return today + timedelta(days=-today.weekday() % 7)


def _ics_text(text: str) -> str:
    """RFC 5545 TEXT: escape backslash, semicolon, comma and line breaks."""
    for raw, escaped in (
        ("\\", "\\\\"),
        (";", "\\;"),
        (",", "\\,"),
        ("\r\n", "\\n"),
        ("\n", "\\n"),
    ):
        text = text.replace(raw, escaped)
    return text


def _ics_fold(line: str) -> str:
    """RFC 5545 3.1: a content line over 75 octets continues after CRLF and a space, never
    splitting a UTF-8 character."""
    chunks, current = [], b""
    for ch in line:
        encoded = ch.encode("utf-8")
        limit = 75 if not chunks else 74  # a continuation starts with a one-octet space
        if len(current) + len(encoded) > limit:
            chunks.append(current)
            current = encoded
        else:
            current += encoded
    chunks.append(current)
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def plan_ics(
    plan: WeeklyPlan, start: date, at: time, tz: str = TIMEZONE, now: datetime | None = None
) -> bytes:
    """The week as an iCalendar file: one event per day from `start`, at `at` on the
    student's clock (`tz`), as long as that day's minutes. Times are written in UTC, so no
    time-zone block is needed."""
    zone, stamp = ZoneInfo(tz), (now or datetime.now(UTC)).astimezone(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PlacementIQ//Weekly plan//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for d in sorted(plan.days, key=lambda d: d.day):
        local = datetime.combine(start + timedelta(days=d.day - 1), at, tzinfo=zone)
        begin = local.astimezone(UTC)
        end = begin + timedelta(minutes=d.duration_min)
        about = f"Week {plan.week_no}, day {d.day}. Goal: {d.practice_goal}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:week{plan.week_no}-day{d.day}-{start:%Y%m%d}@placementiq",
            f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}",
            f"DTSTART:{begin:%Y%m%dT%H%M%SZ}",
            f"DTEND:{end:%Y%m%dT%H%M%SZ}",
            f"SUMMARY:{_ics_text(f'{d.topic}: ' + ', '.join(d.subtopics))}",
            f"DESCRIPTION:{_ics_text(about)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_ics_fold(line) for line in lines) + "\r\n").encode("utf-8")


def plan_days_html(plan: WeeklyPlan, done: Collection[int] = ()) -> str:
    """The week day by day: day, topic chip, minutes, subtopics, goal and, for a day in
    `done`, the word "Done". One escaped HTML list (styled by static/app.css) rather than
    seven sets of widgets: it reads at any width and costs the page a single element."""
    rows = [
        '<li class="piq-day">'
        f'<span class="piq-day-n">Day {d.day}</span><div>'
        f'<div class="piq-day-head">{topic_chip_html(d.topic)}'
        f'<span class="piq-day-min">{d.duration_min} min</span>'
        + ('<span class="piq-done">Done</span>' if d.day in done else "")
        + "</div>"
        f"<div>{escape(' · '.join(d.subtopics))}</div>"
        f'<div class="piq-day-goal">Goal: {escape(d.practice_goal)}</div>'
        "</div></li>"
        for d in sorted(plan.days, key=lambda d: d.day)
    ]
    label = f"Week {plan.week_no}, day by day"
    return f'<ol class="piq-days" aria-label="{label}">{"".join(rows)}</ol>'


def days_done_md(week_no: int, done: int, total: int = 7) -> str:
    """A week's progress, in teal with an icon, as streaks and today's focus are."""
    return f":primary[:material/task_alt:] Week {week_no}: {done} of {total} days done."


def _topics_of(*minutes: Mapping[str, int]) -> list[str]:
    """Every topic in these weeks, in syllabus order (ties of the headline keep it)."""
    names = dict.fromkeys(t for m in minutes for t in m)
    return sorted(
        names, key=lambda t: (syllabus.color_slot(t) is None, syllabus.color_slot(t) or 0)
    )


def minutes_shift_headline(
    before: Mapping[str, int], after: Mapping[str, int], before_week: int
) -> str:
    """The week-over-week chart's takeaway: a new top topic, else the biggest gain and the
    biggest loss (the planner moves minutes from one topic to another)."""
    topics = _topics_of(before, after)
    old = {t: before.get(t, 0) for t in topics}
    new = {t: after.get(t, 0) for t in topics}
    change = {t: new[t] - old[t] for t in topics}
    leaders = [t for t in topics if new[t] == max(new.values())]
    if len(leaders) == 1 and old[leaders[0]] < max(old.values()):
        return f"{leaders[0]} now gets the most minutes"
    gain = max(topics, key=lambda t: change[t])
    loss = min(topics, key=lambda t: change[t])
    since = f"than in week {before_week}"
    if change[gain] > 0 and change[loss] < 0:
        return f"{gain} gets {change[gain]} more minutes and {loss} {-change[loss]} fewer {since}"
    if change[gain] > 0:
        return f"{gain} gets {change[gain]} more minutes {since}"
    if change[loss] < 0:
        return f"{loss} gets {-change[loss]} fewer minutes {since}"
    return f"The same minutes per topic as in week {before_week}"


def minutes_shift_alt(
    before: Mapping[str, int], after: Mapping[str, int], weeks: tuple[int, int]
) -> str:
    """The same chart in words, for screen readers."""
    topics = _topics_of(before, after)
    pairs = ", ".join(f"{t} {before.get(t, 0)} to {after.get(t, 0)}" for t in topics)
    return f"Minutes per topic, week {weeks[0]} to week {weeks[1]}: {pairs}"


def weakness_source() -> str:
    """Where the weakness numbers come from: the adaptive loop, in one sentence."""
    return (
        "Weakness is 100% minus your average over the last three quizzes on a topic. Before "
        "a topic's first quiz it is 70% if your resume lacks it, else 40%."
    )


# --- quiz ------------------------------------------------------------------------------


def topic_option(topic: str, weakness: float) -> str:
    """A topic in the quiz picker, with its weakness as the hint."""
    return f"{topic} · {weakness:.0%} weak"


def suggestion_md(topic: str, last: tuple[float, str] | None, suggested: str) -> str:
    """Why a difficulty is suggested: the latest score on the topic and the rule."""
    # Grey, not primary: Streamlit draws a primary badge in the dark primary, too faint.
    badge = f":gray-badge[:material/recommend: Suggested: {suggested}]"
    if last is None:
        return f"{badge} No {topic} quiz yet, so start at {suggested}."
    pct, difficulty = last
    return (
        f"{badge} Your last {topic} quiz: {pct:.0f}% on {difficulty}. "
        f"{DIFFICULTY_UP_AT}% or more moves you up a level; under {DIFFICULTY_DOWN_BELOW}%, down."
    )


def blanks_md(numbers: Sequence[int]) -> str:
    """Which questions are blank at submit, and the two ways on."""
    names = [f"Q{n}" for n in numbers]
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    verb = "has" if len(names) == 1 else "have"
    return (
        f"{listed} {verb} no answer. Answer and submit again, or submit anyway: a blank "
        "counts as wrong."
    )


def result_md(correct: int, total: int, topic: str, difficulty: str, next_difficulty: str) -> str:
    """The quiz outcome in one sentence: what the score changes next (difficulty and plan)."""
    step = DIFFICULTIES.index(next_difficulty) - DIFFICULTIES.index(difficulty)
    icon = {1: "trending_up", 0: "trending_flat", -1: "trending_down"}[step]
    return (
        f":primary[:material/{icon}:] {correct} of {total} correct, so the next suggested "
        f"difficulty is **{next_difficulty}**. The score also counts toward your {topic} "
        "weakness, which shapes next week's plan."
    )


def review_md(n: int, question: Question, chosen: int | None) -> str:
    """One reviewed question: right, wrong or unanswered as an icon and a word (never colour
    alone), the answers and the explanation."""
    if chosen is None:
        badge = status_md("todo", "Not answered")
    elif chosen == question.correct_index:
        badge = status_md("done", "Correct")
    else:
        badge = status_md("error", "Wrong")
    lines = [f"{badge} **Q{n}. {md_escape(question.text)}**"]
    if chosen is not None:
        lines.append(f"Your answer: {md_escape(question.options[chosen])}")
    if chosen != question.correct_index:
        lines.append(f"Correct answer: {md_escape(question.options[question.correct_index])}")
    lines.append(f":gray[{md_escape(question.explanation)}]")
    return "  \n".join(lines)


def quiz_review(quiz: QuizSet, chosen: Sequence[int | None]) -> list[str]:
    """Every question of a submitted quiz, reviewed; one answer per question is required."""
    pairs = zip(quiz.questions, chosen, strict=True)
    return [review_md(i, q, a) for i, (q, a) in enumerate(pairs, 1)]


def _quote(text: str) -> str:
    """Text as a Markdown quote, one line per line (escaped)."""
    lines = md_escape(text).splitlines() or [""]
    return "\n".join(f"> {line}  " if line.strip() else ">" for line in lines)


def quiz_notes(
    quiz: QuizSet, chosen: Sequence[int | None], score_pct: float, next_difficulty: str, day: date
) -> str:
    """A reviewed quiz as Markdown notes to keep (plain Markdown, no Streamlit directives;
    model text escaped so it reads literally in any viewer)."""
    correct = sum(a == q.correct_index for q, a in zip(quiz.questions, chosen, strict=True))
    out = [
        f"# {quiz.topic} quiz ({quiz.difficulty}), {day:%d %b %Y}",
        "",
        f"Score: {score_pct:.0f}% ({correct} of {len(quiz.questions)} correct). "
        f"Next suggested difficulty: {next_difficulty}.",
    ]
    for i, (q, a) in enumerate(zip(quiz.questions, chosen, strict=True), 1):
        mark = "not answered" if a is None else "correct" if a == q.correct_index else "wrong"
        out += ["", f"## Q{i}. {md_escape(q.text)}", ""]
        if a is not None:
            out.append(f"- Your answer ({mark}): {md_escape(q.options[a])}")
        else:
            out.append("- Your answer: none")
        if a != q.correct_index:
            out.append(f"- Correct answer: {md_escape(q.options[q.correct_index])}")
        out.append(f"- Why: {md_escape(q.explanation)}")
    return "\n".join(out) + "\n"


def interview_notes(
    interview_type: str,
    turns: Sequence[tuple[str, str, AnswerEvaluation]],
    day: date,
    tips: Mapping[str, str] | None = None,
) -> str:
    """An interview's questions, answers and feedback as Markdown notes to keep; `tips` are
    the session summary's (when it is finished)."""
    average = sum(ev.overall for *_, ev in turns) / len(turns) if turns else 0.0
    out = [
        f"# {interview_type} mock interview, {day:%d %b %Y}",
        "",
        f"Average {average:.1f}/5 over {len(turns)} questions.",
    ]
    if tips:
        out += ["", "## What to work on", ""]
        out += [f"- {name.title()}: {tip}" for name, tip in tips.items()]
    for i, (question, answer, ev) in enumerate(turns, 1):
        scores = " · ".join(f"{k.title()} {v}/5" for k, v in ev.scores.items())
        out += [
            "",
            f"## Q{i}. {md_escape(question)}",
            "",
            "Your answer:",
            "",
            _quote(answer),
            "",
            f"Scores: {scores} (overall {_out_of_5(ev.overall)})",
            "",
            f"**Strengths**\n{_bullets(ev.strengths, '- None this time.')}",
            "",
            f"**Improve**\n{_bullets(ev.improvements, '- Nothing to change.')}",
            "",
            "**Model answer**",
            "",
            _quote(ev.model_answer),
        ]
    return "\n".join(out) + "\n"


# --- mock interview -----------------------------------------------------------------------


def question_md(turn: InterviewTurn) -> str:
    """The interviewer's question with a quiet badge: a follow-up on the last answer, or new."""
    kind = ":gray-badge[:material/subdirectory_arrow_right: Follow-up]"
    if not turn.is_followup:
        kind = ":gray-badge[:material/add_comment: New question]"
    return f"{md_escape(turn.question)}  \n{kind}"


def interview_progress(answered: int, current: bool, max_turns: int) -> tuple[float, str]:
    """The session's position for a progress bar: its value and its words."""
    if not current and answered >= max_turns:
        return 1.0, f"All {max_turns} questions answered"
    n = min(answered + 1, max_turns)
    return n / max_turns, f"Question {n} of {max_turns}"


def feedback_title(ev: AnswerEvaluation) -> str:
    return f"**Feedback** · {ev.overall:.1f}/5 overall"


def _out_of_5(v: float) -> str:
    """A 0-5 score as shown: whole numbers plain ("4/5"), averages to one place ("3.4/5")."""
    return f"{v:.0f}/5" if float(v).is_integer() else f"{v:.1f}/5"


def criteria_html(scores: Mapping[str, float]) -> str:
    """The four rubric scores (one answer's, or a session's averages) as small bars, styled
    by static/app.css; the words and the number carry the score, the bar shows it at a
    glance."""
    rows = [
        '<div class="piq-criterion">'
        f"<span>{escape(name.title())}</span>"
        f'<span class="piq-bar" aria-hidden="true"><span style="width:{round(20 * v)}%">'
        f"</span></span><span>{_out_of_5(v)}</span></div>"
        for name, v in scores.items()
    ]
    return f'<div class="piq-criteria">{"".join(rows)}</div>'


def summary_md(averages: Mapping[str, float], strongest: str, weakest: str) -> str:
    """A finished interview's strongest and weakest criterion, in words."""
    if averages[strongest] == averages[weakest]:
        return f"Even across all four criteria: {_out_of_5(averages[strongest])} each."
    return (
        f"Strongest: **{strongest.title()}** ({_out_of_5(averages[strongest])}). "
        f"Weakest: **{weakest.title()}** ({_out_of_5(averages[weakest])})."
    )


def tips_md(tips: Mapping[str, str]) -> str:
    """One fixed tip per weak criterion; or that none is weak."""
    if not tips:
        return ":gray[No criterion averaged below 3/5. Keep answering the same way.]"
    return "\n".join(f"- **{name.title()}:** {tip}" for name, tip in tips.items())


def evaluation_md(ev: AnswerEvaluation) -> str:
    """What to keep, what to change and a model answer, quoted."""
    # Every line keeps its own line in the quote (a hard break): consecutive "> " lines
    # would otherwise run together into one paragraph.
    lines = md_escape(ev.model_answer).splitlines()
    quote = "\n".join(f"> {line}  " if line.strip() else ">" for line in lines)
    return (
        f"**Strengths**  \n{list_md(ev.strengths, 'None this time.')}\n\n"
        f"**Improve**  \n{list_md(ev.improvements, 'Nothing to change.')}\n\n"
        f"**Model answer**\n{quote}"
    )


# --- dashboard ----------------------------------------------------------------------------


TRENDS = {  # trend -> (badge colour, icon, words): never colour alone
    "improving": ("green", "trending_up", "Improving"),
    "steady": ("gray", "trending_flat", "Steady"),
    "slipping": ("yellow", "trending_down", "Slipping"),
    "new": ("gray", "more_horiz", "One quiz so far"),
}


def trend_md(trend: str) -> str:
    color, icon, words = TRENDS[trend]
    return f":{color}-badge[:material/{icon}: {words}]"


def mastery_line(topic: str, weakness: float, scores: Sequence[float]) -> str:
    """A topic card's first line: the topic, its weakness and its latest score."""
    latest = f" · {scores[-1]:.0f}% latest" if scores else " · no quiz yet"
    return f"**{topic}** :gray[· {weakness:.0%} weak{latest}]"


def topic_scores_headline(scores: Mapping[str, Sequence[float]]) -> str:
    """The quiz charts' takeaway: the biggest rise from a topic's first to its latest quiz."""
    moved = {t: s[-1] - s[0] for t, s in scores.items() if len(s) >= 2}
    if not moved:
        return "Take a second quiz on a topic to see it move"
    best = max(moved, key=lambda t: moved[t])
    first, latest = scores[best][0], scores[best][-1]
    if moved[best] > 0:
        return f"{best} is up from {first:.0f}% to {latest:.0f}%"
    worst = min(moved, key=lambda t: moved[t])
    if moved[worst] < 0:
        return f"{worst} is down from {scores[worst][0]:.0f}% to {scores[worst][-1]:.0f}%"
    return "Scores are level since your first quizzes"


def week_mix_headline(plans: Sequence[WeeklyPlan]) -> str:
    """The plan-minutes chart's takeaway: where the latest week's time goes."""
    latest = plans[-1].minutes_by_topic()
    top = max(latest, key=lambda t: latest[t])
    share = latest[top] / sum(latest.values())
    return f"Week {plans[-1].week_no} puts {share:.0%} of its minutes on {top}"


def plan_mix_alt(weeks: Mapping[int, Mapping[str, int]]) -> str:
    """The weekly-minutes chart in words, for screen readers."""
    parts = [
        f"week {w}: " + ", ".join(f"{t} {m}" for t, m in minutes.items() if m)
        for w, minutes in weeks.items()
    ]
    return "Minutes per topic by week. " + "; ".join(parts)


def local_day(timestamp: str, tz: str = TIMEZONE) -> str:
    """A SQLite UTC timestamp as a day on the student's calendar, e.g. "20 Oct"."""
    at = datetime.fromisoformat(timestamp).replace(tzinfo=UTC).astimezone(ZoneInfo(tz))
    return f"{at:%d %b}"


def session_labels(sessions: Iterable[Mapping], tz: str = TIMEZONE) -> list[str]:
    """Interview sessions for a tooltip: the day on the student's calendar and the type."""
    return [f"{local_day(s['started'], tz)}, {s['interview_type']}" for s in sessions]


def days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def streak_md(current: int, longest: int) -> str:
    """The study streak in words, with the primary teal and an icon (never a flame)."""
    if current == 0:
        return (
            f":primary[:material/event_available:] No study streak right now; your longest "
            f"was {days(longest)}."
        )
    if current == longest:
        return (
            f":primary[:material/event_available:] Study streak: **{days(current)}**, your longest."
        )
    return (
        f":primary[:material/event_available:] Study streak: **{days(current)}** "
        f"(longest {days(longest)})."
    )


def activity_headline(active_days: int, longest: int, weeks: int = 12) -> str:
    """The activity calendar's takeaway."""
    if not active_days:
        return f"No quizzes or interviews in the last {weeks} weeks"
    return (
        f"Active on {days(active_days)} in the last {weeks} weeks; longest streak {days(longest)}"
    )


def readiness_change(scores: Sequence[int]) -> tuple[str, str] | None:
    """The readiness KPI's delta and its colour: the latest profile minus the one before.
    None with a single profile: there is nothing to compare, so no delta is invented."""
    if len(scores) < 2:
        return None
    change = scores[-1] - scores[-2]
    if change == 0:
        return "±0 since the last profile", "off"
    return f"{change:+d} since the last profile", "normal"


def readiness_headline(scores: Sequence[int]) -> str:
    """The readiness chart's takeaway, first profile to latest."""
    first, latest, n = scores[0], scores[-1], len(scores)
    if n == 1:
        return f"Readiness is {latest}/100 from your first profile"
    verb = "rose" if latest > first else "fell" if latest < first else "held"
    if verb == "held":
        return f"Readiness held at {latest}/100 over {n} profiles"
    return f"Readiness {verb} from {first} to {latest} over {n} profiles"


def interview_headline(averages: Sequence[float]) -> str:
    """The interview chart's takeaway: the latest session against the one before."""
    latest = averages[-1]
    if len(averages) == 1:
        return f"Your first interview averaged {latest:.1f}/5"
    before = averages[-2]
    change = "up from" if latest > before else "down from" if latest < before else "level with"
    return f"Your latest interview averaged {latest:.1f}/5, {change} {before:.1f}"


def critic_plain(msg: str) -> str:
    """A critic message for a table (plain text): the 0-based "question N:" shown as "QN+1:"."""
    return _QUESTION_N.sub(lambda m: f"Q{int(m[1]) + 1}:", msg)


def agent_table(rows: Iterable[Mapping]) -> pd.DataFrame:
    """agent_stats rows -> one display row per agent; the rejection rate as a percentage."""
    data = [
        {
            "Agent": r["agent_name"].replace("_", " ").capitalize(),
            "Calls": r["calls"],
            "Avg latency (ms)": r["avg_latency_ms"],
            "Avg tokens": r["avg_tokens"],
            "Rejected drafts": r["rejections"],
            "Failed calls": r.get("failures"),  # absent from older summary.json files
            "Rejection rate": None if r["rejection_rate"] is None else 100 * r["rejection_rate"],
        }
        for r in map(dict, rows)
    ]
    df = pd.DataFrame(data, columns=AGENT_COLUMNS)
    if len(df) and df["Failed calls"].isna().all():  # a summary from before failures were counted
        df = df.drop(columns="Failed calls")
    return df


AGENT_COLUMNS = (
    "Agent",
    "Calls",
    "Avg latency (ms)",
    "Avg tokens",
    "Rejected drafts",
    "Failed calls",
    "Rejection rate",
)


def rejections_table(rows: Iterable[Mapping], tz: str = TIMEZONE) -> pd.DataFrame:
    """recent_rejections rows -> when (the student's clock), agent, attempt and the reason."""
    zone = ZoneInfo(tz)
    data = [
        {
            "When": datetime.fromisoformat(r["created_at"])
            .replace(tzinfo=UTC)
            .astimezone(zone)
            .strftime("%d %b, %H:%M"),
            "Agent": r["agent_name"].replace("_", " ").capitalize(),
            "Attempt": (r["retry_count"] or 0) + 1,
            "Critic's reason": critic_plain(r["reject_reason"] or ""),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=["When", "Agent", "Attempt", "Critic's reason"])


# --- evaluation results ------------------------------------------------------------

ATTEMPTS = "Avg quiz attempts"


def results_table(summary: Mapping) -> pd.DataFrame:
    """summary.json -> rows = metrics, columns = Baseline / PlacementIQ (NaN = not measured)."""
    b, p = summary.get("baseline") or {}, summary.get("placementiq") or {}
    rows: dict[str, tuple] = {
        "Plan valid rate": (b.get("plan_valid_rate"), p.get("plan_valid_rate")),
        "Quiz valid rate": (b.get("quiz_valid_rate"), p.get("quiz_valid_rate")),
        "Avg weak-topic share of minutes": (b.get("avg_weak_share"), p.get("avg_weak_share")),
    }
    if c := summary.get("consecutive"):
        rows[f"Duplicate rate over {c['quizzes_per_topic']} quizzes (lower is better)"] = (
            c["baseline_duplicate_rate"],
            c["placementiq_duplicate_rate"],
        )
    if iv := summary.get("interviews"):
        rows["Interview follow-up relevance"] = (None, iv["followup_relevance"])
    rows[ATTEMPTS] = (b.get("avg_quiz_attempts"), p.get("avg_quiz_attempts"))
    df = pd.DataFrame(rows, index=["Baseline", "PlacementIQ"], dtype=float).T
    return df.rename_axis("Metric")


@dataclass(frozen=True)
class Metric:
    """One comparison on the Results page: plain words, its direction, both systems' values
    (0-1 rates; None = not measured)."""

    name: str
    definition: str
    higher_is_better: bool
    baseline: float | None
    placementiq: float | None


# The two systems keep one colour each on the Results page (never a topic colour): a grey
# and the brand teal, both >= 3:1 on either background.
SYSTEM_COLORS = {"Baseline": PALETTE["light"]["border"], "PlacementIQ": BRAND_COLOR}


def results_metrics(summary: Mapping) -> list[Metric]:
    """The measured rates of a run_eval summary, each with its definition and direction."""
    b, p = summary.get("baseline") or {}, summary.get("placementiq") or {}
    out = [
        Metric(
            "Plan valid rate",
            "Share of weekly plans that pass every plan check: seven days for the right week, "
            "weak topics included with at least half the minutes, more minutes for weaker topics.",
            True,
            b.get("plan_valid_rate"),
            p.get("plan_valid_rate"),
        ),
        Metric(
            "Quiz valid rate",
            "Share of quizzes in which every question passes the question checks and the critic.",
            True,
            b.get("quiz_valid_rate"),
            p.get("quiz_valid_rate"),
        ),
        Metric(
            "Weak-topic share of minutes",
            "Average share of a week's study time that goes to the student's weak topics.",
            True,
            b.get("avg_weak_share"),
            p.get("avg_weak_share"),
        ),
    ]
    if c := summary.get("consecutive"):
        out.append(
            Metric(
                f"Repeated questions over {c['quizzes_per_topic']} quizzes",
                f"Share of questions that repeat an earlier one when a topic is quizzed "
                f"{c['quizzes_per_topic']} times in a row.",
                False,
                c["baseline_duplicate_rate"],
                c["placementiq_duplicate_rate"],
            )
        )
    if iv := summary.get("interviews"):
        out.append(
            Metric(
                "Interview follow-up relevance",
                "Share of follow-up questions that build on the candidate's last answer, as "
                "decided by a judge model. The baseline has no interviewer, so it is not measured.",
                True,
                None,
                iv["followup_relevance"],
            )
        )
    return out


def direction_md(higher_is_better: bool) -> str:
    """Which way is good, as a badge with an arrow and words."""
    if higher_is_better:
        return ":gray-badge[:material/arrow_upward: Higher is better]"
    return ":gray-badge[:material/arrow_downward: Lower is better]"


def compare_html(metric: Metric) -> str:
    """Both systems' values as labelled bars in their system colours (styled by app.css);
    a value that was not measured says so instead of drawing an empty bar."""
    rows = []
    for system, value in (("Baseline", metric.baseline), ("PlacementIQ", metric.placementiq)):
        if value is None:
            bar, shown = "", "Not measured"
        else:
            width = round(100 * min(max(float(value), 0.0), 1.0))
            bar = f'<span style="width:{width}%;background:{SYSTEM_COLORS[system]}"></span>'
            shown = f"{float(value):.0%}"
        rows.append(
            f'<div class="piq-criterion"><span>{system}</span>'
            f'<span class="piq-bar" aria-hidden="true">{bar}</span><span>{shown}</span></div>'
        )
    return f'<div class="piq-criteria">{"".join(rows)}</div>'


_STALE_WAIT = re.compile(r"\s*Try again (in about \d+ s|shortly)\.")


def results_caption(summary: Mapping) -> str:
    cases = (summary.get("placementiq") or {}).get("cases", 0)
    parts = [f"{md_escape(str(summary.get('mode', '?')))} run", f"{cases} cases"]
    if summary.get("errors"):
        parts.append(f"{summary['errors']} failed")
    if summary.get("stopped_early"):
        reason = _STALE_WAIT.sub("", str(summary["stopped_early"])).strip()  # long past
        parts.append(f"stopped early ({md_escape(reason)}); continue with --resume")
    return " · ".join(parts)


def results_note(summary: Mapping) -> str:
    """How to read the rates; names the duplicate-rate exception only when that row exists."""
    exception = " except the duplicate rate" if summary.get("consecutive") else ""
    return (
        f"In the table, rates run from 0 to 1; higher is better{exception}. "
        "Confirm quiz validity by hand with evaluation/results/questions.csv."
    )


def _md_table(df: pd.DataFrame) -> str:
    head = f"| {df.index.name or ''} | " + " | ".join(df.columns) + " |"
    rule = "|---" * (len(df.columns) + 1) + "|"
    body = [
        f"| {idx} | " + " | ".join("—" if pd.isna(v) else f"{v:.2f}" for v in row) + " |"
        for idx, row in df.iterrows()
    ]
    return "\n".join([head, rule, *body])


def results_md(summary: Mapping) -> str:
    table = results_table(summary)
    md = [
        "# Evaluation results",
        "",
        results_caption(summary),
        "",
        _md_table(table),
        "",
        "Rates run from 0 to 1. Both systems are judged by the same deterministic checks and "
        "LLM critic; quiz validity should also be confirmed by hand in `questions.csv`.",
    ]
    if summary.get("mode") == "mock":
        md += ["", "**MOCK_MODE results: not meaningful, smoke test only.**"]
    if stats := summary.get("agent_stats"):
        cols = ["agent_name", "calls", "avg_latency_ms", "avg_tokens", "rejection_rate"]
        df = pd.DataFrame(stats)[cols].set_index("agent_name").rename_axis("Agent")
        md += ["", "## Agent cost during the evaluation", "", _md_table(df.astype(float))]
    return "\n".join(md) + "\n"


def results_svg(table: pd.DataFrame) -> str:
    """Grouped horizontal bars for the 0-1 metrics; no plotting dependency needed."""
    rates = table.drop(index=ATTEMPTS, errors="ignore")
    colors = {"Baseline": "#80868b", "PlacementIQ": "#1a73e8"}
    left, bar_w, row_h = 330, 300, 56
    width, height = left + bar_w + 60, 44 + row_h * len(rates)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="Arial, sans-serif" font-size="13">',
        "<title>Baseline vs PlacementIQ</title>",
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    for k, (name, color) in enumerate(colors.items()):
        x = left + k * 140
        out.append(f'<rect x="{x}" y="10" width="12" height="12" fill="{color}"/>')
        out.append(f'<text x="{x + 18}" y="21">{name}</text>')
    for i, (metric, row) in enumerate(rates.iterrows()):
        y = 40 + i * row_h
        out.append(f'<text x="{left - 10}" y="{y + 24}" text-anchor="end">{escape(metric)}</text>')
        for j, system in enumerate(colors):
            v, by = row[system], y + 4 + j * 22
            if pd.isna(v):
                out.append(f'<text x="{left + 4}" y="{by + 14}" fill="#5f6368">not measured</text>')
                continue
            w = round(bar_w * float(v), 1)
            out.append(
                f'<rect x="{left}" y="{by}" width="{w}" height="18" fill="{colors[system]}"/>'
            )
            out.append(f'<text x="{left + w + 6}" y="{by + 14}">{float(v):.2f}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --- the critic loop, as a trail ----------------------------------------------------

FAILED = "failed: "  # prefix ui.run_agent gives a failure in the step log
# graph.Task names -> what the student sees being made
ARTEFACTS = {
    "quiz": "quiz",
    "planner": "plan",
    "profile": "profile",
    "interviewer": "next question",
}
_GENERATED = re.compile(r"^(\w+): generated \(attempt (\d+)\)$")
_REJECTED = re.compile(r"^critic rejected (\w+): (.*)$", re.S)
_APPROVED = re.compile(r"^critic approved (\w+)$")
_GAVE_UP = re.compile(r"^\w+: rejected after retries: ")


@dataclass(frozen=True)
class TrailStep:
    title: str  # plain words; also the step's status label
    reasons: tuple[str, ...] = ()  # Markdown, escaped: why the critic said no
    note: str = ""  # one quiet line: the attempt, or what happened
    failed: bool = False  # a rejection or a stop: shown in the error state


def trail_steps(events: Sequence[str]) -> list[TrailStep]:
    """The agent step log as a readable trail: generated, critic rejected (with the
    reasons), regenerated, then approved or stopped. Messages come from graph.run and
    ui.run_agent; a repeated rejection says so instead of repeating its reasons."""
    steps: list[TrailStep] = []
    previous: list[str] | None = None
    for msg in events:
        if m := _GENERATED.match(msg):
            verb = "Generated" if m[2] == "1" else "Regenerated"
            steps.append(TrailStep(f"{verb} the {_artefact(m[1])}", note=f"Attempt {m[2]}"))
        elif m := _REJECTED.match(msg):
            reasons, title = m[2].split("; "), f"Critic rejected the {_artefact(m[1])}"
            if reasons == previous:
                steps.append(TrailStep(title, note="Same reason as before.", failed=True))
            else:
                steps.append(TrailStep(title, tuple(critic_text(r) for r in reasons), failed=True))
            previous = reasons
        elif m := _APPROVED.match(msg):
            steps.append(
                TrailStep(f"Critic approved the {_artefact(m[1])}", note="Passed every check.")
            )
        elif msg.startswith(FAILED):
            error = msg.removeprefix(FAILED)
            if _GAVE_UP.match(error):
                steps.append(
                    TrailStep("Stopped", note="The critic rejected every attempt.", failed=True)
                )
            else:
                steps.append(TrailStep("Stopped", (critic_text(error),), failed=True))
        else:
            steps.append(TrailStep(critic_text(msg)))
    return steps


def _artefact(task: str) -> str:
    return ARTEFACTS.get(task, md_escape(task))


# --- home ---------------------------------------------------------------------------


def relative_day(at: datetime, now: datetime | None = None) -> str:
    """When something happened, by the student's calendar (TIMEZONE), not UTC's."""
    tz = ZoneInfo(TIMEZONE)
    local = at.astimezone(tz)
    days = ((now or datetime.now(UTC)).astimezone(tz).date() - local.date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    return f"{days} days ago" if days < 7 else f"{local.day} {local:%b}"


def weakness_headline(weakness: Mapping[str, float]) -> str:
    """The weakness chart's takeaway, stated as a sentence."""
    topic = max(weakness, key=lambda t: weakness[t])
    if weakness[topic] > WEAK_THRESHOLD:
        return f"{topic} is your weakest topic"
    return f"No weak topics; {topic} has the most room to grow"


def checklist_line(label: str, done: bool) -> str:
    """A checklist item: an icon and a word for its state, then the item (escaped)."""
    badge = status_md("done", "Done") if done else status_md("todo", "To do")
    return f"{badge} {md_escape(label)}"


def weakness_caption() -> str:
    return (
        f"0% is strong, 100% is weak; the dashed line marks a weak topic (above "
        f"{WEAK_THRESHOLD:.0%})."
    )


def weakness_alt(weakness: Mapping[str, float]) -> str:
    """The same chart in words, for screen readers."""
    ranked = sorted(weakness.items(), key=lambda kv: -kv[1])
    return "Weakness by topic, weakest first: " + ", ".join(f"{t} {w:.0%}" for t, w in ranked)


# --- syllabus ---------------------------------------------------------------------------


def topic_chips_html(topics: Iterable[str]) -> str:
    """Several topic chips that wrap as a row."""
    chips = "".join(topic_chip_html(t) for t in topics)
    return f'<div style="display:flex;flex-wrap:wrap;gap:0.4em">{chips}</div>'


def syllabus_line(domain_name: str, role: str) -> str:
    """Whose syllabus the page shows, in grey (Markdown, escaped)."""
    return f":gray[:material/school: {md_escape(domain_name)} · {md_escape(role)}]"


def locked_md(domain_name: str, since: str, by: str | None = None) -> str:
    """Why the domain cannot change, and since when (`by`: the organization that set it)."""
    if by:
        return (
            f":material/lock: Your domain is **{md_escape(domain_name)}**, set by "
            f"{md_escape(by)}. You can still change role within it."
        )
    return (
        f":material/lock: Your domain is locked to **{md_escape(domain_name)}** since your "
        f"first saved resume ({local_day(since)}): your plans, quizzes and progress are built on "
        "its syllabus. You can still change role within it."
    )


# --- quiz over several topics ----------------------------------------------------------


def topic_pick_label(topic: str, weakness: float | None) -> str:
    """A topic in the quiz picker: its weakness when tracked, else that it is new to you."""
    return f"{topic} · new" if weakness is None else topic_option(topic, weakness)


def mix_md(mix: Mapping[str, int]) -> str:
    """The difficulty mix in words, easy to hard."""
    return " · ".join(f"{d.capitalize()} {mix.get(d, 0)}%" for d in DIFFICULTIES)


def spec_table(parts: Sequence[tuple[str, str, int]]) -> pd.DataFrame:
    """A quiz setup as questions per topic (rows) and difficulty (columns), with totals."""
    topics = list(dict.fromkeys(t for t, _, _ in parts))
    df = pd.DataFrame(0, index=topics, columns=[d.capitalize() for d in DIFFICULTIES])
    for topic, difficulty, n in parts:
        df.loc[topic, difficulty.capitalize()] = n
    df["Total"] = df.sum(axis=1)
    df.loc["All topics"] = df.sum(axis=0)
    return df.rename_axis("Topic")


def spec_note(total: int, batches: int, mock: bool = False) -> str:
    """How the quiz is made: its size, the batches the critic checks and the wait."""
    if batches <= 1:
        return f"{total} questions, written and checked by the critic in one go."
    wait = "" if mock else " On the free AI tier a large quiz takes a few minutes."
    return (
        f"{total} questions, written in {batches} batches of up to 10; the critic checks "
        f"each batch and rewrites any flawed question.{wait}"
    )


def run_title(topics: Sequence[str]) -> str:
    named = ", ".join(topics[:3]) + (f" and {len(topics) - 3} more" if len(topics) > 3 else "")
    return f"Quiz on {named}"


def run_result_md(correct: int, wrong: int, skipped: int, total: int) -> str:
    """The run's outcome in one sentence, with icons and words."""
    parts = [f"**{correct}** of {total} correct", f"{wrong} wrong"]
    if skipped:
        parts.append(f"{skipped} left blank")
    return (
        f":primary[:material/task_alt:] {', '.join(parts)}. Each topic's score counts toward "
        "its weakness in next week's plan."
    )


def next_difficulty_md(next_by_topic: Mapping[str, str]) -> str:
    """Each topic's suggested next difficulty, as a short list."""
    return "  \n".join(
        f":material/trending_flat: {md_escape(t)}: next try **{d}**"
        for t, d in next_by_topic.items()
    )


def outcome_rows(outcomes: Iterable) -> list[tuple[str, int, int, int]]:
    """services.Outcome -> chart rows (label, correct, wrong, skipped); labels capitalised."""
    return [(o.label[:1].upper() + o.label[1:], o.correct, o.wrong, o.skipped) for o in outcomes]


def outcome_alt(title: str, outcomes: Iterable) -> str:
    """An outcome chart in words, for screen readers."""
    return f"{title}: " + "; ".join(
        f"{o.label} {o.correct} correct, {o.wrong} wrong, {o.skipped} blank" for o in outcomes
    )


def grid_table(grid: Mapping[tuple[str, str], object]) -> pd.DataFrame:
    """(topic, difficulty) -> Outcome as a table: "7/10 (70%)" per cell, "—" for none."""
    topics = list(dict.fromkeys(t for t, _ in grid))
    rows = {}
    for t in topics:
        rows[t] = {
            d.capitalize(): (
                f"{o.correct}/{o.total} ({o.pct:.0f}%)" if (o := grid.get((t, d))) else "—"
            )
            for d in DIFFICULTIES
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("Topic")


def mistake_md(n: int, topic: str, difficulty: str, question: Question, chosen: int | None) -> str:
    """A question answered wrong or left blank: where it came from, then the review."""
    head = f":gray[{md_escape(topic)} · {difficulty}]"
    return f"{head}  \n{review_md(n, question, chosen)}"


def run_notes(
    parts: Sequence[QuizSet], chosen: Sequence[int | None], score_pct: float, day: date
) -> str:
    """A reviewed multi-part quiz as Markdown notes to keep, part by part."""
    total = sum(len(p.questions) for p in parts)
    flat = [(p, q) for p in parts for q in p.questions]
    correct = sum(a == q.correct_index for (_, q), a in zip(flat, chosen, strict=True))
    out = [
        f"# {run_title(list(dict.fromkeys(p.topic for p in parts)))}, {day:%d %b %Y}",
        "",
        f"Score: {score_pct:.0f}% ({correct} of {total} correct).",
    ]
    n = 0
    for p in parts:
        out += ["", f"## {md_escape(p.topic)} ({p.difficulty})"]
        for q in p.questions:
            a = chosen[n]
            n += 1
            mark = "not answered" if a is None else "correct" if a == q.correct_index else "wrong"
            out += ["", f"### Q{n}. {md_escape(q.text)}", ""]
            out.append(
                f"- Your answer ({mark}): {md_escape(q.options[a])}"
                if a is not None
                else "- Your answer: none"
            )
            if a != q.correct_index:
                out.append(f"- Correct answer: {md_escape(q.options[q.correct_index])}")
            out.append(f"- Why: {md_escape(q.explanation)}")
    return "\n".join(out) + "\n"


# --- dashboard: quizzes and accuracy -------------------------------------------------------


def runs_table(rows: Iterable[Mapping], tz: str = TIMEZONE) -> pd.DataFrame:
    """quiz_runs rows -> when, topics, questions and score."""
    data = [
        {
            "When": local_day(r["attempted_at"], tz),
            "Topics": (r["topics"] or "").replace(",", ", "),
            "Questions": r["total"],
            "Correct": r["correct"],
            "Score (%)": round(float(r["score_pct"])),
        }
        for r in rows
    ]
    return pd.DataFrame(data, columns=["When", "Topics", "Questions", "Correct", "Score (%)"])


def accuracy_headline(cells: Iterable[tuple[str, str, int, int]]) -> str:
    """The accuracy grid's takeaway: how the share correct changes from easy to hard."""
    by_level: dict[str, list[int]] = {d: [0, 0] for d in DIFFICULTIES}
    for _, d, c, n in cells:
        by_level[d][0] += c
        by_level[d][1] += n
    seen = {d: c / n for d, (c, n) in by_level.items() if n}
    if not seen:
        return "Answer a quiz to see your accuracy by difficulty"
    if len(seen) == 1:
        ((d, share),) = seen.items()
        return f"You answer {share:.0%} of {d} questions correctly"
    first, last = next(iter(seen)), list(seen)[-1]
    return (
        f"You get {seen[first]:.0%} of {first} questions right and {seen[last]:.0%} of {last} ones"
    )


# --- resume versions and advice --------------------------------------------------------


def _names(items: Sequence[str]) -> str:
    return ", ".join(md_escape(i) for i in items)


def diff_md(diff: object, before: int) -> str:
    """What changed since version `before`, as short lines (Markdown, escaped)."""
    lines = []
    if diff.role_changed:
        old, new = diff.role_changed
        lines.append(f":material/swap_horiz: Role: {md_escape(old)} → {md_escape(new)}")
    if diff.skills_added:
        lines.append(f":material/add_circle: Skills added: {_names(diff.skills_added)}")
    if diff.skills_removed:
        lines.append(f":material/remove_circle: Skills removed: {_names(diff.skills_removed)}")
    if diff.projects_added:
        lines.append(f":material/add_circle: Projects added: {_names(diff.projects_added)}")
    if diff.projects_removed:
        lines.append(f":material/remove_circle: Projects removed: {_names(diff.projects_removed)}")
    if diff.certifications_added:
        names = _names(diff.certifications_added)
        lines.append(f":material/add_circle: Certifications added: {names}")
    if diff.experience_added:
        lines.append(f":material/work: Experience added: {_names(diff.experience_added)}")
    if diff.experience_removed:
        lines.append(
            f":material/remove_circle: Experience removed: {_names(diff.experience_removed)}"
        )
    if diff.education_added:
        lines.append(f":material/school: Education added: {_names(diff.education_added)}")
    if diff.ats_change:
        lines.append(f":material/trending_flat: ATS score {diff.ats_change:+d}")
    if not lines:
        return f":gray[No change from version {before}.]"
    return f"**Since version {before}**  \n" + "  \n".join(lines)


def advice_lines(advice: object, today: date) -> list[str]:
    """What to add to the resume next, most useful first (Markdown, escaped)."""
    lines = []
    for m in advice.mastered:
        lines.append(
            f":material/verified: You average **{m.pct:.0f}%** on {md_escape(m.topic)} over "
            f"{m.quizzes} quizzes: add {_names(m.skills)}, ideally inside a project that uses them."
        )
    for name in advice.projects_to_add:
        lines.append(
            f":material/folder_open: {md_escape(name)} is marked done in your Project space "
            "but is not on the resume yet."
        )
    if advice.missing_keywords:
        lines.append(
            ":material/key: Role keywords not on the resume yet: "
            f"{_names(advice.missing_keywords[:6])}. Add only those you can show in a project."
        )
    if advice.review_on:
        since = (
            f"Since your last version you finished {days(advice.plan_days_since)} of your plan "
            f"and took {advice.quizzes_since} quiz{'zes' if advice.quizzes_since != 1 else ''}."
        )
        when = (
            "Review it now." if advice.due(today) else f"Next review on {advice.review_on:%d %b}."
        )
        lines.append(f":material/event: {since} {when}")
    return lines


def resume_filename(name: str, role: str) -> str:
    """A safe PDF file name from the student's name and role."""
    slug = re.sub(r"[^a-z0-9]+", "_", f"{name or 'resume'} {role}".lower()).strip("_")
    return f"{slug or 'resume'}.pdf"


# ---------------------------------------------------------------------------
# ATS keyword categorisation helpers
# ---------------------------------------------------------------------------

# A curated map of common skill→category for the ATS preview panel.
# Skills not in the map stay in "Core Competencies" (the catch-all).
_FRAMEWORKS: frozenset[str] = frozenset(
    {
        "react",
        "angular",
        "vue",
        "next.js",
        "django",
        "flask",
        "fastapi",
        "spring",
        "spring boot",
        "express",
        "node.js",
        "pytorch",
        "tensorflow",
        "keras",
        "scikit-learn",
        "pandas",
        "numpy",
        "bootstrap",
        "tailwind",
        "junit",
        "pytest",
        "jest",
        "hibernate",
        "laravel",
        "rails",
        "asp.net",
        "redux",
        ".net",
        "hadoop",
        "spark",
        "kafka",
    }
)

_TOOLS: frozenset[str] = frozenset(
    {
        "git",
        "github",
        "gitlab",
        "docker",
        "kubernetes",
        "jenkins",
        "terraform",
        "aws",
        "azure",
        "gcp",
        "linux",
        "postman",
        "jira",
        "confluence",
        "figma",
        "vscode",
        "mysql",
        "postgresql",
        "mongodb",
        "redis",
        "elasticsearch",
        "sqlite",
        "firebase",
        "nginx",
        "ansible",
        "maven",
        "gradle",
        "npm",
        "pnpm",
        "yarn",
        "cmake",
        "makefile",
        "heroku",
        "netlify",
        "vercel",
    }
)

_ACTION_VERB_LIST: frozenset[str] = frozenset(
    {
        "architected",
        "engineered",
        "designed",
        "developed",
        "implemented",
        "optimized",
        "deployed",
        "automated",
        "spearheaded",
        "authored",
        "analyzed",
        "reduced",
        "improved",
        "scaled",
        "modeled",
        "simulated",
        "directed",
        "built",
        "programmed",
        "integrated",
        "migrated",
        "refactored",
        "orchestrated",
        "containerised",
        "containerized",
        "benchmarked",
        "mentored",
        "delivered",
        "shipped",
        "launched",
        "configured",
        "documented",
        "maintained",
    }
)


def categorise_skills(
    skills: list[str],
) -> dict[str, list[str]]:
    """Split a flat skill list into the four ATS resume categories.

    Returns a dict with keys: 'Core Competencies', 'Frameworks',
    'Tools', 'Action Verbs'. Skills appear in exactly one
    category; unlisted ones go to 'Core Competencies'.
    """
    categories: dict[str, list[str]] = {
        "Core Competencies": [],
        "Frameworks": [],
        "Tools": [],
        "Action Verbs": [],
    }
    for s in skills:
        low = s.lower()
        if low in _ACTION_VERB_LIST:
            categories["Action Verbs"].append(s)
        elif low in _TOOLS:
            categories["Tools"].append(s)
        elif low in _FRAMEWORKS:
            categories["Frameworks"].append(s)
        else:
            categories["Core Competencies"].append(s)
    return {k: v for k, v in categories.items() if v}


def _bold_keywords(text: str, keywords: list[str]) -> str:
    """Bold every occurrence of each keyword in `text` (case-insensitive, boundary-aware)."""
    for kw in sorted(keywords, key=len, reverse=True):  # longest first avoids partial matches
        if not kw.strip():
            continue
        text = re.sub(
            rf"(?<![A-Za-z0-9_*])({re.escape(kw)})(?![A-Za-z0-9_*])",
            r"**\1**",
            text,
            flags=re.IGNORECASE,
        )
    return text


def ats_categorised_skills_md(
    skills: list[str],
    matched_keywords: list[str] | None = None,
) -> str:
    """The ATS-formatted skills panel: skills grouped by category, matched keywords bolded."""
    cats = categorise_skills(skills)
    matched_set = {k.lower() for k in (matched_keywords or [])}
    lines = []
    for cat, items in cats.items():
        formatted = []
        for s in items:
            if s.lower() in matched_set:
                formatted.append(f"**{md_escape(s)}**")
            else:
                formatted.append(md_escape(s))
        lines.append(f"**{cat}:** {', '.join(formatted)}")
    return "  \n".join(lines) if lines else "—"


def ats_resume_preview_md(
    res: Mapping,
    matched_keywords: list[str] | None = None,
) -> str:
    """The built resume as an ATS-optimised Markdown preview.

    Matches and bolds target role keywords from data/role_skills.json in every
    bullet point and groups skills into ATS categories: Core Competencies, Frameworks,
    Tools, and Action Verbs.
    """
    target_role = str(res.get("target_role", "")).strip()
    role_kws: list[str] = []
    if target_role:
        try:
            from piq import syllabus

            role_kws = list(syllabus.role_skills().get(target_role, {}).keys())
        except Exception:
            pass
    kws = list(dict.fromkeys([*(matched_keywords or []), *role_kws]))
    # Header
    out = [
        f"### {md_escape(res['full_name'])}",
        f"**{md_escape(res['target_role'])}**",
        f":gray[{md_escape(res['contact_line'])}]",
        "---",
        f"**Professional Summary**  \n{md_escape(res['summary'])}",
        "---",
        f"**Skills**  \n{ats_categorised_skills_md(res.get('skills', []), kws)}",
    ]
    # Work experience with keyword bolding
    jobs = resume_builder.experience_entries(res)
    if jobs:
        out.append("---\n**Work Experience**")
    for e in jobs:
        bullets = "\n".join(f"- {_bold_keywords(md_escape(b), kws)}" for b in e["bullets"])
        when = " · ".join(x for x in (e["type"], resume_builder.job_dates(e)) if x)
        head = f"**{md_escape(resume_builder.job_label(e))}** :gray[{md_escape(when)}]"
        out.append(f"{head}\n\n{bullets}" if bullets else head)
    # Projects with keyword bolding
    if res.get("projects"):
        out.append("---\n**Projects**")
    for p in res.get("projects", []):
        bullets = "\n".join(f"- {_bold_keywords(md_escape(b), kws)}" for b in p["bullets"])
        tech_line = f" :gray[{md_escape(p['tech'])}]" if p.get("tech") else ""
        out.append(f"**{md_escape(p['title'])}**{tech_line}\n\n{bullets}")
    # Education
    lines = []
    for e in resume_builder.education_entries(res):
        detail = ", ".join(
            x for x in (e.get("institution", ""), resume_builder.education_dates(e)) if x
        )
        score = f" · {e['score']}" if e.get("score") else ""
        name = degrees.entry_label({**e, "status": "Completed"})
        extra = f" :gray[{md_escape(detail + score)}]" if detail or score else ""
        lines.append(f"{md_escape(name)}{extra}")
    out.append("---\n**Education**  \n" + ("  \n".join(lines) or "—"))
    if res.get("certifications"):
        certs = "  \n".join(md_escape(c) for c in res["certifications"])
        out.append(f"---\n**Certifications**  \n{certs}")
    return "\n\n".join(out)


def github_intelligence_md(intel: object) -> str:
    """A compact card for the GitHub README extraction result."""
    lines = [
        f"#### :material/hub: {md_escape(intel.project_title)}",
        f":gray[{md_escape(intel.one_line_pitch)}]",
    ]
    if intel.tech_stack:
        lines.append("**Tech stack:** " + ", ".join(f"`{md_escape(t)}`" for t in intel.tech_stack))
    if intel.star_bullets:
        lines.append("**STAR bullets (copy to resume):**")
        for b in intel.star_bullets:
            lines.append(f"- {md_escape(b)}")
    if intel.viva_questions:
        lines.append("**Viva questions saved for your voice interview:**")
        for i, q in enumerate(intel.viva_questions, 1):
            lines.append(f"**Q{i}.** {md_escape(q)}")
    return "  \n".join(lines)


def resume_preview_md(res: Mapping) -> str:
    """The built resume as Markdown, section by section; every value escaped."""
    out = [
        f"### {md_escape(res['full_name'])}",
        f"**{md_escape(res['target_role'])}** · {md_escape(res['contact_line'])}",
        f"**Summary**  \n{md_escape(res['summary'])}",
        f"**Skills**  \n{md_escape(', '.join(res['skills'])) or '—'}",
    ]
    jobs = resume_builder.experience_entries(res)
    if jobs:
        out.append("**Work experience**")
    for e in jobs:
        bullets = "\n".join(f"- {md_escape(b)}" for b in e["bullets"])
        when = " · ".join(x for x in (e["type"], resume_builder.job_dates(e)) if x)
        head = f"**{md_escape(resume_builder.job_label(e))}** :gray[{md_escape(when)}]"
        out.append(f"{head}\n\n{bullets}" if bullets else head)
    for p in res["projects"]:
        bullets = "\n".join(f"- {md_escape(b)}" for b in p["bullets"])
        out.append(f"**{md_escape(p['title'])}** :gray[{md_escape(p['tech'])}]\n\n{bullets}")
    lines = []
    for e in resume_builder.education_entries(res):
        detail = ", ".join(
            x for x in (e.get("institution", ""), resume_builder.education_dates(e)) if x
        )
        score = f" · {e['score']}" if e.get("score") else ""
        name = degrees.entry_label({**e, "status": "Completed"})
        extra = f" :gray[{md_escape(detail + score)}]" if detail or score else ""
        lines.append(f"{md_escape(name)}{extra}")
    out.append("**Education**  \n" + ("  \n".join(lines) or "—"))
    if res.get("certifications"):
        certs = "  \n".join(md_escape(c) for c in res["certifications"])
        out.append(f"**Certifications**  \n{certs}")
    return "\n\n".join(out)


DEGREE_FIT = {
    "now": ("done", "Your degree fits this role"),
    "on completion": ("info", "Your degree fits once completed"),
    "no match": ("warning", "None of your degrees fits this role"),
}


def degree_fit_md(fit: str) -> str:
    """The ATS check's degree line: an icon and words, never colour alone."""
    state, text = DEGREE_FIT[fit]
    return status_md(state, text)


def role_fits_md(fits: Sequence) -> str:
    """Roles a student's degrees qualify for, grouped by domain: an icon and words say whether
    each is open now or once the degree being pursued is completed (Markdown, escaped)."""
    if not fits:
        return ":gray[No role in the catalog lists this degree and specialisation yet.]"
    by_domain: dict[str, list] = {}
    for f in fits:
        by_domain.setdefault(f.domain_name, []).append(f)
    blocks = []
    for name, items in by_domain.items():
        rows = []
        for f in items:
            if f.eligible_now:
                state = status_md("done", "Eligible now")
            else:
                state = status_md("info", f"On completion of {f.via}")
            rows.append(f"- {md_escape(f.role)} {state}")
        blocks.append(f"**{md_escape(name)}**\n\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def versions_table(versions: Iterable, tz: str = TIMEZONE) -> pd.DataFrame:
    data = [
        {
            "Version": v.n,
            "Saved": local_day(v.created_at, tz),
            "Role": v.target_role,
            "ATS score": v.ats_score,
            "Skills": len(v.resume.get("skills", [])),
            "Jobs": len(resume_builder.experience_entries(v.resume)),
            "Projects": len(v.resume.get("projects", [])),
        }
        for v in versions
    ]
    return pd.DataFrame(
        data, columns=["Version", "Saved", "Role", "ATS score", "Skills", "Jobs", "Projects"]
    ).set_index("Version")


# --- project space ---------------------------------------------------------------------

PROJECT_STATUS = {"Idea": "todo", "In progress": "info", "Done": "done"}


def project_head_md(row: Mapping) -> str:
    """A repository card's first lines: its name (linked when it has a repository), status
    as an icon and a word, and its one-line description."""
    name = md_escape(row["name"])
    title = f"[**{name}**]({row['repo_url']})" if row["repo_url"] else f"**{name}**"
    badge = status_md(PROJECT_STATUS.get(row["status"], "todo"), row["status"])
    first = next((ln for ln in row["summary"].splitlines() if ln.strip()), "")
    desc = f"  \n:gray[{md_escape(first.strip('-*• ').strip())}]" if first else ""
    return f"{title} {badge}{desc}"


def project_meta_md(row: Mapping, updates: int) -> str:
    """Stack, resume use and activity, in one grey line."""
    bits = []
    if row["tech"]:
        bits.append(f":material/code: {md_escape(row['tech'])}")
    bits.append(":material/description: on resume" if row["on_resume"] else "not on resume")
    bits.append(f":material/commit: {updates} update{'s' if updates != 1 else ''}")
    bits.append(
        f"updated {relative_day(datetime.fromisoformat(row['updated_at']).replace(tzinfo=UTC))}"
    )
    return ":gray[" + " · ".join(bits) + "]"


def update_line_md(row: Mapping) -> str:
    when = relative_day(datetime.fromisoformat(row["created_at"]).replace(tzinfo=UTC))
    return f":material/commit: {md_escape(row['note'])} :gray[· {when}]"


def readme_md(text: str) -> str:
    """A README shown literally: escaped, line breaks kept."""
    return "  \n".join(md_escape(line) for line in text.splitlines()) or ":gray[No README yet.]"


# --- evaluation scorecard ----------------------------------------------------------------


def score_text(score: float | None) -> str:
    return "—" if score is None else f"{score:.1f}/10"


def rating_md(score: float | None) -> str:
    """A 0-10 score's rating as a badge: an icon and a word."""
    word, state = scorecard.rating(score)
    return status_md(state, word)


def raw_value(value: float | None, unit: str) -> str:
    """A parameter's measured value in its unit."""
    if value is None:
        return "Not measured"
    if unit == "seconds":
        return f"{value:.1f} s"
    if unit == "tokens":
        return f"{value:,.0f} tokens"
    return f"{value:.0%}"


def scorecard_compare_html(param: object) -> str:
    """Both systems' scores as labelled bars out of 10 in their system colours, each with
    its measured value (styled by app.css, as compare_html)."""
    rows = []
    for system, value, score in (
        ("Baseline", param.baseline, param.baseline_score),
        ("PlacementIQ", param.placementiq, param.placementiq_score),
    ):
        if score is None:
            bar, shown = "", "Not measured"
        else:
            width = round(10 * min(max(score, 0.0), 10.0))
            bar = f'<span style="width:{width}%;background:{SYSTEM_COLORS[system]}"></span>'
            shown = f"{score:.1f}/10 · {escape(raw_value(value, param.unit))}"
        rows.append(
            f'<div class="piq-criterion"><span>{system}</span>'
            f'<span class="piq-bar" aria-hidden="true">{bar}</span><span>{shown}</span></div>'
        )
    return f'<div class="piq-criteria">{"".join(rows)}</div>'


def scorecard_table(card: object) -> pd.DataFrame:
    """Every parameter: group, both raw values and both scores."""
    data = [
        {
            "Group": p.group,
            "Parameter": p.name,
            "Weight": p.weight,
            "Baseline": raw_value(p.baseline, p.unit),
            "Baseline score": p.baseline_score,
            "PlacementIQ": raw_value(p.placementiq, p.unit),
            "PlacementIQ score": p.placementiq_score,
        }
        for p in card.parameters
    ]
    return pd.DataFrame(data).set_index("Parameter")


# --- study library (plan page) ----------------------------------------------------------------


def book_md(book: dict, fills: Sequence[str] = ()) -> str:
    """One recommended book: title, author, edition, level, why, and its links."""
    links = " · ".join(f"[{md_escape(link['label'])}]({link['url']})" for link in book["links"])
    weak = f" · **fills weak topic: {md_escape(', '.join(fills))}**" if fills else ""
    return (
        f"**{md_escape(book['title'])}**, {md_escape(book['author'])}  \n"
        f"{md_escape(book['edition'])} · {book['level']}{weak}  \n"
        f"{md_escape(book['why'])}  \n"
        f"{links}"
    )


def repo_md(repo: dict) -> str:
    """One curated repository: name and link, level, estimated hours, why it helps."""
    hours = f"about {repo['hours']:,} h" if repo["hours"] else "reference list"
    return (
        f"**[{repo['repo']}]({repo['url']})** · {repo['level']} · {hours}  \n"
        f"{md_escape(repo['why'])}"
    )
