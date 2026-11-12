"""Study library: curated books and GitHub repositories for the plan page.

data/study_library.json holds the books (title, author, edition or focus, why read it, level and
free, publisher or archive links) and the repositories (category, why, estimated hours), each
tagged with the domains and syllabus topics it serves. `payload()` adds a role index built from
the syllabus so a front end can filter by target role without a second request. Pure data, no
Streamlit and no network: links were checked when the file was written ("checked").
"""

import json
from functools import lru_cache

from piq import syllabus
from piq.config import DATA_DIR

LIBRARY = DATA_DIR / "study_library.json"
LINK_KINDS = ("open", "publisher", "archive")
LEVELS = ("Beginner", "Intermediate", "Advanced")


@lru_cache(maxsize=1)
def library() -> dict:
    return json.loads(LIBRARY.read_text(encoding="utf-8"))


def role_index() -> dict[str, dict]:
    """role -> its domain, its focus topics and its required skills."""
    return {
        role: {
            "domain": syllabus.domain_of_role(role).id,
            "topics": syllabus.focus_topics(role),
            "skills": list(skills),
        }
        for role, skills in syllabus.role_skills().items()
    }


def payload() -> dict:
    """What GET /api/library returns."""
    lib = library()
    return {
        "checked": lib["checked"],
        "levels": lib["levels"],
        "domains": [{"id": d.id, "name": d.name} for d in syllabus.domains()],
        "roles": role_index(),
        "books": lib["books"],
        "repo_categories": lib["repo_categories"],
        "repos": lib["repos"],
    }


def books_for(domain_id: str, topic: str | None = None) -> list[dict]:
    """Books for a domain, narrowed to a topic when one is given."""
    return [
        b
        for b in library()["books"]
        if domain_id in b["domains"] and (topic is None or topic in b["topics"])
    ]


# --- the same ranking the web plan page uses (frontend/lib/library.ts) ------------------------

LEVEL_RANK = {level: i for i, level in enumerate(LEVELS)}
LINK_ORDER = {kind: i for i, kind in enumerate(LINK_KINDS)}


def _matches(query: str, *parts: object) -> bool:
    """Every word of `query` appears somewhere in `parts` (case-insensitive)."""
    hay = " ".join(" ".join(p) if isinstance(p, list) else str(p) for p in parts).lower()
    return all(w in hay for w in query.lower().split())


def role_fit(item: dict, role: str) -> int:
    """-1 for another domain, else how many topics (Aptitude aside) and skills it shares."""
    entry = role_index().get(role)
    if entry is None:
        return 0
    if entry["domain"] not in item["domains"]:
        return -1
    topics = [t for t in item["topics"] if t != "Aptitude" and t in entry["topics"]]
    skills = [s for s in item.get("skills", []) if s in entry["skills"]]
    return len(topics) + len(skills)


def books_for_student(
    role: str, weak_topics: list[str], query: str = "", level: str | None = None
) -> list[tuple[dict, list[str]]]:
    """The role's domain's books, each with the weak topics it covers; those come first."""
    domain_id = syllabus.domain_of_role(role).id
    weak = set(weak_topics)
    out = []
    for b in books_for(domain_id):
        if (level and b["level"] != level) or not _matches(
            query, b["title"], b["author"], b["why"], b["topics"]
        ):
            continue
        out.append((b, [t for t in b["topics"] if t in weak]))
    out.sort(
        key=lambda x: (
            -len(x[1]),
            -role_fit(x[0], role),
            LEVEL_RANK[x[0]["level"]],
            x[0]["title"],
        )
    )
    return out


def repos_for_role(role: str, query: str = "", category: str | None = None) -> list[dict]:
    """Repositories that fit the role: 3 shared skills or topics in computer science (where
    there are many), 1 elsewhere; best fit first."""
    entry = role_index().get(role)
    need = 3 if entry and entry["domain"] == "cs" else 1
    picked = [
        (r, role_fit(r, role))
        for r in library()["repos"]
        if (not category or r["category"] == category)
        and _matches(query, r["repo"], r["why"], r["topics"], r["skills"])
    ]
    picked = [(r, f) for r, f in picked if f >= need]
    picked.sort(key=lambda x: (-x[1], LEVEL_RANK[x[0]["level"]], x[0]["repo"]))
    return [r for r, _ in picked]


def best_link(book: dict) -> dict:
    """A free copy first, then the publisher, then the archive."""
    return min(book["links"], key=lambda link: LINK_ORDER[link["kind"]])
