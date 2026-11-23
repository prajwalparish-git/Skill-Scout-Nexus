"""Project inspiration from GitHub's official REST Search API (repositories), metadata only.

Only `GET /search/repositories` is called: never a README, a file or any code. Each result
keeps a whitelist of fields (name, owner, a one-line description, stars, language, topics,
licence, link, last push) and drops the rest. "Built by a company" means the owner is a GitHub
Organization on data/company_orgs.json.

Results are cached per query for CACHE_TTL_S (data in the app database), so students share
them and the rate limit holds. A 403 with no requests left, or a 429, blocks further calls until
GitHub's reset (Retry-After / X-RateLimit-Reset); meanwhile, and when the network or the token
fails, answers come from the stale cache, then from the committed seed
(data/project_inspiration_seed.json). MOCK_MODE uses the seed only, without a network call.
GITHUB_TOKEN raises the limit; without it the API still works at its lower limit.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

import httpx

from piq import db
from piq.config import DATA_DIR, settings

log = logging.getLogger("core.github_search")

COMPANY_ORGS = DATA_DIR / "company_orgs.json"
TOPICS = DATA_DIR / "github_topics.json"
SEED = DATA_DIR / "project_inspiration_seed.json"
CACHE_TTL_S = 24 * 3600
DEFAULT_BLOCK_S = 60
TIMEOUT_S = 8.0
PER_PAGE = 20
DESCRIPTION_MAX = 160
TOPICS_MAX = 8
QUERY_MAX = 250  # GitHub refuses longer search queries (256)
ACTIVE_MONTHS = 18
FIELDS = (  # everything a Repo keeps: nothing else from GitHub is stored
    "full_name", "owner", "owner_is_org", "company", "description", "stars", "language",
    "topics", "licence", "url", "pushed_at",
)  # fmt: skip

Kind = Literal["popular", "company", "hackathon"]
Source = Literal["live", "cache", "seed"]


@dataclass(frozen=True)
class Repo:
    full_name: str
    owner: str
    owner_is_org: bool
    company: str  # the company's name when the owner is a listed organization, else ""
    description: str
    stars: int
    language: str
    topics: tuple[str, ...]
    licence: str  # SPDX id, or "" when the repo states none
    url: str
    pushed_at: str  # YYYY-MM-DD

    def as_dict(self) -> dict:
        d = asdict(self)
        d["topics"] = list(self.topics)
        return d

    @staticmethod
    def from_dict(d: dict) -> Repo:
        return Repo(**{k: (tuple(d[k]) if k == "topics" else d[k]) for k in FIELDS})


@dataclass(frozen=True)
class Found:
    topic: str
    kind: Kind
    repos: list[Repo]
    source: Source
    queries: list[str] = field(default_factory=list)


class Unavailable(Exception):
    """GitHub could not answer now (blocked, offline, an error): use the cache or the seed."""


# --- the curated lists -----------------------------------------------------------------------


@lru_cache(maxsize=1)
def company_orgs() -> dict[str, str]:
    """Company organization login (lower-case) -> name shown."""
    return json.loads(COMPANY_ORGS.read_text(encoding="utf-8"))["orgs"]


@lru_cache(maxsize=1)
def skill_topics() -> dict[str, dict | None]:
    return json.loads(TOPICS.read_text(encoding="utf-8"))["skills"]


@lru_cache(maxsize=1)
def seed() -> dict[str, dict[str, list[dict]]]:
    """topic -> kind -> repo dicts (metadata only), curated through the same API."""
    if not SEED.is_file():
        return {}
    return json.loads(SEED.read_text(encoding="utf-8"))["topics"]


def clear_cache() -> None:
    company_orgs.cache_clear()
    skill_topics.cache_clear()
    seed.cache_clear()


# --- parsing: the whitelist ---------------------------------------------------------------------


def _one_line(text: str | None) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= DESCRIPTION_MAX else line[: DESCRIPTION_MAX - 1].rstrip() + "…"


def to_repo(item: dict) -> Repo | None:
    """A search result as a Repo: the whitelisted fields only (None when it is malformed)."""
    owner = item.get("owner") or {}
    login = str(owner.get("login") or "")
    full_name = str(item.get("full_name") or "")
    url = str(item.get("html_url") or "")
    if not login or "/" not in full_name or not url.startswith("https://github.com/"):
        return None
    is_org = owner.get("type") == "Organization"
    licence = (item.get("license") or {}).get("spdx_id") or ""
    return Repo(
        full_name=full_name,
        owner=login,
        owner_is_org=is_org,
        company=company_orgs().get(login.lower(), "") if is_org else "",
        description=_one_line(item.get("description")),
        stars=int(item.get("stargazers_count") or 0),
        language=str(item.get("language") or ""),
        topics=tuple(str(t) for t in (item.get("topics") or [])[:TOPICS_MAX]),
        licence="" if licence == "NOASSERTION" else str(licence),
        url=url,
        pushed_at=str(item.get("pushed_at") or "")[:10],
    )


# --- queries ------------------------------------------------------------------------------------


def _since(today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=ACTIVE_MONTHS * 30)).isoformat()


def queries(topic: str, kind: Kind, today: date | None = None) -> list[str]:
    """The search queries for a topic and kind. popular: active, starred repos; hackathon: the
    word "hackathon" in a repo's name, description or topics (Devpost and Devfolio projects are
    usually tagged so); company: org qualifiers in chunks that keep each query under GitHub's
    length limit (the chunks are ORed by GitHub within a query)."""
    active = f"topic:{topic} pushed:>{_since(today)}"
    if kind == "popular":
        return [f"{active} stars:>50"]
    if kind == "hackathon":
        return [f"topic:{topic} hackathon"]
    base = f"topic:{topic}"  # no date: more room for organizations
    out, chunk = [], base
    active = base
    for login in company_orgs():
        part = f" org:{login}"
        if len(chunk) + len(part) > QUERY_MAX:
            out.append(chunk)
            chunk = active
        chunk += part
    if chunk != active:
        out.append(chunk)
    return out


# --- rate limits: backoff ---------------------------------------------------------------------


def blocked_for(now: float | None = None) -> float:
    """Seconds GitHub asked us to wait (0 when calls may go out)."""
    until = db.kv_get("github_blocked_until")
    left = float(until or 0) - (now if now is not None else time.time())
    return max(0.0, left)


def block_seconds(headers: httpx.Headers, now: float | None = None) -> float:
    """How long a rate-limited answer asks us to wait: Retry-After, else X-RateLimit-Reset,
    else DEFAULT_BLOCK_S."""
    now = now if now is not None else time.time()
    if (after := headers.get("retry-after", "")).strip().isdigit():
        return float(after)
    if (reset := headers.get("x-ratelimit-reset", "")).strip().isdigit():
        return max(1.0, float(reset) - now)
    return float(DEFAULT_BLOCK_S)


def _rate_limited(r: httpx.Response) -> bool:
    """429, or 403 with no requests left or a Retry-After (GitHub's secondary limit)."""
    return r.status_code == 429 or (
        r.status_code == 403
        and (r.headers.get("x-ratelimit-remaining", "") == "0" or "retry-after" in r.headers)
    )


# --- HTTP ---------------------------------------------------------------------------------------


def _client() -> httpx.Client:
    """The HTTP client (checks replace it with a fake GitHub)."""
    return httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skill-scout-nexus-project-ideas",
    }
    if token := settings().github_token:
        h["Authorization"] = f"Bearer {token}"
    return h


def search(query: str, sort: str = "stars") -> list[Repo]:
    """One live search. Raises Unavailable (and records a block when rate-limited)."""
    if (wait := blocked_for()) > 0:
        raise Unavailable(f"GitHub asked us to wait {int(wait)} s")
    url = f"{settings().github_api_url}/search/repositories"
    params = {"q": query, "sort": sort, "order": "desc", "per_page": PER_PAGE}
    try:
        with _client() as c:
            r = c.get(url, params=params, headers=_headers())
    except httpx.HTTPError as e:
        raise Unavailable(f"GitHub unreachable: {type(e).__name__}") from e
    if _rate_limited(r):
        wait = block_seconds(r.headers)
        db.kv_set("github_blocked_until", str(time.time() + wait))
        log.info("GitHub rate limit: waiting %.0f s", wait)
        raise Unavailable("GitHub rate limit")
    if r.status_code != 200:
        raise Unavailable(f"GitHub answered {r.status_code}")
    try:
        items = r.json().get("items") or []
    except ValueError as e:
        raise Unavailable("GitHub sent no JSON") from e
    return [repo for item in items if isinstance(item, dict) and (repo := to_repo(item))]


# --- cache --------------------------------------------------------------------------------------


def _cached(key: str) -> tuple[list[Repo], float] | None:
    row = db.github_cache_get(key)
    if row is None:
        return None
    return [Repo.from_dict(d) for d in json.loads(row["payload_json"])], row["fetched_at"]


def _filter(kind: Kind, repos: list[Repo], exclude: set[str]) -> list[Repo]:
    seen: set[str] = set()
    out = []
    for r in repos:
        if r.full_name in seen or r.full_name in exclude:
            continue
        if kind == "company" and not r.company:  # an org on the list, never a namesake user
            continue
        if kind in ("popular", "company") and not r.licence:
            continue
        seen.add(r.full_name)
        out.append(r)
    return out


def _from_seed(topic: str, kind: Kind) -> list[Repo]:
    return [Repo.from_dict(d) for d in seed().get(topic, {}).get(kind, [])]


def find(topic: str, kind: Kind, exclude: set[str] | None = None, limit: int = 6) -> Found:
    """Repos for a topic and kind: a fresh cache entry, else a live search (then cached), else
    the stale cache entry, else the seed. `exclude`: repos already shown (More like this looks
    further)."""
    exclude = exclude or set()
    qs = queries(topic, kind)
    if settings().mock_mode:
        repos = _filter(kind, _from_seed(topic, kind), exclude)[:limit]
        return Found(topic, kind, repos, "seed", qs)
    now = time.time()
    repos: list[Repo] = []
    live = False
    for q in qs:
        hit = _cached(q)
        if hit and now - hit[1] < CACHE_TTL_S:
            repos += hit[0]
            continue
        try:
            fetched = search(q)
        except Unavailable as e:
            log.info("project inspiration %r: %s", q, e)
            repos += hit[0] if hit else []
            continue
        db.github_cache_put(q, json.dumps([r.as_dict() for r in fetched]), now)
        repos += fetched
        live = True
    picked = _filter(kind, repos, exclude)[:limit]
    if picked:
        return Found(topic, kind, picked, "live" if live else "cache", qs)
    repos = _filter(kind, _from_seed(topic, kind), exclude)[:limit]
    return Found(topic, kind, repos, "seed", qs)


# --- topics from a student's skills -------------------------------------------------------------


def topic_for(skill: str) -> dict | None:
    """{topic, keyword} for a skill, or None (no project topic, or an unknown skill)."""
    found = skill_topics().get(skill)
    if found is None:
        norm = re.sub(r"[^a-z0-9]+", "", skill.lower())
        found = next(
            (v for k, v in skill_topics().items()
             if v and re.sub(r"[^a-z0-9]+", "", k.lower()) == norm),
            None,
        )  # fmt: skip
    return found
