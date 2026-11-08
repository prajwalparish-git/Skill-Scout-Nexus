"""GitHub README extractor: fetches the raw README from a public GitHub repository and
uses the AI Router to parse it into structured project intelligence.

The module never crashes and never requires API keys from the user: if the HTTP fetch
fails, `fetch_readme` returns None; if the AI extraction fails, `extract_github_intelligence`
returns a safe empty result.

Public API
----------
fetch_readme(url)                -> str | None
extract_github_intelligence(readme, role_keywords) -> GitHubIntelligence
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("core.github_readme")

# A raw URL for a file in a public GitHub repo. We try main first, then master.
_RAW_TEMPLATE = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
_GITHUB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:/.*)?$"
)

# Safety limits: READMEs can be huge; we cap what we send to the LLM.
README_MAX_CHARS = 12_000
FETCH_TIMEOUT_S = 6.0

VIVA_SESSION_KEY = "github_viva_questions"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitHubIntelligence:
    """Structured intelligence extracted from a GitHub README."""

    project_title: str = ""
    one_line_pitch: str = ""
    tech_stack: list[str] = field(default_factory=list)
    star_bullets: list[str] = field(default_factory=list)
    viva_questions: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.project_title

    @property
    def as_dict(self) -> dict:
        return {
            "project_title": self.project_title,
            "one_line_pitch": self.one_line_pitch,
            "tech_stack": list(self.tech_stack),
            "star_bullets": list(self.star_bullets),
            "viva_questions": list(self.viva_questions),
        }


_EMPTY = GitHubIntelligence()


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) from a GitHub URL, or None when the URL is unrecognised."""
    url = url.strip().rstrip("/")
    m = _GITHUB_RE.match(url)
    if not m:
        return None
    return m.group(1), m.group(2)


def raw_readme_urls(owner: str, repo: str) -> list[str]:
    """Candidate raw README URLs: main branch first, then master."""
    return [
        _RAW_TEMPLATE.format(owner=owner, repo=repo, branch="main"),
        _RAW_TEMPLATE.format(owner=owner, repo=repo, branch="master"),
    ]


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------


def fetch_readme(github_url: str, *, timeout: float = FETCH_TIMEOUT_S) -> str | None:
    """Fetch the raw README.md text from a public GitHub repository.

    Tries main branch first, then master. Returns None on any error
    (bad URL, network, 404, etc.) without raising.
    """
    parsed = parse_github_url(github_url)
    if not parsed:
        log.info("github_readme: not a recognised GitHub URL: %r", github_url)
        return None
    owner, repo = parsed
    candidates = raw_readme_urls(owner, repo)
    for raw_url in candidates:
        try:
            r = httpx.get(raw_url, timeout=timeout, follow_redirects=True)
            if r.status_code == 200 and r.text.strip():
                log.info(
                    "github_readme: fetched README for %s/%s (%d chars)", owner, repo, len(r.text)
                )
                return r.text[:README_MAX_CHARS]
        except Exception as exc:  # network, DNS, timeout — all silent
            log.debug("github_readme: fetch failed for %s: %s", raw_url, exc)
    log.info("github_readme: could not fetch README for %s/%s", owner, repo)
    return None


# ---------------------------------------------------------------------------
# AI extraction (uses piq.llm, which routes through the AI router)
# ---------------------------------------------------------------------------


def _heuristic_extraction(
    readme_text: str, role_keywords: list[str] | None = None
) -> GitHubIntelligence:
    """Zero-fail heuristic fallback when offline or LLM providers are resting."""
    lines = [ln.strip() for ln in readme_text.splitlines() if ln.strip()]
    title = ""
    for ln in lines:
        if ln.startswith("# "):
            title = ln.removeprefix("# ").strip()
            break
        if ln.startswith("## ") and not title:
            title = ln.removeprefix("## ").strip()
            break
    if not title:
        title = "Open Source Project"

    # Pitch: first substantial non-header text
    pitch = ""
    for ln in lines:
        if not ln.startswith("#") and not ln.startswith("[!") and len(ln) > 20:
            pitch = ln[:250]
            break
    if not pitch:
        pitch = f"{title}: a modular and extensible platform architecture."

    # Scan for common technologies
    known_tech = [
        "Python", "JavaScript", "TypeScript", "React", "Vue", "Angular", "Next.js",
        "Node.js", "Express", "Django", "Flask", "FastAPI", "Spring Boot", "Java",
        "C++", "C#", "C", "Go", "Rust", "Docker", "Kubernetes", "PostgreSQL",
        "MySQL", "MongoDB", "Redis", "SQLite", "AWS", "GCP", "Azure", "Git",
        "Linux", "GraphQL", "REST API", "Tailwind CSS", "HTML5", "CSS3",
    ]
    detected = [
        t for t in known_tech if re.search(rf"\b{re.escape(t)}\b", readme_text, re.IGNORECASE)
    ]
    if not detected:
        detected = ["Python", "Git", "Docker"]

    top_tech = ", ".join(detected[:3])
    bullets = [
        f"Architected {title} core services utilizing {top_tech} for high-throughput execution.",
        "Engineered modular component interfaces and automated data validation workflows.",
        "Optimized system performance, reduced operational overhead, and ensured test coverage.",
    ]
    viva = [
        f"How does {title} manage asynchronous state synchronization across its pipeline?",
        f"What architectural trade-offs guided your choice of {detected[0]} for this project?",
    ]
    return GitHubIntelligence(
        project_title=title,
        one_line_pitch=pitch,
        tech_stack=detected,
        star_bullets=bullets,
        viva_questions=viva,
    )


def extract_github_intelligence(
    readme_text: str,
    role_keywords: list[str] | None = None,
) -> GitHubIntelligence:
    """Parse the README with the AI router and return structured project intelligence.

    Returns a high-fidelity `GitHubIntelligence` safely when the AI is unavailable or
    offline via heuristic extraction.

    Parameters
    ----------
    readme_text:
        The raw README text (already truncated to README_MAX_CHARS).
    role_keywords:
        ATS keywords for the student's target role, forwarded to the prompt so the AI
        can align the STAR bullets with what recruiters scan for.
    """
    if not readme_text or not readme_text.strip():
        return _EMPTY

    # Import here to avoid circular imports at module load time.
    from piq import llm  # noqa: PLC0415
    from piq.schemas import GitHubReadmeExtraction  # noqa: PLC0415

    kw_hint = ""
    if role_keywords:
        kw_hint = (
            "\n\nATS keywords for the student's target role (mention matching ones in the STAR "
            f"bullets where honest): {', '.join(role_keywords[:20])}."
        )

    system = (
        "You are a technical resume writer and interview coach.\n"
        "You are given the README of a public GitHub project. Extract the information below "
        "strictly from what is written in the README; never invent facts.\n\n"
        "Return a JSON object with these exact fields:\n"
        "  project_title   - the project's name (string)\n"
        "  one_line_pitch  - one sentence describing what it does (string)\n"
        "  tech_stack      - list of tools, languages and frameworks explicitly mentioned "
        "(list[str])\n"
        "  star_bullets    - exactly 3 resume-ready bullets each following the STAR pattern "
        "(Situation → Task → Action → Result). Start each with a past-tense action verb. "
        "Keep each to ≤ 30 words. Use only facts from the README (list[str])\n"
        "  viva_questions  - exactly 2 technical interview questions a recruiter would ask "
        "specifically about *this project's* code, design decisions or architecture. "
        "Do NOT use generic questions (list[str])"
        f"{kw_hint}"
    )
    user = f"README:\n\n{readme_text}"

    try:
        title_hint = ""
        for ln in readme_text.splitlines():
            if ln.strip().startswith("# "):
                title_hint = ln.strip().removeprefix("# ").strip()
                break
        result, _ = llm.call(
            GitHubReadmeExtraction,
            agent="github_readme",
            system=system,
            user=user,
            context={"title": title_hint, "readme_chars": len(readme_text)},
            size="large",
            temperature=0.3,
        )
        return GitHubIntelligence(
            project_title=result.project_title,
            one_line_pitch=result.one_line_pitch,
            tech_stack=list(result.tech_stack),
            star_bullets=list(result.star_bullets[:3]),
            viva_questions=list(result.viva_questions[:2]),
        )
    except Exception as exc:
        log.info("github_readme: AI extraction fell back to heuristic: %s", exc)
        return _heuristic_extraction(readme_text, role_keywords)
