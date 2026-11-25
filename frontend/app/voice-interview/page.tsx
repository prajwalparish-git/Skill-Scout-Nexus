"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  HelpCircle,
  Loader2,
  Mic,
  MicOff,
  Play,
  RotateCcw,
  Sparkles,
  StopCircle,
  Volume2,
  XCircle,
} from "lucide-react";
import { PageHeader, ErrorNote } from "@/components/ui";
import { SignInPrompt } from "@/components/site/auth";
import { useCandidate } from "@/lib/candidate";
import {
  journeyApi,
  type VoiceAssessResponse,
  type VoiceQuestionResponse,
} from "@/lib/journeyApi";
import { useProctor } from "@/lib/proctor/useProctor";
import { ProctorChoice, ProctorLayer, ProctorSummary } from "@/components/proctor/Proctor";

export default function VoiceInterviewPage() {
  const { candidate, loading: authLoading } = useCandidate();

  const [streams, setStreams] = useState<string[]>([]);
  const [selectedStream, setSelectedStream] = useState("Engineering");
  const [selectedCategory, setSelectedCategory] = useState("technical");

  const [generating, setGenerating] = useState(false);
  const [assessing, setAssessing] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [questionData, setQuestionData] = useState<VoiceQuestionResponse | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [assessment, setAssessment] = useState<VoiceAssessResponse | null>(null);

  // Audio recording state
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Audio playback for question
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const startingRef = useRef(false);
  const unmountedRef = useRef(false);

  // Leaving the page must not leave the microphone open or the question still being spoken.
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      const recorder = mediaRecorderRef.current;
      if (recorder) {
        recorder.onstop = null;
        if (recorder.state !== "inactive") recorder.stop();
        recorder.stream.getTracks().forEach((track) => track.stop());
      }
      audioRef.current?.pause();
      if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    };
  }, []);

  const proctor = useProctor({
    kind: "interview",
    signedIn: Boolean(candidate),
    onBreach: () => {},
  });

  useEffect(() => {
    if (!candidate) return;
    journeyApi.getStreams().then((res) => {
      setStreams(res.voice_streams || ["Engineering", "Management & Business", "Applied Sciences"]);
      if (res.voice_streams?.length) setSelectedStream(res.voice_streams[0]);
    }).catch(() => {});
  }, [candidate]);

  const runQuestion = async () => {
    setGenerating(true);
    setError(null);
    setAssessment(null);
    setAnswerText("");
    try {
      const res = await journeyApi.getVoiceQuestion(selectedStream, selectedCategory);
      setQuestionData(res);
      // Play audio if available
      if (res.speech.audio_base64) {
        const audioSrc = `data:${res.speech.media_type};base64,${res.speech.audio_base64}`;
        const audio = new Audio(audioSrc);
        audioRef.current = audio;
        audio.play().catch(() => {});
      } else if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const utter = new SpeechSynthesisUtterance(res.question.question_text);
        window.speechSynthesis.speak(utter);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (proctor.wanted) {
      proctor.open(`Voice-${selectedCategory}`, runQuestion);
    } else {
      await runQuestion();
    }
  };

  const startRecording = async () => {
    // A second click while the permission prompt is open must not open a second microphone.
    if (startingRef.current || isRecording) return;
    startingRef.current = true;
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (unmountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      audioChunksRef.current = [];
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: mediaRecorder.mimeType || "audio/webm" });
        stream.getTracks().forEach((track) => track.stop());
        setTranscribing(true);
        try {
          const res = await journeyApi.transcribeVoice(audioBlob);
          if (res.text) {
            setAnswerText((prev) => (prev ? `${prev} ${res.text}` : res.text));
          } else {
            setError("Transcription could not capture audio clearly. You can also type your answer below.");
          }
        } catch (err) {
          setError("Transcription service unavailable. You can type your answer directly.");
        } finally {
          setTranscribing(false);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      setError("Microphone permission denied or audio device unavailable.");
    } finally {
      startingRef.current = false;
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleAssess = async () => {
    if (!questionData) return;
    if (!answerText.trim()) {
      setError("Record or type an answer before submitting.");
      return;
    }
    setAssessing(true);
    setError(null);
    try {
      const attemptId = proctor.currentAttemptId() || undefined;
      if (proctor.phase === "running") {
        await proctor.end();
      }
      const res = await journeyApi.assessVoice(questionData.question, answerText, attemptId);
      setAssessment(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAssessing(false);
    }
  };

  const playQuestionAudio = () => {
    if (!questionData) return;
    if (questionData.speech.audio_base64) {
      const audioSrc = `data:${questionData.speech.media_type};base64,${questionData.speech.audio_base64}`;
      const audio = new Audio(audioSrc);
      audio.play().catch(() => {});
    } else if (typeof window !== "undefined" && "speechSynthesis" in window) {
      const utter = new SpeechSynthesisUtterance(questionData.question.question_text);
      window.speechSynthesis.speak(utter);
    }
  };

  if (authLoading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="animate-spin text-muted" size={32} />
      </div>
    );
  }

  if (!candidate) {
    return (
      <div>
        <PageHeader
          eyebrow="Placement Journey · Step 5"
          title="Proctored Voice Assessment"
          lead="Hear real scenario interview questions, answer aloud, and receive 0-15 rubric grading."
        />
        <div className="panel p-8 text-center max-w-lg mx-auto">
          <Mic size={36} className="mx-auto text-muted mb-3" />
          <p className="font-semibold text-ink">Sign in to take voice assessments</p>
          <p className="text-xs text-muted mt-1">
            Sign in to track your verbal clarity, content knowledge, and rubric benchmarks.
          </p>
          <SignInPrompt />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <ProctorLayer proctor={proctor} />
      <PageHeader
        eyebrow="Placement Journey · Step 5"
        title="Proctored Voice Assessment"
        lead="Hear industry scenario questions, speak or type your answer, and receive granular 0-15 rubric grading with targeted areas to improve."
      />

      <ErrorNote message={error} />

      {/* Setup Form */}
      {!questionData && (
        <form onSubmit={handleGenerateQuestion} className="panel p-6 space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-muted">Interview Stream</label>
              <select
                value={selectedStream}
                onChange={(e) => setSelectedStream(e.target.value)}
                className="input mt-1 w-full text-xs"
              >
                {streams.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-muted">Question Category</label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="input mt-1 w-full text-xs capitalize"
              >
                {["technical", "situational", "behavioral"].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="border-t border-hair pt-4">
            <ProctorChoice proctor={proctor} what="interview" />
          </div>

          <button
            type="submit"
            disabled={generating}
            className="btn-ink w-full flex items-center justify-center gap-2"
          >
            {generating ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>Synthesizing Voice Scenario...</span>
              </>
            ) : (
              <>
                <Sparkles size={16} />
                <span>Generate Voice Scenario Question</span>
              </>
            )}
          </button>
        </form>
      )}

      {/* Active Question & Recording Area */}
      {questionData && (
        <div className="space-y-6">
          <div className="panel p-6 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hair pb-3">
              <div className="flex items-center gap-2">
                <span className="chip border-ink/30 text-xs font-semibold capitalize">
                  {questionData.question.category}
                </span>
                <span className="text-xs text-muted">{questionData.question.stream}</span>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={playQuestionAudio}
                  className="btn-ghost text-xs flex items-center gap-1.5"
                >
                  <Volume2 size={13} /> Replay Audio
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setQuestionData(null);
                    setAssessment(null);
                  }}
                  className="btn-ghost text-xs"
                >
                  New Scenario
                </button>
              </div>
            </div>

            <div>
              <p className="font-display text-xl font-semibold text-ink">
                {questionData.question.question_text}
              </p>
              {questionData.question.scenario_context && (
                <p className="text-xs text-muted mt-2">
                  Context: {questionData.question.scenario_context}
                </p>
              )}
            </div>

            {/* Answer Input Area */}
            {!assessment && (
              <div className="space-y-4 border-t border-hair pt-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs font-semibold text-muted">Your Spoken or Written Response</p>
                  <div className="flex items-center gap-2">
                    {isRecording ? (
                      <button
                        type="button"
                        onClick={stopRecording}
                        className="btn bg-bad text-bg flex items-center gap-1.5 text-xs animate-pulse"
                      >
                        <StopCircle size={14} /> Stop Recording
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={startRecording}
                        className="btn-ghost flex items-center gap-1.5 text-xs text-ink"
                      >
                        <Mic size={14} /> Record Answer (Mic)
                      </button>
                    )}
                    {transcribing && (
                      <span className="text-xs text-muted flex items-center gap-1">
                        <Loader2 size={12} className="animate-spin" /> Transcribing speech...
                      </span>
                    )}
                  </div>
                </div>

                <textarea
                  rows={5}
                  placeholder="Record with mic above or type your answer here..."
                  value={answerText}
                  onChange={(e) => setAnswerText(e.target.value)}
                  className="input w-full text-xs font-mono"
                />

                <button
                  type="button"
                  disabled={assessing || !answerText.trim()}
                  onClick={handleAssess}
                  className="btn-ink w-full py-3 flex items-center justify-center gap-2 text-sm"
                >
                  {assessing ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      <span>Evaluating Answer with Rubric Agent...</span>
                    </>
                  ) : (
                    <span>Submit Answer for 0-15 Rubric Evaluation</span>
                  )}
                </button>
              </div>
            )}
          </div>

          {/* Assessment Breakdown */}
          {assessment && (
            <div className="panel p-6 border-2 border-hair space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-hair pb-4">
                <div>
                  <span className="eyebrow">Rubric Evaluation</span>
                  <h3 className="font-display text-3xl font-semibold mt-1">
                    Score: {assessment.evaluation.rubric.total_score} / {assessment.max_score}
                  </h3>
                  <p className="text-xs text-muted mt-1">
                    Performance Tier: <span className="font-semibold text-ink">{assessment.evaluation.performance_tier}</span>
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setQuestionData(null);
                    setAssessment(null);
                  }}
                  className="btn-ink text-xs flex items-center gap-1.5"
                >
                  <RotateCcw size={13} /> Try Another Scenario
                </button>
              </div>

              {/* Rubric Criteria 3-Column */}
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-hair p-4 text-center">
                  <p className="text-xs text-muted">Content Knowledge</p>
                  <p className="font-mono text-2xl font-bold mt-1">
                    {assessment.evaluation.rubric.content_knowledge}/5
                  </p>
                </div>
                <div className="rounded-xl border border-hair p-4 text-center">
                  <p className="text-xs text-muted">Clarity &amp; Structure (STAR)</p>
                  <p className="font-mono text-2xl font-bold mt-1">
                    {assessment.evaluation.rubric.verbal_clarity_star}/5
                  </p>
                </div>
                <div className="rounded-xl border border-hair p-4 text-center">
                  <p className="text-xs text-muted">Confidence &amp; Demeanour</p>
                  <p className="font-mono text-2xl font-bold mt-1">
                    {assessment.evaluation.rubric.confidence_demeanour}/5
                  </p>
                </div>
              </div>

              {/* Feedback Strengths and Improvements */}
              <div className="grid gap-6 md:grid-cols-2 text-xs">
                <div className="rounded-2xl border border-ok/30 bg-ok/[0.03] p-4 space-y-2">
                  <p className="font-semibold text-ok flex items-center gap-1.5">
                    <CheckCircle2 size={15} /> Observed Strengths
                  </p>
                  <ul className="space-y-1 list-disc pl-4 text-ink">
                    {assessment.evaluation.strengths.map((str, idx) => (
                      <li key={idx}>{str}</li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-2xl border border-warn/30 bg-warn/[0.03] p-4 space-y-2">
                  <p className="font-semibold text-warn flex items-center gap-1.5">
                    <AlertTriangle size={15} /> Areas for Improvement
                  </p>
                  <ul className="space-y-1 list-disc pl-4 text-ink">
                    {assessment.evaluation.areas_for_improvement.map((area, idx) => (
                      <li key={idx}>{area}</li>
                    ))}
                  </ul>
                </div>
              </div>

              {/* Gap flags if any */}
              {assessment.evaluation.gap_flags.flag_details.length > 0 && (
                <div className="rounded-xl border border-hair p-3 text-xs text-muted">
                  <p className="font-semibold text-warn">Evaluation Flags:</p>
                  <ul className="mt-1 space-y-1">
                    {assessment.evaluation.gap_flags.flag_details.map((flag, idx) => (
                      <li key={idx}>· {flag}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
