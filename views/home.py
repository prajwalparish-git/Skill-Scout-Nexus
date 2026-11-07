"""Home: what PlacementIQ does (no student yet), or where a student stands and what to do
next (Today's focus)."""

import streamlit as st

from piq import charts, formatter, services, ui

HOW_IT_WORKS = (
    ("upload_file", "Profile", "Upload your resume. Your skills are matched to a target role."),
    ("calendar_month", "Plan", "Get seven days of study, most of it on your weakest topics."),
    ("quiz", "Quiz", "Take five-question quizzes. A critic checks every question first."),
    ("autorenew", "Adapt", "Your scores reshape next week's plan, and the loop goes on."),
)


def _go(page: str, **presets: str) -> None:
    """Open another page, preselecting its widgets through session state."""
    st.session_state.update(presets)
    st.switch_page(page)


student = ui.current_student()
if student is None:
    ui.page_header(
        "Placement prep that adapts to you",
        "Skill Scout Nexus reads your resume, plans a week of study, quizzes you and rewrites next "
        "week's plan from your scores. A critic checks every plan, quiz and interview question "
        "before you see it.",
    )
    with st.container(horizontal=True):
        build_resume = st.button(
            "Build ATS resume from scratch",
            type="primary",
            icon=":material/badge:",
            key="home_build_resume",
        )
        start = st.button("Start with your resume", icon=":material/upload_file:", key="start")
        sample = st.button("Try it with a sample resume", icon=":material/description:")
    if build_resume:
        _go("views/resume_builder.py")
    if start:
        _go("views/onboard.py")
    if sample:
        _go("views/onboard.py", onboard_sample=services.default_sample())
    st.subheader("How it works", anchor=False)
    for column, (n, (icon, title, text)) in zip(
        st.columns(4, gap="medium"), enumerate(HOW_IT_WORKS, 1), strict=True
    ):
        column.markdown(f":primary[:material/{icon}:] **{n}. {title}**  \n{text}")

    st.divider()
    st.subheader("Explore Career Pathways & Disciplines", anchor=False)
    st.caption(
        "Open to every stream: Engineering, Commerce, Law, Management, Healthcare and Government."
    )
    from piq import resume_builder

    domains = resume_builder.list_domains()
    for row_start in range(0, len(domains), 2):
        row_domains = domains[row_start : row_start + 2]
        cols = st.columns(2, gap="medium")
        for col, d in zip(cols, row_domains, strict=False):
            with col, st.container(border=True):
                st.markdown(f":primary[:material/{d.get('icon', 'work')}:] **{d['name']}**")
                st.caption(d.get("description", ""))
                role_names = [r["name"] for r in d.get("roles", [])]
                if role_names:
                    st.write(", ".join(f"`{r}`" for r in role_names[:3]))
                if st.button(
                    f"Build Resume: {d['name']}", key=f"btn_dom_{d['id']}", icon=":material/badge:"
                ):
                    _go("views/resume_builder.py")
    st.stop()

sid = student["id"]
profile = services.current_profile(sid)
if profile is None:
    ui.page_header(
        f"Welcome, {formatter.md_escape(student['name'])}",
        "Two ways to begin your placement journey.",
    )
    ui.no_profile_card("home_start")
    st.stop()

try:
    with st.skeleton(height=420):
        overview = services.home(sid, profile)
except services.ServiceError as e:
    if ui.empty_state(
        "error", "Your overview did not load", formatter.md_escape(str(e)), "Try again"
    ):
        st.rerun()
    st.stop()

domain = services.domain_of_role(profile.target_role)
ui.page_header(
    f"Hello, {formatter.md_escape(profile.name)}",
    f"Here is where you stand for {formatter.md_escape(profile.target_role)} "
    f"({formatter.md_escape(domain.name)}), and what to do next.",
)

if (snap := st.session_state.get("snapshot")) and (snap.roadmap_week or snap.quizzes):
    st.info(formatter.welcome_back_md(snap), icon=":material/history:")

ui.org_progress_card(sid)  # an organization's student: their stage against its pass marks

action = overview.next_action
main, side = st.columns([2, 1], gap="medium")
with main:
    with st.container(border=True):
        st.markdown(f":primary[:material/{action.icon}:] **Today's focus**")
        st.subheader(action.label, anchor=False)
        st.markdown(formatter.md_escape(action.reason))
        if action.topic:
            ui.topic_chip(action.topic)
        if st.button(action.cta, type="primary", icon=f":material/{action.icon}:", key="next"):
            _go(action.page, **({"quiz_topic": action.topic} if action.topic else {}))
    st.subheader(formatter.weakness_headline(overview.weakness), anchor=False)
    st.vega_lite_chart(
        spec=charts.weakness_spec(overview.weakness),
        width="stretch",
        alt=formatter.weakness_alt(overview.weakness),
    )
    st.caption(
        f"{formatter.weakness_caption()} Your role's topics in {formatter.md_escape(domain.name)}, "
        "plus any other topic of it you have quizzed."
    )

with side:
    with st.container(border=True):
        st.metric(
            "Readiness",
            f"{profile.readiness_score}/100",
            help="How much of your target role's skill list your resume shows.",
        )
        total = len(profile.matched_skills) + len(profile.missing_skills)
        st.caption(f"{len(profile.matched_skills)} of {total} required skills are on your resume.")
        st.markdown(formatter.streak_md(overview.streak.current, overview.streak.longest))
        if overview.week_done:
            st.markdown(formatter.days_done_md(*overview.week_done))
    with st.container(border=True):
        st.markdown(f"**ATS Resume:** `{profile.target_role}`")
        if st.button(
            "Build / Export ATS Resume", icon=":material/badge:", key="home_update_resume"
        ):
            _go("views/resume_builder.py")
    with st.container(border=True):
        st.markdown("**Getting started**")
        st.markdown(
            "  \n".join(formatter.checklist_line(i.label, i.done) for i in overview.checklist)
        )
    with st.container(border=True):
        st.markdown("**Recent activity**")
        if not overview.recent:
            st.caption("Nothing yet. Your plans, quizzes and interviews will appear here.")
        for item in overview.recent:
            when = formatter.relative_day(item.at)
            st.markdown(f"{formatter.md_escape(item.text)}  \n:small[:gray[{when}]]")
