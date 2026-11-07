"""Run the test suite and write docs/test_report.md, the test-case table for the report.

    python -m scripts.test_report

Every row is a real test from this run (pytest --junitxml), so the table never drifts
from the code. Exit code is pytest's.
"""

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from piq.config import ROOT

# test module -> (test type, what it covers)
LAYERS = {
    "test_config": ("Unit", "Settings and environment"),
    "test_syllabus": ("Unit", "Domain syllabi, role topics and colour slots"),
    "test_stream_data": ("Unit", "Streams, stream roles, bank columns and sample resumes"),
    "test_schemas": ("Unit", "Pydantic output schemas"),
    "test_checks": ("Unit", "Deterministic critic rules"),
    "test_db": ("Unit", "SQLite repository"),
    "test_db_failover": ("Unit", "Telemetry layer: PostgreSQL to SQLite failover, CRUD, analytics"),
    "test_llm": ("Unit", "LLM gateway (fake Groq client) and the offline tier"),
    "test_ai_router": ("Unit", "Layer 3 AI router: breakers, failover, Gemini and Ollama"),
    "test_speech_router": ("Unit", "Layer 3 speech router: ElevenLabs and browser voice"),
    "test_load_balancer": ("Unit", "Layer 3 speed: key pool round robin, 429 failover, cache"),
    "test_offline": ("Unit", "Layer 3 offline tier: answers from data/"),
    "test_preloader": ("Integration", "Layer 3 preloading: concurrent tasks, served once, on disk"),
    "test_auth_and_continuity": (
        "Integration",
        "Accounts: PBKDF2, 9-digit codes, lockout, mail, sessions, continuity, uploads",
    ),
    "test_graph": ("Unit", "LangGraph critic loop"),
    "test_resume": ("Unit", "Resume parsing"),
    "test_formatter": ("Unit", "Output layer"),
    "test_agents": ("Integration", "Agents through the critic loop"),
    "test_services": ("Integration", "User flows through the service layer"),
    "test_services_syllabus": (
        "Integration",
        "Domain topics, multi-topic quizzes, resume versions, Project space",
    ),
    "test_seed": ("Integration", "Demo seed data"),
    "test_eval": ("Integration", "Evaluation harness"),
    "test_report": ("Integration", "Results report"),
    "test_check_models": ("Integration", "Model availability check"),
    "test_export_graph": ("Integration", "Graph export"),
    "test_test_report": ("Integration", "Test report generator"),
    "test_screenshots": ("Unit", "Screenshot tool helpers"),
    "test_perf": ("Unit", "Performance tool helpers"),
    "test_theme": ("Unit", "Design tokens: contrast and distinctness"),
    "test_charts": ("Unit", "Chart builders: encodings and theme"),
    "test_ci": ("Unit", "CI workflow settings"),
    "test_bootstrap": ("Unit", "One-command setup: platform, uv pin, launchers, .env"),
    "test_tunnel": ("Unit", "Demo tunnel settings"),
    "test_summary_pdf": ("Unit", "Summary PDF builder"),
    "test_resume_builder": ("Unit", "ATS resume builder and PDF compilation"),
    "test_scorecard": ("Unit", "Evaluation scorecard parameters and ratings"),
    "test_degrees": ("Unit", "Degrees and the roles they qualify for"),
    "test_question_bank": ("Integration", "Local question bank and its share of quizzes"),
    "test_server": ("Integration", "HTTP API for the Next.js frontend"),
    "test_all_domains": ("Integration", "Every role and domain, resume to interview"),
    "test_agents_layer2": ("Integration", "Layer 2 agents: resume parser, planner, critic quiz"),
    "test_voice_interview_step5": ("Integration", "Voice interview and rubric evaluator agents"),
    "test_cohort": ("Unit", "Cohort analytics, readiness report and faculty charts"),
    "test_journey": ("Integration", "Six-step journey: agents and telemetry, end to end"),
    "test_ui": ("System (UI)", "Streamlit pages, headless"),
    "test_ui_journey": ("System (UI)", "Six-step journey pages, headless"),
}
ORDER = list(LAYERS)


def _describe(name: str) -> str:
    base, _, param = name.partition("[")
    text = base.removeprefix("test_").replace("_", " ")
    text = text[:1].upper() + text[1:]
    return f"{text} [{param}" if param else text


def build_markdown(junit_xml: str, generated: str) -> str:
    cases = []
    for tc in ET.fromstring(junit_xml).iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            result = "Fail"
        elif tc.find("skipped") is not None:
            result = "Skip"
        else:
            result = "Pass"
        module = tc.get("classname", "").split(".")[-1]
        cases.append((module, tc.get("name", ""), result, float(tc.get("time", 0))))
    cases.sort(key=lambda c: ORDER.index(c[0]) if c[0] in LAYERS else len(ORDER))
    totals = Counter(c[2] for c in cases)
    seconds = sum(c[3] for c in cases)

    lines = [
        "# Test report",
        "",
        f"Generated {generated} by `python -m scripts.test_report` from a real run of the suite "
        "(offline: MOCK_MODE, temporary databases, fake Groq clients for live code paths).",
        "",
        f"**{len(cases)} tests: {totals['Pass']} passed, {totals['Fail']} failed, "
        f"{totals['Skip']} skipped** ({seconds:.0f} s of test time).",
        "",
        "## By module",
        "",
        "| Type | Area | Module | Tests | Passed |",
        "|---|---|---|---|---|",
    ]
    for module in dict.fromkeys(c[0] for c in cases):
        kind, area = LAYERS.get(module, ("Other", module))
        mod_cases = [c for c in cases if c[0] == module]
        passed = sum(c[2] == "Pass" for c in mod_cases)
        lines.append(f"| {kind} | {area} | `{module}` | {len(mod_cases)} | {passed} |")
    lines += [
        "",
        "## Test cases",
        "",
        "| ID | Type | Area | Test case (expected behaviour) | Result |",
        "|---|---|---|---|---|",
    ]
    for i, (module, name, result, _) in enumerate(cases, 1):
        kind, area = LAYERS.get(module, ("Other", module))
        lines.append(f"| TC-{i:03d} | {kind} | {area} | {_describe(name)} | {result} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "test_report.md")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ]
        code = subprocess.run(cmd, cwd=ROOT).returncode
        if not junit.exists():
            print("pytest produced no report")
            return code or 1
        text = junit.read_text(encoding="utf-8")
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    args.out.write_text(build_markdown(text, stamp), encoding="utf-8")
    print(f"wrote {args.out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
