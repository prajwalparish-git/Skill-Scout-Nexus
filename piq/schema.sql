-- Rule: agent outputs that are always read whole are stored as JSON;
-- anything filtered, aggregated or charted gets its own column.

-- An organization (a university, college or corporate L&D team): its main admin signs in with
-- admin_email and admin_password_hash (core/auth.py), then manages the students it provisions.
-- Sign-in state (the hash, the verified flag, the lockout counters) stays in this local file
-- only: the telemetry copy of an organization (database/models.py) never carries it.
CREATE TABLE IF NOT EXISTS organizations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    org_code            TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    org_type            TEXT NOT NULL,
    official_domain     TEXT NOT NULL DEFAULT '',
    admin_name          TEXT NOT NULL,
    admin_email         TEXT NOT NULL UNIQUE,
    admin_password_hash TEXT NOT NULL,
    contact_phone       TEXT NOT NULL DEFAULT '',
    location            TEXT NOT NULL DEFAULT '',
    academic_batch      TEXT NOT NULL DEFAULT '',
    quiz_cutoff_pct     INTEGER NOT NULL DEFAULT 70,
    voice_cutoff_score  INTEGER NOT NULL DEFAULT 10,
    admin_verified      INTEGER NOT NULL DEFAULT 0,
    admin_failures      INTEGER NOT NULL DEFAULT 0,
    admin_locked_until  REAL NOT NULL DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- A student is an account: a unique lower-case username (also the key telemetry syncs by) and
-- a unique email (NULL only for the demo account and accounts made before sign-up existed).
-- org_id is NULL for an individual learner and the organization's id for a student it manages;
-- then main_domain / subdomain (Engineering / Computer Science) are what its admin assigned.
-- piq/db.py migrates a database from before accounts or organizations in place on start.
CREATE TABLE IF NOT EXISTS students (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    username             TEXT NOT NULL UNIQUE,
    email                TEXT,
    target_role          TEXT NOT NULL,
    readiness_score      INTEGER,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    org_id               INTEGER REFERENCES organizations(id),
    main_domain          TEXT,
    subdomain            TEXT,
    account_status       TEXT NOT NULL DEFAULT 'active'
                         CHECK (account_status IN ('active', 'invited', 'suspended')),
    must_change_password INTEGER NOT NULL DEFAULT 0,
    phone                TEXT,
    batch_year           TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email ON students (email);
CREATE INDEX IF NOT EXISTS idx_students_org ON students (org_id);

-- Sign-in state stays in this local file only: it is never synced to the cloud copy.
-- A password as core/auth.py stores it, and the lockout counter (core/auth.Lockout).
CREATE TABLE IF NOT EXISTS credentials (
    student_id    TEXT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    failures      INTEGER NOT NULL DEFAULT 0,
    locked_until  REAL NOT NULL DEFAULT 0,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- The 9-digit email code waiting to be typed, one per purpose: only its salted hash.
CREATE TABLE IF NOT EXISTS auth_codes (
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    purpose    TEXT NOT NULL CHECK (purpose IN ('login', 'recover')),
    code_hash  TEXT NOT NULL,
    salt       TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    sent_at    REAL NOT NULL,
    PRIMARY KEY (student_id, purpose)
);

-- "Stay signed in": the SHA-256 of the browser cookie's token, never the token itself.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions (student_id);

-- The same two for an organization's admin: the code that proves the admin's email when the
-- organization is created, and "stay signed in" (hashes only, as above).
CREATE TABLE IF NOT EXISTS admin_codes (
    org_id     INTEGER PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    code_hash  TEXT NOT NULL,
    salt       TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    sent_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    org_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    profile_json    TEXT NOT NULL,
    readiness_score INTEGER NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    week_no     INTEGER NOT NULL,
    plan_json   TEXT NOT NULL,
    rationale   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, week_no)
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    topic        TEXT NOT NULL,
    difficulty   TEXT NOT NULL,
    total        INTEGER NOT NULL,
    correct      INTEGER NOT NULL,
    score_pct    REAL NOT NULL,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id    INTEGER NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,
    question_hash TEXT NOT NULL,
    text          TEXT NOT NULL,
    correct_index INTEGER NOT NULL,
    chosen_index  INTEGER
);

CREATE TABLE IF NOT EXISTS interview_turns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    session_id     TEXT NOT NULL,
    interview_type TEXT NOT NULL,
    question       TEXT NOT NULL,
    answer         TEXT NOT NULL,
    scores_json    TEXT NOT NULL,
    overall        REAL NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT,
    agent_name      TEXT NOT NULL,
    model_used      TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    critic_approved BOOLEAN,
    retry_count     INTEGER,
    reject_reason   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quiz_student_topic ON quiz_attempts (student_id, topic, attempted_at);
CREATE INDEX IF NOT EXISTS idx_turns_student ON interview_turns (student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qq_hash ON quiz_questions (question_hash);

-- Plan days the student marked done (Weekly plan). Added with CREATE TABLE IF NOT EXISTS,
-- so an existing database gains it without a migration.
CREATE TABLE IF NOT EXISTS plan_progress (
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    week_no    INTEGER NOT NULL,
    day        INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),
    done_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id, week_no, day)
);

-- A quiz as the student set it up: several topics and difficulties at once. Each part (one
-- topic at one difficulty) is a quiz_attempts row, so weakness and difficulty suggestions
-- read them as before; a run groups its parts for the result breakdown and history.
CREATE TABLE IF NOT EXISTS quiz_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    total        INTEGER NOT NULL,
    correct      INTEGER NOT NULL,
    score_pct    REAL NOT NULL,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quiz_run_parts (
    run_id     INTEGER NOT NULL REFERENCES quiz_runs(id) ON DELETE CASCADE,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES quiz_attempts(id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, attempt_id)
);

-- Every resume saved from the Resume builder, oldest first. The first version's domain locks
-- the student's domain (their plans and quizzes are built on its syllabus).
CREATE TABLE IF NOT EXISTS resume_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    domain_id   TEXT NOT NULL,
    target_role TEXT NOT NULL,
    resume_json TEXT NOT NULL,
    ats_score   INTEGER NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_resume_student ON resume_versions (student_id, id);

-- Project space (computing domains): the student's repositories and a log of work on each.
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    tech       TEXT NOT NULL DEFAULT '',
    repo_url   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL,
    readme     TEXT NOT NULL DEFAULT '',
    on_resume  BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, name)
);

CREATE TABLE IF NOT EXISTS project_updates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    note       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
