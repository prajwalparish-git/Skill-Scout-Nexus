"""Layer 3, speculative preloading: write the next journey steps' content in the background
while the student reads the current one, so the roadmap, the quiz and the voice assessment
open on a finished result instead of a spinner.

After a resume scan or onboarding, `trigger_post_resume_preload` starts three tasks at once on
a small thread pool (PRELOAD_WORKERS) and returns:
  A. the 7-day roadmap for the top gaps (study planner agent);
  B. a critic-checked quiz on the top gap (critic quiz agent);
  C. the voice questions for the student's stream, the first one's audio synthesised.
While a quiz is open the next set on that skill is written, and while a voice question is open
the next question's audio is synthesised.

Each task is stored under a key made of exactly the inputs the page will ask with (student,
role, skills, difficulty, ...), so a page asking for anything else simply misses. Pages call
`get_or_wait(key, fallback_fn, on_miss=...)`: a finished result returns at once; one still
running gets up to PRELOAD_WAIT_S, then the instant fallback (question bank, curated roadmap,
browser voice) answers and the late result waits for the next identical request; with nothing
preloaded `on_miss` runs the normal generation. Every result is used once, so quizzes and
questions stay fresh.

State lives in a lock-guarded dictionary shared by every Streamlit session (each runs on its
own thread) and, for roadmaps, quizzes and questions, in PRELOAD_CACHE_DIR (default
data/.preload_cache/<key>.json, git-ignored), so a restart keeps them; entries expire after
PRELOAD_TTL_S. Worker threads never touch st.session_state: they have no script context, and
core/ never imports Streamlit. PRELOAD=false turns it all off; pages then behave as before.

This is the one core/ module that runs agents: it is the background twin of piq/journey.py,
and the `make_*` functions are the agent calls both use, so a preload and a page request are
always built the same way.
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from agents.critic_quiz_agent import QuizBatch, generate_critic_quiz
from agents.study_planner_agent import SevenDayRoadmap, generate_study_roadmap
from agents.voice_interview_agent import (
    CATEGORIES,
    Category,
    VoiceInterviewQuestion,
    bank_stream,
    generate_voice_interview_question,
)
from core import speech_router
from piq.config import (
    CRITIC_QUIZ_DEFAULT,
    CRITIC_QUIZ_DEFAULT_DIFFICULTY,
    PRELOAD_QUIZ_SKILLS,
    PRELOAD_TTL_S,
    PRELOAD_WAIT_S,
    PRELOAD_WORKERS,
    ROADMAP_DEFAULT_SKILLS,
    VOICE_DEFAULT_CATEGORY,
    settings,
)

log = logging.getLogger("core.preloader")
# Results kept on disk, by key kind; anything else (audio) lives in memory only.
STORED: dict[str, type[BaseModel]] = {
    "roadmap": SevenDayRoadmap,
    "quiz": QuizBatch,
    "voice": VoiceInterviewQuestion,
}
COUNTERS = ("hits", "waits", "fallbacks", "misses")


# --- keys: exactly the inputs a page asks with ------------------------------------------------


def clean_skills(skills: Iterable[str]) -> list[str]:
    return [s.strip() for s in skills if s.strip()]


def _key(kind: str, *parts: object) -> str:
    raw = json.dumps([kind, *parts], ensure_ascii=False, default=str)
    return f"{kind}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"  # also a file name


def roadmap_key(student_id: str, role: str, stream: str, gaps: Iterable[str]) -> str:
    return _key("roadmap", student_id, role, stream, clean_skills(gaps))


def quiz_key(student_id: str, role: str, skill: str, difficulty: str, count: int) -> str:
    return _key("quiz", student_id, role, skill.strip(), difficulty, count)


def voice_key(student_id: str, role: str, stream: str, category: str | None) -> str:
    return _key("voice", student_id, role, bank_stream(stream), category)


def audio_key(text: str) -> str:
    return _key("audio", speech_router.clip(text))


# --- the agent calls a preload and a page request share ---------------------------------------


def make_roadmap(student_id: str, role: str, stream: str, gaps: Iterable[str]) -> SevenDayRoadmap:
    return generate_study_roadmap(clean_skills(gaps), role, stream, student_id=student_id)


def make_quiz(student_id: str, role: str, skill: str, difficulty: str, count: int) -> QuizBatch:
    return generate_critic_quiz(
        skill.strip(),
        role,
        difficulty,  # type: ignore[arg-type]  # journey validated it against DIFFICULTIES
        count,
        max_retries=settings().max_critic_retries,
        student_id=student_id,
    )


def make_voice_question(
    role: str, stream: str, category: Category | None
) -> VoiceInterviewQuestion:
    # Audio is synthesised apart (speech_router), so a page can wait for it on its own.
    return generate_voice_interview_question(
        role, stream=bank_stream(stream), category=category, include_audio=False
    )


# --- the engine -------------------------------------------------------------------------------


def _failed(f: Future) -> bool:
    return f.done() and (f.cancelled() or f.exception() is not None)


@dataclass(frozen=True)
class _Task:
    future: Future
    started: float  # clock time
    keep: bool  # False: forgotten once done (audio: its clip is in the speech cache)


@dataclass(frozen=True)
class PreloadStatus:
    enabled: bool
    running: int
    ready: int  # finished, waiting to be used
    hits: int  # served finished: no wait at all
    waits: int  # served after waiting for a running task
    fallbacks: int  # still running after the wait: the instant fallback answered
    misses: int  # nothing preloaded (or it failed): the normal generation ran

    @property
    def label(self) -> str:
        if not self.enabled:
            return "off"
        return f"warming {self.running}" if self.running else "ready"


class BackgroundPreloader:
    """Background tasks by key, each result used once; see the module doc."""

    def __init__(
        self,
        cache_dir: Path | None,
        *,
        enabled: bool = True,
        workers: int = PRELOAD_WORKERS,
        wait_s: float = PRELOAD_WAIT_S,
        ttl_s: float = PRELOAD_TTL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cache_dir, self.enabled, self.workers = cache_dir, enabled, workers
        self.wait_s, self.ttl_s, self._clock = wait_s, ttl_s, clock
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None  # started on the first task
        self._tasks: dict[str, _Task] = {}
        self._counts = dict.fromkeys(COUNTERS, 0)
        self._closed = False
        if enabled:
            self._prune_disk()

    # --- running tasks ---------------------------------------------------------------------------

    def submit(self, key: str, fn: Callable[[], object], *, keep: bool = True) -> bool:
        """Run `fn` in the background under `key`. False when preloading is off, or that key is
        already running or ready (in memory or on disk); a failed one is tried again. Never
        blocks."""
        if not self.enabled:
            return False
        with self._lock:
            if self._closed:
                return False
            self._expire()
            existing = self._tasks.get(key)
            if existing is not None and not _failed(existing.future):
                return False
            if existing is None and self._read_disk(key) is not None:
                return False
            if self._executor is None:
                self._executor = ThreadPoolExecutor(self.workers, thread_name_prefix="preload")
            task = _Task(self._executor.submit(self._run, key, fn), self._clock(), keep)
            self._tasks[key] = task
        if not keep:
            task.future.add_done_callback(lambda _f: self._forget(key, task))
        return True

    def _run(self, key: str, fn: Callable[[], object]) -> object:
        t0 = time.perf_counter()
        try:
            result = fn()
        except Exception:
            log.exception("preload %s failed; the page will generate it itself", key)
            raise
        self._persist(key, result)  # before the future is done: "done" implies "on disk"
        log.info("preload %s ready in %.1f s", key, time.perf_counter() - t0)
        return result

    def _forget(self, key: str, task: _Task) -> None:
        with self._lock:
            if self._tasks.get(key) is task:
                del self._tasks[key]

    def _expire(self) -> None:
        """Drop finished results nobody used within ttl_s (caller holds the lock)."""
        now = self._clock()
        for key, task in list(self._tasks.items()):
            if task.future.done() and now - task.started > self.ttl_s:
                del self._tasks[key]
                self._unlink(key)

    # --- reading results -------------------------------------------------------------------------

    def get_or_wait[T](
        self,
        task_key: str,
        fallback_fn: Callable[[], T],
        timeout: float | None = None,
        *,
        on_miss: Callable[[], T] | None = None,
    ) -> T:
        """The preloaded result for `task_key`, used up by this call.

        Finished: returned at once. Still running: waited for up to `timeout` seconds
        (PRELOAD_WAIT_S), then `fallback_fn()` answers and the late result stays ready for the
        next identical request. Nothing preloaded, or the task failed: `on_miss()` (default:
        `fallback_fn`), the normal generation.
        """
        miss = on_miss or fallback_fn
        with self._lock:
            task = self._tasks.get(task_key)
            stored = self._read_disk(task_key) if task is None else None
            if stored is not None:
                self._unlink(task_key)
        if task is None:
            self._count("misses" if stored is None else "hits")
            return miss() if stored is None else cast(T, stored)
        finished = task.future.done()
        if not finished:
            done, _ = wait([task.future], timeout=self.wait_s if timeout is None else timeout)
            if not done:
                self._count("fallbacks")
                log.info("preload %s still running; the fallback answers", task_key)
                return fallback_fn()
        self._forget(task_key, task)
        with self._lock:
            self._unlink(task_key)
        if _failed(task.future):
            self._count("misses")
            return miss()
        self._count("hits" if finished else "waits")
        return cast(T, task.future.result())

    def take_ready(self, task_key: str) -> object | None:
        """A finished result, used up by this call; None while it is still running, failed, or
        when there is none. Never waits (the provisional-roadmap upgrade polls with it)."""
        with self._lock:
            task = self._tasks.get(task_key)
            if task is None:
                stored = self._read_disk(task_key)
                if stored is not None:
                    self._unlink(task_key)
                return stored
            if not task.future.done():
                return None
            del self._tasks[task_key]
            self._unlink(task_key)
        return None if _failed(task.future) else task.future.result()

    def peek(self, task_key: str) -> object | None:
        """A finished result without using it up (None: missing, running or failed)."""
        with self._lock:
            task = self._tasks.get(task_key)
            if task is None:
                return self._read_disk(task_key)
        f = task.future
        return f.result() if f.done() and not _failed(f) else None

    def _count(self, name: str) -> None:
        with self._lock:
            self._counts[name] += 1

    # --- the journey's triggers ------------------------------------------------------------------

    def trigger_post_resume_preload(
        self,
        student_id: str,
        stream: str,
        role: str,
        matched_skills: Iterable[str],
        missing_skills: Iterable[str],
    ) -> list[str]:
        """The moment a resume is parsed or a role chosen: start the three next-step tasks at
        once and return their keys (already running or ready ones are not restarted).
        `stream` is the catalog stream; the quiz takes the top gap, else the top matched skill
        (the quiz page's default order)."""
        if not self.enabled:
            return []
        missing, matched = list(missing_skills), list(matched_skills)
        started: list[str] = []
        gaps = clean_skills(missing[:ROADMAP_DEFAULT_SKILLS])  # A: what the roadmap preselects
        if gaps:
            key = roadmap_key(student_id, role, stream, gaps)
            if self.submit(key, lambda: make_roadmap(student_id, role, stream, gaps)):
                started.append(key)
        skills = list(dict.fromkeys(clean_skills([*missing, *matched])))  # B
        started += self.trigger_quiz_next_batch_preload(
            student_id, role, skills[:PRELOAD_QUIZ_SKILLS]
        )
        for category in sorted(CATEGORIES, key=lambda c: c != VOICE_DEFAULT_CATEGORY):  # C
            started += self.preload_voice_question(
                student_id, role, stream, category, speak=category == VOICE_DEFAULT_CATEGORY
            )
        return started

    def trigger_quiz_next_batch_preload(
        self,
        student_id: str,
        role: str,
        missing_skills: Iterable[str],
        difficulty: str = CRITIC_QUIZ_DEFAULT_DIFFICULTY,
        count: int = CRITIC_QUIZ_DEFAULT,
    ) -> list[str]:
        """A fresh critic-checked quiz on each skill, ready the moment the student asks for one
        (called while a quiz is open, for the next set). The keys started."""
        started = []
        for skill in clean_skills(missing_skills):
            key = quiz_key(student_id, role, skill, difficulty, count)
            if self.submit(key, lambda s=skill: make_quiz(student_id, role, s, difficulty, count)):
                started.append(key)
        return started

    def preload_voice_question(
        self, student_id: str, role: str, stream: str, category: Category, *, speak: bool
    ) -> list[str]:
        """The question the voice page will serve for (stream, category); `speak` also
        synthesises its audio. Already ready: only its audio is warmed. The keys started."""
        if not self.enabled:
            return []
        key = voice_key(student_id, role, stream, category)
        ready = self.peek(key)
        if isinstance(ready, VoiceInterviewQuestion):
            return self.trigger_interview_next_audio_preload(ready.question_text) if speak else []

        def work() -> VoiceInterviewQuestion:
            q = make_voice_question(role, stream, category)
            if speak:
                self.trigger_interview_next_audio_preload(q.question_text)
            return q

        return [key] if self.submit(key, work) else []

    def trigger_interview_next_audio_preload(self, question_text: str) -> list[str]:
        """Synthesise the next question's audio while the student answers the current one; the
        clip lands in the speech cache. Nothing to do without ElevenLabs, or when it is cached."""
        if not self.enabled or not speech_router.needs_synthesis(question_text):
            return []
        key = audio_key(question_text)
        started = self.submit(key, lambda: speech_router.synthesize(question_text), keep=False)
        return [key] if started else []

    # --- disk ------------------------------------------------------------------------------------

    def _path(self, key: str) -> Path | None:
        kind = key.split("-", 1)[0]
        return self.cache_dir / f"{key}.json" if self.cache_dir and kind in STORED else None

    def _persist(self, key: str, result: object) -> None:
        """Write the result atomically; a failed write only costs the restart copy."""
        path = self._path(key)
        if path is None or not isinstance(result, BaseModel):
            return
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
            body = {"at": self._clock(), "data": result.model_dump(mode="json")}
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            log.warning("preload cache could not be written to %s: %s", path, e)
            if tmp:
                Path(tmp).unlink(missing_ok=True)

    def _read_disk(self, key: str) -> BaseModel | None:
        """The stored result, or None (missing, expired or damaged: then deleted)."""
        path = self._path(key)
        if path is None or not path.is_file():
            return None
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            if self._clock() - float(body["at"]) <= self.ttl_s:
                return STORED[key.split("-", 1)[0]].model_validate(body["data"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("preload cache entry %s is unreadable (%s); dropped", path.name, e)
        path.unlink(missing_ok=True)
        return None

    def _unlink(self, key: str) -> None:
        path = self._path(key)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                log.warning("preload cache entry %s could not be removed: %s", path.name, e)

    def _prune_disk(self) -> None:
        """Delete expired, damaged and half-written entries (on start)."""
        if not self.cache_dir or not self.cache_dir.is_dir():
            return
        for part in self.cache_dir.glob("*.part"):
            part.unlink(missing_ok=True)
        for path in self.cache_dir.glob("*.json"):
            self._read_disk(path.stem)

    # --- status and lifecycle --------------------------------------------------------------------

    def status(self) -> PreloadStatus:
        with self._lock:
            self._expire()
            running = sum(not t.future.done() for t in self._tasks.values())
            return PreloadStatus(self.enabled, running, len(self._tasks) - running, **self._counts)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Wait until no task is running, chained ones included (tests). False on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                running = [t.future for t in self._tasks.values() if not t.future.done()]
            left = deadline - time.monotonic()
            if not running:
                return True
            if left <= 0:
                return False
            wait(running, timeout=left)

    def shutdown(self, wait_for_running: bool = True) -> None:
        """Stop taking tasks; queued ones are cancelled, running ones finish."""
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait_for_running, cancel_futures=True)
        with self._lock:
            self._tasks.clear()


# --- the process-wide preloader -----------------------------------------------------------------

_instance: BackgroundPreloader | None = None
_instance_lock = threading.Lock()


def get_preloader() -> BackgroundPreloader:
    """The process-wide preloader, configured from settings (PRELOAD, PRELOAD_CACHE_DIR)."""
    global _instance
    with _instance_lock:
        if _instance is None:
            s = settings()
            _instance = BackgroundPreloader(s.preload_cache_dir, enabled=s.preload)
        return _instance


def reset_preloader() -> None:
    """Let running tasks finish, then drop the preloader (tests; or after changing .env)."""
    global _instance
    with _instance_lock:
        old, _instance = _instance, None
    if old is not None:
        old.shutdown()
