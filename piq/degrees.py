"""Degrees: the qualifications a student can list, and which catalog roles they qualify for.

data/degrees.json lists every qualification from Class 10 to a doctorate, with its level and
the field it names. Each role in data/career_catalog.json has an `eligibility` rule: degree
codes or "@group"s it accepts and, optionally, the fields (branches) it accepts. A degree
qualifies when its code is accepted and, if the role names fields, the degree's own field or
the student's specialisation names one of them as whole words. A completed degree qualifies
now; one being pursued qualifies on completion. Pure data, no Streamlit.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from piq import syllabus
from piq.checks import evidenced, tokens
from piq.config import DATA_DIR

DEGREES = DATA_DIR / "degrees.json"
STATUSES = ("Completed", "Pursuing")
GRADUATE_LEVELS = ("Bachelor's", "Master's", "Doctorate")


@dataclass(frozen=True)
class Degree:
    code: str
    name: str
    level: str
    field: str  # the subject the degree itself names ("" for a general one)
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class RoleFit:
    """A catalog role a student's degrees qualify them for."""

    role: str
    domain_id: str
    domain_name: str
    eligible_now: bool  # False: qualifies once the degree being pursued is completed
    via: str  # the qualifying degree, as entry_label shows it


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(DEGREES.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def degrees() -> tuple[Degree, ...]:
    """Every qualification, lowest level first (the order of data/degrees.json)."""
    return tuple(
        Degree(d["code"], d["name"], d["level"], d.get("field", ""), tuple(d.get("aliases", [])))
        for d in _data()["degrees"]
    )


def levels() -> tuple[str, ...]:
    return tuple(_data()["levels"])


def stream_degrees(stream: str) -> tuple[str, ...]:
    """The degree codes a stream's students typically study for ("Commerce": B.Com, M.Com); empty
    for a stream data/degrees.json does not list."""
    return tuple(_data().get("streams", {}).get(stream, {}).get("degrees", ()))


def degree(code: str) -> Degree | None:
    return next((d for d in degrees() if d.code == code), None)


def codes() -> list[str]:
    return [d.code for d in degrees()]


def label(code: str) -> str:
    """How a degree code reads in a picker: its full name."""
    d = degree(code)
    return d.name if d else code


def _short_code(letters: str, text: str) -> bool:
    """A two-letter code ("BE", "ME", "BA", "CA") counts only in capitals, dotted or not, so
    "will be graduating" does not read as a B.E."""
    pattern = r"\.?".join(re.escape(c) for c in letters.upper())
    return re.search(rf"(?<![A-Za-z]){pattern}\.?(?![A-Za-z])", text) is not None


def parse(text: str) -> Degree | None:
    """The degree a free-text line names ("B.E. in ECE, 2026" -> B.E), or None. The longest
    alias that appears as whole words wins; dots are ignored ("B.Tech" = "BTech")."""
    words = tokens(text.replace(".", ""))
    best: tuple[int, int, Degree] | None = None
    rank = {lvl: i for i, lvl in enumerate(levels())}
    for d in degrees():
        for alias in (d.code, *d.aliases):
            phrase = tokens(alias.replace(".", ""))
            if not phrase or not _contains(words, phrase):
                continue
            if len(phrase) == 1 and len(phrase[0]) <= 2 and not _short_code(phrase[0], text):
                continue
            key = (len("".join(phrase)), rank.get(d.level, 0))
            if best is None or key > best[:2]:
                best = (*key, d)
    return best[2] if best else None


def _contains(words: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return any(words[i : i + n] == phrase for i in range(len(words) - n + 1))


def expand(accepted: Iterable[str]) -> set[str]:
    """Degree codes and "@group"s -> the set of degree codes they accept."""
    groups = _data().get("groups", {})
    out: set[str] = set()
    for item in accepted:
        if item == "@any_graduate":
            out |= {d.code for d in degrees() if d.level in GRADUATE_LEVELS and d.code != "Other"}
        elif item == "@any_postgraduate":
            out |= {d.code for d in degrees() if d.level in GRADUATE_LEVELS[1:]}
        elif item.startswith("@"):
            out |= set(groups[item[1:]])
        else:
            out.add(item)
    return out


def entry_label(entry: Mapping[str, Any]) -> str:
    """One education entry in a line: "M.Tech in VLSI Design (pursuing, 2027)"."""
    code = entry.get("degree", "")
    spec = (entry.get("specialization") or "").strip()
    if entry.get("title"):  # an entry carried over from an older resume: its own words
        text = str(entry["title"]).strip()
    elif code == "Other" or not code:
        text = spec or "Other qualification"
    else:
        text = f"{code} in {spec}" if spec else code
    if entry.get("status") == "Pursuing":
        end = (entry.get("end") or "").strip()
        text += f" (pursuing, {end})" if end else " (pursuing)"
    return text


def qualifies(eligibility: Mapping[str, Any] | None, entry: Mapping[str, Any]) -> bool:
    """Does one education entry meet a role's rule (whatever its status)?"""
    if not eligibility:
        return False
    code = entry.get("degree", "")
    if code not in expand(eligibility.get("degrees", [])):
        return False
    fields = eligibility.get("fields") or []
    if not fields:
        return True
    d = degree(code)
    own = f"{d.field if d else ''} {entry.get('specialization', '')} {entry.get('title', '')}"
    words = tokens(own)
    return any(evidenced(f, words) for f in fields)


def fit(
    eligibility: Mapping[str, Any] | None, entries: Sequence[Mapping[str, Any]]
) -> tuple[bool, str] | None:
    """(eligible now, qualifying degree) for the best entry, or None when none qualifies. A
    completed degree beats one being pursued."""
    best: tuple[bool, str] | None = None
    for e in entries:
        if not qualifies(eligibility, e):
            continue
        now = e.get("status", "Completed") != "Pursuing"
        if best is None or (now and not best[0]):
            best = (now, entry_label(e))
    return best


def roles_for(entries: Sequence[Mapping[str, Any]]) -> list[RoleFit]:
    """Every catalog role the entries qualify for: those open now first, then those open on
    completion, each in catalog order."""
    out = []
    for d in syllabus.catalog()["domains"]:
        for r in d.get("roles", []):
            if (f := fit(r.get("eligibility"), entries)) is not None:
                out.append(RoleFit(r["name"], d["id"], d["name"], f[0], f[1]))
    return sorted(out, key=lambda f: not f.eligible_now)
