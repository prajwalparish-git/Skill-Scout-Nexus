"""ATS resume builder: the student's own details as a single-column resume, an ATS keyword
audit against the target role, version-to-version differences and a vector PDF (fpdf2).

Only what the student entered goes on the resume. The role's keywords and the catalog's
sample projects are suggestions shown beside the form, never written into the resume.

A resume lists any number of education entries (Class 10 to a doctorate, each completed or
being pursued) and work entries (jobs, internships and other work, each with dates). Years of
experience are computed from the work dates, never typed in. Versions saved before education
and work became lists (one education dict, no work) read the same through
`education_entries` and `experience_entries`.
"""

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fpdf import FPDF

from piq import degrees, syllabus
from piq.config import EXPERIENCE_TYPES


@dataclass(frozen=True)
class ATSScoreResult:
    score: int
    matched_keywords: list[str]
    missing_keywords: list[str]
    action_verbs_count: int
    has_metrics: bool
    suggestions: list[str]
    # "now", "on completion", "no match", or "" when the role has no degree rule
    degree_fit: str = ""


def load_catalog() -> dict[str, Any]:
    return syllabus.catalog()


def list_domains() -> list[dict[str, Any]]:
    return load_catalog().get("domains", [])


def roles_for_domain(domain_identifier: str) -> list[dict[str, Any]]:
    for d in list_domains():
        if d["name"] == domain_identifier or d["id"] == domain_identifier:
            return d.get("roles", [])
    return []


def all_role_names() -> list[str]:
    names = []
    for d in list_domains():
        for r in d.get("roles", []):
            names.append(r["name"])
    return names


def get_role_info(role_name: str) -> dict[str, Any] | None:
    for d in list_domains():
        for r in d.get("roles", []):
            if r["name"].strip().lower() == role_name.strip().lower():
                return {**r, "domain_name": d["name"]}
    return None


ACTION_VERBS = {
    "architected",
    "engineered",
    "designed",
    "developed",
    "implemented",
    "optimized",
    "deployed",
    "automated",
    "spearheaded",
    "authored",
    "analyzed",
    "reduced",
    "improved",
    "scaled",
    "modeled",
    "simulated",
    "directed",
    "built",
    "programmed",
}

# --- dates and experience ------------------------------------------------------------------

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}


def parse_month(text: str) -> tuple[int, int] | None:
    """(year, month) from "2024-06", "06/2024", "Jun 2024", "June 2024" or "2024" (January),
    or None when the text is not a month."""
    t = text.strip().lower()
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})", t):
        year, month = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", t):
        year, month = int(m[2]), int(m[1])
    elif m := re.fullmatch(r"([a-z]+)\.?,?\s+(\d{4})", t):
        if m[1] not in _MONTHS:
            return None
        year, month = int(m[2]), _MONTHS[m[1]]
    elif m := re.fullmatch(r"(\d{4})", t):
        year, month = int(m[1]), 1
    else:
        return None
    if not (1 <= month <= 12 and 1950 <= year <= 2100):
        return None
    return year, month


def _index(ym: tuple[int, int]) -> int:
    return ym[0] * 12 + ym[1] - 1


def experience_months(entries: Sequence[Mapping[str, Any]], today: date) -> tuple[int, int]:
    """(work months, internship months): calendar months covered by entries with a valid
    start, an end before today counted inclusively, overlapping entries counted once. A
    current job ends this month. Entries without a readable start add nothing."""
    spans: dict[bool, list[tuple[int, int]]] = {True: [], False: []}
    now = today.year * 12 + today.month - 1
    for e in entries:
        start = parse_month(str(e.get("start", "")))
        if start is None:
            continue
        end = None if e.get("current") else parse_month(str(e.get("end", "")))
        last = min(_index(end), now) if end else now
        if last >= _index(start):
            spans[e.get("type") == "Internship"].append((_index(start), last))
    out = []
    for kind in (False, True):
        total, reach = 0, -1
        for a, b in sorted(spans[kind]):
            a = max(a, reach + 1)
            if b >= a:
                total += b - a + 1
                reach = b
        out.append(total)
    return out[0], out[1]


def duration_text(months: int) -> str:
    """12 -> "1 year", 27 -> "2 years 3 months", 5 -> "5 months"."""
    years, rest = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if rest or not years:
        parts.append(f"{rest} month{'s' if rest != 1 else ''}")
    return " ".join(parts)


def _bullets(text: str) -> list[str]:
    return [b.strip().lstrip("-*• ").strip() for b in text.splitlines() if b.strip()]


def clean_education(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Entries the student filled in (a degree other than "Other" or any text), trimmed."""
    out = []
    for e in raw:
        entry = {
            "degree": str(e.get("degree") or "Other").strip(),
            "specialization": str(e.get("specialization", "")).strip(),
            "institution": str(e.get("institution", "")).strip(),
            "start": str(e.get("start", "")).strip(),
            "end": str(e.get("end", "")).strip(),
            "status": e.get("status") if e.get("status") in degrees.STATUSES else "Completed",
            "score": str(e.get("score", "")).strip(),
        }
        if e.get("title"):
            entry["title"] = str(e["title"]).strip()
        if entry["institution"] or entry["specialization"] or e.get("title"):
            out.append(entry)
    return out


def clean_experience(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Work entries with a title or an organisation, trimmed; highlights become bullets."""
    out = []
    for e in raw:
        title = str(e.get("title", "")).strip()
        company = str(e.get("company", "")).strip()
        if not (title or company):
            continue
        current = bool(e.get("current"))
        bullets = e.get("bullets")
        out.append(
            {
                "title": title,
                "company": company,
                "type": e.get("type") if e.get("type") in EXPERIENCE_TYPES else "Full-time",
                "location": str(e.get("location", "")).strip(),
                "start": str(e.get("start", "")).strip(),
                "end": "" if current else str(e.get("end", "")).strip(),
                "current": current,
                "bullets": list(bullets) if bullets else _bullets(str(e.get("highlights", ""))),
            }
        )
    return out


def education_entries(res: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A resume's education as a list, whatever version saved it."""
    edu = res.get("education")
    if isinstance(edu, list):
        return edu
    if not edu or not (edu.get("degree") or edu.get("institution")):
        return []
    parsed = degrees.parse(edu.get("degree", ""))
    return [
        {
            "degree": parsed.code if parsed else "Other",
            "title": edu.get("degree", ""),
            "specialization": "",
            "institution": edu.get("institution", ""),
            "start": "",
            "end": edu.get("year", ""),
            "status": "Completed",
            "score": edu.get("gpa", ""),
        }
    ]


def form_education(form: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A saved form's education entries; a form saved before entry lists had one degree."""
    if "education" in form:
        return list(form["education"] or [])
    legacy = {
        "degree": form.get("degree", ""),
        "institution": form.get("institution", ""),
        "year": form.get("grad_year", ""),
        "gpa": form.get("gpa", ""),
    }
    return education_entries({"education": legacy})


def experience_entries(res: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(res.get("experience") or [])


def job_label(e: Mapping[str, Any]) -> str:
    """ "Firmware Intern, Acme Labs" """
    return ", ".join(x for x in (e.get("title", ""), e.get("company", "")) if x)


def job_dates(e: Mapping[str, Any]) -> str:
    end = "Present" if e.get("current") else e.get("end", "")
    return " - ".join(x for x in (e.get("start", ""), end) if x)


def education_dates(e: Mapping[str, Any]) -> str:
    end = e.get("end", "")
    if e.get("status") == "Pursuing":
        end = f"expected {end}" if end else "pursuing"
    return " - ".join(x for x in (e.get("start", ""), end) if x)


# --- building the resume ---------------------------------------------------------------------


def build_ats_resume_data(
    full_name: str,
    email: str,
    phone: str,
    location: str,
    linkedin_url: str,
    role_name: str,
    selected_skills: list[str],
    experience_level: str = "Fresher / Entry Level",
    degree: str = "",
    institution: str = "",
    grad_year: str = "",
    gpa: str = "",
    custom_project_title: str = "",
    custom_project_tech: str = "",
    custom_project_desc: str = "",
    github_url: str = "",
    certifications: list[str] | None = None,
    extra_projects: list[dict[str, Any]] | None = None,
    education: Sequence[Mapping[str, Any]] | None = None,
    experience: Sequence[Mapping[str, Any]] | None = None,
    today: date | None = None,
    template: str = "standard",
    leetcode_url: str = "",
    codeforces_url: str = "",
    portfolio_url: str = "",
    achievements: Sequence[str] | None = None,
    exam_scores: Sequence[str] | None = None,
    personal: Mapping[str, str] | None = None,
    declaration_place: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """The resume from the student's inputs only. `education` and `experience` are the form's
    entries (see clean_education / clean_experience); without `education`, the single
    degree / institution / grad_year / gpa fields make one entry. With `experience`, the
    years of experience in the summary are computed from its dates (`today` closes current
    jobs) and `experience_level` is ignored. `extra_projects` ({title, tech, bullets}) come
    from the Project space. Nothing is invented: no keyword is added to the skills, no sample
    project and no certificate the student did not enter. The raw inputs are kept under
    "form" so the next version starts from them.

    `template` (piq/resume_templates.py) picks the layout; `summary` replaces the written one
    (a tailored summary the student accepted). `personal` may hold date_of_birth and address:
    they go into this resume (and its PDF) only. They are never kept under "form", and
    without_private() strips them before anything is saved."""
    today = today or date.today()
    skills = list(dict.fromkeys(s.strip() for s in selected_skills if s.strip()))
    if education is None:
        legacy = {"degree": degree, "institution": institution, "year": grad_year, "gpa": gpa}
        edu = education_entries({"education": legacy})
    else:
        edu = clean_education(education)
    jobs = clean_experience(experience or [])

    focus = f" with hands-on work in {', '.join(skills[:4])}" if skills else ""
    if experience is not None:
        work, intern = experience_months(jobs, today)
        if work:
            lead = f"{role_name} with {duration_text(work)} of professional experience{focus}."
        else:
            internships = f" and {duration_text(intern)} of internships" if intern else ""
            lead = f"Entry-level {role_name}{focus}{internships}."
    else:
        fresher = experience_level.lower().startswith("fresher")
        level = "Entry-level" if fresher else experience_level.strip()
        lead = f"{level} {role_name}{focus}."
    written = (
        f"{lead} Builds and documents work end to end and keeps learning the fundamentals the "
        "role depends on."
    )
    pursuing = next((e for e in edu if e["status"] == "Pursuing"), None)
    if pursuing:
        name = degrees.entry_label({**pursuing, "status": "Completed"})
        when = f", completing in {pursuing['end']}" if pursuing["end"] else ""
        written += f" Currently pursuing {name}{when}."
    override = " ".join((summary or "").split())

    projects = []
    if custom_project_title.strip():
        projects.append(
            {
                "title": custom_project_title.strip(),
                "tech": custom_project_tech.strip(),
                "bullets": _bullets(custom_project_desc),
            }
        )
    for extra in extra_projects or []:
        if extra["title"] not in {p["title"] for p in projects}:
            projects.append(extra)

    links = [linkedin_url, github_url]
    extra_links = {
        "LeetCode": leetcode_url.strip(),
        "Codeforces": codeforces_url.strip(),
        "Portfolio": portfolio_url.strip(),
    }
    contact_parts = [p.strip() for p in [location, email, phone, *links] if p.strip()]
    contact_parts += [u for u in extra_links.values() if u]
    personal = {k: " ".join(str(v).split()) for k, v in (personal or {}).items() if str(v).strip()}
    return {
        "full_name": full_name.strip(),
        "contact_line": " | ".join(contact_parts),
        "contact": {
            "location": location.strip(),
            "email": email.strip(),
            "phone": phone.strip(),
        },
        "links": {
            "LinkedIn": linkedin_url.strip(),
            "GitHub": github_url.strip(),
            **extra_links,
        },
        "target_role": role_name,
        "template": template,
        "summary": override or written,
        "skills": skills,
        "experience": jobs,
        "education": edu,
        "projects": projects,
        "certifications": list(dict.fromkeys(c.strip() for c in certifications or [] if c.strip())),
        "achievements": [a.strip() for a in achievements or [] if a.strip()],
        "exam_scores": [s.strip() for s in exam_scores or [] if s.strip()],
        "personal": {k: v for k, v in personal.items() if k in PERSONAL_FIELDS},
        "declaration_place": declaration_place.strip(),
        "form": {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "location": location,
            "linkedin_url": linkedin_url,
            "github_url": github_url,
            "experience_level": experience_level,
            "education": [dict(e) for e in education] if education is not None else edu,
            "experience": [dict(e) for e in experience or []],
            "project_title": custom_project_title,
            "project_tech": custom_project_tech,
            "project_desc": custom_project_desc,
            "certifications": "\n".join(certifications or []),
            "template": template,
            "leetcode_url": leetcode_url,
            "codeforces_url": codeforces_url,
            "portfolio_url": portfolio_url,
            "achievements": "\n".join(achievements or []),
            "exam_scores": "\n".join(exam_scores or []),
            # never date_of_birth or address: those live in this resume only
            **{k: personal[k] for k in SAVED_PERSONAL if k in personal},
            "declaration_place": declaration_place,
            "summary": override,
        },
    }


# Personal details a Government / PSU resume may show. Date of birth and address go into the
# current resume and its PDF only: never saved, never put under "form", never logged.
PERSONAL_FIELDS = ("date_of_birth", "nationality", "languages", "address")
PRIVATE_FIELDS = ("date_of_birth", "address")
SAVED_PERSONAL = tuple(k for k in PERSONAL_FIELDS if k not in PRIVATE_FIELDS)


def merge_certifications(typed: Sequence[str], uploaded: Sequence[Mapping[str, str]]) -> list[str]:
    """Uploaded certificates ({title, line}) first, then the typed ones that do not repeat one
    (by its title or full line, ignoring case)."""
    known = {u[k].strip().casefold() for u in uploaded for k in ("title", "line")}
    rest = [t.strip() for t in typed if t.strip() and t.strip().casefold() not in known]
    return list(dict.fromkeys([*(u["line"] for u in uploaded), *rest]))


def without_private(res: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of the resume without date of birth or address anywhere: what may be saved."""
    out = copy.deepcopy(dict(res))
    out["personal"] = {
        k: v for k, v in (out.get("personal") or {}).items() if k not in PRIVATE_FIELDS
    }
    form = out.get("form")
    if isinstance(form, dict):
        for k in PRIVATE_FIELDS:
            form.pop(k, None)
    return out


def resume_text(res: dict[str, Any]) -> str:
    """The resume as plain text, for the profile agent (same sections as the PDF)."""
    jobs = "\n".join(
        f"Experience: {job_label(e)} ({e['type']}, {job_dates(e)})\n"
        + "\n".join(f"- {b}" for b in e["bullets"])
        for e in experience_entries(res)
    )
    projects = "\n".join(
        f"Project: {p['title']} ({p['tech']})\n" + "\n".join(f"- {b}" for b in p["bullets"])
        for p in res["projects"]
    )
    education = "\n".join(
        " | ".join(
            x
            for x in (
                degrees.entry_label(e),
                e.get("institution", ""),
                education_dates(e),
                e.get("score", ""),
            )
            if x
        )
        for e in education_entries(res)
    )
    certs = "\n".join(f"- {c}" for c in res.get("certifications", []))
    parts = [
        res["full_name"],
        res["contact_line"],
        f"OBJECTIVE: {res['summary']}",
        f"SKILLS: {', '.join(res['skills'])}",
        f"WORK EXPERIENCE:\n{jobs}" if jobs else "",
        f"EDUCATION:\n{education}" if education else "",
        f"PROJECTS:\n{projects}" if projects else "",
        f"CERTIFICATIONS:\n{certs}" if certs else "",
    ]
    return "\n\n".join(p for p in parts if p)


@dataclass(frozen=True)
class ResumeDiff:
    """What changed from one resume version to the next."""

    skills_added: list[str]
    skills_removed: list[str]
    projects_added: list[str]
    projects_removed: list[str]
    certifications_added: list[str]
    role_changed: tuple[str, str] | None
    ats_change: int
    experience_added: list[str] = field(default_factory=list)
    experience_removed: list[str] = field(default_factory=list)
    education_added: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.skills_added
            or self.skills_removed
            or self.projects_added
            or self.projects_removed
            or self.certifications_added
            or self.role_changed
            or self.ats_change
            or self.experience_added
            or self.experience_removed
            or self.education_added
        )


def _added(old: list[str], new: list[str]) -> list[str]:
    before = {x.lower() for x in old}
    return [x for x in new if x.lower() not in before]


def diff_resumes(
    old: dict[str, Any], new: dict[str, Any], old_ats: int = 0, new_ats: int = 0
) -> ResumeDiff:
    old_projects = [p["title"] for p in old.get("projects", [])]
    new_projects = [p["title"] for p in new.get("projects", [])]
    old_jobs = [job_label(e) for e in experience_entries(old)]
    new_jobs = [job_label(e) for e in experience_entries(new)]

    def degree_names(res: Mapping[str, Any]) -> list[str]:
        # A degree finished since the last version counts as new: compare labels with status.
        return [degrees.entry_label(e) for e in education_entries(res)]

    role = (old.get("target_role", ""), new.get("target_role", ""))
    return ResumeDiff(
        skills_added=_added(old.get("skills", []), new.get("skills", [])),
        skills_removed=_added(new.get("skills", []), old.get("skills", [])),
        projects_added=_added(old_projects, new_projects),
        projects_removed=_added(new_projects, old_projects),
        certifications_added=_added(old.get("certifications", []), new.get("certifications", [])),
        role_changed=role if role[0] != role[1] else None,
        ats_change=new_ats - old_ats,
        experience_added=_added(old_jobs, new_jobs),
        experience_removed=_added(new_jobs, old_jobs),
        education_added=_added(degree_names(old), degree_names(new)),
    )


def degree_fit(role_name: str, education: Sequence[Mapping[str, Any]]) -> str:
    """How the resume's degrees meet the role's degree rule: "now", "on completion",
    "no match", or "" when the role has none (or no degree is listed)."""
    info = get_role_info(role_name)
    rule = info.get("eligibility") if info else None
    if not rule or not education:
        return ""
    fit = degrees.fit(rule, education)
    if fit is None:
        return "no match"
    return "now" if fit[0] else "on completion"


def evaluate_ats_compatibility(resume_data: dict[str, Any], role_name: str) -> ATSScoreResult:
    role_info = get_role_info(role_name)
    target_keywords = role_info.get("ats_keywords", []) if role_info else []
    jobs = experience_entries(resume_data)
    projects = resume_data.get("projects", [])

    # Compile all text
    corpus = " ".join(
        [
            resume_data.get("summary", ""),
            " ".join(resume_data.get("skills", [])),
            " ".join(e["title"] + " " + " ".join(e.get("bullets", [])) for e in jobs),
            " ".join(
                p.get("title", "") + " " + p.get("tech", "") + " " + " ".join(p.get("bullets", []))
                for p in projects
            ),
        ]
    ).lower()

    matched = []
    missing = []
    for kw in target_keywords:
        # Whole words only: "Git" must not match inside "digital".
        if re.search(rf"(?<!\w){re.escape(kw.lower())}(?!\w)", corpus):
            matched.append(kw)
        else:
            missing.append(kw)

    # Check action verbs
    found_verbs = [v for v in ACTION_VERBS if re.search(rf"\b{v}\b", corpus)]
    has_metrics = any(char.isdigit() for char in corpus)

    # Compute ATS Score
    # 50 pts: keyword match ratio
    kw_ratio = len(matched) / max(len(target_keywords), 1)
    kw_score = min(50, int(kw_ratio * 50))

    # 20 pts: action verbs
    verb_score = min(20, len(found_verbs) * 4)

    # 15 pts: structure & metrics
    metric_score = 15 if has_metrics else 5

    # 15 pts: contact and completeness, 3 per section that is filled in
    edu = education_entries(resume_data)
    work = [*projects, *jobs]
    sections = [
        bool(resume_data.get("full_name")),
        bool(resume_data.get("contact_line")),
        any(e.get("institution") and (e.get("degree") or e.get("title")) for e in edu),
        bool(work),
        any(len(w.get("bullets", [])) >= 2 for w in work),
    ]
    completeness = 3 * sum(sections)

    total_score = min(98, kw_score + verb_score + metric_score + completeness)
    fit = degree_fit(role_name, edu)

    suggestions = []
    if fit == "no match":
        suggestions.append(
            f"This role usually asks for {role_info.get('recommended_degree', 'another degree')}"
            "; none of your degrees matches it, so screening filters may reject the resume."
        )
    if not sections[2]:
        suggestions.append("Add your degree and college: most screens filter on education.")
    if not sections[3]:
        suggestions.append(
            "Add at least one project or job: it is where ATS keywords carry weight."
        )
    elif not sections[4]:
        suggestions.append(
            "Give each project and job two or more bullets: what you did and its result."
        )
    if missing:
        suggestions.append(f"Incorporate missing core industry keywords: {', '.join(missing[:4])}.")
    if not has_metrics:
        suggestions.append("Add quantifiable metrics (e.g. 'improved by 25%') to your bullets.")
    if len(found_verbs) < 3:
        suggestions.append("Begin bullets with strong action verbs (e.g. Engineered, Optimized).")

    return ATSScoreResult(
        score=total_score,
        matched_keywords=matched,
        missing_keywords=missing,
        action_verbs_count=len(found_verbs),
        has_metrics=has_metrics,
        suggestions=suggestions,
        degree_fit=fit,
    )


_PDF_SUBSTITUTES = str.maketrans(
    {
        "–": "-",
        "—": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "•": "-",
        "…": "...",
        "₹": "Rs.",
        "→": "->",
        " ": " ",
        "​": "",
    }
)


def pdf_safe(text: str) -> str:
    """Text the PDF's core fonts can draw (Latin-1): common typography mapped to ASCII, any
    other character replaced, so a pasted dash or a rupee sign never breaks the export."""
    return text.translate(_PDF_SUBSTITUTES).encode("latin-1", "replace").decode("latin-1")


class ATSDoc(FPDF):
    def normalize_text(self, text: str) -> str:
        return super().normalize_text(pdf_safe(text))

    def section_heading(self, label: str) -> None:
        self.set_font("Helvetica", "B", 10.5)
        self.set_text_color(20, 30, 35)
        self.cell(0, 6, label.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(160, 175, 175)
        self.set_line_width(0.3)
        self.line(self.get_x(), self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def entry(self, title: str, detail: str, bullets: Sequence[str]) -> None:
        """A job, project or degree: bold title, grey detail line, bullets."""
        self.set_font("Helvetica", "B", 9.5)
        self.set_text_color(20, 30, 35)
        self.multi_cell(0, 4.5, title, new_x="LMARGIN", new_y="NEXT")
        if detail:
            self.set_font("Helvetica", "I", 8.5)
            self.set_text_color(70, 80, 85)
            self.multi_cell(0, 4, detail, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(30, 35, 40)
        for bullet in bullets:
            self.multi_cell(0, 4.2, f"  -  {bullet.strip()}", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)


def generate_ats_pdf(resume_data: Mapping[str, Any], template: str | None = None) -> bytes:
    """The resume as a single-column, standard-font, ATS-friendly PDF, in its template (or
    `template`); Standard is the original layout (piq/resume_templates.py)."""
    from piq import resume_templates  # it builds on this module's helpers

    return resume_templates.render_pdf(resume_data, template)[0]
