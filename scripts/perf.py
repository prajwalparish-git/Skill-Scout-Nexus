"""Server-side render time per page (dev tool; no browser).

    python -m scripts.perf docs/design/perf-before.md [--runs 7] [--mode fresh|rerun]

In an isolated environment (MOCK_MODE, a temporary database seeded with the demo student,
the developer's .env ignored, Groq never contacted) it renders every page with Streamlit's
AppTest with DEMO0001 selected: 1 warm-up and N timed runs each. It reports the median
and p90 render time, the SQLite calls and statements per render (counted by temporarily
wrapping piq.db.tx), the cold start (a fresh process up to its first full render) and the
size of static/. The markdown table goes to stdout and to the given path.
"""

import argparse
import contextlib
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Runs in a fresh interpreter, so the timing includes imports and the first render.
_COLD_START = """
import time; t0 = time.perf_counter()
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(r"{app}", default_timeout=120)
at.session_state["student_id"] = "{sid}"
at.run()
assert not at.exception, [e.value for e in at.exception]
print((time.perf_counter() - t0) * 1000)
"""


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile, so p90 of 7 samples is the 7th-fastest, never interpolated."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class _CountingConnection:
    """Delegates to a sqlite3 connection and counts the statements sent through it."""

    def __init__(self, conn: Any, counts: dict[str, int]) -> None:
        self._conn, self._counts = conn, counts

    def _count(self, name: str) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._counts["statements"] += 1
            return getattr(self._conn, name)(*args, **kwargs)

        return wrapper

    def __getattr__(self, name: str) -> Any:
        if name in ("execute", "executemany", "executescript"):
            return self._count(name)
        return getattr(self._conn, name)


@contextlib.contextmanager
def counting_queries(db_module: ModuleType) -> Iterator[dict[str, int]]:
    """Temporarily wrap `db_module.tx`; counts["calls"] = connections, ["statements"] = SQL."""
    counts = {"calls": 0, "statements": 0}
    real = db_module.tx

    @contextlib.contextmanager
    def tx() -> Iterator[_CountingConnection]:
        counts["calls"] += 1
        with real() as conn:
            yield _CountingConnection(conn, counts)

    db_module.tx = tx
    try:
        yield counts
    finally:
        db_module.tx = real


def markdown_table(rows: list[dict], cold_ms: float, static_bytes: int, runs: int) -> str:
    lines = [
        f"Render time per page (AppTest, MOCK_MODE, demo student; 1 warm-up + {runs} runs)",
        "",
        "| Page | Median (ms) | p90 (ms) | DB calls | SQL statements |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['page']} | {r['median']:.0f} | {r['p90']:.0f} | {r['calls']} | {r['statements']} |"
        for r in rows
    ]
    lines += [
        "",
        f"Cold start (fresh process to first full render): {cold_ms:.0f} ms",
        f"static/ total: {static_bytes / 1024:.1f} KB",
    ]
    return "\n".join(lines) + "\n"


MODES = {
    "fresh": "a new AppTest for every run: includes AppTest's own per-instance setup (it "
    "scans every installed package for components, which a server does once at start)",
    "rerun": "one AppTest per page, run again: the page's own render cost, as when a "
    "student moves between pages in one session",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path, help="markdown file to write, e.g. docs/design/perf.md")
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument(
        "--mode",
        choices=list(MODES),
        default="fresh",
        help="; ".join(f"{k}: {v}" for k, v in MODES.items()),
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from scripts.screenshots import PAGES, isolated_env

    with tempfile.TemporaryDirectory() as tmp:
        env = isolated_env(Path(tmp)) | {"SEED_DEMO": "false"}  # seeded explicitly below
        os.environ.clear()
        os.environ.update(env)

        from streamlit.testing.v1 import AppTest

        from piq import db
        from piq.config import settings
        from scripts import seed

        settings.cache_clear()
        db.init_db()
        seed.main()
        sid = next(s["id"] for s in db.list_students() if s["username"] == seed.USERNAME)

        cold = subprocess.run(
            [sys.executable, "-c", _COLD_START.format(app=ROOT / "app.py", sid=sid)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        cold_ms = float(cold.stdout.strip().splitlines()[-1])

        rows = []
        for page in PAGES:
            times, counts = [], {}
            at = None
            for i in range(args.runs + 1):  # run 0 is the warm-up
                if at is None or args.mode == "fresh":
                    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
                    at.session_state["student_id"] = sid
                    at.switch_page(page.path)
                with counting_queries(db) as c:
                    started = time.perf_counter()
                    at.run()
                    elapsed = (time.perf_counter() - started) * 1000
                if at.exception:
                    raise SystemExit(f"{page.title} raised: {at.exception[0].value}")
                if i:
                    times.append(elapsed)
                    counts = dict(c)
            rows.append(
                {
                    "page": page.title,
                    "median": statistics.median(times),
                    "p90": percentile(times, 90),
                    **counts,
                }
            )
            print(f"{page.title}: median {rows[-1]['median']:.0f} ms", flush=True)

    table = markdown_table(rows, cold_ms, dir_size(ROOT / "static"), args.runs)
    table += f"\nMode: {args.mode} ({MODES[args.mode]}).\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(table, encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
