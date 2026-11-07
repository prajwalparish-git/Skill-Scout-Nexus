"""Demo organization for the admin portal: a fictional placement cell with two dozen students
across Engineering, Commerce, Law and Management, each with a resume scan, a roadmap, quiz
attempts over six weeks and voice sessions.

    python -m scripts.seed_cohort            # adds the demo organization (once)
    python -m scripts.seed_cohort --replace  # first deletes the earlier one

"Try demo organization admin" on the sign-in page seeds it on first use. The organization
(DEMO_ORG_CODE) and every student (username starting "cohort", named "Demo student NN") are
fictional. Their accounts and the organization live in the app database; their results live in
the telemetry database, written inside `local_only()` so none of it is ever sent to the cloud
copy. Nobody can sign in as them: the one password hash they share belongs to no password.
Deterministic (fixed random seed). No LLM calls.
"""

import argparse
import random
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core import auth
from core import org_provisioning as prov
from database import crud
from database.connection import get_manager, local_only
from database.models import Organization, QuizAttempt, StudentProfile, VoiceInterviewSession
from piq import db, services, syllabus
from piq.config import (
    DEMO_COHORT_PREFIX,
    DEMO_ORG_CODE,
    DEMO_ORG_NAME,
    ORG_QUIZ_CUTOFF_DEFAULT,
    ORG_VOICE_CUTOFF_DEFAULT,
    settings,
)

PREFIX = DEMO_COHORT_PREFIX  # never synced to the cloud (database/connection.py)
WEEKS = 6
DOMAIN = "dbit-demo.example.com"  # reserved for examples: no real address is ever mailed
# (main domain, subdomain, students, how strong the group starts: 0..1)
GROUPS = (
    ("Engineering", "Computer Science", 5, 0.58),
    ("Engineering", "Electronics & Communication", 3, 0.45),
    ("Commerce", "Taxation & Audit", 3, 0.62),
    ("Commerce", "Accounting & Finance", 3, 0.5),
    ("Law", "Corporate & Contract Law", 5, 0.4),
    ("Management", "Finance & Operations", 3, 0.6),
    ("Management", "Marketing", 2, 0.55),
)


def _clear(s: Session) -> int:
    """Delete the earlier demo organization from telemetry (students first, then the row)."""
    ids = list(
        s.scalars(select(StudentProfile.id).where(StudentProfile.username.like(f"{PREFIX}%")))
    )
    if ids:
        s.execute(delete(StudentProfile).where(StudentProfile.id.in_(ids)))
    s.execute(delete(Organization).where(Organization.org_code == DEMO_ORG_CODE))
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    """Seed the demo organization on this machine only (never sent to the cloud copy); returns
    how many students it wrote (0 when it already exists and --replace was not given)."""
    with local_only():
        return _seed(argv)


def _seed(argv: list[str] | None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--replace", action="store_true", help="delete the earlier demo first")
    args = ap.parse_args(argv)
    manager = get_manager()
    db.init_db()
    if args.replace:
        db.delete_organization(DEMO_ORG_CODE)
        manager.run(_clear)
    elif db.organization_by_code(DEMO_ORG_CODE) is not None:
        print("The demo organization already exists (use --replace to rebuild it).")
        return 0

    org_id = db.create_organization(
        {
            "org_code": DEMO_ORG_CODE,
            "name": DEMO_ORG_NAME,
            "org_type": "Autonomous Institute",
            "official_domain": DOMAIN,
            "admin_name": "Demo Admin",
            "admin_email": f"demo.admin@{DOMAIN}",
            "contact_phone": "",
            "location": "Bengaluru, Karnataka",
            "academic_batch": "2026-2027",
            "quiz_cutoff_pct": ORG_QUIZ_CUTOFF_DEFAULT,
            "voice_cutoff_score": ORG_VOICE_CUTOFF_DEFAULT,
        },
        auth.hash_password(secrets.token_urlsafe(32), pepper=settings().auth_pepper),
        verified=True,
    )
    crud.save_organization(
        DEMO_ORG_CODE,
        DEMO_ORG_NAME,
        "Autonomous Institute",
        "Demo Admin",
        f"demo.admin@{DOMAIN}",
        official_domain=DOMAIN,
        location="Bengaluru, Karnataka",
        academic_batch="2026-2027",
    )

    rng = random.Random(7)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    unusable = auth.hash_password(secrets.token_urlsafe(32), pepper=settings().auth_pepper)
    n = 0
    for main_domain, sub, count, strength in GROUPS:
        mapped = prov.map_domain(main_domain, sub)
        assert not isinstance(mapped, str), mapped
        domain = syllabus.domain(mapped.domain_id)
        roles = syllabus.roles_in(mapped.domain_id)
        start = roles.index(mapped.role)
        for _ in range(count):
            n += 1
            role = roles[(start + n) % min(len(roles), 3)] if len(roles) > 1 else mapped.role
            username, name = f"{PREFIX}{n:03d}", f"Demo student {n:02d}"
            sid = uuid.uuid4().hex
            db.create_org_students(
                org_id,
                [
                    db.NewStudent(
                        id=sid,
                        name=name,
                        username=username,
                        email=f"{username}@{DOMAIN}",
                        target_role=role,
                        main_domain=mapped.stream,
                        subdomain=sub,
                        phone=None,
                        batch_year="2027",
                        password_hash=unusable,
                        code_hash="0" * 64,
                        code_salt="0" * 32,
                        code_expires_at=0.0,  # expired: there is no code to type
                        sent_at=time.time(),
                        profile=services.starting_profile(
                            name, role, prov.education_text(mapped.degree, sub, "2027")
                        ),
                    )
                ],
            )
            # most are active; a few show the other states in the directory
            if n % 8 == 0:
                status = "suspended"
            elif n % 6 == 0:
                status = "invited"
            else:
                status = "active"
            if status != "invited":
                db.set_must_change_password(sid, False)
                db.set_org_student_status(org_id, sid, status)
            _telemetry(rng, now, username, name, mapped, sub, role, domain.name, status, strength)
    print(f"Seeded the demo organization with {n} students into the app and telemetry databases.")
    return n


def _telemetry(
    rng: random.Random,
    now: datetime,
    username: str,
    name: str,
    mapped: prov.Mapped,
    sub: str,
    role: str,
    domain_name: str,
    status: str,
    strength: float,
) -> None:
    skills = list(syllabus.role_skills()[role])
    ability = min(0.95, max(0.15, rng.gauss(strength, 0.15)))
    student = crud.save_student(
        username,
        name,
        mapped.stream,
        role,
        email=f"{username}@{DOMAIN}",
        department=domain_name,
        org_code=DEMO_ORG_CODE,
        main_domain=mapped.stream,
        subdomain=sub,
        account_status=status,
    )
    if status == "invited" or rng.random() < 0.08:  # a few have not started
        return
    matched = [s for s in skills if rng.random() < ability]
    missing = [s for s in skills if s not in matched]
    crud.save_resume_analysis(
        student.id, matched, missing, round(len(matched) / len(skills) * 100, 1)
    )
    crud.save_study_plan(
        student.id,
        1,
        {"target_role": role, "addressed_gaps": missing[:5], "days": []},
        [f"d{d}:0" for d in range(1, 8) if rng.random() < ability],
    )

    def add_activity(s: Session) -> None:
        for week in range(WEEKS):
            if rng.random() < 0.25:  # not every student quizzes every week
                continue
            skill = ability + week * 0.04  # practice helps
            total = rng.choice((5, 10))
            score = sum(rng.random() < min(0.97, skill) for _ in range(total))
            topic = rng.choice(skills)
            difficulty = rng.choice(("easy", "medium", "hard"))
            when = now - timedelta(weeks=WEEKS - 1 - week, days=rng.randint(0, 4))
            s.add(
                QuizAttempt(
                    student_id=student.id,
                    stream=mapped.stream,
                    domain=domain_name,
                    score=score,
                    total_questions=total,
                    critique_notes=f"Skill: {topic}. Difficulty: {difficulty}. Source: demo data.",
                    timestamp=when,
                )
            )
        for k in range(rng.randint(0, 2)):
            knowledge = min(5, max(1, round(ability * 5 + rng.uniform(-1, 1))))
            clarity = min(5, max(1, round(ability * 5 + rng.uniform(-1.5, 0.5))))
            confidence = min(5, max(1, round(ability * 5 + rng.uniform(-1, 1))))
            flags = ["Answer is very brief."] if knowledge + clarity < 5 else []
            s.add(
                VoiceInterviewSession(
                    student_id=student.id,
                    role=role,
                    audio_transcript="Demo session: no transcript was recorded.",
                    rubric_score=knowledge + clarity + confidence,
                    verbal_clarity_score=float(clarity),
                    relevance_score=float(knowledge),
                    feedback="Demo session.",
                    proctor_flags=flags,
                    timestamp=now - timedelta(days=7 * k + rng.randint(0, 6)),
                )
            )

    get_manager().run(add_activity)


if __name__ == "__main__":
    main()
