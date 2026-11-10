"""Get this machine ready to run with no internet, then say what is and is not ready.

    python -m scripts.offline_setup            check, and download the speech model if missing
    python -m scripts.offline_setup --check    only check (never downloads, never pulls)

Run it once while online. Offline, the app falls back on its own:
  AI text   Groq -> Gemini -> Ollama (local) -> built-in answers from data/
  Voice out ElevenLabs -> Gemini TTS -> pyttsx3 (local) -> the browser's voice
  Voice in  Groq Whisper -> Gemini -> faster-whisper (local) -> the student types
Exit code 0 when every offline piece is ready, 1 otherwise.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import connectivity, transcribe_router  # noqa: E402
from core.ai_router import PROVIDERS  # noqa: E402
from piq.config import settings  # noqa: E402


def _row(ok: bool, what: str, hint: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'TODO'} {what}" + (f"  ->  {hint}" if hint and not ok else ""))
    return ok


def main(argv: list[str]) -> int:
    download = "--check" not in argv
    s = settings()
    print(f"Internet: {'reachable' if connectivity.online() else 'NOT reachable'}")
    ready: list[bool] = []

    print("\nAI text (local model)")
    why = PROVIDERS["ollama"].unavailable()
    ready.append(
        _row(
            not why,
            f"Ollama {s.ollama_model or '(OLLAMA_MODEL not set)'}: {why or 'running and pulled'}",
            f"install ollama.com, then: ollama pull {s.ollama_model or 'llama3.2:3b'}",
        )
    )
    _row(True, "Built-in answers from data/ (always available, last resort)")

    print("\nVoice out (speaks the question)")
    has_tts = importlib.util.find_spec("pyttsx3") is not None
    ready.append(_row(has_tts, "pyttsx3 local voice", "pip install -r requirements-offline.txt"))
    _row(True, "Browser voice (always available, last resort)")

    print("\nVoice in (transcribes the answer)")
    has_pkg = importlib.util.find_spec("faster_whisper") is not None
    ready.append(_row(has_pkg, "faster-whisper", "pip install -r requirements-offline.txt"))
    if has_pkg and s.local_stt_model:
        try:
            from faster_whisper import WhisperModel

            WhisperModel(
                s.local_stt_model, device="cpu", compute_type="int8", local_files_only=True
            )
            ready.append(_row(True, f"speech model {s.local_stt_model} downloaded"))
        except Exception:
            if download and connectivity.online():
                print(f"  ...  downloading speech model {s.local_stt_model} (one time)")
                try:
                    WhisperModel(s.local_stt_model, device="cpu", compute_type="int8")
                    ready.append(_row(True, f"speech model {s.local_stt_model} downloaded"))
                except Exception as e:
                    ready.append(_row(False, f"speech model download failed: {e}"))
            else:
                ready.append(
                    _row(
                        False,
                        f"speech model {s.local_stt_model} not downloaded",
                        "run while online",
                    )
                )
    elif has_pkg:
        ready.append(_row(False, "LOCAL_STT_MODEL is blank in .env", "set LOCAL_STT_MODEL=base.en"))
    print(f"\nLocal transcription usable: {transcribe_router.local_available()}")
    ok = all(ready)
    print("\n" + ("Offline mode is ready." if ok else "Offline mode is partly ready (see TODO)."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
