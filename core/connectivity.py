"""Layer 3, connectivity: is the internet reachable right now?

The voice paths (speech synthesis, transcription) ask before they touch a cloud provider, so a
machine with no network goes straight to its local tiers (pyttsx3, faster-whisper, Ollama's
text) instead of waiting for each cloud timeout in turn. The verdict is reused for
NET_PROBE_TTL_S seconds; a failed probe costs at most PROBE_TIMEOUT_S once per window.
Never raises.
"""

from __future__ import annotations

import socket
import threading
import time

from piq.config import NET_PROBE_TTL_S

PROBE_TIMEOUT_S = 0.6
# Plain TCP connects (no payload). Hostnames first: they are what the app really calls, and a
# network that blocks raw-IP connections (some campus/proxy setups) still lets these through.
PROBE_HOSTS = (
    ("generativelanguage.googleapis.com", 443),
    ("api.groq.com", 443),
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
)

_lock = threading.Lock()
_verdict: tuple[float, bool] | None = None


def reset() -> None:
    """Forget the cached verdict (tests, or after the user reconnects)."""
    global _verdict
    with _lock:
        _verdict = None


def _probe() -> bool:
    for host in PROBE_HOSTS:
        try:
            with socket.create_connection(host, timeout=PROBE_TIMEOUT_S):
                return True
        except OSError:
            continue
    return False


def online() -> bool:
    """True when a public host accepts a TCP connection (cached for NET_PROBE_TTL_S)."""
    global _verdict
    now = time.monotonic()
    with _lock:
        if _verdict and now - _verdict[0] < NET_PROBE_TTL_S:
            return _verdict[1]
    result = _probe()
    with _lock:
        _verdict = (time.monotonic(), result)
    return result
