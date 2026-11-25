"""The developer console's live server log: the last MAX_RECORDS log records, in memory.

`install()` attaches one RingLogHandler to the root logger (and to uvicorn's own logger when
uvicorn stops it from propagating), so /api/ops/logs can show what the server printed without
shell access to the host. Records are redacted before they are stored: bearer tokens, Groq and
Gemini keys, database URL passwords and `password=` / `secret=` / `token=` pairs never reach the
buffer. Nothing is written to disk; a restart starts empty.
"""

import itertools
import logging
import re
import threading
from collections import deque
from datetime import UTC, datetime

MAX_RECORDS = 1000
MESSAGE_MAX = 4000  # a long traceback is cut, the start kept
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{6,}"), "gsk_[REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{6,}"), "AIza[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"), "sk-[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}"), "gh_[REDACTED]"),
    (
        re.compile(r"(?i)\b((?:postgres(?:ql)?|mysql|redis|amqp)(?:\+\w+)?://[^:/@\s]+):[^@\s]+@"),
        r"\1:[REDACTED]@",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|app_password|pepper)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s&,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
)


def redact(text: str) -> str:
    """`text` with every known secret pattern replaced by [REDACTED]."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RingLogHandler(logging.Handler):
    """Keeps the last `capacity` records as {id, ts, level, logger, message} (thread-safe)."""

    def __init__(self, capacity: int = MAX_RECORDS) -> None:
        super().__init__(level=logging.DEBUG)
        self._records: deque[dict] = deque(maxlen=capacity)
        self._ids = itertools.count(1)
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message = f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
            message = redact(message)
            if len(message) > MESSAGE_MAX:
                message = message[:MESSAGE_MAX] + " …[truncated]"
            with self._guard:
                self._records.append(
                    {
                        "id": next(self._ids),
                        "ts": record.created,
                        "level": record.levelname,
                        "logger": record.name,
                        "message": message,
                    }
                )
        except Exception:  # a log handler must never break the code that logs
            self.handleError(record)

    def snapshot(self) -> list[dict]:
        with self._guard:
            return list(self._records)

    def clear(self) -> int:
        with self._guard:
            count = len(self._records)
            self._records.clear()
            return count


handler = RingLogHandler()
_install_lock = threading.Lock()


def install() -> None:
    """Attach the handler (idempotent). uvicorn's logger gets it too when uvicorn has turned its
    propagation off; otherwise its records already reach the root logger."""
    with _install_lock:
        root = logging.getLogger()
        if handler not in root.handlers:
            root.addHandler(handler)
        uv = logging.getLogger("uvicorn")
        if not uv.propagate and handler not in uv.handlers:
            uv.addHandler(handler)


def query_logs(
    level: str | None = None,
    logger_prefix: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Newest first: records at `level` or above, from loggers starting with `logger_prefix`,
    whose message or logger name contains `search` (any case); at most `limit` (1-1000)."""
    floor = logging.getLevelName((level or "").upper()) if level else 0
    floor = floor if isinstance(floor, int) else 0
    prefix = (logger_prefix or "").strip()
    needle = (search or "").strip().lower()
    limit = max(1, min(int(limit), MAX_RECORDS))
    out: list[dict] = []
    for r in reversed(handler.snapshot()):
        lv = logging.getLevelName(r["level"])
        if isinstance(lv, int) and lv < floor:
            continue
        if prefix and not r["logger"].startswith(prefix):
            continue
        if needle and needle not in r["message"].lower() and needle not in r["logger"].lower():
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def clear_logs() -> int:
    """Empty the buffer; returns how many records were dropped."""
    return handler.clear()


def export_text() -> str:
    """The whole buffer, oldest first, one line per record (multi-line messages indented)."""
    lines = []
    for r in handler.snapshot():
        stamp = datetime.fromtimestamp(r["ts"], UTC).isoformat(timespec="milliseconds")
        body = r["message"].replace("\n", "\n    ")
        lines.append(f"{stamp} {r['level']:<8} {r['logger']}: {body}")
    return "\n".join(lines) + ("\n" if lines else "")
