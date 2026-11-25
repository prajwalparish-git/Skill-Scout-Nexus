"""The open question bank: openly licensed questions with answers, and where each came from.

data/questions/sources.json records every source: its licence (checked against the pinned
licence file when imported), the pinned version and checksums, the attribution and what we
changed. data/questions/open_bank.csv (multiple choice, read by piq/question_bank.py) and
data/questions/open_interview.json (open questions with our own model answers, for mock
interviews) are the committed seed that scripts/import_open_questions.py builds. Every row names
its source and licence. Nothing comes from Quora, Medium, LinkedIn, Glassdoor, PracHub,
LeetCode problem text or copyrighted books.

These questions are general practice: they are never presented as asked at any company.
Pure data.
"""

import json
import re
from collections.abc import Sequence
from functools import lru_cache

from piq.config import DATA_DIR

QUESTIONS_DIR = DATA_DIR / "questions"
SOURCES = QUESTIONS_DIR / "sources.json"
LICENSES = QUESTIONS_DIR / "LICENSES.md"
OPEN_BANK = QUESTIONS_DIR / "open_bank.csv"
OPEN_BANK_FULL = QUESTIONS_DIR / "open_bank_full.csv"  # the optional full import (git-ignored)
OPEN_INTERVIEW = QUESTIONS_DIR / "open_interview.json"
OPEN_LABEL = "General practice (open question bank)"
NOT_ASKED = "Not questions asked at {company}: general practice from openly licensed sources."
# Sites nothing may be taken from (checked on every source URL and row).
FORBIDDEN = ("quora", "medium.com", "linkedin", "glassdoor", "prachub", "leetcode")
OPEN_COLUMNS = ("id", "source", "licence", "modified", "changes", "source_ref")
INTERVIEW_ROUNDS = ("hr", "technical")

_NUMBER = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+)?")


@lru_cache(maxsize=1)
def registry() -> dict:
    """sources.json: {"sources": {key: {...}}, "licences": {id: {...}}}."""
    return json.loads(SOURCES.read_text(encoding="utf-8"))


def sources() -> dict[str, dict]:
    return registry()["sources"]


def credit(source: str, modified: bool, by: str = "") -> str:
    """The short credit line shown under a question, e.g. "AQuA-RAT · Apache-2.0 · modified",
    or for a contribution "Community · CC-BY-4.0 · by <display name>"."""
    s = sources().get(source)
    if s is None or source == "own":
        return ""
    parts = [s.get("short", s["name"]), s["licence_id"]]
    if modified:
        parts.append("modified")
    if by:
        parts.append(f"by {by}")
    return " · ".join(parts)


def credits_page(bank_counts: dict[str, int]) -> dict:
    """What the "Question sources & credits" page shows: each source with its licence,
    attribution, pinned version, what we changed and how many of its questions are in use."""
    reg = registry()
    interview: dict[str, int] = {}
    for q in interview_questions():
        interview[q["source"]] = interview.get(q["source"], 0) + 1
    out = []
    for key, s in reg["sources"].items():
        lic = reg["licences"].get(s["licence_id"], {})
        out.append(
            {
                "key": key,
                "name": s["name"],
                "homepage": s.get("homepage", ""),
                "commit": s.get("commit", ""),
                "licence_id": s["licence_id"],
                "licence_name": lic.get("name", "Our own questions"),
                "licence_url": lic.get("url", ""),
                "attribution": s["attribution"],
                "modifications": s.get("modifications", []),
                "multiple_choice": bank_counts.get(key, 0),
                "interview": interview.get(key, 0),
            }
        )
    return {
        "sources": out,
        "general_practice_note": (
            "Open questions are general practice. None is presented as asked at any company."
        ),
        "licences_file": "data/questions/LICENSES.md",
    }


def forbidden_in(text: str) -> list[str]:
    low = (text or "").lower()
    return [f for f in FORBIDDEN if f in low]


# --- answer checks shared by the import, the app and ci_check ----------------------------------


def numbers(text: str) -> set[str]:
    """Numbers in a text, normalised: "1,200" and "1200.0" are the same."""
    out = set()
    for raw in _NUMBER.findall(text or ""):
        n = raw.replace(",", "")
        if "/" not in n and "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n.lstrip("+") or "0")
    return out


def answer_in_rationale(rationale: str, options: Sequence[str], correct: int) -> str | None:
    """None when the rationale's conclusion (its last two lines) gives the correct option's
    number and no other option's; else why not. Options without a number cannot be checked."""
    mine = numbers(options[correct])
    if not mine:
        return "the correct option has no number to check against the rationale"
    lines = [ln.strip() for ln in (rationale or "").splitlines() if ln.strip()]
    tail = numbers(" ".join(lines[-2:]))
    if not mine & tail:
        return "the rationale does not end on the correct option's value"
    others = set().union(*(numbers(o) for i, o in enumerate(options) if i != correct)) - mine
    if others & tail:
        return "the rationale's conclusion also names another option's value"
    return None


# --- open questions for mock interviews ----------------------------------------------------------


@lru_cache(maxsize=1)
def interview_questions() -> tuple[dict, ...]:
    """Open questions with model answers: {id, round, subtopic, text, model_answer, source,
    licence, answer_source}. Empty when the file is missing."""
    if not OPEN_INTERVIEW.is_file():
        return ()
    return tuple(json.loads(OPEN_INTERVIEW.read_text(encoding="utf-8"))["questions"])


def for_round(round_: str) -> list[dict]:
    return [q for q in interview_questions() if q["round"] == round_]


def clear_cache() -> None:
    registry.cache_clear()
    interview_questions.cache_clear()
