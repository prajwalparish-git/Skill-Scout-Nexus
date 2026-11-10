"""Evaluation scorecard: the last run_eval judged on advanced parameters, each scored 0-10.

Every parameter comes from what the evaluation recorded (summary.json and the per-case CSVs
cases.csv, questions.csv and interviews.csv); nothing is measured again. Each states what it
measures, how, and the formula that turns the raw value into a score out of 10, so a rating
can be checked by hand. A parameter that cannot be computed (a missing CSV, a system without
an interviewer) is left out or marked not measured, never guessed. Pure: no Streamlit.
"""

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

PIQ_AGENTS = ("critic", "interviewer", "planner", "profile", "quiz")
BASELINE_AGENTS = ("baseline", "baseline_quiz")
DAILY_TOKENS = 200_000  # Groq free tier, per model per day (CLAUDE.md)

# score -> (rating, status state for formatter.STATUS); first match wins
RATINGS = ((9.0, "Excellent", "done"), (7.0, "Good", "done"), (5.0, "Fair", "warning"))
LOW = ("Needs work", "error")


@dataclass(frozen=True)
class Parameter:
    key: str
    name: str
    group: str
    what: str  # what it measures and why it matters
    method: str  # how it is computed, including the score formula
    unit: str  # "rate" (0-1), "seconds" or "tokens"
    higher_is_better: bool
    weight: float
    baseline: float | None  # raw values; None = not measured
    placementiq: float | None
    baseline_score: float | None  # 0-10
    placementiq_score: float | None
    note: str = ""


@dataclass(frozen=True)
class Scorecard:
    parameters: list[Parameter]

    def groups(self) -> list[str]:
        return list(dict.fromkeys(p.group for p in self.parameters))

    def overall(self, system: str, head_to_head: bool = False) -> float | None:
        """Weighted mean score (0-10) over the parameters measured for `system`; with
        `head_to_head`, only over those measured for both systems (a fair comparison)."""
        pairs = []
        for p in self.parameters:
            both = p.baseline_score is not None and p.placementiq_score is not None
            score = p.baseline_score if system == "baseline" else p.placementiq_score
            if score is not None and (both or not head_to_head):
                pairs.append((score, p.weight))
        if not pairs:
            return None
        return round(sum(s * w for s, w in pairs) / sum(w for _, w in pairs), 1)


def rating(score: float | None) -> tuple[str, str]:
    """(word, status state) for a 0-10 score."""
    if score is None:
        return "Not measured", "todo"
    for floor, word, state in RATINGS:
        if score >= floor:
            return word, state
    return LOW


def _clamp10(x: float) -> float:
    return round(10 * min(max(x, 0.0), 1.0), 1)


def _score(fn: Callable[[float], float], value: float | None) -> float | None:
    return None if value is None else _clamp10(fn(value))


def _bool(v: object) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def _int(v: object, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except ValueError:
        return default


def _rows(rows: Sequence[Mapping], system: str) -> list[Mapping]:
    return [r for r in rows if r.get("system") == system]


def first_draft_validity(cases: Sequence[Mapping], kind: str) -> float | None:
    """PlacementIQ: share of cases whose `kind` ("plan" or "quiz") was valid on attempt 1,
    i.e. before the critic sent anything back."""
    rows = _rows(cases, "placementiq")
    if not rows:
        return None
    ok = sum(_bool(r[f"{kind}_valid"]) and _int(r[f"{kind}_attempts"], 1) == 1 for r in rows)
    return round(ok / len(rows), 3)


def answer_key_balance(questions: Sequence[Mapping], system: str) -> float | None:
    """Normalised entropy (0-1) of the marked answer's position over A-D: 1 when the right
    answer is spread evenly, lower when one position is favoured (a cue test-takers learn)."""
    marks = [_int(r.get("marked"), -1) for r in _rows(questions, system)]
    counts = Counter(m for m in marks if 0 <= m <= 3)
    n = sum(counts.values())
    if n == 0:
        return None
    entropy = -sum(c / n * math.log(c / n) for c in counts.values())
    return round(entropy / math.log(4), 3)


def longest_answer_cue(questions: Sequence[Mapping], system: str) -> float | None:
    """Share of questions whose correct option is strictly the longest: a classic item-writing
    flaw, since guessing the longest option then pays. About 25% happens by chance."""
    rows = _rows(questions, system)
    flagged = total = 0
    for r in rows:
        options = [o.strip() for o in str(r.get("options", "")).split("||")]
        marked = _int(r.get("marked"), -1)
        if len(options) != 4 or not 0 <= marked <= 3:
            continue
        total += 1
        lengths = [len(o) for o in options]
        flagged += lengths[marked] == max(lengths) and lengths.count(max(lengths)) == 1
    return round(flagged / total, 3) if total else None


def human_validity(questions: Sequence[Mapping], system: str) -> float | None:
    """Share of hand-labelled questions marked valid (label_valid y/n); None if none labelled."""
    labels = [str(r.get("label_valid (y/n)", "")).strip().lower() for r in _rows(questions, system)]
    labelled = [x for x in labels if x in {"y", "n"}]
    return round(labelled.count("y") / len(labelled), 3) if labelled else None


def followup_precision(interviews: Sequence[Mapping]) -> float | None:
    """Of the questions the interviewer flagged as follow-ups, the share the judge agreed
    build on the candidate's answer."""
    flagged = [r for r in interviews if _bool(r.get("flagged_followup"))]
    if not flagged:
        return None
    return round(sum(_bool(r.get("references_answer")) for r in flagged) / len(flagged), 3)


def _stats(summary: Mapping) -> dict[str, Mapping]:
    return {s["agent_name"]: s for s in summary.get("agent_stats") or []}


def call_success(summary: Mapping, agents: Sequence[str]) -> float | None:
    stats = _stats(summary)
    calls = sum(stats[a]["calls"] for a in agents if a in stats)
    if not calls:
        return None
    failures = sum(stats[a].get("failures") or 0 for a in agents if a in stats)
    return round(1 - failures / calls, 3)


def cost_per_valid_quiz(summary: Mapping, field: str) -> dict[str, float | None]:
    """Average `field` ("avg_latency_ms" or "avg_tokens") one valid quiz costs each system.
    PlacementIQ: (quiz call + its share of critic calls) x quiz attempts per approved quiz,
    over the quiz valid rate. Baseline: one quiz call (the quiz-only prompt when it was
    measured) over its quiz valid rate, since invalid quizzes are thrown away."""
    stats = _stats(summary)
    b, p = summary.get("baseline") or {}, summary.get("placementiq") or {}
    out: dict[str, float | None] = {"baseline": None, "placementiq": None}
    base = stats.get("baseline_quiz") or stats.get("baseline")
    if base and b.get("quiz_valid_rate"):
        out["baseline"] = base[field] / b["quiz_valid_rate"]
    quiz, critic = stats.get("quiz"), stats.get("critic")
    if quiz and p.get("quiz_valid_rate") and p.get("avg_quiz_attempts"):
        critic_share = critic["calls"] / quiz["calls"] * critic[field] if critic else 0
        out["placementiq"] = (
            (quiz[field] + critic_share) * p["avg_quiz_attempts"] / p["quiz_valid_rate"]
        )
    return out


def build(
    summary: Mapping,
    cases: Sequence[Mapping] = (),
    questions: Sequence[Mapping] = (),
    interviews: Sequence[Mapping] = (),
) -> Scorecard:
    b, p = summary.get("baseline") or {}, summary.get("placementiq") or {}
    out: list[Parameter] = []

    def add(
        key: str,
        name: str,
        group: str,
        what: str,
        method: str,
        values: tuple[float | None, float | None],
        to_score: Callable[[float], float],
        *,
        unit: str = "rate",
        higher: bool = True,
        weight: float = 1.0,
        note: str = "",
    ) -> None:
        if values == (None, None):
            return
        out.append(
            Parameter(
                key,
                name,
                group,
                what,
                method,
                unit,
                higher,
                weight,
                values[0],
                values[1],
                _score(to_score, values[0]),
                _score(to_score, values[1]),
                note,
            )
        )

    rate = lambda v: v  # noqa: E731 - the identity score: a 0-1 rate times 10

    # --- planning
    add(
        "plan_valid",
        "Plan validity",
        "Planning",
        "Whether a weekly plan obeys every rule a coach would: seven days for the right week, "
        "weak topics present with at least half the minutes, more minutes for weaker topics.",
        "Share of the frozen cases whose final plan passes every deterministic plan check. "
        "Score = 10 x rate.",
        (b.get("plan_valid_rate"), p.get("plan_valid_rate")),
        rate,
        weight=2,
    )
    add(
        "weak_focus",
        "Weak-topic focus",
        "Planning",
        "How much of the week goes to what the student is weakest at: the core of an "
        "adaptive plan.",
        "Average share of a plan's minutes on weak topics. The rule asks for 50%; 75% or more "
        "scores 10 and 25% or less scores 0. Score = 10 x (share - 0.25) / 0.5.",
        (b.get("avg_weak_share"), p.get("avg_weak_share")),
        lambda v: (v - 0.25) / 0.5,
    )
    add(
        "plan_first_draft",
        "First-draft plan validity",
        "Planning",
        "How good the planner is on its own, before the critic sends a draft back. A high "
        "value means fewer retries, so less waiting and fewer tokens.",
        "PlacementIQ: share of cases valid on the first attempt (cases.csv). The baseline "
        "only ever writes one draft, so its value is its plan validity. Score = 10 x rate.",
        (b.get("plan_valid_rate"), first_draft_validity(cases, "plan")),
        rate,
    )

    # --- quiz quality
    add(
        "quiz_valid",
        "Quiz validity",
        "Quiz quality",
        "Whether every question in a quiz has exactly one defensible answer, distinct options "
        "and stays on topic: one bad question teaches the wrong thing.",
        "Share of quizzes in which every question passes the deterministic checks and the "
        "LLM critic. Score = 10 x rate.",
        (b.get("quiz_valid_rate"), p.get("quiz_valid_rate")),
        rate,
        weight=2,
    )
    if c := summary.get("consecutive"):
        add(
            "novelty",
            "Question novelty",
            "Quiz quality",
            f"Whether a student who takes {c['quizzes_per_topic']} quizzes in a row on one "
            "topic keeps getting new questions, or the same ones reworded.",
            "1 - share of questions that repeat an earlier one (normalised text hash). "
            "Score = 10 x (1 - duplicate rate).",
            (1 - c["baseline_duplicate_rate"], 1 - c["placementiq_duplicate_rate"]),
            rate,
        )
    add(
        "quiz_first_draft",
        "First-draft quiz validity",
        "Quiz quality",
        "How often the quiz writer gets a whole quiz right before any critic feedback.",
        "PlacementIQ: share of cases whose quiz was valid on attempt 1 (cases.csv). Baseline: "
        "its quiz validity (it has one attempt). Score = 10 x rate.",
        (b.get("quiz_valid_rate"), first_draft_validity(cases, "quiz")),
        rate,
    )
    add(
        "key_balance",
        "Answer-key balance",
        "Quiz quality",
        "Whether the right answer is spread over options A to D. A favoured position is a "
        "cue that lets students score without knowing the topic.",
        "Normalised entropy of the marked option's position over every generated question "
        "(questions.csv): 1 is perfectly even. Score = 10 x entropy.",
        (answer_key_balance(questions, "baseline"), answer_key_balance(questions, "placementiq")),
        rate,
        weight=0.5,
    )
    add(
        "longest_cue",
        "Longest-answer cue",
        "Quiz quality",
        "How often the right answer is also the longest option, a classic item-writing flaw "
        "that rewards guessing.",
        "Share of questions whose correct option is strictly the longest (questions.csv); "
        "about 25% happens by chance. At or below 25% scores 10, 75% scores 0. "
        "Score = 10 x (1 - (share - 0.25) / 0.5).",
        (longest_answer_cue(questions, "baseline"), longest_answer_cue(questions, "placementiq")),
        lambda v: 1 - (v - 0.25) / 0.5,
        higher=False,
        weight=0.5,
    )
    add(
        "human_valid",
        "Hand-checked validity",
        "Quiz quality",
        "A person's verdict on each question, the check the automatic critic stands in for.",
        "Share of questions labelled y in questions.csv's label_valid column. Score = 10 x rate.",
        (human_validity(questions, "baseline"), human_validity(questions, "placementiq")),
        rate,
        weight=2,
    )

    # --- interview
    if iv := summary.get("interviews"):
        add(
            "followup",
            "Follow-up relevance",
            "Interview",
            "Whether the interviewer's next question builds on what the candidate just said, "
            "as a real interviewer does, instead of reading from a list.",
            "Share of follow-up questions a judge model found to reference the last answer. "
            "Score = 10 x rate.",
            (None, iv.get("followup_relevance")),
            rate,
            note="The baseline has no interviewer.",
        )
    add(
        "followup_precision",
        "Follow-up flag precision",
        "Interview",
        "When the interviewer says a question is a follow-up, is it really one? Honest flags "
        "keep the transcript and the feedback trustworthy.",
        "Of the questions flagged is_followup, the share the judge agreed reference the "
        "answer (interviews.csv). Score = 10 x rate.",
        (None, followup_precision(interviews)),
        rate,
        weight=0.5,
        note="The baseline has no interviewer.",
    )

    # --- reliability and cost
    add(
        "success",
        "Call success rate",
        "Reliability and cost",
        "How often an AI call returns something usable. Failures are mostly the free tier's "
        "rate limit; each one makes a student wait or retry.",
        "1 - failed calls / calls over each system's agents (agent_stats). 50% or less "
        "scores 0. Score = 10 x (rate - 0.5) / 0.5.",
        (call_success(summary, BASELINE_AGENTS), call_success(summary, PIQ_AGENTS)),
        lambda v: (v - 0.5) / 0.5,
    )
    seconds = {
        k: v / 1000 if v is not None else None
        for k, v in cost_per_valid_quiz(summary, "avg_latency_ms").items()
    }
    add(
        "latency",
        "Seconds per valid quiz",
        "Reliability and cost",
        "How long a student waits for a quiz they can trust, counting the critic and every "
        "retry, and dividing by the share of quizzes that come out valid.",
        "From agent_stats latencies, quiz attempts and quiz validity (see the code's "
        "cost_per_valid_quiz). 10 s or less scores 10, 60 s scores 0. "
        "Score = 10 x (1 - (s - 10) / 50).",
        (_round(seconds["baseline"]), _round(seconds["placementiq"])),
        lambda v: 1 - (v - 10) / 50,
        unit="seconds",
        higher=False,
        weight=0.5,
    )
    tokens = cost_per_valid_quiz(summary, "avg_tokens")
    piq_tokens = tokens["placementiq"]
    add(
        "tokens",
        "Tokens per valid quiz",
        "Reliability and cost",
        "What a trustworthy quiz costs in AI quota. On the free tier (about "
        f"{DAILY_TOKENS:,} tokens a day) this sets how many quizzes a day the app can serve"
        + (f": about {DAILY_TOKENS // piq_tokens:.0f} for PlacementIQ." if piq_tokens else "."),
        "Same formula as seconds per valid quiz, on tokens. 2,000 or fewer score 10, "
        "10,000 score 0. Score = 10 x (1 - (tokens - 2000) / 8000).",
        (_round(tokens["baseline"], 0), _round(piq_tokens, 0)),
        lambda v: 1 - (v - 2000) / 8000,
        unit="tokens",
        higher=False,
        weight=0.5,
    )
    return Scorecard(out)


def _round(v: float | None, digits: int = 1) -> float | None:
    return None if v is None else round(v, digits)
