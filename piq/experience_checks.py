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
    DIFFICULTIES,
    EXPERIENCE_MAX_QUESTIONS,
    EXPERIENCE_QUESTION_MAX,
    EXPERIENCE_QUESTION_MIN,
    EXPERIENCE_ROUNDS,
    EXPERIENCE_TEXT_MAX,
    EXPERIENCE_TIP_MAX,
    PROCESS_MAX_ROUNDS,
    PROCESS_MINUTES,
    PROCESS_RESULTS,
    PROCESS_ROUND_TYPES,
    PROCESS_SUMMARY_MAX,
    PROCESS_TO_ROUND,
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
    process: dict | None = None  # {rounds: [{type, minutes, difficulty}], result, summary}

    @property
    def content_hash(self) -> str:
        return content_hash(self.company_slug, post_texts(self.questions, self.process))


def content_hash(company_slug: str, texts: Sequence[str]) -> str:
    """Same company, same questions: the same post (a duplicate is refused)."""
    return text_hash(company_slug + "|" + "|".join(texts))


def post_texts(questions: Sequence[Mapping], process: Mapping | None) -> list[str]:
    """What makes a post itself: its questions, and its interview process (round order and
    summary), so the same process shared twice is a duplicate too."""
    texts = [q["text"] for q in questions]
    if process:
        order = ">".join(r["type"] for r in process["rounds"])
        texts.append(f"process:{order}:{process['result']}:{process['summary']}")
    return texts


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


# Promotion spam: flagged for the moderator, never refused (an "offer letter" is not spam).
_PROMO_STRONG = re.compile(
    r"\b(buy|buying|sell|selling|cheap|followers|discount|giveaway|promo ?code|coupon|"
    r"subscribers|likes for)\b",
    re.I,
)
_PROMO_WEAK = re.compile(r"\b(offer|deal|price|paid|payment|earn|income|dm me)\b", re.I)
_INVITE = re.compile(
    r"\b(whats ?app|telegram|t\.me|discord|discord\.gg|chat\.whatsapp)\b|"
    r"\bjoin (my|our|the) (group|channel|server|community)\b",
    re.I,
)
_HIDDEN_LINK = re.compile(
    r"\b[a-z0-9-]+\s*[\[(]?\s*dot\s*[\])]?\s*(com|in|net|org|io|co|xyz|me|app)\b|"
    r"\[\.\]|\(\.\)|\bhxxps?\b",
    re.I,
)
_LEFTOVER_PHONE = re.compile(r"(?:\d[\s.\-/()]*){8,}")  # digits the phone pattern missed
_PAID_REFERRAL = re.compile(
    r"\brefer(?:ral|rals|red)?\b.{0,40}\b(fee|fees|pay|paid|charge|charges|rs\.?|inr|rupees|"
    r"money|cost|₹)|\b(pay|paid|charge|fee)\b.{0,40}\breferr?al",
    re.I,
)


def promo_signals(text: str) -> list[str]:
    """Signs a post is promotion rather than an interview (checked after cleaning): selling
    words, chat-group invites, disguised links, phone numbers that slipped through, paid
    referrals. Flags for the moderator: nothing is refused for these."""
    out = []
    weak = {m.lower() for m in _PROMO_WEAK.findall(text)}
    if _PROMO_STRONG.search(text) or len(weak) >= 2:
        out.append("reads like promotion (buying, selling, followers or offers)")
    if _INVITE.search(text):
        out.append("invites readers to a WhatsApp, Telegram or Discord group")
    if _HIDDEN_LINK.search(text):
        out.append('contains a disguised link ("dot com", "[.]")')
    if _LEFTOVER_PHONE.search(text):
        out.append("contains a long number that may be a phone number")
    if _PAID_REFERRAL.search(text):
        out.append("offers a referral for money")
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


def _process(raw: Mapping, own: Sequence[str], found: set[str], flags: list[str]) -> dict:
    """The interview process: rounds in order (type, minutes or none, difficulty), the result
    and a short summary, cleaned like the questions."""
    rounds_in = list(raw.get("rounds") or [])
    if not rounds_in:
        raise ExperienceRejected("Your interview process: add the rounds you went through.")
    if len(rounds_in) > PROCESS_MAX_ROUNDS:
        raise ExperienceRejected(f"Your interview process: at most {PROCESS_MAX_ROUNDS} rounds.")
    low, high = PROCESS_MINUTES
    rounds = []
    for n, r in enumerate(rounds_in, 1):
        kind = str(r.get("type", ""))
        if kind not in PROCESS_ROUND_TYPES:
            raise ExperienceRejected(
                f"Round {n}: choose its type ({', '.join(PROCESS_ROUND_TYPES.values())})."
            )
        difficulty = str(r.get("difficulty", ""))
        if difficulty not in DIFFICULTIES:
            raise ExperienceRejected(f"Round {n}: say whether it was easy, medium or hard.")
        minutes = r.get("minutes")
        if minutes in ("", None):
            minutes = None
        elif (
            not isinstance(minutes, int) or isinstance(minutes, bool) or not low <= minutes <= high
        ):
            raise ExperienceRejected(f"Round {n}: give its length in minutes ({low}-{high}).")
        rounds.append({"type": kind, "minutes": minutes, "difficulty": difficulty})
    result = str(raw.get("result", ""))
    if result not in PROCESS_RESULTS:
        raise ExperienceRejected(
            f"Your interview process: choose the result ({', '.join(PROCESS_RESULTS.values())})."
        )
    summary = _clean_text(str(raw.get("summary", "")), "The summary", own, found)
    if len(summary) > PROCESS_SUMMARY_MAX:
        raise ExperienceRejected(f"Keep the summary under {PROCESS_SUMMARY_MAX} characters.")
    flags += [f"process summary: {s}" for s in copy_signals(summary)]
    if _shouting(summary):
        flags.append("process summary: mostly capitals")
    return {"rounds": rounds, "result": result, "summary": summary}


def clean_text(value: str, what: str, own: Sequence[str], found: set[str]) -> str:
    """Personal data replaced (the kinds found added to `found`); abuse and spam refused."""
    return _clean_text(value, what, own, found)


def meaningful(text: str) -> str:
    """The text without placeholders: what is left to judge."""
    return _meaningful(text)


def clean_submission(form: Mapping, own: Sequence[str], today: date | None = None) -> Cleaned:
    """Validate and clean a post: questions, an interview process, or both. Raises
    ExperienceRejected with the reason."""
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
    month = _month(str(form.get("interview_month", "")), today)
    tip = _clean_text(str(form.get("tip", "")), "The tip", own, found)
    if len(tip) > EXPERIENCE_TIP_MAX:
        raise ExperienceRejected(f"Keep the tip under {EXPERIENCE_TIP_MAX} characters.")
    raw_process = form.get("process")
    process = _process(raw_process, own, found, flags) if raw_process else None

    raw = list(form.get("questions") or [])
    round_ = str(form.get("round", ""))
    if not raw and process is None:
        raise ExperienceRejected("Add at least one question you were asked, or your process.")
    if not raw and round_ not in EXPERIENCE_ROUNDS:  # only a process: its first round
        first = process["rounds"][0]["type"]
        round_ = PROCESS_TO_ROUND.get(first, first)
    if round_ not in EXPERIENCE_ROUNDS:
        raise ExperienceRejected(f"Choose a round: {', '.join(EXPERIENCE_ROUNDS.values())}.")
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
    whole = " ".join(
        [
            role,
            tip,
            (process or {}).get("summary", ""),
            *(f"{q['text']} {' '.join(q['options'])} {q['explanation']}" for q in questions),
        ]
    )
    flags += [f"promotion: {s}" for s in promo_signals(whole)]
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
        process,
    )
