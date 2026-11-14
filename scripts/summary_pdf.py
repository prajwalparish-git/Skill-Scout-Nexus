"""Write docs/PlacementIQ_Summary.pdf: the abstract, key features and problems it solves.

    python -m scripts.summary_pdf                      # from evaluation/results/summary.json
    python -m scripts.summary_pdf --summary S --out O

The evaluation numbers come from the summary `python -m evaluation.run_eval` writes, so run
this again after every evaluation run. The page is HTML printed to A4 by Playwright's
Chromium (a dev dependency) with the app's own fonts and mark embedded,
so nothing is fetched. Never imported by the app; the test suite covers build_html only.
"""

import argparse
import base64
import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from piq.agents import roles
from piq.config import INTERVIEW_TYPES, PALETTE, QUIZ_SIZE, RESULTS_DIR, ROOT, STATIC_DIR
from piq.schemas import AnswerEvaluation

OUT = ROOT / "docs" / "PlacementIQ_Summary.pdf"
CASES = ROOT / "evaluation" / "test_cases.json"
FONTS = {
    "Body": STATIC_DIR / "fonts/atkinson-hyperlegible-next/AtkinsonHyperlegibleNext-latin.woff2",
    "Head": STATIC_DIR / "fonts/bricolage-grotesque/BricolageGrotesque-latin.woff2",
}
MARK = STATIC_DIR / "brand/mark.svg"
# The 0-5 integer fields are the interview criteria, in the order the app shows them.
CRITERIA = [n for n, f in AnswerEvaluation.model_fields.items() if f.annotation is int]
WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _pct(rate: float, digits: int = 0) -> str:
    """0.65 -> '65%'; with digits=1, 0.053 -> '5.3%' and 0.0 -> '0%'."""
    text = f"{rate * 100:.{digits}f}"
    return (text.rstrip("0").rstrip(".") if "." in text else text) + "%"


def _words(n: int) -> str:
    return WORDS[n] if n < len(WORDS) else str(n)


def _join(items: Sequence[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b and c'."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _repeats(summary: Mapping, topics: Sequence[str]) -> str:
    """The duplicate-rate clause, naming the topics measured when a run stopped early."""
    c = summary.get("consecutive")
    if not c or c.get("placementiq_duplicate_rate") is None:
        return ""
    measured = [html.escape(str(t)) for t in c.get("topics", [])]
    scope = "" if set(c.get("topics", [])) >= set(topics) else f", measured for {_join(measured)}"
    return (
        f"; over {c['quizzes_per_topic']} back-to-back quizzes per topic{scope}, "
        f"{_pct(c['placementiq_duplicate_rate'], 1)} of questions repeated "
        f"(baseline {_pct(c['baseline_duplicate_rate'], 1)})"
    )


def build_html(summary: Mapping, topics: Sequence[str]) -> str:
    """summary.json -> the two A4 pages as HTML. topics: every quiz topic the evaluation uses."""
    if summary.get("mode") != "live":
        raise SystemExit(f"the summary is from a {summary.get('mode')} run; quote live results")
    b, p = summary.get("baseline"), summary.get("placementiq")
    if not (b and p):
        raise SystemExit("the summary has no results for both systems; run the evaluation")
    n = p["cases"]
    iv = summary.get("interviews")
    followups = f" ({_pct(iv['followup_relevance'])} relevant in the evaluation)" if iv else ""
    plans = f"{_pct(p['plan_valid_rate'])} vs {_pct(b['plan_valid_rate'])}"
    quizzes = f"{_pct(p['quiz_valid_rate'])} vs {_pct(b['quiz_valid_rate'])}"
    rounds = _join([t if t == "HR" else t.lower() for t in INTERVIEW_TYPES])
    c = PALETTE["light"]
    fonts = "\n".join(
        f"@font-face {{ font-family: {name}; font-weight: 200 800; "
        f"src: url({_data_uri(path, 'font/woff2')}) format('woff2'); }}"
        for name, path in FONTS.items()
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>PlacementIQ</title><style>
{fonts}
@page {{ size: A4; margin: 16mm 17mm 15mm; }}
* {{ box-sizing: border-box; }}
body {{ font: 10.3pt/1.5 Body, sans-serif; color: {c["text"]}; margin: 0; }}
header {{ display: flex; align-items: center; gap: 12px; padding-bottom: 9px;
  border-bottom: 2px solid {c["primary"]}; margin-bottom: 4px; }}
header img {{ width: 40px; height: 40px; }}
h1 {{ font: 700 22pt/1.1 Head, sans-serif; margin: 0; }}
.sub {{ color: {c["muted"]}; font-size: 10pt; margin-top: 2px; }}
h2 {{ font: 700 13pt/1.25 Head, sans-serif; color: {c["primary_text"]}; margin: 15px 0 6px; }}
h2.page {{ break-before: page; margin-top: 0; }}
p {{ margin: 0 0 6px; text-align: justify; }}
ul {{ margin: 0; padding-left: 16px; }}
li {{ margin: 0 0 4px; }}
b {{ font-weight: 700; }}
.kw {{ color: {c["muted"]}; font-size: 9.4pt; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 9.6pt; }}
th, td {{ text-align: left; vertical-align: top; padding: 5px 7px;
  border-bottom: 1px solid {c["hairline"]}; }}
th {{ background: {c["surface"]}; font-weight: 700; }}
td:first-child {{ width: 4%; color: {c["muted"]}; }}
td:nth-child(2) {{ width: 34%; }}
tr {{ break-inside: avoid; }}
</style></head><body>
<header><img src="{_data_uri(MARK, "image/svg+xml")}" alt=""><div><h1>PlacementIQ</h1>
<div class="sub">An adaptive multi-agent placement-readiness coach for engineering students</div>
</div></header>

<h2>Abstract</h2>
<p>Engineering students prepare for campus placements with generic material that ignores their
resume, their target role and their own weak topics, and general-purpose AI chatbots give
unchecked, unrepeatable advice. PlacementIQ is a multi-agent system that turns a resume and a
target role into a personal, self-correcting preparation loop. A profile agent extracts skills;
code computes a readiness score and the missing skills against a role-to-skill map. A planner
agent writes a seven-day study plan weighted to the weakest topics, a quiz agent sets adaptive
multiple-choice quizzes, and an interviewer agent runs {rounds} mock interviews with follow-up
questions and scored feedback. A critic, built from deterministic checks followed by an LLM
judge in a LangGraph generate&ndash;verify&ndash;retry loop, verifies every generated output and
forces regeneration when it fails. Quiz scores update each topic&rsquo;s weakness, which reshapes
the next week&rsquo;s plan. On {n} frozen evaluation cases against a single-prompt baseline,
PlacementIQ produced valid plans in {_pct(p["plan_valid_rate"])} of cases (baseline
{_pct(b["plan_valid_rate"])}) and valid quizzes in {_pct(p["quiz_valid_rate"])} (baseline
{_pct(b["quiz_valid_rate"])}). It runs as one Streamlit application with one SQLite file on a
free LLM tier, and fully offline in a mock mode.</p>
<p class="kw"><b>Keywords:</b> multi-agent systems, large language models, LangGraph, critic
agent, adaptive learning, placement preparation, Streamlit, SQLite.</p>

<h2>Key features</h2>
<ul>
<li><b>Resume profiling:</b> a PDF, DOCX or TXT resume against one of {_words(len(roles()))}
roles gives a readiness score, matched and missing skills, and concrete resume fixes.</li>
<li><b>Adaptive weekly plan:</b> seven days of study with minutes weighted to weak topics, the
reason for the plan, the shift from last week, day check-off and export to calendar (.ics) or
CSV.</li>
<li><b>Adaptive quizzes:</b> topics ranked by weakness, difficulty suggested from recent scores,
{_words(QUIZ_SIZE)} questions never repeated from the student&rsquo;s history, and an answer
review saved as notes.</li>
<li><b>Mock interviews:</b> {rounds} rounds; follow-ups on vague answers; each answer scored on
{_join(CRITERIA)}, with a model answer and a session summary.</li>
<li><b>Critic loop on every output:</b> free deterministic checks first, then an LLM critic;
only rejected questions are rewritten, approved ones are cached, and every step is shown as a
trail.</li>
<li><b>Closed feedback loop:</b> quiz results change topic weakness, quiz difficulty and the next
week&rsquo;s plan automatically.</li>
<li><b>Progress dashboard:</b> readiness over time, study streak, 12-week activity calendar,
topic mastery with trends, interview scores, and agent and critic statistics.</li>
<li><b>Built-in evaluation:</b> a resumable harness compares PlacementIQ with a single-prompt
baseline on {n} frozen cases; a Results page explains each metric.</li>
<li><b>Practical to run:</b> offline mock mode, light and dark themes, phone-readable layout,
free-tier Groq models, 400+ automated offline tests and CI.</li>
</ul>

<h2 class="page">Problems it solves</h2>
<table><thead><tr><th>#</th><th>Problem</th><th>How PlacementIQ solves it</th></tr></thead>
<tbody>
<tr><td>1</td><td>Students do not know how ready they are for a role or which skills are
missing.</td><td>A readiness score and missing-skill list computed by code from the resume and a
role-to-skill map, so it is explainable and repeatable.</td></tr>
<tr><td>2</td><td>Preparation is generic and unplanned, with no focus on personal weak
areas.</td><td>A day-by-day weekly plan that gives the most time to the weakest topics and
states why.</td></tr>
<tr><td>3</td><td>Study plans stay fixed while the student improves or falls behind.</td>
<td>Quiz scores update topic weakness and difficulty; the next plan shifts minutes
accordingly.</td></tr>
<tr><td>4</td><td>AI-generated content is unreliable: invalid plans, wrong answer keys, ambiguous
or duplicate questions.</td><td>Every output passes deterministic checks and a critic before it
is shown; plan validity {plans}, quiz validity {quizzes} for a single prompt.</td></tr>
<tr><td>5</td><td>Practice repeats the same questions.</td><td>Questions are hashed and checked
against everything the student was asked before{_repeats(summary, topics)}.</td></tr>
<tr><td>6</td><td>Little access to realistic interview practice with feedback.</td>
<td>On-demand mock interviews with follow-ups on vague answers{followups}, rubric scores and a
model answer.</td></tr>
<tr><td>7</td><td>Progress is invisible, so motivation and course-correction suffer.</td>
<td>A dashboard of readiness over time, streak, activity and topic mastery.</td></tr>
<tr><td>8</td><td>Paid tools and complex infrastructure put AI coaching out of reach.</td>
<td>Free LLM tier, one process and one database file, and an offline mode for lab
machines.</td></tr>
</tbody></table>
</body></html>"""


def export_placement_shortlist_pdf(
    org_name: str,
    cutoffs: tuple[float, float] | str,
    students: Sequence[object],
    out: Path | None = None,
) -> bytes:
    """Generate a branded placement shortlist PDF report for an organization.
    Header prominently displays Organization.name and exact cutoffs used.
    Table includes 'Proctor Breach' column showing BREACH or CLEARED."""
    from fpdf import FPDF

    from piq.resume_builder import pdf_safe

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    # Header
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(26, 35, 38)
    pdf.cell(0, 10, pdf_safe(f"{org_name} - Placement Shortlist"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 105, 110)
    if isinstance(cutoffs, tuple):
        cutoff_str = f"Quiz > {cutoffs[0]:g}%, Voice > {cutoffs[1]:g}/15"
    else:
        cutoff_str = str(cutoffs)
    pdf.multi_cell(
        w, 5.5, pdf_safe(f"Pass Cutoffs Used: {cutoff_str}"), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(3)

    # Table
    pdf.set_font("Helvetica", "B", 9)
    headers = ["Name", "Domain", "Target role", "Quiz", "Voice", "Readiness", "Proctor Breach"]
    widths = (30, 32, 40, 14, 15, 17, 22)
    with pdf.table(col_widths=widths, text_align="LEFT", line_height=6) as t:
        head = t.row()
        for h in headers:
            head.cell(pdf_safe(h))
        pdf.set_font("Helvetica", "", 8)
        for s in students:
            row = t.row()
            name = getattr(s, "name", str(s))
            domain = getattr(s, "main_domain", "") or getattr(s, "stream", "")
            role = getattr(s, "target_role", "")
            quiz = getattr(s, "quiz_average", None)
            quiz_str = f"{quiz:g}%" if quiz is not None else "-"
            voice = getattr(s, "rubric_average", None)
            voice_str = f"{voice:g}/15" if voice is not None else "-"
            ready = getattr(s, "readiness", None)
            ready_str = f"{ready:.0f}" if ready is not None else "-"
            flags = getattr(s, "proctor_flags", 0)
            breach_str = "BREACH" if flags > 0 else "CLEARED"

            for cell_val in (name, domain, role, quiz_str, voice_str, ready_str, breach_str):
                row.cell(pdf_safe(str(cell_val)))

    content = bytes(pdf.output())
    if out:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    return content


def render(page: str, out: Path) -> None:
    """Print the HTML to an A4 PDF with Chromium."""
    from playwright.sync_api import sync_playwright  # dev dependency; tests never render

    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.set_content(page, wait_until="load")
            tab.evaluate("document.fonts.ready.then(() => true)")
            tab.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary", type=Path, default=RESULTS_DIR / "summary.json")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if not args.summary.exists():
        raise SystemExit(f"{args.summary} not found: run python -m evaluation.run_eval first")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    render(build_html(summary, sorted({case["quiz_topic"] for case in cases})), args.out)
    print(f"wrote {args.out}")
    return args.out


if __name__ == "__main__":
    main()
