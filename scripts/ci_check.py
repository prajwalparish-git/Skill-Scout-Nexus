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
   nearest-level fallback, an explicit difficulty kept), resume templates (each a text-only
   one-column PDF in its own section order, Standard the original, one page where meant,
   uploaded certificates included, tailoring that invents no number, no date of birth or
   address in a saved version), company interview experiences (personal data removed, abuse
   refused, copied text flagged, pending until the right moderator approves, labelled never
   named, the college only for batches of five, 429 past the daily limit, reports hide a post,
   reported and AI practice kept apart), and the refusals (signed out, another student, the
   operations view, an invalid body).
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
    for name in (
        "app.py",
        "server.py",
        "server_auth.py",
        "server_ops.py",
        "server_companies.py",
        "server_drive.py",
        "server_proctor.py",
        "server_handsfree.py",
        "bootstrap.py",
    ):
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
            resume_templates(c, sid)
            company_questions(c, sid)
            drive(c, sid)
            proctoring_checks(c, sid)
            c.post("/api/auth/logout")
            tailor = c.post(
                "/api/resume/tailor", json={**SAMPLE_RESUME, "job_description": "x" * 90}
            )
            check(tailor.status_code == 401, "signed out: tailoring is refused")
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


def drive(c: "TestClient", sid: str) -> None:
    """Google Drive against a fake Google (scripts/fake_google.py), no network: hidden without
    keys; sign-in with only drive.file, PKCE and a single-use state bound to the student;
    refusals; the refresh token encrypted and bound to the student; folders made once;
    certificates mirrored, restored from Drive and trashed; a resume saved; disconnect and
    account deletion revoke; no token in the logs."""
    import base64
    import logging
    from urllib.parse import parse_qs, urlsplit

    from core import drive as gdrive
    from core import secretbox
    from piq import db, services
    from piq.config import settings
    from piq.db import tx
    from scripts.fake_google import FakeGoogle

    off = c.get("/api/drive")
    check(off.status_code == 200 and off.json()["enabled"] is False, "Drive: off without keys")
    check(
        all(
            c.post(f"/api/drive/{p}").status_code == 404
            for p in ("connect", "disconnect", "backup-certificates")
        )
        and c.get("/api/drive/callback", follow_redirects=False).status_code == 404
        and c.post("/api/drive/resume", json=SAMPLE_RESUME).status_code == 404,
        "Drive: every other route is 404 without keys",
    )

    keys = {
        "GOOGLE_CLIENT_ID": "ci-client",
        "GOOGLE_CLIENT_SECRET": "ci-secret",
        "DRIVE_TOKEN_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }
    os.environ.update(keys)
    settings.cache_clear()
    fake = FakeGoogle()
    fake.install()
    records: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    keep, root = Keep(level=logging.DEBUG), logging.getLogger()
    old_level = root.level
    root.addHandler(keep)
    root.setLevel(logging.DEBUG)
    other = db.create_student("CI Drive Other", "cidriveother", "Software Engineer")
    try:

        def query(url: str) -> dict[str, str]:
            return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}

        def callback(**params: str) -> dict[str, str]:
            r = c.get("/api/drive/callback", params=params, follow_redirects=False)
            where = r.headers.get("location", "")
            ok = r.status_code == 303 and where.startswith(settings().app_url + "/settings?")
            return query(where) if ok else {"drive": f"bad redirect {r.status_code} {where}"}

        def connect() -> tuple[str, str]:
            url = c.post("/api/drive/connect").json()["url"]
            return query(url)["state"], fake.consent(url)

        url = c.post("/api/drive/connect").json().get("url", "")
        q = query(url)
        check(
            url.startswith(gdrive.AUTH_URL)
            and q.get("scope") == gdrive.SCOPE
            and q.get("code_challenge_method") == "S256"
            and len(q.get("code_challenge", "")) == 43
            and q.get("redirect_uri") == settings().app_url + "/api/drive/callback"
            and q.get("access_type") == "offline"
            and "include_granted_scopes" not in q
            and len(q.get("state", "")) >= 43,
            "Drive: the sign-in asks only for drive.file, with PKCE and a state",
        )
        check(
            callback(error="access_denied")["drive"] == "error"
            and callback(state="unknown", code="x")["drive"] == "error",
            "Drive: a declined sign-in and an unknown state are refused",
        )
        state, code = connect()
        with tx() as conn:
            conn.execute("UPDATE drive_oauth_states SET expires_at = 0")
        check(callback(state=state, code=code)["drive"] == "error", "Drive: an expired state")
        url = gdrive.start(other, "web")
        check(
            callback(state=query(url)["state"], code=fake.consent(url))["drive"] == "error",
            "Drive: another student's sign-in is refused",
        )
        fake.grant_scope = gdrive.SCOPE + " https://www.googleapis.com/auth/drive"
        state, code = connect()
        revoked = len(fake.revoked)
        check(
            callback(state=state, code=code)["drive"] == "error"
            and len(fake.revoked) == revoked + 1
            and db.drive_account(sid) is None,
            "Drive: a broader grant is refused, revoked and not saved",
        )
        fake.grant_scope = gdrive.SCOPE

        state, code = connect()
        done = callback(state=state, code=code)
        status = c.get("/api/drive").json()
        check(
            done.get("drive") == "connected" and status["connected"] and status["folder_link"],
            f"Drive: connected ({done})",
        )
        check(callback(state=state, code=code)["drive"] == "error", "Drive: a used state")
        refresh = next(t for t, live in fake.refresh.items() if live)
        sealed = db.drive_account(sid)["refresh_token_enc"]
        try:
            secretbox.open_(sealed, student_id=other, purpose="refresh")
            moved = True
        except secretbox.SecretError:
            moved = False
        check(
            refresh not in sealed
            and secretbox.open_(sealed, student_id=sid, purpose="refresh") == refresh
            and not moved,
            "Drive: the refresh token is stored encrypted and opens only for its student",
        )
        gdrive.ensure_folders(sid)
        folders = {
            n: fake.folder_named(n) for n in (gdrive.ROOT, gdrive.CERTIFICATES, gdrive.RESUMES)
        }
        check(
            all(len(ids) == 1 for ids in folders.values()),
            "Drive: the three folders are made once and reused",
        )

        pdf = b"%PDF-1.4\n% drive\ntrailer<<>>\n%%EOF\n"
        up = c.post(
            f"/api/certificates/{sid}",
            data={"title": "CI Drive", "issuer": "CI", "issue_date": "2025-02-01"},
            files={"file": ("drive.pdf", pdf, "application/pdf")},
        )
        cid = up.json().get("id") if up.status_code == 200 else None
        row = db.certificate(sid, cid) if cid else None
        fid = row["drive_file_id"] if row else None
        check(
            bool(up.status_code == 200 and up.json().get("in_drive") and fid)
            and fake.files[fid]["data"] == pdf
            and fake.files[fid]["parents"] == folders[gdrive.CERTIFICATES],
            f"Drive: an uploaded certificate is copied to Certificates{_why(up)}",
        )
        if cid and row:
            local = services._certificate_dir(sid) / row["stored_name"]
            local.unlink()
            got = c.get(f"/api/certificates/{sid}/{cid}/file")
            check(
                got.status_code == 200 and got.content == pdf and local.read_bytes() == pdf,
                "Drive: View falls back to Drive when the local file is gone",
            )
            db.set_certificate_drive_id(sid, cid, None)
            missing = sum(not r["drive_file_id"] for r in db.certificates(sid))
            backed = c.post("/api/drive/backup-certificates")
            check(
                backed.status_code == 200
                and backed.json() == {"copied": missing}
                and all(r["drive_file_id"] for r in db.certificates(sid)),
                "Drive: Back up certificates copies every one not yet in Drive",
            )
            db.set_certificate_drive_id(sid, cid, None)
            retried = c.post(f"/api/drive/certificates/{cid}/retry")
            fid = db.certificate(sid, cid)["drive_file_id"]
            check(
                retried.status_code == 200 and retried.json() == {"in_drive": True} and fid,
                "Drive: Retry Drive copies one certificate",
            )
            c.post(f"/api/certificates/{sid}/{cid}/delete")
            check(fake.files[fid]["trashed"], "Drive: deleting a certificate trashes its copy")

        saved = c.post("/api/drive/resume", json=SAMPLE_RESUME)
        rid = saved.json().get("id") if saved.status_code == 200 else None
        check(
            bool(rid)
            and fake.files[rid]["parents"] == folders[gdrive.RESUMES]
            and fake.files[rid]["data"].startswith(b"%PDF")
            and fake.files[rid]["name"].endswith(".pdf"),
            f"Drive: Save to Drive puts the resume PDF in Resumes{_why(saved)}",
        )

        gone = c.post("/api/drive/disconnect")
        check(
            gone.status_code == 200
            and gone.json()["connected"] is False
            and refresh in fake.revoked
            and db.drive_account(sid) is None,
            "Drive: Disconnect revokes at Google and deletes the token",
        )
        url = gdrive.start(other, "web")
        gdrive.finish(query(url)["state"], fake.consent(url), signed_in=other, ui="web")
        theirs = secretbox.open_(
            db.drive_account(other)["refresh_token_enc"], student_id=other, purpose="refresh"
        )
        services.delete_student(other, "cidriveother")
        other = ""
        check(theirs in fake.revoked, "Drive: deleting the account revokes its Drive access")

        tokens = [t for t in (*fake.refresh, *fake.access) if t]
        said = "\n".join(r.getMessage() for r in records)
        check(bool(records) and not any(t in said for t in tokens), "Drive: no token in the logs")
    finally:
        root.removeHandler(keep)
        root.setLevel(old_level)
        if other:
            db.delete_student(other)
        fake.uninstall()
        for key in keys:
            os.environ.pop(key, None)
        settings.cache_clear()
    check(c.get("/api/drive").json()["enabled"] is False, "Drive: off again without keys")


def proctoring_checks(c: "TestClient", sid: str) -> None:
    """Proctoring without a camera: practice stays unproctored; an organization's requirement
    is enforced; the server decides severity (one strike per incident, 3 breach, review events
    never strike); only events are accepted; Safe Exam Browser's hash is checked against the
    PUBLIC URL (also behind a proxy); students see their own record; everything goes with the
    account; a rubric flag is no breach; a failed MediaPipe download never fails the build."""
    import hashlib
    import shutil
    import subprocess
    from types import SimpleNamespace

    from piq import cohort, db, services
    from piq import proctoring as pr
    from piq.config import settings
    from piq.db import tx

    catalog = c.get("/api/catalog").json()["domains"]
    topic, level = next(
        (t["name"], next(iter(t["bank"]))) for d in catalog for t in d["topics"] if t["bank"]
    )

    def submit(attempt: str | None = None) -> "Response":
        q = c.get("/api/quiz", params={"topic": topic, "difficulty": level, "count": 3}).json()
        body = {
            "candidate_id": sid,
            "topic": q["topic"],
            "difficulty": q["difficulty"],
            "answers": [{"id": x["id"], "choice": 0} for x in q["questions"]],
            "proctor_attempt_id": attempt,
        }
        return c.post("/api/quiz/submit", json=body)

    def start(**over: object) -> "Response":
        body = {"kind": "quiz", "label": topic, "camera": "on", "consent": True, **over}
        return c.post("/api/proctor/attempts", json=body)

    def events(attempt: str, *items: tuple, headers: dict | None = None) -> "Response":
        body = {
            "events": [
                {"kind": k, "at_s": t, **({"duration_s": d} if d else {})} for k, t, d in items
            ]
        }
        return c.post(f"/api/proctor/attempts/{attempt}/events", json=body, headers=headers)

    def age(attempt: str, seconds: float = 400) -> None:  # the attempt started a while ago
        with tx() as conn:
            conn.execute(
                "UPDATE proctor_attempts SET started_at = started_at - ?, "
                "last_seen = last_seen - 1 WHERE id = ?",
                (seconds, attempt),
            )

    policy = c.get("/api/proctor/policy").json()
    plain = submit()
    check(
        policy["mode"] == "practice"
        and plain.status_code == 200
        and plain.json().get("proctoring") is None,
        "Proctoring: a student without an organization gets unproctored practice",
    )

    org = db.create_organization(
        {
            "org_code": "PRC-2026",
            "name": "Proctor College",
            "org_type": "college",
            "official_domain": "",
            "admin_name": "P",
            "admin_email": "admin@prc.example",
            "contact_phone": "",
            "location": "",
            "academic_batch": "",
            "quiz_cutoff_pct": 70,
            "voice_cutoff_score": 10,
        },
        "x",
        verified=True,
    )
    with tx() as conn:
        before_org = conn.execute("SELECT org_id FROM students WHERE id = ?", (sid,)).fetchone()[0]
        conn.execute("UPDATE students SET org_id = ? WHERE id = ?", (org, sid))
    other = db.create_student("Proctor Other", "proctorother", "Software Engineer")
    try:
        pr.set_org_mode(org, "required")
        check(
            c.get("/api/proctor/policy").json()["required"] and submit().status_code == 409,
            "Proctoring: required by the organization, a submit without an attempt is 409",
        )
        check(start(consent=False).status_code == 400, "Proctoring: no consent, no start")
        check(
            start(image="data:image/png;base64,AAAA").status_code == 422
            and c.post(
                "/api/proctor/attempts/x/events",
                json={"events": [{"kind": "NO_FACE", "at_s": 1, "frame": "AAAA"}]},
            ).status_code
            in (403, 422),
            "Proctoring: an image or frame field is refused (only events are accepted)",
        )

        a = start(camera="unavailable", camera_note="no camera found").json()["attempt_id"]
        age(a)
        burst = events(
            a,
            ("WINDOW_BLUR", 10, None),
            ("TAB_HIDDEN", 10.3, None),
            ("FULLSCREEN_EXIT", 10.6, None),
        ).json()
        check(burst["strikes"] == 1, f"Proctoring: one incident is one strike ({burst})")
        check(
            events(a, ("TAB_HIDDEN", 11, None)).status_code == 200
            and c.post(
                f"/api/proctor/attempts/{a}/events",
                json={"events": [{"kind": "TAB_HIDDEN", "at_s": 12, "severity": "review"}]},
            ).status_code
            == 422,
            "Proctoring: the page cannot set an event's severity",
        )
        calm = {}
        for n in range(4):  # 200 soft signals, in batches of 50
            calm = events(
                a, *[("LOOKED_AWAY" if i % 2 else "NO_FACE", 20 + n * 50 + i, 9) for i in range(50)]
            ).json()
        check(
            calm.get("strikes") == 1 and calm.get("breached") is False,
            "Proctoring: 200 looked-away / no-face events strike no one (for review only)",
        )
        check(
            events(a, ("HACKED", 1, None)).status_code == 400
            and events(a, ("REPORTING_GAP", 1, None)).status_code == 400
            and c.post(
                f"/api/proctor/attempts/{a}/events",
                json={"events": [{"kind": "NO_FACE", "at_s": 1}] * 51},
            ).status_code
            == 422,
            "Proctoring: unknown or server-only events and oversized batches are refused",
        )
        fill = events(a, *[("PASTE_BLOCKED", 300 + i, None) for i in range(50)])  # 255 kept
        over = events(a, *[("PASTE_BLOCKED", 310 + i, None) for i in range(50)])  # 305: no
        check(
            fill.status_code == 200 and over.status_code == 400,
            "Proctoring: an attempt keeps at most 300 events",
        )
        done = events(a, ("PHONE_VISIBLE", 330, None), ("SECOND_FACE", 345, None)).json()
        result = submit(a)
        flags = (result.json().get("proctoring") or {}).get("flags", [])
        check(
            done["breached"]
            and result.status_code == 200
            and "PROCTOR_BREACH" in flags
            and not any(f in flags for f in ("LOOKED_AWAY", "NO_FACE", "PASTE_BLOCKED")),
            f"Proctoring: the third strike breaches; the submit records it ({flags})",
        )
        mine = c.get("/api/proctor/attempts").json()
        rec = mine[0] if mine else {}
        check(
            rec.get("id") == a
            and rec.get("breached")
            and rec.get("camera") == "unavailable"
            and any(e["kind"] == "CAMERA_UNAVAILABLE" for e in rec.get("review", []))
            and all(e["severity"] == "clear" for e in rec.get("clear", []))
            and any("looked away 9s at" in e["text"] for e in rec.get("review", [])),
            "Proctoring: the student sees their own record, clear vs review, camera noted",
        )
        theirs = pr.start(other, "quiz", "x", camera="on", consent=True)
        check(
            events(theirs, ("TAB_HIDDEN", 1, None)).status_code == 403
            and c.get(f"/api/proctor/attempts/{theirs}").status_code == 403
            and submit(theirs).status_code == 403,
            "Proctoring: another student's attempt is refused (403)",
        )

        key = hashlib.sha256(b"ci-seb-config").hexdigest()
        pr.set_org_mode(org, "seb", key)
        public = settings().app_url.rstrip("/") + "/api/proctor/attempts"
        good = hashlib.sha256((public + key).encode()).hexdigest()
        internal = hashlib.sha256((str(c.base_url) + "/api/proctor/attempts" + key).encode())
        seb = "X-SafeExamBrowser-ConfigKeyHash"
        proxied = {seb: good, "Host": "10.0.0.7:8000", "X-Forwarded-Host": "app.example"}
        ok = c.post(
            "/api/proctor/attempts",
            json={"kind": "quiz", "label": topic, "camera": "on", "consent": True},
            headers=proxied,
        )
        check(
            start().status_code == 403
            and c.post(
                "/api/proctor/attempts",
                headers={seb: "0" * 64},
                json={"kind": "quiz", "camera": "on", "consent": True},
            ).status_code
            == 403
            and c.post(
                "/api/proctor/attempts",
                headers={seb: internal.hexdigest()},
                json={"kind": "quiz", "camera": "on", "consent": True},
            ).status_code
            == 403,
            "Proctoring: SEB mode refuses no header, a wrong hash, and the internal URL's hash",
        )
        b = ok.json().get("attempt_id") if ok.status_code == 200 else None
        ev_url = f"{settings().app_url.rstrip('/')}/api/proctor/attempts/{b}/events"
        ev_hash = hashlib.sha256((ev_url + key).encode()).hexdigest()
        check(
            bool(b)
            and events(b).status_code == 403
            and events(b, headers={seb: ev_hash, "Host": "internal-api:8000"}).status_code == 200,
            "Proctoring: SEB hash of the public URL verifies on a proxied request",
        )
        check(
            (seen := next(x for x in pr.history(sid) if x.id == a)).clear
            and seen.review
            and cohort.breaches([SimpleNamespace(proctor_flags=["Too short", "Off topic"])]) == 0
            and cohort.breaches(
                [SimpleNamespace(proctor_flags=["TAB_HIDDEN", "PROCTOR_BREACH"])],
                [SimpleNamespace(proctor_flags=None)],
            )
            == 1,
            "Proctoring: the admin's record splits clear and review; only a breach is BREACH",
        )
        services.delete_student(other, "proctorother")
        with tx() as conn:
            left = conn.execute(
                "SELECT COUNT(*) FROM proctor_attempts WHERE id = ?", (theirs,)
            ).fetchone()[0]
            orphan = conn.execute(
                "SELECT COUNT(*) FROM proctor_events WHERE attempt_id = ?", (theirs,)
            ).fetchone()[0]
        other = ""
        check(left == 0 and orphan == 0, "Proctoring: attempts and events go with the account")
    finally:
        if other:
            db.delete_student(other)
        with tx() as conn:
            conn.execute("UPDATE students SET org_id = ? WHERE id = ?", (before_org, sid))
            conn.execute("DELETE FROM proctor_attempts WHERE student_id = ?", (sid,))
        pr.set_org_mode(org, "off")

    node = shutil.which("node")
    script = ROOT / "frontend" / "scripts" / "fetch-mediapipe.mjs"
    if node and script.exists() and (ROOT / "frontend" / "node_modules").exists():
        out = Path(tempfile.mkdtemp(prefix="ci-mediapipe-"))
        env = {
            **os.environ,
            "MEDIAPIPE_OUT": str(out),
            "MEDIAPIPE_MODEL_BASE": "http://127.0.0.1:9",
        }
        run = subprocess.run(
            [node, str(script)], env=env, capture_output=True, text=True, timeout=120, check=False
        )
        manifest = (
            json.loads((out / "manifest.json").read_text())
            if (out / "manifest.json").exists()
            else {}
        )
        check(
            run.returncode == 0
            and "camera checks will be disabled" in run.stderr + run.stdout
            and manifest.get("ok") is False,
            "Proctoring: a failed MediaPipe download warns, exits 0 and turns camera checks off",
        )
    else:
        print("  skip MediaPipe download check (no Node.js or frontend packages here)")


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


SAMPLE_RESUME = {
    "full_name": "Asha Rao",
    "email": "asha@example.com",
    "phone": "+91 98450 12345",
    "location": "Bengaluru",
    "linkedin_url": "linkedin.com/in/asha",
    "github_url": "github.com/asha",
    "leetcode_url": "leetcode.com/u/asha",
    "role_name": "Software Engineer",
    "skills": ["Python", "SQL", "Docker", "Git"],
    "education": [
        {
            "degree": "B.E.",
            "specialization": "Computer Science",
            "status": "Completed",
            "institution": "CI Institute",
            "start": "2021",
            "end": "2025",
            "score": "CGPA 8.4",
        }
    ],
    "experience": [
        {
            "title": "Software Intern",
            "company": "Acme",
            "type": "Internship",
            "start": "Jun 2024",
            "end": "Aug 2024",
            "highlights": "Wrote unit tests for the billing service\n"
            "Containerised 3 services with Docker",
        }
    ],
    "project_title": "Inventory API",
    "project_tech": "FastAPI, PostgreSQL",
    "project_desc": "Designed the admin UI\nBuilt REST endpoints in Python for 3 warehouses\n"
    "Cut query time by 40% with SQL indexes",
    "certifications": ["Oracle SQL Associate"],
    "achievements": ["Top 5% in a national coding contest"],
    "exam_scores": ["GATE 2026 (CS): 612"],
    "nationality": "Indian",
    "languages": "English, Kannada",
    "date_of_birth": "01 Jan 2003",
    "address": "12 MG Road, Bengaluru",
    "declaration_place": "Bengaluru",
}


def resume_templates(c: "TestClient", sid: str) -> None:
    """Every layout: a text-only, one-column PDF with standard headings in its own order
    (Standard exactly the original), one page where it aims at one, the template-only parts,
    an uploaded certificate in the PDF, tailoring that invents nothing, and no date of birth
    or address in a saved version."""
    import io
    import json as _json

    from pypdf import PdfReader

    from piq import checks as _checks
    from piq import db, services
    from piq import resume_templates as rt

    def pdf_of(template: str, **extra: object) -> tuple[bytes, str]:
        r = c.post("/api/resume/build-pdf", json={**SAMPLE_RESUME, **extra, "template": template})
        if r.status_code != 200:
            return b"", ""
        reader = PdfReader(io.BytesIO(r.content))
        return r.content, "\n".join(p.extract_text() for p in reader.pages)

    def in_order(text: str, parts: list[str]) -> bool:
        at = -1
        for p in parts:
            at = text.find(p, at + 1)
            if at < 0:
                return False
        return True

    listing = c.get("/api/resume/templates", params={"domain": "govt_central"}).json()
    check(
        [t["id"] for t in listing["templates"]]
        == ["standard", "service", "product", "core", "government"]
        and listing["default"] == "government",
        "GET /api/resume/templates: five layouts, a default per domain",
    )
    for tid, t in rt.TEMPLATES.items():
        raw, text = pdf_of(tid)
        images = sum(len(p.images) for p in PdfReader(io.BytesIO(raw)).pages) if raw else -1
        layout = c.post("/api/resume/ats", json={**SAMPLE_RESUME, "template": tid}).json()["layout"]
        headings = [s["heading"].upper() for s in layout["sections"]]
        check(
            raw.startswith(b"%PDF") and images == 0 and in_order(text, headings),
            f"{t.name}: a text-only PDF, no images, headings in the template's order",
        )
        if t.one_page:
            check(layout["pages"] == 1 and not layout["page_note"], f"{t.name}: fits one page")
    _, standard = pdf_of("standard")
    check(
        in_order(
            standard,
            [
                "ASHA RAO",
                "SOFTWARE ENGINEER",
                "Bengaluru | asha@example.com",
                "PROFESSIONAL SUMMARY",
                "CORE COMPETENCIES & SKILLS",
                "Core Focus:",
                "WORK EXPERIENCE",
                "PROJECTS",
                "EDUCATION",
                "CERTIFICATIONS & HONORS",
            ],
        )
        and "DECLARATION" not in standard
        and "01 Jan 2003" not in standard,
        "Standard: the original layout's text and section order",
    )
    _, gov = pdf_of("government")
    check(
        in_order(gov, ["CURRICULUM VITAE", "PERSONAL DETAILS", "01 Jan 2003", "DECLARATION"])
        and "612" in gov
        and "hereby declare" in gov,
        "Government / PSU: CV title, personal details, exam score, declaration",
    )
    _, product = pdf_of("product")
    check(
        product.find("LeetCode: leetcode.com/u/asha") < product.find("SKILLS"),
        "Product / startup: coding-profile links before the first section",
    )
    check(
        c.post("/api/resume/ats", json={**SAMPLE_RESUME, "template": "tcs-official"}).status_code
        == 422,
        "an unknown template is a 422",
    )

    form = {"title": "AWS Cloud Practitioner", "issuer": "Amazon Web Services"}
    form["issue_date"] = "2025-01-15"
    pdf = b"%PDF-1.4\n%%EOF\n"
    c.post(
        f"/api/certificates/{sid}", data=form, files={"file": ("aws.pdf", pdf, "application/pdf")}
    )
    lines = c.get("/api/resume/certificates").json().get("certificates", [])
    merged = [u["line"] for u in lines] + SAMPLE_RESUME["certifications"]
    _, with_cert = pdf_of("service", certifications=merged)
    check(
        "Amazon Web Services (Jan 2025)" in with_cert,
        "an uploaded certificate appears in the Certifications section",
    )

    jd = "Backend engineer: Python, SQL and Docker, building REST APIs and services. " * 2
    tailored = c.post("/api/resume/tailor", json={**SAMPLE_RESUME, "job_description": jd}).json()
    before = "\n".join(
        [SAMPLE_RESUME["project_desc"], SAMPLE_RESUME["experience"][0]["highlights"]]
    )
    after = "\n".join(b for bullets in tailored.get("bullets", {}).values() for b in bullets)
    counts = sorted(len(v) for v in tailored.get("bullets", {}).values())
    check(
        bool(tailored.get("summary"))
        and counts == [2, 3]
        and not _checks.invented_numbers(before, after),
        "tailoring (mock): every bullet kept once, no number invented",
    )

    res = c.post("/api/resume/ats", json={**SAMPLE_RESUME, "template": "government"}).json()
    check(
        "01 Jan 2003" not in _json.dumps(res["preview"])
        and "01 Jan 2003" in _json.dumps(res["layout"]),
        "date of birth is drawn, never echoed back in the resume data",
    )
    from piq import resume_builder as rb

    built = rb.build_ats_resume_data(
        full_name="Asha Rao",
        email="asha@example.com",
        phone="",
        location="",
        linkedin_url="",
        role_name="Software Engineer",
        selected_skills=["Python"],
        template="government",
        personal={"date_of_birth": "01 Jan 2003", "address": "12 MG Road", "nationality": "Indian"},
    )
    services.save_resume(sid, "cs", built)
    saved = _json.dumps(db.resume_versions(sid)[-1])
    check(
        not any(x in saved for x in ("date_of_birth", "01 Jan 2003", "12 MG Road", '"address"'))
        and "Indian" in saved,
        "a saved resume version has no date of birth or address",
    )


def company_questions(c: "TestClient", sid: str) -> None:
    """Company interview experiences: cleaned, pending until approved by the right moderator,
    labelled (never named, the college only for big enough batches), limited, reportable, and
    practised with reported and AI material kept apart."""
    import json as _json

    from piq import db, experiences, services
    from piq.db import ORG_FIELDS, tx

    post = {
        "company": "TCS",
        "role": "Systems Engineer",
        "round": "technical",
        "interview_month": "2026-08",
        "tip": "Mr. Rao liked clear answers; ring me on 9845012345 or mail me@example.com.",
        "questions": [
            {"kind": "open", "text": "Explain the difference between a process and a thread"},
            {
                "kind": "mcq",
                "text": "Which SQL clause filters grouped rows?",
                "options": ["WHERE", "HAVING", "ORDER BY", "LIMIT"],
                "correct_index": 1,
            },
        ],
    }
    shared = c.post("/api/experiences", json=post)
    exp_id = shared.json().get("id") if shared.status_code == 200 else None
    check(exp_id is not None, f"POST /api/experiences: shared, pending{_why(shared)}")
    if exp_id is None:
        return
    row = db.experience(exp_id)
    check(
        row["status"] == "pending" and row["company_slug"] == "tcs",
        "a post waits for approval, its company normalised (TCS -> Tata Consultancy Services)",
    )
    tip = row["tip"]
    check(
        "9845012345" not in tip and "me@example.com" not in tip and "Rao" not in tip,
        "phone numbers, emails and titled names are removed before anyone sees the post",
    )
    check(c.get("/api/companies/tcs").json()["posts"] == [], "a pending post is not visible")
    abusive = {**post, "questions": [{"kind": "open", "text": "this fucking round was rubbish"}]}
    bad = c.post("/api/experiences", json=abusive)
    check(
        bad.status_code == 400 and "abusive" in bad.json().get("detail", ""),
        "abusive text is refused, with the reason",
    )
    copied = {
        **post,
        "questions": [
            {
                "kind": "open",
                "text": "Two Sum. Example 1: Input: nums = [2,7], target 9. Constraints: n < 100",
            }
        ],
    }
    flagged = c.post("/api/experiences", json=copied).json().get("id")
    flags = _json.loads(db.experience(flagged)["flags"]) if flagged else []
    check(
        any("problem-site" in f for f in flags) and db.experience(flagged)["status"] == "pending",
        "text that looks copied from a problem site is flagged for the moderator, not published",
    )
    check(c.get("/api/ops/experiences").status_code == 401, "ops moderation needs the ops sign-in")
    experiences.review(experiences.OPS, exp_id, True)  # an individual learner's post: ops
    detail = c.get("/api/companies/tcs").json()
    dumped = _json.dumps(detail).lower()
    me = db.student(sid)
    check(
        [p["label"] for p in detail["posts"]] == ["a student, 2026"]
        and me["username"] not in dumped
        and me["name"].lower() not in dumped
        and (me["email"] or "@@") not in dumped,
        "approved: visible as 'a student, 2026', never with a name, username or email",
    )

    before = len(db.quiz_history(sid))
    quiz = c.get("/api/companies/tcs/practice", params={"round": "technical"}).json()
    graded = c.post(
        "/api/companies/tcs/practice/submit",
        json={
            "round": "technical",
            "source": "reported",
            "answers": [{"id": q["id"], "choice": 1} for q in quiz.get("questions", [])],
        },
    ).json()
    check(
        quiz.get("source") == "reported"
        and "correct_index" not in _json.dumps(quiz)
        and graded.get("score_pct") == 100.0
        and len(db.quiz_history(sid)) == before,
        "a reported quiz: answers withheld, graded, and no syllabus quiz history touched",
    )
    ai = c.get("/api/companies/tcs/practice", params={"round": "technical", "source": "ai"})
    ai_ids = {q["id"] for q in ai.json().get("questions", [])}
    reported_ids = {q["id"] for q in quiz.get("questions", [])}
    check(
        ai.json().get("source") == "ai"
        and "AI practice" in ai.json().get("label", "")
        and not ai_ids & reported_ids,
        "AI practice is labelled AI and never among the reported questions",
    )
    session = experiences.interview_practice(sid, "tcs", "technical")
    check(
        session.current.question == post["questions"][0]["text"]
        and session.current.intent == services.REPORTED_INTENT,
        "company interview practice asks the reported question first, word for word",
    )

    codes = [
        c.post(
            "/api/experiences",
            json={
                **post,
                "questions": [{"kind": "open", "text": f"A distinct question {i} on joins"}],
            },
        ).status_code
        for i in range(4)
    ]
    check(codes[-1] == 429 and 200 in codes, "more than five posts in a day is refused (429)")

    def org(code: str, name: str) -> int:
        fields = {k: "" for k in ORG_FIELDS} | {
            "org_code": code,
            "name": name,
            "org_type": "University",
            "admin_name": "Admin",
            "admin_email": f"admin@{code.lower()}.example",
            "quiz_cutoff_pct": 70,
            "voice_cutoff_score": 10,
        }
        return db.create_organization(fields, "x", verified=True)

    def member(username: str, org_id: int) -> str:
        new = db.create_student(username, username, "Software Engineer")
        services.benchmark_profile(new)
        with tx() as conn:
            conn.execute(
                "UPDATE students SET org_id = ?, batch_year = '2026' WHERE id = ?", (org_id, new)
            )
        return new

    ci_org, other_org = org("CIU-2026", "CIU - CI University"), org("OTH-2026", "Other College")
    posters = [member(f"ciu{i}", ci_org) for i in range(5)]
    ids = [
        experiences.submit(
            s, {**post, "questions": [{"kind": "open", "text": f"Walk me through project {i}"}]}
        ).id
        for i, s in enumerate(posters)
    ]

    def refused(moderator: int | str) -> bool:
        try:
            experiences.review(moderator, ids[0], True)
        except services.ServiceError:
            return True
        return False

    check(
        refused(other_org) and refused(experiences.OPS),
        "an organization moderates only its own students' posts (not ops, not others)",
    )
    for i in ids[:4]:
        experiences.review(ci_org, i, True)
    labels = {p["label"] for p in experiences.company_detail("tcs")["posts"]}
    check(
        "a student, 2026" in labels and not any("CIU" in lb for lb in labels),
        "fewer than five approved posters of a batch: no college in the label",
    )
    experiences.review(ci_org, ids[4], True)
    labels = {p["label"] for p in experiences.company_detail("tcs")["posts"]}
    check("a CIU student, 2026" in labels, "from the fifth approved poster: the college is named")

    c.post(f"/api/experiences/{ids[0]}/report")
    experiences.report(posters[1], ids[0])
    check(db.experience(ids[0])["status"] == "hidden", "two reports hide a post for review")


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
        labels = [t.label for t in at.tabs]
        ok = not errors and any("Overview" in t for t in labels)
        ok = ok and any("Interview posts" in t for t in labels)
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
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "DRIVE_TOKEN_KEY",
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
