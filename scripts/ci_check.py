"""Release checks for CI: the full test suite stays with the developers, so the public
repository proves the product itself works.

    python -m scripts.ci_check

1. Every product Python file compiles.
2. The datasets parse and agree: every JSON file loads; the question bank has its columns and
   usable questions; every catalog role has a skill list; every bank topic maps to a real
   syllabus topic (or none).
3. The app starts: every page renders headless (Streamlit AppTest) in mock mode, with no
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
    for name in ("app.py", "server.py"):
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


def pages() -> None:
    print("Pages (headless, mock mode)")
    from streamlit.testing.v1 import AppTest

    from piq import db, orgs, services
    from scripts import seed
    from scripts.screenshots import PAGES, STUDENT_ONLY

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
    org_id = orgs.demo_admin()
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
    )
    for key in ("DATABASE_URL", "SUPABASE_DB_URL", "GROQ_API_KEY", "GROQ_API_KEYS", "SEED_DEMO"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(ROOT))
    compile_all()
    datasets()
    pages()
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
