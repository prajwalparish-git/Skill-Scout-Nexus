"""Seed the demo account with 4 weeks of history so adaptive re-planning can be shown instantly.

    python -m scripts.seed

Idempotent: deletes and recreates the demo account (username DEMO_USERNAME, no password: it is
entered only with "Continue with demo account"). Makes no LLM calls. All data is fictional.
"""

from datetime import UTC, datetime, timedelta

from piq import agents, checks, db, mock
from piq.config import DEMO_USERNAME, TOPICS
from piq.schemas import AnswerEvaluation, Question, QuizSet, StudentProfile, WeeklyPlan

USERNAME = DEMO_USERNAME
NAME = "Demo Student"
ROLE = "Java Backend Developer"
# Quiz score per topic in weeks 1..4: OS and DBMS start weak and improve.
TRAJECTORY = {
    "OS": [30, 40, 60, 70],
    "DBMS": [40, 50, 60, 70],
    "DSA": [70, 70, 80, 80],
    "CN": [60, 50, 60, 70],
    "OOP": [80, 80, 90, 90],
    "Aptitude": [50, 60, 60, 70],
}
INTERVIEWS = [  # (week, type, [(question, answer, (relevance, depth, structure, clarity))])
    (
        2,
        "HR",
        [
            ("Tell me about yourself.", "I am a student. I like coding.", (2, 1, 1, 3)),
            ("Why do you want this role?", "Backend work is interesting.", (2, 1, 1, 3)),
        ],
    ),
    (
        4,
        "Technical",
        [
            (
                "Explain the difference between a process and a thread.",
                "A process has its own address space; threads share the process memory, so context "
                "switches between threads are cheaper but need synchronisation such as locks.",
                (5, 4, 4, 4),
            ),
            (
                "What is database normalization?",
                "Organising tables to remove redundancy: 1NF atomic values, 2NF no partial "
                "dependency, 3NF no transitive dependency. I normalised my library project to 3NF.",
                (5, 4, 4, 5),
            ),
        ],
    ),
]


def _ts(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _quiz(topic: str, week: int) -> QuizSet:
    return QuizSet(
        topic=topic,
        difficulty="medium",
        questions=[
            Question(
                text=f"[seed] {topic} practice question, week {week}, item {i + 1}",
                options=["A", "B", "C", "D"],
                correct_index=i % 4,
                explanation="Seed data.",
                bloom_level="understand",
            )
            for i in range(10)
        ],
    )


def main() -> None:
    db.init_db()
    if old := db.student_by_username(USERNAME):
        db.delete_student(old["id"])
    required = list(agents.roles()[ROLE])
    matched = ["Java", "Object-Oriented Programming", "SQL", "Git", "Spring Boot"]
    profile = StudentProfile(
        name=NAME,
        education="B.E. (fictional demo record)",
        skills=[*matched, "HTML"],
        projects=["Library Management System — Spring Boot REST API with MySQL"],
        internships=[],
        matched_skills=matched,
        resume_feedback=["Add measurable results to each project."],
        target_role=ROLE,
        missing_skills=[s for s in required if s not in matched],
        readiness_score=checks.readiness_score(agents.roles()[ROLE], matched),
    )
    start = datetime.now(UTC) - timedelta(days=28)  # UTC, like SQLite CURRENT_TIMESTAMP
    sid = db.create_student(NAME, USERNAME, ROLE, at=_ts(start))
    db.save_profile(sid, profile, at=_ts(start))

    for week in range(1, 5):
        week_start = start + timedelta(days=7 * (week - 1))
        inp = agents.planner_inputs(profile, db.topic_performance(sid), week)
        plan = WeeklyPlan.model_validate(mock.respond("planner", inp))
        weakest = ", ".join(sorted(inp["weakness"], key=lambda t: -inp["weakness"][t])[:2])
        plan.rationale = f"Seeded plan for week {week}; most time on weakest topics: {weakest}."
        db.save_plan(sid, plan, at=_ts(week_start))

        for day, topic in enumerate(TOPICS, 1):
            quiz = _quiz(topic, week)
            right = TRAJECTORY[topic][week - 1] // 10
            chosen = [
                q.correct_index if i < right else (q.correct_index + 1) % 4
                for i, q in enumerate(quiz.questions)
            ]
            db.save_quiz_attempt(sid, quiz, chosen, at=_ts(week_start + timedelta(days=day)))

    for week, kind, turns in INTERVIEWS:
        session = f"seed-{week}-{kind.lower()}"
        at = start + timedelta(days=7 * (week - 1) + 6)
        for i, (q, a, (r, d, s, c)) in enumerate(turns):
            ev = AnswerEvaluation(
                relevance=r,
                depth=d,
                structure=s,
                clarity=c,
                strengths=[],
                improvements=[],
                model_answer="",
            )
            db.save_turn(sid, session, kind, q, a, ev, at=_ts(at + timedelta(minutes=5 * i)))

    print(
        f"Seeded @{USERNAME} ({ROLE}) with 4 weeks of plans, 24 quizzes, "
        f"{sum(len(t) for *_, t in INTERVIEWS)} interview turns. Next plan = week 5."
    )


if __name__ == "__main__":
    main()
