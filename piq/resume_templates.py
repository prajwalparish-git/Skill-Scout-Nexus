"""Resume layouts by the kind of employer a student applies to.

Companies do not publish an official resume format, so these are layouts for a company TYPE,
shaped by common Indian placement practice; company names appear only as examples in a
template's hint. Every template stays ATS-safe: real text in one column, standard fonts and
standard section headings, no tables for layout, no images and no photo.

One section plan (`plan`) feeds both the PDF (`render_pdf`) and the previews (`preview_md`,
`preview_sections`), so what the student sees is what they download. Standard reproduces the
original ATS layout. The content (and so the ATS score) is the same in every template; only
the order, the headings and a few template-only sections differ.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from piq import degrees
from piq.resume_builder import (
    ATSDoc,
    education_dates,
    education_entries,
    experience_entries,
    job_dates,
    job_label,
)

DECLARATION = (
    "I hereby declare that the information furnished above is true to the best of my "
    "knowledge and belief."
)


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    best_for: str  # one line for the picker; company names only as examples
    sections: tuple[str, ...]  # the order of the body
    headings: Mapping[str, str]
    header: str = "centered"  # centered | left | cv (a "Curriculum Vitae" title, then left)
    one_page: bool = False  # the layout aims at one page (never cut: only reported)
    fields: frozenset[str] = field(default_factory=frozenset)  # extra inputs it uses
    skills_split: bool = False  # the original layout's two skill lines


TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template(
            "standard",
            "Standard",
            "A general ATS layout for any employer: summary, skills, experience, projects, "
            "education.",
            ("summary", "skills", "experience", "projects", "education", "certifications"),
            {
                "summary": "Professional Summary",
                "skills": "Core Competencies & Skills",
                "experience": "Work Experience",
                "projects": "Projects",
                "education": "Education",
                "certifications": "Certifications & Honors",
            },
            skills_split=True,
        ),
        Template(
            "service",
            "IT services / mass recruiter",
            "One page with marks up top, for campus drives at IT services firms (for example "
            "TCS, Infosys, Wipro, Cognizant or Accenture).",
            (
                "summary",
                "education",
                "skills",
                "projects",
                "experience",
                "certifications",
                "achievements",
                "personal",
            ),
            {
                "summary": "Career Objective",
                "education": "Education",
                "skills": "Technical Skills",
                "projects": "Projects",
                "experience": "Internships & Experience",
                "certifications": "Certifications",
                "achievements": "Achievements",
                "personal": "Personal Details",
            },
            one_page=True,
            fields=frozenset({"achievements", "personal_basic"}),
        ),
        Template(
            "product",
            "Product / startup",
            "Links and what you built first, for product companies and startups (for example "
            "a SaaS firm or a funded startup).",
            ("skills", "experience", "projects", "achievements", "education", "certifications"),
            {
                "skills": "Skills",
                "experience": "Experience",
                "projects": "Projects",
                "achievements": "Achievements",
                "education": "Education",
                "certifications": "Certifications",
            },
            header="left",
            one_page=True,
            fields=frozenset({"links", "achievements"}),
        ),
        Template(
            "core",
            "Core engineering",
            "Training, tools and projects first, for core engineering employers (for example "
            "L&T, Tata Motors or an EPC contractor).",
            (
                "summary",
                "experience",
                "skills",
                "projects",
                "education",
                "certifications",
                "achievements",
            ),
            {
                "summary": "Professional Summary",
                "experience": "Industrial Training & Experience",
                "skills": "Technical Skills & Tools",
                "projects": "Projects",
                "education": "Education",
                "certifications": "Certifications",
                "achievements": "Achievements",
            },
            one_page=True,
            fields=frozenset({"achievements"}),
        ),
        Template(
            "government",
            "Government / PSU",
            "A formal curriculum vitae with personal details, full marks, exam scores and a "
            "declaration (for example PSUs through GATE, bank PO or state services).",
            (
                "personal",
                "education",
                "exam_scores",
                "experience",
                "skills",
                "projects",
                "certifications",
                "achievements",
                "declaration",
            ),
            {
                "personal": "Personal Details",
                "education": "Educational Qualifications",
                "exam_scores": "Examination Scores",
                "experience": "Work Experience",
                "skills": "Skills",
                "projects": "Projects",
                "certifications": "Certifications",
                "achievements": "Achievements",
                "declaration": "Declaration",
            },
            header="cv",
            fields=frozenset({"personal", "exam_scores", "declaration", "achievements"}),
        ),
    )
}

# The layout a domain's students start from (they can pick any).
DOMAIN_DEFAULTS = {
    "cs": "product",
    "ece": "product",
    "mech": "core",
    "civil": "core",
    "eee": "core",
    "biotech": "core",
    "govt_central": "government",
    "govt_state": "government",
}

PERSONAL_LABELS = {
    "date_of_birth": "Date of Birth",
    "nationality": "Nationality",
    "languages": "Languages Known",
    "address": "Address",
}


def get(template_id: str | None) -> Template:
    """The template, or Standard for an empty id. KeyError for an unknown one."""
    return TEMPLATES[template_id or "standard"]


def default_for(domain_id: str | None) -> str:
    return DOMAIN_DEFAULTS.get(domain_id or "", "standard")


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "best_for": t.best_for,
            "one_page": t.one_page,
            "fields": sorted(t.fields),
        }
        for t in TEMPLATES.values()
    ]


# --- the section plan ----------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    title: str
    detail: str
    bullets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Section:
    key: str
    heading: str
    text: str = ""  # a paragraph
    lines: tuple[str, ...] = ()  # one line each (skills rows, certificates, details)
    entries: tuple[Entry, ...] = ()  # jobs, projects, degrees


@dataclass(frozen=True)
class Header:
    title: str  # "Curriculum Vitae", or ""
    name: str
    subtitle: str  # the target role
    lines: tuple[str, ...]  # contact (and links) lines


def _header(res: Mapping[str, Any], t: Template) -> Header:
    name, role = res.get("full_name", ""), res.get("target_role", "")
    if t.header == "left":  # links first: what a product interviewer opens
        links = res.get("links") or {}
        contact = res.get("contact") or {}
        link_line = " | ".join(f"{k}: {v}" for k, v in links.items() if v)
        basic = " | ".join(
            v for v in (contact.get(k, "") for k in ("location", "email", "phone")) if v
        )
        return Header("", name, role, tuple(x for x in (link_line, basic) if x))
    title = "Curriculum Vitae" if t.header == "cv" else ""
    return Header(title, name, role, (res.get("contact_line", ""),))


def _section(key: str, res: Mapping[str, Any], t: Template, today: date) -> Section | None:
    heading = t.headings.get(key, key.title())
    if key == "summary":
        text = res.get("summary", "")
        return Section(key, heading, text=text) if text else None
    if key == "skills":
        skills = res.get("skills", [])
        if t.skills_split:  # the original layout: always shown, in two labelled rows
            half = max(1, len(skills) // 2)
            rows = [f"Core Focus: {', '.join(skills[:half])}"]
            if skills[half:]:
                rows.append(f"Tools & Methodologies: {', '.join(skills[half:])}")
            return Section(key, heading, lines=tuple(rows))
        return Section(key, heading, lines=(", ".join(skills),)) if skills else None
    if key == "experience":
        jobs = [
            Entry(
                job_label(e),
                " | ".join(x for x in (e["type"], e["location"], job_dates(e)) if x),
                tuple(e["bullets"]),
            )
            for e in experience_entries(res)
        ]
        return Section(key, heading, entries=tuple(jobs)) if jobs else None
    if key == "projects":
        projects = [
            Entry(
                p.get("title", ""),
                f"Technologies: {p['tech']}" if p.get("tech") else "",
                tuple(p.get("bullets", [])),
            )
            for p in res.get("projects", [])
        ]
        return Section(key, heading, entries=tuple(projects)) if projects else None
    if key == "education":
        rows = []
        for e in education_entries(res):
            score = f"Performance: {e['score']}" if e.get("score") else ""
            detail = " | ".join(
                x for x in (e.get("institution", ""), education_dates(e), score) if x
            )
            rows.append(Entry(degrees.entry_label({**e, "status": "Completed"}), detail))
        return Section(key, heading, entries=tuple(rows)) if rows else None
    if key in ("certifications", "achievements", "exam_scores"):
        items = tuple(res.get(key, []))
        return Section(key, heading, lines=items) if items else None
    if key == "personal":
        personal = res.get("personal") or {}
        keys = ("nationality", "languages") if "personal_basic" in t.fields else PERSONAL_LABELS
        rows = tuple(f"{PERSONAL_LABELS[k]}: {personal[k]}" for k in keys if personal.get(k))
        return Section(key, heading, lines=rows) if rows else None
    if key == "declaration":
        place = res.get("declaration_place", "")
        sign = (
            f"Place: {place}" if place else "Place:",
            f"Date: {today.strftime('%d %b %Y')}",
            res.get("full_name", ""),
        )
        return Section(key, heading, text=DECLARATION, lines=sign)
    raise KeyError(key)


def plan(
    res: Mapping[str, Any], template_id: str | None = None, today: date | None = None
) -> tuple[Template, Header, list[Section]]:
    """The template (the resume's own unless one is given), its header and its non-empty
    sections, in order."""
    t = get(template_id if template_id is not None else res.get("template"))
    today = today or date.today()
    sections = [s for key in t.sections if (s := _section(key, res, t, today))]
    return t, _header(res, t), sections


# --- the PDF ---------------------------------------------------------------------------------


def _draw_header(pdf: ATSDoc, t: Template, h: Header) -> None:
    if t.id == "standard":  # the original header, unchanged
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(13, 102, 112)
        pdf.cell(0, 7, h.name.upper(), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(60, 70, 75)
        pdf.cell(0, 5, h.subtitle.upper(), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(80, 90, 95)
        pdf.cell(0, 4.5, h.lines[0] if h.lines else "", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        return
    align = "C" if t.header == "centered" else "L"
    if h.title:
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(20, 30, 35)
        pdf.cell(0, 7, h.title.upper(), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(20, 30, 35)
    pdf.multi_cell(0, 7, h.name, align=align, new_x="LMARGIN", new_y="NEXT")
    if h.subtitle:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(60, 70, 75)
        pdf.multi_cell(0, 5, h.subtitle, align=align, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(70, 80, 85)
    for line in h.lines:
        if line:
            pdf.multi_cell(0, 4.5, line, align=align, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def _draw_section(pdf: ATSDoc, s: Section) -> None:
    pdf.section_heading(s.heading)
    if s.text:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(30, 35, 40)
        pdf.multi_cell(0, 4.3, s.text, new_x="LMARGIN", new_y="NEXT")
        if not s.lines:
            pdf.ln(3)
    if s.entries:
        for e in s.entries:
            pdf.entry(e.title, e.detail, e.bullets)
        return
    if s.lines:
        listed = s.key in ("certifications", "achievements", "exam_scores")
        pdf.set_font("Helvetica", "", 8.5 if listed else 9)
        pdf.set_text_color(30, 35, 40)
        if s.key == "declaration":
            pdf.ln(2)
        for line in s.lines:
            pdf.multi_cell(
                0, 4.3, f"  -  {line}" if listed else line, new_x="LMARGIN", new_y="NEXT"
            )
        pdf.ln(3)


def render_pdf(
    res: Mapping[str, Any], template_id: str | None = None, today: date | None = None
) -> tuple[bytes, int]:
    """(PDF bytes, pages). A single-column, standard-font, text-only ATS PDF."""
    t, header, sections = plan(res, template_id, today)
    pdf = ATSDoc(format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    _draw_header(pdf, t, header)
    for s in sections:
        _draw_section(pdf, s)
    return bytes(pdf.output()), pdf.page_no()


# --- previews ------------------------------------------------------------------------------


def preview_sections(
    res: Mapping[str, Any], template_id: str | None = None, today: date | None = None
) -> dict[str, Any]:
    """The plan as plain data, for the web preview."""
    t, h, sections = plan(res, template_id, today)
    return {
        "template": t.id,
        "header": {
            "title": h.title,
            "name": h.name,
            "subtitle": h.subtitle,
            "lines": list(h.lines),
        },
        "sections": [
            {
                "key": s.key,
                "heading": s.heading,
                "text": s.text,
                "lines": list(s.lines),
                "entries": [
                    {"title": e.title, "detail": e.detail, "bullets": list(e.bullets)}
                    for e in s.entries
                ],
            }
            for s in sections
        ],
    }


def _md(text: str) -> str:
    return "".join(f"\\{c}" if c in "\\`*_[]#<>|~$" else c for c in text)


def preview_md(
    res: Mapping[str, Any], template_id: str | None = None, today: date | None = None
) -> str:
    """The plan as Markdown, for the preview."""
    t, h, sections = plan(res, template_id, today)
    out: list[str] = []
    if h.title:
        out.append(f"**{_md(h.title.upper())}**")
    out.append(f"### {_md(h.name)}")
    if h.subtitle:
        out.append(f"**{_md(h.subtitle)}**")
    out += [f":gray[{_md(line)}]" for line in h.lines if line]
    for s in sections:
        out.append(f"#### {_md(s.heading)}")
        if s.text:
            out.append(_md(s.text))
        for e in s.entries:
            out.append(f"**{_md(e.title)}**" + (f"  \n*{_md(e.detail)}*" if e.detail else ""))
            out += [f"- {_md(b)}" for b in e.bullets]
        listed = s.key in ("certifications", "achievements", "exam_scores")
        out += [f"- {_md(x)}" if listed else _md(x) for x in s.lines]
    return "\n\n".join(out)


def headings_in_order(res: Mapping[str, Any], template_id: str | None = None) -> list[str]:
    return [s.heading for s in plan(res, template_id)[2]]


def one_page_note(template_id: str, pages: int, sections: Sequence[Section] = ()) -> str:
    """A warning when a one-page layout runs over (nothing is cut)."""
    t = get(template_id)
    if not t.one_page or pages <= 1:
        return ""
    longest = sorted(sections, key=lambda s: -(len(s.entries) * 3 + len(s.lines)))[:2]
    names = " and ".join(s.heading for s in longest) or "the longest sections"
    return (
        f"This layout aims at one page and yours runs to {pages}. Nothing was cut: shorten "
        f"{names}, or keep the strongest bullets only."
    )
