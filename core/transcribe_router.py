"""Layer 3, transcription router: a spoken answer to text, online or offline.

Tiers, in order (a tier that is missing or fails hands over to the next):
1. Groq Whisper (GROQ_API_KEYS): the fastest cloud transcriber.
2. Gemini audio understanding (GEMINI_API_KEYS, GEMINI_MODEL): the cloud alternative.
3. faster-whisper on this machine (LOCAL_STT_MODEL in .env, e.g. base.en): no internet needed.
   Optional: `pip install -r requirements-offline.txt`, then `python -m scripts.offline_setup`
   downloads the model once while online.
4. Nothing: the empty string, and the page asks the student to type instead.

core/connectivity.py is asked first: offline, both cloud tiers are skipped at once.
Never raises, never asks for a key on screen.
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

from core import connectivity
from core.ai_router import _excerpt, _http, key_pool
from piq.config import settings

log = logging.getLogger("core.transcribe_router")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_STT_TIMEOUT_S = 20.0
GROQ_STT_MODEL = "whisper-large-v3"

_local_lock = threading.Lock()
_local_models: dict[str, object] = {}


@dataclass(frozen=True)
class Transcript:
    text: str  # "" when no tier could transcribe
    source: str  # "groq" | "gemini" | "local" | "" (nothing)
    detail: str = ""


def local_available() -> bool:
    """Is faster-whisper installed and a local model configured?"""
    return (
        bool(settings().local_stt_model) and importlib.util.find_spec("faster_whisper") is not None
    )


def _mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".mp3": "audio/mp3",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
    }.get(ext, "audio/wav")


def _groq(audio: bytes, filename: str, api_key: str | None) -> str:
    key = api_key or settings().groq_api_key or os.getenv("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEYS is not set")
    from groq import Groq

    client = Groq(api_key=key)
    out = client.audio.transcriptions.create(
        file=(filename, audio),
        model=GROQ_STT_MODEL,
        response_format="text",
        temperature=0.0,
    )
    return str(out).strip()


def _gemini(audio: bytes, filename: str) -> str:
    s = settings()
    if not s.gemini_api_keys:
        raise RuntimeError("GEMINI_API_KEYS is not set")
    if not s.gemini_model:
        raise RuntimeError("GEMINI_MODEL is not set")
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": "Transcribe this spoken interview answer verbatim. "
                        "Reply with the transcript only, no commentary."
                    },
                    {
                        "inlineData": {
                            "mimeType": _mime(filename),
                            "data": base64.b64encode(audio).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0},
    }
    last: Exception | None = None
    for key in key_pool("gemini", s.gemini_api_keys).order() or list(s.gemini_api_keys):
        try:
            r = _http().post(
                GEMINI_URL.format(model=s.gemini_model),
                json=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                timeout=GEMINI_STT_TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            last = e
            continue
        if r.status_code >= 400:
            last = RuntimeError(f"Gemini HTTP {r.status_code}: {_excerpt(r)}")
            continue
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = " ".join(p.get("text", "") for p in parts).strip()
        if text:
            return text
        last = RuntimeError("Gemini answered without text")
    raise RuntimeError(f"Gemini transcription failed: {last}")


def _local(audio: bytes, filename: str) -> str:
    """faster-whisper on the CPU; the model loads once and stays in memory."""
    name = settings().local_stt_model
    if not local_available():
        raise RuntimeError("faster-whisper is not installed (see requirements-offline.txt)")
    from faster_whisper import WhisperModel

    with _local_lock:
        model = _local_models.get(name)
        if model is None:
            model = WhisperModel(name, device="cpu", compute_type="int8")
            _local_models[name] = model
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio)
        path = f.name
    try:
        segments, _ = model.transcribe(path, beam_size=1)  # type: ignore[attr-defined]
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        Path(path).unlink(missing_ok=True)


def transcribe(
    audio: bytes, filename: str = "response.wav", *, api_key: str | None = None
) -> Transcript:
    """The spoken answer as text from the first tier that works; never raises."""
    if not audio:
        return Transcript("", "", "no audio")
    why: list[str] = []
    if connectivity.online():
        for name, run in (
            ("groq", lambda: _groq(audio, filename, api_key)),
            ("gemini", lambda: _gemini(audio, filename)),
        ):
            try:
                text = run()
                if text:
                    return Transcript(text, name)
                why.append(f"{name}: empty transcript")
            except Exception as e:
                log.info("Transcription tier %s failed: %s", name, e)
                why.append(f"{name}: {e}")
    else:
        why.append("no internet connection")
    if local_available():
        try:
            text = _local(audio, filename)
            if text:
                return Transcript(text, "local")
            why.append("local: empty transcript")
        except Exception as e:
            log.info("Local transcription failed: %s", e)
            why.append(f"local: {e}")
    else:
        why.append("local transcription not installed")
    return Transcript("", "", "; ".join(why))
