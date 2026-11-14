"""Dashboard: how the student is doing (readiness, quiz scores per topic, plan minutes,
interview scores), then how the agents and the critic behave, kept apart."""

import streamlit as st

from core import calendar_export
from piq import charts, formatter, services, ui
from piq.ui import Stat, empty_state, page_header, require_profile, stat_row


def _kpis(d: services.Dashboard, streak: services.Streak) -> None:
    change = formatter.readiness_change([r["readiness_score"] for r in d.readiness])
    delta, color = change or (None, "normal")
    correct, answered = d.answered
    stat_row(
        [
            Stat("Readiness", f"{d.profile.readiness_score}/100", delta, delta_color=color),
            Stat("Quizzes taken", str(d.quizzes_taken)),
            Stat(
                "Questions answered",
                str(answered),
                f"{correct / answered:.0%} right" if answered else None,
                delta_color="off",
                delta_arrow="off",  # a share, not a change
            ),
            Stat("Interview sessions", str(len(d.sessions))),
            Stat(
                "Study streak",
                formatter.days(streak.current),
                help=f"Days in a row with a quiz or an interview. Longest: "
                f"{formatter.days(streak.longest)}.",
            ),
        ]
    )


def _activity(streak: services.Streak) -> None:
    today = formatter.local_today()
    recent = sum(1 for day in streak.days if (today - day).days < 7 * 12)
    st.subheader(formatter.activity_headline(recent, streak.longest), anchor=False)
    st.vega_lite_chart(
        spec=charts.activity_heatmap_spec(streak.days, today),
        width="stretch",
        alt=f"Calendar of the last 12 weeks: {formatter.days(recent)} with study.",
    )
    st.caption(
        "One square per day, a column per week, oldest on the left; a stronger teal is busier."
    )


def _syllabus(d: services.Dashboard) -> None:
    """The topics this student is measured on: their role's, the ones they chose, the rest."""
    syl = d.syllabus
    if syl is None:
        return
    with st.container(border=True):
        st.subheader("Your syllabus", anchor=False)
        st.markdown(formatter.syllabus_line(syl.domain.name, syl.role))
        chosen = [t for t in syl.tracked if t not in syl.focus]
        columns = st.columns(3 if chosen else 2, gap="medium")
        groups = [("For your role", syl.focus)]
        if chosen:
            groups.append(("Chosen by you", chosen))
        groups.append(("Not tried yet", syl.others))
        for column, (title, topics) in zip(columns, groups, strict=True):
            with column:
                st.markdown(f"**{title}**")
                if topics:
                    st.html(formatter.topic_chips_html(topics))
                else:
                    st.caption("None: you have tried every topic of your domain.")
        if syl.others:
            st.caption("Add any topic of your domain to a quiz; it is tracked from then on.")


def _topic_mastery(d: services.Dashboard) -> None:
    """Every tracked topic, weakest first: weakness now, which way it moves, its scores."""
    mastery = d.mastery
    st.subheader(
        formatter.topic_scores_headline({m.topic: m.scores for m in mastery}), anchor=False
    )
    if not d.quiz_history:
        st.caption("No quizzes yet. Each topic's scores appear here after its first quiz.")
        return
    st.caption(
        "Weakest topic first. Weakness is what the next plan uses; the line is every quiz "
        "score on the topic, oldest to latest, on a 0-100% scale."
    )
    for start in range(0, len(mastery), 3):
        row = mastery[start : start + 3]
        for column, m in zip(st.columns(3, gap="small"), row, strict=False):
            with column, st.container(border=True, gap="small"):
                st.markdown(formatter.mastery_line(m.topic, m.weakness, m.scores))
                if m.scores:
                    st.markdown(formatter.trend_md(m.trend))
                    st.vega_lite_chart(
                        spec=charts.score_spark_spec(m.topic, m.scores),
                        width="stretch",
                        alt=f"{m.topic} quiz scores: " + ", ".join(f"{s:.0f}%" for s in m.scores),
                    )


def _accuracy(d: services.Dashboard) -> None:
    cells = [(r["topic"], r["difficulty"], r["correct"], r["total"]) for r in d.accuracy]
    st.subheader(formatter.accuracy_headline(cells), anchor=False)
    if not cells:
        st.caption("Each quiz adds its questions here, per topic and difficulty.")
        return
    st.vega_lite_chart(
        spec=charts.accuracy_grid_spec(cells),
        width="stretch",
        alt="Share correct by topic and difficulty: "
        + "; ".join(f"{t} {lvl} {c} of {n}" for t, lvl, c, n in cells),
    )
    st.caption("Every question you answered; a stronger teal is a higher share right.")


def _runs(d: services.Dashboard) -> None:
    st.subheader("Recent quizzes", anchor=False)
    if not d.runs:
        st.caption("Quizzes you set up on the Quiz page appear here with their score.")
        return
    st.dataframe(formatter.runs_table(d.runs), hide_index=True, width="stretch")


def _readiness(d: services.Dashboard) -> None:
    scores = [r["readiness_score"] for r in d.readiness]
    st.subheader(formatter.readiness_headline(scores), anchor=False)
    labels = [formatter.local_day(r["created_at"]) for r in d.readiness]
    st.vega_lite_chart(
        spec=charts.readiness_trend_spec(scores, labels),
        width="stretch",
        alt="Readiness by profile: " + ", ".join(f"{s} of 100" for s in scores),
    )
    if len(scores) < 2:  # one point is not a trend: say how to get one
        st.caption(
            "One profile so far. Re-profile with an updated resume on the Onboard page; "
            "each profile adds a point here."
        )
    else:
        st.caption("Readiness out of 100 at each profile.")


def _interviews(d: services.Dashboard) -> None:
    if not d.sessions:
        st.subheader("No interview yet", anchor=False)
        st.caption("Each session's average score appears here after your first interview.")
        return
    averages = [float(s["avg_overall"]) for s in d.sessions]
    st.subheader(formatter.interview_headline(averages), anchor=False)
    st.vega_lite_chart(
        spec=charts.interview_trend_spec(averages, formatter.session_labels(d.sessions)),
        width="stretch",
        alt="Interview averages: " + ", ".join(f"{a:.1f} of 5" for a in averages),
    )
    st.caption("Average score per mock interview, out of 5.")


def _plans(d: services.Dashboard) -> None:
    if not d.plans:
        st.subheader("No plan yet", anchor=False)
        st.caption("Each week's minutes per topic appear here once you generate a plan.")
        return
    weeks = {p.week_no: p.minutes_by_topic() for p in d.plans}
    st.subheader(formatter.week_mix_headline(d.plans), anchor=False)
    st.vega_lite_chart(
        spec=charts.week_mix_spec(weeks), width="stretch", alt=formatter.plan_mix_alt(weeks)
    )
    week, done = d.plans_done[-1][0].week_no, len(d.plans_done[-1][1])
    st.markdown(formatter.days_done_md(week, done))
    st.caption("Minutes per week, split by topic.")

    curr_plan = d.plans[-1]
    done_set = d.plans_done[-1][1] if d.plans_done else set()

    with st.container(horizontal=True):
        st.download_button(
            "📥 Download Schedule (.ics)",
            data=calendar_export.generate_plan_ics(curr_plan),
            file_name=f"study-schedule-week-{curr_plan.week_no}.ics",
            mime="text/calendar",
            key="dash_plan_download_ics",
            help="Download RFC-5545 compliant 7-day schedule for your calendar",
        )
        pending_days = [
            d_ for d_ in sorted(curr_plan.days, key=lambda x: x.day) if d_.day not in done_set
        ]
        next_d = pending_days[0] if pending_days else curr_plan.days[0]
        gcal_title = f"[Skill Scout Nexus] Day {next_d.day}: {next_d.topic}"
        gcal_desc = (
            f"Day {next_d.day} Study Plan - Week {curr_plan.week_no}\n"
            f"Topic: {next_d.topic} ({next_d.duration_min} min)\n"
            f"Practice Goal: {next_d.practice_goal}\n"
            f"Subtopics: {', '.join(next_d.subtopics)}"
        )
        st.link_button(
            f"📅 Day {next_d.day} to GCal",
            url=calendar_export.build_gcal_url(
                gcal_title, gcal_desc, duration_min=next_d.duration_min
            ),
            help=f"Add Day {next_d.day} study session to Google Calendar in a new tab",
        )

    with st.expander("📝 Export to Google Keep / Tasks", icon=":material/checklist:"):
        dash_checklist = calendar_export.format_tasks_checklist(curr_plan, done_days=done_set)
        st.code(dash_checklist, language="markdown")
        st.html(calendar_export.copy_clipboard_button_html(dash_checklist, "dash_copy_btn"))


def _under_the_hood(d: services.Dashboard) -> None:
    st.divider()
    st.header("Under the hood: agents and critic", anchor=False)
    st.markdown(
        ":gray[Every agent call in this app, for all students: how often the critic rejected "
        "a draft and sent it back, and what it said.]"
    )
    if d.agent_stats:
        st.dataframe(
            formatter.agent_table(d.agent_stats),
            hide_index=True,
            width="stretch",
            column_config={
                "Rejection rate": st.column_config.ProgressColumn(
                    "Rejection rate", min_value=0, max_value=100, format="%.0f%%"
                ),
            },
        )
    else:
        st.caption("No agent calls yet.")
    st.subheader("Recent critic rejections", anchor=False)
    if d.rejections:
        st.caption("Each one sent a draft back for regeneration.")
        st.dataframe(formatter.rejections_table(d.rejections), hide_index=True, width="stretch")
    else:
        st.caption("None yet: the critic has approved every draft.")


page_header(
    "Dashboard",
    "Your progress across quizzes, plans and interviews, and below it how the agents and the "
    "critic worked.",
)
sid, profile = require_profile()
try:
    with st.skeleton(height=480):
        d = services.dashboard(sid, profile)
except services.ServiceError as e:
    if empty_state(
        "error", "Your dashboard did not load", formatter.md_escape(str(e)), "Try again"
    ):
        st.rerun()
    st.stop()

streak = d.streak
ui.org_progress_card(sid)  # an organization's student: their stage against its pass marks
_kpis(d, streak)
_syllabus(d)
_topic_mastery(d)
accuracy_col, runs_col = st.columns(2, gap="medium")
with accuracy_col, st.container(border=True, height="stretch"):
    _accuracy(d)
with runs_col, st.container(border=True, height="stretch"):
    _runs(d)
readiness_col, interview_col = st.columns(2, gap="medium")
with readiness_col, st.container(border=True, height="stretch"):
    _readiness(d)
with interview_col, st.container(border=True, height="stretch"):
    _interviews(d)
plans_col, activity_col = st.columns(2, gap="medium")
with plans_col, st.container(border=True, height="stretch"):
    _plans(d)
with activity_col, st.container(border=True, height="stretch"):
    _activity(streak)
_under_the_hood(d)
