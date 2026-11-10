"""Voice Interview Agent for Skill Scout Nexus (Step 5 Mock Voice Interview Architecture).

Responsibilities:
- Converts interview questions into realistic spoken audio using ElevenLabs TTS API
  (`ELEVENLABS_API_KEY`) or Gemini TTS (`GEMINI_API_KEYS`), else a local or browser voice.
- Provides fallback to browser SpeechSynthesis / data URI synthetic wavs if API key is not present.
- Generates realistic role-specific behavioral, technical, and situational scenario questions
  tailored across student streams:
  * Engineering: System design & coding logic.
  * Commerce: Financial audit scenario & GST filing dispute.
  * Law: Moot court scenario & contractual breach interpretation.
  * Management: HR grievance handling & marketing case study.
- Seamlessly interfaces with Streamlit frontend.
"""

from __future__ import annotations

import base64
import logging
import random
from typing import Literal

from pydantic import BaseModel, Field

from core import speech_router

log = logging.getLogger("agents.voice_interview_agent")
Category = Literal["technical", "behavioral", "situational"]
CATEGORIES: tuple[Category, ...] = ("technical", "behavioral", "situational")


class VoiceInterviewQuestion(BaseModel):
    category: Category
    stream: str = Field(
        description="Target discipline / stream (Engineering, Commerce, Law, Management)"
    )
    role: str = Field(description="Specific target role")
    question_text: str = Field(min_length=15, description="Full spoken interview question")
    intent: str = Field(description="What competencies the interviewer is evaluating")
    scenario_context: str = Field(default="", description="Industry situational setup or backdrop")
    audio_base64: str | None = Field(
        default=None, description="MP3 audio base64 payload if synthesized"
    )
    tts_source: str = Field(
        default="browser_fallback", description="elevenlabs | gemini | pyttsx3 | browser_fallback"
    )


# --- Curated Domain Scenario Banks ---
DOMAIN_SCENARIOS: dict[str, list[dict[str, str]]] = {
    "Engineering": [
        {
            "category": "technical",
            "scenario": "High-throughput Distributed Architecture",
            "question": (
                "Imagine our e-commerce checkout service experiences a sudden 10x traffic spike "
                "during a flash sale, causing cascading database connection timeouts. How would "
                "you redesign the order ingestion pipeline and rate limiting to prevent database "
                "saturation while guaranteeing zero lost transactions?"
            ),
            "intent": (
                "Evaluates distributed systems architecture, asynchronous queues, caching, and "
                "graceful degradation."
            ),
        },
        {
            "category": "situational",
            "scenario": "Live Production Outage Debugging",
            "question": (
                "A critical microservice deployed 30 minutes ago is intermittently returning HTTP "
                "500 errors for 5% of active users. The metrics dashboards show elevated CPU "
                "utilization and garbage collection pauses. Walk me step-by-step through how you "
                "isolate whether this is a memory leak, a deadlock, or an external dependency "
                "failure."
            ),
            "intent": (
                "Assesses systematic root-cause analysis, production telemetry interpretation, "
                "and incident triage."
            ),
        },
        {
            "category": "behavioral",
            "scenario": "Technical Disagreement on Architecture",
            "question": (
                "Tell me about a time you strongly disagreed with a senior teammate's "
                "architectural or library choice for a project. How did you formulate your "
                "counter-proposal with data, and what was the ultimate resolution?"
            ),
            "intent": (
                "Evaluates technical persuasion, professional maturity, and collaborative "
                "consensus building."
            ),
        },
    ],
    "Commerce": [
        {
            "category": "situational",
            "scenario": "Financial Audit & Internal Controls",
            "question": (
                "During a statutory year-end audit of a manufacturing client, you notice a "
                "material mismatch between vendor ledger balances and physical inventory stock "
                "registers, with missing purchase order reconciliations in Q3. How do you design "
                "your audit procedure to test for revenue leakage or fictitious purchase entries?"
            ),
            "intent": (
                "Assesses analytical auditing procedures, internal control testing (ICFR), and "
                "fraud risk skepticism."
            ),
        },
        {
            "category": "technical",
            "scenario": "GST Filing & Input Tax Credit Dispute",
            "question": (
                "A client receives a notice from the GST department alleging a discrepancy "
                "between GSTR-2B and GSTR-3B regarding ineligible Input Tax Credit claimed on "
                "capital goods and blocked credits under Section 17(5). How would you reconcile "
                "the vendor invoices and draft the legal reply explaining the tax credit "
                "eligibility?"
            ),
            "intent": (
                "Tests practical grasp of statutory GST provisions, ITC reconciliation, and tax "
                "dispute drafting."
            ),
        },
        {
            "category": "behavioral",
            "scenario": "Financial Reporting Under Tight Deadlines",
            "question": (
                "Describe a scenario where you had to compile variance analysis or quarterly "
                "financial projections with incomplete ledger entries right before a board "
                "deadline. How did you maintain precision without compromising audit compliance?"
            ),
            "intent": (
                "Tests integrity under pressure, time management, and pragmatic prioritization."
            ),
        },
    ],
    "Law": [
        {
            "category": "situational",
            "scenario": "Contractual Breach & Force Majeure Interpretation",
            "question": (
                "Your corporate client entered into a multi-crore supply contract containing a "
                "standard force majeure clause. Due to sudden regulatory export tariffs and raw "
                "material supply chain interruptions, the vendor unilaterally stopped shipments "
                "and claimed frustration of contract under Section 56 of the Indian Contract Act. "
                "How would you advise the client on claiming liquidated damages versus invoking "
                "arbitration?"
            ),
            "intent": (
                "Evaluates mastery of contract law doctrines, risk evaluation, and dispute "
                "resolution strategy."
            ),
        },
        {
            "category": "technical",
            "scenario": "Moot Court & Constitutional Doctrine",
            "question": (
                "In a hypothetical challenge before the High Court against a state data "
                "surveillance notification, how would you construct arguments invoking the "
                "proportionality test laid down in the Justice K.S. Puttaswamy judgment regarding "
                "Article 21 privacy rights?"
            ),
            "intent": (
                "Evaluates constitutional jurisprudence, legal reasoning, and oral advocacy "
                "structure."
            ),
        },
        {
            "category": "behavioral",
            "scenario": "Ethical Client Representation",
            "question": (
                "How would you handle a situation where a corporate client asks you to overlook a "
                "non-compliance disclosure in a share purchase agreement due diligence report to "
                "close a deal quickly?"
            ),
            "intent": "Tests professional ethics, regulatory rigor, and client counsel fortitude.",
        },
    ],
    "Management": [
        {
            "category": "situational",
            "scenario": "HR Grievance & Attrition Resolution",
            "question": (
                "Two high-performing team leads from engineering and product have had an "
                "escalating interpersonal conflict regarding project attribution, leading to "
                "multiple complaints and rumors impacting team morale. How do you conduct an "
                "impartial grievance hearing, maintain psychological safety, and institute "
                "structural mediation?"
            ),
            "intent": (
                "Assesses HR mediation capabilities, empathy, organizational dynamics, and labor "
                "compliance."
            ),
        },
        {
            "category": "technical",
            "scenario": "Marketing ROI & CAC Breakdown Case Study",
            "question": (
                "Your B2B SaaS startup's Customer Acquisition Cost increased by 40% over the last "
                "two quarters while Customer Lifetime Value remained flat, resulting in an "
                "unfavorable CAC to LTV ratio. Walk me through the funnel audit you would conduct "
                "across performance marketing, lead nurturing, and sales conversion velocity to "
                "restore unit economics."
            ),
            "intent": (
                "Tests unit economics literacy, growth marketing funnel diagnostics, and "
                "analytical decision-making."
            ),
        },
        {
            "category": "behavioral",
            "scenario": "Managing Underperforming Stakeholders",
            "question": (
                "Describe an instance where a cross-functional project was at severe risk because "
                "a dependent team was consistently missing milestones. How did you manage upward "
                "communication and realign deliverables without burning relationships?"
            ),
            "intent": (
                "Evaluates stakeholder management, cross-functional leadership, and accountable "
                "execution."
            ),
        },
    ],
}


STREAMS = tuple(DOMAIN_SCENARIOS)  # the streams with their own scenario bank


def bank_stream(stream: str) -> str:
    """The scenario bank for a catalog stream (one without its own bank: Engineering)."""
    return stream if stream in DOMAIN_SCENARIOS else "Engineering"


def synthesize_speech_elevenlabs(text: str, api_key: str | None = None) -> tuple[bytes | None, str]:
    """(audio bytes, the voice that spoke: "elevenlabs" | "gemini" | "pyttsx3") or
    (None, "browser_fallback"). core/speech_router.py does the work: ElevenLabs, Gemini TTS
    or the local voice, with circuit breakers, and no exception ever escapes.
    `api_key=""` asks for the browser voice outright."""
    if api_key == "":
        return None, "browser_fallback"
    speech = speech_router.synthesize(text)
    return (speech.audio, speech.source) if speech.audio else (None, "browser_fallback")


def get_stream_from_role_or_domain(role: str, domain_id: str = "") -> str:
    """Normalizes role/domain into one of the four flagship interview streams."""
    r_lower = role.lower()
    d_lower = domain_id.lower()

    if any(k in r_lower or k in d_lower for k in ["law", "legal", "advocate", "counsel"]):
        return "Law"
    if any(
        k in r_lower or k in d_lower for k in ["commerce", "accountant", "audit", "tax", "finance"]
    ):
        return "Commerce"
    if any(
        k in r_lower or k in d_lower for k in ["management", "hr", "marketing", "business", "corp"]
    ):
        return "Management"
    return "Engineering"


def generate_voice_interview_question(
    target_role: str,
    stream: str | None = None,
    category: Category | None = None,
    include_audio: bool = True,
    elevenlabs_key: str | None = None,
    custom_question: str | None = None,
    custom_scenario: str | None = None,
    custom_intent: str | None = None,
) -> VoiceInterviewQuestion:
    """Generates a high-fidelity scenario question and synthesizes its audio.

    Args:
        target_role: Job role (e.g. 'Frontend Engineer', 'Chartered Accountant').
        stream: Optional stream override ('Engineering', 'Commerce', 'Law', 'Management').
        category: Optional category ('technical', 'behavioral', 'situational').
        include_audio: Whether to invoke ElevenLabs TTS if key is present.
        elevenlabs_key: "" forces the browser voice; None uses ELEVENLABS_API_KEY from .env.
        custom_question: Optional custom question text (e.g. from GitHub Project Viva).
        custom_scenario: Optional context label for custom question.
        custom_intent: Optional competency intent for custom question.
    """
    stream_name = stream or get_stream_from_role_or_domain(target_role)

    # A GitHub viva question arrives only as `custom_question` (the voice page's toggle); the
    # agent never reads UI state, so the same inputs always give the same kind of question.
    if custom_question:
        q_text = custom_question
        selected_category = category or "technical"
        scenario_context = custom_scenario or "GitHub Project Architecture Viva"
        intent = (
            custom_intent
            or "Evaluates architectural depth, code quality, and engineering trade-offs "
            "of the candidate's GitHub project."
        )
    else:
        scenarios = DOMAIN_SCENARIOS.get(stream_name, DOMAIN_SCENARIOS["Engineering"])

        if category:
            pool = [s for s in scenarios if s["category"] == category]
            selected = random.choice(pool) if pool else random.choice(scenarios)
        else:
            selected = random.choice(scenarios)

        q_text = selected["question"]
        selected_category = selected["category"]
        scenario_context = selected["scenario"]
        intent = selected["intent"]

    audio_b64 = None
    tts_source = "browser_fallback"

    if include_audio:
        audio_bytes, tts_source = synthesize_speech_elevenlabs(q_text, api_key=elevenlabs_key)
        if audio_bytes:
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

    return VoiceInterviewQuestion(
        category=selected_category,  # type: ignore
        stream=stream_name,
        role=target_role,
        question_text=q_text,
        intent=intent,
        scenario_context=scenario_context,
        audio_base64=audio_b64,
        tts_source=tts_source,
    )
