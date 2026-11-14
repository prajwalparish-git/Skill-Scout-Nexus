"""Weekly plan: what to study on each day of the week, why, and how the plan moved since the
week before. The next week is generated from the latest weakness scores."""

from functools import partial

import streamlit as st

from core import calendar_export
from piq import charts, formatter, services, study_library
from piq.config import STUDY_TIME, TIMEZONE, WEAK_THRESHOLD
from piq.ui import empty_state, page_header, require_profile, run_agent, show_last_run


def _days_done(sid: str, week_no: int, saved: set[int]) -> set[int]:
    """Tick the days of the week you finished; a change is saved at once."""
    picked = st.pills(
        "Days done",
        list(range(1, 8)),
        selection_mode="multi",
        default=sorted(saved),
        format_func=lambda d: f"Day {d}",
        key=f"plan_done_{sid}_{week_no}",  # per student: a switch must not carry ticks over
        help="Home and the Dashboard count the days you mark here.",
        wrap=True,
    )
    if set(picked) != saved:
        return services.set_days_done(sid, week_no, picked)
    return saved


PAGE = 8  # books and repositories shown before "show all"


def _library(role: str, weakness: dict[str, float]) -> None:
    """Books for the role's track (weak topics first) and curated GitHub repositories for the
    role: the same library and ranking as the web plan page (piq/study_library.py)."""
    weak = sorted(t for t, w in weakness.items() if w > WEAK_THRESHOLD)
    with st.container(border=True):
        st.subheader("Recommended Books & Deep Reading", anchor=False)
        st.caption(
            "Textbooks and handbooks for your track, with a free or official link wherever one "
            "exists. "
            + (f"Books for your weak topics ({', '.join(weak)}) come first." if weak else "")
        )
        left, right = st.columns([3, 2])
        query = left.text_input(
            "Search books", placeholder="Title, author or topic", key="lib_book_q"
        )
        level = right.segmented_control(
            "Difficulty", list(study_library.LEVELS), key="lib_book_level"
        )
        books = study_library.books_for_student(role, weak, query, level)
        if not books:
            empty_state("No books match. Clear the search or choose another level.")
        show_all = len(books) > PAGE and st.toggle(
            f"Show all {len(books)} books", key="lib_book_all"
        )
        for book, fills in books if show_all else books[:PAGE]:
            st.markdown(formatter.book_md(book, fills))
        st.caption(f"Links last checked {study_library.library()['checked']}.")

    with st.container(border=True):
        st.subheader("Nexus Curated Roadmaps & Field Guides", anchor=False)
        st.caption(
            f"Free, open-source GitHub repositories that fit {role}. Hours are rough planning "
            "estimates."
        )
        cats = {c["id"]: c["name"] for c in study_library.library()["repo_categories"]}
        left, right = st.columns([3, 2])
        query = left.text_input(
            "Search repositories", placeholder="Name, topic or skill", key="lib_repo_q"
        )
        category = right.selectbox(
            "Category",
            [None, *cats],
            format_func=lambda c: "All categories" if c is None else cats[c],
            key="lib_repo_cat",
        )
        repos = study_library.repos_for_role(role, query, category)
        if not repos:
            empty_state(
                "No repositories match yet. GitHub study guides lean towards software, so some "
                "tracks have fewer; try another category or clear the search."
            )
        for repo in repos[:PAGE]:
            st.markdown(formatter.repo_md(repo))
        if len(repos) > PAGE:
            with st.expander(f"{len(repos) - PAGE} more repositories"):
                for repo in repos[PAGE:]:
                    st.markdown(formatter.repo_md(repo))


def _export(plan: services.WeeklyPlan) -> None:
    """The shown week as a calendar file or a table, to keep outside the app. The files are
    built only when a button is clicked, not on every render."""
    with st.expander("Export this week", icon=":material/download:"):
        first = st.date_input(
            "First day", value=formatter.next_monday(formatter.local_today()), format="DD/MM/YYYY"
        )
        at = st.time_input("Study time each day", value=STUDY_TIME, step=1800)
        st.caption(
            f"Times are {TIMEZONE} time. Each day becomes one event, as long as that day's minutes."
        )
        name = f"placementiq-week-{plan.week_no}"
        with st.container(horizontal=True):
            st.download_button(
                "Calendar (.ics)",
                partial(formatter.plan_ics, plan, first, at),
                file_name=f"{name}.ics",
                mime="text/calendar",
                icon=":material/event:",
                on_click="ignore",
            )
            st.download_button(
                "Table (.csv)",
                partial(formatter.plan_csv, plan),
                file_name=f"{name}.csv",
                mime="text/csv",
                icon=":material/table_view:",
                on_click="ignore",
            )


# Choosing a week, ticking days, the table view and the export inputs rerun only this
# section, not the page (no queries, no header, no sidebar).
@st.fragment
def _plans(sid: str, ov: services.PlanOverview) -> None:
    plan_col, side_col = st.columns([2, 1], gap="medium")
    previous = None
    with plan_col:
        if not ov.plans:
            empty_state(
                "calendar_month",
                "No plan yet",
                "Generate week 1 with the button above. The planner turns your weakness scores "
                "into seven days of practice, most of it on your weakest topics.",
            )
        else:
            weeks = [p.week_no for p in ov.plans]
            week = st.pills(  # chips wrap onto more rows on a phone, however many weeks
                "Week",
                weeks,
                format_func=lambda w: f"Week {w}",
                default=weeks[-1],
                required=True,
                label_visibility="collapsed",
                wrap=True,
            )
            shown = next(p for p in ov.plans if p.week_no == week)
            previous = next((p for p in ov.plans if p.week_no == shown.week_no - 1), None)
            with st.container(border=True):
                w_top1, w_top2 = st.columns([3, 2], vertical_alignment="center")
                with w_top1:
                    st.subheader(f"Week {shown.week_no}", anchor=False)
                    st.caption(formatter.plan_summary(shown))
                with w_top2:
                    st.download_button(
                        "📥 Download 7-Day Schedule (.ics)",
                        data=partial(calendar_export.generate_plan_ics, shown),  # on click
                        file_name=f"study-schedule-week-{shown.week_no}.ics",
                        mime="text/calendar",
                        type="primary",
                        icon=":material/calendar_month:",
                        help="Export all 7 days as all-day events for Google Calendar / Outlook",
                        key=f"plan_shown_ics_{shown.week_no}",
                    )
                st.info(
                    f"**Why this plan.** {formatter.md_escape(shown.rationale)}",
                    icon=":material/lightbulb:",
                )
                done = _days_done(sid, shown.week_no, ov.done.get(shown.week_no, set()))
                ov.done[shown.week_no] = done  # a fragment rerun keeps its first arguments

                st.markdown("##### 📅 Daily Tasks & Schedule")
                for d in sorted(shown.days, key=lambda x: x.day):
                    day_is_done = d.day in done
                    badge_icon = "✅" if day_is_done else "📖"
                    task_title = f"[Skill Scout Nexus] Day {d.day}: {d.topic}"
                    task_desc = (
                        f"Day {d.day} Study Plan - Week {shown.week_no}\n"
                        f"Topic: {d.topic} ({d.duration_min} min)\n"
                        f"Practice Goal: {d.practice_goal}\n"
                        f"Subtopics: {', '.join(d.subtopics)}"
                    )
                    gcal_url = calendar_export.build_gcal_url(
                        title=task_title,
                        details=task_desc,
                        duration_min=d.duration_min,
                    )
                    with st.container(border=True):
                        d_col1, d_col2 = st.columns([4, 1], vertical_alignment="center")
                        with d_col1:
                            sub_text = " · ".join(d.subtopics)
                            status_tag = " :green[(Completed)]" if day_is_done else ""
                            st.markdown(
                                f"**{badge_icon} Day {d.day}: {d.topic}** "
                                f"({d.duration_min} min){status_tag}  \n"
                                f":gray[Subtopics: {formatter.md_escape(sub_text)}]  \n"
                                f"🎯 *Goal: {formatter.md_escape(d.practice_goal)}*"
                            )
                        with d_col2:
                            st.link_button(
                                "📅 Add to GCal",
                                url=gcal_url,
                                help=f"Add Day {d.day} task to Google Calendar in a new tab",
                                key=f"gcal_btn_w{shown.week_no}_d{d.day}",
                            )

                with st.container(border=True):
                    st.subheader("📝 Export to Google Keep / Tasks", anchor=False)
                    st.caption(
                        "Copy your 7-day checklist formatted with task boxes `[ ]` "
                        "ready to paste directly into Google Keep, Apple Notes, Notion, or Tasks."
                    )
                    checklist_md = calendar_export.format_tasks_checklist(shown, done_days=done)
                    st.code(checklist_md, language="markdown")
                    st.html(
                        calendar_export.copy_clipboard_button_html(
                            checklist_md, f"copy_btn_w{shown.week_no}"
                        )
                    )

                if st.toggle("Table view", help="The same seven days as a table."):
                    st.dataframe(formatter.plan_table(shown), width="stretch")
                else:
                    st.html(formatter.plan_days_html(shown, done))
                _export(shown)

    with side_col:
        # What changed in the week shown, then the weakness the next week is planned from.
        if previous:
            before, after = previous.minutes_by_topic(), shown.minutes_by_topic()
            pair = (previous.week_no, shown.week_no)
            with st.container(border=True):
                st.subheader(
                    formatter.minutes_shift_headline(before, after, previous.week_no),
                    anchor=False,
                )
                st.vega_lite_chart(
                    spec=charts.minutes_shift_spec(before, after, pair),
                    width="stretch",
                    alt=formatter.minutes_shift_alt(before, after, pair),
                )
                st.caption(
                    f"Minutes per topic. Hollow grey dot: week {pair[0]}. Filled dot, in the "
                    f"topic's colour: week {pair[1]}."
                )
        with st.container(border=True):
            st.subheader(formatter.weakness_headline(ov.weakness), anchor=False)
            st.vega_lite_chart(
                spec=charts.weakness_spec(ov.weakness),
                width="stretch",
                alt=formatter.weakness_alt(ov.weakness),
            )
            st.caption(f"{formatter.weakness_caption()} {formatter.weakness_source()}")


page_header(
    "Weekly plan",
    "Seven days of study, most of it on your weakest topics. Each new week is planned from "
    "your latest quiz scores, and a critic checks it before you see it.",
)
sid, profile = require_profile()
ov = services.plan_overview(sid, profile)

col_top_gen, col_top_ics = st.columns([1, 1], vertical_alignment="center")
with col_top_gen:
    if st.button(
        f"Generate week {ov.next_week} plan", type="primary", icon=":material/autorenew:"
    ) and run_agent("Planner agent", lambda ev: services.generate_next_plan(sid, ev)):
        st.rerun()

with col_top_ics:
    if ov.plans:
        latest = ov.plans[-1]
        st.download_button(
            "📥 Download 7-Day Schedule (.ics)",
            data=partial(calendar_export.generate_plan_ics, latest),  # built on click
            file_name=f"study-schedule-week-{latest.week_no}.ics",
            mime="text/calendar",
            type="primary",
            icon=":material/event:",
            help="Download RFC-5545 compliant 7-day schedule for Google Calendar, Outlook, Apple",
            key="plan_top_primary_ics",
        )

show_last_run("Planner agent")
_plans(sid, ov)
_library(profile.target_role, ov.weakness)
