"""Layer 3, speech router: speak a text with the best voice available, never raising.

1. ElevenLabs (ELEVENLABS_API_KEY; ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL optional) returns
   MP3 bytes the page plays with st.audio.
2. Otherwise the browser's own voice (Web Speech API): `browser_speech_html` builds a button
   that reads the text aloud in the student's browser. Nothing leaves the machine, so it also
   works offline.

pyttsx3 is deliberately not used: it speaks through the server's sound card, which in a web
app is not the student's, and it would add a dependency.

ElevenLabs sits behind the same kind of circuit breaker as the AI providers: an outage, a 429
or a refused key pauses it, and the browser voice answers in the meantime. Every clip it makes
is kept in AUDIO_CACHE_DIR (default data/.audio_cache/<sha256>.mp3, git-ignored), keyed by the
text, voice and model, so the same question is never synthesised (or paid for) twice.

No key is ever asked for: ELEVENLABS_API_KEY is read from .env or the browser voice is used,
with nothing shown to the student but the play button.
"""

import hashlib
import html
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from core.ai_router import CircuitBreaker, _http, _retry_after
from piq.config import (
    BRAND_COLOR,
    BROWSER_VOICE_LANG,
    ELEVENLABS_DEFAULT_VOICE,
    PALETTE,
    ROUTER_BROKEN_COOLDOWN_S,
    TTS_MAX_CHARS,
    TTS_TIMEOUT_S,
    settings,
)

log = logging.getLogger("core.speech_router")
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
Source = Literal["elevenlabs", "browser"]
_breaker = CircuitBreaker()


@dataclass(frozen=True)
class Speech:
    text: str  # what is spoken (cut to TTS_MAX_CHARS)
    source: Source
    audio: bytes | None = None  # MP3 when source is "elevenlabs"
    detail: str = ""  # why the browser voice is used


def reset() -> None:
    """Close the ElevenLabs breaker (tests; or after fixing .env)."""
    _breaker.success()


def clip(text: str) -> str:
    """Whitespace collapsed, and cut at the last full sentence within TTS_MAX_CHARS."""
    text = " ".join(text.split())
    if len(text) <= TTS_MAX_CHARS:
        return text
    cut = text[:TTS_MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end > 0 else cut


def elevenlabs_unavailable() -> str:
    """Why ElevenLabs cannot speak now ('' = it can)."""
    if not settings().elevenlabs_api_key:
        return "ELEVENLABS_API_KEY is not set"
    if not _breaker.allow():
        return f"ElevenLabs paused for {_breaker.retry_in():.0f} s: {_breaker.reason}"
    return ""


def _elevenlabs(text: str) -> bytes:
    s = settings()
    body: dict = {"text": text, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    if s.elevenlabs_model:  # unset: ElevenLabs uses its default model
        body["model_id"] = s.elevenlabs_model
    try:
        r = _http().post(
            ELEVENLABS_URL.format(voice=s.elevenlabs_voice_id or ELEVENLABS_DEFAULT_VOICE),
            json=body,
            headers={"xi-api-key": s.elevenlabs_api_key, "Accept": "audio/mpeg"},
            timeout=TTS_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        _breaker.failure(f"unreachable ({type(e).__name__})")
        raise
    if r.status_code == 429:
        _breaker.failure("rate limit", retry_after=_retry_after(r.headers), rate_limited=True)
    elif r.status_code in (401, 403):  # a bad key or used-up quota will not heal in a minute
        _breaker.failure(f"refused (HTTP {r.status_code})", cooldown=ROUTER_BROKEN_COOLDOWN_S)
    elif r.status_code >= 400:
        _breaker.failure(f"HTTP {r.status_code}")
    elif not r.content:
        _breaker.failure("empty audio")
    else:
        _breaker.success()
        return r.content
    raise RuntimeError(f"ElevenLabs answered HTTP {r.status_code}")


def audio_path(text: str) -> Path:
    """Where the clip for `text` in the configured voice and model is cached."""
    s = settings()
    voice = s.elevenlabs_voice_id or ELEVENLABS_DEFAULT_VOICE
    digest = hashlib.sha256(f"{voice}\n{s.elevenlabs_model}\n{text}".encode()).hexdigest()
    return s.audio_cache_dir / f"{digest}.mp3"


def _store(path: Path, audio: bytes) -> None:
    """Write the clip atomically; a failed write only costs the cache, never the audio."""
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Audio cache could not be written to %s: %s", path, e)
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def needs_synthesis(text: str) -> bool:
    """Would `synthesize(text)` call ElevenLabs? (A key is set, it is not paused and the clip
    is not cached yet.) The preloader warms only these."""
    spoken = clip(text)
    return bool(spoken) and not elevenlabs_unavailable() and not audio_path(spoken).is_file()


def synthesize(text: str, *, network: bool = True) -> Speech:
    """Cached or fresh ElevenLabs audio when a key is set, else a Speech the page renders with
    the browser voice. Never raises, never asks for anything. `network=False`: a cached clip or
    the browser voice, never a request (a preload is already synthesising this text)."""
    spoken = clip(text)
    if not spoken:
        return Speech(spoken, "browser", None, "nothing to say")
    if settings().elevenlabs_api_key:
        path = audio_path(spoken)
        try:
            if path.is_file():  # served even while ElevenLabs itself is paused
                return Speech(spoken, "elevenlabs", path.read_bytes())
        except OSError:
            pass
    if not network:
        return Speech(spoken, "browser", None, "the clip is still being prepared")
    why = elevenlabs_unavailable()
    if not why:
        try:
            audio = _elevenlabs(spoken)
            _store(audio_path(spoken), audio)
            return Speech(spoken, "elevenlabs", audio)
        except Exception as e:  # the student still hears the question
            log.info("ElevenLabs failed (%s); the browser voice takes over", e)
            why = f"ElevenLabs failed: {e}"
    return Speech(spoken, "browser", None, why)


def active_voice() -> str:
    return "ElevenLabs" if not elevenlabs_unavailable() else "Browser voice"


def _js_string(text: str) -> str:
    """A JavaScript string literal that cannot end the <script> element or the attribute."""
    return json.dumps(text).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def browser_speech_html(text: str, label: str = "Read the question aloud") -> str:
    """A self-contained page (for st.components.v1.html) with one button that speaks `text`
    through the Web Speech API, and says so in words when the browser has no voice."""
    light, dark = PALETTE["light"], PALETTE["dark"]
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  /* An iframe cannot read the Streamlit theme: the same tokens, picked by the OS scheme. */
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; font: 16px system-ui, sans-serif; color: {light["text"]}; }}
  button {{ background: {light["primary"]}; color: #fff; border: 0; border-radius: 8px;
           padding: 8px 16px; font: inherit; font-weight: 600; cursor: pointer; }}
  button:focus-visible {{ outline: 3px solid {BRAND_COLOR}; outline-offset: 2px; }}
  #note {{ margin-left: 12px; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: {dark["text"]}; }}
    button {{ background: {dark["primary"]}; }}
  }}
</style></head><body>
<button type="button" id="speak" aria-describedby="note">{html.escape(label)}</button>
<span id="note" role="status"></span>
<script>
  const text = {_js_string(text)};
  const note = document.getElementById("note");
  document.getElementById("speak").addEventListener("click", () => {{
    if (!("speechSynthesis" in window)) {{
      note.textContent = "This browser cannot speak; read the question below.";
      return;
    }}
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "{BROWSER_VOICE_LANG}";
    u.onstart = () => {{ note.textContent = "Speaking"; }};
    u.onend = () => {{ note.textContent = ""; }};
    window.speechSynthesis.speak(u);
  }});
</script></body></html>"""
