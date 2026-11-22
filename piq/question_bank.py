"""The question bank: vetted multiple-choice questions, served instantly or mixed into quizzes.

data/questions/mcq_bank.csv is our own bank (its raw source, MCQ.csv, is not committed), and
data/questions/open_bank.csv the open question bank: openly licensed questions with answers,
each row naming its source and licence (piq/open_questions.py; open_bank_full.csv, the optional
full import, replaces it when present). data/bank_topics.json maps each fine-grained topic to the
syllabus topic it serves (career_catalog.json), or to null. Without the CSVs the bank is empty
and every quiz question is generated, as before. Questions whose options repeat, whose answer
letter is invalid or whose text repeats another's are skipped (our own bank comes first).
Pure data, no Streamlit.
"""

import csv
import json
import random
import sqlite3
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from piq import open_questions
from piq.checks import text_hash
from piq.config import DATA_DIR, DIFFICULTIES
from piq.schemas import Question

BANK = DATA_DIR / "questions" / "mcq_bank.csv"
TOPIC_MAP = DATA_DIR / "bank_topics.json"
_LETTERS = "ABCD"


@lru_cache(maxsize=1)
def topic_map() -> dict[str, str | None]:
    """Bank topic -> syllabus topic (None: no domain teaches it)."""
    return json.loads(TOPIC_MAP.read_text(encoding="utf-8"))["topics"]


def problems(row: dict[str, str]) -> str | None:
    """Why a bank row cannot be a question (None when it can): four non-empty options that
    differ, one valid answer letter, and a question the quiz schema accepts. Used by the
    loader, scripts/verify_and_ingest_mcq.py and scripts/import_open_questions.py."""
    options = [(row.get(f"option_{c}") or "").strip() for c in "abcd"]
    letter = (row.get("correct_option") or "").strip().upper()
    if not all(options):
        return "an option is empty"
    if len({" ".join(o.lower().split()) for o in options}) < 4:
        return "options repeat"
    if len(letter) != 1 or letter not in _LETTERS:
        return "no valid answer letter"
    try:
        _build(row, options, letter)
    except ValidationError:
        return "the question or explanation is not usable"
    return None


def _build(row: dict[str, str], options: list[str], letter: str) -> Question:
    return Question(
        text=(row.get("question") or "").strip(),
        options=options,
        correct_index=_LETTERS.index(letter),
        explanation=(row.get("explanation") or "").strip() or "From the question bank.",
        bloom_level=row.get("bloom_level") or "understand",
    )


def as_question(row: dict[str, str]) -> Question:
    """A row that passed problems() as a quiz question."""
    options = [(row.get(f"option_{c}") or "").strip() for c in "abcd"]
    return _build(row, options, (row.get("correct_option") or "").strip().upper())


def _question(row: dict[str, str]) -> Question | None:
    return None if problems(row) else as_question(row)


def _files() -> list[tuple[str, Path]]:
    """(default source, path): our own bank first, then the open bank (the full import when
    present). A row's own `source` column wins over the default."""
    full = open_questions.OPEN_BANK_FULL
    return [("own", BANK), ("open", full if full.is_file() else open_questions.OPEN_BANK)]


Loaded = tuple[
    dict[tuple[str, str], tuple[Question, ...]], dict[str, str], dict[str, tuple[str, bool, str]]
]


def _version() -> object:
    """The approved contributions' version: they live in the database, so every process sees an
    approval without a restart. None before there is a database (an import script)."""
    from piq import db  # the bank is pure data until contributions are asked for

    try:
        return db.contributions_version()
    except (sqlite3.Error, OSError):
        return None


def _rows(version: object) -> Iterator[tuple[str, dict[str, str]]]:
    """(default source, row): our own bank, the open bank, then approved contributions."""
    for default, path in _files():
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    yield default, row
    if version is not None:
        from piq import contributions

        for row in contributions.bank_rows():
            yield "contrib", row


@lru_cache(maxsize=2)
def _load_at(version: object) -> Loaded:
    """((syllabus topic, difficulty) -> distinct valid questions in file order, question id ->
    the bank's own fine-grained topic, e.g. SQL_Joins: what "a similar question" shares,
    question id -> (source key, modified, credited author or ""))."""
    mapping = topic_map()
    out: dict[tuple[str, str], list[Question]] = {}
    subtopics: dict[str, str] = {}
    origin: dict[str, tuple[str, bool, str]] = {}
    for default, row in _rows(version):
        raw = (row.get("topic") or "").strip()
        topic = mapping.get(raw) or row.get("syllabus_topic")
        difficulty = (row.get("difficulty") or "").strip().lower()
        if topic is None or difficulty not in DIFFICULTIES:
            continue
        q = _question(row)
        if q is None or (h := text_hash(q.text)) in subtopics:
            continue
        subtopics[h] = raw
        origin[h] = (row.get("source") or default, row.get("modified") == "1", row.get("by", ""))
        out.setdefault((topic, difficulty), []).append(q)
    return {k: tuple(v) for k, v in out.items()}, subtopics, origin


def _load() -> Loaded:
    return _load_at(_version())


def own_hashes() -> set[str]:
    """Duplicate hashes of every question in our own bank (the import never repeats one)."""
    return {h for h, (src, _, _) in _load()[2].items() if src == "own"}


def source(question_id: str) -> tuple[str, bool] | None:
    """(source key, modified) of a bank question: "own", "aqua_rat", "mmlu", "contrib", ..."""
    found = _load()[2].get(question_id)
    return found[:2] if found else None


def credit(question_id: str) -> str:
    """The credit line for an open-bank question ("" for our own and unknown questions)."""
    found = _load()[2].get(question_id)
    return open_questions.credit(*found) if found else ""


def is_open(question_id: str) -> bool:
    """From the open question bank (openly licensed, not our own bank)."""
    found = source(question_id)
    return found is not None and found[0] != "own"


def open_count(topic: str) -> int:
    """Open-bank questions on a syllabus topic, all levels."""
    return sum(
        1 for (t, _), qs in _questions().items() if t == topic for q in qs if is_open(qid(q))
    )


def draw_open(
    topic: str, level: str, k: int, avoid: Iterable[str], seed: str
) -> list[tuple[str, Question]]:
    """Up to `k` unseen open-bank (difficulty, question) pairs: the level first, then the
    nearest levels (like draw_nearest, open questions only)."""
    banned = {text_hash(t) for t in avoid}
    out: list[tuple[str, Question]] = []
    for d in nearest_levels(level):
        pool = [
            q
            for q in _questions().get((topic, d), ())
            if (h := text_hash(q.text)) not in banned and is_open(h)
        ]
        for q in random.Random(f"{seed}|{d}").sample(pool, min(k - len(out), len(pool))):
            out.append((d, q))
        if len(out) >= k:
            break
    return out


def counts_by_source() -> dict[str, int]:
    out: dict[str, int] = {}
    for src, _, _ in _load()[2].values():
        out[src] = out.get(src, 0) + 1
    return out


def _questions() -> dict[tuple[str, str], tuple[Question, ...]]:
    return _load()[0]


def qid(q: Question) -> str:
    """A question's stable id: the critic's duplicate hash of its text (unique in the bank)."""
    return text_hash(q.text)


@lru_cache(maxsize=2)
def _by_id_at(version: object) -> dict[str, tuple[str, str, Question]]:
    return {qid(q): (t, d, q) for (t, d), qs in _load_at(version)[0].items() for q in qs}


def _by_id() -> dict[str, tuple[str, str, Question]]:
    return _by_id_at(_version())


def get(question_id: str) -> tuple[str, str, Question] | None:
    """(syllabus topic, difficulty, question) for a bank question id, or None."""
    return _by_id().get(question_id)


def counts() -> dict[str, dict[str, int]]:
    """Syllabus topic -> difficulty -> bank questions."""
    out: dict[str, dict[str, int]] = {}
    for (t, d), qs in _questions().items():
        out.setdefault(t, {})[d] = len(qs)
    return out


def available(topic: str, difficulty: str) -> int:
    """How many bank questions serve `topic` at `difficulty`."""
    return len(_questions().get((topic, difficulty), ()))


def size() -> int:
    """Questions in the bank that some syllabus topic can use."""
    return sum(len(v) for v in _questions().values())


def draw(topic: str, difficulty: str, k: int, avoid: Iterable[str], seed: str) -> list[Question]:
    """Up to `k` bank questions on `topic` at `difficulty`, none matching a text in `avoid`
    (compared like the critic's duplicate check), chosen reproducibly from `seed`."""
    if k <= 0:
        return []
    banned = {text_hash(t) for t in avoid}
    pool = [q for q in _questions().get((topic, difficulty), ()) if text_hash(q.text) not in banned]
    return random.Random(seed).sample(pool, min(k, len(pool)))


def nearest_levels(level: str) -> list[str]:
    """Every difficulty, the given one first, then the others nearest to it (easier first)."""
    return sorted(
        DIFFICULTIES,
        key=lambda d: (abs(DIFFICULTIES.index(d) - DIFFICULTIES.index(level)), d != "easy"),
    )


def draw_nearest(
    topic: str, level: str, k: int, avoid: Iterable[str], seed: str
) -> list[tuple[str, Question]]:
    """Up to `k` unseen (difficulty, question) pairs: the asked level first, then the nearest."""
    avoid = list(avoid)
    out: list[tuple[str, Question]] = []
    for d in nearest_levels(level):
        if len(out) >= k:
            break
        for q in draw(topic, d, k - len(out), avoid, f"{seed}|{d}"):
            out.append((d, q))
            avoid.append(q.text)
    return out


def subtopic(question_id: str) -> str | None:
    """The bank's fine-grained topic of a bank question (None: not a bank question)."""
    return _load()[1].get(question_id)


def similar(
    question_id: str, avoid: Iterable[str], seed: str, prefer: str | None = None
) -> tuple[str, Question] | None:
    """An unseen bank question like this one: the same fine-grained topic, at its difficulty
    or an easier one (a missed question comes back no harder). `prefer`: try this level first
    when it is no harder (the student's level now). None when there is none."""
    found, sub = get(question_id), subtopic(question_id)
    if found is None or sub is None:
        return None
    topic, difficulty, _ = found
    banned = {text_hash(t) for t in avoid} | {question_id}
    subs = _load()[1]
    levels = DIFFICULTIES[: DIFFICULTIES.index(difficulty) + 1][::-1]  # same level, then easier
    if prefer in levels:
        levels = (prefer, *(d for d in levels if d != prefer))
    for d in levels:
        pool = [
            q
            for q in _questions().get((topic, d), ())
            if subs.get(h := text_hash(q.text)) == sub and h not in banned
        ]
        if pool:
            return d, random.Random(seed).choice(pool)
    return None


def clear_cache() -> None:
    topic_map.cache_clear()
    _load_at.cache_clear()
    _by_id_at.cache_clear()
    open_questions.clear_cache()
