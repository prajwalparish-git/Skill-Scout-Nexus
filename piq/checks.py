"""Deterministic rules: weakness scoring and the zero-cost first stage of the critic.

Every `check_*` returns a list of human-readable rejection reasons; empty means approved.
The reasons are fed back verbatim into the regeneration prompt.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping

from piq.config import SYLLABUS_SKILL_WEIGHT, TOPICS, WEAK_MIN_SHARE, WEAK_THRESHOLD
from piq.schemas import (
    ExperienceScreen,
    InterviewTurn,
    ProfileExtraction,
    QuizSet,
    TailoredResume,
    WeeklyPlan,
)

_QUESTION_REASON = re.compile(r"^question (\d+): (.*)$", re.S)


def question_reason(index: int, message: str) -> str:
    return f"question {index}: {message}"


def question_issues(reasons: list[str]) -> dict[int, list[str]] | None:
    """index -> messages when every reason concerns a single question, else None."""
    issues: dict[int, list[str]] = {}
    for r in reasons:
        m = _QUESTION_REASON.match(r)
        if m is None:
            return None
        issues.setdefault(int(m[1]), []).append(m[2])
    return issues or None


def text_hash(text: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


_WORD_BREAK = re.compile(r"[^a-z0-9+#]+")  # "C++" and "C#" keep their symbols


def tokens(text: str) -> list[str]:
    """Lower-case words, splitting on everything but letters, digits, "+" and "#", so
    "Node.js", "CI/CD" and "Object-Oriented" compare word by word."""
    return [t for t in _WORD_BREAK.split(text.lower()) if t]


def _same_word(a: str, b: str) -> bool:
    """Equal, or one is the other's plural ("algorithm" / "algorithms")."""
    return a == b or a + "s" == b or b + "s" == a or a + "es" == b or b + "es" == a


def evidenced(skill: str, words: list[str], aliases: Iterable[str] = ()) -> bool:
    """Does the text (as `tokens`) name `skill` or one of its aliases, as whole words?"""
    for phrase in (skill, *aliases):
        p = tokens(phrase)
        if not p:
            continue
        for i in range(len(words) - len(p) + 1):
            if all(_same_word(p[j], words[i + j]) for j in range(len(p))):
                return True
    return False


def readiness_score(required: Mapping[str, str | None], matched: Iterable[str]) -> int:
    """0-100: the weighted share of the role's required skills that are matched. A skill
    practised under a syllabus topic weighs SYLLABUS_SKILL_WEIGHT, a tool skill 1."""
    weight = {s: SYLLABUS_SKILL_WEIGHT if t else 1 for s, t in required.items()}
    total = sum(weight.values())
    got = sum(weight[s] for s in set(matched) if s in weight)
    return round(100 * got / total) if total else 0


def topic_weakness(
    scores: dict[str, float], missing_topics: set[str], topics: Iterable[str] = TOPICS
) -> dict[str, float]:
    """0 = strong, 1 = weak, for each of the student's `topics` (syllabus.tracked_topics).
    Quiz evidence wins; otherwise fall back to resume gaps."""
    out = {}
    for t in topics:
        if t in scores:
            out[t] = round(1 - scores[t] / 100, 2)
        else:
            out[t] = 0.7 if t in missing_topics else 0.4
    return out


def weak_topics(weakness: dict[str, float]) -> list[str]:
    return sorted(
        (t for t, w in weakness.items() if w > WEAK_THRESHOLD), key=lambda t: -weakness[t]
    )


def check_profile(ext: ProfileExtraction, required: list[str]) -> list[str]:
    reasons = []
    if not ext.skills:
        reasons.append("skills is empty; extract every technical skill mentioned in the resume")
    allowed = {s.lower() for s in required}
    unknown = [s for s in ext.matched_skills if s.lower() not in allowed]
    if unknown:
        reasons.append(
            f"matched_skills must be chosen only from the required list; invalid: {unknown}"
        )
    return reasons


def check_plan(plan: WeeklyPlan, week_no: int, weakness: dict[str, float]) -> list[str]:
    reasons = []
    if plan.week_no != week_no:
        reasons.append(f"week_no must be {week_no}, got {plan.week_no}")
    if sorted(d.day for d in plan.days) != list(range(1, 8)):
        reasons.append("days must be numbered 1 to 7 exactly once each")
    unknown = sorted({d.topic for d in plan.days} - set(weakness))
    if unknown:
        reasons.append(
            f"topics {unknown} are not in this student's syllabus; use only: {list(weakness)}"
        )
        return reasons  # the minute rules below need every topic's weakness
    minutes = plan.minutes_by_topic()
    weak = weak_topics(weakness)
    if weak:
        absent = [t for t in weak if t not in minutes]
        if absent:
            reasons.append(f"weak topics missing from the plan: {absent}")
        share = sum(minutes.get(t, 0) for t in weak) / sum(minutes.values())
        if share < WEAK_MIN_SHARE:
            reasons.append(
                f"weak topics {weak} get {share:.0%} of total minutes; "
                f"they must get at least {WEAK_MIN_SHARE:.0%}"
            )
    # Among scheduled topics, minutes must not decrease as weakness increases (ties are free).
    inversions = sorted(
        (
            (a, b)
            for a in minutes
            for b in minutes
            if weakness[a] > weakness[b] and minutes[a] < minutes[b]
        ),
        key=lambda p: weakness[p[1]] - weakness[p[0]],
    )
    if inversions:
        pairs = "; ".join(
            f"{a} ({weakness[a]:.2f}) {minutes[a]} < {b} ({weakness[b]:.2f}) {minutes[b]}"
            for a, b in inversions[:3]
        )
        reasons.append(
            f"minutes must not decrease as weakness increases: {pairs}; "
            "a weaker topic must never get fewer minutes than a less-weak one"
        )
    return reasons


def check_quiz(
    quiz: QuizSet, topic: str, difficulty: str, count: int, previous: list[str]
) -> list[str]:
    reasons = []
    if quiz.topic != topic:
        reasons.append(f"topic must be {topic}, got {quiz.topic}")
    if quiz.difficulty != difficulty:
        reasons.append(f"difficulty must be {difficulty}, got {quiz.difficulty}")
    if len(quiz.questions) != count:
        reasons.append(f"exactly {count} questions required, got {len(quiz.questions)}")
    seen = {text_hash(t) for t in previous}
    for i, q in enumerate(quiz.questions):
        if len({o.strip().lower() for o in q.options}) < 4:
            reasons.append(question_reason(i, "options are not distinct"))
        h = text_hash(q.text)
        if h in seen:
            reasons.append(
                question_reason(i, f"duplicate of an earlier question ({q.text[:60]!r})")
            )
        seen.add(h)
    return reasons


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def check_bullet(original: str, rewrite: str) -> list[str]:
    """A rewrite may rephrase, never invent: every number in it must be in the original."""
    reasons = []
    known = {n.replace(",", "") for n in _NUMBER.findall(original)}
    invented = sorted({n for n in _NUMBER.findall(rewrite) if n.replace(",", "") not in known})
    if invented:
        reasons.append(
            f"numbers {invented} are not in the original bullet; use only its numbers or "
            "write [metric] where a measure belongs"
        )
    if "\n" in rewrite.strip():
        reasons.append("return one bullet on one line")
    if text_hash(rewrite) == text_hash(original):
        reasons.append("rewrite the bullet in XYZ form; it came back unchanged")
    return reasons


def invented_numbers(source: str, text: str) -> list[str]:
    """Numbers in `text` that `source` does not contain (1,200 and 1200 count as the same)."""
    known = {n.replace(",", "") for n in _NUMBER.findall(source)}
    return sorted({n for n in _NUMBER.findall(text) if n.replace(",", "") not in known})


def _only_removed(original: str, screened: str) -> bool:
    """Every word of `screened` is a word of `original` or the [name] placeholder."""
    known = {w.lower() for w in re.findall(r"[\w']+", original)} | {"name"}
    return all(w.lower() in known for w in re.findall(r"[\w']+", screened))


def check_screen(inp: Mapping, out: ExperienceScreen) -> list[str]:
    """A screen may replace names with [name] and add flags; it may never add or change text."""
    reasons = []
    if len(out.questions) != len(inp["questions"]):
        reasons.append(f"return all {len(inp['questions'])} questions, in order")
    for n, (before, after) in enumerate(zip(inp["questions"], out.questions, strict=False), 1):
        if not _only_removed(before, after):
            reasons.append(f"question {n}: only replace names with [name]; add no words")
    if not _only_removed(inp["tip"], out.tip):
        reasons.append("tip: only replace names with [name]; add no words")
    if any(len(f) > 200 for f in out.flags):
        reasons.append("keep each flag under 200 characters")
    return reasons


def check_tailoring(inp: Mapping, out: TailoredResume) -> list[str]:
    """A tailored resume may reorder and reword, never add, drop or invent: each entry keeps
    exactly its own bullets (by number), each bullet only its own numbers, and the summary only
    numbers that are somewhere in the resume."""
    reasons = []
    entries: Mapping[str, list[str]] = inp["entries"]
    if bad := invented_numbers(inp["corpus"], out.summary):
        reasons.append(f"summary: numbers {bad} are not in the resume; do not add figures")
    if "\n" in out.summary.strip():
        reasons.append("summary: one paragraph, no line breaks")
    for e in out.entries:
        original = entries.get(e.id)
        if original is None:
            reasons.append(f"{e.id} is not an entry of this resume; use only the ids given")
            continue
        ns = sorted(b.n for b in e.bullets)
        if ns != list(range(1, len(original) + 1)):
            reasons.append(
                f"{e.id}: return each of its {len(original)} bullets exactly once (numbers "
                f"1-{len(original)}); none added or dropped"
            )
            continue
        for b in e.bullets:
            if bad := invented_numbers(original[b.n - 1], b.text):
                reasons.append(f"{e.id} bullet {b.n}: numbers {bad} are not in that bullet")
            if "\n" in b.text.strip():
                reasons.append(f"{e.id} bullet {b.n}: one line only")
    return reasons


def check_turn(turn: InterviewTurn, asked: list[str]) -> list[str]:
    reasons = []
    if turn.question.count("?") > 2:
        reasons.append("ask exactly one question per turn")
    if text_hash(turn.question) in {text_hash(q) for q in asked}:
        reasons.append(f"question already asked: {turn.question[:80]!r}")
    return reasons
