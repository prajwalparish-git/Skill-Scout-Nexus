"""Deterministic canned responses for MOCK_MODE (UI work, tests, offline demo).

Each function receives the same `context` the real prompt was built from and
returns a JSON-able dict that must pass the same schema + checks as real output.
Mock output is plausible, not intelligent; never use it for evaluation results.

Deliberate exception: the quiz agent's FIRST attempt contains one flawed question
(duplicate options) so the critic's reject -> regenerate loop is visible offline.
"""

import re

from piq import degrees
from piq.checks import text_hash, weak_topics
from piq.config import TOPICS

_INTERVIEW_BANK = {
    "HR": [
        "Tell me about yourself.",
        "Why do you want to join our company?",
        "Describe a time you handled a conflict in a team.",
        "What is your biggest weakness?",
        "Where do you see yourself in three years?",
        "Describe a failure and what you learned from it.",
    ],
    "Technical": [
        "Explain the difference between a process and a thread.",
        "What is database normalization and why is it used?",
        "How does a hash map handle collisions?",
        "Explain the four pillars of object-oriented programming.",
        "What happens when you type a URL into a browser?",
        "What is a deadlock and how can it be prevented?",
    ],
    "Project": [
        "Walk me through the architecture of your main project.",
        "What was the hardest technical problem in your project?",
        "Why did you choose that technology stack?",
        "How did you test your project?",
        "What would you change if you rebuilt the project today?",
        "How did you divide the work in your team?",
    ],
}


# A domain track (data/interview_tracks.json) has no fixed bank: questions from its focus.
_TRACK_TEMPLATES = [
    "In {track}, walk me through how you would approach {focus}.",
    "Tell me about a time your work touched {focus}. What did you do?",
    "What is the hardest {track} problem you have solved, and how did you know it worked?",
    "Which {track} concept do people most often get wrong, and why?",
    "How would you explain {focus} to a new team member?",
    "What would you study next to get stronger at {track}?",
]


def _bullet(ctx: dict) -> dict:
    text = ctx["text"].strip().rstrip(".")
    return {"bullet": f"Delivered {text[0].lower()}{text[1:]}, measured by [metric]."}


def _profile(ctx: dict) -> dict:
    text = ctx["resume_text"]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    matched = [
        s for s in ctx["required_skills"] if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text, re.I)
    ]
    edu = next((ln for ln in lines if re.search(r"b\.?e\b|b\.?tech|bachelor", ln, re.I)), "")
    edu = edu or next((ln for ln in lines[1:] if degrees.parse(ln)), "")  # any other degree
    return {
        "name": lines[0] if lines else "Unknown",
        "education": edu or "Not stated",
        "skills": matched or ["Communication"],
        "projects": [ln for ln in lines if ln.lower().startswith("project")][:3],
        "internships": [ln for ln in lines if "intern" in ln.lower()][:2],
        "matched_skills": matched,
        "resume_feedback": ["Quantify project impact with numbers (users, latency, accuracy)."],
    }


def _planner(ctx: dict) -> dict:
    w = ctx["weakness"]
    pool = weak_topics(w) or sorted(w, key=lambda t: -w[t])  # only the student's topics
    days = []
    for i in range(7):
        t = pool[i % len(pool)]
        days.append(
            {
                "day": i + 1,
                "topic": t,
                "subtopics": [f"{t} core concepts", f"{t} practice problems"],
                "duration_min": 30 * round((60 + 120 * w[t]) / 30),  # 60-180, grows with weakness
                "practice_goal": f"Solve 10 {t} questions and review mistakes",
            }
        )
    return {
        "week_no": ctx["week_no"],
        "rationale": f"[mock] Prioritised weakest topics: {', '.join(pool[:3])}.",
        "days": days,
    }


def _quiz(ctx: dict) -> dict:
    seen = {text_hash(t) for t in ctx["previous"]}
    qs, n = [], len(ctx["previous"]) + 1
    while len(qs) < ctx["count"]:
        text = f"[mock] {ctx['topic']} ({ctx['difficulty']}) question {n}: which option is correct?"
        n += 1
        if text_hash(text) in seen:
            continue
        qs.append(
            {
                "text": text,
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_index": n % 4,
                "explanation": "[mock] Placeholder explanation.",
                "bloom_level": "understand",
            }
        )
    if ctx.get("first_attempt"):
        qs[0]["options"][1] = qs[0]["options"][0]
    return {"topic": ctx["topic"], "difficulty": ctx["difficulty"], "questions": qs}


def _critic(ctx: dict) -> dict:
    return {"verdicts": [{"index": i, "valid": True, "reason": ""} for i in range(ctx["count"])]}


def _interviewer(ctx: dict) -> dict:
    history = ctx["history"]
    final = len(history) + 1 >= ctx["max_turns"]
    asked = {text_hash(q) for q in ctx["asked"]}
    if history:
        words = history[-1]["answer"].split()
        if len(words) < 25:
            quote = " ".join(words[:6]).rstrip(".,;:!?") + ("..." if len(words) > 6 else "")
            q = f"You said '{quote}'. Can you give one specific example with the outcome?"
            # Probe a given answer once: the critic rejects a repeated question, and the
            # mock (unlike the LLM) ignores rejection reasons, so a repeat could never pass.
            if text_hash(q) not in asked:
                return {
                    "question": q,
                    "intent": "probe vague answer",
                    "is_followup": True,
                    "is_final": final,
                }
    bank = _INTERVIEW_BANK.get(ctx["interview_type"]) or [
        t.format(track=ctx["interview_type"], focus=ctx.get("focus") or "this area")
        for t in _TRACK_TEMPLATES
    ]
    q = next((q for q in bank if text_hash(q) not in asked), f"{bank[0]} (round {len(asked)})")
    return {"question": q, "intent": "new area", "is_followup": bool(history), "is_final": final}


def _evaluator(ctx: dict) -> dict:
    ans = ctx["answer"]
    words = len(ans.split())
    star = sum(k in ans.lower() for k in ("situation", "task", "action", "result"))
    return {
        "relevance": 3 if words > 5 else 1,
        "depth": min(5, words // 20),
        "structure": min(5, 1 + star),
        "clarity": 3 if 10 < words < 250 else 2,
        "strengths": ["[mock] Answered the question directly."] if words > 5 else [],
        "improvements": ["[mock] Use the STAR structure and add a measurable result."],
        "model_answer": "[mock] Situation... Task... Action... Result (with a number).",
    }


def _judge(ctx: dict) -> dict:
    words = {w for w in re.findall(r"[a-z]{5,}", ctx["answer"].lower())}
    hits = sorted(words & set(re.findall(r"[a-z]{5,}", ctx["question"].lower())))
    return {"references_answer": bool(hits), "reason": f"[mock] shared words: {hits}"}


def _baseline(ctx: dict) -> dict:
    days = [
        {
            "day": i + 1,
            "topic": TOPICS[i % len(TOPICS)],
            "subtopics": ["overview", "practice"],
            "duration_min": 60,
            "practice_goal": "Practice questions",
        }
        for i in range(7)
    ]
    plan = {"week_no": ctx["week_no"], "rationale": "[mock] baseline", "days": days}
    return {"plan": plan, "quiz": _quiz(ctx)}


def _github_readme(ctx: dict) -> dict:
    title = ctx.get("title") or "Smart Nexus Platform"
    return {
        "project_title": title,
        "one_line_pitch": "An enterprise-grade platform for modern distributed applications.",
        "tech_stack": ["Python", "Streamlit", "SQLite", "Docker"],
        "star_bullets": [
            f"Architected {title} data pipeline using asynchronous task workers.",
            "Engineered modular REST API services with automated schema validation and testing.",
            "Optimized query performance and reduced database connection latency by 35%.",
        ],
        "viva_questions": [
            f"How did you design {title}'s architecture for state synchronization?",
            "What architectural trade-offs guided the selection of the core database layer?",
        ],
    }


_HANDLERS = {
    "profile": _profile,
    "planner": _planner,
    "quiz": _quiz,
    "critic": _critic,
    "interviewer": _interviewer,
    "evaluator": _evaluator,
    "baseline": _baseline,
    "baseline_quiz": _quiz,
    "judge": _judge,
    "bullet": _bullet,
    "github_readme": _github_readme,
}


def respond(agent: str, ctx: dict) -> dict:
    return _HANDLERS[agent](ctx)
