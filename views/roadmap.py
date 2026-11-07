"""Step 3, 7-day roadmap: a day-by-day study plan for the student's skill gaps
(agents/study_planner_agent.py), saved week by week with the tasks ticked off."""

import streamlit as st

from piq import formatter, journey
from piq.config import ROADMAP_DEFAULT_SKILLS
from piq.services import URL_RE, ServiceError
from piq.ui import page_header, require_profile

GAPS = "roadmap_gaps"  # skills handed over by the resume scan (piq.ui.PER_STUDENT_KEYS)
UNSAVED = "roadmap_unsaved"  # a roadmap built while telemetry was down: still shown

page_header(
    "7-day study roadmap",
    "A day-by-day plan for the skills you are missing: what to learn, where to learn it free, "
    "and small tasks that prove it. Tick the tasks off as you go.",
)
sid, _ = require_profile()
me = journey.student(sid)

handed = st.session_state.get(GAPS)
gaps, origin = (handed, "your resume scan") if handed is not None else journey.latest_gaps(sid)
saved_plans = journey.roadmaps(sid)
next_week = (saved_plans[-1].week + 1) if saved_plans else 1

with st.container(border=True):
    options = list(dict.fromkeys([*gaps, *journey.role_skills(me.target_role)]))
    chosen = st.multiselect(
        "Skills to cover",
        options,
        default=gaps[:ROADMAP_DEFAULT_SKILLS],  # what the preloader wrote ahead
        help="Seven days fit up to seven skills well; more are shared across the days.",
    )
    st.caption(
        f"Suggested from {origin} for {formatter.md_escape(me.target_role)}."
        if gaps
        else "No gaps found yet: pick the skills you want to strengthen."
    )
    label = "Generate my 7-day roadmap" if next_week == 1 else f"Generate week {next_week}"
    if st.button(label, type="primary", icon=":material/route:", disabled=not chosen):
        try:
            with st.spinner("The planner agent is writing your week"):
                roadmap, saved = journey.build_roadmap(sid, chosen)
            st.session_state[UNSAVED] = None if saved else roadmap
            st.session_state.pop(GAPS, None)
            st.rerun()
        except ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")

unsaved: journey.Roadmap | None = st.session_state.get(UNSAVED)
plans = [*saved_plans, *([unsaved] if unsaved else [])]
if not plans:
    st.caption("No roadmap yet. Choose the skills above and generate your first week.")
    st.stop()

weeks = [p.week for p in plans]
week = st.segmented_control("Week", weeks, default=weeks[-1], format_func=lambda w: f"Week {w}")
current = next(p for p in plans if p.week == (week or weeks[-1]))
plan = current.plan
if plan.is_provisional:
    st.info(
        "A starter plan while your personalised one is written. It is swapped in on your next "
        "visit, as long as no task is ticked yet.",
        icon=":material/hourglass_top:",
    )
if current is unsaved:
    st.warning(
        "This roadmap could not be saved, so ticked tasks are not kept. It is still yours to use.",
        icon=":material/cloud_off:",
    )

total = sum(len(d.micro_tasks) for d in plan.days)
st.subheader(
    f"Week {current.week}: {formatter.md_escape(', '.join(plan.addressed_gaps[:4]))}", anchor=False
)
st.markdown(formatter.md_escape(plan.summary))
progress = st.empty()

done: set[str] = set()
for day in plan.days:
    with st.container(border=True):
        st.markdown(
            f"**Day {day.day} · {formatter.md_escape(day.focus_skill)}** "
            f":gray[· about {day.estimated_hours:g} h]"
        )
        st.markdown("\n".join(f"- {formatter.md_escape(o)}" for o in day.learning_objectives))
        links = [
            f"[{formatter.md_escape(r.title)}]({r.url})"
            if URL_RE.match(r.url)
            else formatter.md_escape(r.title)
            for r in day.resources
        ]
        st.markdown(":material/menu_book: " + " · ".join(links))
        for n, task in enumerate(day.micro_tasks):
            key = journey.task_key(day.day, n)
            if st.checkbox(
                formatter.md_escape(task),
                value=key in current.done,
                key=f"rm{current.week}:{key}",
                disabled=current is unsaved,
            ):
                done.add(key)

progress.progress(len(done) / total if total else 0, text=f"{len(done)} of {total} tasks done")
if current is not unsaved and done != set(current.done):
    if journey.set_tasks_done(sid, current.week, done):
        st.toast("Progress saved", icon=":material/check_circle:")
    else:
        st.warning("Progress could not be saved just now.", icon=":material/cloud_off:")
