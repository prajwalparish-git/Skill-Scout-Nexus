"""Settings loaded once from the environment / .env file."""

import os
import re
from dataclasses import dataclass, field
from datetime import time
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "evaluation" / "results"
STATIC_DIR = ROOT / "static"  # served at app/static/: fonts, brand, app.css
BRAND_DIR = STATIC_DIR / "brand"  # mark.svg (icon) and wordmark.svg

# The computer-science core syllabus. Every domain's own topics (and which of them are always
# tracked) live in data/career_catalog.json and are read by piq/syllabus.py; these six stay
# the CS core, which the frozen evaluation and the demo seed are built on.
TOPICS = ("Aptitude", "DBMS", "OS", "CN", "DSA", "OOP")
DEFAULT_DOMAIN = "cs"  # the domain of a role the catalog does not list (the original CS roles)
DEFAULT_SAMPLE = "data_analyst.txt"  # the sample Home's "Try it with a sample resume" opens
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# --- accounts (piq/accounts.py, core/auth.py, core/mailer.py) --------------------------------
# A username is the student's identity everywhere, cloud sync included: lower-case, 3-20
# characters, starting with a letter or digit (20 keeps the telemetry column's width).
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,19}$")
EMAIL_MAX = 254
PASSWORD_MIN, PASSWORD_MAX = 8, 128
AUTH_PBKDF2_ITERATIONS = 600_000  # PBKDF2-HMAC-SHA256, OWASP's 2023 figure
AUTH_SALT_BYTES = 16
AUTH_MAX_FAILURES = 5  # wrong passwords or codes in a row before the account locks
AUTH_LOCK_S = 15 * 60
AUTH_CODE_TTL_S = 10 * 60  # a 9-digit email code expires after this
AUTH_CODE_MAX_ATTEMPTS = 5  # wrong tries before a code is void
AUTH_CODE_RESEND_S = 30  # a new code is sent at most this often
SESSION_TTL_S = 7 * 24 * 3600  # how long "stay signed in" lasts (the browser cookie too)
SESSION_COOKIE = "piq_session"
DEMO_USERNAME = "demo"  # the 1-click demo account (scripts/seed.py); it has no password
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587  # 465 also works (implicit TLS)
SMTP_TIMEOUT_S = 15
MAIL_WORKERS = 2
MAIL_BATCH = 50  # messages sent over one SMTP connection (core/mailer.py send_many)
# --- telemetry storage (database/): local SQLite always, a cloud PostgreSQL copy in background --
DB_CONNECT_TIMEOUT = 3  # seconds to wait for the cloud database (Supabase) to connect
CLOUD_POOL_SIZE = 5  # Supabase transaction pooler (port 6543) or session pooler (5432)
CLOUD_MAX_OVERFLOW = 10
CLOUD_POOL_TIMEOUT_S = 3  # seconds to wait for a free pooled connection
SQLITE_BUSY_TIMEOUT_MS = 5000  # the UI and the sync thread share the file: wait, never fail
SYNC_WORKERS = 2  # background threads that push local records to the cloud
SYNC_BATCH = 100  # outbox rows read per pass
SYNC_RETRY_S = 15  # first retry after the cloud is unreachable; doubles up to SYNC_RETRY_MAX_S
SYNC_RETRY_MAX_S = 300
SYNC_MAX_ATTEMPTS = 3  # a record the cloud rejects this many times is set aside and reported
SYNC_KEEP_DAYS = 30  # synced outbox rows are pruned after this many days
DEMO_COHORT_PREFIX = "cohort"  # demo cohort usernames (scripts/seed_cohort.py): never synced
# --- organizations: the admin portal and bulk provisioning (piq/orgs.py, core/org_provisioning.py)
ORG_TYPES = ("University", "Autonomous Institute", "Law/Commerce College", "Corporate L&D")
ORG_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,29}$")  # DBIT-BLR-2027: upper-case, 3-30 characters
DOMAIN_RE = re.compile(r"^(?=.{4,120}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
BATCH_RE = re.compile(r"^\d{4}(-\d{4})?$")  # 2027 or 2026-2027
PHONE_RE = re.compile(r"^\+?\d[\d ()-]{6,18}$")
ORG_QUIZ_CUTOFF_DEFAULT = 70  # percent: an organization's quiz pass mark until its admin sets one
ORG_VOICE_CUTOFF_DEFAULT = 10  # out of VOICE_RUBRIC_MAX
ACCOUNT_STATUSES = ("active", "invited", "suspended")
ORG_WELCOME_CODE_TTL_S = 7 * 24 * 3600  # the 9-digit code in a welcome email works this long
TEMP_PASSWORD_LEN = 12  # generated passwords (core/org_provisioning.py)
CSV_MAX_BYTES = 1_000_000  # a student CSV above this is refused
CSV_MAX_ROWS = 1000
ACTIVE_WITHIN_DAYS = 14  # a learner with a quiz or voice session this recent counts as active
DEMO_ORG_CODE = "DEMO-DBIT-2027"  # the 1-click demo organization (scripts/seed_cohort.py)
DEMO_ORG_NAME = "Don Bosco Institute of Technology - Multi-Stream Placement Cell"
DEMO_ORG_PREFIX = "DEMO-"  # demo organizations are never synced to the cloud copy
# --- Layer 3: the AI and speech routers (core/) --------------------------------------
# Speed first: Groq (fastest cloud), Gemini, a local Ollama; then the offline tier.
AI_PROVIDER_NAMES = ("groq", "gemini", "ollama")  # every provider core/ai_router.py knows
ROUTER_FAILURE_THRESHOLD = 2  # failures in a row that open a provider's circuit breaker
ROUTER_COOLDOWN_S = 60  # seconds an open breaker skips its provider before one trial request
ROUTER_BROKEN_COOLDOWN_S = 3600  # a retired model or a refused key: skip for an hour
KEY_COOLDOWN_S = 60  # a rate-limited key rests this long (or the server's retry-after)
KEY_LATENCY_WEIGHT = 0.3  # weight of the newest sample in a key's moving-average latency
GROQ_TIMEOUT_S = 4.0  # default per-request timeouts (GROQ_TIMEOUT_S / GEMINI_TIMEOUT_S in .env)
GEMINI_TIMEOUT_S = 5.0
OLLAMA_TIMEOUT_S = 180  # a local model on a laptop CPU is slow
OLLAMA_PING_TIMEOUT_S = 0.2  # the TCP ping before every Ollama request
OLLAMA_PROBE_TIMEOUT_S = 1.0  # the model check (GET /api/tags) must answer within this
OLLAMA_HEALTH_TTL_S = 30  # seconds the model check's answer is reused
OLLAMA_KEEP_ALIVE = -1  # keep the model loaded in RAM/VRAM between requests
OLLAMA_TEMPERATURE = 0.2  # small local models keep to valid JSON far better when cool
OLLAMA_NUM_CTX = 2048  # defaults; OLLAMA_NUM_CTX / OLLAMA_NUM_PREDICT in .env override
OLLAMA_NUM_PREDICT = 512
# Prompt cache (core/ai_cache.py): only answers that should not vary for the same input.
# Quizzes and interview questions are left out: a student regenerating one wants new ones.
AI_CACHE_AGENTS = frozenset({"planner", "critic", "evaluator"})
AI_CACHE_MAX_ENTRIES = 500
AI_CACHE_TTL_S = 7 * 24 * 3600
TTS_TIMEOUT_S = 20  # seconds to wait for ElevenLabs before the browser voice takes over
TTS_MAX_CHARS = 2500  # text sent for synthesis; longer text is cut at the last full sentence
# --- the six-step journey and the faculty dashboard (piq/journey.py, piq/cohort.py) ----------
CRITIC_QUIZ_SIZES = (3, 5, 10)  # questions a critic-checked quiz can have
CRITIC_QUIZ_DEFAULT = 5
CRITIC_QUIZ_DEFAULT_DIFFICULTY = "medium"
ROADMAP_DEFAULT_SKILLS = 7  # gaps the roadmap page preselects: seven days, one skill each
VOICE_DEFAULT_CATEGORY = "situational"  # the voice page's preselected question type
# Speculative preloading (core/preloader.py): the next steps' content is written in the
# background while the student reads the current one.
PRELOAD_WORKERS = 4
PRELOAD_WAIT_S = 1.5  # a page waits this long for a preload still running, then falls back
PRELOAD_TTL_S = 24 * 3600  # an unused preload is dropped after this
PRELOAD_QUIZ_SKILLS = 1  # skills quizzed ahead of time: the top gap, the page's default
# A student's placement readiness (0-100) for the faculty report: the weighted mean of what
# they have done: resume match (%), quiz average (%), voice rubric (scaled to %). Weights of
# missing parts are spread over the rest; with none done the student is "Not assessed".
READINESS_WEIGHTS = {"resume": 0.3, "quiz": 0.4, "voice": 0.3}
READY_AT = 75  # readiness at or above this: "Ready"
NEARLY_READY_AT = 50  # at or above this: "Nearly ready"; below: "Needs work"
GAP_CHART_TOP = 10  # skill gaps the faculty chart shows
ELEVENLABS_DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # a premade voice; ELEVENLABS_VOICE_ID overrides
BROWSER_VOICE_LANG = "en-IN"  # the Web Speech API voice the browser fallback asks for
VOICE_RUBRIC_MAX = 15  # a voice interview's rubric score runs 0 to 15
VOICE_CRITERION_MAX = 5  # verbal clarity and relevance each run 0 to 5
MAX_DOMAIN_TOPICS = 10  # one topic colour each; tests/test_syllabus.py enforces it
DIFFICULTIES = ("easy", "medium", "hard")
INTERVIEW_TYPES = ("HR", "Technical", "Project")  # generic types; the frozen evaluation uses them
INSTANT_QUIZ_SIZE = 5  # questions in a quiz served straight from the question bank
BULLET_MAX_CHARS = 400  # a resume bullet sent for an XYZ rewrite

QUIZ_SIZE = 5  # questions per topic when a quiz is first set up
QUIZ_MAX_PER_TOPIC = 50
QUIZ_MAX_TOTAL = 100
QUIZ_BATCH = 10  # questions per generation call; each batch is checked by the critic
# Share of each quiz part (one topic at one difficulty) drawn from the local question bank
# (piq/question_bank.py) when it has unseen questions; the LLM writes the rest, through the
# critic. Half keeps the critic visible on every quiz while halving its token cost.
QUIZ_BANK_SHARE = 0.5
DEFAULT_MIX = {"easy": (60, 90), "medium": (20, 80), "hard": (10, 40)}  # slider handles per level
RESUME_REVIEW_DAYS = 14  # a resume version this old is due for review
RESUME_MAX_EDUCATION = 6  # education entries a resume can list (Class 10 to a doctorate)
RESUME_MAX_EXPERIENCE = 8  # jobs, internships and other work a resume can list
# Kinds of work; every kind but an internship counts towards years of experience.
EXPERIENCE_TYPES = (
    "Full-time",
    "Internship",
    "Part-time",
    "Contract",
    "Freelance",
    "Apprenticeship",
)
RESUME_MASTERY_AT = 70  # recent quiz average (%) at which a topic's skills belong on the resume
PROJECT_STATUSES = ("Idea", "In progress", "Done")
INTERVIEW_MAX_TURNS = 5
CRITERION_WEAK_BELOW = 3.0  # an interview criterion averaging below this gets a tip
# One fixed tip per rubric criterion (the evaluator's four), shown when it averages low.
INTERVIEW_TIPS = {
    "relevance": "Answer the question that was asked in your first sentence, then add detail.",
    "depth": "Add specifics: a number, a tool, a trade-off you weighed or the result you got.",
    "structure": (
        "Use STAR for behavioural answers (situation, task, action, result); for technical "
        "ones, define the idea, explain how it works, then give an example."
    ),
    "clarity": "Use short sentences with one idea each, and end by restating your main point.",
}
# Readiness weighs a required skill practised under a syllabus topic (role_skills.json maps it to
# a topic) this many times a tool skill (mapped to null): the topics are what recruitment tests
# examine, a tool is learnt in days.
SYLLABUS_SKILL_WEIGHT = 2
WEAK_THRESHOLD = 0.5  # weakness above this marks a topic as weak
WEAK_MIN_SHARE = 0.5  # weak topics must get at least this share of weekly minutes
DIFFICULTY_UP_AT = 80  # a quiz score (%) at or above this suggests the next difficulty up
DIFFICULTY_DOWN_BELOW = 50  # a score below this suggests the next difficulty down
TREND_STEP = 10  # points the latest quiz must beat (or miss) the ones before by to count as a trend
RESUME_MAX_PDF_PAGES = 30  # pages read from a PDF resume; the rest is ignored
RESUME_MAX_DOCX_UNZIPPED = 25 * 1024 * 1024  # bytes a DOCX may unpack to (zip-bomb guard)
RESUME_MAX_TEXT_CHARS = 200_000  # text kept from one file: a decompression bomb stops here
RESUME_MAX_BYTES = 5 * 1024 * 1024  # an upload above this is refused (.streamlit/config.toml too)
TIMEZONE = "Asia/Kolkata"  # students' local time, for dates shown in the app
STUDY_TIME = time(19, 0)  # default daily start of an exported plan's calendar events
RECENT_DAYS = 7  # a topic quizzed within this many days counts as practised; a plan
# this old is due for next week's version

# --- design tokens: the UI's colours ------------------------------------------------
# .streamlit/config.toml mirrors these (Streamlit reads only TOML); tests/test_theme.py
# checks contrast and that both files agree. See docs/design/DESIGN.md.
SCHEMES = ("light", "dark")

PALETTE = {
    "light": {
        "background": "#FBFBFA",  # page
        "surface": "#F0F2F0",  # sidebar, inputs, table headers
        "text": "#1A2326",
        "muted": "#566461",  # captions and secondary text
        "border": "#7A8582",  # input and card edges, >= 3:1
        "hairline": "#DCE1DE",  # table rules only (decorative)
        "primary": "#0D6670",  # actions; also today's focus and streaks, always with an icon
        "primary_text": "#0D6670",  # links and teal text, >= 4.5:1
    },
    "dark": {
        "background": "#111A1C",
        "surface": "#1A2528",
        "text": "#E3EAE8",
        "muted": "#A0AEAB",
        "border": "#64716E",
        "hairline": "#2C383B",
        "primary": "#1F7F86",
        "primary_text": "#6CCBC4",
    },
}

# Logo teal (static/brand/*.svg): an <img> cannot follow the theme toggle, so one tone that
# reads on both sidebars and both page backgrounds (>= 3:1 on each).
BRAND_COLOR = "#278C93"

# Status colours: always shown with an icon and words, never used for a topic.
SEMANTIC_COLORS = {
    "light": {"success": "#1B6F36", "warning": "#784E00", "error": "#951B2C", "info": "#0045D2"},
    "dark": {"success": "#5BBF7A", "warning": "#F0D45C", "error": "#FF8675", "info": "#A9BCF5"},
}

# Topic colours by position: a domain's n-th topic (career_catalog.json) takes the n-th colour,
# so a topic keeps its colour on every page. The first six are Okabe-Ito hues without yellow;
# the last four (purple, olive, rose, violet) were chosen to stay as far from all others as the
# contrast rule allows. Lightness is tuned per scheme to >= 3:1 on the background. They mark
# chart series and topic chips (which also show the topic name), never a status.
TOPIC_PALETTE = {
    "light": (
        "#C78100",
        "#005D9C",
        "#A55582",
        "#009B71",
        "#B23D00",
        "#3799CC",
        "#672692",
        "#7A710D",
        "#6C3C4B",
        "#7858BB",
    ),
    "dark": (
        "#EFA71C",
        "#0975B6",
        "#DF8BB9",
        "#009B71",
        "#D05900",
        "#55B4E8",
        "#A365D4",
        "#A09520",
        "#D35182",
        "#B495FE",
    ),
}

# Quiz outcomes in result charts. Vega cannot follow the theme switch, so each reads at >= 3:1
# on both page backgrounds; the charts also name every outcome in words (legend, tooltip).
OUTCOME_COLORS = {"Correct": BRAND_COLOR, "Wrong": "#CF4B5B", "Skipped": "#8E8A80"}  # warm grey


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(repr=False)  # the pool's first key (scripts/check_models.py)
    model_large: str
    model_small: str
    db_path: Path
    max_critic_retries: int
    mock_mode: bool
    seed_demo: bool = False  # recreate the demo student on start when the DB is empty
    # GROQ_API_KEYS (comma-separated) plus GROQ_API_KEY and the older GROQ_API_KEY_1/_2: one
    # round-robin pool (core/key_pool.py).
    groq_api_keys: tuple[str, ...] = field(default=(), repr=False)
    # Telemetry layer (database/): PostgreSQL when DATABASE_URL answers, else this SQLite file.
    database_url: str = field(default="", repr=False)
    telemetry_db_path: Path = DATA_DIR / "placement_nexus.db"
    # Layer 3 (core/ai_router.py): providers tried in this order; empty key or URL = skipped.
    ai_providers: tuple[str, ...] = AI_PROVIDER_NAMES
    gemini_api_key: str = field(default="", repr=False)  # the first key of the Gemini pool
    gemini_api_keys: tuple[str, ...] = field(default=(), repr=False)
    gemini_model: str = ""
    ollama_base_url: str = ""
    ollama_model: str = ""
    groq_timeout_s: float = GROQ_TIMEOUT_S
    gemini_timeout_s: float = GEMINI_TIMEOUT_S
    ollama_num_ctx: int = OLLAMA_NUM_CTX
    ollama_num_predict: int = OLLAMA_NUM_PREDICT
    ai_cache: bool = True  # evaluation/run_eval.py turns it off
    ai_cache_path: Path = DATA_DIR / ".ai_cache.json"
    audio_cache_dir: Path = DATA_DIR / ".audio_cache"
    # true: when no provider answers, serve the deterministic offline tier (piq/mock.py) instead
    # of an error. evaluation/run_eval.py turns it off: offline answers would void its results.
    offline_fallback: bool = True
    # core/speech_router.py: empty key = the browser's own voice (Web Speech API).
    elevenlabs_api_key: str = field(default="", repr=False)
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = ""
    # core/preloader.py: false stops speculative generation (saves quota; pages work as before).
    preload: bool = True
    preload_cache_dir: Path = DATA_DIR / ".preload_cache"
    # core/mailer.py: Gmail SMTP with an App Password; blank = codes go to mail_outbox_path.
    smtp_email: str = ""
    smtp_app_password: str = field(default="", repr=False)
    smtp_host: str = SMTP_HOST
    smtp_port: int = SMTP_PORT
    mail_outbox_path: Path = DATA_DIR / ".mail_outbox.log"
    # core/auth.py: an optional secret mixed into every password hash (never stored in the DB).
    auth_pepper: str = field(default="", repr=False)
    # app.py shows a friendly message for a crashed page; tests set PIQ_RAISE_ERRORS=1 so
    # AppTest sees the exception instead.
    raise_page_errors: bool = False


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


def key_pool(*names: str) -> tuple[str, ...]:
    """Every key in these variables, in order, without repeats: each may hold one key or a
    comma-separated list (GROQ_API_KEYS=key1,key2,key3)."""
    keys = (k.strip() for name in names for k in os.getenv(name, "").split(","))
    return tuple(dict.fromkeys(k for k in keys if k))


def _number[N: (int, float)](name: str, default: N) -> N:
    try:
        value = type(default)(os.getenv(name, "").strip() or default)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number") from e
    if value <= 0:
        raise ConfigError(f"{name} must be above zero")
    return value


def _providers(raw: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(p.strip().lower() for p in raw.split(",") if p.strip()))
    unknown = [p for p in names if p not in AI_PROVIDER_NAMES]
    if unknown:
        raise ConfigError(
            f"AI_PROVIDERS lists unknown provider(s) {', '.join(unknown)}; "
            f"choose from {', '.join(AI_PROVIDER_NAMES)}"
        )
    return names


@lru_cache
def settings() -> Settings:
    # PIQ_DOTENV lets tests point at a non-existent file so the developer's .env never leaks in.
    load_dotenv(os.getenv("PIQ_DOTENV", ROOT / ".env"))
    # GROQ_API_KEY_1/_2 are the earlier two-key names; they still join the pool.
    pool = key_pool("GROQ_API_KEYS", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY")
    gemini = key_pool("GEMINI_API_KEYS", "GEMINI_API_KEY")
    s = Settings(
        groq_api_key=pool[0] if pool else "",
        groq_api_keys=pool,
        model_large=os.getenv("GROQ_MODEL_LARGE", ""),
        model_small=os.getenv("GROQ_MODEL_SMALL", ""),
        db_path=Path(os.getenv("DB_PATH", str(DATA_DIR / "placementiq.db"))),
        max_critic_retries=int(os.getenv("MAX_CRITIC_RETRIES", "2")),
        mock_mode=_flag("MOCK_MODE", "true"),
        seed_demo=_flag("SEED_DEMO", "false"),
        # SUPABASE_DB_URL is a hosted PostgreSQL URL by another name; DATABASE_URL wins.
        database_url=(os.getenv("DATABASE_URL", "") or os.getenv("SUPABASE_DB_URL", "")).strip(),
        telemetry_db_path=Path(
            os.getenv("TELEMETRY_DB_PATH", str(DATA_DIR / "placement_nexus.db"))
        ),
        ai_providers=_providers(os.getenv("AI_PROVIDERS", ",".join(AI_PROVIDER_NAMES))),
        gemini_api_key=gemini[0] if gemini else "",
        gemini_api_keys=gemini,
        gemini_model=os.getenv("GEMINI_MODEL", "").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "").strip(),
        offline_fallback=_flag("AI_OFFLINE_FALLBACK", "true"),
        groq_timeout_s=_number("GROQ_TIMEOUT_S", GROQ_TIMEOUT_S),
        gemini_timeout_s=_number("GEMINI_TIMEOUT_S", GEMINI_TIMEOUT_S),
        ollama_num_ctx=_number("OLLAMA_NUM_CTX", OLLAMA_NUM_CTX),
        ollama_num_predict=_number("OLLAMA_NUM_PREDICT", OLLAMA_NUM_PREDICT),
        ai_cache=_flag("AI_CACHE", "true"),
        ai_cache_path=Path(os.getenv("AI_CACHE_PATH", str(DATA_DIR / ".ai_cache.json"))),
        audio_cache_dir=Path(os.getenv("AUDIO_CACHE_DIR", str(DATA_DIR / ".audio_cache"))),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
        elevenlabs_model=os.getenv("ELEVENLABS_MODEL", "").strip(),
        preload=_flag("PRELOAD", "true"),
        preload_cache_dir=Path(os.getenv("PRELOAD_CACHE_DIR", str(DATA_DIR / ".preload_cache"))),
        smtp_email=os.getenv("SMTP_EMAIL", "").strip(),
        # Google shows App Passwords in groups of four ("abcd efgh ijkl mnop"): spaces dropped.
        smtp_app_password="".join(os.getenv("SMTP_APP_PASSWORD", "").split()),
        smtp_host=os.getenv("SMTP_HOST", "").strip() or SMTP_HOST,
        smtp_port=_number("SMTP_PORT", SMTP_PORT),
        mail_outbox_path=Path(os.getenv("MAIL_OUTBOX_PATH", str(DATA_DIR / ".mail_outbox.log"))),
        auth_pepper=os.getenv("AUTH_PEPPER", ""),
        raise_page_errors=_flag("PIQ_RAISE_ERRORS", "false"),
    )
    if not s.mock_mode:
        # A provider with no key (or URL) is simply skipped by the router; one that is half set
        # up (a key without its model) is a mistake worth stopping for.
        half_set = {
            "GROQ_API_KEYS (or GROQ_API_KEY)": (
                s.groq_api_key,
                {"GROQ_MODEL_LARGE": s.model_large, "GROQ_MODEL_SMALL": s.model_small},
            ),
            "GEMINI_API_KEYS (or GEMINI_API_KEY)": (
                s.gemini_api_key,
                {"GEMINI_MODEL": s.gemini_model},
            ),
            "OLLAMA_BASE_URL": (s.ollama_base_url, {"OLLAMA_MODEL": s.ollama_model}),
        }
        for key, (value, needs) in half_set.items():
            missing = [name for name, v in needs.items() if not v]
            if value and missing:
                raise ConfigError(f"{key} is set but {', '.join(missing)} not set in .env")
    return s
