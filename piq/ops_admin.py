"""The developer console's service layer (routers/ops.py): curated data files, databases,
caches, the mail outbox, settings and account controls.

Data files (the question banks, the GitHub inspiration seed, the skill -> topic map and the
company organizations) are replaced through validated CSV uploads. Every upload is previewed
first (a dry run that writes nothing), and an import backs the old file up to data/.backups/
(the last BACKUP_KEEP per file), writes the new one atomically (a temporary file, then
os.replace) and clears the caches that read it, so the change is live at once.

Databases are inspected read-only: a table is only ever named from sqlite_master, and every
column that could hold a secret (password, hash, salt, token, key, code, ...) comes back as
[REDACTED] and is left out of searches. Settings are reported as configured or not; a secret's
value is never returned. Errors a developer can fix raise ServiceError (shown as is).
"""

import csv
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from core import ai_router, mailer
from core import github_search as gh
from core.preloader import get_preloader
from database import crud
from piq import db, open_questions, question_bank
from piq.checks import text_hash
from piq.config import DATA_DIR, DIFFICULTIES, ROOT, settings
from piq.services import ServiceError

CSV_MAX_BYTES = 10 * 1024 * 1024
BACKUP_DIR = DATA_DIR / ".backups"
BACKUP_KEEP = 5
ERRORS_SHOWN = 50
SAMPLE_SHOWN = 10
BROWSE_MAX = 200
REDACTED = "[REDACTED]"
SENSITIVE_PARTS = ("password", "hash", "salt", "secret", "token", "key", "code", "enc", "refresh")

MCQ_BANK = question_bank.BANK
MCQ_COLUMNS = (
    "stream", "domain", "role", "topic", "difficulty", "question", "option_a", "option_b",
    "option_c", "option_d", "correct_option", "explanation", "bloom_level",
)  # fmt: skip
MCQ_REQUIRED = (
    "topic", "difficulty", "question", "option_a", "option_b", "option_c", "option_d",
    "correct_option",
)  # fmt: skip
INTERVIEW_BANK = open_questions.OPEN_INTERVIEW
INTERVIEW_COLUMNS = (
    "category", "role", "interview_type", "difficulty", "question", "key_evaluation_points",
    "model_answer", "round", "topic", "source", "licence",
)  # fmt: skip
HR_TYPES = {"hr", "behavioural", "behavioral", "situational", "managerial", "personal"}
REPO_COLUMNS = ("topic", "kind", *gh.FIELDS)
REPO_KINDS = ("popular", "company", "hackathon")
TOPIC_COLUMNS = ("skill", "topic", "keyword")
ORG_COLUMNS = ("login", "name")
TEMPLATES = ROOT / "data" / "templates"

_GH_TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
_GH_FULL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_GH_LOGIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38})$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_write_lock = threading.Lock()  # one import at a time

Which = Literal["app", "telemetry"]
CacheTarget = Literal["ai", "preload", "github", "question_bank", "all"]
Maintenance = Literal["integrity_check", "checkpoint", "vacuum", "sync_now", "retry_set_aside"]


# --- shared CSV and file helpers ----------------------------------------------------------------


def _decode(raw: bytes) -> str:
    if len(raw) > CSV_MAX_BYTES:
        raise ServiceError(f"The file is larger than {CSV_MAX_BYTES // (1024 * 1024)} MB.")
    if not raw.strip():
        raise ServiceError("The file is empty.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ServiceError("Save the file as UTF-8 CSV and upload it again.") from None


def _read_csv(raw: bytes, required: Sequence[str]) -> list[tuple[int, dict[str, str]]]:
    """(line number, row with lower-case keys and stripped values); refuses a file without the
    required headers."""
    reader = csv.DictReader(io.StringIO(_decode(raw), newline=""))
    headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    missing = [h for h in required if h not in headers]
    if missing:
        raise ServiceError(f"The CSV is missing these columns: {', '.join(missing)}.")
    reader.fieldnames = headers
    rows = []
    try:
        for row in reader:
            clean = {k: (v or "").strip() for k, v in row.items() if k and isinstance(v, str)}
            if any(clean.values()):
                rows.append((reader.line_num, clean))
    except csv.Error as e:
        raise ServiceError(f"The CSV could not be read near line {reader.line_num}: {e}") from e
    if not rows:
        raise ServiceError("The CSV has a header but no rows.")
    return rows


def _csv_bytes(columns: Sequence[str], rows: Iterable[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow({k: "" if row.get(k) is None else row.get(k) for k in columns})
    return buf.getvalue().encode("utf-8")


def _summary(
    total: int,
    valid: list[dict],
    duplicates: int,
    errors: list[dict],
    warnings: list[str] | None = None,
    **extra: object,
) -> dict:
    return {
        "total_rows": total,
        "valid_count": len(valid),
        "duplicate_count": duplicates,
        "invalid_count": len(errors),
        "sample_valid": valid[:SAMPLE_SHOWN],
        "errors": errors[:ERRORS_SHOWN],
        "warnings": (warnings or [])[:ERRORS_SHOWN],
        **extra,
    }


def _backup(path: Path) -> str | None:
    """Copy `path` to data/.backups/ (keeping the newest BACKUP_KEEP per file); its name."""
    if not path.is_file():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}"
    target.write_bytes(path.read_bytes())
    old = sorted(BACKUP_DIR.glob(f"{path.stem}-*{path.suffix}"), key=lambda p: p.name)
    for extra in old[:-BACKUP_KEEP]:
        extra.unlink(missing_ok=True)
    return target.name


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _json_bytes(data: dict, indent: int) -> bytes:
    """The project's JSON style for curated files (UTF-8, a final newline)."""
    return (json.dumps(data, indent=indent, ensure_ascii=False) + "\n").encode("utf-8")


def _commit(path: Path, data: bytes, after: Callable[[], None]) -> str | None:
    """Back up, write atomically, then clear the caches that read `path`; the backup's name."""
    backup = _backup(path)
    _atomic_write(path, data)
    after()
    return backup


def _mode(mode: str, allowed: Sequence[str]) -> str:
    if mode not in allowed:
        raise ServiceError(f"Choose one of: {', '.join(allowed)}.")
    return mode


def _template(name: str, columns: Sequence[str], rows: Sequence[dict]) -> bytes:
    """The committed template from data/templates/ when there is one, else built here."""
    path = TEMPLATES / name
    return path.read_bytes() if path.is_file() else _csv_bytes(columns, rows)


# --- 1. multiple-choice bank (data/questions/mcq_bank.csv) --------------------------------------


def _mcq_row(row: dict[str, str]) -> dict[str, str]:
    out = {k: row.get(k, "") for k in MCQ_COLUMNS}
    out["difficulty"] = out["difficulty"].lower()
    out["correct_option"] = out["correct_option"].upper()
    out["bloom_level"] = out["bloom_level"].lower()
    return out


def _bank_hashes() -> set[str]:
    if not MCQ_BANK.is_file():
        return set()
    with MCQ_BANK.open(encoding="utf-8", newline="") as f:
        return {text_hash(r.get("question") or "") for r in csv.DictReader(f)}


def _check_mcq(raw: bytes, mode: str) -> tuple[list[dict], int, list[dict], list[str], int]:
    """(new valid rows, duplicates, errors, warnings, total)."""
    rows = _read_csv(raw, MCQ_REQUIRED)
    existing = _bank_hashes() if mode == "append" else set()
    mapped = question_bank.topic_map()
    seen: set[str] = set()
    valid: list[dict] = []
    errors: list[dict] = []
    unmapped: set[str] = set()
    duplicates = 0
    for line, raw_row in rows:
        row = _mcq_row(raw_row)
        why = None
        if not row["question"]:
            why = "the question is empty"
        elif not row["topic"]:
            why = "the topic is empty"
        elif row["difficulty"] not in DIFFICULTIES:
            why = f"difficulty must be one of {', '.join(DIFFICULTIES)}"
        else:
            why = question_bank.problems(row)
        if why:
            errors.append({"line": line, "error": why, "question": row["question"][:120]})
            continue
        h = text_hash(row["question"])
        if h in seen or h in existing:
            duplicates += 1
            continue
        seen.add(h)
        if row["topic"] not in mapped:
            unmapped.add(row["topic"])
        valid.append(row)
    warnings = [
        f"Topic '{t}' is not in data/bank_topics.json: its rows are stored but no syllabus topic "
        "serves them until it is mapped."
        for t in sorted(unmapped)
    ]
    return valid, duplicates, errors, warnings, len(rows)


def preview_mcq_csv(raw_bytes: bytes, mode: str = "append") -> dict:
    """Dry run of an MCQ upload: counts, the first valid rows and the errors. Writes nothing."""
    valid, dups, errors, warnings, total = _check_mcq(raw_bytes, _mode(mode, ("append", "replace")))
    return _summary(total, valid, dups, errors, warnings, mode=mode)


def import_mcq_csv(raw_bytes: bytes, mode: Literal["append", "replace"]) -> dict:
    """Append the new valid rows to the bank, or replace the bank with them."""
    _mode(mode, ("append", "replace"))
    with _write_lock:
        valid, dups, errors, warnings, total = _check_mcq(raw_bytes, mode)
        if not valid:
            raise ServiceError("No new valid questions to import (see the preview's errors).")
        if mode == "append" and MCQ_BANK.is_file():
            current = MCQ_BANK.read_bytes()
            header = current.decode("utf-8-sig").splitlines()[0] if current.strip() else ""
            columns = [h.strip() for h in next(csv.reader([header]))] if header else MCQ_COLUMNS
            body = _csv_bytes(columns, valid).split(b"\n", 1)[1]  # rows only, the file's order
            data = current + (b"" if current.endswith(b"\n") else b"\n") + body
        else:
            data = _csv_bytes(MCQ_COLUMNS, valid)
        backup = _commit(MCQ_BANK, data, question_bank.clear_cache)
    return {
        **_summary(total, valid, dups, errors, warnings, mode=mode),
        "imported": len(valid),
        "backup": backup,
        "bank_size": question_bank.size(),
        "file_rows": _count_csv_rows(MCQ_BANK),
    }


def _count_csv_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def mcq_bank_stats() -> dict:
    by_difficulty: dict[str, int] = {}
    topics: set[str] = set()
    streams: set[str] = set()
    if MCQ_BANK.is_file():
        with MCQ_BANK.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                d = (r.get("difficulty") or "").strip().lower()
                by_difficulty[d] = by_difficulty.get(d, 0) + 1
                topics.add((r.get("topic") or "").strip())
                streams.add((r.get("stream") or "").strip())
    return {
        "file": str(MCQ_BANK.relative_to(ROOT)),
        "rows": sum(by_difficulty.values()),
        "by_difficulty": by_difficulty,
        "topics": len(topics - {""}),
        "streams": len(streams - {""}),
        "served": question_bank.size(),
        "by_source": question_bank.counts_by_source(),
        "bytes": MCQ_BANK.stat().st_size if MCQ_BANK.is_file() else 0,
    }


def mcq_template_csv() -> bytes:
    return _template("mcq_template.csv", MCQ_COLUMNS, [])


def export_mcq_csv() -> bytes:
    if not MCQ_BANK.is_file():
        return _csv_bytes(MCQ_COLUMNS, [])
    return MCQ_BANK.read_bytes()


# --- 2. open interview questions (data/questions/open_interview.json) ---------------------------


def _interview_file() -> dict:
    if not INTERVIEW_BANK.is_file():
        return {
            "_comment": "Open questions with model answers for mock interviews.",
            "questions": [],
        }
    return json.loads(INTERVIEW_BANK.read_text(encoding="utf-8"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def _interview_round(row: dict[str, str]) -> str | None:
    explicit = row.get("round", "").lower()
    if explicit:
        return explicit if explicit in open_questions.INTERVIEW_ROUNDS else None
    kind = row.get("interview_type", "").lower()
    if kind == "technical":
        return "technical"
    return "hr" if kind in HR_TYPES else None


def _check_interview(raw: bytes, mode: str) -> tuple[list[dict], int, list[dict], int]:
    rows = _read_csv(raw, ("question", "model_answer"))
    registry = open_questions.sources()
    existing = (
        {text_hash(q["text"]) for q in _interview_file()["questions"]}
        if mode == "append"
        else set()
    )
    seen: set[str] = set()
    valid: list[dict] = []
    errors: list[dict] = []
    duplicates = 0
    for line, row in rows:
        text, answer = row.get("question", ""), row.get("model_answer", "")
        round_ = _interview_round(row)
        source = row.get("source", "").lower() or "own"
        difficulty = row.get("difficulty", "").lower()
        why = None
        if len(text) < 8:
            why = "the question is empty or too short"
        elif len(answer) < 20:
            why = "the model answer is empty or too short"
        elif round_ is None:
            why = "set round (hr / technical) or interview_type (Technical, HR, Behavioural, ...)"
        elif difficulty and difficulty not in DIFFICULTIES:
            why = f"difficulty must be one of {', '.join(DIFFICULTIES)} (or blank)"
        elif source not in registry:
            why = f"unknown source '{source}' (see data/questions/sources.json)"
        elif bad := open_questions.forbidden_in(" ".join([text, answer, source])):
            why = f"text from a site nothing may be taken from: {', '.join(bad)}"
        if why:
            errors.append({"line": line, "error": why, "question": text[:120]})
            continue
        h = text_hash(text)
        if h in seen or h in existing:
            duplicates += 1
            continue
        seen.add(h)
        points = row.get("key_evaluation_points", "")
        full_answer = f"{answer}\n\nKey points: {points}" if points else answer
        valid.append(
            {
                "id": f"{source}-{round_}-{h[:10]}",
                "round": round_,
                "subtopic": _slug(row.get("topic") or row.get("role") or row.get("category", ""))
                or "general",
                "text": text,
                "model_answer": full_answer,
                "source": source,
                "licence": row.get("licence") or registry[source].get("licence_id", "own"),
                "answer_source": "own",
            }
        )
    return valid, duplicates, errors, len(rows)


def preview_interview_csv(raw_bytes: bytes, mode: str = "append") -> dict:
    valid, dups, errors, total = _check_interview(raw_bytes, _mode(mode, ("append", "replace")))
    return _summary(total, valid, dups, errors, mode=mode)


def import_interview_csv(raw_bytes: bytes, mode: Literal["append", "replace"]) -> dict:
    _mode(mode, ("append", "replace"))
    with _write_lock:
        valid, dups, errors, total = _check_interview(raw_bytes, mode)
        if not valid:
            raise ServiceError("No new valid interview questions to import.")
        data = _interview_file()
        data["questions"] = ([*data["questions"]] if mode == "append" else []) + valid
        backup = _commit(INTERVIEW_BANK, _json_bytes(data, 2), question_bank.clear_cache)
    return {
        **_summary(total, valid, dups, errors, mode=mode),
        "imported": len(valid),
        "backup": backup,
        "bank_size": len(open_questions.interview_questions()),
    }


def interview_template_csv() -> bytes:
    return _template("interview_template.csv", INTERVIEW_COLUMNS, [])


def interview_bank_stats() -> dict:
    questions = open_questions.interview_questions()
    by_round: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for q in questions:
        by_round[q["round"]] = by_round.get(q["round"], 0) + 1
        by_source[q["source"]] = by_source.get(q["source"], 0) + 1
    return {
        "file": str(INTERVIEW_BANK.relative_to(ROOT)),
        "questions": len(questions),
        "by_round": by_round,
        "by_source": by_source,
        "bytes": INTERVIEW_BANK.stat().st_size if INTERVIEW_BANK.is_file() else 0,
    }


def question_stats() -> dict:
    return {
        "mcq": mcq_bank_stats(),
        "interview": interview_bank_stats(),
        "backups": backups(),
    }


def backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    files = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.name, reverse=True)
    return [{"name": p.name, "bytes": p.stat().st_size} for p in files if p.is_file()][:40]


# --- 3. GitHub inspiration seed (data/project_inspiration_seed.json) ----------------------------


def _flag(value: str) -> bool | None:
    v = value.strip().lower()
    if v in ("", "0", "false", "no", "n"):
        return False
    if v in ("1", "true", "yes", "y"):
        return True
    return None


def _repo_from_row(row: dict[str, str]) -> tuple[str, str, dict] | str:
    """(topic, kind, repo dict) or why the row cannot be one."""
    topic, kind = row.get("topic", "").lower(), row.get("kind", "").lower()
    full_name = row.get("full_name", "").strip().strip("/")
    if not _GH_TOPIC.match(topic):
        return "topic must be a GitHub topic (lower-case letters, digits and hyphens)"
    if kind not in REPO_KINDS:
        return f"kind must be one of {', '.join(REPO_KINDS)}"
    if not _GH_FULL_NAME.match(full_name):
        return "full_name must look like owner/repository"
    owner = row.get("owner") or full_name.split("/")[0]
    url = row.get("url") or f"https://github.com/{full_name}"
    if not url.startswith("https://github.com/"):
        return "url must start with https://github.com/"
    is_org = _flag(row.get("owner_is_org", ""))
    if is_org is None:
        return "owner_is_org must be true or false"
    stars_raw = row.get("stars", "").replace(",", "") or "0"
    if not stars_raw.isdigit():
        return "stars must be a whole number"
    pushed = row.get("pushed_at", "")[:10]
    if pushed and not _ISO_DATE.match(pushed):
        return "pushed_at must be YYYY-MM-DD (or blank)"
    topics = [t.strip().lower() for t in re.split(r"[|;]", row.get("topics", "")) if t.strip()]
    company = row.get("company", "")
    if not company and is_org:
        company = gh.company_orgs().get(owner.lower(), "")
    description = " ".join(row.get("description", "").split())
    if len(description) > gh.DESCRIPTION_MAX:
        description = description[: gh.DESCRIPTION_MAX - 1].rstrip() + "…"
    repo = {
        "full_name": full_name,
        "owner": owner,
        "owner_is_org": is_org,
        "company": company,
        "description": description,
        "stars": int(stars_raw),
        "language": row.get("language", ""),
        "topics": topics[: gh.TOPICS_MAX],
        "licence": row.get("licence", ""),
        "url": url,
        "pushed_at": pushed,
    }
    gh.Repo.from_dict(repo)  # exactly the whitelisted fields
    return topic, kind, repo


def _seed_file() -> dict:
    if not gh.SEED.is_file():
        return {"_comment": "Curated example repositories per topic.", "fetched": "", "topics": {}}
    return json.loads(gh.SEED.read_text(encoding="utf-8"))


def _seed_keys(seed: dict) -> set[tuple[str, str, str]]:
    return {
        (t, k, r["full_name"].lower())
        for t, kinds in seed.get("topics", {}).items()
        for k, repos in kinds.items()
        for r in repos
    }


def _check_repos(raw: bytes, mode: str) -> tuple[list[tuple[str, str, dict]], dict]:
    rows = _read_csv(raw, ("topic", "kind", "full_name"))
    existing = _seed_keys(_seed_file()) if mode == "merge" else set()
    seen: set[tuple[str, str, str]] = set()
    valid: list[tuple[str, str, dict]] = []
    errors: list[dict] = []
    warnings: list[str] = []
    duplicates = updated = 0
    for line, row in rows:
        found = _repo_from_row(row)
        if isinstance(found, str):
            errors.append({"line": line, "error": found, "question": row.get("full_name", "")})
            continue
        topic, kind, repo = found
        key = (topic, kind, repo["full_name"].lower())
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        updated += key in existing
        if kind in ("popular", "company") and not repo["licence"]:
            warnings.append(f"line {line}: {repo['full_name']} has no licence, so {kind} hides it")
        if kind == "company" and not repo["company"]:
            warnings.append(
                f"line {line}: {repo['full_name']} has no company (its owner is not in "
                "data/company_orgs.json), so the company list hides it"
            )
        valid.append(found)
    summary = _summary(
        len(rows),
        [{"topic": t, "kind": k, **r} for t, k, r in valid],
        duplicates,
        errors,
        warnings,
        mode=mode,
        updated_count=updated,
    )
    return valid, summary


def preview_github_repos_csv(raw_bytes: bytes, mode: str = "merge") -> dict:
    return _check_repos(raw_bytes, _mode(mode, ("merge", "replace")))[1]


def import_github_repos_csv(raw_bytes: bytes, mode: Literal["merge", "replace"]) -> dict:
    _mode(mode, ("merge", "replace"))
    with _write_lock:
        valid, summary = _check_repos(raw_bytes, mode)
        if not valid:
            raise ServiceError("No valid repositories to import.")
        seed = _seed_file()
        topics: dict[str, dict[str, list[dict]]] = seed.get("topics", {}) if mode == "merge" else {}
        for topic, kind, repo in valid:
            bucket = topics.setdefault(topic, {}).setdefault(kind, [])
            at = next(
                (
                    i
                    for i, r in enumerate(bucket)
                    if r["full_name"].lower() == repo["full_name"].lower()
                ),
                None,
            )
            if at is None:
                bucket.append(repo)
            else:
                bucket[at] = repo
        seed["topics"] = topics
        seed["fetched"] = date.today().isoformat()
        backup = _commit(gh.SEED, _json_bytes(seed, 1), gh.clear_cache)
    return {**summary, "imported": len(valid), "backup": backup, **github_repos_stats()}


def github_repos_template_csv() -> bytes:
    return _csv_bytes(
        REPO_COLUMNS,
        [
            {
                "topic": "react",
                "kind": "popular",
                "full_name": "facebook/docusaurus",
                "owner": "facebook",
                "owner_is_org": "true",
                "company": "Meta",
                "description": "Easy to maintain open source documentation websites.",
                "stars": "60000",
                "language": "TypeScript",
                "topics": "documentation|react|website",
                "licence": "MIT",
                "url": "https://github.com/facebook/docusaurus",
                "pushed_at": "2026-11-20",
            },
            {
                "topic": "machine-learning",
                "kind": "hackathon",
                "full_name": "example-team/crop-advisor",
                "owner": "",
                "owner_is_org": "false",
                "company": "",
                "description": "Hackathon project: crop recommendations from soil readings.",
                "stars": "42",
                "language": "Python",
                "topics": "hackathon;machine-learning;agriculture",
                "licence": "",
                "url": "",
                "pushed_at": "",
            },
        ],
    )


def export_github_repos_csv() -> bytes:
    rows = []
    for topic, kinds in _seed_file().get("topics", {}).items():
        for kind, repos in kinds.items():
            for r in repos:
                rows.append({"topic": topic, "kind": kind, **r, "topics": "|".join(r["topics"])})
    return _csv_bytes(REPO_COLUMNS, rows)


def github_repos_stats() -> dict:
    seed = _seed_file()
    by_kind: dict[str, int] = {}
    for kinds in seed.get("topics", {}).values():
        for kind, repos in kinds.items():
            by_kind[kind] = by_kind.get(kind, 0) + len(repos)
    return {
        "topics": len(seed.get("topics", {})),
        "repos": sum(by_kind.values()),
        "by_kind": by_kind,
        "fetched": seed.get("fetched", ""),
    }


# --- 4. skill -> GitHub topic (data/github_topics.json) -----------------------------------------


def _topics_file() -> dict:
    return json.loads(gh.TOPICS.read_text(encoding="utf-8"))


def _check_topics(raw: bytes, mode: str) -> tuple[dict[str, dict | None], dict]:
    rows = _read_csv(raw, ("skill", "topic"))
    existing = set(_topics_file()["skills"]) if mode == "merge" else set()
    valid: dict[str, dict | None] = {}
    errors: list[dict] = []
    duplicates = updated = 0
    for line, row in rows:
        skill = " ".join(row.get("skill", "").split())
        topic = row.get("topic", "").lower()
        if not skill or len(skill) > 80:
            errors.append(
                {"line": line, "error": "the skill is empty or too long", "question": skill}
            )
            continue
        if topic and not _GH_TOPIC.match(topic):
            errors.append(
                {"line": line, "error": "topic must be a GitHub topic or blank", "question": skill}
            )
            continue
        if skill in valid:
            duplicates += 1
            continue
        updated += skill in existing
        keyword = " ".join(row.get("keyword", "").split()) or skill.lower()
        valid[skill] = {"topic": topic, "keyword": keyword[:80]} if topic else None
    sample = [{"skill": k, **(v or {"topic": None, "keyword": None})} for k, v in valid.items()]
    summary = _summary(len(rows), sample, duplicates, errors, mode=mode, updated_count=updated)
    return valid, summary


def preview_github_topics_csv(raw_bytes: bytes, mode: str = "merge") -> dict:
    return _check_topics(raw_bytes, _mode(mode, ("merge", "replace")))[1]


def import_github_topics_csv(raw_bytes: bytes, mode: Literal["merge", "replace"]) -> dict:
    _mode(mode, ("merge", "replace"))
    with _write_lock:
        valid, summary = _check_topics(raw_bytes, mode)
        if not valid:
            raise ServiceError("No valid skill mappings to import.")
        data = _topics_file()
        skills = {**data["skills"], **valid} if mode == "merge" else dict(valid)
        data["skills"] = skills  # existing order kept; new skills at the end
        backup = _commit(gh.TOPICS, _json_bytes(data, 2), gh.clear_cache)
    return {**summary, "imported": len(valid), "backup": backup, "skills": len(data["skills"])}


def github_topics_template_csv() -> bytes:
    return _csv_bytes(
        TOPIC_COLUMNS,
        [
            {"skill": "React", "topic": "react", "keyword": "react app"},
            {"skill": "Docker", "topic": "docker", "keyword": "docker"},
            {"skill": "Quantitative Aptitude", "topic": "", "keyword": ""},
        ],
    )


def export_github_topics_csv() -> bytes:
    rows = [
        {"skill": k, "topic": (v or {}).get("topic", ""), "keyword": (v or {}).get("keyword", "")}
        for k, v in _topics_file()["skills"].items()
    ]
    return _csv_bytes(TOPIC_COLUMNS, rows)


# --- 5. company GitHub organizations (data/company_orgs.json) -----------------------------------


def _orgs_file() -> dict:
    return json.loads(gh.COMPANY_ORGS.read_text(encoding="utf-8"))


def _check_orgs(raw: bytes, mode: str) -> tuple[dict[str, str], dict]:
    rows = _read_csv(raw, ORG_COLUMNS)
    existing = set(_orgs_file()["orgs"]) if mode == "merge" else set()
    valid: dict[str, str] = {}
    errors: list[dict] = []
    duplicates = updated = 0
    for line, row in rows:
        login, name = row.get("login", "").lower(), " ".join(row.get("name", "").split())
        if not _GH_LOGIN.match(login):
            errors.append(
                {"line": line, "error": "login must be a GitHub login", "question": login}
            )
            continue
        if not name or len(name) > 80:
            errors.append(
                {"line": line, "error": "the name is empty or too long", "question": login}
            )
            continue
        if login in valid:
            duplicates += 1
            continue
        updated += login in existing
        valid[login] = name
    sample = [{"login": k, "name": v} for k, v in valid.items()]
    return valid, _summary(len(rows), sample, duplicates, errors, mode=mode, updated_count=updated)


def preview_company_orgs_csv(raw_bytes: bytes, mode: str = "merge") -> dict:
    return _check_orgs(raw_bytes, _mode(mode, ("merge", "replace")))[1]


def import_company_orgs_csv(raw_bytes: bytes, mode: Literal["merge", "replace"]) -> dict:
    _mode(mode, ("merge", "replace"))
    with _write_lock:
        valid, summary = _check_orgs(raw_bytes, mode)
        if not valid:
            raise ServiceError("No valid organizations to import.")
        data = _orgs_file()
        data["orgs"] = {**data["orgs"], **valid} if mode == "merge" else dict(valid)
        backup = _commit(gh.COMPANY_ORGS, _json_bytes(data, 2), gh.clear_cache)
    return {**summary, "imported": len(valid), "backup": backup, "orgs": len(data["orgs"])}


def company_orgs_template_csv() -> bytes:
    return _csv_bytes(
        ORG_COLUMNS,
        [{"login": "google", "name": "Google"}, {"login": "microsoft", "name": "Microsoft"}],
    )


def export_company_orgs_csv() -> bytes:
    return _csv_bytes(
        ORG_COLUMNS, [{"login": k, "name": v} for k, v in _orgs_file()["orgs"].items()]
    )


def github_stats() -> dict:
    return {
        "repos": github_repos_stats(),
        "skills": len(_topics_file()["skills"]),
        "skills_without_topic": sum(1 for v in _topics_file()["skills"].values() if v is None),
        "orgs": len(_orgs_file()["orgs"]),
        "cache_rows": db.github_cache_count(),
        "token": bool(settings().github_token),
    }


# --- 6. databases -------------------------------------------------------------------------------


def _db_path(which: str) -> Path:
    s = settings()
    if which == "app":
        return s.db_path
    if which == "telemetry":
        return s.telemetry_db_path
    raise ServiceError("Choose the app or the telemetry database.")


def _connect(path: Path, readonly: bool = True) -> sqlite3.Connection:
    if not path.is_file():
        raise ServiceError(f"The database file does not exist yet: {path.name}")
    if readonly:
        try:
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            return conn
        except sqlite3.Error:
            pass  # e.g. a WAL file whose -shm cannot be opened read-only: a normal connection
    return sqlite3.connect(path, timeout=5)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def _sync() -> dict:
    try:
        s = crud.sync_status()
    except Exception as e:  # telemetry unavailable: say so instead of failing the page
        return {"error": type(e).__name__}
    return {
        "cloud_configured": s.cloud_configured,
        "state": s.state,
        "pending": s.pending,
        "set_aside": s.set_aside,
        "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
        "retry_in_s": round(s.retry_in_s, 1),
        "last_error": s.last_error,
    }


def _database_info(which: str) -> dict:
    path = _db_path(which)
    info: dict = {
        "which": which,
        "path": str(path),
        "exists": path.is_file(),
        "bytes": _size(path),
        "wal_bytes": _size(Path(f"{path}-wal")),
        "sqlite_version": sqlite3.sqlite_version,
    }
    if not path.is_file():
        return info
    try:
        conn = _connect(path)
        try:
            info["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            info["integrity"] = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
            info["tables"] = [
                {"name": t, "rows": conn.execute(f"SELECT COUNT(*) FROM {_quote(t)}").fetchone()[0]}
                for t in _tables(conn)
            ]
        finally:
            conn.close()
    except sqlite3.Error as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def db_overview() -> dict:
    return {
        "app": _database_info("app"),
        "telemetry": _database_info("telemetry"),
        "sync": _sync(),
    }


def sensitive(column: str) -> bool:
    low = column.lower()
    return any(part in low for part in SENSITIVE_PARTS)


def _cell(value: object) -> object:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def browse_table(
    which: Which, table: str, limit: int = 50, offset: int = 0, search: str = ""
) -> dict:
    """One page of a table, newest rows first; sensitive columns redacted and never searched."""
    limit = max(1, min(int(limit), BROWSE_MAX))
    offset = max(0, int(offset))
    conn = _connect(_db_path(which))
    try:
        if table not in _tables(conn):
            raise ServiceError("No such table.")
        q = _quote(table)
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({q})").fetchall()]
        hidden = [c for c in columns if sensitive(c)]
        where, params = "", []
        needle = search.strip()
        searchable = [c for c in columns if c not in hidden]
        if needle and searchable:
            esc = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where = " WHERE " + " OR ".join(
                f"CAST({_quote(c)} AS TEXT) LIKE ? ESCAPE '\\'" for c in searchable
            )
            params = [f"%{esc}%"] * len(searchable)
        total = conn.execute(f"SELECT COUNT(*) FROM {q}{where}", params).fetchone()[0]
        try:
            cur = conn.execute(
                f"SELECT * FROM {q}{where} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
        except sqlite3.OperationalError:  # a WITHOUT ROWID table
            cur = conn.execute(
                f"SELECT * FROM {q}{where} LIMIT ? OFFSET ?", [*params, limit, offset]
            )
        names = [d[0] for d in cur.description]
        rows = [
            {
                n: (REDACTED if n in hidden and v is not None else _cell(v))
                for n, v in zip(names, r, strict=True)
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()
    return {
        "which": which,
        "table": table,
        "columns": columns,
        "redacted": hidden,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _each_db(work: Callable[[sqlite3.Connection], object], readonly: bool) -> dict:
    out = {}
    for which in ("app", "telemetry"):
        path = _db_path(which)
        if not path.is_file():
            out[which] = {"ok": False, "detail": "no database file yet"}
            continue
        try:
            conn = _connect(path, readonly=readonly)
            try:
                out[which] = {"ok": True, "detail": work(conn)}
            finally:
                conn.close()
        except sqlite3.Error as e:
            out[which] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    return out


def db_maintenance(action: Maintenance) -> dict:
    if action == "integrity_check":
        result = _each_db(
            lambda c: [r[0] for r in c.execute("PRAGMA integrity_check(20)").fetchall()], True
        )
    elif action == "checkpoint":

        def checkpoint(c: sqlite3.Connection) -> dict:
            busy, log_frames, done = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            return {"busy": busy, "wal_frames": log_frames, "checkpointed": done}

        result = _each_db(checkpoint, False)
    elif action == "vacuum":

        def vacuum(c: sqlite3.Connection) -> str:
            c.isolation_level = None  # VACUUM cannot run inside a transaction
            c.execute("VACUUM")
            return "vacuumed"

        result = _each_db(vacuum, False)
    elif action == "sync_now":
        s = crud.sync_now()
        result = {
            "cloud": {
                "ok": s.cloud_configured,
                "detail": f"state: {s.state}, pending: {s.pending}"
                if s.cloud_configured
                else "no cloud database configured (DATABASE_URL / SUPABASE_DB_URL)",
            }
        }
    elif action == "retry_set_aside":
        count = crud.retry_set_aside()
        result = {"cloud": {"ok": True, "detail": f"{count} set-aside record(s) queued again"}}
    else:
        raise ServiceError("Unknown maintenance action.")
    return {"action": action, "result": result, "overview": db_overview()}


def db_backup_bytes(which: Which) -> bytes:
    """A consistent copy of the database (sqlite3's online backup), as bytes."""
    src = _connect(_db_path(which), readonly=True)
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="ops-backup-")
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        return Path(tmp).read_bytes()
    finally:
        src.close()
        Path(tmp).unlink(missing_ok=True)


# --- 7. settings and caches ---------------------------------------------------------------------

CONFIGURED, NOT_SET = "Configured (masked)", "Not set"


def _secret(name: str, category: str, value: object) -> dict:
    return {
        "name": name,
        "category": category,
        "configured": bool(value),
        "secret": True,
        "display_value": CONFIGURED if value else NOT_SET,
    }


def _plain(name: str, category: str, value: object, default_note: str = "") -> dict:
    text = (
        ""
        if value is None
        else ("true" if value is True else "false" if value is False else str(value))
    )
    return {
        "name": name,
        "category": category,
        "configured": bool(text),
        "secret": False,
        "display_value": text or (default_note or NOT_SET),
    }


def _mask_email(address: str) -> str:
    if "@" not in address:
        return CONFIGURED if address else ""
    local, _, domain = address.partition("@")
    return f"{local[:2]}***@{domain}"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _cache_metrics(ops_sessions: int = 0) -> dict:
    s = settings()
    preload_entries, preload_bytes = get_preloader().stored_files()
    try:
        ai_entries = len(ai_router.prompt_cache())
    except Exception:  # an unreadable cache file counts as empty
        ai_entries = 0
    return {
        "ai": {"entries": ai_entries, "bytes": _size(s.ai_cache_path), "enabled": s.ai_cache},
        "preload": {"entries": preload_entries, "bytes": preload_bytes, "enabled": s.preload},
        "github": {"entries": db.github_cache_count()},
        "question_bank": {"entries": question_bank.size()},
        "sessions": {"live": db.live_session_count(time.time()), "ops": ops_sessions},
    }


def developer_settings_summary(ops_sessions: int = 0) -> dict:
    """Every setting as configured / not, secrets masked; key pool sizes; cache metrics."""
    s = settings()
    core_c, ai_c, db_c, mail_c, gh_c = (
        "Core & Security", "AI Providers & Caching", "Databases", "Email & Drive", "GitHub",
    )  # fmt: skip
    rows = [
        _plain("APP_URL", core_c, s.app_url),
        _secret("AUTH_PEPPER", core_c, s.auth_pepper),
        _secret("DEV_SECRET", core_c, s.dev_secret),
        _plain("FRONTEND_ORIGINS", core_c, _env("FRONTEND_ORIGINS"), "same origin only"),
        _plain("COOKIE_SECURE", core_c, _env("COOKIE_SECURE"), "auto (follows HTTPS)"),
        _plain("LOG_LEVEL", core_c, _env("LOG_LEVEL"), "INFO (default)"),
        _plain("PORT", core_c, _env("PORT"), "8000 (default)"),
        _plain("LOCAL_MODE", core_c, s.local_mode),
        _plain("LOCAL_AI", core_c, s.local_ai),
        _plain("MOCK_MODE", ai_c, s.mock_mode),
        _plain("AI_PROVIDERS", ai_c, ",".join(s.ai_providers)),
        _secret("GROQ_API_KEYS", ai_c, s.groq_api_keys),
        _plain("Groq key pool size", ai_c, len(s.groq_api_keys)),
        _plain("MODEL_LARGE (GROQ_MODEL_LARGE)", ai_c, s.model_large),
        _plain("MODEL_SMALL (GROQ_MODEL_SMALL)", ai_c, s.model_small),
        _secret("GEMINI_API_KEYS", ai_c, s.gemini_api_keys),
        _plain("Gemini key pool size", ai_c, len(s.gemini_api_keys)),
        _plain("GEMINI_MODEL", ai_c, s.gemini_model),
        _secret("ELEVENLABS_API_KEY", ai_c, s.elevenlabs_api_key),
        _plain("OLLAMA_BASE_URL", ai_c, s.ollama_base_url),
        _plain("OLLAMA_MODEL", ai_c, s.ollama_model),
        _plain("PRELOAD", ai_c, s.preload),
        _plain("AI_CACHE", ai_c, s.ai_cache),
        _plain("AI_CACHE_PATH", ai_c, s.ai_cache_path),
        _plain("PRELOAD_CACHE_DIR", ai_c, s.preload_cache_dir),
        _plain("DB_PATH", db_c, s.db_path),
        _plain("TELEMETRY_DB_PATH", db_c, s.telemetry_db_path),
        _secret("DATABASE_URL / SUPABASE_DB_URL", db_c, s.database_url),
        _plain("SMTP_EMAIL", mail_c, _mask_email(s.smtp_email)),
        _secret("SMTP_APP_PASSWORD", mail_c, s.smtp_app_password),
        _plain("SMTP_HOST", mail_c, s.smtp_host),
        _plain("SMTP_PORT", mail_c, s.smtp_port),
        _plain("MAIL_OUTBOX_PATH", mail_c, s.mail_outbox_path),
        _plain("GOOGLE_CLIENT_ID", mail_c, CONFIGURED if s.google_client_id else ""),
        _secret("GOOGLE_CLIENT_SECRET", mail_c, s.google_client_secret),
        _secret("DRIVE_TOKEN_KEY", mail_c, s.drive_token_key),
        _plain("GOOGLE_REDIRECT_URI", mail_c, s.google_redirect_uri),
        _plain("Google Drive", mail_c, "enabled" if s.drive_enabled else "off"),
        _secret("GITHUB_TOKEN", gh_c, s.github_token),
        _plain("GITHUB_API_URL", gh_c, s.github_api_url),
    ]
    return {
        "settings": rows,
        "key_pools": {"groq": len(s.groq_api_keys), "gemini": len(s.gemini_api_keys)},
        "providers": [
            {"name": p.name, "label": p.label, "state": p.state, "keys": p.keys}
            for p in ai_router.status()
        ],
        "caches": _cache_metrics(ops_sessions),
        "mail": "SMTP" if mailer.configured() else "local outbox file",
    }


def clear_cache(target: CacheTarget) -> dict:
    """Clear one cache (or all); before and after counts."""
    if target not in ("ai", "preload", "github", "question_bank", "all"):
        raise ServiceError("Unknown cache.")
    before = _cache_metrics()
    cleared: dict[str, int] = {}
    if target in ("ai", "all"):
        cleared["ai"] = ai_router.prompt_cache().clear()
    if target in ("preload", "all"):
        cleared["preload"] = get_preloader().clear()
    if target in ("github", "all"):
        cleared["github"] = db.github_cache_clear()
        gh.clear_cache()
    if target in ("question_bank", "all"):
        question_bank.clear_cache()
        cleared["question_bank"] = before["question_bank"]["entries"]
    return {"target": target, "cleared": cleared, "before": before, "after": _cache_metrics()}


# --- 8. mail outbox -----------------------------------------------------------------------------


def read_mail_outbox(tail_lines: int = 200) -> dict:
    path = settings().mail_outbox_path
    tail_lines = max(1, min(int(tail_lines), 5000))
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "lines": 0, "text": ""}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "path": str(path),
        "exists": True,
        "bytes": _size(path),
        "lines": len(lines),
        "text": "\n".join(lines[-tail_lines:]),
        "smtp": mailer.configured(),
    }


def clear_mail_outbox() -> dict:
    path = settings().mail_outbox_path
    size = _size(path)
    if path.is_file():
        path.write_text("", encoding="utf-8")
    return {"cleared_bytes": size}


def test_smtp_connection() -> dict:
    ok, detail = mailer.check_connection()
    return {"ok": ok, "configured": mailer.configured(), "detail": detail}


# --- 9. organizations and accounts --------------------------------------------------------------


def list_organizations_ops() -> list[dict]:
    return [
        {
            "id": r["id"],
            "org_code": r["org_code"],
            "name": r["name"],
            "type": r["org_type"],
            "admin_name": r["admin_name"],
            "admin_email": r["admin_email"],
            "verified": bool(r["admin_verified"]),
            "students": r["students"],
            "proctoring": r["proctoring"],
            "created_at": r["created_at"],
        }
        for r in db.ops_organizations()
    ]


def _account(username: str) -> str:
    row = db.student_by_username(username.strip())
    if row is None:
        raise ServiceError("No account with that username.")
    return row["id"]


def unlock_student(username: str) -> dict:
    sid = _account(username)
    had_password = db.unlock_account(sid)
    return {"username": username.lower(), "unlocked": had_password}


def revoke_student_sessions(username: str) -> dict:
    sid = _account(username)
    return {"username": username.lower(), "revoked": db.delete_sessions(sid)}


def set_student_status_ops(username: str, status: Literal["active", "suspended"]) -> dict:
    if status not in ("active", "suspended"):
        raise ServiceError("Status must be active or suspended.")
    sid = _account(username)
    db.set_account_status(sid, status)
    revoked = db.delete_sessions(sid) if status == "suspended" else 0
    return {"username": username.lower(), "status": status, "revoked": revoked}
