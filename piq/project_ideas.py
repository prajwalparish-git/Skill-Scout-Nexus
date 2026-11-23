"""Project ideas matched to a student's skill gaps, derived from real open-source repositories.

The student's skill gaps (their profile's missing skills) choose up to MAX_TOPICS GitHub topics
(data/github_topics.json). For each topic, core/github_search.py finds popular repos, repos built
by companies (a listed GitHub Organization) and hackathon repos: metadata only, cached, with the
seed offline. The AI then writes 3-5 ideas built FROM those repos (combining two, a student-scale
version, an Indian use case, or a missing feature), each citing at least two of them with what
it takes and how it differs; the critic (checks.check_project_ideas) refuses invented repos.

Hackathon inspiration beyond GitHub is a link to the platforms' own search pages (Devpost,
Unstop) or project gallery (Devfolio, which has no public search): never scraped.

"Start this project" puts an idea in the Project space with status "Idea". Project space and
ideas are for computing domains (services.has_project_space). Pure logic, no Streamlit.
"""

import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from core import github_search as gh
from piq import agents, db, services, syllabus
from piq.graph import OnEvent
from piq.schemas import StudentProfile
from piq.services import ServiceError

MAX_TOPICS = 3
SETS_PER_DAY = 8  # idea sets (Suggest or More like this) a student may make in a day
LIMITS = {"popular": 5, "company": 4, "hackathon": 3}  # repos per topic and kind
REPOS_FOR_AI = 16
DERIVATION_LABELS = {
    "combine": "Combines two repos",
    "student_scale": "Student-scale version",
    "indian_use_case": "For an Indian use case",
    "missing_feature": "Fills a missing feature",
}
NOT_COMPUTING = (
    "Project ideas come with the Project space, which is for computing roles (CS and ECE). "
    "Your weekly plan and quizzes cover your domain."
)
GENERIC_TOPICS = {"hacktoberfest", "awesome", "awesome-list", "hacktoberfest2023", "list"}
FALLBACK_SKILLS = ("Git", "Python", "REST APIs")


def hackathon_links(keyword: str) -> list[dict]:
    """Where to find winning hackathon projects on a topic: the platforms' own pages."""
    q = quote_plus(keyword)
    return [
        {"name": "Devpost", "url": f"https://devpost.com/software/search?query={q}"},
        {"name": "Unstop", "url": f"https://unstop.com/hackathons?searchTerm={q}"},
        {"name": "Devfolio", "url": "https://devfolio.co/discover"},  # no public search URL
    ]


# --- who, and which topics ----------------------------------------------------------------------


def student_profile(student_id: str) -> StudentProfile:
    profile = services.current_profile(student_id)
    if profile is None:
        raise ServiceError("Scan your resume or choose your role first.")
    if not services.has_project_space(profile):
        raise ServiceError(NOT_COMPUTING)
    return profile


_profile = student_profile


def gaps(profile: StudentProfile) -> list[str]:
    """The student's skill gaps that have a project topic, in the profile's order; the role's
    required skills they lack when the profile lists none."""
    missing = [s for s in profile.missing_skills if gh.topic_for(s)]
    if missing:
        return missing
    have = {s.lower() for s in profile.skills}
    required = syllabus.role_skills().get(profile.target_role, {})
    return [s for s in required if s.lower() not in have and gh.topic_for(s)] or list(
        FALLBACK_SKILLS
    )


def topics(profile: StudentProfile) -> list[dict]:
    """Up to MAX_TOPICS {topic, keyword, skill} from the gaps (one per GitHub topic)."""
    out: list[dict] = []
    for skill in gaps(profile):
        t = gh.topic_for(skill)
        if t and all(o["topic"] != t["topic"] for o in out):
            out.append({**t, "skill": skill})
        if len(out) == MAX_TOPICS:
            break
    return out


# --- generating ---------------------------------------------------------------------------------


def _limit(student_id: str) -> None:
    since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    if db.idea_sets_since(student_id, since) >= SETS_PER_DAY:
        raise ServiceError(f"You can ask for project ideas {SETS_PER_DAY} times a day.")


def _fetch(chosen: Sequence[dict], exclude: set[str]) -> tuple[list[dict], list[gh.Repo], str]:
    """Per topic: its repos by kind and links; all repos for the AI; the overall source."""
    shown, everything, sources = [], [], set()
    for t in chosen:
        by_kind = {}
        for kind, limit in LIMITS.items():
            found = gh.find(t["topic"], kind, exclude, limit)
            sources.add(found.source)
            by_kind[kind] = [r.full_name for r in found.repos]
            everything += found.repos
        shown.append({**t, **by_kind, "links": hackathon_links(t["keyword"])})
    unique = list({r.full_name: r for r in everything}.values())
    source = "live" if "live" in sources else "cache" if "cache" in sources else "seed"
    return shown, unique, source


def _for_ai(repos: list[gh.Repo]) -> list[gh.Repo]:
    """At most REPOS_FOR_AI, company and popular first (by stars), hackathon ones kept too."""
    return sorted(repos, key=lambda r: (not r.company, -r.stars))[:REPOS_FOR_AI]


def _make(
    student_id: str,
    profile: StudentProfile,
    chosen: list[dict],
    exclude: set[str],
    based_on: str,
    on_event: OnEvent | None,
) -> dict:
    shown, repos, source = _fetch(chosen, exclude)
    if len(repos) < 2:  # nothing new around these topics: start again without the exclusions
        shown, repos, source = _fetch(chosen, set())
    if len(repos) < 2:
        shown, repos, source = _fetch([{**gh.topic_for("Python"), "skill": "Python"}], set())
    picked = _for_ai(repos)
    inp = {
        "role": profile.target_role,
        "skills": list(profile.skills),
        "gaps": gaps(profile),
        "keywords": [t["keyword"] for t in chosen],
        "repos": [r.as_dict() for r in picked],
        "based_on": based_on,
        "student_id": student_id,
    }
    if on_event:
        on_event(f"{len(picked)} repositories found ({source}); writing ideas from them")
    out = agents.project_ideas(inp, on_event)
    set_id = db.add_idea_set(
        student_id,
        json.dumps(shown),
        json.dumps([r.as_dict() for r in repos]),
        out.model_dump_json(),
        source,
        based_on,
    )
    return view(db.idea_set(student_id, set_id))


def suggest(student_id: str, on_event: OnEvent | None = None) -> dict:
    """A new set of ideas from the student's skill gaps."""
    profile = _profile(student_id)
    _limit(student_id)
    return _make(student_id, profile, topics(profile), set(), "", on_event)


def more_like(student_id: str, set_id: int, index: int, on_event: OnEvent | None = None) -> dict:
    """A new set around one idea: the topics of the repos it was built from (and its stack),
    looking past the repos already shown."""
    profile = _profile(student_id)
    row, idea = _idea(student_id, set_id, index)
    _limit(student_id)
    repos = {r["full_name"]: r for r in json.loads(row["repos_json"])}
    counts = Counter(
        t
        for d in idea["derived_from"]
        for t in repos.get(d["repo"], {}).get("topics", [])
        if t not in GENERIC_TOPICS
    )
    chosen = [
        {"topic": t, "keyword": t.replace("-", " "), "skill": ""} for t, _ in counts.most_common(2)
    ]
    for skill in idea["stack"]:
        t = gh.topic_for(skill)
        if t and all(c["topic"] != t["topic"] for c in chosen) and len(chosen) < MAX_TOPICS:
            chosen.append({**t, "skill": skill})
    chosen = chosen or topics(profile)
    based_on = f"{idea['title']} ({DERIVATION_LABELS[idea['derivation']].lower()})"
    return _make(student_id, profile, chosen, set(repos), based_on, on_event)


# --- reading and starting -------------------------------------------------------------------------


def view(row) -> dict:  # noqa: ANN001 - a project_idea_sets row
    """A stored set for display: each idea's cited repos resolved to their metadata."""
    repos = {r["full_name"]: r for r in json.loads(row["repos_json"])}
    ideas = json.loads(row["ideas_json"])["ideas"]
    for idea in ideas:
        idea["label"] = DERIVATION_LABELS[idea["derivation"]]
        for d in idea["derived_from"]:
            d["meta"] = repos.get(d["repo"])
    topics_ = json.loads(row["topics_json"])
    for t in topics_:
        for kind in LIMITS:
            t[kind] = [repos[n] for n in t.get(kind, []) if n in repos]
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "based_on": row["based_on"],
        "topics": topics_,
        "ideas": ideas,
    }


def latest(student_id: str) -> dict | None:
    _profile(student_id)
    row = db.latest_idea_set(student_id)
    return view(row) if row else None


def _idea(student_id: str, set_id: int, index: int) -> tuple:
    row = db.idea_set(student_id, set_id)
    if row is None:
        raise ServiceError("Those ideas are not yours, or no longer exist.")
    ideas = json.loads(row["ideas_json"])["ideas"]
    if not 0 <= index < len(ideas):
        raise ServiceError("No such idea.")
    return row, ideas[index]


def readme(idea: dict, repos: dict[str, dict]) -> str:
    """The new project's README, in our own words: the idea and what inspired it."""
    lines = [
        f"# {idea['title']}",
        "",
        idea["problem"],
        "",
        f"**Why it fits:** {idea['why_it_fits']}",
    ]
    lines += ["", f"**Scope:** {idea['scope_weeks']} week(s)", "", "## Milestones"]
    lines += [f"- [ ] {m}" for m in idea["milestones"]]
    if idea["stretch_goals"]:
        lines += ["", "## Stretch goals", *(f"- {s}" for s in idea["stretch_goals"])]
    lines += ["", "## Inspired by"]
    for d in idea["derived_from"]:
        url = (repos.get(d["repo"]) or {}).get("url", f"https://github.com/{d['repo']}")
        lines.append(f"- [{d['repo']}]({url}): {d['takes']} {d['differs']}")
    return "\n".join(lines)


def start(student_id: str, set_id: int, index: int) -> int:
    """Put an idea in the Project space with status "Idea"; returns the project id."""
    _profile(student_id)
    row, idea = _idea(student_id, set_id, index)
    repos = {r["full_name"]: r for r in json.loads(row["repos_json"])}
    taken = {p["name"].lower() for p in db.projects(student_id)}
    name, n = idea["title"][:72], 2
    while name.lower() in taken:
        name, n = f"{idea['title'][:72]} ({n})", n + 1
    summary = "\n".join([idea["problem"], *idea["milestones"]])
    return services.save_project(
        student_id,
        name=name,
        summary=summary[:1500],
        tech=", ".join(idea["stack"])[:200],
        status="Idea",
        readme=readme(idea, repos)[:8000],
        on_resume=False,
    )
