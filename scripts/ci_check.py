"""Release checks for CI: the full test suite stays with the developers, so the public
repository proves the product itself works.

    python -m scripts.ci_check

1. Every product Python file compiles.
2. The datasets parse and agree: every JSON file loads; the question bank has its columns and
   usable questions; every catalog role has a skill list; every bank topic maps to a real
   syllabus topic (or none).
3. The API answers (server.py through FastAPI's TestClient): health, catalog, a guest quiz,
   the resume audit, a local sign-up, the student's plan, calendar and dashboard, and the
   refusals (signed out, the operations view, an invalid body).
4. The app starts: every page renders headless (Streamlit AppTest) in mock mode, with no
   student and with the demo student, on throwaway databases. No network, no secrets.

Exit code 0 when everything passes, 1 otherwise (each failure is printed).
"""

import compileall
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ("agents", "core", "database", "piq", "views", "scripts", "evaluation")
BANK_COLUMNS = {
    "topic",
    "difficulty",
    "question",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "correct_option",
}
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def compile_all() -> None:
    print("Compile")
    for name in CODE:
        check(bool(compileall.compile_dir(ROOT / name, quiet=1)), f"{name}/ compiles")
    for name in ("app.py", "server.py", "server_auth.py", "server_ops.py", "bootstrap.py"):
        check(bool(compileall.compile_file(ROOT / name, quiet=1)), f"{name} compiles")


def datasets() -> None:
    print("Datasets")
    for path in sorted((ROOT / "data").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
            check(True, f"{path.name} parses")
        except ValueError as e:
            check(False, f"{path.name} parses ({e})")
    bank = ROOT / "data" / "questions" / "mcq_bank.csv"
    with bank.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = BANK_COLUMNS - set(reader.fieldnames or [])
        rows = sum(1 for _ in reader)
    check(not missing, f"question bank has its columns{f' (missing {missing})' if missing else ''}")

    from piq import question_bank, syllabus

    usable = question_bank.size()
    check(usable > 0 and rows > 0, f"question bank: {usable} usable of {rows} rows")
    skills = syllabus.role_skills()
    roles = [r for d in syllabus.domains() for r in d.roles]
    lacking = [r for r in roles if r not in skills]
    check(not lacking, f"every catalog role has skills ({len(roles)} roles){lacking[:3] or ''}")
    topics = {t for d in syllabus.domains() for t in d.topics}
    unknown = sorted({t for t in question_bank.topic_map().values() if t and t not in topics})
    check(not unknown, f"bank topics map to syllabus topics{unknown[:3] or ''}")

    from piq import study_library

    gaps = [
        f"{d.id}/{t}"
        for d in syllabus.domains()
        for t in d.topics
        if not study_library.books_for(d.id, t)
    ]
    check(not gaps, f"every domain topic has a study book{gaps[:3] or ''}")


def _why(response: object) -> str:
    """The server's own message for a failed call, appended to the check's label."""
    status = getattr(response, "status_code", 0)
    if 200 <= status < 300:
        return ""
    try:
        return f" -> {status}: {response.json().get('detail')}"  # type: ignore[attr-defined]
    except ValueError:
        return f" -> {status}"


def api() -> None:
    print("API (server.py, mock mode)")
    from fastapi.testclient import TestClient

    from piq import syllabus
    from server import app

    skills = syllabus.role_skills()
    password = "blue river 4821"  # letters and digits, no username or email in it
    with TestClient(app) as c:
        health = c.get("/api/health")
        check(health.status_code == 200 and health.json().get("ok") is True, "GET /api/health")
        catalog = c.get("/api/catalog")
        domains = catalog.json().get("domains", []) if catalog.status_code == 200 else []
        check(bool(domains), f"GET /api/catalog ({len(domains)} domains)")
        topic = next((t["name"] for d in domains for t in d["topics"] if t["bank"]), None)
        if topic:
            level = next(
                lv for d in domains for t in d["topics"] if t["name"] == topic for lv in t["bank"]
            )
            quiz = c.get("/api/quiz", params={"topic": topic, "difficulty": level})
            qs = quiz.json().get("questions", []) if quiz.status_code == 200 else []
            check(
                bool(qs) and all("correct_index" not in q for q in qs),
                f"GET /api/quiz (guest, {topic}): questions without answers",
            )
        # A role both the catalog (resume templates) and the skill lists know.
        role = next(r["name"] for d in domains for r in d["roles"] if r["name"] in skills)
        ats = c.post("/api/resume/ats", json={"full_name": "CI", "role_name": role})
        check(
            ats.status_code == 200 and "score" in ats.json().get("ats", {}),
            f"POST /api/resume/ats{_why(ats)}",
        )
        me = c.get("/api/auth/me")
        check(me.status_code == 200 and me.json().get("student") is None, "GET /api/auth/me")
        check(c.get("/api/ops/overview").status_code == 401, "operations view refuses a visitor")
        bad = c.post("/api/quiz/submit", json={"topic": "x", "difficulty": "easy", "answers": []})
        check(
            bad.status_code == 422 and isinstance(bad.json().get("detail"), str),
            "an invalid body is a 422 with a readable detail",
        )
        signup = c.post(
            "/api/auth/signup",
            json={
                "name": "CI Student",
                "username": "cicheck",
                "email": "student.ci@example.com",
                "password": password,
                "confirm": password,
                "target_role": role,
            },
        )
        sid = (signup.json().get("student") or {}).get("id") if signup.status_code == 200 else None
        check(
            sid is not None, f"POST /api/auth/signup (local mode: signed in at once){_why(signup)}"
        )
        if sid:
            check(c.get(f"/api/plan/{sid}").status_code == 200, "GET /api/plan/{id}")
            made = c.post(f"/api/plan/{sid}/next")
            check(
                made.status_code == 200 and made.json().get("plan") is not None,
                "POST /api/plan/{id}/next (mock planner, critic-checked)",
            )
            ics = c.get(f"/api/plan/{sid}/calendar.ics")
            check(
                ics.status_code == 200 and ics.text.startswith("BEGIN:VCALENDAR"),
                "GET /api/plan/{id}/calendar.ics",
            )
            check(c.get(f"/api/dashboard/{sid}").status_code == 200, "GET /api/dashboard/{id}")
            c.post("/api/auth/logout")
            check(c.get(f"/api/plan/{sid}").status_code == 401, "signed out: the plan is refused")


def pages() -> None:
    print("Pages (headless, mock mode)")
    from streamlit.testing.v1 import AppTest

    from piq import db, services
    from scripts import seed, seed_cohort
    from scripts.pages import PAGES, STUDENT_ONLY

    db.init_db()
    seed.main()
    demo = next(s["id"] for s in services.list_students() if s["username"] == seed.USERNAME)
    for student in (None, demo):
        for page in PAGES:
            if student is None and page.slug in STUDENT_ONLY:
                continue
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
            if student:
                at.session_state["student_id"] = student
            at.switch_page(page.path)
            at.run()
            errors = [str(e.value)[:200] for e in at.exception]
            label = f"{page.title} ({'demo student' if student else 'no student'})"
            check(not errors, label + (f": {errors[0]}" if errors else ""))

    # The organization admin portal, signed in to the fictional demo organization.
    org_id = seed_cohort.ensure_org()
    for path in ("views/org_admin.py", "views/faculty.py"):  # the old address redirects
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
        at.session_state["admin_org_id"] = org_id
        at.switch_page(path)
        at.run()
        errors = [str(e.value)[:200] for e in at.exception]
        ok = not errors and any("Overview" in t.label for t in at.tabs)
        check(ok, f"{path} (demo organization admin)" + (f": {errors[0]}" if errors else ""))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ci-check-"))
    os.environ.update(
        PIQ_DOTENV=str(tmp / "absent.env"),  # never a developer's .env
        MOCK_MODE="true",
        PIQ_RAISE_ERRORS="1",  # a crashed page fails the check instead of showing a message
        DB_PATH=str(tmp / "app.db"),
        TELEMETRY_DB_PATH=str(tmp / "telemetry.db"),
        AI_CACHE_PATH=str(tmp / "ai_cache.json"),
        AUDIO_CACHE_DIR=str(tmp / "audio"),
        PRELOAD_CACHE_DIR=str(tmp / "preload"),
        MAIL_OUTBOX_PATH=str(tmp / "outbox.log"),
        LOCAL_MODE="true",  # one student, password only: the API check signs up without email
    )
    for key in (
        "DATABASE_URL",
        "SUPABASE_DB_URL",
        "GROQ_API_KEY",
        "GROQ_API_KEYS",
        "SMTP_EMAIL",
        "SMTP_APP_PASSWORD",
        "DEV_SECRET",
    ):
        os.environ.pop(key, None)
    sys.path.insert(0, str(ROOT))
    compile_all()
    datasets()
    api()
    pages()
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
