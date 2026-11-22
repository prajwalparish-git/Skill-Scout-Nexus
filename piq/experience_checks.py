"""Cleaning a reported interview experience before a human moderator sees it.

Deterministic, so it runs the same in every mode (live, offline, MOCK_MODE):
- personal data is replaced: emails, phone numbers, links, @handles, "Mr. / Ms. / Dr. Name",
  "my name is ...", "named / called Name", and the poster's own name, username and email;
- a post is refused, with a reason the student sees, for abuse, spam, nothing left after
  cleaning, questions too short or too long, or an invalid MCQ;
- it is flagged for the moderator (never refused) when it looks copied from a problem or review
  site, is mostly capitals, or names a company we do not know;
- the company name is normalised against data/companies.json.

Nothing here approves a post: only a person does (piq/experiences.py).
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from piq.checks import text_hash
from piq.config import (
    DATA_DIR,
    EXPERIENCE_MAX_QUESTIONS,
    EXPERIENCE_QUESTION_MAX,
    EXPERIENCE_QUESTION_MIN,
    EXPERIENCE_ROUNDS,
    EXPERIENCE_TEXT_MAX,
    EXPERIENCE_TIP_MAX,
)

COMPANIES = DATA_DIR / "companies.json"
PLACEHOLDERS = ("[name]", "[email]", "[phone]", "[link]", "[handle]")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w])(?:\+?91[\s-]?)?(?:\d[\s-]?){9}\d(?![\w])")
_URL = re.compile(
    r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|in|org|net|io|co|dev|me|ai)(?:/\S*)?\b", re.I
)
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_.]{3,}")
_TITLED = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof|Sir|Madam)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")
_INTRO = re.compile(r"\b(my name is|named|called)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", re.I)
_REPEAT = re.compile(r"(.)\1{7,}")
_WORD = re.compile(r"[A-Za-z0-9']+")

# Abuse a post is refused for (English and common Hinglish), matched as whole words.
_ABUSE = frozenset(
    [
        *("fuck", "fucking", "fucker", "motherfucker", "shit", "bitch", "bastard", "asshole"),
        *("dick", "cunt", "slut", "whore", "chutiya", "chutiye", "madarchod", "behenchod"),
        *("bhenchod", "bhosdike", "bhosdi", "gandu", "harami", "randi", "lund", "lauda", "laude"),
    ]
)
# Signs a question was pasted from a problem or review site: the moderator decides.
_SITES = ("leetcode", "geeksforgeeks", "glassdoor", "prachub", "ambitionbox", "interviewbit")
_BOILERPLATE = re.compile(
    r"\bExample \d+\s*:|\bConstraints\s*:|\bFollow[- ]up\s*:|\bUpvote|\bAsked in\b|"
    r"\bDifficulty\s*:\s*(?:Easy|Medium|Hard)\b|\bCompanies\s*:",
    re.I,
)


class ExperienceRejected(ValueError):
    """The post cannot be accepted; the message says why (safe to show the student)."""


@dataclass(frozen=True)
class Cleaned:
    company_slug: str
    company_name: str
    known_company: bool
    role: str
    round: str
    interview_month: str
    tip: str
    show_college: bool
    questions: list[dict]
    flags: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # kinds of personal data taken out

    @property
    def content_hash(self) -> str:
        return content_hash(self.company_slug, [q["text"] for q in self.questions])


def content_hash(company_slug: str, texts: Sequence[str]) -> str:
    """Same company, same questions: the same post (a duplicate is refused)."""
    return text_hash(company_slug + "|" + "|".join(texts))


# --- companies -----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def companies() -> tuple[dict, ...]:
    return tuple(json.loads(COMPANIES.read_text(encoding="utf-8"))["companies"])


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "and"))


@lru_cache(maxsize=1)
def _company_index() -> dict[str, dict]:
    out = {}
    for c in companies():
        for n in (c["name"], c["slug"], *c.get("aliases", [])):
            out[_key(n)] = c
    return out


def company(slug: str) -> dict | None:
    return next((c for c in companies() if c["slug"] == slug), None)


def normalise_company(typed: str) -> tuple[str, str, bool]:
    """(slug, display name, known). An unknown name is kept, title-cased where it was all one
    case, under a slug made from it."""
    name = " ".join((typed or "").split())
    if not name:
        raise ExperienceRejected("Name the company.")
    if len(name) > EXPERIENCE_TEXT_MAX:
        raise ExperienceRejected(f"Keep the company name under {EXPERIENCE_TEXT_MAX} characters.")
    found = _company_index().get(_key(name))
    if found:
        return found["slug"], found["name"], True
    shown = name.title() if name.islower() or name.isupper() else name
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "company"
    return f"x-{slug}", shown, False


# --- personal data -------------------------------------------------------------------------


def scrub(text: str, own: Iterable[str] = ()) -> tuple[str, set[str]]:
    """The text with personal data replaced, and which kinds were found."""
    found: set[str] = set()

    def sub(pattern: re.Pattern, repl: str, kind: str, s: str) -> str:
        out, n = pattern.subn(repl, s)
        if n:
            found.add(kind)
        return out

    s = sub(_EMAIL, "[email]", "email", text)
    s = sub(_URL, "[link]", "link", s)
    s = sub(_PHONE, "[phone]", "phone", s)
    s = sub(_HANDLE, "[handle]", "handle", s)
    s = sub(_TITLED, "[name]", "name", s)
    s, n = _INTRO.subn(lambda m: f"{m.group(1)} [name]", s)
    if n:
        found.add("name")
    for part in own:
        part = part.strip()
        if len(part) >= 3:
            s, n = re.subn(rf"(?<!\w){re.escape(part)}(?!\w)", "[name]", s, flags=re.I)
            if n:
                found.add("name")
    return " ".join(s.split()), found


def own_identity(name: str, username: str, email: str | None) -> list[str]:
    """What of the poster's own identity must never appear: name parts, username, email."""
    parts = [p for p in (name or "").split() if len(p) >= 3]
    return [*parts, name or "", username or "", email or "", (email or "").split("@")[0]]


# --- abuse, spam, copied text ---------------------------------------------------------------


def abusive(text: str) -> bool:
    return any(w.lower() in _ABUSE for w in _WORD.findall(text))


def copy_signals(text: str) -> list[str]:
    low = text.lower()
    sites = [s for s in _SITES if s in low]
    out = [f"mentions {', '.join(sites)}: check it is the student's own words"] if sites else []
    if _BOILERPLATE.search(text):
        out.append("reads like a problem-site listing (Example / Constraints / Difficulty)")
    return out


def _shouting(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) > 30 and sum(c.isupper() for c in letters) / len(letters) > 0.7


def _meaningful(text: str) -> str:
    """The text without placeholders: what is left to judge."""
    for p in PLACEHOLDERS:
        text = text.replace(p, " ")
    return " ".join(text.split())


# --- the whole submission --------------------------------------------------------------------


def _month(value: str, today: date) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})", (value or "").strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ExperienceRejected("Give the interview month as YYYY-MM, e.g. 2026-08.")
    year, month = int(m.group(1)), int(m.group(2))
    if (year, month) > (today.year, today.month):
        raise ExperienceRejected("The interview month cannot be in the future.")
    if year < today.year - 6:
        raise ExperienceRejected("Share interviews from the last few years only.")
    return f"{year:04d}-{month:02d}"


def _clean_text(value: str, what: str, own: Sequence[str], found: set[str]) -> str:
    s, kinds = scrub(value or "", own)
    found |= kinds
    if abusive(s):
        raise ExperienceRejected(f"{what} contains abusive language. Please rephrase it.")
    if _REPEAT.search(s):
        raise ExperienceRejected(f"{what} looks like spam (a character repeated many times).")
    return s


def clean_submission(form: Mapping, own: Sequence[str], today: date | None = None) -> Cleaned:
    """Validate and clean a post. Raises ExperienceRejected with the reason."""
    today = today or date.today()
    found: set[str] = set()
    flags: list[str] = []
    slug, name, known = normalise_company(str(form.get("company", "")))
    if not known:
        flags.append(f"new company {name!r}: check the name (or correct it to a known one)")
    role = _clean_text(str(form.get("role", "")), "The role", own, found)
    if not 2 <= len(role) <= EXPERIENCE_TEXT_MAX:
        raise ExperienceRejected(
            "Give the role you interviewed for (for example Systems Engineer)."
        )
    round_ = str(form.get("round", ""))
    if round_ not in EXPERIENCE_ROUNDS:
        raise ExperienceRejected(f"Choose a round: {', '.join(EXPERIENCE_ROUNDS.values())}.")
    month = _month(str(form.get("interview_month", "")), today)
    tip = _clean_text(str(form.get("tip", "")), "The tip", own, found)
    if len(tip) > EXPERIENCE_TIP_MAX:
        raise ExperienceRejected(f"Keep the tip under {EXPERIENCE_TIP_MAX} characters.")

    raw = list(form.get("questions") or [])
    if not raw:
        raise ExperienceRejected("Add at least one question you were asked.")
    if len(raw) > EXPERIENCE_MAX_QUESTIONS:
        raise ExperienceRejected(f"One post holds at most {EXPERIENCE_MAX_QUESTIONS} questions.")
    questions = []
    for n, q in enumerate(raw, 1):
        kind = q.get("kind", "open")
        if kind not in ("open", "mcq"):
            raise ExperienceRejected(f"Question {n}: choose open or multiple choice.")
        text = _clean_text(str(q.get("text", "")), f"Question {n}", own, found)
        left = _meaningful(text)
        if len(left) < EXPERIENCE_QUESTION_MIN:
            raise ExperienceRejected(
                f"Question {n}: write the question in your own words (at least "
                f"{EXPERIENCE_QUESTION_MIN} characters, not just a link)."
            )
        if len(text) > EXPERIENCE_QUESTION_MAX:
            raise ExperienceRejected(
                f"Question {n}: keep it under {EXPERIENCE_QUESTION_MAX} characters."
            )
        item: dict = {"kind": kind, "text": text, "options": [], "correct_index": None}
        if kind == "mcq":
            options = [
                _clean_text(str(o), f"Question {n}'s options", own, found)
                for o in (q.get("options") or [])
            ]
            if len(options) != 4 or not all(options) or len({o.lower() for o in options}) < 4:
                raise ExperienceRejected(f"Question {n}: give four different options.")
            correct = q.get("correct_index")
            if correct not in (0, 1, 2, 3):
                raise ExperienceRejected(f"Question {n}: mark the correct option.")
            item |= {"options": options, "correct_index": correct}
        explanation = _clean_text(str(q.get("explanation", "")), f"Question {n}'s note", own, found)
        item["explanation"] = explanation[:EXPERIENCE_QUESTION_MAX]
        flags += [f"question {n}: {s}" for s in copy_signals(text)]
        if _shouting(text):
            flags.append(f"question {n}: mostly capitals")
        questions.append(item)
    if found:
        flags.append(f"personal data removed automatically: {', '.join(sorted(found))}")
    return Cleaned(
        slug,
        name,
        known,
        role,
        round_,
        month,
        tip,
        bool(form.get("show_college", True)),
        questions,
        flags,
        sorted(found),
    )
