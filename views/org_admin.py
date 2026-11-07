"""Organization admin command center: four tabs for the organization's main admin.

Overview (KPIs, readiness funnel, tiers, performance by domain, skill-gap heatmap, trends,
leaderboard and watchlist), Provisioning (CSV preview, accounts and welcome emails, one-time
credentials, quick add), Students (a filterable directory and a 360 profile with admin actions)
and Settings (profile and pass marks, placement drive shortlist and exports, service health).

Everything is the signed-in admin's own organization: the page reads it from the session
(ui.current_admin), never from a form, and every call goes through piq/orgs.py, which refuses
any student that is not in it.
"""

from datetime import UTC, datetime

import streamlit as st

from piq import charts, cohort, formatter, journey, org_insights, orgs, services, ui
from piq.config import ACCOUNT_STATUSES, ACTIVE_WITHIN_DAYS, VOICE_RUBRIC_MAX
from piq.ui import Stat, empty_state, page_header, stat_row, status_badge

CREDS = "org_creds"  # the credentials just made, until downloaded or discarded (one time)
OPEN = "org_open"  # the username whose 360 profile is open
USERS = "org_dir_users"  # the directory's usernames in the order shown (to map a clicked row)
PICK = "org_pick"
STATE_BADGE = {"ready": "done", "paused": "warning", "off": "todo"}
STATUS_BADGE = {"active": "done", "invited": "info", "suspended": "warning"}
AUTO_ROLE = "Auto (best fit)"

org = ui.current_admin()
if org is None:  # a student or a visitor who followed a link here
    empty_state(
        "admin_panel_settings",
        "Organization admins only",
        "Sign in with Organization admin access to open this page.",
    )
    st.stop()

cut = orgs.cutoffs(org)
try:
    with st.spinner("Reading your organization"):
        view = orgs.overview(org.id)
except services.ServiceError as e:
    empty_state("error", "The portal did not load", formatter.md_escape(str(e)))
    st.stop()

page_header(
    org.name,
    f"{org.org_type} in {org.location or 'no location set'}, "
    f"batch {org.academic_batch or 'not set'}. "
    "Provision students, follow their progress and prepare placement drives.",
)
if view.error:
    st.warning(
        f"{view.error} Students are listed, but their results are missing.",
        icon=":material/cloud_off:",
    )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:g}%"


# --- one-time credentials ---------------------------------------------------------------------


def _store_creds(headline: str, creds, queued: int) -> None:  # type: ignore[no-untyped-def]
    st.session_state[CREDS] = {
        "csv": orgs.credentials_csv(creds),
        "headline": headline,
        "channel": orgs.mail_channel(org),
        "queued": queued,
    }


def _clear_creds() -> None:
    st.session_state.pop(CREDS, None)


def _credentials_banner() -> None:
    held = st.session_state.get(CREDS)
    if not held:
        return
    note = {
        "smtp": "The emails are on their way in the background.",
        "outbox": "Email is not set up here, so each message was written to data/.mail_outbox.log. "
        "Hand the credentials file to your students instead.",
        "demo": "The demo organization sends no email. The credentials are in the file below.",
    }[held["channel"]]
    with st.container(border=True):
        st.success(held["headline"], icon=":material/mark_email_read:")
        st.caption(note)
        with st.container(horizontal=True):
            st.download_button(
                "Download provisioned credentials CSV (one-time)",
                held["csv"],
                file_name=f"credentials-{datetime.now(UTC):%Y-%m-%d}.csv",
                mime="text/csv",
                type="primary",
                icon=":material/download:",
                on_click=_clear_creds,
                key="org_creds_download",
            )
            st.button("Discard", type="tertiary", on_click=_clear_creds, key="org_creds_discard")
        st.caption(
            ":material/warning: This file holds temporary passwords. It is shown once: download it "
            "now, share it only with the students named in it, and delete it afterwards."
        )


# --- tab 1: overview --------------------------------------------------------------------------


def _overview() -> None:
    rows = view.rows
    if not rows:
        empty_state(
            "group_add",
            "No students yet",
            "Add students from a CSV file or one at a time in the Provisioning tab. Their "
            "progress appears here as they scan resumes, follow plans, take quizzes and practise "
            "voice interviews.",
        )
        return
    now = datetime.now(UTC)
    k = org_insights.kpis(rows, cut, now)
    stat_row(
        [
            Stat("Enrolled students", str(k.enrolled)),
            Stat(
                "Active learners",
                str(k.active),
                help=f"A quiz or voice session in the last {ACTIVE_WITHIN_DAYS} days.",
            ),
            Stat("Avg resume match", _pct(k.avg_resume_match)),
            Stat("Avg quiz score", _pct(k.avg_quiz)),
            Stat(
                f"Avg voice (/{VOICE_RUBRIC_MAX})",
                "-" if k.avg_voice is None else f"{k.avg_voice:g}",
            ),
            Stat(
                "Placement-ready",
                str(k.ready),
                f"of {k.enrolled}",
                delta_color="off",
                delta_arrow="off",
                help=f"An average quiz score of at least {cut.quiz_pct:g}% and an average voice "
                f"score of at least {cut.voice_score:g}/{VOICE_RUBRIC_MAX}: your pass marks "
                "(Settings).",
            ),
        ]
    )

    stages = org_insights.funnel(rows, cut)
    left, right = st.columns([3, 2], gap="medium")
    with left, st.container(border=True, height="stretch"):
        st.subheader(org_insights.funnel_takeaway(stages), anchor=False)
        st.vega_lite_chart(
            charts.funnel_spec([(s.label, s.count, s.of_enrolled, s.of_previous) for s in stages]),
            width="stretch",
        )
        st.caption(
            "Each stage keeps only students who cleared every stage before it: a resume scan, a "
            f"plan task ticked, a quiz average of {cut.quiz_pct:g}% and a voice average of "
            f"{cut.voice_score:g}/{VOICE_RUBRIC_MAX}."
        )
    with right, st.container(border=True, height="stretch"):
        mix = org_insights.tier_mix(rows, cut)
        st.subheader("Where the batch stands", anchor=False)
        st.vega_lite_chart(charts.tier_spec(mix), width="stretch")
        st.caption(
            f"Ready: both pass marks met. At risk: nothing assessed yet or readiness under "
            f"{50}. Everyone else is in progress. Suspended accounts are left out."
        )

    with st.container(border=True):
        by = st.segmented_control(
            "Compare by", ["Main domain", "Subdomain"], default="Main domain", key="org_perf_by"
        )
        group = "subdomain" if by == "Subdomain" else "main_domain"
        perf = org_insights.performance(rows, group)
        st.subheader(org_insights.performance_takeaway(perf), anchor=False)
        if perf:
            st.vega_lite_chart(charts.stream_readiness_spec(perf), width="stretch")
        st.caption("Average placement readiness (0-100). Hover a bar for its parts.")

    with st.container(border=True):
        gap_by = st.segmented_control(
            "Skill gaps by", ["Main domain", "Subdomain"], default="Main domain", key="org_gap_by"
        )
        cells = org_insights.gap_matrix(
            rows, "subdomain" if gap_by == "Subdomain" else "main_domain"
        )
        scanned = sum(r.resume_match is not None for r in rows)
        st.subheader(cohort.gaps_takeaway(cohort.skill_gaps(rows), scanned), anchor=False)
        if cells:
            st.vega_lite_chart(charts.gap_heatmap_spec(cells), width="stretch")
        st.caption(
            "Skills missing from students' latest resume scan: the tint is the share of the "
            "group's scanned students missing it and the number is how many."
        )

    snap = view.snapshot
    quiz_avgs = [r.quiz_average for r in rows if r.quiz_average is not None]
    voice_avgs = [r.rubric_average for r in rows if r.rubric_average is not None]
    trend = cohort.weekly_quiz_trend(snap) if snap else []
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, height="stretch"):
        st.subheader(f"{len(quiz_avgs)} students with a quiz average", anchor=False)
        if quiz_avgs:
            st.vega_lite_chart(
                charts.histogram_spec(quiz_avgs, top=100, step=10, noun="Average (%)"),
                width="stretch",
            )
        st.caption(f"Each student's average quiz score; the pass mark is {cut.quiz_pct:g}%.")
    with right, st.container(border=True, height="stretch"):
        if len(trend) >= 2:
            st.subheader(
                f"Quiz scores went from {trend[0][1]:.0f}% to {trend[-1][1]:.0f}% "
                f"over {len(trend)} weeks",
                anchor=False,
            )
            weeks = [(w.strftime("%d %b"), avg, n) for w, avg, n in trend]
            st.vega_lite_chart(charts.cohort_trend_spec(weeks), width="stretch")
            st.caption("Average quiz score per week (weeks start on Monday).")
        else:
            st.subheader("Weekly trend", anchor=False)
            st.caption("The trend appears once quizzes span two weeks.")
    breakdown = cohort.rubric_breakdown(snap) if snap else {}
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, height="stretch"):
        st.subheader(f"{len(voice_avgs)} students with a voice average", anchor=False)
        if voice_avgs:
            st.vega_lite_chart(
                charts.histogram_spec(
                    voice_avgs, top=VOICE_RUBRIC_MAX, step=1, noun="Average rubric"
                ),
                width="stretch",
            )
        st.caption(f"Each student's average voice score; the pass mark is {cut.voice_score:g}.")
    with right, st.container(border=True, height="stretch"):
        weakest = min(breakdown, key=breakdown.get) if breakdown else None
        st.subheader(
            f"Weakest voice criterion: {weakest}" if weakest else "No voice sessions yet",
            anchor=False,
        )
        if breakdown:
            st.vega_lite_chart(charts.rubric_breakdown_spec(breakdown), width="stretch")
        st.caption("Average score per rubric criterion, out of 5.")

    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, height="stretch"):
        st.subheader("Top performers", anchor=False)
        top = org_insights.top_performers(rows)
        if top:
            st.dataframe(
                [
                    {
                        "#": i,
                        "Name": r.name,
                        "Domain": f"{r.main_domain or r.stream} / {r.subdomain}".strip(" /"),
                        "Readiness": r.readiness,
                    }
                    for i, r in enumerate(top, 1)
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "Readiness": st.column_config.ProgressColumn(
                        "Readiness", min_value=0, max_value=100, format="%.0f"
                    )
                },
            )
        else:
            st.caption("Nobody has been assessed yet.")
    with right, st.container(border=True, height="stretch"):
        st.subheader("Needs attention", anchor=False)
        needy = org_insights.needs_attention(rows, cut, now)
        if needy:
            for r, reason in needy:
                st.markdown(
                    f":material/priority_high: **{formatter.md_escape(r.name)}** "
                    f"({formatter.md_escape(r.main_domain or r.stream)})  \n"
                    f":small[:gray[{formatter.md_escape(reason)}]]"
                )
            st.caption(
                "Open them in the Students tab to resend credentials or check their progress."
            )
        else:
            st.caption("Nobody needs a nudge right now.")


# --- tab 2: provisioning ----------------------------------------------------------------------

READY_ICON = {
    "Ready": ":material/check_circle:",
    "Duplicate": ":material/content_copy:",
    "Invalid Email": ":material/mail_off:",
}


def _preview_table(preview) -> None:  # type: ignore[no-untyped-def]
    st.dataframe(
        [
            {
                "Line": r.line,
                "Name": r.name,
                "Email": r.email,
                "Main domain": r.stream or r.main_domain,
                "Subdomain": r.subdomain,
                "Target role": r.target_role,
                "Role from": {"file": "the file", "auto": "auto-mapped"}.get(r.role_source, ""),
                "Status": f"{r.status}",
                "Note": r.note,
            }
            for r in preview.rows
        ],
        hide_index=True,
        width="stretch",
    )


def _provisioning() -> None:
    _credentials_banner()
    with st.container(border=True):
        st.subheader("Add students from a CSV file", anchor=False)
        st.markdown(
            "Columns: `name`, `email`, `main_domain`, `subdomain` (required), then `target_role`, "
            "`phone` and `batch_year`. Headers are matched in any case, and names such as "
            "`full_name`, `student_email`, `stream`, `department` or `branch` work too. A blank "
            "`target_role` is filled with the best fit for the subdomain."
        )
        st.download_button(
            "Download the CSV template",
            orgs.template_csv(),
            file_name="org_students_template.csv",
            mime="text/csv",
            icon=":material/download:",
            key="org_template",
        )
        upload = st.file_uploader("Student CSV", type=["csv"], key="org_csv")
        if upload is not None:
            data = upload.getvalue()
            try:
                preview = orgs.preview_csv(org.id, data)
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
            else:
                ready = preview.count("Ready")
                problems = len(preview.rows) - ready
                with st.container(horizontal=True):
                    status_badge("done", f"{ready} ready")
                    if preview.count("Duplicate"):
                        status_badge("warning", f"{preview.count('Duplicate')} duplicate")
                    if preview.count("Invalid Email"):
                        status_badge("error", f"{preview.count('Invalid Email')} invalid email")
                    other = problems - preview.count("Duplicate") - preview.count("Invalid Email")
                    if other:
                        status_badge("warning", f"{other} need fixing")
                _preview_table(preview)
                st.caption(
                    "Only Ready rows are created. Fix the others in your file and upload it "
                    "again: students already created are skipped as duplicates."
                )
                if st.button(
                    "Provision accounts and send welcome emails",
                    type="primary",
                    icon=":material/forward_to_inbox:",
                    disabled=ready == 0,
                    key="org_provision",
                ):
                    try:
                        with st.spinner(f"Creating {ready} accounts"):
                            result = orgs.provision_csv(org.id, data)
                    except services.ServiceError as e:
                        st.error(formatter.md_escape(str(e)), icon=":material/error:")
                    else:
                        made, queued = len(result.created), result.emails_queued
                        _store_creds(
                            f"Created {made} accounts, queued {queued} emails.",
                            result.created,
                            result.emails_queued,
                        )
                        st.rerun()

    with st.container(border=True):
        st.subheader("Quick add a student", anchor=False)
        streams = orgs.streams()
        main = st.selectbox("Main domain", streams, key="org_qa_main")
        with st.form("org_quick_add", border=False, clear_on_submit=True):
            left, right = st.columns(2)
            name = left.text_input("Full name", key="org_qa_name")
            email = right.text_input("Email", key="org_qa_email")
            sub = left.text_input("Subdomain", placeholder="Taxation & Audit", key="org_qa_sub")
            role = right.selectbox(
                "Target role",
                [AUTO_ROLE, *orgs.roles_for_stream(main or streams[0])],
                key="org_qa_role",
            )
            phone = left.text_input("Phone (optional)", key="org_qa_phone")
            batch = right.text_input(
                "Batch year (optional)", placeholder="2027", key="org_qa_batch"
            )
            go = st.form_submit_button(
                "Add student and send email", type="primary", icon=":material/person_add:"
            )
        if go:
            try:
                result = orgs.quick_add(
                    org.id,
                    name=name,
                    email=email,
                    main_domain=main or "",
                    subdomain=sub,
                    target_role="" if role == AUTO_ROLE else role or "",
                    phone=phone,
                    batch_year=batch,
                )
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
            else:
                _store_creds(
                    f"Created 1 account, queued {result.emails_queued} email.",
                    result.created,
                    result.emails_queued,
                )
                st.rerun()


# --- tab 3: students --------------------------------------------------------------------------


def _row_picked() -> None:
    picked = st.session_state.get("org_dir", {}).get("selection", {}).get("rows", [])
    users = st.session_state.get(USERS, [])
    if picked and picked[0] < len(users):
        st.session_state[OPEN] = users[picked[0]]


def _name_picked() -> None:
    if st.session_state.get(PICK):
        st.session_state[OPEN] = st.session_state[PICK]


def _directory() -> None:
    rows = view.rows
    if not rows:
        empty_state(
            "groups",
            "No students yet",
            "Provision students in the previous tab, then find and inspect them here.",
        )
        return
    with st.container(border=True):
        query = st.text_input(
            "Search", placeholder="Name, email, username or role", key="org_f_query"
        )
        c1, c2, c3 = st.columns(3)
        domains = c1.multiselect(
            "Main domain", sorted({r.main_domain or r.stream for r in rows}), key="org_f_domain"
        )
        sub_options = sorted(
            {
                r.subdomain
                for r in rows
                if r.subdomain and (not domains or (r.main_domain or r.stream) in domains)
            }
        )
        subs = c2.multiselect("Subdomain", sub_options, key="org_f_sub")
        statuses = c3.multiselect("Account status", list(ACCOUNT_STATUSES), key="org_f_status")
        tiers = st.pills(
            "Readiness tier", org_insights.TIERS, selection_mode="multi", key="org_f_tier"
        )
    shown = org_insights.filter_rows(
        rows,
        cut,
        query=query,
        main_domains=domains,
        subdomains=[s for s in subs if s in sub_options],
        statuses=statuses,
        tiers=tiers or (),
    )
    st.caption(f"{len(shown)} of {len(rows)} students. Select a row to open their 360 profile.")
    records = org_insights.directory_rows(shown, cut)
    st.session_state[USERS] = [r["Username"] for r in records]
    st.dataframe(
        records,
        hide_index=True,
        width="stretch",
        on_select=_row_picked,
        selection_mode="single-row",
        key="org_dir",
        column_config={
            "Readiness": st.column_config.ProgressColumn(
                "Readiness", min_value=0, max_value=100, format="%.0f"
            ),
            "Resume match (%)": st.column_config.ProgressColumn(
                "Resume match (%)", min_value=0, max_value=100, format="%.0f"
            ),
            "Quiz average (%)": st.column_config.ProgressColumn(
                "Quiz average (%)", min_value=0, max_value=100, format="%.0f"
            ),
            f"Voice average (/{VOICE_RUBRIC_MAX})": st.column_config.ProgressColumn(
                f"Voice average (/{VOICE_RUBRIC_MAX})",
                min_value=0,
                max_value=VOICE_RUBRIC_MAX,
                format="%.1f",
            ),
        },
    )
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.selectbox(
            "Or find a student by name",
            [r["Username"] for r in records],
            index=None,
            placeholder="Choose a student",
            format_func=lambda u: next(
                f"{r['Name']} (@{u})" for r in records if r["Username"] == u
            ),
            on_change=_name_picked,
            key=PICK,
        )
        st.download_button(
            "Export progress report (CSV)",
            org_insights.progress_report_csv(shown, cut),
            file_name=f"progress-report-{datetime.now(UTC):%Y-%m-%d}.csv",
            mime="text/csv",
            icon=":material/download:",
            key="org_progress_csv",
        )

    username = st.session_state.get(OPEN)
    if not username:
        return
    try:
        sid = orgs.student_id_of(org.id, username)
    except services.ServiceError:
        st.session_state.pop(OPEN, None)
        return
    _profile(sid)


def _profile(sid: str) -> None:
    """The 360 panel: progress against the pass marks, skills and plan, quizzes, voice sessions
    and the admin's actions for one student."""
    cand = orgs.candidate(org.id, sid, view)
    row, d, acct = cand.row, cand.detail, cand.account
    with st.container(border=True):
        top, badges = st.columns([3, 2], vertical_alignment="center")
        top.subheader(
            formatter.md_escape(acct["name"]), anchor=False, icon=":material/account_circle:"
        )
        esc = formatter.md_escape
        top.caption(
            f"@{esc(acct['username'])} | {esc(acct['email'] or 'no email')} | "
            f"{esc(row.main_domain or row.stream)} / {esc(row.subdomain or '-')} | "
            f"{esc(row.target_role)}"
        )
        with badges, st.container(horizontal=True):
            status_badge(STATUS_BADGE[acct["account_status"]], acct["account_status"].capitalize())
            status_badge(*formatter.TIER_BADGE[org_insights.tier(row, cut)])
        if cand.error:
            st.warning(cand.error, icon=":material/cloud_off:")

        ring, quiz, voice, plan = st.columns(4, vertical_alignment="center")
        with ring:
            score = row.readiness
            if score is None:
                st.metric("Readiness", "-", border=True)
            else:
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.metric("Readiness", f"{score:.0f}/100", width="content")
                    st.vega_lite_chart(
                        spec=charts.readiness_ring_spec(round(score)),
                        width="content",
                        alt=f"Readiness {score:.0f} out of 100",
                    )
        quiz.metric(
            "Quiz average",
            _pct(row.quiz_average),
            None
            if row.quiz_average is None
            else f"{row.quiz_average - cut.quiz_pct:+.0f} vs pass mark",
            border=True,
        )
        voice.metric(
            f"Voice average (/{VOICE_RUBRIC_MAX})",
            "-" if row.rubric_average is None else f"{row.rubric_average:g}",
            None
            if row.rubric_average is None
            else f"{row.rubric_average - cut.voice_score:+.1f} vs pass mark",
            border=True,
        )
        plan.metric(
            "Study plan done", "-" if d.plan_percent is None else f"{d.plan_percent}%", border=True
        )
        ui.step_bars(org_insights.journey_steps(row, cut))

        skills, quizzes, voices, actions = st.tabs(
            [
                ":material/checklist: Skills and plan",
                ":material/quiz: Quizzes",
                ":material/graphic_eq: Voice sessions",
                ":material/manage_accounts: Admin actions",
            ]
        )
        with skills:
            if d.match_percent is None:
                st.caption("No resume scan yet. Every skill of the target role is still to build.")
            else:
                st.markdown(f"**On the resume** ({d.match_percent:g}% match)")
                st.markdown(formatter.skill_chips(d.matched, present=True) or ":gray[None yet.]")
                st.markdown("**Still missing**")
                st.markdown(
                    formatter.skill_chips(d.missing, present=False)
                    or ":gray[Nothing: a full match.]"
                )
            st.markdown("**7-day study plan**")
            if d.plans:
                for w in d.plans:
                    st.progress(
                        w.percent / 100, text=f"Week {w.week}: {w.done} of {w.total} tasks done"
                    )
            else:
                st.caption("No study plan built yet.")
        with quizzes:
            if not d.quizzes:
                st.caption("No quiz attempts yet.")
            else:
                if len(d.quizzes) >= 2:
                    ordered = list(reversed(d.quizzes))
                    st.vega_lite_chart(
                        charts.quiz_trend_spec(
                            [q.percent for q in ordered],
                            [f"{q.when:%d %b}: {q.skill}" for q in ordered],
                        ),
                        width="stretch",
                    )
                st.markdown("**Topic breakdown** (weakest first)")
                st.vega_lite_chart(
                    charts.percent_bars_spec([(t.skill, t.percent) for t in d.topics], "Correct"),
                    width="stretch",
                )
                st.dataframe(
                    [
                        {
                            "Date": f"{q.when:%d %b %Y}",
                            "Skill": q.skill,
                            "Level": q.difficulty,
                            "Score": f"{q.score}/{q.total}",
                            "Percent": q.percent,
                        }
                        for q in d.quizzes
                    ],
                    hide_index=True,
                    width="stretch",
                )
        with voices:
            if not d.voices:
                st.caption("No voice sessions yet.")
            for v in d.voices:
                flags = f", {len(v.flags)} proctor flag(s)" if v.flags else ""
                with st.expander(
                    f"{v.when:%d %b %Y}: {v.rubric}/{VOICE_RUBRIC_MAX}{flags}",
                    icon=":material/mic:",
                ):
                    a, b, c_ = st.columns(3)
                    a.metric("Content knowledge", f"{v.content:g}/5")
                    b.metric("Clarity and structure", f"{v.clarity:g}/5")
                    c_.metric("Confidence", f"{v.confidence:g}/5")
                    for flag in v.flags:
                        status_badge("warning", flag)
                    st.markdown(f"**Feedback**  \n{formatter.md_escape(v.feedback)}")
                    st.markdown("**Transcript**")
                    st.text(v.transcript)
        with actions:
            _actions(sid, acct, row, cand)


def _actions(sid: str, acct: dict, row, cand) -> None:  # type: ignore[no-untyped-def]
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True):
        st.markdown("**Credentials**")
        st.caption(
            "A new temporary password and 9-digit code, emailed to the student. Their old "
            "password stops working."
        )
        if st.button(
            "Resend credentials and reset password",
            icon=":material/lock_reset:",
            key=f"org_reset_{sid}",
        ):
            try:
                cred = orgs.reset_credentials(org.id, sid)
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
            else:
                _store_creds(f"New credentials made for {cred.name}.", [cred], 1)
                st.rerun()
        suspended = acct["account_status"] == "suspended"
        st.markdown("**Account**")
        st.caption(
            "A suspended student is signed out at once and cannot sign in until reactivated."
            if not suspended
            else "This account is suspended."
        )
        if st.button(
            "Reactivate account" if suspended else "Suspend account",
            icon=":material/lock_open:" if suspended else ":material/block:",
            key=f"org_status_{sid}",
        ):
            try:
                orgs.set_status(org.id, sid, "active" if suspended else "suspended")
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
            else:
                st.rerun()
    with right, st.container(border=True):
        st.markdown("**Domain, subdomain and role**")
        streams = orgs.streams()
        current = row.main_domain or row.stream
        main = st.selectbox(
            "Main domain",
            streams,
            index=streams.index(current) if current in streams else 0,
            key=f"org_re_main_{sid}",
        )
        with st.form(f"org_reassign_{sid}", border=False):
            sub = st.text_input("Subdomain", value=acct["subdomain"] or "", key=f"org_re_sub_{sid}")
            roles = orgs.roles_for_stream(main or streams[0])
            role = st.selectbox(
                "Target role",
                [AUTO_ROLE, *roles],
                index=(roles.index(row.target_role) + 1) if row.target_role in roles else 0,
                key=f"org_re_role_{sid}_{main}",
            )
            go = st.form_submit_button("Save placement", type="primary", icon=":material/save:")
        if go:
            try:
                mapped = orgs.reassign(
                    org.id, sid, main or "", sub, "" if role == AUTO_ROLE else role or ""
                )
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
            else:
                st.toast(
                    f"Placed in {mapped.stream}, as {mapped.role}.", icon=":material/check_circle:"
                )
                st.rerun()
    st.download_button(
        "Download this student's progress report (PDF)",
        orgs.student_report_pdf(org, cand),
        file_name=f"progress-{acct['username']}.pdf",
        mime="application/pdf",
        icon=":material/picture_as_pdf:",
        key=f"org_report_{sid}",
    )


# --- tab 4: settings and placement drives -----------------------------------------------------


def _settings() -> None:
    with st.container(border=True):
        st.subheader("Organization profile and pass marks", anchor=False)
        st.caption(
            f"Organization code {org.org_code} and admin login {org.admin_email} stay as they are. "
            "The pass marks decide who counts as ready and who the funnel and shortlist include."
        )
        with st.form("org_profile", border=False):
            left, right = st.columns(2)
            name = left.text_input("Organization name", value=org.name, key="org_set_name")
            location = right.text_input("Location", value=org.location, key="org_set_loc")
            batch = left.text_input("Academic batch", value=org.academic_batch, key="org_set_batch")
            quiz = left.slider(
                "Quiz pass mark (%)", 0, 100, org.quiz_cutoff_pct, key="org_set_quiz"
            )
            voice = right.slider(
                f"Voice pass mark (out of {VOICE_RUBRIC_MAX})",
                0,
                VOICE_RUBRIC_MAX,
                org.voice_cutoff_score,
                key="org_set_voice",
            )
            go = st.form_submit_button("Save changes", type="primary", icon=":material/save:")
        if go:
            try:
                orgs.update_organization(
                    org.id,
                    name=name,
                    location=location,
                    academic_batch=batch,
                    quiz_cutoff_pct=quiz,
                    voice_cutoff_score=voice,
                )
            except services.ServiceError as e:
                st.error(formatter.md_escape(str(e)), icon=":material/error:")
            else:
                st.toast("Saved.", icon=":material/check_circle:")
                st.rerun()

    with st.container(border=True):
        st.subheader("Placement drive shortlist", anchor=False)
        st.caption("Choose a drive's criteria. Suspended students are never listed.")
        domains_all = sorted({r.main_domain or r.stream for r in view.rows})
        c1, c2 = st.columns(2)
        domains = c1.multiselect("Main domain", domains_all, key="org_drive_domain")
        sub_options = sorted(
            {
                r.subdomain
                for r in view.rows
                if r.subdomain and (not domains or (r.main_domain or r.stream) in domains)
            }
        )
        subs = c2.multiselect("Subdomain", sub_options, key="org_drive_sub")
        c3, c4 = st.columns(2)
        quiz_min = c3.slider(
            "Quiz average at least (%)", 0, 100, org.quiz_cutoff_pct, key="org_drive_quiz"
        )
        voice_min = c4.slider(
            f"Voice average at least (/{VOICE_RUBRIC_MAX})",
            0,
            VOICE_RUBRIC_MAX,
            org.voice_cutoff_score,
            key="org_drive_voice",
        )
        criteria = org_insights.DriveFilter(
            main_domains=tuple(domains),
            subdomains=tuple(s for s in subs if s in sub_options),
            min_quiz=float(quiz_min),
            min_voice=float(voice_min),
        )
        drive = orgs.drive(org.id, criteria, view)
        st.metric(
            "Students meeting the criteria",
            f"{len(drive.shortlisted)} of {len(view.rows)}",
            border=True,
        )
        if drive.shortlisted:
            st.dataframe(
                org_insights.directory_rows(drive.shortlisted, cut),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("Nobody meets these criteria yet. Lower them, or wait for more results.")
        with st.container(horizontal=True):
            stamp = f"{datetime.now(UTC):%Y-%m-%d}"
            st.download_button(
                "Placement shortlist (CSV)",
                drive.csv,
                file_name=f"placement-shortlist-{stamp}.csv",
                mime="text/csv",
                type="primary",
                icon=":material/download:",
                disabled=not drive.shortlisted,
                key="org_drive_csv",
            )
            st.download_button(
                "Executive summary (PDF)",
                drive.pdf,
                file_name=f"executive-summary-{stamp}.pdf",
                mime="application/pdf",
                icon=":material/picture_as_pdf:",
                key="org_drive_pdf",
            )
        st.caption(
            "The summary carries your organization's name, batch figures, the funnel, results "
            "by domain and the top 25 of this shortlist: it is meant for company recruiters."
        )

    health = journey.service_status()
    with st.expander(
        f"Services: AI {health.active_ai} · voice {health.voice} · records {health.telemetry}",
        icon=":material/health_and_safety:",
    ):
        st.caption(
            "Each service falls back on its own: a paused provider is retried after a cooldown, "
            "and answers keep coming from the next one."
        )
        for p in health.ai:
            status_badge(STATE_BADGE[p.state], f"{p.label}: {p.detail}")
        status_badge(
            "done" if health.voice == "ElevenLabs" else "info", f"Voice: {health.voice_detail}"
        )


overview_tab, provisioning_tab, students_tab, settings_tab = st.tabs(
    [
        ":material/dashboard: Overview",
        ":material/group_add: Provisioning",
        ":material/groups: Students",
        ":material/tune: Settings and drives",
    ]
)
with overview_tab:
    _overview()
with provisioning_tab:
    _provisioning()
with students_tab:
    _directory()
with settings_tab:
    _settings()
