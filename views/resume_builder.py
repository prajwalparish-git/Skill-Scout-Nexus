"""Resume builder: the student's own details as an ATS-friendly resume, audited against
the target role, saved as numbered versions. "Find roles for your degree" lists the catalog
roles a completed or in-progress degree qualifies for and can set the target role. The form
takes any number of degrees (completed or being pursued) and jobs. The first saved version
locks the domain; the history shows what changed between versions, and "What to add next"
says what the student's quiz scores and projects now justify adding."""

from functools import partial

import streamlit as st

from core import github_readme as gh
from piq import charts, formatter, resume_builder, services, ui
from piq.config import EXPERIENCE_TYPES, RESUME_MAX_EDUCATION, RESUME_MAX_EXPERIENCE

BUILT = "built_resume"  # (domain id, resume dict, ATS result) of the last Generate
SAVED = "resume_saved"  # the version number just saved, shown once
PICK = "rb_pick"  # (domain id, role) chosen in "Find roles for your degree"
_GH_INTEL = "gh_intel"      # shared with projects.py: the last GitHubIntelligence result
_GH_URL = "gh_url_last"     # URL that produced it

ui.page_header(
    "Resume builder",
    "Build a single-column, ATS-friendly resume from your own details, see how it matches "
    "your target role, and save each improvement as a new version. Only what you enter goes "
    "on the resume; keywords and project ideas are suggestions.",
)

student = ui.current_student()
sid = student["id"] if student else None
profile = services.current_profile(sid)
versions = services.resume_history(sid)
latest = versions[-1] if versions else None
lock = services.locked_domain(sid)
key = sid or "new"  # widget keys per student: a switch never carries another's inputs over
codes = services.degree_codes()
STATUSES = services.DEGREE_STATUSES

# The form's starting values: the latest version's inputs, else what the profile read.
form = (latest.resume.get("form") if latest else None) or {}
if not form and profile:
    form = {"full_name": profile.name}
    if profile.education and profile.education != "Not stated":
        form["education"] = [services.education_from_text(profile.education)]
saved_education = resume_builder.form_education(form)
saved_jobs = form.get("experience") or []


def _use_role(domain_id: str, role: str) -> None:
    """Target a role found by degree: the domain and role pickers start from it."""
    st.session_state[PICK] = (domain_id, role)
    st.session_state.pop(f"rb_domain_{key}", None)
    st.session_state.pop(f"rb_role_{key}_{domain_id}", None)


# --- find roles for a degree ----------------------------------------------------------------
with st.expander("Find roles for your degree", icon=":material/travel_explore:"):
    st.caption(
        "Choose a degree you have completed or are pursuing. Roles open now are listed first; "
        "a degree in progress shows the roles it opens once you complete it."
    )
    first = next((e for e in saved_education if e.get("status") == "Pursuing"), None)
    first = first or (saved_education[0] if saved_education else {})
    f1, f2, f3 = st.columns([2, 2, 1], gap="small")
    with f1:
        find_code = st.selectbox(
            "Degree",
            codes,
            index=codes.index(first["degree"]) if first.get("degree") in codes else None,
            format_func=services.degree_label,
            placeholder="Choose a degree",
            key=f"rb_find_degree_{key}",
        )
    with f2:
        find_spec = st.text_input(
            "Specialisation or branch",
            value=first.get("specialization", ""),
            placeholder="e.g. Computer Science",
            key=f"rb_find_spec_{key}",
        )
    with f3:
        find_status = st.selectbox(
            "Status",
            STATUSES,
            index=STATUSES.index(first["status"]) if first.get("status") in STATUSES else 0,
            key=f"rb_find_status_{key}",
        )
    fits = services.roles_for_degree(find_code, find_spec, find_status) if find_code else []
    if find_code:
        st.markdown(formatter.role_fits_md(fits))
    pickable = [f for f in fits if not lock or f.domain_id == lock.domain.id]
    if lock and len(pickable) < len(fits):
        st.caption(
            f"Your domain is locked to {formatter.md_escape(lock.domain.name)}: roles in other "
            "domains are shown for reference."
        )
    if pickable:
        with st.container(horizontal=True, vertical_alignment="bottom"):
            chosen = st.selectbox(
                "Target one of these roles",
                pickable,
                format_func=lambda f: f"{f.role} ({f.domain_name})",
                key=f"rb_find_pick_{key}",
            )
            st.button(
                "Use this role",
                icon=":material/target:",
                on_click=_use_role,
                args=(chosen.domain_id, chosen.role),
            )

# --- domain and role -------------------------------------------------------------------
pick = st.session_state.get(PICK)
domains = list(services.domains())
col_dom, col_role = st.columns(2, gap="medium")
with col_dom:
    if lock:
        domain = lock.domain
        st.selectbox("Career domain", [domain.name], disabled=True, key=f"rb_domain_lock_{key}")
    else:
        role_now = latest.target_role if latest else profile.target_role if profile else None
        current = services.domain_of_role(role_now).id if role_now else domains[0].id
        current = pick[0] if pick else current
        domain = st.selectbox(
            "Career domain",
            domains,
            index=next((i for i, d in enumerate(domains) if d.id == current), 0),
            format_func=lambda d: d.name,
            key=f"rb_domain_{key}",
        )
roles = services.domain_roles(domain.id)
with col_role:
    wanted = latest.target_role if latest else profile.target_role if profile else None
    wanted = pick[1] if pick and pick[0] == domain.id else wanted
    role = st.selectbox(
        "Target job role",
        roles,
        index=roles.index(wanted) if wanted in roles else 0,
        key=f"rb_role_{key}_{domain.id}",
    )
if lock:
    st.markdown(formatter.locked_md(domain.name, lock.since, lock.by))
elif sid:
    st.caption(
        ":material/lock_open: Saving your first version locks your domain, so your plans and "
        "quizzes stay on one syllabus. You can still change role within it."
    )

role_info = resume_builder.get_role_info(role) or {}
# The original CS roles have no catalog entry (no description or keywords): no empty card.
if role_info:
    with st.container(border=True):
        st.markdown(f"**{formatter.md_escape(role)}** · {formatter.md_escape(domain.name)}")
        st.caption(role_info.get("description", ""))
        if degree := role_info.get("recommended_degree"):
            st.markdown(f"**Usual background:** {formatter.md_escape(degree)}")
        if keywords := role_info.get("ats_keywords"):
            st.caption(f"**Keywords recruiters scan for:** {', '.join(keywords)}")
        if ideas := role_info.get("sample_projects"):
            with st.expander("Project ideas for this role", icon=":material/lightbulb:"):
                st.caption(
                    "Ideas to build, not to copy onto the resume: add a project once it is yours."
                )
                for idea in ideas:
                    title = formatter.md_escape(idea["title"])
                    tech = formatter.md_escape(idea["tech"])
                    st.markdown(f"**{title}** :gray[({tech})]")

if saved_n := st.session_state.pop(SAVED, None):  # once, right after a save
    st.success(
        f"Saved version {saved_n}. Your profile and readiness now follow this resume.",
        icon=":material/task_alt:",
    )
    ui.show_last_run("Profile agent")

# --- what to add next (a returning student) -------------------------------------------------
if sid and profile:
    advice = services.resume_advice(sid, profile)
    lines = formatter.advice_lines(advice, formatter.local_today())
    with st.container(border=True):
        st.subheader("What to add next", anchor=False)
        if advice.due(formatter.local_today()):
            st.warning("Your resume is due for a review.", icon=":material/event:")
        if lines:
            st.markdown("  \n".join(lines))
        else:
            st.caption(
                "Nothing new yet. Average 70% or more on a topic over two quizzes, or finish a "
                "project, and it will be suggested here."
            )

st.divider()

# --- GitHub project import ---------------------------------------------------------------
has_rb_intel = bool(st.session_state.get(_GH_INTEL))
with st.expander(
    "Import project from GitHub URL", icon=":material/hub:", expanded=has_rb_intel
):
    st.caption(
        "Paste any public GitHub repository URL to auto-fill STAR bullets and tech stack "
        "into Section 5 of this form, and save 2 viva questions for your voice interview."
    )
    rb_gh_url = st.text_input(
        "Import Project from GitHub URL",
        placeholder="https://github.com/username/repo",
        key="rb_gh_import_url",
    )
    rb_col1, rb_col2 = st.columns([2, 1], gap="small")
    with rb_col1:
        rb_fetch = st.button(
            "Import from GitHub",
            type="primary",
            icon=":material/cloud_download:",
            key="rb_gh_import_btn",
            disabled=not rb_gh_url.strip(),
        )
    with rb_col2:
        if st.button("Clear", icon=":material/close:", key="rb_gh_clear"):
            st.session_state.pop(_GH_INTEL, None)
            st.session_state.pop(_GH_URL, None)
            st.session_state.pop(gh.VIVA_SESSION_KEY, None)
            st.rerun()

    if rb_fetch and rb_gh_url.strip():
        if rb_gh_url.strip() == st.session_state.get(_GH_URL):
            st.info("Already imported. Clear and re-import to refresh.", icon=":material/info:")
        elif not gh.parse_github_url(rb_gh_url.strip()):
            st.error(
                "Not a recognised GitHub URL. Use https://github.com/owner/repo.",
                icon=":material/error:",
            )
        else:
            with st.spinner("Fetching README …"):
                readme = gh.fetch_readme(rb_gh_url.strip())
            if readme is None:
                st.error(
                    "Could not fetch the README. Make sure the repository is public "
                    "and has a README.md at the root.",
                    icon=":material/error:",
                )
            else:
                role_kws = role_info.get("ats_keywords", [])
                with st.spinner("Extracting project intelligence …"):
                    intel = gh.extract_github_intelligence(readme, role_kws)
                if intel.is_empty:
                    st.warning(
                        "README fetched but the AI could not parse structured information. "
                        "Try a repository with a more detailed README.",
                        icon=":material/warning:",
                    )
                else:
                    st.session_state[_GH_INTEL] = intel
                    st.session_state[_GH_URL] = rb_gh_url.strip()
                    if intel.viva_questions:
                        st.session_state[gh.VIVA_SESSION_KEY] = intel.viva_questions
                    st.rerun()

    rb_intel = st.session_state.get(_GH_INTEL)
    if rb_intel and not rb_intel.is_empty:
        st.success(
            f"Imported: **{formatter.md_escape(rb_intel.project_title)}**",
            icon=":material/task_alt:",
        )
        st.markdown(formatter.github_intelligence_md(rb_intel))
        st.caption(
            "Copy the STAR bullets above into the **What you did and what it achieved** "
            "field in Section 5 below, and the tech stack into **Tools and technologies**."
        )
        if rb_intel.viva_questions:
            st.caption(
                ":material/mic: Viva questions are saved and will be used in your next "
                "Voice Interview automatically."
            )

st.divider()

# --- the form -----------------------------------------------------------------------------
gh_intel = st.session_state.get(_GH_INTEL)
gh_tech_skills = list(gh_intel.tech_stack) if (gh_intel and not gh_intel.is_empty) else []
previous_skills = (
    list(latest.resume["skills"]) if latest else list(profile.matched_skills) if profile else []
)
options = list(
    dict.fromkeys([*role_info.get("ats_keywords", []), *previous_skills, *gh_tech_skills])
)
space_projects = services.resume_projects(sid) if domain.code_space else []

# How many entries the form shows: outside the form, so a change redraws it at once.
n1, n2 = st.columns(2, gap="medium")
with n1:
    n_edu = st.number_input(
        "Education entries",
        min_value=1,
        max_value=RESUME_MAX_EDUCATION,
        value=min(max(1, len(saved_education)), RESUME_MAX_EDUCATION),
        help="Your degrees, highest first: one being pursued, any completed, Class 12 or 10.",
        key=f"rb_n_edu_{key}",
    )
with n2:
    n_jobs = st.number_input(
        "Jobs and internships",
        min_value=0,
        max_value=RESUME_MAX_EXPERIENCE,
        value=min(len(saved_jobs), RESUME_MAX_EXPERIENCE),
        help="Full-time jobs, internships, part-time, contract or freelance work, newest first.",
        key=f"rb_n_jobs_{key}",
    )

with st.form(f"builder_{key}", border=False):
    st.subheader("1. Contact details", anchor=False)
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        full_name = st.text_input(
            "Full name *", value=form.get("full_name", ""), placeholder="Your name"
        )
        email = st.text_input("Email *", value=form.get("email", ""), placeholder="you@example.com")
        phone = st.text_input("Phone", value=form.get("phone", ""), placeholder="+91 ...")
    with c2:
        location = st.text_input("City", value=form.get("location", ""), placeholder="City, State")
        linkedin = st.text_input(
            "LinkedIn or portfolio",
            value=form.get("linkedin_url", ""),
            placeholder="linkedin.com/in/...",
        )
        github = (
            st.text_input(
                "GitHub profile", value=form.get("github_url", ""), placeholder="github.com/..."
            )
            if domain.code_space
            else ""
        )

    st.subheader("2. Education", anchor=False)
    st.caption(
        "List what you are studying now and what you have completed, highest first. Mark a "
        "degree in progress as Pursuing with its expected year."
    )
    education = []
    for i in range(int(n_edu)):
        e = saved_education[i] if i < len(saved_education) else {}
        with st.container(border=True):
            e1, e2, e3 = st.columns([2, 2, 1], gap="small")
            with e1:
                code = st.selectbox(
                    "Qualification" + (" *" if i == 0 else ""),
                    codes,
                    index=codes.index(e["degree"]) if e.get("degree") in codes else None,
                    format_func=services.degree_label,
                    placeholder="Choose a qualification",
                    key=f"edu_{i}_degree",
                )
            with e2:
                spec = st.text_input(
                    "Specialisation or branch",
                    value=e.get("specialization", ""),
                    placeholder="e.g. Electronics & Communication",
                    key=f"edu_{i}_spec",
                )
            with e3:
                status = st.selectbox(
                    "Status",
                    STATUSES,
                    index=STATUSES.index(e["status"]) if e.get("status") in STATUSES else 0,
                    key=f"edu_{i}_status",
                )
            e4, e5, e6, e7 = st.columns([3, 1, 1, 1], gap="small")
            with e4:
                school = st.text_input(
                    "College, university or school" + (" *" if i == 0 else ""),
                    value=e.get("institution", ""),
                    key=f"edu_{i}_school",
                )
            with e5:
                start_y = st.text_input(
                    "Start year", value=e.get("start", ""), placeholder="2022", key=f"edu_{i}_s"
                )
            with e6:
                end_y = st.text_input(
                    "End or expected year",
                    value=e.get("end", ""),
                    placeholder="2026",
                    key=f"edu_{i}_e",
                )
            with e7:
                score = st.text_input(
                    "CGPA or %", value=e.get("score", ""), placeholder="8.2", key=f"edu_{i}_g"
                )
        entry = {
            "degree": code or "",
            "specialization": spec,
            "status": status,
            "institution": school,
            "start": start_y,
            "end": end_y,
            "score": score,
        }
        if e.get("title") and code == e.get("degree"):  # keep an older version's own wording
            entry["title"] = e["title"]
        education.append(entry)

    st.subheader("3. Work experience", anchor=False)
    if not n_jobs:
        st.caption(
            "None listed. Set Jobs and internships above to add full-time work or internships."
        )
    experience = []
    for j in range(int(n_jobs)):
        e = saved_jobs[j] if j < len(saved_jobs) else {}
        with st.container(border=True):
            w1, w2, w3 = st.columns([2, 2, 1], gap="small")
            with w1:
                title = st.text_input("Job title", value=e.get("title", ""), key=f"job_{j}_title")
            with w2:
                company = st.text_input(
                    "Company or organisation", value=e.get("company", ""), key=f"job_{j}_org"
                )
            with w3:
                kind = st.selectbox(
                    "Type",
                    EXPERIENCE_TYPES,
                    index=EXPERIENCE_TYPES.index(e["type"])
                    if e.get("type") in EXPERIENCE_TYPES
                    else 0,
                    key=f"job_{j}_type",
                )
            w4, w5, w6, w7 = st.columns([2, 1, 1, 1], gap="small", vertical_alignment="bottom")
            with w4:
                where = st.text_input("Location", value=e.get("location", ""), key=f"job_{j}_loc")
            with w5:
                start_m = st.text_input(
                    "Start", value=e.get("start", ""), placeholder="Jun 2024", key=f"job_{j}_s"
                )
            with w6:
                end_m = st.text_input(
                    "End", value=e.get("end", ""), placeholder="May 2025", key=f"job_{j}_e"
                )
            with w7:
                current = st.checkbox(
                    "I work here now", value=bool(e.get("current")), key=f"job_{j}_now"
                )
            highlights = st.text_area(
                "What you did and what it achieved (one bullet per line)",
                value=e.get("highlights", "\n".join(e.get("bullets", []))),
                placeholder="Built X with Y, which did Z\nCut A by 30% by changing B",
                height=90,
                key=f"job_{j}_hl",
            )
        experience.append(
            {
                "title": title,
                "company": company,
                "type": kind,
                "location": where,
                "start": start_m,
                "end": end_m,
                "current": current,
                "highlights": highlights,
            }
        )

    st.subheader("4. Skills", anchor=False)
    skills = st.multiselect(
        "Skills you can show evidence for",
        options=options,
        default=[s for s in previous_skills if s in options],
        help="The role's keywords are listed; choose only those you have used.",
    )
    extra_default = form.get("extra_skills", "") or (
        ", ".join(gh_tech_skills) if gh_tech_skills and not form.get("extra_skills") else ""
    )
    extra_raw = st.text_input(
        "Other skills (comma-separated)",
        value=extra_default,
        placeholder="e.g. Oscilloscope, KiCad, Python",
    )

    st.subheader("5. Projects", anchor=False)
    chosen_space = []
    if space_projects:
        titles = [p["title"] for p in space_projects]
        chosen_space = st.multiselect(
            "From your Project space",
            titles,
            default=titles,
            help="Projects marked On resume in your Project space; highlights become bullets.",
        )
    st.caption("Describe a project as: what you built, how, and the result, one bullet per line.")
    gh_proj_title = form.get("project_title", "") or (gh_intel.project_title if gh_intel else "")
    gh_proj_tech = form.get("project_tech", "") or (
        ", ".join(gh_intel.tech_stack) if gh_intel else ""
    )
    gh_proj_desc = form.get("project_desc", "") or (
        "\n".join(gh_intel.star_bullets) if gh_intel else ""
    )
    proj_title = st.text_input("Project title", value=gh_proj_title)
    proj_tech = st.text_input("Tools and technologies", value=gh_proj_tech)
    proj_desc = st.text_area(
        "What you did and what it achieved (one bullet per line)",
        value=gh_proj_desc,
        placeholder="Built X with Y, which did Z\nReduced A by 30% by changing B",
        height=110,
    )

    st.subheader("6. Certifications", anchor=False)
    certs_raw = st.text_area(
        "Certifications you hold (one per line)", value=form.get("certifications", ""), height=80
    )
    submitted = st.form_submit_button(
        "Build resume", type="primary", icon=":material/auto_awesome:"
    )

if submitted:
    extra = [s.strip() for s in extra_raw.split(",") if s.strip()]
    res = resume_builder.build_ats_resume_data(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        linkedin_url=linkedin,
        role_name=role,
        selected_skills=[*skills, *extra],
        custom_project_title=proj_title,
        custom_project_tech=proj_tech,
        custom_project_desc=proj_desc,
        github_url=github,
        certifications=[c for c in certs_raw.splitlines() if c.strip()],
        extra_projects=[p for p in space_projects if p["title"] in chosen_space],
        education=education,
        experience=experience,
        today=formatter.local_today(),
    )
    res["form"]["extra_skills"] = extra_raw
    st.session_state[BUILT] = (domain.id, res, resume_builder.evaluate_ats_compatibility(res, role))
    st.rerun()

# --- the built resume -------------------------------------------------------------------
built = st.session_state.get(BUILT)
if built and built[0] == domain.id and built[1]["target_role"] == role:
    _, res, ats = built
    st.divider()
    st.subheader("ATS check", anchor=False)
    score_col, detail_col = st.columns([1, 2], gap="large")
    with score_col, st.container(border=True):
        st.metric("ATS match", f"{ats.score}/100")
        state = "done" if ats.score >= 80 else "warning" if ats.score >= 60 else "error"
        word = (
            "Strong match" if ats.score >= 80 else "Fair match" if ats.score >= 60 else "Weak match"
        )
        st.markdown(formatter.status_md(state, word))
        if ats.degree_fit:
            st.markdown(formatter.degree_fit_md(ats.degree_fit))
        numbers = "yes" if ats.has_metrics else "none"
        st.caption(f"Action verbs: {ats.action_verbs_count} · Numbers in bullets: {numbers}")
    with detail_col, st.container(border=True):
        st.markdown(f"**Keywords found ({len(ats.matched_keywords)})**")
        st.markdown(formatter.skill_chips(ats.matched_keywords, present=True) or ":gray[None yet.]")
        if ats.missing_keywords:
            st.markdown(f"**Keywords not on the resume ({len(ats.missing_keywords)})**")
            st.markdown(formatter.skill_chips(ats.missing_keywords[:10], present=False))
        for tip in ats.suggestions:
            st.markdown(f":material/lightbulb: {formatter.md_escape(tip)}")
    if latest:
        diff = resume_builder.diff_resumes(latest.resume, res, latest.ats_score, ats.score)
        st.markdown(formatter.diff_md(diff, latest.n))

    pdf_name = formatter.resume_filename(res["full_name"], role)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.download_button(
            "Download PDF",
            data=partial(resume_builder.generate_ats_pdf, res),  # built only when clicked
            file_name=pdf_name,
            mime="application/pdf",
            icon=":material/download:",
            on_click="ignore",
        )
        label_save = f"Save as version {len(versions) + 1}" if sid else "Save and start coaching"
        save = st.button(label_save, type="primary", icon=":material/save:")
    if save:
        saved = ui.run_agent(
            "Profile agent", lambda ev: services.save_resume(sid, domain.id, res, ev)
        )
        if saved:
            st.session_state.pop(BUILT, None)
            st.session_state.pop(PICK, None)
            ui.set_student(saved[0], keep_runs=("Profile agent",), fresh=True)
            st.session_state[SAVED] = saved[1]  # after set_student, which clears old state
            st.rerun()

    with st.expander("Preview", expanded=True, icon=":material/visibility:"):
        preview_tab, standard_tab = st.tabs(
            [":material/auto_awesome: ATS-Optimised Preview", ":material/description: Standard"]
        )
        with preview_tab:
            st.caption(
                "Matched ATS keywords are **bolded**. Skills are grouped into ATS categories "
                "(Core Competencies · Frameworks · Tools · Action Verbs)."
            )
            st.markdown(formatter.ats_resume_preview_md(res, ats.matched_keywords))
        with standard_tab:
            st.markdown(formatter.resume_preview_md(res))

# --- version history -----------------------------------------------------------------------
if versions:
    st.divider()
    st.subheader("Your versions", anchor=False)
    scores = [v.ats_score for v in versions]
    hist_col, compare_col = st.columns(2, gap="medium")
    with hist_col, st.container(border=True, height="stretch"):
        first_score, last_score = scores[0], scores[-1]
        headline = (
            f"ATS score {first_score} at version 1, {last_score} now"
            if len(scores) > 1
            else f"Version 1 scores {first_score}/100"
        )
        st.markdown(f"**{headline}**")
        st.vega_lite_chart(
            spec=charts.ats_trend_spec(
                scores, [formatter.local_day(v.created_at) for v in versions]
            ),
            width="stretch",
            alt="ATS score by version: " + ", ".join(f"{s} of 100" for s in scores),
        )
        st.dataframe(formatter.versions_table(versions), width="stretch")
    with compare_col, st.container(border=True, height="stretch"):
        st.markdown("**Compare two versions**")
        numbers = [v.n for v in versions]
        if len(numbers) > 1:
            a, b = st.select_slider(
                "Versions", numbers, value=(numbers[-2], numbers[-1]), format_func=lambda n: f"v{n}"
            )
            old, new = versions[a - 1], versions[b - 1]
            st.markdown(
                formatter.diff_md(
                    resume_builder.diff_resumes(
                        old.resume, new.resume, old.ats_score, new.ats_score
                    ),
                    old.n,
                )
            )
        else:
            st.caption("Save a second version to compare what changed.")
        pick_n = st.selectbox(
            "Download a version",
            numbers,
            index=len(numbers) - 1,
            format_func=lambda n: f"Version {n}",
        )
        chosen_v = versions[pick_n - 1]
        st.download_button(
            f"Download version {pick_n} (PDF)",
            data=partial(resume_builder.generate_ats_pdf, chosen_v.resume),
            file_name=f"resume_v{pick_n}.pdf",
            mime="application/pdf",
            icon=":material/history:",
            on_click="ignore",
        )
