"""Which device a sign-in comes from: a random per-browser id (a cookie), the browser and OS read
from the User-Agent, the IP, and a location when the host's proxy supplies one.

The location is never looked up from an outside service: it comes only from headers that a host
such as Vercel or Cloudflare adds (city, region, country), so offline and on a laptop it is simply
unknown. Nothing here needs a dependency.
"""

import hashlib
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import unquote

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

# Most specific first: Edge and Opera also say "Chrome", Chrome also says "Safari".
_BROWSERS = (
    ("Edge", r"Edg(?:e|A|iOS)?/([\d.]+)"),
    ("Opera", r"(?:OPR|Opera)/([\d.]+)"),
    ("Samsung Internet", r"SamsungBrowser/([\d.]+)"),
    ("Firefox", r"(?:Firefox|FxiOS)/([\d.]+)"),
    ("Chrome", r"(?:Chrome|CriOS)/([\d.]+)"),
    ("Safari", r"Version/([\d.]+).*Safari/"),
)
_OSES = (
    ("iOS", r"(?:iPhone|iPad|iPod).*?OS ([\d_]+)"),
    ("Android", r"Android ([\d.]+)"),
    ("ChromeOS", r"CrOS"),
    ("Windows", r"Windows NT ([\d.]+)"),
    ("macOS", r"Mac OS X ([\d_.]+)"),
    ("Linux", r"Linux"),
)
_WINDOWS = {"10.0": "10/11", "6.3": "8.1", "6.2": "8", "6.1": "7"}


def new_id() -> str:
    return secrets.token_urlsafe(24)


def valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def id_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode()).hexdigest() if device_id else ""


def browser(ua: str) -> str:
    for name, pattern in _BROWSERS:
        if m := re.search(pattern, ua or ""):
            return f"{name} {m.group(1).split('.')[0]}"
    return "Unknown browser"


def os_name(ua: str) -> str:
    for name, pattern in _OSES:
        if m := re.search(pattern, ua or ""):
            if not m.groups():
                return name
            version = m.group(1).replace("_", ".")
            if name == "Windows":
                return f"Windows {_WINDOWS.get(version, version)}"
            return f"{name} {'.'.join(version.split('.')[:2])}"
    return "Unknown OS"


def location(headers: Mapping[str, str]) -> str:
    """City, region, country from the host's proxy headers; "" when it adds none."""

    def h(name: str) -> str:
        return unquote(headers.get(name) or headers.get(name.title()) or "").strip()

    city = h("x-vercel-ip-city") or h("cf-ipcity")
    region = h("x-vercel-ip-country-region") or h("cf-region")
    country = h("x-vercel-ip-country") or h("cf-ipcountry")
    if country in {"XX", "T1"}:  # Cloudflare: unknown, Tor
        country = ""
    return ", ".join(p for p in (city, region, country) if p)


def client_ip(headers: Mapping[str, str], fallback: str = "") -> str:
    forwarded = (headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or "").split(",")
    return forwarded[0].strip() or (headers.get("x-real-ip") or "").strip() or fallback


@dataclass(frozen=True)
class Device:
    device_id: str = ""  # the browser's cookie value ("" when it has none)
    user_agent: str = ""
    ip: str = ""
    location: str = ""

    @property
    def browser(self) -> str:
        return browser(self.user_agent)

    @property
    def os(self) -> str:
        return os_name(self.user_agent)

    @property
    def hash(self) -> str:
        return id_hash(self.device_id)

    def describe(self) -> str:
        return f"{self.browser} on {self.os}"


def from_headers(headers: Mapping[str, str], device_id: str, peer_ip: str = "") -> Device:
    ua = headers.get("user-agent") or headers.get("User-Agent") or ""
    return Device(device_id, ua[:400], client_ip(headers, peer_ip), location(headers))
