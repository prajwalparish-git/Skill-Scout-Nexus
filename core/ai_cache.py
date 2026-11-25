"""Layer 3: a content-addressed cache of AI answers, so an identical request costs no call.

The key is the SHA-256 of the exact request (messages, model size, temperature, agent); the
value is the answer text that already passed validation, plus which provider gave it. Only
the agents in AI_CACHE_AGENTS use it (plans, critiques, rubric evaluations): a quiz or an
interview question should be new each time it is asked for.

Held in memory (a hit is a dictionary lookup) and written through to a JSON file
(AI_CACHE_PATH, default data/.ai_cache.json, git-ignored) so it survives restarts. At most
AI_CACHE_MAX_ENTRIES entries, least recently used dropped first; entries older than
AI_CACHE_TTL_S are ignored. A missing or damaged file just means an empty cache.
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from piq.config import AI_CACHE_MAX_ENTRIES, AI_CACHE_TTL_S

log = logging.getLogger("core.ai_cache")


@dataclass(frozen=True)
class Entry:
    text: str
    label: str  # the provider:model that answered first
    at: float  # epoch seconds


def request_key(messages: list[dict[str, str]], size: str, temperature: float, agent: str) -> str:
    raw = json.dumps(
        {"messages": messages, "size": size, "temperature": temperature, "agent": agent},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PromptCache:
    def __init__(
        self,
        path: Path | None,
        max_entries: int = AI_CACHE_MAX_ENTRIES,
        ttl_s: float = AI_CACHE_TTL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path, self.max_entries, self.ttl_s, self._clock = path, max_entries, ttl_s, clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, Entry] | None = None  # loaded on first use

    def _load(self) -> OrderedDict[str, Entry]:
        if self._entries is None:
            self._entries = OrderedDict()
            if self.path and self.path.is_file():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    for k, v in raw.items():
                        self._entries[k] = Entry(str(v["text"]), str(v["label"]), float(v["at"]))
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                    log.warning("AI cache at %s is unreadable (%s); starting empty", self.path, e)
                    self._entries = OrderedDict()
        return self._entries

    def get(self, key: str) -> Entry | None:
        with self._lock:
            entries = self._load()
            entry = entries.get(key)
            if entry is None:
                return None
            if self._clock() - entry.at > self.ttl_s:
                del entries[key]
                return None
            entries.move_to_end(key)  # least recently used is dropped first
            return entry

    def put(self, key: str, text: str, label: str) -> None:
        with self._lock:
            entries = self._load()
            entries[key] = Entry(text, label, self._clock())
            entries.move_to_end(key)
            while len(entries) > self.max_entries:
                entries.popitem(last=False)
            self._save(entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._load())

    def clear(self) -> int:
        """Drop every entry, in memory and on disk (the developer console); returns how many."""
        with self._lock:
            entries = self._load()
            count = len(entries)
            entries.clear()
            if self.path:
                try:
                    self.path.unlink(missing_ok=True)
                except OSError as e:
                    log.warning("AI cache at %s could not be removed: %s", self.path, e)
            return count

    def _save(self, entries: OrderedDict[str, Entry]) -> None:
        """Write the whole cache atomically (temp file, then rename); a failed write only
        costs persistence, never the answer."""
        if not self.path:
            return
        data = {k: {"text": e.text, "label": e.label, "at": e.at} for k, e in entries.items()}
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ai_cache.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("AI cache could not be written to %s: %s", self.path, e)
            if tmp:
                Path(tmp).unlink(missing_ok=True)
