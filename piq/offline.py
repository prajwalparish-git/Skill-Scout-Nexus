"""Layer 3's last tier: deterministic answers built from data/ when no AI provider answers.

piq/llm.py calls `respond` when every provider is unset, resting or down (and
AI_OFFLINE_FALLBACK is on), so the student keeps working without a single error. Each answer
passes the same schema and checks as a model's. Unlike MOCK_MODE (piq/mock.py), nothing here
is labelled or carries the demo's deliberate flaw: a student who is offline sees ordinary
content.

- quiz: questions from the question bank (data/questions/mcq_bank.csv) on the topic, at the
  difficulty asked, then the neighbouring ones; never one the student has already been asked.
- profile: the role's required skills (data/role_skills.json) matched in the resume's words.
- interviewer: the domain track's focus (data/interview_tracks.json) or the generic bank.
- planner: minutes weighted to the weakest topics. evaluator: scores from length and STAR
  markers, with the fixed coaching tips for the weakest criteria (config.INTERVIEW_TIPS).
"""

import re

from piq import mock, question_bank
from piq.checks import weak_topics
from piq.config import CRITERION_WEAK_BELOW, DIFFICULTIES, INTERVIEW_TIPS


def _quiz(ctx: dict) -> dict:
    """Bank questions first (asked difficulty, then the others nearest to it); generic
    practice questions only if the bank has too few for the topic."""
    want, topic, asked = ctx["count"], ctx["topic"], list(ctx["previous"])
    order = sorted(
        DIFFICULTIES,
        key=lambda d: abs(DIFFICULTIES.index(d) - DIFFICULTIES.index(ctx["difficulty"])),
    )
    picked = []
    for difficulty in order:
        if len(picked) >= want:
            break
        seed = f"offline:{topic}:{difficulty}:{len(asked)}"
        for q in question_bank.draw(topic, difficulty, want - len(picked), asked, seed):
            picked.append(q.model_dump())
            asked.append(q.text)
    if len(picked) < want:  # no bank on this machine, or not enough on the topic
        filler = mock._quiz(
            {**ctx, "count": want - len(picked), "previous": asked, "first_attempt": False}
        )
        for q in filler["questions"]:
            q["text"] = q["text"].replace("[mock] ", "Practice: ")
            q["explanation"] = "Review this topic's notes to confirm the reasoning."
            picked.append(q)
    return {"topic": topic, "difficulty": ctx["difficulty"], "questions": picked}


def _planner(ctx: dict) -> dict:
    plan = mock._planner(ctx)
    w = ctx["weakness"]
    pool = weak_topics(w) or sorted(w, key=lambda t: -w[t])
    plan["rationale"] = (
        f"The weakest topics get the most time this week: {', '.join(pool[:3])}. Minutes grow "
        "with how weak a topic is, from your latest quiz scores."
    )
    return plan


def _evaluator(ctx: dict) -> dict:
    answer = ctx["answer"]
    words = len(answer.split())
    star = sum(k in answer.lower() for k in ("situation", "task", "action", "result"))
    has_number = bool(re.search(r"\d", answer))
    scores = {
        "relevance": 3 if words > 5 else 1,
        "depth": min(5, words // 20 + (1 if has_number else 0)),
        "structure": min(5, 1 + star),
        "clarity": 3 if 10 < words < 250 else 2,
    }
    weak = [c for c, v in sorted(scores.items(), key=lambda kv: kv[1]) if v < CRITERION_WEAK_BELOW]
    strengths = []
    if words > 5:
        strengths.append("You answered the question directly.")
    if has_number:
        strengths.append("You gave a concrete figure, which makes the answer believable.")
    return {
        **scores,
        "strengths": strengths,
        "improvements": [INTERVIEW_TIPS[c] for c in weak[:2]] or [INTERVIEW_TIPS["depth"]],
        "model_answer": (
            "Situation: where you were and what was at stake. Task: what you had to achieve. "
            "Action: the two or three steps you took yourself. Result: what changed, with a "
            "number if you have one, and what you learnt."
        ),
    }


_HANDLERS = {
    "quiz": _quiz,
    "planner": _planner,
    "evaluator": _evaluator,
    "critic": mock._critic,  # the deterministic checks in checks.py already ran
    "profile": mock._profile,
    "interviewer": mock._interviewer,
    "bullet": mock._bullet,
    "github_readme": mock._github_readme,
}


def respond(agent: str, ctx: dict) -> dict:
    """The offline answer for `agent`; KeyError for an agent it does not cover (the agents/
    package then falls back to its own banks)."""
    return _HANDLERS[agent](ctx)
