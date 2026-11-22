"""Release checks for CI: the full test suite stays with the developers, so the public
repository proves the product itself works.

    python -m scripts.ci_check

1. Every product Python file compiles.
2. The datasets parse and agree: every JSON file loads; the question bank has its columns and
   usable questions; every catalog role has a skill list; every bank topic maps to a real
   syllabus topic (or none).
3. The API answers (server.py through FastAPI's TestClient): health, catalog, a guest quiz,
   the resume audit, a local sign-up, the student's plan, calendar and dashboard, their
   certificates (upload, list, download, delete; a fake PDF, a non-.pdf name and an oversize
   file refused), their own local model (only loopback addresses, no redirects, Test
   connection against a stand-in on 127.0.0.1, their AI call answered by it and never cached,
   a fallback once it stops, 403 when LOCAL_AI is off), adaptive quizzes (the level rule, up
   after a perfect quiz and down after none right, a missed question back flagged, the
   nearest-level fallback, an explicit difficulty kept), and the refusals (signed out, another
   student, the operations view, an invalid body).
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the API check imports them lazily, after the environment is set
    from fastapi.testclient import TestClient
    from httpx import Response

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
        return f" -> {status}: {response.json().get('detail')}"
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
            certificates(c, sid)
            local_model(c, sid)
            adaptive_quiz(c, sid)
            c.post("/api/auth/logout")
            check(c.get(f"/api/plan/{sid}").status_code == 401, "signed out: the plan is refused")
            check(
                c.get(f"/api/certificates/{sid}").status_code == 401,
                "signed out: the certificates are refused",
            )


def certificates(c: "TestClient", sid: str) -> None:
    """Upload, list, download and delete a certificate, and the uploads that are refused."""
    url = f"/api/certificates/{sid}"
    form = {"title": "CI Certificate", "issuer": "CI Board", "issue_date": "2025-01-31"}
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

    def send(name: str, data: bytes, fields: dict = form) -> "Response":
        return c.post(url, data=fields, files={"file": (name, data, "application/pdf")})

    up = send("ci.pdf", pdf)
    cid = up.json().get("id") if up.status_code == 200 else None
    check(cid is not None, f"POST /api/certificates/{{id}} (a PDF){_why(up)}")
    listed = c.get(url)
    check(
        listed.status_code == 200 and [x["id"] for x in listed.json()] == [cid],
        "GET /api/certificates/{id}",
    )
    got = c.get(f"{url}/{cid}/file")
    check(
        got.status_code == 200
        and got.content == pdf
        and got.headers.get("content-type", "").startswith("application/pdf"),
        "GET /api/certificates/{id}/{cert}/file",
    )
    check(send("fake.pdf", b"not a pdf").status_code == 400, "a non-PDF named .pdf is refused")
    check(send("ci.txt", pdf).status_code == 400, "a file not named .pdf is refused")
    check(
        send("big.pdf", pdf + b"0" * (5 * 2**20)).status_code == 400, "a PDF over 5 MB is refused"
    )
    check(
        c.get("/api/certificates/someone-else").status_code == 403, "another student's are refused"
    )
    gone = c.post(f"{url}/{cid}/delete")
    check(
        gone.status_code == 200 and gone.json() == [], "POST /api/certificates/{id}/{cert}/delete"
    )
    check(c.get(f"{url}/{cid}/file").status_code == 404, "a deleted certificate is gone")


def _fake_local_model() -> tuple[object, int]:
    """A stand-in for Ollama and LM Studio on 127.0.0.1 (stdlib only, no network): model lists,
    one chat answer for the bullet agent, and a redirect that must never be followed."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    answer = json.dumps({"bullet": "Built the feature end to end, measured by a passing check."})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _reply(self, status: int, body: object = None, location: str = "") -> None:
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/api/tags":
                self._reply(200, {"models": [{"name": "ci-model:latest"}]})
            elif self.path == "/v1/models":
                self._reply(200, {"data": [{"id": "ci-lmstudio-model"}]})
            else:
                self._reply(302, location="http://example.com/")  # never followed

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/api/chat":
                self._reply(200, {"message": {"content": answer}})
            elif self.path == "/v1/chat/completions":
                self._reply(200, {"choices": [{"message": {"content": f"```json\n{answer}\n```"}}]})
            else:
                self._reply(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def local_model(c: "TestClient", sid: str) -> None:
    """A student's own local model: the address guard, Test connection, routing their AI call
    to it (mock mode: when preferred), never caching its answer, the indicator, and the 403s
    once LOCAL_AI is off."""
    from core import ai_router, local_ai
    from piq import db
    from piq.config import settings

    for bad in (
        "http://example.com",
        "http://10.0.0.1:11434",
        "http://169.254.169.254",
        "http://0.0.0.0:11434",
        "http://localhost.evil.com",
        "http://user@127.0.0.1:11434",
        "ftp://127.0.0.1:11434",
        "http://127.0.0.1:11434/?x=1",
    ):
        r = c.post("/api/auth/local-ai/test", json={"provider": "ollama", "base_url": bad})
        check(r.status_code == 400, f"local model: {bad} is refused")
    good = [local_ai.normalize_url("ollama", u) for u in ("http://localhost:1", "http://[::1]:1")]
    check(good == ["http://127.0.0.1:1", "http://[::1]:1"], "local model: loopback addresses pass")

    server, port = _fake_local_model()
    try:
        base = f"http://localhost:{port}"
        listed = c.post("/api/auth/local-ai/test", json={"provider": "ollama", "base_url": base})
        check(
            listed.status_code == 200 and listed.json()["models"] == ["ci-model:latest"],
            f"POST /api/auth/local-ai/test (Ollama models listed){_why(listed)}",
        )
        lms = c.post("/api/auth/local-ai/test", json={"provider": "lmstudio", "base_url": base})
        check(
            lms.status_code == 200 and lms.json()["models"] == ["ci-lmstudio-model"],
            "POST /api/auth/local-ai/test (LM Studio models listed)",
        )
        try:
            local_ai._send("GET", f"{base}/elsewhere", who="CI", read_timeout=2, max_bytes=999)
            check(False, "local model: a redirect is refused")
        except local_ai.LocalAIError:
            check(True, "local model: a redirect is refused")
        for provider, model in (("lmstudio", "ci-lmstudio-model"), ("ollama", "ci-model:latest")):
            saved = c.post(
                "/api/auth/local-ai",
                json={"provider": provider, "base_url": base, "model": model, "preferred": True},
            )
            check(saved.status_code == 200, f"POST /api/auth/local-ai ({provider}){_why(saved)}")
            bullet = {"text": "built the feature", "role": "Software Engineer"}
            out = c.post("/api/resume/enhance-bullet", json=bullet)
            check(
                out.status_code == 200 and db.last_model_used(sid) == f"local:{model}",
                f"a preferred {provider} model answers the student's AI call{_why(out)}",
            )
        me = c.get("/api/auth/me").json()
        check(me.get("local_ai") == {"model": "ci-model:latest"}, "GET /api/auth/me shows local_ai")
        check(
            not ai_router.prompt_cache().path.exists()
            or "local:" not in ai_router.prompt_cache().path.read_text(encoding="utf-8"),
            "a local model's answer is never cached",
        )
    finally:
        server.shutdown()
        server.server_close()
    out = c.post("/api/resume/enhance-bullet", json=bullet)
    check(
        out.status_code == 200 and db.last_model_used(sid) == "mock",
        "a stopped local model falls back to the mock answers",
    )

    os.environ["LOCAL_AI"] = "false"
    settings.cache_clear()
    try:
        check(c.get("/api/auth/local-ai").json().get("allowed") is False, "LOCAL_AI=false: off")
        for path, body in (
            ("/api/auth/local-ai/test", {"provider": "ollama"}),
            ("/api/auth/local-ai", {"provider": "ollama", "model": "x"}),
            ("/api/auth/local-ai/delete", {}),
        ):
            check(c.post(path, json=body).status_code == 403, f"LOCAL_AI=false: {path} is 403")
    finally:
        os.environ["LOCAL_AI"] = "auto"
        settings.cache_clear()
    gone = c.post("/api/auth/local-ai/delete")
    check(gone.status_code == 200 and gone.json()["config"] is None, "local model removed")


def adaptive_quiz(c: "TestClient", sid: str) -> None:
    """Each topic's level: the rule, a quiz at the level, up after a perfect score, down after
    none right, a miss coming back flagged, the nearest-level fallback when the bank runs out,
    and the old paths (an explicit difficulty, a guest) unchanged."""
    from piq import db, question_bank, services

    rule = services.next_level
    cases = (
        ("medium", [("medium", 4, 5)], "hard"),  # 80%: up
        ("medium", [("medium", 2, 5)], "easy"),  # 40%: down
        ("medium", [("medium", 3, 5)], "medium"),  # 60%: stays
        ("medium", [("medium", 3, 3)], "medium"),  # too few at the level to judge
        ("easy", [("hard", 4, 4)], "hard"),  # a harder part answered well lifts it
        ("medium", [("easy", 0, 5)], "medium"),  # an easier part never moves it
        ("hard", [("hard", 5, 5)], "hard"),  # clamped at the top
        ("easy", [("easy", 0, 5)], "easy"),  # and at the bottom
    )
    check(all(rule(lvl, p) == want for lvl, p, want in cases), "level rule: 80/50 at the level")

    def take(topic: str, wrong: int = 0, difficulty: str | None = None) -> tuple[dict, dict]:
        params = {"topic": topic, "candidate_id": sid}
        if difficulty:
            params["difficulty"] = difficulty
        quiz = c.get("/api/quiz", params=params).json()
        answers = []
        for i, q in enumerate(quiz.get("questions", [])):
            right = services._find_question(q["id"])[2].correct_index
            answers.append({"id": q["id"], "choice": (right + 1) % 4 if i < wrong else right})
        graded = c.post(
            "/api/quiz/submit",
            json={
                "candidate_id": sid,
                "topic": topic,
                "difficulty": quiz.get("difficulty", "medium"),
                "answers": answers,
            },
        ).json()
        return quiz, graded

    quiz, graded = take("DBMS")
    check(
        quiz.get("adaptive") is True and quiz.get("level") == "medium",
        "GET /api/quiz without a difficulty: a quiz at the student's level",
    )
    check(
        graded.get("level_before") == "medium" and graded.get("level_after") == "hard",
        "a perfect quiz moves the level up",
    )
    quiz, graded = take("DBMS", wrong=5)
    check(quiz.get("level") == "hard" and graded.get("level_after") == "medium", "0% eases off")
    quiz, last = take("DBMS")  # answered perfectly: the level goes back up
    check(
        sum(q.get("review", False) for q in quiz.get("questions", [])) >= 1,
        "a missed question comes back in a later quiz, flagged review",
    )

    thin = next((t for t, n in question_bank.counts().items() if 0 < n.get("hard", 0) < 5), None)
    domain = services.student_syllabus(sid, services.current_profile(sid)).domain
    if thin and thin in domain.topics:
        db.set_topic_levels(sid, {thin: "hard"})
        quiz, graded = take(thin)
        kinds = {q.get("difficulty") for q in quiz.get("questions", [])}
        check(
            len(quiz.get("questions", [])) == 5 and kinds - {"hard"},
            f"too few hard {thin} questions: nearest-level ones fill the quiz (mock mode)",
        )
        check("score_pct" in graded, "a mixed-difficulty quiz is graded")

    manual = c.get("/api/quiz", params={"topic": "OS", "difficulty": "easy", "candidate_id": sid})
    check(
        manual.status_code == 200
        and manual.json().get("adaptive") is False
        and {q["difficulty"] for q in manual.json()["questions"]} == {"easy"},
        "an explicit difficulty is kept as asked",
    )
    levels = c.get(f"/api/quiz/levels/{sid}").json().get("levels", {})
    dash = c.get(f"/api/dashboard/{sid}").json()
    want = last.get("level_after")
    check(
        want is not None
        and levels.get("DBMS") == want
        and dash.get("levels", {}).get("DBMS") == want,
        "GET /api/quiz/levels and /api/dashboard show the levels",
    )
    check(c.get("/api/quiz/levels/someone-else").status_code == 403, "another's levels: 403")


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
        CERTIFICATES_DIR=str(tmp / "certificates"),
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
        "LOCAL_AI",  # auto: on, since LOCAL_MODE is (the local-model checks need it)
        "RENDER",
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
