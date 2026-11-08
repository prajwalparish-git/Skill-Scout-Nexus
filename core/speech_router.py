"""Layer 3, speech router: 4-Tier Zero-Fail Voice Synthesis Cascade with automatic caching.

Tiers:
1. ElevenLabs (ELEVENLABS_API_KEY; ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL optional, Timeout: 2.5s)
   Returns MP3 bytes.
2. Gemini TTS (GEMINI_API_KEYS with load balancer / key pool, Timeout: 2.5s)
   Generates speech via Google's Gemini audio modality (PCM/WAV or MP3).
3. Local OS Voice (pyttsx3)
   Runs in background thread at 160wpm with clear system voice to produce a local .wav file.
4. Browser Web Speech API
   If server-side pyttsx3 fails or is unavailable, returns a flag (trigger_browser_speech=True)
   to trigger window.speechSynthesis.speak() via JavaScript.

Automatic Caching:
Cached clips are stored in AUDIO_CACHE_DIR (data/.audio_cache/<sha256>.mp3 or .wav).
If a clip already exists for the text, it is returned immediately without contacting any API
or invoking pyttsx3.

Never crashes, never raises, and never asks for API keys in the UI.
"""

from __future__ import annotations

import base64
import concurrent.futures
import contextlib
import hashlib
import html
import io
import json
import logging
import os
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from core.ai_router import CircuitBreaker, _excerpt, _http, _retry_after, key_pool
from core.key_pool import KeyPoolManager
from piq.config import (
    BRAND_COLOR,
    BROWSER_VOICE_LANG,
    ELEVENLABS_DEFAULT_VOICE,
    PALETTE,
    ROUTER_BROKEN_COOLDOWN_S,
    TTS_MAX_CHARS,
    settings,
)

log = logging.getLogger("core.speech_router")

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

ELEVENLABS_TIMEOUT_S = 2.5
GEMINI_TTS_TIMEOUT_S = 2.5
PYTTSX3_TIMEOUT_S = 3.0

Source = Literal["elevenlabs", "gemini", "pyttsx3", "browser"]

_elevenlabs_breaker = CircuitBreaker()
_gemini_breaker = CircuitBreaker()
# Backward compatibility alias
_breaker = _elevenlabs_breaker


@dataclass(frozen=True)
class Speech:
    text: str  # what is spoken (cut to TTS_MAX_CHARS)
    source: Source
    audio: bytes | None = None  # MP3/WAV bytes when source is elevenlabs, gemini, or pyttsx3
    detail: str = ""  # why a fallback tier is used or tier note
    mime_type: str = "audio/mpeg"  # "audio/mpeg" or "audio/wav"
    trigger_browser_speech: bool = False  # Tier 4 flag to trigger window.speechSynthesis.speak()


def reset() -> None:
    """Close breakers (for tests or after fixing keys)."""
    _elevenlabs_breaker.success()
    _gemini_breaker.success()


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
    if not _elevenlabs_breaker.allow():
        wait_s = _elevenlabs_breaker.retry_in()
        return f"ElevenLabs paused for {wait_s:.0f} s: {_elevenlabs_breaker.reason}"
    return ""


def gemini_tts_unavailable() -> str:
    """Why Gemini TTS cannot speak now ('' = it can)."""
    if not settings().gemini_api_keys:
        return "GEMINI_API_KEYS is not set"
    if not _gemini_breaker.allow():
        wait_s = _gemini_breaker.retry_in()
        return f"Gemini TTS paused for {wait_s:.0f} s: {_gemini_breaker.reason}"
    return ""


def _gemini_pool() -> KeyPoolManager:
    return key_pool("gemini", settings().gemini_api_keys)


def audio_path(text: str, ext: str = ".mp3") -> Path:
    """Where the clip for `text` is cached in AUDIO_CACHE_DIR (<sha256>.mp3 or .wav)."""
    s = settings()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not ext.startswith("."):
        ext = f".{ext}"
    return s.audio_cache_dir / f"{digest}{ext}"


def _elevenlabs_audio_path(text: str) -> Path:
    """Legacy voice-keyed path for ElevenLabs audio compatibility."""
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


def get_cached_speech(text: str) -> Speech | None:
    """Check if audio is already cached in data/.audio_cache/ as .mp3 or .wav."""
    candidates = [
        (_elevenlabs_audio_path(text), "elevenlabs", "audio/mpeg"),
        (audio_path(text, ".mp3"), "elevenlabs", "audio/mpeg"),
        (audio_path(text, ".wav"), "pyttsx3", "audio/wav"),
    ]
    for path, default_source, mime_type in candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                audio_bytes = path.read_bytes()
                return Speech(
                    text=text,
                    source=default_source,  # type: ignore
                    audio=audio_bytes,
                    mime_type=mime_type,
                    detail="served from audio cache",
                )
        except OSError:
            pass
    return None


def pcm_to_wav(
    pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1, sampwidth: int = 2
) -> bytes:
    """Convert raw 16-bit linear PCM audio into a standard WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# --- Tier 1: ElevenLabs -----------------------------------------------------------------------


def _elevenlabs(text: str) -> bytes:
    s = settings()
    body: dict = {"text": text, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    if s.elevenlabs_model:
        body["model_id"] = s.elevenlabs_model
    try:
        r = _http().post(
            ELEVENLABS_URL.format(voice=s.elevenlabs_voice_id or ELEVENLABS_DEFAULT_VOICE),
            json=body,
            headers={"xi-api-key": s.elevenlabs_api_key, "Accept": "audio/mpeg"},
            timeout=ELEVENLABS_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        _elevenlabs_breaker.failure(f"unreachable ({type(e).__name__})")
        raise
    if r.status_code == 429:
        _elevenlabs_breaker.failure(
            "rate limit", retry_after=_retry_after(r.headers), rate_limited=True
        )
    elif r.status_code in (401, 403):
        _elevenlabs_breaker.failure(
            f"refused (HTTP {r.status_code})", cooldown=ROUTER_BROKEN_COOLDOWN_S
        )
    elif r.status_code >= 400:
        _elevenlabs_breaker.failure(f"HTTP {r.status_code}")
    elif not r.content:
        _elevenlabs_breaker.failure("empty audio")
    else:
        _elevenlabs_breaker.success()
        return r.content
    raise RuntimeError(f"ElevenLabs answered HTTP {r.status_code}")


# --- Tier 2: Gemini TTS -----------------------------------------------------------------------


def _gemini_tts(text: str) -> tuple[bytes, str]:
    """Request speech synthesis from Gemini using audio modality."""
    s = settings()
    pool = _gemini_pool()
    keys = pool.order()
    if not keys:
        _gemini_breaker.failure("no Gemini keys available or all resting")
        raise RuntimeError("No available Gemini keys in pool")

    model = s.gemini_model or "gemini-3.8-flash"
    url = GEMINI_URL.format(model=model)
    body = {
        "contents": [
            {
                "parts": [
                    {"text": f"Read aloud verbatim with natural cadence:\n\n{text}"}
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": "Puck"
                    }
                }
            }
        }
    }

    last_err: Exception | None = None
    for key in keys:
        t0 = time.perf_counter()
        try:
            r = _http().post(
                url,
                json=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                timeout=GEMINI_TTS_TIMEOUT_S,
            )
        except httpx.TimeoutException as e:
            last_err = e
            continue
        except httpx.HTTPError as e:
            last_err = e
            continue

        if r.status_code == 429:
            hint = _retry_after(r.headers)
            pool.rate_limited(key, hint)
            continue
        if r.status_code in (401, 403):
            pool.refused(key, f"refused by Gemini (HTTP {r.status_code})")
            continue
        if r.status_code >= 400:
            last_err = RuntimeError(f"Gemini API error {r.status_code}: {_excerpt(r)}")
            continue

        try:
            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            for p in parts:
                inline = p.get("inlineData") or p.get("inline_data")
                if inline and inline.get("data"):
                    mime = inline.get("mimeType", "") or inline.get("mime_type", "")
                    raw_b64 = inline["data"]
                    audio_bytes = base64.b64decode(raw_b64)
                    pool.success(key, time.perf_counter() - t0)
                    _gemini_breaker.success()
                    if "pcm" in mime.lower():
                        return pcm_to_wav(audio_bytes), "audio/wav"
                    mime_type = "audio/wav" if "wav" in mime.lower() else "audio/mpeg"
                    return audio_bytes, mime_type
        except Exception as e:
            last_err = e
            continue

    _gemini_breaker.failure(f"Gemini TTS failed: {last_err}")
    raise RuntimeError(f"Gemini TTS request failed: {last_err}")


# --- Tier 3: Local OS Voice (pyttsx3) ---------------------------------------------------------


def _pyttsx3_synthesize(text: str, out_path: Path, rate: int = 160) -> bool:
    """Run pyttsx3 in a background thread to generate a local .wav file."""
    def worker() -> bool:
        try:
            with contextlib.suppress(Exception):
                import pythoncom  # type: ignore
                pythoncom.CoInitialize()
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            voices = engine.getProperty("voices")
            if voices:
                engine.setProperty("voice", voices[0].id)
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
            with contextlib.suppress(Exception):
                engine.stop()
            return out_path.is_file() and out_path.stat().st_size > 0
        except Exception as e:
            log.info("pyttsx3 synthesis worker encountered an issue: %s", e)
            return False
        finally:
            with contextlib.suppress(Exception):
                import pythoncom  # type: ignore
                pythoncom.CoUninitialize()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker)
        try:
            return future.result(timeout=PYTTSX3_TIMEOUT_S)
        except Exception as e:
            log.info("pyttsx3 background thread timed out or failed: %s", e)
            return False


def _pyttsx3_available() -> bool:
    """Check if pyttsx3 is importable and functional."""
    import importlib.util

    return importlib.util.find_spec("pyttsx3") is not None


# --- Main synthesize function -----------------------------------------------------------------


def needs_synthesis(text: str) -> bool:
    """Would synthesize(text) call ElevenLabs? (A key is set, it is not paused and the clip
    is not cached yet.) The preloader warms only these."""
    spoken = clip(text)
    return (
        bool(spoken)
        and not elevenlabs_unavailable()
        and not _elevenlabs_audio_path(spoken).is_file()
        and not audio_path(spoken, ".mp3").is_file()
    )


def synthesize(
    text: str,
    *,
    network: bool = True,
    enable_elevenlabs: bool = True,
    enable_gemini: bool = True,
    enable_pyttsx3: bool = True,
) -> Speech:
    """4-Tier Zero-Fail Voice Synthesis Cascade:
    1. ElevenLabs (cloud MP3)
    2. Gemini TTS (cloud audio modality, WAV/MP3)
    3. Local OS Voice (pyttsx3 WAV, 160wpm)
    4. Browser Web Speech API (HTML/JS fallback)

    Never crashes, never asks for keys.
    """
    spoken = clip(text)
    if not spoken:
        return Speech(spoken, "browser", None, "nothing to say")

    # Step 0: Check cache first
    cached = get_cached_speech(spoken)
    if cached is not None:
        return cached

    if not network:
        return Speech(spoken, "browser", None, "the clip is still being prepared")

    eleven_why = ""
    # Tier 1: ElevenLabs
    if enable_elevenlabs and not elevenlabs_unavailable():
        try:
            audio = _elevenlabs(spoken)
            _store(audio_path(spoken, ".mp3"), audio)
            _store(_elevenlabs_audio_path(spoken), audio)
            return Speech(spoken, "elevenlabs", audio, mime_type="audio/mpeg")
        except Exception as e:
            log.info("Tier 1 (ElevenLabs) failed (%s); cascading to Tier 2 (Gemini)", e)
            eleven_why = f"ElevenLabs failed: {e}"
    elif elevenlabs_unavailable():
        eleven_why = elevenlabs_unavailable()

    # Tier 2: Gemini TTS
    if enable_gemini and not gemini_tts_unavailable():
        try:
            audio, mime_type = _gemini_tts(spoken)
            ext = ".wav" if mime_type == "audio/wav" else ".mp3"
            _store(audio_path(spoken, ext), audio)
            return Speech(spoken, "gemini", audio, mime_type=mime_type)
        except Exception as e:
            log.info("Tier 2 (Gemini TTS) failed (%s); cascading to Tier 3 (pyttsx3)", e)

    # Tier 3: Local OS Voice (pyttsx3)
    if enable_pyttsx3 and _pyttsx3_available():
        wav_path = audio_path(spoken, ".wav")
        tmp_id = uuid.uuid4().hex[:8]
        tmp_wav = Path(tempfile.gettempdir()) / f"pyttsx3_{tmp_id}.wav"
        try:
            success = _pyttsx3_synthesize(spoken, tmp_wav, rate=160)
            if success and tmp_wav.is_file() and tmp_wav.stat().st_size > 0:
                wav_bytes = tmp_wav.read_bytes()
                tmp_wav.unlink(missing_ok=True)
                _store(wav_path, wav_bytes)
                return Speech(spoken, "pyttsx3", wav_bytes, mime_type="audio/wav")
        except Exception as e:
            log.info("Tier 3 (pyttsx3) failed (%s); cascading to Tier 4 (Browser)", e)
        finally:
            if tmp_wav.is_file():
                tmp_wav.unlink(missing_ok=True)

    # Tier 4: Browser Web Speech API
    detail = eleven_why or "Cloud and local speech tiers unavailable"

    return Speech(
        spoken,
        "browser",
        None,
        detail=detail,
        trigger_browser_speech=True,
    )


def active_voice() -> str:
    """Which voice provider is currently active/ready."""
    if not elevenlabs_unavailable():
        return "ElevenLabs"
    if not gemini_tts_unavailable():
        return "Gemini TTS"
    return "Browser voice"


def _js_string(text: str) -> str:
    """A JavaScript string literal safe for inline injection."""
    raw = json.dumps(text)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def browser_speech_html(
    text: str, label: str = "Read the question aloud", autoplay: bool = False
) -> str:
    """A self-contained HTML/JS component with Web Speech API button and optional autoplay."""
    light, dark = PALETTE["light"], PALETTE["dark"]
    autoplay_js = (
        "if (typeof triggerSpeak === 'function') { triggerSpeak(); }" if autoplay else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
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
  function triggerSpeak() {{
    if (!("speechSynthesis" in window)) {{
      note.textContent = "This browser cannot speak; read the question below.";
      return;
    }}
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "{BROWSER_VOICE_LANG}";
    u.rate = 1.0;
    u.onstart = () => {{ note.textContent = "Speaking"; }};
    u.onend = () => {{ note.textContent = ""; }};
    window.speechSynthesis.speak(u);
  }}
  document.getElementById("speak").addEventListener("click", triggerSpeak);
  {autoplay_js}
</script></body></html>"""
