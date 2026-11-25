"""Syllabus: each career domain's topics, each role's focus topics, and topic colour slots.

data/career_catalog.json lists the domains: their topics in a fixed order (the n-th topic takes
the n-th topic colour) and how many leading topics every student of the domain tracks
(`core_topics`; the six CS core topics, otherwise just Aptitude). data/role_skills.json maps
each role's required skills to those topics. A student tracks their role's focus topics plus
any other topic of the domain they have chosen to quiz. Pure data.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from piq.config import DATA_DIR, DEFAULT_DOMAIN, MAX_DOMAIN_TOPICS

CATALOG = DATA_DIR / "career_catalog.json"
ROLE_SKILLS = DATA_DIR / "role_skills.json"


@dataclass(frozen=True)
class Domain:
    id: str
    name: str
    icon: str
    description: str
    topics: tuple[str, ...]
    core: tuple[str, ...]  # tracked by every student of the domain
    code_space: bool  # coding-heavy: students get the Project space
    roles: tuple[str, ...]  # catalog roles, in catalog order


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def role_skills() -> dict[str, dict[str, str | None]]:
    """role -> {required skill -> topic or None}."""
    return json.loads(ROLE_SKILLS.read_text(encoding="utf-8"))["roles"]


@lru_cache(maxsize=1)
def skill_aliases() -> dict[str, tuple[str, ...]]:
    """skill -> other names a resume may use for it (role_skills.json "aliases")."""
    raw = json.loads(ROLE_SKILLS.read_text(encoding="utf-8")).get("aliases", {})
    return {s: tuple(a) for s, a in raw.items()}


@lru_cache(maxsize=1)
def domains() -> tuple[Domain, ...]:
    out = []
    for d in catalog()["domains"]:
        topics = tuple(d["topics"])
        out.append(
            Domain(
                id=d["id"],
                name=d["name"],
                icon=d.get("icon", "work"),
                description=d.get("description", ""),
                topics=topics,
                core=topics[: d.get("core_topics", 1)],
                code_space=bool(d.get("code_space", False)),
                roles=tuple(r["name"] for r in d.get("roles", [])),
            )
        )
    return tuple(out)


def stream_of(domain_id: str) -> str:
    """The academic stream (Engineering, Commerce, Law, Management, ...) a domain belongs to."""
    return next(
        (d.get("stream", "Engineering") for d in catalog()["domains"] if d["id"] == domain_id),
        "Engineering",
    )


def domain(domain_id: str) -> Domain:
    for d in domains():
        if d.id == domain_id:
            return d
    raise KeyError(domain_id)


def domain_of_role(role: str) -> Domain:
    """The domain that lists `role`; a role only role_skills.json knows (the original CS
    roles) belongs to DEFAULT_DOMAIN."""
    for d in domains():
        if role in d.roles:
            return d
    return domain(DEFAULT_DOMAIN)


def roles_in(domain_id: str) -> list[str]:
    """The roles a student of this domain can target: catalog order, then any role only
    role_skills.json lists that falls back to this domain. Only roles with a skill list."""
    d = domain(domain_id)
    known = role_skills()
    listed = [r for r in d.roles if r in known]
    extra = [r for r in known if r not in listed and domain_of_role(r).id == domain_id]
    return listed + extra


def focus_topics(role: str) -> list[str]:
    """The domain's core topics plus every topic the role's skills are practised under, in
    the domain's order."""
    d = domain_of_role(role)
    wanted = set(d.core) | {t for t in role_skills().get(role, {}).values() if t}
    return [t for t in d.topics if t in wanted]


def tracked_topics(role: str, chosen: Iterable[str] = ()) -> list[str]:
    """Focus topics plus the domain topics in `chosen` (topics with quiz scores), in the
    domain's order. Topics of another domain (left by an earlier role) are not tracked."""
    d = domain_of_role(role)
    wanted = set(focus_topics(role)) | set(chosen)
    return [t for t in d.topics if t in wanted]


def other_topics(role: str, tracked: Iterable[str]) -> list[str]:
    """The rest of the role's domain: topics a student can choose to practise."""
    seen = set(tracked)
    return [t for t in domain_of_role(role).topics if t not in seen]


def all_topics() -> frozenset[str]:
    """Every topic of every domain."""
    return frozenset(_slots())


def skills_for_topic(role: str, topic: str) -> list[str]:
    return [s for s, t in role_skills().get(role, {}).items() if t == topic]


@lru_cache(maxsize=1)
def _slots() -> dict[str, int]:
    """topic -> its colour slot: its position in the first domain that lists it."""
    out: dict[str, int] = {}
    for d in domains():
        for i, t in enumerate(d.topics):
            out.setdefault(t, i)
    return out


def color_slot(topic: str) -> int | None:
    return _slots().get(topic)


def color_domain(topics: Iterable[str]) -> list[str]:
    """A colour-scale domain of MAX_DOMAIN_TOPICS entries for charts: each topic at its own
    slot, so the theme's n-th categorical colour lands on it. A topic without a slot, or
    whose slot is taken (topics of two domains in one chart), takes the next free one.
    Unused slots hold placeholders that no data matches."""
    domain_ = [f"⁣{i}" for i in range(MAX_DOMAIN_TOPICS)]  # invisible, never a topic
    taken: set[int] = set()
    pending = []
    for t in dict.fromkeys(topics):
        slot = color_slot(t)
        if slot is None or slot in taken or slot >= MAX_DOMAIN_TOPICS:
            pending.append(t)
            continue
        domain_[slot] = t
        taken.add(slot)
    for t in pending:
        free = next((i for i in range(MAX_DOMAIN_TOPICS) if i not in taken), None)
        if free is None:
            domain_.append(t)  # more topics than colours: Vega cycles the palette
            continue
        domain_[free] = t
        taken.add(free)
    return domain_
