"""Project space (computing domains): the student's repositories in one place, GitHub-style:
what each project is, its stack and link, a README, a log of the work done on it and a
contribution calendar. Projects marked "On resume" feed the Resume builder."""

import streamlit as st

from core import github_readme as gh
from piq import charts, formatter, services
from piq.config import PROJECT_STATUSES
from piq.ui import Stat, empty_state, page_header, require_profile, stat_row

# Session-state keys used by the GitHub importer
_GH_INTEL = "gh_intel"  # last GitHubIntelligence result
_GH_URL = "gh_url_last"  # URL that produced that result (to avoid re-fetching on rerun)


def _fields(prefix: str, row: dict | None = None) -> dict:
    """The project inputs (inside a form), prefilled from `row` when editing."""
    row = row or {}
    if not row and prefix == "new":
        intel = st.session_state.get(_GH_INTEL)
        if intel and not intel.is_empty:
            bullets = list(intel.star_bullets)
            desc = intel.one_line_pitch
            summary_lines = [desc, *bullets] if desc else bullets
            row = {
                "name": intel.project_title,
                "repo_url": st.session_state.get(_GH_URL, ""),
                "tech": ", ".join(intel.tech_stack),
                "status": "Done",
                "summary": "\n".join(summary_lines),
                "readme": st.session_state.get("gh_readme_raw", ""),
                "on_resume": True,
            }
    name = st.text_input("Repository name *", value=row.get("name", ""), key=f"{prefix}_name")
    repo = st.text_input(
        "Repository link",
        value=row.get("repo_url", ""),
        placeholder="https://github.com/you/project",
        key=f"{prefix}_repo",
    )
    tech = st.text_input(
        "Stack (comma-separated)",
        value=row.get("tech", ""),
        placeholder="e.g. C, STM32, FreeRTOS",
        key=f"{prefix}_tech",
    )
    status = st.segmented_control(
        "Status",
        PROJECT_STATUSES,
        default=row.get("status", "In progress"),
        required=True,
        key=f"{prefix}_status",
    )
    summary = st.text_area(
        "Highlights (one per line; the first is the description, all become resume bullets)",
        value=row.get("summary", ""),
        placeholder="Logged sensor data at 1 kHz to an SD card\nCut data loss below 0.1% with DMA",
        key=f"{prefix}_summary",
        height=100,
    )
    readme = st.text_area("README", value=row.get("readme", ""), key=f"{prefix}_readme", height=140)
    on_resume = st.checkbox(
        "On resume", value=bool(row.get("on_resume", True)), key=f"{prefix}_resume"
    )
    return {
        "name": name,
        "repo_url": repo,
        "tech": tech,
        "status": status,
        "summary": summary,
        "readme": readme,
        "on_resume": on_resume,
    }


def _save(sid: str, fields: dict, project_id: int | None = None) -> bool:
    try:
        services.save_project(sid, project_id=project_id, **fields)
    except services.ServiceError as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")
        return False
    return True


def _repository(sid: str, row, updates: list) -> None:
    pid = row["id"]
    with st.container(border=True):
        st.markdown(formatter.project_head_md(row))
        st.markdown(formatter.project_meta_md(row, row["updates"]))
        with st.expander("README and work log", icon=":material/menu_book:"):
            st.markdown(formatter.readme_md(row["readme"]))
            st.markdown("**Work log**")
            mine = [u for u in updates if u["project_id"] == pid]
            if mine:
                st.markdown("  \n".join(formatter.update_line_md(u) for u in mine[:10]))
            else:
                st.caption("No updates yet. Log what you did each time you work on it.")
            with st.form(f"log_{pid}", border=False, clear_on_submit=True):
                note = st.text_input(
                    "Log an update",
                    placeholder="e.g. Added DMA for UART receive",
                    key=f"note_{pid}",
                )
                if st.form_submit_button("Log update", icon=":material/commit:"):
                    try:
                        services.log_project_update(sid, pid, note)
                    except services.ServiceError as e:
                        st.error(formatter.md_escape(str(e)), icon=":material/error:")
                    else:
                        st.rerun()
        with st.expander("Edit", icon=":material/edit:"):
            with st.form(f"edit_{pid}", border=False):
                fields = _fields(f"edit_{pid}", dict(row))
                if st.form_submit_button("Save changes", type="primary") and _save(
                    sid, fields, pid
                ):
                    st.rerun()
            with st.popover("Delete repository", icon=":material/delete:"):
                st.markdown(f"Delete **{formatter.md_escape(row['name'])}** and its work log?")
                if st.button("Delete for good", type="primary", key=f"del_{pid}"):
                    services.delete_project(sid, pid)
                    st.rerun()


page_header(
    "Project space",
    "Your repositories in one place: what each project is, its stack and link, a README and "
    "a log of your work. Projects marked On resume go into the Resume builder.",
)
sid, profile = require_profile()
if not services.has_project_space(profile):
    empty_state(
        "code_off",
        "Not part of your domain",
        "The Project space is for computing domains. Add your projects in the Resume builder.",
    )
    st.stop()

space = services.project_space(sid)
today = formatter.local_today()
recent = sum(n for day, n in space.activity.items() if (today - day).days < 7 * 12)
stat_row(
    [
        Stat("Repositories", str(len(space.projects))),
        Stat("Done", str(sum(p["status"] == "Done" for p in space.projects))),
        Stat("In progress", str(sum(p["status"] == "In progress" for p in space.projects))),
        Stat("Updates, last 12 weeks", str(recent)),
    ]
)

list_col, side_col = st.columns([3, 2], gap="medium")
with list_col:
    # --- GitHub README importer -----------------------------------------------------------
    has_intel = bool(st.session_state.get(_GH_INTEL))
    with st.expander(
        "Import project from GitHub URL",
        icon=":material/cloud_download:",
        expanded=has_intel,
    ):
        st.caption(
            "Paste any public GitHub repository URL to auto-fill the project name, tech stack, "
            "STAR resume bullets, and 2 viva questions for your voice interview."
        )
        gh_url = st.text_input(
            "Import Project from GitHub URL",
            placeholder="https://github.com/username/repo",
            key="gh_import_url",
        )
        col_fetch, col_clear = st.columns([2, 1], gap="small")
        with col_fetch:
            fetch_clicked = st.button(
                "Import from GitHub",
                type="primary",
                icon=":material/hub:",
                key="gh_import_btn",
                disabled=not gh_url.strip(),
            )
        with col_clear:
            if st.button("Clear", icon=":material/close:", key="gh_clear_btn"):
                st.session_state.pop(_GH_INTEL, None)
                st.session_state.pop(_GH_URL, None)
                st.session_state.pop("gh_readme_raw", None)
                st.session_state.pop(gh.VIVA_SESSION_KEY, None)
                st.rerun()

        if fetch_clicked and gh_url.strip():
            if gh_url.strip() == st.session_state.get(_GH_URL):
                st.info("Already imported. Clear and re-import to refresh.", icon=":material/info:")
            else:
                # Validate URL format before hitting the network
                if not gh.parse_github_url(gh_url.strip()):
                    st.error(
                        "That doesn't look like a GitHub repository URL. "
                        "Use the format https://github.com/owner/repo.",
                        icon=":material/error:",
                    )
                else:
                    with st.spinner("Fetching README …"):
                        readme = gh.fetch_readme(gh_url.strip())
                    if readme is None:
                        st.error(
                            "Could not fetch the README. Make sure the repository is public "
                            "and has a README.md at the root.",
                            icon=":material/error:",
                        )
                    else:
                        st.session_state["gh_readme_raw"] = readme
                        with st.spinner("Extracting project intelligence …"):
                            intel = gh.extract_github_intelligence(readme)
                        if intel.is_empty:
                            st.warning(
                                "README fetched but structured extraction failed. "
                                "Try a repository with a more detailed README.",
                                icon=":material/warning:",
                            )
                        else:
                            st.session_state[_GH_INTEL] = intel
                            st.session_state[_GH_URL] = gh_url.strip()
                            # Save viva questions for the Voice Interviewer
                            if intel.viva_questions:
                                st.session_state[gh.VIVA_SESSION_KEY] = intel.viva_questions
                            st.rerun()

        # Display last successful result
        intel = st.session_state.get(_GH_INTEL)
        if intel and not intel.is_empty:
            st.success(
                f"Imported: **{formatter.md_escape(intel.project_title)}**",
                icon=":material/task_alt:",
            )
            st.markdown(formatter.github_intelligence_md(intel))
            st.divider()
            st.caption(
                ":material/auto_awesome: The **New repository** form below has been prefilled with "
                "your STAR bullets and tech stack!"
            )
            if intel.viva_questions:
                st.caption(
                    ":material/mic: Viva questions are saved and will appear in your next "
                    "Voice Interview automatically."
                )

    # --- New repository form --------------------------------------------------------------
    new_expanded = not space.projects or bool(st.session_state.get(_GH_INTEL))
    with (
        st.expander("New repository", icon=":material/add:", expanded=new_expanded),
        st.form("new_project", border=False, clear_on_submit=True),
    ):
        fields = _fields("new")
        if st.form_submit_button("Create repository", type="primary") and _save(sid, fields):
            st.rerun()
    if not space.projects:
        st.caption("No repositories yet. Add one above; finished ones belong on your resume.")
    for row in space.projects:
        _repository(sid, row, space.updates)

with side_col:
    with st.container(border=True):
        noun = "update" if recent == 1 else "updates"
        st.subheader(f"{recent} {noun} in the last 12 weeks", anchor=False)
        st.vega_lite_chart(
            spec=charts.activity_heatmap_spec(space.activity, today),
            width="stretch",
            alt=f"Project updates over the last 12 weeks: {recent} in all.",
        )
        st.caption(
            "Your contribution calendar: one square per day, stronger teal for more updates."
        )
    with st.container(border=True):
        st.subheader("Latest activity", anchor=False)
        if space.updates:
            st.markdown(
                "  \n".join(
                    f"**{formatter.md_escape(u['project'])}** {formatter.update_line_md(u)}"
                    for u in space.updates[:8]
                )
            )
        else:
            st.caption("Updates you log on any repository appear here.")
