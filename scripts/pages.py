"""The app's student pages and an isolated environment to run it in, for the dev checks
(scripts/ci_check.py renders every page headless; scripts/perf.py times them)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPage:
    slug: str
    title: str  # navigation label, as passed to st.Page in app.py
    path: str  # page file, as passed to st.Page / AppTest.switch_page


PAGES = (
    # the placement journey
    AppPage("onboard", "1. Onboarding and profile", "views/onboard.py"),
    AppPage("scanner", "2. Resume scan and skill gaps", "views/scanner.py"),
    AppPage("roadmap", "3. 7-day study roadmap", "views/roadmap.py"),
    AppPage("critic_quiz", "4. Critic-checked quiz", "views/critic_quiz.py"),
    AppPage("voice_interview", "5. Proctored voice assessment", "views/voice_interview.py"),
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
STUDENT_ONLY = {"projects"}  # in the navigation only once a (computing) student is chosen


def isolated_env(tmp: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for running the app: mock LLM, throwaway database, no .env, no Groq keys."""
    env = dict(base if base is not None else os.environ)
    for key in [k for k in env if k.startswith(("GROQ_", "STREAMLIT_"))]:
        del env[key]
    env.update(
        PIQ_DOTENV=str(tmp / "no-such.env"),
        MOCK_MODE="true",
        DB_PATH=str(tmp / "app.db"),
        PRELOAD_CACHE_DIR=str(tmp / "preload"),  # speculative results stay out of data/
        PYTHONIOENCODING="utf-8",
    )
    return env
