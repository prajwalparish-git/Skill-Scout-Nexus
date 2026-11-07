"""Step 5, proctored voice assessment: a spoken scenario question for the student's stream
(core/speech_router.py: ElevenLabs, else the browser's voice), a spoken or typed answer, a 0-15
rubric score with proctor flags (agents/rubric_evaluator_agent.py), recorded for the faculty."""

import streamlit as st
import streamlit.components.v1 as components

from piq import formatter, journey
from piq.config import VOICE_DEFAULT_CATEGORY, VOICE_RUBRIC_MAX
from piq.services import ServiceError
from piq.ui import Stat, page_header, require_profile, stat_row, status_badge

QUESTION, RESULT, TEXT, AUDIO = "voice_q", "voice_result", "voice_text", "voice_audio"
CATEGORY_LABELS = {
    "technical": "Technical",
    "situational": "Situational",
    "behavioral": "Behavioural",
}
RUBRIC = (
    "- **Content knowledge (0-5):** accuracy and depth for the role.\n"
    "- **Clarity and structure (0-5):** situation, task, action, result.\n"
    "- **Confidence and demeanour (0-5):** composed, direct, no deflection.\n"
    "- **Proctor flags:** very short, off-topic or buzzword-heavy answers."
)

page_header(
    "Proctored voice assessment",
    "Hear a scenario question for your stream, answer it aloud or in writing, and get a "
    f"0-{VOICE_RUBRIC_MAX} rubric score with notes on what to improve.",
)
sid, _ = require_profile()
me = journey.student(sid)


def _transcribe() -> None:
    """Callback, so the transcript can fill the answer box before it is drawn."""
    audio = st.session_state.get(AUDIO)
    text = journey.transcribe(audio.getvalue()) if audio else ""
    if text:
        st.session_state[TEXT] = text
    else:
        st.session_state["voice_note"] = (
            "Transcription is not available right now. Type your answer below."
        )


setup, rubric = st.columns([3, 2], gap="large")
with setup, st.container(border=True):
    default = journey.voice_stream(me.stream)
    stream = st.selectbox(
        "Stream", journey.VOICE_STREAMS, index=journey.VOICE_STREAMS.index(default)
    )
    category = st.segmented_control(
        "Question type",
        journey.CATEGORIES,
        default=VOICE_DEFAULT_CATEGORY,  # its question and audio are preloaded
        format_func=lambda c: CATEGORY_LABELS[c],
    )
    if st.button("Generate question", type="primary", icon=":material/play_circle:"):
        try:
            st.session_state[QUESTION] = journey.voice_question(sid, stream, category)
            st.session_state[RESULT] = None
            st.session_state[TEXT] = ""
        except ServiceError as e:
            st.error(formatter.md_escape(str(e)), icon=":material/error:")
with rubric, st.container(border=True):
    st.markdown(f"**How answers are scored (0-{VOICE_RUBRIC_MAX})**")
    st.markdown(RUBRIC)

vq: journey.VoiceQuestion | None = st.session_state.get(QUESTION)
if vq is None:
    st.caption("No question yet. Choose the stream and type, then press Generate question.")
    st.stop()

q = vq.question
with st.container(border=True):
    st.caption(
        f"{formatter.md_escape(q.stream)} · {CATEGORY_LABELS[q.category]} · "
        f"{formatter.md_escape(q.scenario_context)}"
    )
    st.markdown(f"#### {formatter.md_escape(q.question_text)}")
    st.markdown(f":gray[What the interviewer looks for: {formatter.md_escape(q.intent)}]")
    if vq.speech.audio:
        st.audio(vq.speech.audio, format="audio/mpeg")
    else:
        components.html(journey.browser_speech_html(vq.speech.text), height=48)
        st.caption("Spoken by your browser's own voice.")
journey.preload_next_voice(sid, q.stream, q.category)  # the next type's audio, while they answer

st.subheader("Your answer", anchor=False)
st.audio_input("Record your answer", key=AUDIO)
st.button(
    "Transcribe the recording",
    icon=":material/transcribe:",
    on_click=_transcribe,
    disabled=st.session_state.get(AUDIO) is None,
)
if note := st.session_state.pop("voice_note", None):
    st.info(note, icon=":material/keyboard:")
answer = st.text_area(
    "Answer (the transcript appears here; edit it or type instead)",
    key=TEXT,
    height=160,
    placeholder="Situation, task, action, result: what happened, what you did, what changed.",
)
if st.button("Score my answer", type="primary", icon=":material/grading:"):
    try:
        with st.spinner("The evaluator is scoring your answer"):
            st.session_state[RESULT] = journey.assess_answer(sid, q, answer)
    except ServiceError as e:
        st.error(formatter.md_escape(str(e)), icon=":material/error:")

result: journey.VoiceResult | None = st.session_state.get(RESULT)
if result is None:
    st.stop()

ev = result.evaluation
r = ev.rubric
st.subheader(f"{r.total_score}/{VOICE_RUBRIC_MAX}: {ev.performance_tier}", anchor=False)
stat_row(
    [
        Stat("Total", f"{r.total_score}/{VOICE_RUBRIC_MAX}"),
        Stat("Content knowledge", f"{r.content_knowledge}/5"),
        Stat("Clarity and structure", f"{r.verbal_clarity_star}/5"),
        Stat("Confidence", f"{r.confidence_demeanor}/5"),
    ]
)
with st.container(border=True):
    if ev.gap_flags.flag_details:
        status_badge("warning", f"{len(ev.gap_flags.flag_details)} proctor flag(s)")
        st.markdown("\n".join(f"- {formatter.md_escape(f)}" for f in ev.gap_flags.flag_details))
    else:
        status_badge("done", "No proctor flags")

good, better = st.columns(2, gap="medium")
with good, st.container(border=True, height="stretch"):
    st.markdown("**:material/thumb_up: Strengths**")
    st.markdown("\n".join(f"- {formatter.md_escape(s)}" for s in ev.strengths))
with better, st.container(border=True, height="stretch"):
    st.markdown("**:material/trending_up: To improve**")
    st.markdown("\n".join(f"- {formatter.md_escape(s)}" for s in ev.areas_for_improvement))
with st.expander("A model answer", icon=":material/star:"):
    st.markdown(formatter.md_escape(ev.exemplary_model_answer))
if not result.saved:
    st.warning(
        "This session could not be saved for the faculty dashboard.", icon=":material/cloud_off:"
    )
