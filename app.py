"""Streamlit entry point: `streamlit run app.py`."""

import logging

import streamlit as st

from piq import db, formatter, journey, services
from piq.config import BRAND_DIR, ConfigError, settings
from piq.ui import current_student, load_css, sidebar_context, student_selector
from scripts.seed import main as seed_demo
from scripts.seed_cohort import main as seed_cohort

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
st.set_page_config(
    page_title="Skill Scout Nexus", page_icon=str(BRAND_DIR / "mark.svg"), layout="wide"
)
st.logo(str(BRAND_DIR / "wordmark.svg"), icon_image=str(BRAND_DIR / "mark.svg"), size="large")
load_css()

try:
    cfg = settings()
except ConfigError as e:
    st.error(formatter.md_escape(str(e)))
    st.stop()


@st.cache_resource
def _startup() -> None:
    db.init_db()
    if cfg.seed_demo and not db.list_students():  # hosted disks reset on every restart
        seed_demo()
    if cfg.seed_demo and not journey.cohort_view().rows:  # the faculty dashboard's demo cohort
        seed_cohort([])
    journey.start_sync()  # records made while offline go to the cloud copy, in the background
    logging.getLogger("piq").info(
        "mock_mode=%s large=%s small=%s db=%s",
        cfg.mock_mode,
        cfg.model_large or "-",
        cfg.model_small or "-",
        cfg.db_path,
    )


_startup()

student_selector()
engine = journey.engine_status()  # one router check feeds both the badge and the footer line
sidebar_context(mock_mode=cfg.mock_mode, ai=engine.active_ai, engine=engine.line)

# Computing domains get a Project space; the selected student's row already names the role.
student = current_student()
code_space = bool(student) and services.domain_of_role(student["target_role"]).code_space
projects = (
    [st.Page("views/projects.py", title="Project space", icon=":material/folder_code:")]
    if code_space
    else []
)

# Sidebar navigation keeps every page visible with the student context beneath it; a top
# bar would fold the sections into menus, which is worse on a projector (docs/design).
# The six numbered steps come first; the earlier tools stay one group below.
page = st.navigation(
    {
        "Placement journey": [
            st.Page(
                "views/onboard.py", title="1. Onboarding and profile", icon=":material/person_add:"
            ),
            st.Page(
                "views/scanner.py",
                title="2. Resume scan and skill gaps",
                icon=":material/document_scanner:",
            ),
            st.Page("views/roadmap.py", title="3. 7-day study roadmap", icon=":material/route:"),
            st.Page(
                "views/critic_quiz.py", title="4. Critic-checked quiz", icon=":material/verified:"
            ),
            st.Page(
                "views/voice_interview.py",
                title="5. Proctored voice assessment",
                icon=":material/graphic_eq:",
            ),
            st.Page("views/faculty.py", title="6. Faculty dashboard", icon=":material/school:"),
        ],
        "More tools": [
            st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
            st.Page("views/resume_builder.py", title="Resume builder", icon=":material/badge:"),
            *projects,
            st.Page("views/plan.py", title="Weekly plan", icon=":material/calendar_month:"),
            st.Page("views/quiz.py", title="Quiz", icon=":material/quiz:"),
            st.Page(
                "views/interview.py", title="Mock interview", icon=":material/record_voice_over:"
            ),
            st.Page("views/dashboard.py", title="Dashboard", icon=":material/monitoring:"),
            st.Page("views/results.py", title="Results", icon=":material/fact_check:"),
        ],
    },
    position="sidebar",
    expanded=True,  # every page listed: no "View more" fold hiding the earlier tools
)
try:
    page.run()
except Exception:  # the last line of defence: a page bug shows a message, never a traceback
    logging.getLogger("piq.app").exception("page %s failed", page.url_path)
    if cfg.raise_page_errors:  # tests: let AppTest see the exception
        raise
    st.error(
        "Something went wrong on this page. Your saved work is safe; try again, or open "
        "another page from the sidebar.",
        icon=":material/error:",
    )
