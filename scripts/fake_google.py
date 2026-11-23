"""A stand-in for Google's OAuth and Drive endpoints, for offline checks (scripts/ci_check.py)
and trying the Drive feature without a Google account. Never used by the app itself.

    fake = FakeGoogle(); fake.install()     # core.drive now talks to the fake
    code = fake.consent(auth_url)            # what Google's consent page would hand back

It checks what Google checks: the client, the PKCE verifier against the challenge, the redirect
URI against the one in the sign-in, bearer tokens, and revoked refresh tokens.
"""

import base64
import hashlib
import json
import secrets
from email.parser import BytesParser
from email.policy import HTTP
from urllib.parse import parse_qs, urlsplit

import httpx

from core import drive


class FakeGoogle:
    def __init__(self, client_id: str = "ci-client", client_secret: str = "ci-secret") -> None:
        self.client_id, self.client_secret = client_id, client_secret
        self.grant_scope = drive.SCOPE  # set to something broader to test the refusal
        self.codes: dict[str, dict] = {}
        self.refresh: dict[str, bool] = {}  # refresh token -> still valid
        self.access: set[str] = set()
        self.revoked: list[str] = []
        self.files: dict[str, dict] = {}  # id -> {name, mime, parents, data, trashed}
        self.calls: list[tuple[str, str]] = []

    # --- wiring ---------------------------------------------------------------------------

    def install(self) -> None:
        drive._client.cache_clear()
        transport = httpx.MockTransport(self.handle)
        client = httpx.Client(transport=transport, follow_redirects=False)
        drive._client = lambda: client  # type: ignore[assignment]

    @staticmethod
    def uninstall() -> None:
        import importlib

        importlib.reload(drive)

    def consent(self, auth_url: str) -> str:
        """The code Google's consent page returns for this sign-in address."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(auth_url).query).items()}
        assert q["client_id"] == self.client_id and q["code_challenge_method"] == "S256"
        code = "4/" + secrets.token_urlsafe(12)
        self.codes[code] = {
            "challenge": q["code_challenge"],
            "redirect_uri": q["redirect_uri"],
            "scope": q["scope"],
        }
        return code

    def folder_named(self, name: str) -> list[str]:
        return [
            i for i, f in self.files.items() if f["name"] == name and f["mime"] == drive.FOLDER_MIME
        ]

    # --- the endpoints -----------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        self.calls.append((request.method, url))
        if url == drive.TOKEN_URL:
            return self._token(dict(parse_qs(request.content.decode())))
        if url == drive.REVOKE_URL:
            token = parse_qs(request.content.decode()).get("token", [""])[0]
            self.revoked.append(token)
            self.refresh[token] = False
            return httpx.Response(200)
        auth = request.headers.get("authorization", "")
        if auth.removeprefix("Bearer ") not in self.access:
            return httpx.Response(401, json={"error": {"message": "invalid credentials"}})
        if url == drive.UPLOAD_URL and request.method == "POST":
            return self._upload(request)
        if url == drive.FILES_URL and request.method == "POST":
            body = json.loads(request.content)
            fid = self._new_id()
            self.files[fid] = {
                "name": body["name"],
                "mime": body["mimeType"],
                "parents": body.get("parents", []),
                "data": b"",
                "trashed": False,
            }
            return httpx.Response(200, json={"id": fid})
        if url.startswith(drive.FILES_URL + "/"):
            fid = url.rsplit("/", 1)[1]
            f = self.files.get(fid)
            if f is None:
                return httpx.Response(404, json={"error": {"message": "File not found"}})
            if request.method == "PATCH":
                f["trashed"] = bool(json.loads(request.content).get("trashed"))
                return httpx.Response(200, json={"id": fid})
            if request.url.params.get("alt") == "media":
                return httpx.Response(200, content=f["data"])
            return httpx.Response(200, json={"id": fid, "trashed": f["trashed"]})
        return httpx.Response(404, json={"error": {"message": "unknown endpoint"}})

    def _new_id(self) -> str:
        return "f" + secrets.token_urlsafe(16).replace("-", "a").replace("_", "b")

    def _issue_access(self) -> str:
        token = "ya29." + secrets.token_urlsafe(16)
        self.access.add(token)
        return token

    def _token(self, form: dict[str, list[str]]) -> httpx.Response:
        f = {k: v[0] for k, v in form.items()}
        if f.get("client_id") != self.client_id or f.get("client_secret") != self.client_secret:
            return httpx.Response(401, json={"error": "invalid_client"})
        if f.get("grant_type") == "authorization_code":
            grant = self.codes.pop(f.get("code", ""), None)
            if grant is None or grant["redirect_uri"] != f.get("redirect_uri"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(f.get("code_verifier", "").encode()).digest()
                )
                .decode()
                .rstrip("=")
            )
            if challenge != grant["challenge"]:
                return httpx.Response(
                    400, json={"error": "invalid_grant", "error_description": "PKCE"}
                )
            refresh = "1//" + secrets.token_urlsafe(24)
            self.refresh[refresh] = True
            return httpx.Response(
                200,
                json={
                    "access_token": self._issue_access(),
                    "refresh_token": refresh,
                    "expires_in": 3599,
                    "scope": self.grant_scope,
                    "token_type": "Bearer",
                },
            )
        if f.get("grant_type") == "refresh_token":
            if not self.refresh.get(f.get("refresh_token", "")):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(
                200, json={"access_token": self._issue_access(), "expires_in": 3599}
            )
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
        message = BytesParser(policy=HTTP).parsebytes(head + request.content)
        meta_part, data_part = list(message.iter_parts())
        meta = json.loads(meta_part.get_content())
        fid = self._new_id()
        self.files[fid] = {
            "name": meta["name"],
            "mime": meta.get("mimeType", "application/pdf"),
            "parents": meta.get("parents", []),
            "data": data_part.get_payload(decode=True),
            "trashed": False,
        }
        return httpx.Response(
            200, json={"id": fid, "webViewLink": f"https://drive.google.com/file/d/{fid}/view"}
        )
