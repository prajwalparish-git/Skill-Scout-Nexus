"""SQLite persistence: connection handling and every read/write the app performs.

One short-lived connection per call keeps this safe under Streamlit's threads.
"""

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from piq.checks import text_hash
from piq.config import settings
from piq.schemas import AnswerEvaluation, QuizSet, StudentProfile, WeeklyPlan

SCHEMA = Path(__file__).with_name("schema.sql")
FAILED = "failed: "  # reject_reason prefix of an agent_logs row whose call or check failed


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    path = settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")  # with WAL: safe and fast
    try:
        with conn:  # commits on success, rolls back on exception
            yield conn
    finally:
        conn.close()


# Columns students gained with organizations; an older file gets them by ALTER TABLE (nullable or
# defaulted, so every row is kept). A new file already has them from schema.sql.
STUDENT_ADDED = (
    ("org_id", "INTEGER REFERENCES organizations(id)"),
    ("main_domain", "TEXT"),
    ("subdomain", "TEXT"),
    (
        "account_status",
        "TEXT NOT NULL DEFAULT 'active' "
        "CHECK (account_status IN ('active', 'invited', 'suspended'))",
    ),
    ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
    ("phone", "TEXT"),
    ("batch_year", "TEXT"),
)


def _migrate(c: sqlite3.Connection) -> None:
    """Bring a database from before accounts or organizations up to date, in place (data kept):
    the USN column becomes the lower-cased username, an email column is added, and so are the
    organization columns (STUDENT_ADDED). A no-op afterwards."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(students)")}
    if "usn" in cols and "username" not in cols:  # SQLite 3.25+: keeps NOT NULL UNIQUE
        c.execute("ALTER TABLE students RENAME COLUMN usn TO username")
        c.execute("UPDATE students SET username = lower(username)")
        cols = (cols - {"usn"}) | {"username"}
    if cols and "email" not in cols:
        c.execute("ALTER TABLE students ADD COLUMN email TEXT")
        cols.add("email")
    if cols:
        for name, ddl in STUDENT_ADDED:
            if name not in cols:
                c.execute(f"ALTER TABLE students ADD COLUMN {name} {ddl}")  # fixed identifiers


def init_db() -> None:
    with tx() as c:
        c.execute("PRAGMA journal_mode = WAL")  # persistent: readers never block the writer
        _migrate(c)
        c.executescript(SCHEMA.read_text(encoding="utf-8"))


# --- students & profiles -------------------------------------------------------


def create_student(
    name: str,
    username: str,
    target_role: str,
    email: str | None = None,
    password_hash: str | None = None,
    at: str | None = None,
) -> str:
    """A new account (and its password, when it has one); returns its id. The caller has
    validated and lower-cased username and email; a duplicate raises sqlite3.IntegrityError."""
    sid = uuid.uuid4().hex
    with tx() as c:
        c.execute(
            """INSERT INTO students (id, name, username, email, target_role, created_at)
               VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            (sid, name, username, email, target_role, at),
        )
        if password_hash:
            c.execute(
                "INSERT INTO credentials (student_id, password_hash) VALUES (?, ?)",
                (sid, password_hash),
            )
    return sid


def save_profile(student_id: str, profile: StudentProfile, at: str | None = None) -> str:
    """Append a profile row for the student; their role and readiness follow it (their account
    name stays theirs). Returns the student id."""
    with tx() as c:
        c.execute(
            "UPDATE students SET target_role = ?, readiness_score = ? WHERE id = ?",
            (profile.target_role, profile.readiness_score, student_id),
        )
        c.execute(
            """INSERT INTO profiles (student_id, profile_json, readiness_score, created_at)
               VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            (student_id, profile.model_dump_json(), profile.readiness_score, at),
        )
    return student_id


# One student with the organization it belongs to (NULL org_* for an individual learner).
_STUDENT = (
    "SELECT s.id, s.name, s.username, s.email, s.target_role, s.readiness_score, s.org_id, "
    "s.main_domain, s.subdomain, s.account_status, s.must_change_password, s.phone, "
    "s.batch_year, s.created_at, o.org_code, o.name AS org_name "
    "FROM students s LEFT JOIN organizations o ON o.id = s.org_id "
)


def student_by_username(username: str) -> sqlite3.Row | None:
    with tx() as c:
        return c.execute(_STUDENT + "WHERE s.username = ?", (username.lower(),)).fetchone()


def student_by_login(identifier: str) -> sqlite3.Row | None:
    """The account whose username or email is `identifier` (any case), or None."""
    key = identifier.strip().lower()
    with tx() as c:
        return c.execute(
            _STUDENT + "WHERE s.username = ? OR lower(s.email) = ?", (key, key)
        ).fetchone()


def email_taken(email: str) -> bool:
    with tx() as c:
        row = c.execute("SELECT 1 FROM students WHERE lower(email) = ?", (email.lower(),))
        return row.fetchone() is not None


def delete_student(student_id: str) -> None:
    """Remove a student and (via ON DELETE CASCADE) all of their history and sign-in state."""
    with tx() as c:
        c.execute("DELETE FROM students WHERE id = ?", (student_id,))


def student(student_id: str) -> sqlite3.Row | None:
    """One student: id, name, username, email, target_role, readiness_score, and the
    organization columns (org_id, org_code, org_name, main_domain, subdomain, account_status,
    must_change_password, phone, batch_year, created_at)."""
    with tx() as c:
        return c.execute(_STUDENT + "WHERE s.id = ?", (student_id,)).fetchone()


def list_students() -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(_STUDENT + "ORDER BY s.username").fetchall()


# --- sign-in state (piq/accounts.py; never synced) -------------------------------


def credentials(student_id: str) -> sqlite3.Row | None:
    """password_hash, failures and locked_until, or None for an account without a password."""
    with tx() as c:
        return c.execute(
            "SELECT password_hash, failures, locked_until FROM credentials WHERE student_id = ?",
            (student_id,),
        ).fetchone()


def set_password(student_id: str, password_hash: str) -> None:
    """Store a new password and clear any lockout."""
    with tx() as c:
        c.execute(
            """INSERT INTO credentials (student_id, password_hash) VALUES (?, ?)
               ON CONFLICT(student_id) DO UPDATE SET password_hash = excluded.password_hash,
                 failures = 0, locked_until = 0, updated_at = CURRENT_TIMESTAMP""",
            (student_id, password_hash),
        )


def set_lockout(student_id: str, failures: int, locked_until: float) -> None:
    with tx() as c:
        c.execute(
            "UPDATE credentials SET failures = ?, locked_until = ? WHERE student_id = ?",
            (failures, locked_until, student_id),
        )


def save_code(
    student_id: str, purpose: str, code_hash: str, salt: str, expires_at: float, sent_at: float
) -> None:
    """The account's one live code for `purpose`, replacing an earlier one (attempts reset)."""
    with tx() as c:
        c.execute(
            """INSERT INTO auth_codes (student_id, purpose, code_hash, salt, expires_at, sent_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(student_id, purpose) DO UPDATE SET code_hash = excluded.code_hash,
                 salt = excluded.salt, expires_at = excluded.expires_at, attempts = 0,
                 sent_at = excluded.sent_at""",
            (student_id, purpose, code_hash, salt, expires_at, sent_at),
        )


def auth_code(student_id: str, purpose: str) -> sqlite3.Row | None:
    with tx() as c:
        return c.execute(
            """SELECT code_hash, salt, expires_at, attempts, sent_at FROM auth_codes
               WHERE student_id = ? AND purpose = ?""",
            (student_id, purpose),
        ).fetchone()


def count_code_attempt(student_id: str, purpose: str) -> None:
    with tx() as c:
        c.execute(
            "UPDATE auth_codes SET attempts = attempts + 1 WHERE student_id = ? AND purpose = ?",
            (student_id, purpose),
        )


def delete_code(student_id: str, purpose: str) -> None:
    with tx() as c:
        c.execute(
            "DELETE FROM auth_codes WHERE student_id = ? AND purpose = ?", (student_id, purpose)
        )


def create_session(token_hash: str, student_id: str, expires_at: float) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO sessions (token_hash, student_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, student_id, expires_at),
        )


def session_student(token_hash: str, now: float) -> str | None:
    """The student a live session belongs to; expired sessions are removed on the way."""
    with tx() as c:
        c.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        row = c.execute(
            "SELECT student_id FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    return row["student_id"] if row else None


def delete_session(token_hash: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_sessions(student_id: str) -> None:
    """Sign the student out everywhere (after a password reset)."""
    with tx() as c:
        c.execute("DELETE FROM sessions WHERE student_id = ?", (student_id,))


# --- organizations (piq/orgs.py): the roster, and the admin's own sign-in state ----------

ORG_FIELDS = (
    "org_code",
    "name",
    "org_type",
    "official_domain",
    "admin_name",
    "admin_email",
    "contact_phone",
    "location",
    "academic_batch",
    "quiz_cutoff_pct",
    "voice_cutoff_score",
)
ORG_EDITABLE = (  # what an admin may change later: not the code, and not the login email
    "name",
    "org_type",
    "official_domain",
    "admin_name",
    "contact_phone",
    "location",
    "academic_batch",
    "quiz_cutoff_pct",
    "voice_cutoff_score",
)
_ORG = "SELECT id, " + ", ".join(ORG_FIELDS) + ", created_at FROM organizations "  # no hash


def create_organization(
    fields: Mapping[str, object], password_hash: str, *, verified: bool = False
) -> int:
    """A new organization (its admin's password already hashed); returns its id. A taken code
    or admin email raises sqlite3.IntegrityError."""
    with tx() as c:
        cur = c.execute(
            f"INSERT INTO organizations ({', '.join(ORG_FIELDS)}, admin_password_hash, "
            f"admin_verified) VALUES ({', '.join('?' * len(ORG_FIELDS))}, ?, ?)",
            (*(fields[k] for k in ORG_FIELDS), password_hash, int(verified)),
        )
        return int(cur.lastrowid or 0)


def organization(org_id: int | None) -> sqlite3.Row | None:
    """The organization without any sign-in state, or None."""
    if org_id is None:
        return None
    with tx() as c:
        return c.execute(_ORG + "WHERE id = ?", (org_id,)).fetchone()


def organization_by_code(org_code: str) -> sqlite3.Row | None:
    with tx() as c:
        return c.execute(_ORG + "WHERE org_code = ?", (org_code.strip().upper(),)).fetchone()


def organization_login(admin_email: str) -> sqlite3.Row | None:
    """The admin's sign-in state for this email: id, admin_password_hash, admin_verified,
    admin_failures, admin_locked_until, admin_name, admin_email; or None."""
    with tx() as c:
        return c.execute(
            "SELECT id, admin_name, admin_email, admin_password_hash, admin_verified, "
            "admin_failures, admin_locked_until FROM organizations WHERE admin_email = ?",
            (admin_email.strip().lower(),),
        ).fetchone()


def organization_state(org_id: int) -> sqlite3.Row | None:
    """organization_login's columns, looked up by id."""
    with tx() as c:
        return c.execute(
            "SELECT id, admin_name, admin_email, admin_password_hash, admin_verified, "
            "admin_failures, admin_locked_until FROM organizations WHERE id = ?",
            (org_id,),
        ).fetchone()


def update_organization(org_id: int, fields: Mapping[str, object]) -> None:
    """Change the editable profile fields (anything else in `fields` is ignored)."""
    keys = [k for k in ORG_EDITABLE if k in fields]
    if not keys:
        return
    with tx() as c:
        c.execute(
            f"UPDATE organizations SET {', '.join(f'{k} = ?' for k in keys)} WHERE id = ?",
            (*(fields[k] for k in keys), org_id),
        )


def set_admin_lockout(org_id: int, failures: int, locked_until: float) -> None:
    with tx() as c:
        c.execute(
            "UPDATE organizations SET admin_failures = ?, admin_locked_until = ? WHERE id = ?",
            (failures, locked_until, org_id),
        )


def mark_admin_verified(org_id: int) -> None:
    with tx() as c:
        c.execute(
            "UPDATE organizations SET admin_verified = 1, admin_failures = 0, "
            "admin_locked_until = 0 WHERE id = ?",
            (org_id,),
        )


def save_admin_code(
    org_id: int, code_hash: str, salt: str, expires_at: float, sent_at: float
) -> None:
    with tx() as c:
        c.execute(
            """INSERT INTO admin_codes (org_id, code_hash, salt, expires_at, sent_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(org_id) DO UPDATE SET code_hash = excluded.code_hash,
                 salt = excluded.salt, expires_at = excluded.expires_at, attempts = 0,
                 sent_at = excluded.sent_at""",
            (org_id, code_hash, salt, expires_at, sent_at),
        )


def admin_code(org_id: int) -> sqlite3.Row | None:
    with tx() as c:
        return c.execute(
            "SELECT code_hash, salt, expires_at, attempts, sent_at FROM admin_codes "
            "WHERE org_id = ?",
            (org_id,),
        ).fetchone()


def count_admin_code_attempt(org_id: int) -> None:
    with tx() as c:
        c.execute("UPDATE admin_codes SET attempts = attempts + 1 WHERE org_id = ?", (org_id,))


def delete_admin_code(org_id: int) -> None:
    with tx() as c:
        c.execute("DELETE FROM admin_codes WHERE org_id = ?", (org_id,))


def create_admin_session(token_hash: str, org_id: int, expires_at: float) -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO admin_sessions (token_hash, org_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, org_id, expires_at),
        )


def admin_session_org(token_hash: str, now: float) -> int | None:
    """The organization a live admin session belongs to; expired ones are removed on the way."""
    with tx() as c:
        c.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now,))
        row = c.execute(
            "SELECT org_id FROM admin_sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    return row["org_id"] if row else None


def delete_admin_session(token_hash: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))


@dataclass(frozen=True)
class NewStudent:
    """One account provisioned for an organization, ready to store: the password and welcome
    code are already hashed, and the starting profile holds the role's benchmark skills."""

    id: str
    name: str
    username: str
    email: str
    target_role: str
    main_domain: str
    subdomain: str
    phone: str | None
    batch_year: str | None
    password_hash: str
    code_hash: str
    code_salt: str
    code_expires_at: float
    sent_at: float
    profile: StudentProfile


def usernames_in_use() -> set[str]:
    with tx() as c:
        return {r["username"] for r in c.execute("SELECT username FROM students")}


def emails_in_use(emails: Iterable[str]) -> set[str]:
    """Which of these (lower-case) emails already belong to an account, in any organization."""
    wanted = list(dict.fromkeys(emails))
    found: set[str] = set()
    with tx() as c:
        for i in range(0, len(wanted), 500):  # SQLite caps the parameters of one statement
            chunk = wanted[i : i + 500]
            rows = c.execute(
                "SELECT lower(email) AS email FROM students "
                f"WHERE lower(email) IN ({', '.join('?' * len(chunk))})",
                chunk,
            )
            found.update(r["email"] for r in rows)
    return found


def create_org_students(org_id: int, students: Sequence[NewStudent]) -> None:
    """Store every student, with its credentials, welcome code and starting profile, in ONE
    transaction: all of them or none. A taken username or email raises sqlite3.IntegrityError
    and nothing is kept."""
    with tx() as c:
        c.executemany(
            """INSERT INTO students (id, name, username, email, target_role, readiness_score,
                 org_id, main_domain, subdomain, account_status, must_change_password, phone,
                 batch_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'invited', 1, ?, ?)""",
            [
                (
                    s.id,
                    s.name,
                    s.username,
                    s.email,
                    s.target_role,
                    s.profile.readiness_score,
                    org_id,
                    s.main_domain,
                    s.subdomain,
                    s.phone,
                    s.batch_year,
                )
                for s in students
            ],
        )
        c.executemany(
            "INSERT INTO credentials (student_id, password_hash) VALUES (?, ?)",
            [(s.id, s.password_hash) for s in students],
        )
        c.executemany(
            """INSERT INTO auth_codes (student_id, purpose, code_hash, salt, expires_at, sent_at)
               VALUES (?, 'login', ?, ?, ?, ?)""",
            [(s.id, s.code_hash, s.code_salt, s.code_expires_at, s.sent_at) for s in students],
        )
        c.executemany(
            "INSERT INTO profiles (student_id, profile_json, readiness_score) VALUES (?, ?, ?)",
            [(s.id, s.profile.model_dump_json(), s.profile.readiness_score) for s in students],
        )


# Every query below carries `org_id`: an organization's admin can read and change its own
# students and nobody else's, however the id reached us (a stale form, a tampered request).


def org_students(org_id: int) -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(
            _STUDENT + "WHERE s.org_id = ? ORDER BY s.name, s.username", (org_id,)
        ).fetchall()


def org_student(org_id: int, student_id: str) -> sqlite3.Row | None:
    """The student only when they belong to this organization."""
    with tx() as c:
        return c.execute(
            _STUDENT + "WHERE s.id = ? AND s.org_id = ?", (student_id, org_id)
        ).fetchone()


def reassign_org_student(
    org_id: int, student_id: str, main_domain: str, subdomain: str, target_role: str
) -> bool:
    with tx() as c:
        cur = c.execute(
            "UPDATE students SET main_domain = ?, subdomain = ?, target_role = ? "
            "WHERE id = ? AND org_id = ?",
            (main_domain, subdomain, target_role, student_id, org_id),
        )
        return cur.rowcount == 1


def set_org_student_status(org_id: int, student_id: str, status: str) -> bool:
    """Suspending also signs the student out everywhere."""
    with tx() as c:
        cur = c.execute(
            "UPDATE students SET account_status = ? WHERE id = ? AND org_id = ?",
            (status, student_id, org_id),
        )
        if cur.rowcount == 1 and status == "suspended":
            c.execute("DELETE FROM sessions WHERE student_id = ?", (student_id,))
        return cur.rowcount == 1


def reset_org_student_credentials(
    org_id: int,
    student_id: str,
    password_hash: str,
    code_hash: str,
    code_salt: str,
    code_expires_at: float,
    sent_at: float,
) -> bool:
    """A new temporary password and welcome code, one transaction: the old password stops
    working, the lockout clears, every session ends, and the student must change the password."""
    with tx() as c:
        cur = c.execute(
            "UPDATE students SET must_change_password = 1 WHERE id = ? AND org_id = ?",
            (student_id, org_id),
        )
        if cur.rowcount != 1:
            return False
        c.execute(
            """INSERT INTO credentials (student_id, password_hash) VALUES (?, ?)
               ON CONFLICT(student_id) DO UPDATE SET password_hash = excluded.password_hash,
                 failures = 0, locked_until = 0, updated_at = CURRENT_TIMESTAMP""",
            (student_id, password_hash),
        )
        c.execute(
            """INSERT INTO auth_codes (student_id, purpose, code_hash, salt, expires_at, sent_at)
               VALUES (?, 'login', ?, ?, ?, ?)
               ON CONFLICT(student_id, purpose) DO UPDATE SET code_hash = excluded.code_hash,
                 salt = excluded.salt, expires_at = excluded.expires_at, attempts = 0,
                 sent_at = excluded.sent_at""",
            (student_id, code_hash, code_salt, code_expires_at, sent_at),
        )
        c.execute("DELETE FROM sessions WHERE student_id = ?", (student_id,))
        return True


def delete_organization(org_code: str) -> int:
    """Remove an organization with its students (and, by cascade, all their records) and its
    admin's sessions and code. Dev tooling (scripts/seed_cohort.py --replace); returns how many
    students went."""
    with tx() as c:
        row = c.execute("SELECT id FROM organizations WHERE org_code = ?", (org_code,)).fetchone()
        if row is None:
            return 0
        n = c.execute("DELETE FROM students WHERE org_id = ?", (row["id"],)).rowcount
        c.execute("DELETE FROM organizations WHERE id = ?", (row["id"],))
        return n


def mark_signed_in(student_id: str) -> None:
    """The first successful sign-in turns an invited account into an active one."""
    with tx() as c:
        c.execute(
            "UPDATE students SET account_status = 'active' "
            "WHERE id = ? AND account_status = 'invited'",
            (student_id,),
        )


def set_must_change_password(student_id: str, flag: bool) -> None:
    with tx() as c:
        c.execute(
            "UPDATE students SET must_change_password = ? WHERE id = ?", (int(flag), student_id)
        )


def latest_profile(student_id: str) -> StudentProfile | None:
    with tx() as c:
        row = c.execute(
            "SELECT profile_json FROM profiles WHERE student_id = ? ORDER BY id DESC LIMIT 1",
            (student_id,),
        ).fetchone()
    return StudentProfile.model_validate_json(row["profile_json"]) if row else None


def readiness_history(student_id: str) -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(
            "SELECT created_at, readiness_score FROM profiles WHERE student_id = ? ORDER BY id",
            (student_id,),
        ).fetchall()


# --- plans ---------------------------------------------------------------------


def save_plan(student_id: str, plan: WeeklyPlan, at: str | None = None) -> None:
    with tx() as c:
        c.execute(
            """INSERT INTO plans (student_id, week_no, plan_json, rationale, created_at)
               VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
               ON CONFLICT(student_id, week_no) DO UPDATE SET
                 plan_json = excluded.plan_json, rationale = excluded.rationale""",
            (student_id, plan.week_no, plan.model_dump_json(), plan.rationale, at),
        )


def latest_plan(student_id: str) -> sqlite3.Row | None:
    """The newest plan's week_no, created_at (UTC) and days_done, or None before week 1."""
    with tx() as c:
        return c.execute(
            """SELECT week_no, created_at,
                      (SELECT COUNT(*) FROM plan_progress pp
                       WHERE pp.student_id = plans.student_id
                         AND pp.week_no = plans.week_no) AS days_done
               FROM plans WHERE student_id = ? ORDER BY week_no DESC LIMIT 1""",
            (student_id,),
        ).fetchone()


def plans_with_progress(student_id: str) -> list[tuple[WeeklyPlan, set[int]]]:
    """Every plan, oldest week first, with the days marked done, in one query."""
    with tx() as c:
        rows = c.execute(
            """SELECT p.plan_json, GROUP_CONCAT(pp.day) AS done FROM plans p
               LEFT JOIN plan_progress pp
                 ON pp.student_id = p.student_id AND pp.week_no = p.week_no
               WHERE p.student_id = ? GROUP BY p.id ORDER BY p.week_no""",
            (student_id,),
        ).fetchall()
    return [
        (
            WeeklyPlan.model_validate_json(r["plan_json"]),
            {int(d) for d in r["done"].split(",")} if r["done"] else set(),
        )
        for r in rows
    ]


def set_days_done(student_id: str, week_no: int, days: set[int]) -> None:
    """Make exactly `days` (1-7) the done days of a week; a day already done keeps its time."""
    with tx() as c:
        c.executemany(
            "DELETE FROM plan_progress WHERE student_id = ? AND week_no = ? AND day = ?",
            [(student_id, week_no, d) for d in range(1, 8) if d not in days],
        )
        c.executemany(
            "INSERT OR IGNORE INTO plan_progress (student_id, week_no, day) VALUES (?, ?, ?)",
            [(student_id, week_no, d) for d in sorted(days)],
        )


def list_plans(student_id: str) -> list[WeeklyPlan]:
    with tx() as c:
        rows = c.execute(
            "SELECT plan_json FROM plans WHERE student_id = ? ORDER BY week_no", (student_id,)
        ).fetchall()
    return [WeeklyPlan.model_validate_json(r["plan_json"]) for r in rows]


# --- quizzes -------------------------------------------------------------------


def _insert_attempt(
    c: sqlite3.Connection,
    student_id: str,
    quiz: QuizSet,
    chosen: list[int | None],
    at: str | None,
) -> tuple[int, int, int]:
    """One quiz part and its questions; returns (attempt id, correct, total)."""
    correct = sum(q.correct_index == a for q, a in zip(quiz.questions, chosen, strict=True))
    total = len(quiz.questions)
    cur = c.execute(
        """INSERT INTO quiz_attempts
           (student_id, topic, difficulty, total, correct, score_pct, attempted_at)
           VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
        (
            student_id,
            quiz.topic,
            quiz.difficulty,
            total,
            correct,
            round(100 * correct / total, 1),
            at,
        ),
    )
    c.executemany(
        """INSERT INTO quiz_questions
           (attempt_id, question_hash, text, correct_index, chosen_index)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (cur.lastrowid, text_hash(q.text), q.text, q.correct_index, a)
            for q, a in zip(quiz.questions, chosen, strict=True)
        ],
    )
    return cur.lastrowid, correct, total


def save_quiz_attempt(
    student_id: str, quiz: QuizSet, chosen: list[int | None], at: str | None = None
) -> float:
    with tx() as c:
        _, correct, total = _insert_attempt(c, student_id, quiz, chosen, at)
    return round(100 * correct / total, 1)


def save_quiz_run(
    student_id: str, parts: list[tuple[QuizSet, list[int | None]]], at: str | None = None
) -> int:
    """A quiz of several parts (topic x difficulty) in one transaction: each part an attempt,
    in the order given (so the last part of a topic is its latest attempt). Returns run id."""
    with tx() as c:
        saved = [_insert_attempt(c, student_id, quiz, chosen, at) for quiz, chosen in parts]
        correct, total = sum(s[1] for s in saved), sum(s[2] for s in saved)
        cur = c.execute(
            """INSERT INTO quiz_runs (student_id, total, correct, score_pct, attempted_at)
               VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            (student_id, total, correct, round(100 * correct / total, 1), at),
        )
        c.executemany(
            "INSERT INTO quiz_run_parts (run_id, attempt_id) VALUES (?, ?)",
            [(cur.lastrowid, s[0]) for s in saved],
        )
        return cur.lastrowid


def quiz_runs(student_id: str, limit: int = 20) -> list[sqlite3.Row]:
    """Recent multi-part quizzes, newest first: when, size, score and the topics in it."""
    with tx() as c:
        return c.execute(
            """SELECT r.id, r.attempted_at, r.total, r.correct, r.score_pct,
                      GROUP_CONCAT(DISTINCT a.topic) AS topics
               FROM quiz_runs r
               JOIN quiz_run_parts p ON p.run_id = r.id
               JOIN quiz_attempts a ON a.id = p.attempt_id
               WHERE r.student_id = ? GROUP BY r.id ORDER BY r.id DESC LIMIT ?""",
            (student_id, limit),
        ).fetchall()


def accuracy_grid(student_id: str) -> list[sqlite3.Row]:
    """Every question answered, summed per topic and difficulty."""
    with tx() as c:
        return c.execute(
            """SELECT topic, difficulty, SUM(correct) AS correct, SUM(total) AS total
               FROM quiz_attempts WHERE student_id = ? GROUP BY topic, difficulty""",
            (student_id,),
        ).fetchall()


def topic_stats(student_id: str) -> dict[str, dict]:
    """Per quizzed topic, in one query: avg_pct, the share of questions answered correctly
    over its three most recent attempts (weighted by size; for equal-sized quizzes the plain
    average), and the latest attempt's last_pct and last_difficulty."""
    with tx() as c:
        rows = c.execute(
            """SELECT topic, 100.0 * SUM(correct) / SUM(total) AS avg_pct,
                      MAX(CASE WHEN rn = 1 THEN score_pct END) AS last_pct,
                      MAX(CASE WHEN rn = 1 THEN difficulty END) AS last_difficulty
               FROM (SELECT topic, score_pct, difficulty, correct, total, ROW_NUMBER() OVER (
                       PARTITION BY topic ORDER BY attempted_at DESC, id DESC) AS rn
                     FROM quiz_attempts WHERE student_id = ?)
               WHERE rn <= 3 GROUP BY topic""",
            (student_id,),
        ).fetchall()
    return {
        r["topic"]: {
            "avg_pct": round(r["avg_pct"], 1),
            "last_pct": r["last_pct"],
            "last_difficulty": r["last_difficulty"],
        }
        for r in rows
    }


def topic_performance(student_id: str) -> dict[str, float]:
    """Average score_pct over each topic's three most recent attempts."""
    return {t: s["avg_pct"] for t, s in topic_stats(student_id).items()}


def last_attempt(student_id: str, topic: str) -> sqlite3.Row | None:
    with tx() as c:
        return c.execute(
            """SELECT score_pct, difficulty FROM quiz_attempts WHERE student_id = ? AND topic = ?
               ORDER BY attempted_at DESC, id DESC LIMIT 1""",
            (student_id, topic),
        ).fetchone()


def asked_questions(student_id: str, topic: str, limit: int = 30) -> list[str]:
    with tx() as c:
        rows = c.execute(
            """SELECT qq.text FROM quiz_questions qq
               JOIN quiz_attempts qa ON qa.id = qq.attempt_id
               WHERE qa.student_id = ? AND qa.topic = ?
               ORDER BY qq.id DESC LIMIT ?""",
            (student_id, topic, limit),
        ).fetchall()
    return [r["text"] for r in rows]


def quiz_history(student_id: str) -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(
            """SELECT a.attempted_at, a.topic, a.difficulty, a.score_pct, a.correct, a.total,
                      p.run_id
               FROM quiz_attempts a LEFT JOIN quiz_run_parts p ON p.attempt_id = a.id
               WHERE a.student_id = ? ORDER BY a.attempted_at, a.id""",
            (student_id,),
        ).fetchall()


# --- interviews ----------------------------------------------------------------


def save_turn(
    student_id: str,
    session_id: str,
    interview_type: str,
    question: str,
    answer: str,
    ev: AnswerEvaluation,
    at: str | None = None,
) -> None:
    with tx() as c:
        c.execute(
            """INSERT INTO interview_turns (student_id, session_id, interview_type, question,
                 answer, scores_json, overall, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            (
                student_id,
                session_id,
                interview_type,
                question,
                answer,
                json.dumps(ev.scores),
                ev.overall,
                at,
            ),
        )


def past_turns(student_id: str, exclude_session: str | None = None, limit: int = 30) -> list[dict]:
    """Most recent Q/A pairs from earlier sessions — the interview agent's long-term memory."""
    with tx() as c:
        rows = c.execute(
            """SELECT question, answer FROM interview_turns
               WHERE student_id = ? AND session_id IS NOT ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (student_id, exclude_session, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def interview_history(student_id: str) -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(
            """SELECT session_id, interview_type, MIN(created_at) AS started,
                      AVG(overall) AS avg_overall, COUNT(*) AS turns
               FROM interview_turns WHERE student_id = ?
               GROUP BY session_id ORDER BY started""",
            (student_id,),
        ).fetchall()


# --- agent logs ----------------------------------------------------------------


def log_call(
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    student_id: str | None = None,
    failed: str | None = None,
) -> int:
    """One LLM call. `failed`: why the call produced nothing usable; the row then carries
    reject_reason "failed: ..." and no critic verdict (agent_logs has no status column,
    and existing tables are not altered)."""
    with tx() as c:
        cur = c.execute(
            """INSERT INTO agent_logs (student_id, agent_name, model_used, input_tokens,
                                       output_tokens, latency_ms, reject_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                student_id,
                agent,
                model,
                input_tokens,
                output_tokens,
                latency_ms,
                f"{FAILED}{failed}" if failed else None,
            ),
        )
        return cur.lastrowid


def mark_failed(log_id: int, retry_count: int, reason: str) -> None:
    """A generated draft that could not be judged (verify raised): failed, not rejected."""
    with tx() as c:
        c.execute(
            "UPDATE agent_logs SET critic_approved = NULL, retry_count = ?, reject_reason = ? "
            "WHERE id = ?",
            (retry_count, f"{FAILED}{reason}", log_id),
        )


def mark_log(log_id: int, approved: bool, retry_count: int, reject_reason: str | None) -> None:
    with tx() as c:
        c.execute(
            """UPDATE agent_logs SET critic_approved = ?, retry_count = ?, reject_reason = ?
               WHERE id = ?""",
            (approved, retry_count, reject_reason, log_id),
        )


def agent_stats() -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(
            """SELECT agent_name, COUNT(*) AS calls,
                      ROUND(AVG(latency_ms)) AS avg_latency_ms,
                      ROUND(AVG(input_tokens + output_tokens)) AS avg_tokens,
                      COALESCE(SUM(critic_approved = 0), 0) AS rejections,
                      COALESCE(SUM(reject_reason LIKE 'failed: %'), 0) AS failures,
                      ROUND(AVG(CASE WHEN critic_approved IS NOT NULL
                                     THEN critic_approved = 0 END), 2) AS rejection_rate
               FROM agent_logs GROUP BY agent_name ORDER BY agent_name"""
        ).fetchall()


def recent_rejections(limit: int = 10) -> list[sqlite3.Row]:
    with tx() as c:
        return c.execute(
            """SELECT created_at, agent_name, retry_count, reject_reason FROM agent_logs
               WHERE critic_approved = 0 ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()


# --- resume versions -----------------------------------------------------------


def save_resume_version(
    student_id: str,
    domain_id: str,
    target_role: str,
    resume: dict,
    ats_score: int,
    at: str | None = None,
) -> int:
    with tx() as c:
        cur = c.execute(
            """INSERT INTO resume_versions
               (student_id, domain_id, target_role, resume_json, ats_score, created_at)
               VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            (student_id, domain_id, target_role, json.dumps(resume), ats_score, at),
        )
        return cur.lastrowid


def resume_versions(student_id: str) -> list[dict]:
    """Every saved resume, oldest first, with its JSON decoded."""
    with tx() as c:
        rows = c.execute(
            """SELECT id, domain_id, target_role, resume_json, ats_score, created_at
               FROM resume_versions WHERE student_id = ? ORDER BY id""",
            (student_id,),
        ).fetchall()
    return [{**dict(r), "resume": json.loads(r["resume_json"])} for r in rows]


def first_resume_domain(student_id: str) -> sqlite3.Row | None:
    """What locks the student's domain, in one query: domain_id and created_at of their first
    saved resume (None before one), and for an organization's student org_name and
    target_role (their organization's placement is the lock, resume or not). None when the
    student has neither."""
    with tx() as c:
        return c.execute(
            """SELECT r.domain_id, COALESCE(r.created_at, s.created_at) AS created_at,
                      o.name AS org_name, s.target_role
               FROM students s
               LEFT JOIN organizations o ON o.id = s.org_id
               LEFT JOIN resume_versions r ON r.id =
                 (SELECT MIN(id) FROM resume_versions WHERE student_id = s.id)
               WHERE s.id = ? AND (r.id IS NOT NULL OR o.id IS NOT NULL)""",
            (student_id,),
        ).fetchone()


def plan_days_done_since(student_id: str, since: str) -> int:
    with tx() as c:
        return c.execute(
            "SELECT COUNT(*) FROM plan_progress WHERE student_id = ? AND done_at >= ?",
            (student_id, since),
        ).fetchone()[0]


# --- project space -------------------------------------------------------------

PROJECT_FIELDS = ("name", "summary", "tech", "repo_url", "status", "readme", "on_resume")


def save_project(student_id: str, fields: dict, project_id: int | None = None) -> int:
    """Create a project, or update `project_id` (only when it is this student's)."""
    values = [fields[k] for k in PROJECT_FIELDS]
    with tx() as c:
        if project_id is None:
            cur = c.execute(
                """INSERT INTO projects
                   (student_id, name, summary, tech, repo_url, status, readme, on_resume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (student_id, *values),
            )
            return cur.lastrowid
        c.execute(
            """UPDATE projects SET name = ?, summary = ?, tech = ?, repo_url = ?, status = ?,
                 readme = ?, on_resume = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND student_id = ?""",
            (*values, project_id, student_id),
        )
        return project_id


def projects(student_id: str) -> list[sqlite3.Row]:
    """The student's projects, most recently active first (an update or an edit bumps
    updated_at), with their update count."""
    with tx() as c:
        return c.execute(
            """SELECT p.*, COUNT(u.id) AS updates
               FROM projects p LEFT JOIN project_updates u ON u.project_id = p.id
               WHERE p.student_id = ? GROUP BY p.id ORDER BY p.updated_at DESC, p.id DESC""",
            (student_id,),
        ).fetchall()


def delete_project(student_id: str, project_id: int) -> None:
    with tx() as c:
        c.execute("DELETE FROM projects WHERE id = ? AND student_id = ?", (project_id, student_id))


def add_project_update(student_id: str, project_id: int, note: str, at: str | None = None) -> bool:
    """Log work on a project; False when the project is not this student's."""
    with tx() as c:
        owned = c.execute(
            "SELECT 1 FROM projects WHERE id = ? AND student_id = ?", (project_id, student_id)
        ).fetchone()
        if not owned:
            return False
        c.execute(
            """INSERT INTO project_updates (project_id, note, created_at)
               VALUES (?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            (project_id, note, at),
        )
        c.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
        return True


def project_updates(student_id: str) -> list[sqlite3.Row]:
    """Every logged update of the student's projects, newest first."""
    with tx() as c:
        return c.execute(
            """SELECT u.id, u.project_id, p.name AS project, u.note, u.created_at
               FROM project_updates u JOIN projects p ON p.id = u.project_id
               WHERE p.student_id = ? ORDER BY u.created_at DESC, u.id DESC""",
            (student_id,),
        ).fetchall()
