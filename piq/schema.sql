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
    proctoring          TEXT NOT NULL DEFAULT 'off'
                        CHECK (proctoring IN ('off', 'required', 'seb')),
    seb_config_keys     TEXT NOT NULL DEFAULT '',
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
    batch_year           TEXT,
    email_verified       INTEGER NOT NULL DEFAULT 0, -- a code sent to the email was typed
    -- a contributor (piq/contributions.py) shares questions only: no role, resume or score
    account_kind         TEXT NOT NULL DEFAULT 'student'
                         CHECK (account_kind IN ('student', 'contributor'))
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
-- Each also says which device it is on (piq/devices.py), for the student's list of signed-in
-- devices: browser and OS from the User-Agent, the IP, and a location when the host provides one.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    student_id  TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    expires_at  REAL NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_hash TEXT NOT NULL DEFAULT '',
    user_agent  TEXT NOT NULL DEFAULT '',
    ip          TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    last_seen   REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions (student_id);

-- The devices (hashed browser ids) a student has signed in on: a sign-in from any other is new.
CREATE TABLE IF NOT EXISTS known_devices (
    student_id  TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    device_hash TEXT NOT NULL,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    PRIMARY KEY (student_id, device_hash)
);

-- A student's own settings (piq/prefs.py), as JSON; missing keys take the defaults.
CREATE TABLE IF NOT EXISTS student_prefs (
    student_id TEXT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    prefs_json TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- What happened at sign-in (sign-ups, sign-ins, wrong passwords, codes, new devices, sign-outs),
-- for the operations view. student_id is NULL when no account matched.
CREATE TABLE IF NOT EXISTS auth_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         REAL NOT NULL,
    student_id TEXT REFERENCES students(id) ON DELETE SET NULL,
    kind       TEXT NOT NULL,
    identifier TEXT NOT NULL DEFAULT '',
    ip         TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_auth_events_at ON auth_events (at);

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

-- Certificate PDFs the student uploaded. The file itself lives on disk at
-- <certificates_dir>/<student_id>/<stored_name> (a random name, never the student's own);
-- filename is the original name, cleaned, shown on the card and used for the download.
CREATE TABLE IF NOT EXISTS certificates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    issuer      TEXT NOT NULL,
    issue_date  TEXT,
    filename    TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    size_bytes  INTEGER NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    drive_file_id TEXT  -- its copy in the student's Google Drive, when they connected one
);

CREATE INDEX IF NOT EXISTS idx_certificates_student ON certificates (student_id, id);

-- A student's own AI model on this computer (core/local_ai.py): Ollama or LM Studio. Used only
-- while the server allows it (LOCAL_AI) and only at a localhost / 127.0.0.1 / ::1 address.
CREATE TABLE IF NOT EXISTS student_local_ai (
    student_id TEXT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    provider   TEXT NOT NULL CHECK (provider IN ('ollama', 'lmstudio')),
    base_url   TEXT NOT NULL,
    model      TEXT NOT NULL,
    preferred  INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Adaptive quizzes (piq/services.py): each student's level per topic. A topic with no row
-- starts from the suggestion its latest attempt gives (medium before the first quiz).
CREATE TABLE IF NOT EXISTS topic_levels (
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    topic      TEXT NOT NULL,
    level      TEXT NOT NULL CHECK (level IN ('easy', 'medium', 'hard')),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id, topic)
);

-- Questions the AI wrote when the bank ran out at a level, kept whole so a quiz served over
-- the API can be graded and a missed one asked again. They are never served to another
-- student (an offline answer may pad with generic practice questions). source: 'ai' (through
-- the critic) or 'mock' (MOCK_MODE samples).
CREATE TABLE IF NOT EXISTS generated_questions (
    qid           TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    difficulty    TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    question_json TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('ai', 'mock')),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_generated_topic ON generated_questions (topic, difficulty);

-- Questions a student got wrong (or left blank), brought back in a later quiz on the topic:
-- a similar bank question when there is one (served_qid), else the same question again.
-- Right on review: done. Wrong again: misses + 1, dropped after REVIEW_MAX_MISSES.
CREATE TABLE IF NOT EXISTS review_queue (
    student_id    TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    qid           TEXT NOT NULL,
    topic         TEXT NOT NULL,
    difficulty    TEXT NOT NULL,
    question_json TEXT NOT NULL,
    misses        INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'served', 'done')),
    served_qid    TEXT,
    missed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id, qid)
);

CREATE INDEX IF NOT EXISTS idx_review_due ON review_queue (student_id, topic, status);

-- Interview experiences students report in their own words (piq/experiences.py): our own bank,
-- never copied from another site. Pending until a human approves: the poster's organization
-- admin, or the operations view for an individual learner (org_id NULL). The poster is never
-- shown: browse shows a label worked out when read ("a <college> student, <year>", or
-- "a student, <year>" for small batches, hidden colleges and individual learners).
CREATE TABLE IF NOT EXISTS interview_experiences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    org_id          INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    org_short       TEXT NOT NULL DEFAULT '',
    batch_year      TEXT NOT NULL DEFAULT '',
    show_college    INTEGER NOT NULL DEFAULT 1,
    company_slug    TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    role            TEXT NOT NULL,
    round           TEXT NOT NULL
                    CHECK (round IN ('aptitude', 'technical', 'hr', 'coding', 'group_discussion')),
    interview_month TEXT NOT NULL,
    tip             TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'hidden')),
    flags           TEXT NOT NULL DEFAULT '[]',
    reject_reason   TEXT NOT NULL DEFAULT '',
    reviewed_by     TEXT NOT NULL DEFAULT '',
    reviewed_at     TIMESTAMP,
    content_hash    TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_experiences_browse ON interview_experiences (status, company_slug, round);
CREATE INDEX IF NOT EXISTS idx_experiences_student ON interview_experiences (student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_experiences_org ON interview_experiences (org_id, status);

CREATE TABLE IF NOT EXISTS experience_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experience_id INTEGER NOT NULL REFERENCES interview_experiences(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('open', 'mcq')),
    text          TEXT NOT NULL,
    options_json  TEXT NOT NULL DEFAULT '[]',
    correct_index INTEGER,
    explanation   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_experience_questions ON experience_questions (experience_id, position);

-- The interview process a post reports, with or instead of questions: the rounds in order
-- ([{type, minutes or null, difficulty}]), the result and a short summary (cleaned like the
-- questions). Goes with its post, and so with the student's account.
CREATE TABLE IF NOT EXISTS experience_processes (
    experience_id INTEGER PRIMARY KEY REFERENCES interview_experiences(id) ON DELETE CASCADE,
    rounds_json   TEXT NOT NULL,
    result        TEXT NOT NULL CHECK (result IN ('selected', 'not_selected', 'waiting')),
    summary       TEXT NOT NULL DEFAULT ''
);

-- One report per student per post; enough reports hide a post until its moderator looks again.
CREATE TABLE IF NOT EXISTS experience_reports (
    experience_id INTEGER NOT NULL REFERENCES interview_experiences(id) ON DELETE CASCADE,
    student_id    TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (experience_id, student_id)
);

-- Google Drive (core/drive.py), only while the server sets GOOGLE_CLIENT_ID/SECRET and
-- DRIVE_TOKEN_KEY. The refresh token is stored encrypted (AES-GCM, DRIVE_TOKEN_KEY, bound to
-- the student); the short-lived access token is never stored. Disconnecting deletes the row.
CREATE TABLE IF NOT EXISTS drive_accounts (
    student_id        TEXT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    refresh_token_enc TEXT NOT NULL,
    scope             TEXT NOT NULL,
    root_id           TEXT NOT NULL DEFAULT '',
    certs_id          TEXT NOT NULL DEFAULT '',
    resumes_id        TEXT NOT NULL DEFAULT '',
    connected_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- An OAuth sign-in in progress: only the state's SHA-256 and the PKCE verifier (encrypted),
-- single use, expiring after a few minutes.
CREATE TABLE IF NOT EXISTS drive_oauth_states (
    state_hash   TEXT PRIMARY KEY,
    student_id   TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    verifier_enc TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    return_to    TEXT NOT NULL,
    expires_at   REAL NOT NULL
);

-- Company practice scores, kept apart from quiz_attempts: they never move a syllabus topic's
-- level, weakness or the weekly plan.
CREATE TABLE IF NOT EXISTS company_practice (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    company_slug TEXT NOT NULL,
    round        TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('reported', 'ai', 'open')),
    correct      INTEGER NOT NULL,
    total        INTEGER NOT NULL,
    at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Proctoring (core/proctoring.py): one row per proctored quiz or interview, and its events.
-- Only event kinds and times are kept, never video, images or landmarks. The student and their
-- organization's admin can see them; both tables go with the account (CASCADE).
CREATE TABLE IF NOT EXISTS proctor_attempts (
    id                   TEXT PRIMARY KEY,
    student_id           TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    kind                 TEXT NOT NULL CHECK (kind IN ('quiz', 'interview')),
    label                TEXT NOT NULL,
    mode                 TEXT NOT NULL CHECK (mode IN ('practice', 'required', 'seb')),
    camera               TEXT NOT NULL CHECK (camera IN ('on', 'unavailable')),
    camera_note          TEXT NOT NULL DEFAULT '',
    consent_at           REAL NOT NULL,
    started_at           REAL NOT NULL,
    last_seen            REAL NOT NULL,
    ended_at             REAL,
    strikes              INTEGER NOT NULL DEFAULT 0,
    last_clear_at        REAL,
    breached             INTEGER NOT NULL DEFAULT 0,
    quiz_run_id          INTEGER,
    interview_session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_proctor_attempts_student
    ON proctor_attempts (student_id, started_at);

CREATE TABLE IF NOT EXISTS proctor_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL REFERENCES proctor_attempts(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    severity   TEXT NOT NULL CHECK (severity IN ('clear', 'review')),
    strike     INTEGER NOT NULL DEFAULT 0,
    at_s       REAL NOT NULL,
    duration_s REAL
);
CREATE INDEX IF NOT EXISTS idx_proctor_events_attempt ON proctor_events (attempt_id, at_s);

-- Hands-free voice interviews (piq/handsfree.py): the rules each run was given (the same for
-- everyone, frozen when it starts) and how each answer was given (voice, push-to-talk, typed)
-- with the reason for any fallback. No audio is stored. Deleted with the account.
CREATE TABLE IF NOT EXISTS handsfree_runs (
    id                   TEXT PRIMARY KEY,
    student_id           TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    interview_session_id TEXT,
    rules_json           TEXT NOT NULL,
    started_at           REAL NOT NULL,
    ended_at             REAL
);
CREATE INDEX IF NOT EXISTS idx_handsfree_runs_student ON handsfree_runs (student_id, started_at);

CREATE TABLE IF NOT EXISTS handsfree_answers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL REFERENCES handsfree_runs(id) ON DELETE CASCADE,
    question_index    INTEGER NOT NULL,
    attempt_no        INTEGER NOT NULL,
    input             TEXT NOT NULL CHECK (input IN ('voice', 'push_to_talk', 'typed')),
    fallback_reason   TEXT NOT NULL DEFAULT '',
    duration_s        REAL,
    transcript_source TEXT NOT NULL DEFAULT '',
    at                REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_handsfree_answers_run ON handsfree_answers (run_id, question_index);

-- Contributors (piq/contributions.py): placed students, alumni and professionals who add
-- questions to the open bank (students.account_kind = 'contributor': no target role, resume or
-- readiness score), and students who contribute too (company_joined empty). Credit is opt-in:
-- anonymous unless credit_opt_in is set with a display name.
CREATE TABLE IF NOT EXISTS contributors (
    student_id     TEXT PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    company_joined TEXT NOT NULL DEFAULT '',
    credit_opt_in  INTEGER NOT NULL DEFAULT 0,
    display_name   TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Questions contributed to the open bank, licensed CC BY 4.0 by their author (accepted on the
-- form, recorded per question). Cleaned and checked like interview posts, critic-checked in
-- live mode, pending until a moderator approves (the author's organization admin, else the
-- operations view). Approved multiple-choice questions join the quiz bank; open ones (with
-- their model answer) the general-practice interviews. Deleted with the author's account.
CREATE TABLE IF NOT EXISTS contributed_questions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id           TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    org_id              INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('mcq', 'open')),
    round               TEXT NOT NULL CHECK (round IN ('aptitude', 'technical', 'hr')),
    topic               TEXT NOT NULL,
    difficulty          TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    text                TEXT NOT NULL,
    options_json        TEXT NOT NULL DEFAULT '[]',
    correct_index       INTEGER,
    explanation         TEXT NOT NULL DEFAULT '',
    model_answer        TEXT NOT NULL DEFAULT '',
    licence             TEXT NOT NULL DEFAULT 'CC-BY-4.0' CHECK (licence = 'CC-BY-4.0'),
    licence_accepted_at TIMESTAMP NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'hidden')),
    flags               TEXT NOT NULL DEFAULT '[]',
    reject_reason       TEXT NOT NULL DEFAULT '',
    reviewed_by         TEXT NOT NULL DEFAULT '',
    reviewed_at         TIMESTAMP,
    content_hash        TEXT NOT NULL UNIQUE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_contributed_status ON contributed_questions (status, round);
CREATE INDEX IF NOT EXISTS idx_contributed_author ON contributed_questions (author_id, created_at);
