"""Hybrid telemetry storage: local SQLite always, a cloud PostgreSQL (Supabase) copy behind it.

Local engine (always on). Every read and write goes to the SQLite file TELEMETRY_DB_PATH
(default data/placement_nexus.db) in WAL mode with synchronous=NORMAL, shared across threads
(check_same_thread=False) with a busy timeout, so a page never waits on the network: a write
is a local commit of a millisecond or two.

Cloud engine (optional). SUPABASE_DB_URL or DATABASE_URL names a PostgreSQL; nothing is ever
asked for when both are blank. postgres:// and postgresql:// mean psycopg 3 here (the driver
the project installs). The pool suits Supabase's poolers (port 6543 transaction mode or 5432
session mode): pool_size 5, max_overflow 10, pool_timeout 3 s, pre-ping, a 3 s connect timeout,
sslmode=require (prefer on localhost), and no server-side prepared statements, which a
transaction pooler cannot keep.

Write-through. Each write also adds a row to the local sync outbox in the same transaction,
then wakes the background worker (a ThreadPoolExecutor with SYNC_WORKERS threads), which
pushes pending records to the cloud oldest first. Students are matched by username, plans by
(student, week), and each attempt, analysis and session carries a receipt
"<device>:<entity>:<local id>" in the cloud, so records from many machines never collide and a
retry never duplicates. While the cloud is unreachable, records simply wait: the worker backs
off (SYNC_RETRY_S, doubling to SYNC_RETRY_MAX_S) and retries on its own timer, so whatever
was made offline is pushed, oldest first, once the connection is back. Records that
were already in the local file before the outbox existed are queued once, on first start.
Nothing here ever raises a network error to the caller. Logs show URLs with the password hidden.
"""

import contextvars
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from sqlalchemy import URL, Engine, create_engine, delete, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database.models import (
    CLOUD_TABLES,
    ENTITIES,
    LOCAL_TABLES,
    Base,
    Organization,
    StudentProfile,
    StudyPlan,
    SyncMeta,
    SyncOutbox,
    SyncReceipt,
    migrate_columns,
    migrate_identity,
    utc_now,
)
from piq.config import (
    CLOUD_MAX_OVERFLOW,
    CLOUD_POOL_SIZE,
    CLOUD_POOL_TIMEOUT_S,
    DB_CONNECT_TIMEOUT,
    DEMO_COHORT_PREFIX,
    DEMO_ORG_PREFIX,
    SQLITE_BUSY_TIMEOUT_MS,
    SYNC_BATCH,
    SYNC_KEEP_DAYS,
    SYNC_MAX_ATTEMPTS,
    SYNC_RETRY_MAX_S,
    SYNC_RETRY_S,
    SYNC_WORKERS,
    settings,
)

log = logging.getLogger("database")
POSTGRES, SQLITE = "postgresql", "sqlite"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MUTABLE = frozenset(
    {"organization", "student", "plan"}
)  # updated in place: one pending outbox row is enough

_local_only: contextvars.ContextVar[bool] = contextvars.ContextVar("local_only", default=False)


@contextmanager
def local_only() -> Iterator[None]:
    """Writes inside stay on this machine (the demo cohort): no outbox rows."""
    token = _local_only.set(True)
    try:
        yield
    finally:
        _local_only.reset(token)


class CloudUnavailable(RuntimeError):
    """No cloud database is configured, or its URL cannot be used."""


def safe_url(url: str) -> str:
    """The URL as it may be logged: password hidden, or a placeholder if it does not parse."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except SQLAlchemyError:
        return "<unparseable database URL>"


# --- engines ----------------------------------------------------------------------------------


def normalize_cloud_url(raw: str) -> URL:
    """A usable PostgreSQL URL: postgres:// and postgresql:// become postgresql+psycopg://.
    Raises ValueError for one that does not parse or names another database."""
    try:
        url = make_url(raw.strip())
    except SQLAlchemyError as e:
        raise ValueError("the cloud database URL does not parse") from e
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() != POSTGRES:
        raise ValueError(f"the cloud database URL names {url.get_backend_name()!r}, not PostgreSQL")
    return url


def cloud_connect_args(url: URL, connect_timeout: int = DB_CONNECT_TIMEOUT) -> dict:
    args: dict = {"connect_timeout": connect_timeout}
    if "sslmode" not in url.query:  # Supabase requires TLS; a local server may not offer it
        args["sslmode"] = "prefer" if (url.host or "localhost") in LOCAL_HOSTS else "require"
    if url.get_driver_name() == "psycopg":
        args["prepare_threshold"] = None  # transaction poolers cannot keep prepared statements
    return args


def create_cloud_engine(raw_url: str, connect_timeout: int = DB_CONNECT_TIMEOUT) -> Engine:
    """The pooled engine for the cloud copy. Creating it opens no connection."""
    url = normalize_cloud_url(raw_url)
    return create_engine(
        url,
        pool_size=CLOUD_POOL_SIZE,
        max_overflow=CLOUD_MAX_OVERFLOW,
        pool_timeout=CLOUD_POOL_TIMEOUT_S,
        pool_pre_ping=True,
        connect_args=cloud_connect_args(url, connect_timeout),
    )


def create_local_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)), connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # readers never block the writer, or vice versa
        cur.execute("PRAGMA synchronous=NORMAL")  # durable at checkpoints; far fewer fsyncs
        cur.execute("PRAGMA foreign_keys=ON")  # SQLite leaves them off by default
        cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cur.close()

    return engine


# --- the manager --------------------------------------------------------------------------------


SyncState = Literal["local only", "up to date", "syncing", "offline"]


@dataclass(frozen=True)
class SyncStatus:
    cloud_configured: bool
    state: SyncState  # derived in DatabaseManager.status() from the config and the worker
    pending: int
    set_aside: int  # rejected SYNC_MAX_ATTEMPTS times
    last_synced_at: datetime | None
    retry_in_s: float
    last_error: str


class DatabaseManager:
    """The local engine, the optional cloud engine and the sync worker; see the module doc."""

    def __init__(
        self,
        database_url: str = "",
        sqlite_path: Path | str = Path("data") / "placement_nexus.db",
        connect_timeout: int = DB_CONNECT_TIMEOUT,
        *,
        cloud_engine: Engine | None = None,
    ) -> None:
        self.database_url = database_url.strip()
        self.sqlite_path = Path(sqlite_path)
        self.connect_timeout = max(1, int(connect_timeout))
        self._local: Engine | None = None
        self._cloud: Engine | None = cloud_engine
        self._cloud_ready = False  # tables created on the cloud side
        self._lock = threading.RLock()
        self.sync = SyncWorker(self)

    # --- engines -----------------------------------------------------------------------------
    @property
    def local(self) -> Engine:
        with self._lock:
            if self._local is None:
                engine = create_local_engine(self.sqlite_path)
                migrate_identity(engine)  # a file from before accounts: usn -> username
                Base.metadata.create_all(engine, tables=LOCAL_TABLES)
                migrate_columns(engine)  # a file from before organizations: new columns in place
                self._local = engine
                self._queue_existing()
            return self._local

    engine = local  # the name callers used before the cloud copy existed

    @property
    def cloud_configured(self) -> bool:
        return self._cloud is not None or bool(self.database_url)

    def cloud(self) -> Engine:
        """The cloud engine, its tables created on first use. Raises CloudUnavailable when none
        is configured or the URL is unusable, or a SQLAlchemy error when it is unreachable."""
        with self._lock:
            if self._cloud is None:
                if not self.database_url:
                    raise CloudUnavailable("no cloud database configured")
                try:
                    self._cloud = create_cloud_engine(self.database_url, self.connect_timeout)
                except (ValueError, ImportError, SQLAlchemyError) as e:
                    raise CloudUnavailable(str(e)) from e
            engine = self._cloud
        if not self._cloud_ready:
            migrate_identity(engine)  # the first machine with accounts migrates the cloud copy
            Base.metadata.create_all(engine, tables=CLOUD_TABLES)
            migrate_columns(engine)  # ...and the first with organizations adds their columns
            self._cloud_ready = True
        return engine

    def use_cloud_engine(self, engine: Engine | None) -> None:
        """Swap the cloud engine (tests: an outage that ends; or after fixing the URL)."""
        with self._lock:
            if self._cloud is not None and self._cloud is not engine:
                self._cloud.dispose()
            self._cloud, self._cloud_ready = engine, False
        self.sync.reset_backoff()

    # --- running work ------------------------------------------------------------------------
    def run[T](self, work: Callable[[Session], T]) -> T:
        """Run `work(session)` on the local file in one transaction (committed if it returns,
        rolled back if it raises). Reads, and writes that need no cloud copy."""
        with Session(self.local, expire_on_commit=False) as session, session.begin():
            return work(session)

    def write[T](self, work: Callable[[Session], T], entity: str) -> T:
        """Run a write locally, queue its record for the cloud in the same transaction, and wake
        the sync worker. Returns as soon as the local commit is done."""
        with Session(self.local, expire_on_commit=False) as session, session.begin():
            row = work(session)
            if not _local_only.get():
                session.flush()
                self._enqueue(session, entity, row.id)
        if not _local_only.get():
            self.sync.kick()
        return row

    def run_cloud[T](self, work: Callable[[Session], T]) -> T:
        """Run `work(session)` on the cloud copy (the faculty page's whole-cohort view)."""
        with Session(self.cloud(), expire_on_commit=False) as session, session.begin():
            return work(session)

    # --- the outbox --------------------------------------------------------------------------
    @staticmethod
    def _enqueue(session: Session, entity: str, local_id: int) -> None:
        if entity in MUTABLE and session.scalar(
            select(SyncOutbox.id).where(
                SyncOutbox.entity == entity,
                SyncOutbox.local_id == local_id,
                SyncOutbox.synced_at.is_(None),
                SyncOutbox.attempts < SYNC_MAX_ATTEMPTS,
            )
        ):
            return  # the pending row will send the latest state anyway
        session.add(SyncOutbox(entity=entity, local_id=local_id))

    def _queue_existing(self) -> None:
        """Once per database: queue records written before the outbox existed (not the demo
        cohort), so a database that was only ever local reaches the cloud once one is set."""
        with Session(self._local, expire_on_commit=False) as s, s.begin():  # type: ignore[arg-type]
            if s.get(SyncMeta, "queued_existing"):
                return
            demo = select(StudentProfile.id).where(
                StudentProfile.username.like(f"{DEMO_COHORT_PREFIX}%")
            )
            demo_orgs = select(Organization.id).where(
                Organization.org_code.like(f"{DEMO_ORG_PREFIX}%")
            )
            already = {(o.entity, o.local_id) for o in s.scalars(select(SyncOutbox))}
            for entity, model in ENTITIES.items():
                if entity == "organization":
                    column, skip = model.id, demo_orgs  # type: ignore[attr-defined]
                elif entity == "student":
                    column, skip = model.id, demo  # type: ignore[attr-defined]
                else:
                    column, skip = model.student_id, demo  # type: ignore[attr-defined]
                for rid in s.scalars(select(model.id).where(column.not_in(skip))):  # type: ignore[attr-defined]
                    if (entity, rid) not in already:
                        s.add(SyncOutbox(entity=entity, local_id=rid))
            s.add(SyncMeta(key="queued_existing", value=utc_now().isoformat()))

    def device_id(self) -> str:
        with Session(self.local) as s, s.begin():
            meta = s.get(SyncMeta, "device_id")
            if meta is None:
                meta = SyncMeta(key="device_id", value=uuid.uuid4().hex)
                s.add(meta)
            return meta.value

    def status(self) -> SyncStatus:
        with Session(self.local) as s:
            pending = s.scalar(
                select(func.count())
                .select_from(SyncOutbox)
                .where(SyncOutbox.synced_at.is_(None), SyncOutbox.attempts < SYNC_MAX_ATTEMPTS)
            )
            set_aside = s.scalar(
                select(func.count())
                .select_from(SyncOutbox)
                .where(SyncOutbox.synced_at.is_(None), SyncOutbox.attempts >= SYNC_MAX_ATTEMPTS)
            )
            last = s.scalar(select(func.max(SyncOutbox.synced_at)))
        w = self.sync
        state: SyncState
        if not self.cloud_configured:
            state = "local only"
        elif w.retry_in() > 0:
            state = "offline"
        elif w.busy or pending:
            state = "syncing"
        else:
            state = "up to date"
        return SyncStatus(
            self.cloud_configured,
            state,
            int(pending or 0),
            int(set_aside or 0),
            last,
            w.retry_in(),
            w.last_error,
        )

    def reason(self, error: BaseException) -> str:
        """One line about `error`, safe to log: the URL's password never appears."""
        cause = error.orig if isinstance(error, DBAPIError) and error.orig else error
        lines = str(cause).strip().splitlines()
        message = lines[0] if lines else type(cause).__name__
        try:
            password = make_url(self.database_url).password if self.database_url else None
        except SQLAlchemyError:
            password = None
        if password:
            message = message.replace(str(password), "***")
        return f"{type(error).__name__}: {message}"

    def dispose(self) -> None:
        self.sync.shutdown()
        with self._lock:
            for engine in (self._local, self._cloud):
                if engine is not None:
                    engine.dispose()
            self._local, self._cloud, self._cloud_ready = None, None, False


# --- the background worker ----------------------------------------------------------------------


class SyncWorker:
    """Pushes pending outbox rows to the cloud on background threads; never blocks a caller."""

    def __init__(self, manager: DatabaseManager) -> None:
        self.manager = manager
        self._executor: ThreadPoolExecutor | None = None
        self._drain_lock = threading.Lock()  # one drain at a time; others just ask for another
        self._state = threading.Lock()
        self._again = False
        self._futures: list[Future] = []
        self._timer: threading.Timer | None = None
        self.failures = 0
        self._retry_at = 0.0
        self.last_error = ""
        self.busy = False

    def retry_in(self) -> float:
        return max(0.0, self._retry_at - time.monotonic()) if self._retry_at else 0.0

    def reset_backoff(self) -> None:
        with self._state:
            self.failures, self._retry_at, self.last_error = 0, 0.0, ""
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def kick(self) -> None:
        """Ask for a drain in the background (no-op without a cloud, or while backing off)."""
        if not self.manager.cloud_configured or self.retry_in() > 0:
            return
        with self._state:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(SYNC_WORKERS, thread_name_prefix="cloud-sync")
            self._futures = [f for f in self._futures if not f.done()]
            if len(self._futures) >= SYNC_WORKERS:  # a drain is queued: it will see this write
                self._again = True
                return
            self._futures.append(self._executor.submit(self.drain))

    def flush(self, timeout: float = 10.0) -> None:
        """Wait for the queued drains (tests, and a clean shutdown)."""
        deadline = time.monotonic() + timeout
        while True:
            with self._state:
                futures = [f for f in self._futures if not f.done()]
            if not futures or time.monotonic() > deadline:
                return
            futures[0].result(timeout=max(0.0, deadline - time.monotonic()))

    def shutdown(self) -> None:
        with self._state:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None

    def drain(self) -> int:
        """Push every pending record; returns how many went. Safe to call from any thread."""
        if not self._drain_lock.acquire(blocking=False):
            self._again = True
            return 0
        pushed = 0
        self.busy = True
        try:
            while True:
                self._again = False
                batch, ok = self._pass()
                pushed += batch
                if not ok or not (self._again or batch == SYNC_BATCH):
                    break
        finally:
            self.busy = False
            self._drain_lock.release()
        return pushed

    def _pass(self) -> tuple[int, bool]:
        """One batch. (records pushed, whether the cloud stayed reachable)."""
        m = self.manager
        try:
            cloud = m.cloud()
            device = m.device_id()
        except CloudUnavailable as e:
            self._failed(e, permanent=True)
            return 0, False
        except Exception as e:
            self._failed(e)
            return 0, False
        with Session(m.local, expire_on_commit=False) as local:
            items = list(
                local.scalars(
                    select(SyncOutbox)
                    .where(SyncOutbox.synced_at.is_(None), SyncOutbox.attempts < SYNC_MAX_ATTEMPTS)
                    .order_by(SyncOutbox.id)
                    .limit(SYNC_BATCH)
                )
            )
        pushed = 0
        for item in items:
            try:
                with Session(cloud) as cs, cs.begin(), Session(m.local) as ls:
                    _push(ls, cs, item, device)
            except (IntegrityError, ValueError, KeyError) as e:  # this record, not the cloud
                self._reject(item, m.reason(e))
                continue
            except Exception as e:
                self._failed(e)
                return pushed, False
            with Session(m.local) as ls, ls.begin():
                ls.get(SyncOutbox, item.id).synced_at = utc_now()  # type: ignore[union-attr]
            pushed += 1
        if items or self.failures:
            self._succeeded()
        return pushed, True

    def _reject(self, item: SyncOutbox, reason: str) -> None:
        with Session(self.manager.local) as ls, ls.begin():
            row = ls.get(SyncOutbox, item.id)
            if row is not None:
                row.attempts += 1
                row.last_error = reason[:500]
        log.warning("Cloud sync: %s %s rejected (%s)", item.entity, item.local_id, reason)

    def _failed(self, error: BaseException, permanent: bool = False) -> None:
        reason = self.manager.reason(error)
        with self._state:
            self.failures += 1
            first = self.failures == 1
            delay = (
                SYNC_RETRY_MAX_S
                if permanent
                else min(SYNC_RETRY_MAX_S, SYNC_RETRY_S * 2 ** (self.failures - 1))
            )
            self._retry_at = time.monotonic() + delay
            self.last_error = reason
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(delay, self._retry)
            self._timer.daemon = True
            self._timer.start()
        level = logging.WARNING if first else logging.DEBUG
        log.log(
            level,
            "Cloud sync paused: %s at %s unavailable (%s); records wait locally, retry in %.0f s",
            "cloud database",
            safe_url(self.manager.database_url) if self.manager.database_url else "(engine)",
            reason,
            delay,
        )

    def _retry(self) -> None:
        with self._state:
            self._retry_at, self._timer = 0.0, None
        self.kick()

    def _succeeded(self) -> None:
        with self._state:
            if self.failures:
                log.info("Cloud sync resumed after %d failed attempt(s)", self.failures)
            self.failures, self._retry_at, self.last_error = 0, 0.0, ""
        cutoff = utc_now() - timedelta(days=SYNC_KEEP_DAYS)
        with Session(self.manager.local) as ls, ls.begin():
            ls.execute(delete(SyncOutbox).where(SyncOutbox.synced_at < cutoff))


# --- pushing one record ---------------------------------------------------------------------------


def _columns(model: type, skip: tuple[str, ...] = ("id",)) -> list[str]:
    return [c.key for c in model.__table__.columns if c.key not in skip]  # type: ignore[attr-defined]


def _cloud_org(cs: Session, org: Organization) -> Organization:
    """The cloud row for this organization code, created or brought up to date (its id there
    is its own)."""
    row = cs.scalar(select(Organization).where(Organization.org_code == org.org_code))
    if row is None:
        row = Organization(**{c: getattr(org, c) for c in _columns(Organization)})
        cs.add(row)
    else:
        for c in _columns(Organization, ("id", "created_at")):
            setattr(row, c, getattr(org, c))
    cs.flush()
    return row


def _cloud_student(cs: Session, student: StudentProfile, ls: Session) -> StudentProfile:
    """The cloud row for this username, created or brought up to date (its id there is its
    own, and so is its organization's: `ls` is the local session that knows the local one)."""
    values = {c: getattr(student, c) for c in _columns(StudentProfile)}
    org = ls.get(Organization, student.org_id) if student.org_id is not None else None
    values["org_id"] = _cloud_org(cs, org).id if org is not None else None
    row = cs.scalar(select(StudentProfile).where(StudentProfile.username == student.username))
    if row is None:
        row = StudentProfile(**values)
        cs.add(row)
    else:
        for c, v in values.items():
            if c != "created_at":
                setattr(row, c, v)
    cs.flush()
    return row


def _push(ls: Session, cs: Session, item: SyncOutbox, device: str) -> None:
    model = ENTITIES[item.entity]
    row = ls.get(model, item.local_id)
    if row is None:
        return  # deleted locally since (a student removed): nothing left to send
    if item.entity == "organization":
        _cloud_org(cs, row)  # type: ignore[arg-type]
        return
    if item.entity == "student":
        _cloud_student(cs, row, ls)  # type: ignore[arg-type]
        return
    student = ls.get(StudentProfile, row.student_id)  # type: ignore[attr-defined]
    if student is None:
        return
    cloud_sid = _cloud_student(cs, student, ls).id
    if item.entity == "plan":
        plan = cs.scalar(
            select(StudyPlan).where(
                StudyPlan.student_id == cloud_sid,
                StudyPlan.week_number == row.week_number,  # type: ignore[attr-defined]
            )
        )
        if plan is None:
            plan = StudyPlan(student_id=cloud_sid, week_number=row.week_number)  # type: ignore[attr-defined]
            cs.add(plan)
        plan.plan_data, plan.completed_tasks = row.plan_data, row.completed_tasks  # type: ignore[attr-defined]
        return
    key = f"{device}:{item.entity}:{item.local_id}"
    if cs.get(SyncReceipt, key) is not None:
        return  # it arrived before; the local "synced" mark was what got lost
    values = {c: getattr(row, c) for c in _columns(model)} | {"student_id": cloud_sid}
    clone = model(**values)
    cs.add(clone)
    cs.flush()
    cs.add(SyncReceipt(source_key=key, cloud_id=clone.id))  # type: ignore[attr-defined]


# --- the process-wide manager ------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_manager() -> DatabaseManager:
    """The process-wide manager, configured from settings (SUPABASE_DB_URL or DATABASE_URL, and
    TELEMETRY_DB_PATH)."""
    s = settings()
    return DatabaseManager(s.database_url, s.telemetry_db_path)


def reset_manager() -> None:
    """Drop the process-wide manager (tests; or to pick up a changed URL)."""
    if get_manager.cache_info().currsize:
        get_manager().dispose()
    get_manager.cache_clear()
