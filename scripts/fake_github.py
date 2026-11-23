"""A stand-in for GitHub's Search API, for offline checks (scripts/ci_check.py). Never used by
the app itself.

    fake = FakeGitHub(); fake.install()      # core.github_search now talks to the fake
    fake.rate_limit = "403"                  # the next search answers 403, no requests left

Its results carry fields the app must NOT keep (a README-like body, the owner's email, the
clone URLs) so a check can prove only the whitelist is stored. It records every request path:
a call to anything but /search/repositories (a README, a file) is a failure.
"""

import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from core import github_search

README_MARK = "FAKE-README-TEXT-must-never-be-stored"


def item(
    full_name: str,
    owner_type: str = "Organization",
    topics: tuple[str, ...] = (),
    stars: int = 500,
    licence: str | None = "MIT",
    language: str = "Python",
) -> dict:
    owner = full_name.split("/")[0]
    return {
        "full_name": full_name,
        "name": full_name.split("/")[1],
        "owner": {"login": owner, "type": owner_type, "email": f"{owner}@example.com"},
        "description": f"{full_name.split('/')[1]} does something useful for {', '.join(topics)}",
        "stargazers_count": stars,
        "language": language,
        "topics": list(topics),
        "license": {"spdx_id": licence} if licence else None,
        "html_url": f"https://github.com/{full_name}",
        "pushed_at": "2026-10-01T10:00:00Z",
        "clone_url": f"https://github.com/{full_name}.git",
        "readme": README_MARK,  # not a real search field: the app must drop it
        "body": README_MARK,
    }


class FakeGitHub:
    def __init__(self) -> None:
        self.calls: list[str] = []  # request path + query
        self.paths: list[str] = []
        self.rate_limit: str = ""  # "403" or "429": the next search answers so, once
        self.retry_after = 120
        self.repos: dict[str, list[dict]] = {}  # topic -> items

    def add(self, topic: str, *items: dict) -> None:
        self.repos.setdefault(topic, []).extend(items)

    def install(self) -> None:
        transport = httpx.MockTransport(self.handle)
        github_search._client = lambda: httpx.Client(transport=transport)  # type: ignore[assignment]

    @staticmethod
    def uninstall() -> None:
        import importlib

        importlib.reload(github_search)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        self.paths.append(url.path)
        q = parse_qs(url.query).get("q", [""])[0]
        self.calls.append(q)
        if url.path != "/search/repositories":
            return httpx.Response(404, json={"message": "Not Found"})
        if self.rate_limit == "403":
            self.rate_limit = ""
            reset = str(int(time.time()) + self.retry_after)
            return httpx.Response(
                403,
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset},
                json={"message": "API rate limit exceeded"},
            )
        if self.rate_limit == "429":
            self.rate_limit = ""
            return httpx.Response(
                429, headers={"retry-after": str(self.retry_after)}, json={"message": "slow"}
            )
        topic = m.group(1) if (m := re.search(r"topic:([\w.-]+)", q)) else ""
        found = list(self.repos.get(topic, []))
        orgs = re.findall(r"org:([\w.-]+)", q)
        if orgs:
            found = [i for i in found if i["owner"]["login"].lower() in orgs]
        if "hackathon" in q.split():
            found = [i for i in found if "hackathon" in i["topics"]]
        return httpx.Response(200, json={"total_count": len(found), "items": found})
