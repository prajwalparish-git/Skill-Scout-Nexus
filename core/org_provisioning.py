"""Bulk provisioning of an organization's students: a CSV in, accounts and welcome emails out.

Four steps, each a function the portal (piq/orgs.py) and the tests call on its own:

1. parse_csv: read the file leniently (Excel's encodings and delimiters, header aliases such as
   `stream` for main_domain), clean every cell against CSV/formula injection, and check each row:
   email format, duplicates inside the file, missing fields.
2. map_domain: place a row in the platform. The CSV's main domain and subdomain ("Commerce" /
   "Taxation & Audit") become a catalog stream and domain, the degree that stream's students
   study for, and, when the CSV gives no target role, the catalog role that fits the subdomain
   best (Tax Consultant). Roles are matched by words in the catalog's own text; nothing here
   calls an LLM.
3. check_database: rows whose email already has an account (in any organization) are Duplicates.
4. provision: for every Ready row make a readable 12-character temporary password and a 9-digit
   code (`secrets`), hash the password with core/auth.py (PBKDF2-HMAC-SHA256, 600,000 rounds, on
   a thread pool: the hashing is C code that releases the GIL), store all the accounts in ONE
   transaction (piq/db.py create_org_students), give each a starting profile holding its role's
   benchmark skills so the dashboard, plan and quiz are ready at the first sign-in, mirror them
   into telemetry, and queue the welcome emails (core/mailer.py; always also to the outbox log).

Passwords and codes exist in plain text only here, in the emails and in the one-time credentials
CSV handed to the admin; the database keeps hashes. Nothing here logs one.
"""

import csv
import difflib
import io
import logging
import re
import secrets
import sqlite3
import time
import uuid
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache

from core import auth, mailer
from piq import db, degrees, journey, services, syllabus
from piq.config import (
    BATCH_RE,
    CSV_MAX_BYTES,
    CSV_MAX_ROWS,
    DATA_DIR,
    EMAIL_MAX,
    EMAIL_RE,
    ORG_WELCOME_CODE_TTL_S,
    TEMP_PASSWORD_LEN,
    settings,
)
from piq.schemas import Organization
from piq.services import ServiceError

log = logging.getLogger("core.org_provisioning")

TEMPLATE = DATA_DIR / "templates" / "org_students_template.csv"
COLUMNS = ("name", "email", "main_domain", "subdomain", "target_role", "phone", "batch_year")
REQUIRED = ("name", "email", "main_domain", "subdomain")
# Header aliases (after lower-casing and turning spaces and hyphens into "_").
ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "full_name", "fullname", "student_name", "student"),
    "email": ("email", "student_email", "email_address", "email_id", "e_mail", "mail"),
    "main_domain": ("main_domain", "maindomain", "domain", "stream", "faculty", "school"),
    "subdomain": (
        "subdomain",
        "sub_domain",
        "department",
        "branch",
        "specialization",
        "specialisation",
        "discipline",
    ),
    "target_role": ("target_role", "role", "job_role", "career_role", "target"),
    "phone": ("phone", "mobile", "phone_number", "mobile_number", "contact", "contact_number"),
    "batch_year": ("batch_year", "batch", "year", "graduation_year", "passing_year"),
}
READY, DUPLICATE, INVALID_EMAIL = "Ready", "Duplicate", "Invalid Email"
MISSING, UNKNOWN_DOMAIN, UNKNOWN_ROLE = "Missing Field", "Unknown Domain", "Unknown Role"
# Other names for the catalog's streams, matched after dropping punctuation and case.
STREAM_ALIASES = {
    "Engineering": ("engineering", "engg", "eng", "technology", "btech", "be", "mtech", "me"),
    "Commerce": ("commerce", "bcom", "mcom", "accounts", "accountancy"),
    "Law": ("law", "legal", "llb", "llm", "ballb"),
    "Management": ("management", "mgmt", "mba", "bba", "business", "businessadministration"),
    "Healthcare": ("healthcare", "health", "medicine", "medical", "pharmacy"),
    "Government": ("government", "govt", "publicsector", "civilservices"),
}
_STOPWORDS = frozenset(
    {
        "and",
        "of",
        "the",
        "in",
        "for",
        "to",
        "with",
        "a",
        "an",
        "on",
        "at",
        "engineering",
        "engineer",
    }
)
# What an abbreviation or a loose word stands for in the catalog's own wording, so "ML" meets
# "Machine Learning" and "operations" meets "supply chain".
EXPANSIONS = {
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "cse": "computer science",
    "ise": "information science",
    "ece": "electronics communication",
    "eee": "electrical electronics",
    "it": "information technology",
    "hr": "human resources",
    "ops": "operations",
    "operations": "supply chain logistics",
    "finance": "financial",
}
# Words that name a domain without telling its roles apart (the whole of "Information Science"
# means the computing domain). They help choose the domain and are ignored when choosing a role.
DOMAIN_WORDS = {
    "cs": "computer computing software information informatics it cse ise science",
    "ece": "electronics electronic communication ece telecom",
    "mech": "mechanical mechanics automobile automotive",
    "civil": "civil construction structural",
    "eee": "electrical electronics eee power",
    "biotech": "biotechnology biomedical biology",
}
_FORMULA_START = "=+-@\t\r"


# --- reading the file ---------------------------------------------------------------------------


def sanitize(value: object) -> str:
    """One cell as plain text: control characters and surrounding spaces gone, and no leading
    `=`, `+`, `-` or `@` (a spreadsheet would run such a cell as a formula)."""
    text = "".join(ch for ch in str(value or "") if ch == " " or ch.isprintable())
    text = " ".join(text.split())
    return text.lstrip(_FORMULA_START + " ")


def normalise_header(header: str) -> str:
    key = re.sub(r"[\s\-./]+", "_", (header or "").strip().lower().lstrip("﻿"))
    return key.strip("_")


def header_map(headers: Iterable[str]) -> dict[str, str]:
    """canonical column -> the file's own header, for every column found (first one wins)."""
    seen = {normalise_header(h): h for h in headers if h}
    found: dict[str, str] = {}
    for column, names in ALIASES.items():
        for name in names:
            if name in seen:
                found[column] = seen[name]
                break
    return found


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):  # Excel saves CSV as cp1252 on Windows
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


@dataclass(frozen=True)
class ParsedRow:
    """One student line, cleaned, mapped and checked. `status` is READY or what is wrong."""

    line: int  # the line in the file (the header is line 1)
    name: str
    email: str
    main_domain: str  # as the file wrote it
    subdomain: str
    target_role: str  # the file's role resolved to the catalog, or the auto-mapped one
    phone: str
    batch_year: str
    stream: str = ""  # the catalog stream (Engineering, Commerce, ...)
    domain_id: str = ""
    degree: str = ""
    role_source: str = ""  # "file" or "auto"
    status: str = READY
    note: str = ""

    @property
    def ready(self) -> bool:
        return self.status == READY


def build_row(
    line: int,
    name: object,
    email: object,
    main_domain: object,
    subdomain: object,
    target_role: object = "",
    phone: object = "",
    batch_year: object = "",
) -> ParsedRow:
    """Clean and check one student (a CSV line, or the portal's quick-add form).

    Data minimisation: a phone number is never stored. The `phone` column is still read, so
    older files import, and the preview says the number was left out."""
    name, email = sanitize(name), sanitize(email).lower()
    main_domain, subdomain = sanitize(main_domain), sanitize(subdomain)
    role, batch = sanitize(target_role), sanitize(batch_year)
    notes: list[str] = []
    if str(phone or "").strip():
        notes.append("phone not stored (not needed)")
    if batch and not BATCH_RE.match(batch):
        notes.append("batch year ignored")
        batch = ""
    row = ParsedRow(line, name[:120], email, main_domain, subdomain, role, "", batch)

    missing = [
        label
        for label, value in (
            ("name", name),
            ("email", email),
            ("main_domain", main_domain),
            ("subdomain", subdomain),
        )
        if not value
    ]
    if missing:
        return replace(row, status=MISSING, note="missing " + ", ".join(missing))
    if len(email) > EMAIL_MAX or not EMAIL_RE.match(email):
        return replace(row, status=INVALID_EMAIL, note="not an email address")
    mapped = map_domain(main_domain, subdomain, role)
    if isinstance(mapped, str):  # an explanation of what could not be placed
        status = UNKNOWN_ROLE if mapped.startswith("role") else UNKNOWN_DOMAIN
        return replace(row, status=status, note=mapped)
    notes.extend([mapped.note] if mapped.note else [])
    return replace(
        row,
        target_role=mapped.role,
        stream=mapped.stream,
        domain_id=mapped.domain_id,
        degree=mapped.degree,
        role_source="file" if role else "auto",
        note="; ".join(notes),
    )


@dataclass(frozen=True)
class ParseResult:
    rows: tuple[ParsedRow, ...]
    columns: tuple[str, ...]  # the canonical columns the file had

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.rows)


def parse_csv(data: bytes) -> ParseResult:
    """Read the file into checked rows. Raises ServiceError for a file that is too big, empty,
    or lacking a required column. Duplicates inside the file are marked here; duplicates of
    existing accounts by check_database."""
    if len(data) > CSV_MAX_BYTES:
        raise ServiceError(f"That file is over {CSV_MAX_BYTES // 1_000_000} MB. Split it up.")
    text = _decode(data)
    if not text.strip():
        raise ServiceError("That file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = next(reader)
    except StopIteration:
        raise ServiceError("That file is empty.") from None
    columns = header_map(headers)
    absent = [c for c in REQUIRED if c not in columns]
    if absent:
        raise ServiceError(
            "The file needs these columns: "
            + ", ".join(REQUIRED)
            + f" (missing: {', '.join(absent)}). Download the template to see the layout."
        )
    index = {c: headers.index(h) for c, h in columns.items()}
    rows: list[ParsedRow] = []
    first_seen: dict[str, int] = {}
    for line, record in enumerate(reader, start=2):
        if not any(cell.strip() for cell in record):
            continue
        if len(rows) >= CSV_MAX_ROWS:
            raise ServiceError(f"A file holds up to {CSV_MAX_ROWS} students; split it up.")

        def cell(column: str, record: list[str] = record) -> str:
            i = index.get(column)
            return record[i] if i is not None and i < len(record) else ""

        row = build_row(line, *(cell(c) for c in COLUMNS))
        if row.status != INVALID_EMAIL and row.email in first_seen:
            note = f"same email as line {first_seen[row.email]}"
            row = replace(row, status=DUPLICATE, note=note)
        elif row.ready:
            first_seen[row.email] = line
        rows.append(row)
    if not rows:
        raise ServiceError("The file has a header but no students.")
    return ParseResult(tuple(rows), tuple(columns))


def check_database(rows: Sequence[ParsedRow]) -> tuple[ParsedRow, ...]:
    """Mark Ready rows whose email already has an account (anywhere) as Duplicates."""
    taken = db.emails_in_use(r.email for r in rows if r.ready)
    return tuple(
        replace(r, status=DUPLICATE, note="already has an account")
        if r.ready and r.email in taken
        else r
        for r in rows
    )


def template_csv() -> bytes:
    """The downloadable sample file (data/templates/org_students_template.csv)."""
    try:
        return TEMPLATE.read_bytes()
    except OSError:
        sample = ",".join(COLUMNS) + "\n"
        return sample.encode("utf-8")


# --- placing a student in the platform ----------------------------------------------------------


@dataclass(frozen=True)
class Mapped:
    stream: str
    domain_id: str
    degree: str
    role: str
    note: str = ""


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _words(text: str) -> set[str]:
    raw = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]
    expanded = raw + [x for w in raw for x in EXPANSIONS.get(w, "").split()]
    return set(expanded) - _STOPWORDS


def _overlap(a: set[str], b: set[str]) -> int:
    """How many words of `a` appear in `b`, counting a shared stem (tax / taxation, finance /
    financial) as a match."""

    def same(x: str, y: str) -> bool:
        if x == y:
            return True
        n = min(len(x), len(y))
        return n >= 3 and (x.startswith(y) or y.startswith(x) or (n >= 5 and x[:5] == y[:5]))

    return sum(any(same(x, y) for y in b) for x in a)


@lru_cache(maxsize=1)
def streams() -> tuple[str, ...]:
    return tuple(dict.fromkeys(syllabus.stream_of(d.id) for d in syllabus.domains()))


def resolve_stream(main_domain: str) -> str | None:
    """The catalog stream a main domain names ("Commerce", "B.Com", "engg", "MBA"), or None."""
    key = _key(main_domain)
    table = {_key(alias): s for s, names in STREAM_ALIASES.items() for alias in names}
    table |= {_key(s): s for s in streams()}
    if key in table:
        return table[key]
    close = difflib.get_close_matches(key, list(table), n=1, cutoff=0.8)
    return table[close[0]] if close else None


@lru_cache(maxsize=1)
def _catalog_domains() -> dict[str, dict]:
    return {d["id"]: d for d in syllabus.catalog()["domains"]}


def _generic(domain: dict) -> set[str]:
    """The words that name this domain: its catalog name and DOMAIN_WORDS."""
    return _words(domain["name"]) | set(DOMAIN_WORDS.get(domain["id"], "").split())


def _score_domain(sub: set[str], domain: dict) -> int:
    roles = [_words(r["name"]) for r in domain.get("roles", [])]
    return (
        3 * _overlap(sub, _generic(domain))
        + 2 * max((_overlap(sub, r) for r in roles), default=0)
        + _overlap(sub, _words(domain.get("description", "")))
    )


def _score_role(sub: set[str], role: dict) -> int:
    keywords = _words(" ".join(role.get("ats_keywords", [])))
    return (
        3 * _overlap(sub, _words(role["name"]))
        + 2 * _overlap(sub, _words(role.get("category", "")))
        + _overlap(sub, _words(role.get("description", "")))
        + _overlap(sub, keywords)
    )


def map_domain(main_domain: str, subdomain: str, target_role: str = "") -> Mapped | str:
    """Place (main domain, subdomain, optional role) in the catalog: a Mapped, or a sentence
    saying what could not be placed. The role from the file wins when it is a catalog role
    (close spellings are accepted); without one the role that fits the subdomain best is chosen,
    preferring one the stream's degree qualifies for."""
    stream = resolve_stream(main_domain)
    if stream is None:
        return f"main domain {main_domain!r} is not one of: {', '.join(streams())}"
    sub = _words(subdomain)
    domains = [d for d in syllabus.catalog()["domains"] if syllabus.stream_of(d["id"]) == stream]
    known = syllabus.role_skills()
    if target_role:
        names = {r: d["id"] for d in domains for r in (x["name"] for x in d.get("roles", []))}
        hit = {_key(n): n for n in names if n in known}.get(_key(target_role))
        if hit is None:
            close = difflib.get_close_matches(target_role, [n for n in names if n in known], 1, 0.8)
            hit = close[0] if close else None
        if hit is None:
            return f"role {target_role!r} is not a {stream} role in the catalog"
        domain = _catalog_domains()[names[hit]]
        return Mapped(stream, domain["id"], degree_for(stream), hit)
    scored = [(_score_domain(sub, d), -i, d) for i, d in enumerate(domains)]
    best_domain = max(scored, key=lambda t: t[:2])
    domain = best_domain[2]
    sub -= _generic(domain)  # what is left tells this domain's roles apart
    degree = degree_for(stream)
    entry = {"degree": degree, "specialization": subdomain, "status": "Pursuing"}
    roles = [r for r in domain.get("roles", []) if r["name"] in known]
    if not roles:
        return f"no catalog role to assign in {domain['name']}"
    ranked = [
        (_score_role(sub, r), degrees.fit(r.get("eligibility"), [entry]) is not None, -i, r)
        for i, r in enumerate(roles)
    ]
    best = max(ranked, key=lambda t: t[:3])
    unclear = bool(sub) or best_domain[0] == 0  # words the catalog has no role for, or nothing
    note = (
        f"no clear match for {subdomain!r}: {best[3]['name']} chosen"
        if unclear and not best[0]
        else ""
    )
    return Mapped(stream, domain["id"], degree, best[3]["name"], note)


def degree_for(stream: str) -> str:
    codes = degrees.stream_degrees(stream)
    return codes[0] if codes else ""


def education_text(degree: str, subdomain: str, batch_year: str = "") -> str:
    """The education a new student starts with: 'B.Com in Taxation & Audit (pursuing, 2027)'."""
    if not degree:
        return subdomain
    entry = {
        "degree": degree,
        "specialization": subdomain,
        "status": "Pursuing",
        "end": batch_year[-4:] if batch_year else "",
    }
    return degrees.entry_label(entry)


def education_line(row: ParsedRow) -> str:
    return education_text(row.degree, row.subdomain, row.batch_year)


# --- secrets ------------------------------------------------------------------------------------

_UPPER, _LOWER = "ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz"  # no I, O, l
_DIGITS, _SYMBOLS = "23456789", "!#$%&*?"  # no 0, 1; no quotes, @ or spaces
_ALL = _UPPER + _LOWER + _DIGITS + _SYMBOLS


def generate_password(length: int = TEMP_PASSWORD_LEN) -> str:
    """A readable temporary password: `length` characters with an upper-case letter, a
    lower-case letter, a digit and a symbol, none of the look-alikes (0 O 1 l I). It never
    starts with a symbol, so a spreadsheet cannot read it as a formula."""
    first = secrets.choice(_UPPER + _LOWER + _DIGITS)
    chars = [secrets.choice(_UPPER), secrets.choice(_LOWER), secrets.choice(_DIGITS)]
    chars.append(secrets.choice(_SYMBOLS))
    chars += [secrets.choice(_ALL) for _ in range(max(0, length - 5))]
    secrets.SystemRandom().shuffle(chars)
    return first + "".join(chars)


def make_username(email: str, taken: set[str]) -> str:
    """A free username from the email's local part (3-20 characters of a-z 0-9 . _ -); a
    number is added when it is taken. `taken` gains the one returned."""
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower()).strip("._-")
    base = (base or "student")[:20].ljust(3, "0")
    name, n = base, 1
    while name in taken:
        n += 1
        name = base[: 20 - len(str(n))] + str(n)
    taken.add(name)
    return name


# --- provisioning -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Credential:
    """What one student was given. The only place a password or code exists in plain text,
    other than their email."""

    name: str
    email: str
    username: str
    password: str
    code: str  # XXX-XXX-XXX
    main_domain: str
    subdomain: str
    target_role: str
    student_id: str = ""


@dataclass(frozen=True)
class ProvisionResult:
    created: tuple[Credential, ...]
    skipped: tuple[ParsedRow, ...]  # rows that were not Ready
    emails_queued: int
    channel: str  # "smtp" or "outbox"
    telemetry_saved: int


def _hash_all(passwords: Sequence[str]) -> list[str]:
    """PBKDF2 for every password, in parallel (the digest runs without the GIL)."""
    pepper = settings().auth_pepper
    with ThreadPoolExecutor(min(8, max(1, len(passwords)))) as pool:
        return list(pool.map(lambda p: auth.hash_password(p, pepper=pepper), passwords))


def _welcome_code(now: float) -> tuple[str, str, str, float]:
    """(code, its hash, its salt, expiry): the 9-digit code a welcome email carries."""
    code, salt = auth.new_code(), auth.new_salt()
    hashed = auth.hash_code(code, salt, pepper=settings().auth_pepper)
    return code, hashed, salt, now + ORG_WELCOME_CODE_TTL_S


def provision(
    org: Organization,
    rows: Sequence[ParsedRow],
    *,
    send_email: bool = True,
    now: float | None = None,
) -> ProvisionResult:
    """Create an account for every Ready row (see the module doc). Rows are re-checked against
    the database first, so a student added since the preview is skipped, not duplicated. All
    accounts are stored together or not at all; telemetry and email are best-effort after that.
    Raises ServiceError only when nothing could be stored."""
    rows = check_database(rows)
    ready = [r for r in rows if r.ready]
    skipped = tuple(r for r in rows if not r.ready)
    if not ready:
        return ProvisionResult((), skipped, 0, "outbox", 0)
    now = time.time() if now is None else now  # the sign-in clock, so a code's life is its own
    taken = db.usernames_in_use()
    usernames = [make_username(r.email, taken) for r in ready]
    passwords = [generate_password() for _ in ready]
    hashes = _hash_all(passwords)
    codes = [_welcome_code(now) for _ in ready]
    ids = [uuid.uuid4().hex for _ in ready]
    new = [
        db.NewStudent(
            id=sid,
            name=r.name,
            username=user,
            email=r.email,
            target_role=r.target_role,
            main_domain=r.stream or r.main_domain,
            subdomain=r.subdomain,
            phone=r.phone or None,
            batch_year=r.batch_year or None,
            password_hash=h,
            code_hash=c[1],
            code_salt=c[2],
            code_expires_at=c[3],
            sent_at=now,
            profile=services.starting_profile(r.name, r.target_role, education_line(r)),
        )
        for r, sid, user, h, c in zip(ready, ids, usernames, hashes, codes, strict=True)
    ]
    try:
        db.create_org_students(org.id, new)
    except sqlite3.IntegrityError as e:  # taken between the check and the insert
        raise ServiceError(
            "Some of these students were added while you were uploading. Nothing was saved: "
            "check the file again."
        ) from e
    created = tuple(
        Credential(
            r.name,
            r.email,
            user,
            pw,
            auth.format_code(c[0]),
            r.stream or r.main_domain,
            r.subdomain,
            r.target_role,
            sid,
        )
        for r, sid, user, pw, c in zip(ready, ids, usernames, passwords, codes, strict=True)
    )
    journey.record_organization(org.id)
    saved = journey.record_students(list(ids))
    queued, channel = (0, "outbox")
    if send_email:
        queued, channel = send_welcomes(org, created)
    return ProvisionResult(created, skipped, queued, channel, saved)


def send_welcomes(
    org: Organization, creds: Sequence[Credential], *, reset: bool = False
) -> tuple[int, str]:
    """Queue one welcome email per credential (background, one SMTP connection per batch) and
    write each to the outbox log too. Returns (emails queued, "smtp" or "outbox")."""
    msgs = [
        mailer.welcome_message(
            c.email,
            name=c.name,
            org_name=org.name,
            admin_name=org.admin_name,
            main_domain=c.main_domain,
            subdomain=c.subdomain,
            target_role=c.target_role,
            password=c.password,
            code=c.code,
            reset=reset,
        )
        for c in creds
    ]
    channel = mailer.send_many(msgs, also_outbox=True)
    return len(msgs), channel


def reset_credentials(
    org: Organization, student: sqlite3.Row, *, send_email: bool = True, now: float | None = None
) -> Credential:
    """New temporary password and welcome code for one of the organization's students: stored,
    emailed (and logged to the outbox) and returned for the admin's one-time download. The old
    password stops working and the student is signed out everywhere."""
    now = time.time() if now is None else now
    password = generate_password()
    code, code_hash, salt, expires = _welcome_code(now)
    ok = db.reset_org_student_credentials(
        org.id,
        student["id"],
        _hash_all([password])[0],
        code_hash,
        salt,
        expires,
        now,
    )
    if not ok:
        raise ServiceError("That student is not in your organization.")
    cred = Credential(
        student["name"],
        student["email"] or "",
        student["username"],
        password,
        auth.format_code(code),
        student["main_domain"] or "",
        student["subdomain"] or "",
        student["target_role"],
        student["id"],
    )
    if cred.email and send_email:
        send_welcomes(org, [cred], reset=True)
    return cred


CREDENTIAL_COLUMNS = (
    "Name",
    "Login email",
    "Username",
    "Temporary password",
    "9-digit code",
    "Main domain",
    "Subdomain",
    "Target role",
)


def credentials_csv(creds: Sequence[Credential]) -> bytes:
    """The credentials the admin may hand out when email is slow or offline: UTF-8 with a BOM
    for Excel. Names and domains are sanitized; the password and code cannot begin with a
    formula character by construction (generate_password)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CREDENTIAL_COLUMNS)
    for c in creds:
        w.writerow(
            [
                sanitize(c.name),
                c.email,
                c.username,
                c.password,
                c.code,
                sanitize(c.main_domain),
                sanitize(c.subdomain),
                sanitize(c.target_role),
            ]
        )
    return buf.getvalue().encode("utf-8-sig")
