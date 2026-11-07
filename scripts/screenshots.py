"""Capture every page and key flow for visual review (dev tool; Playwright + Chromium).

    python -m scripts.screenshots docs/design/before
    python -m scripts.screenshots docs/design/after --widths 1440,390 --schemes light

For each colour scheme it starts the app on a fresh, isolated database (MOCK_MODE and
SEED_DEMO on, the developer's .env ignored, Groq never contacted) and captures:
  * every page with no student selected and with the demo student selected
  * key in-flow states: an onboarding error, a new plan week, the critic loop, quiz
    taking and review, an interview mid-session and complete
at each viewport width, as <page>-<state>-<width>-<scheme>.png, compressed to about
250 KB or less. Browser console errors are printed and make the run exit with status 1.

Never imported by the app; the test suite exercises only the pure helpers.
"""

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parent.parent
PORT = 8599
VIEWPORTS = {1440: 900, 1366: 768, 390: 844}  # width -> height
SCHEMES = ("light", "dark")
MAX_BYTES = 250_000
MAX_SHOT_HEIGHT = 9000  # px; longer pages are cut here
DEMO_OPTION = "DEMO0001 — Demo Student"  # sidebar option text, see piq.ui.student_selector


@dataclass(frozen=True)
class AppPage:
    slug: str
    title: str  # navigation label, as passed to st.Page in app.py
    path: str  # page file, as passed to st.Page / AppTest.switch_page


PAGES = (
    # the six-step placement journey
    AppPage("onboard", "1. Onboarding and profile", "views/onboard.py"),
    AppPage("scanner", "2. Resume scan and skill gaps", "views/scanner.py"),
    AppPage("roadmap", "3. 7-day study roadmap", "views/roadmap.py"),
    AppPage("critic_quiz", "4. Critic-checked quiz", "views/critic_quiz.py"),
    AppPage("voice_interview", "5. Proctored voice assessment", "views/voice_interview.py"),
    AppPage("faculty", "6. Faculty dashboard", "views/faculty.py"),
    # more tools
    AppPage("home", "Home", "views/home.py"),
    AppPage("resume_builder", "Resume builder", "views/resume_builder.py"),
    AppPage("projects", "Project space", "views/projects.py"),  # computing domains only
    AppPage("plan", "Weekly plan", "views/plan.py"),
    AppPage("quiz", "Quiz", "views/quiz.py"),
    AppPage("interview", "Mock interview", "views/interview.py"),
    AppPage("dashboard", "Dashboard", "views/dashboard.py"),
    AppPage("results", "Results", "views/results.py"),
)
STATES = ("nostudent", "demo")
STUDENT_ONLY = {"projects"}  # in the navigation only once a (computing) student is chosen
FLOWS = (
    ("onboard", "error"),
    ("plan", "newweek"),
    ("quiz", "critic"),
    ("quiz", "taking"),
    ("quiz", "review"),
    ("interview", "mid"),
    ("interview", "complete"),
)
# Text that must be on screen before a state is captured, so a wrong state fails the run
# instead of being saved. Mostly strings the UI tests also rely on (stable by contract).
MARKERS = {
    ("home", "nostudent"): "Start with your resume",
    ("home", "demo"): "Today's focus",
    ("resume_builder", "nostudent"): "Resume builder",
    ("resume_builder", "demo"): "What to add next",
    # Without a student the page is not in the navigation, so its URL lands on Home.
    ("projects", "nostudent"): "Start with your resume",
    ("projects", "demo"): "Project space",
    ("onboard", "nostudent"): "Analyse resume",
    ("plan", "nostudent"): "No student selected",
    ("quiz", "nostudent"): "No student selected",
    ("interview", "nostudent"): "No student selected",
    ("voice_interview", "nostudent"): "No student selected",
    ("scanner", "nostudent"): "No student selected",
    ("roadmap", "nostudent"): "No student selected",
    ("critic_quiz", "nostudent"): "No student selected",
    # The faculty page needs no student; SEED_DEMO gives it the demo cohort.
    ("faculty", "nostudent"): "Export placement readiness report",
    ("faculty", "demo"): "Export placement readiness report",
    ("scanner", "demo"): "Scan resume",
    ("roadmap", "demo"): "Skills to cover",
    ("critic_quiz", "demo"): "Generate quiz",
    ("dashboard", "nostudent"): "No student selected",
    ("results", "nostudent"): "Baseline",
    ("onboard", "demo"): "Missing for this role",
    ("plan", "demo"): "Generate week 5 plan",
    ("quiz", "demo"): "Generate quiz",
    ("interview", "demo"): "Start session",
    ("voice_interview", "demo"): "Generate question",
    ("dashboard", "demo"): "Quizzes taken",
    ("results", "demo"): "Baseline",
    ("onboard", "error"): "Upload a resume or pick a sample",
    ("plan", "newweek"): "Generate week 6 plan",
    ("quiz", "critic"): "Critic rejected the quiz",
    ("quiz", "taking"): "Submit",
    ("quiz", "review"): "Where the marks went",
    ("interview", "mid"): "You said 'I like coding",
    ("interview", "complete"): "Session complete",
}
# Detailed (>= 25 words) and distinct, so the mock moves on instead of probing them.
INTERVIEW_ANSWERS = (
    "In my final year project I led a team of four to build an attendance tracker in Flask; "
    "I designed the schema and API, and manual entry time dropped by about seventy percent.",
    "During my internship a nightly report job kept timing out, so I profiled the queries, "
    "added two indexes and batched the inserts, which cut the run from forty to six minutes.",
    "When two teammates disagreed about the database design, I set up a short call, listed "
    "the trade-offs in a table, and we agreed on a hybrid that we delivered a week early.",
    "I prepare for exams by solving previous papers under time limits, reviewing every "
    "mistake the same evening, and keeping a notebook of patterns that I revise each Sunday.",
)


# --- pure helpers (unit-tested) ------------------------------------------------


def shot_name(page: str, state: str, width: int, scheme: str) -> str:
    return f"{page}-{state}-{width}-{scheme}.png"


def parse_widths(raw: str) -> list[int]:
    widths = [int(w) for w in raw.split(",") if w.strip()]
    unknown = [w for w in widths if w not in VIEWPORTS]
    if unknown or not widths:
        raise ValueError(f"widths must be from {sorted(VIEWPORTS)}, got {raw!r}")
    return widths


def parse_schemes(raw: str) -> list[str]:
    schemes = [s.strip() for s in raw.split(",") if s.strip()]
    if not schemes or any(s not in SCHEMES for s in schemes):
        raise ValueError(f"schemes must be from {SCHEMES}, got {raw!r}")
    return schemes


def parse_pages(raw: str) -> set[str]:
    """Page slugs to capture ("" = all); flows follow their page."""
    slugs = {s.strip() for s in raw.split(",") if s.strip()}
    known = {p.slug for p in PAGES}
    if slugs - known:
        raise ValueError(f"pages must be from {sorted(known)}, got {raw!r}")
    return slugs or known


def planned_shots(widths: list[int], schemes: list[str]) -> list[str]:
    """Every file one run writes, in capture order."""
    names = []
    for scheme in schemes:
        names += [
            shot_name(p.slug, state, w, scheme) for state in STATES for p in PAGES for w in widths
        ]
        names += [shot_name(page, state, w, scheme) for page, state in FLOWS for w in widths]
    return names


def isolated_env(tmp: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the app server: mock LLM, throwaway database, no .env, no Groq keys."""
    env = {k: v for k, v in (base if base is not None else os.environ).items()}
    for key in [k for k in env if k.startswith(("GROQ_", "STREAMLIT_"))]:
        del env[key]
    env.update(
        PIQ_DOTENV=str(tmp / "no-such.env"),
        MOCK_MODE="true",
        SEED_DEMO="true",
        DB_PATH=str(tmp / "screenshots.db"),
        PRELOAD_CACHE_DIR=str(tmp / "preload"),  # speculative results stay out of data/
        PYTHONIOENCODING="utf-8",
    )
    return env


def compress_png(path: Path, max_bytes: int = MAX_BYTES) -> int:
    """Rewrite `path` smaller: lossless first, then fewer palette colours until it fits."""
    from PIL import Image

    with Image.open(path) as img:
        rgb = img.convert("RGB")
    rgb.save(path, optimize=True)
    for colours in (256, 128, 64):
        if path.stat().st_size <= max_bytes:
            break
        rgb.quantize(
            colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        ).save(path, optimize=True)
    return path.stat().st_size


# --- server --------------------------------------------------------------------


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@contextlib.contextmanager
def running_app(env: dict[str, str], port: int) -> Iterator[str]:
    if _port_in_use(port):
        raise SystemExit(f"port {port} is busy; stop that server or pass --port")
    cmd = [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true"]
    cmd += ["--server.port", str(port), "--browser.gatherUsageStats", "false"]
    proc = subprocess.Popen(
        cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    url = f"http://localhost:{port}/"
    try:
        for _ in range(120):
            with contextlib.suppress(OSError):
                urllib.request.urlopen(url + "_stcore/health", timeout=2)
                break
            time.sleep(0.5)
        else:
            raise SystemExit("the app did not become healthy within 60 s")
        yield url
    finally:
        proc.terminate()
        proc.communicate(timeout=30)


@contextlib.contextmanager
def results_summary_present() -> Iterator[None]:
    """Render a populated Results page without ever overwriting a real summary.json."""
    from piq.config import RESULTS_DIR

    summary = RESULTS_DIR / "summary.json"
    if summary.exists():
        yield
        return
    from tests.factories import eval_summary

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(eval_summary(mode="mock")), encoding="utf-8")
    try:
        yield
    finally:
        summary.unlink(missing_ok=True)


# --- browser -------------------------------------------------------------------

_STATE = "document.querySelector('[data-testid=stApp]')?.getAttribute('data-test-script-state')"
# Streamlit scrolls inside its own containers (a chat page inside the scroll-to-bottom one),
# so measure them, not just the document.
_CONTENT_HEIGHT = (
    "() => Math.max(document.documentElement.scrollHeight, ...[...document.querySelectorAll("
    "'[data-testid=stMain], [data-testid=stAppViewContainer], "
    "[data-testid=stAppScrollToBottomContainer]')].map(e => e.scrollHeight))"
)


def _wait_idle(page: "Page", expect_run: bool = True) -> None:
    """Wait until the script has rerun (if expected) and finished, then let charts settle."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    if expect_run:
        with contextlib.suppress(PlaywrightTimeout):
            page.wait_for_function(f"{_STATE} === 'running'", timeout=2500)
    page.wait_for_function(f"{_STATE} === 'notRunning'", timeout=120_000)
    page.evaluate("document.fonts.ready.then(() => true)")
    page.wait_for_timeout(800)


def _expect(page: "Page", slug: str, state: str) -> None:
    """Fail the run, loudly, unless the state's marker text is on screen."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    text = MARKERS[(slug, state)]
    try:
        page.get_by_text(text).first.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeout:
        raise SystemExit(
            f"{slug}-{state}: {text!r} is not on screen, so the app is not in the intended "
            "state; no screenshot saved"
        ) from None


def _open_sidebar(page: "Page") -> None:
    expand = page.get_by_test_id("stExpandSidebarButton")
    if expand.is_visible():
        expand.click()
        page.wait_for_timeout(400)


def _select_student(page: "Page", option: str) -> None:
    _open_sidebar(page)
    page.get_by_test_id("stSidebar").get_by_role("combobox", name="Student").click()
    page.get_by_role("option", name=option).click()
    _wait_idle(page)


def _goto(page: "Page", title: str) -> None:
    _open_sidebar(page)
    page.get_by_test_id("stSidebarNavLink").filter(has_text=title).first.click()
    _wait_idle(page)


def _click(page: "Page", label: str, exact: bool = True) -> None:
    page.get_by_role("button", name=label, exact=exact).first.click()
    _wait_idle(page)


def _answer_chat(page: "Page", text: str) -> None:
    box = page.get_by_test_id("stChatInputTextArea")
    box.fill(text)
    box.press("Enter")
    _wait_idle(page)


def _capture(page: "Page", out: Path, name: str, width: int) -> Path:
    page.set_viewport_size({"width": width, "height": VIEWPORTS[width]})
    page.wait_for_timeout(600)  # relayout; the sidebar collapses by itself at mobile width
    page.mouse.move(width - 2, 2)  # park the pointer: no hover state in the shot
    full = page.evaluate(_CONTENT_HEIGHT)
    height = min(max(VIEWPORTS[width], int(full)), MAX_SHOT_HEIGHT)
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(400)
    path = out / name
    page.screenshot(path=str(path), full_page=True)
    page.set_viewport_size({"width": width, "height": VIEWPORTS[width]})
    compress_png(path)
    return path


def _capture_widths(
    page: "Page",
    out: Path,
    slug: str,
    state: str,
    widths: list[int],
    scheme: str,
    written: list[Path],
) -> None:
    _expect(page, slug, state)
    for w in widths:
        written.append(_capture(page, out, shot_name(slug, state, w, scheme), w))
    page.set_viewport_size({"width": 1440, "height": VIEWPORTS[1440]})
    page.wait_for_timeout(300)


def capture_scheme(
    url: str,
    out: Path,
    scheme: str,
    widths: list[int],
    errors: list[str],
    only: set[str] | None = None,
) -> list[Path]:
    only = only or {p.slug for p in PAGES}
    from playwright.sync_api import sync_playwright

    written: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": VIEWPORTS[1440]}, color_scheme=scheme
        )
        page = context.new_page()
        where = {"step": "load"}
        page.on(
            "console",
            lambda m: (
                errors.append(f"[{scheme} {where['step']}] console: {m.text}")
                if m.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda e: errors.append(f"[{scheme} {where['step']}] pageerror: {e}"))
        page.goto(url)
        _wait_idle(page, expect_run=False)

        for state in STATES:
            if state == "demo":
                where["step"] = "select demo student"
                _select_student(page, DEMO_OPTION)
            for p in (p for p in PAGES if p.slug in only):
                where["step"] = f"{p.slug} ({state})"
                # A page only some students get has no link before one is chosen: what a
                # visitor sees then is Home.
                _goto(page, "Home" if state == "nostudent" and p.slug in STUDENT_ONLY else p.title)
                _capture_widths(page, out, p.slug, state, widths, scheme, written)

        if "onboard" in only:
            where["step"] = "onboard: re-profile without a resume"
            _goto(page, "Onboard")
            page.get_by_text("Re-profile with a new resume").click()
            page.wait_for_timeout(400)
            _click(page, "Analyse resume")
            _capture_widths(page, out, "onboard", "error", widths, scheme, written)
        if "plan" in only:
            where["step"] = "plan: generate a new week"
            _goto(page, "Weekly plan")
            _click(page, "Generate week", exact=False)
            _capture_widths(page, out, "plan", "newweek", widths, scheme, written)
        if "quiz" in only:
            _quiz_flow(page, out, widths, scheme, written, where)
        if "interview" in only:
            _interview_flow(page, out, widths, scheme, written, where)
        browser.close()
    return written


def _quiz_flow(
    page: "Page", out: Path, widths: list[int], scheme: str, written: list[Path], where: dict
) -> None:
    where["step"] = "quiz: generate (critic loop)"
    _goto(page, "Quiz")
    _click(page, "Generate quiz")
    _capture_widths(page, out, "quiz", "critic", widths, scheme, written)
    where["step"] = "quiz: answer"
    radios = page.get_by_test_id("stRadio").all()
    for radio in radios:
        radio.get_by_role("radio").first.check(force=True)  # inputs are visually hidden
    page.wait_for_timeout(300)
    checked = page.locator("[data-testid=stRadio] input[type=radio]:checked").count()
    if not radios or checked != len(radios):
        raise SystemExit(f"quiz-taking: {checked} of {len(radios)} questions answered")
    _capture_widths(page, out, "quiz", "taking", widths, scheme, written)
    where["step"] = "quiz: review"
    _click(page, "Submit")
    _capture_widths(page, out, "quiz", "review", widths, scheme, written)


def _interview_flow(
    page: "Page", out: Path, widths: list[int], scheme: str, written: list[Path], where: dict
) -> None:
    where["step"] = "interview: start and answer vaguely"
    _goto(page, "Mock interview")
    _click(page, "Start session")
    _answer_chat(page, "I like coding.")
    _capture_widths(page, out, "interview", "mid", widths, scheme, written)
    where["step"] = "interview: finish"
    for answer in INTERVIEW_ANSWERS * 2:  # bounded; the chat input goes when it completes
        if not page.get_by_test_id("stChatInputTextArea").count():
            break
        _answer_chat(page, answer)
    _capture_widths(page, out, "interview", "complete", widths, scheme, written)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path, help="folder for the PNGs, e.g. docs/design/before")
    ap.add_argument("--widths", default="1440,1366,390")
    ap.add_argument("--schemes", default="light,dark")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--pages", default="", help="page slugs, e.g. onboard,plan (default all)")
    args = ap.parse_args(argv)
    widths, schemes = parse_widths(args.widths), parse_schemes(args.schemes)
    only = parse_pages(args.pages)
    args.out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    written: list[Path] = []
    started = time.perf_counter()
    with results_summary_present():
        for scheme in schemes:
            with (
                tempfile.TemporaryDirectory() as tmp,
                running_app(isolated_env(Path(tmp)), args.port) as url,
            ):
                print(f"{scheme}: capturing ...", flush=True)
                written += capture_scheme(url, args.out, scheme, widths, errors, only)

    sizes = [p.stat().st_size for p in written]
    print(
        f"{len(written)} screenshots in {args.out} in {time.perf_counter() - started:.0f} s; "
        f"largest {max(sizes) // 1024} KB, total {sum(sizes) // 1024} KB"
    )
    over = [p.name for p, s in zip(written, sizes, strict=True) if s > MAX_BYTES]
    if over:
        print(f"over {MAX_BYTES // 1000} KB: {', '.join(over)}")
    for e in errors:
        print(e)
    print(f"browser console errors: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
