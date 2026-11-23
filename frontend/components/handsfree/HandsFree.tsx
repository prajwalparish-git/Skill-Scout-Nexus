"use client";

// The hands-free interview UI: the setup panel (the rules, the microphone check) and the runner
// that takes one question from spoken to submitted without a click: speak → think → listen →
// transcribe → review → submit. Every fallback (no mic, no voice detection, no transcript, no
// speech) moves to push-to-talk or typing, is noted on the run, and never blocks the student.

import { useCallback, useEffect, useRef, useState } from "react";
import { Keyboard, Loader2, Mic, MicOff, RotateCcw, Volume2 } from "lucide-react";
import { failure, get, post, type HandsfreeReason, type HandsfreeRules, type HandsfreeSummary, type QuestionSpeech, type Transcribed } from "@/lib/api";
import { Capture, encodeWav, openMic } from "@/lib/handsfree/audio";
import { createListener, holdToTalk, type Listener } from "@/lib/handsfree/listen";
import { cancelSpeech, speak } from "@/lib/handsfree/speak";

export type Setup = {
  rules: HandsfreeRules | null;
  stream: MediaStream | null;
  micReason: HandsfreeReason | null; // why there is no mic
  capture: Capture | null;
  listener: Listener | null;
  tier: "silero" | "loudness" | null;
  heard: boolean; // the mic check picked up speech
  ready: boolean;
};

/** Rules + microphone, prepared when hands-free is chosen (the mic prompt comes now, before any
 * proctoring or fullscreen, so it never interrupts the test). */
export function useHandsFreeSetup(active: boolean): Setup & { level: number } {
  const [s, setS] = useState<Setup>({ rules: null, stream: null, micReason: null, capture: null, listener: null, tier: null, heard: false, ready: false });
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!active) return;
    let live = true;
    let stream: MediaStream | null = null;
    let capture: Capture | null = null;
    let listener: Listener | null = null;
    void (async () => {
      const rules = await get<HandsfreeRules>("/api/handsfree/rules").catch(() => null);
      const mic = await openMic();
      if (!live) return mic.stream?.getTracks().forEach((t) => t.stop());
      if (!mic.stream) return setS((x) => ({ ...x, rules, micReason: mic.reason, ready: true }));
      stream = mic.stream;
      capture = new Capture(stream);
      listener = await createListener(stream, capture, rules?.silence_s ?? 2.5).catch(() => null);
      if (!live) return;
      setS({ rules, stream, micReason: null, capture, listener, tier: listener?.tier ?? null, heard: false, ready: true });
    })();
    const meter = setInterval(() => live && setLevel(listener?.level() ?? 0), 150);
    return () => {
      live = false;
      clearInterval(meter);
      listener?.destroy();
      capture?.close();
      stream?.getTracks().forEach((t) => t.stop());
      cancelSpeech();
      setS({ rules: null, stream: null, micReason: null, capture: null, listener: null, tier: null, heard: false, ready: false });
    };
  }, [active]);
  return { ...s, level };
}

/** Before starting: the rules in words, and whether the microphone works. */
export function HandsFreeSetup({ setup }: { setup: Setup & { level: number } }) {
  const r = setup.rules;
  return (
    <section className="rounded-2xl border border-hair p-4" aria-label="Hands-free rules and microphone check">
      <p className="font-medium">Hands-free: the same rules for everyone</p>
      {r ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
          <li>Each question is spoken aloud (and shown). You then have {r.think_s} s to think before the microphone opens.</li>
          <li>
            Answer aloud for up to {r.max_answer_s} s. {r.silence_s} s of silence ends your answer.
          </li>
          <li>
            Your answer is transcribed and shown for {r.review_s} s, then submitted.{" "}
            {r.retries ? `You may answer again ${r.retries === 1 ? "once" : `${r.retries} times`} per question.` : "There are no retries."}
          </li>
          <li>If the microphone or transcription fails, you type instead ({Math.round(r.typed_max_s / 60)} min per question); this is noted, never held against you.</li>
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">Loading the rules…</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        {!setup.ready ? (
          <span className="flex items-center gap-2 text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden /> Checking the microphone…
          </span>
        ) : setup.stream ? (
          <>
            <span className="flex items-center gap-2">
              <Mic size={14} aria-hidden /> Microphone on: say something to test
            </span>
            <span className="h-2 w-32 overflow-hidden rounded-full bg-hair" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(setup.level * 100)}>
              <span className="block h-full bg-ok transition-[width]" style={{ width: `${Math.round(setup.level * 100)}%` }} />
            </span>
            <span className="text-xs text-muted">
              End of answer detected by {setup.tier === "silero" ? "voice detection (on this device)" : "loudness (voice detection unavailable)"}.
            </span>
          </>
        ) : (
          <span className="flex items-center gap-2 text-warn">
            <MicOff size={14} aria-hidden /> No microphone ({setup.micReason}). Answers will be typed; this is noted.
          </span>
        )}
      </div>
    </section>
  );
}

type Phase = "speaking" | "thinking" | "listening" | "transcribing" | "review" | "typing" | "talking" | "sending";

const ATTEMPT_LIMIT_FALLBACK = "transcription unavailable" as const;

/** One question, from spoken to submitted. Remount it (key) for the next question. */
export function HandsFreeRunner({
  setup,
  runId,
  index,
  question,
  speech,
  onSubmit,
}: {
  setup: Setup;
  runId: string;
  index: number;
  question: string;
  speech: QuestionSpeech | undefined;
  onSubmit: (answer: string) => void;
}) {
  const r = setup.rules!;
  const [phase, setPhase] = useState<Phase>("speaking");
  const [left, setLeft] = useState(0); // seconds on the visible countdown
  const [speaking, setSpeaking] = useState(false);
  const [offerManual, setOfferManual] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [retriesLeft, setRetriesLeft] = useState(r.retries);
  const [typed, setTyped] = useState("");
  const [why, setWhy] = useState<HandsfreeReason | null>(null);
  const attempt = useRef(0);
  const alive = useRef(true);
  const sent = useRef(false);
  const talk = useRef<{ release: () => Float32Array } | null>(null);
  const typedRef = useRef("");
  typedRef.current = typed;

  const submit = useCallback(
    (answer: string) => {
      if (sent.current) return;
      sent.current = true;
      setPhase("sending");
      onSubmit(answer.trim() || "[No answer given in time]");
    },
    [onSubmit],
  );

  const toTyping = useCallback(
    (reason: HandsfreeReason) => {
      if (!alive.current) return;
      setWhy(reason);
      setPhase("typing");
      setLeft(r.typed_max_s);
      void post(`/api/handsfree/runs/${runId}/note`, { question_index: index, input: "typed", reason }).catch(() => undefined);
    },
    [index, r.typed_max_s, runId],
  );

  const send = useCallback(
    async (audio: Float32Array, input: "voice" | "push_to_talk") => {
      setPhase("transcribing");
      attempt.current += 1;
      const form = new FormData();
      form.append("question_index", String(index));
      form.append("attempt_no", String(attempt.current));
      form.append("input", input);
      form.append("audio", encodeWav(audio), "answer.wav");
      try {
        const res = await fetch(`/api/handsfree/runs/${runId}/transcribe`, { method: "POST", body: form });
        if (!res.ok) throw await failure(res);
        const t = (await res.json()) as Transcribed;
        if (!alive.current) return;
        if (!t.text) return toTyping("transcription unavailable");
        setTranscript(t.text);
        setRetriesLeft(t.retries_left);
        setPhase("review");
        setLeft(r.review_s);
      } catch {
        toTyping(ATTEMPT_LIMIT_FALLBACK);
      }
    },
    [index, r.review_s, runId, toTyping],
  );

  const listen = useCallback(async () => {
    const l = setup.listener;
    if (!l) return toTyping(setup.micReason ?? "voice detection unavailable");
    setPhase("listening");
    setLeft(r.max_answer_s);
    setOfferManual(false);
    const heard = await l.listen({
      silenceS: r.silence_s,
      maxS: r.max_answer_s,
      noSpeechS: r.no_speech_s,
      onSpeaking: setSpeaking,
      onNoSpeech: () => setOfferManual(true),
    });
    if (!alive.current || heard.ended === "stopped") return; // push-to-talk or typing took over
    if (!heard.audio) return toTyping("no speech detected");
    await send(heard.audio, "voice");
  }, [r, send, setup.listener, setup.micReason, toTyping]);

  // Speak → think → listen, once per question.
  useEffect(() => {
    alive.current = true;
    void (async () => {
      if (!setup.stream) {
        await speak(speech, question);
        return toTyping(setup.micReason ?? "microphone unavailable");
      }
      await setup.capture?.resume();
      setPhase("speaking");
      await speak(speech, question);
      if (!alive.current) return;
      setPhase("thinking");
      setLeft(r.think_s);
    })();
    return () => {
      alive.current = false;
      cancelSpeech();
      setup.listener?.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  // The visible countdowns; each phase's end moves on by itself.
  useEffect(() => {
    if (!["thinking", "listening", "review", "typing"].includes(phase)) return;
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [phase]);
  useEffect(() => {
    if (left > 0) return;
    if (phase === "thinking") void listen();
    else if (phase === "review") submit(transcript);
    else if (phase === "typing") submit(typedRef.current);
  }, [left, phase, listen, submit, transcript]);

  const again = useCallback(() => {
    if (phase !== "review" || retriesLeft <= 0) return;
    setTranscript("");
    void listen();
  }, [listen, phase, retriesLeft]);

  // Space: answer again during review (when a retry is left).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && ["TEXTAREA", "INPUT"].includes(t.tagName)) return;
      if (e.code === "Space" && phase === "review" && retriesLeft > 0) {
        e.preventDefault();
        again();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [again, phase, retriesLeft]);

  const pressTalk = async () => {
    if (!setup.capture || talk.current) return;
    setup.listener?.stop();
    setPhase("talking");
    talk.current = await holdToTalk(setup.capture);
  };
  const releaseTalk = () => {
    const t = talk.current;
    talk.current = null;
    if (!t) return;
    const audio = t.release();
    if (audio.length < 4000) return toTyping("no speech detected");
    void post(`/api/handsfree/runs/${runId}/note`, { question_index: index, input: "push_to_talk", reason: "no speech detected" }).catch(() => undefined);
    void send(audio, "push_to_talk");
  };

  return (
    <div className="mt-4 rounded-2xl border border-hair p-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {phase === "speaking" && (
          <span className="flex items-center gap-2">
            <Volume2 size={16} aria-hidden /> Listening to the question…
          </span>
        )}
        {phase === "thinking" && <span className="font-medium">Think: the microphone opens in {left} s</span>}
        {phase === "listening" && (
          <>
            <span className="flex items-center gap-2 font-medium text-ok">
              <Mic size={16} aria-hidden /> Answer now · {left} s left
            </span>
            <span className="text-muted">{speaking ? `Speaking… ${r.silence_s} s of silence ends your answer` : "Waiting for you to speak"}</span>
          </>
        )}
        {phase === "transcribing" && (
          <span className="flex items-center gap-2">
            <Loader2 size={16} className="animate-spin" aria-hidden /> Transcribing your answer…
          </span>
        )}
        {phase === "talking" && <span className="font-medium text-ok">Recording while you hold…</span>}
        {phase === "sending" && (
          <span className="flex items-center gap-2">
            <Loader2 size={16} className="animate-spin" aria-hidden /> Scoring your answer…
          </span>
        )}
      </div>

      {phase === "review" && (
        <div className="mt-2">
          <p className="text-sm text-muted">Your answer (submitted in {left} s):</p>
          <blockquote className="mt-1 rounded-xl bg-surface/60 p-3 text-sm">{transcript}</blockquote>
          {retriesLeft > 0 && (
            <button type="button" className="btn-ghost mt-2" onClick={again}>
              <RotateCcw size={14} aria-hidden /> Answer again (Space) · {retriesLeft} left
            </button>
          )}
        </div>
      )}

      {phase === "listening" && offerManual && (
        <div className="mt-3 flex flex-wrap gap-2 text-sm">
          <span className="text-muted">Not picking you up?</span>
          {setup.capture && (
            <button type="button" className="btn-ghost min-h-0 px-3 py-1" onPointerDown={() => void pressTalk()} onPointerUp={releaseTalk} onPointerLeave={releaseTalk}>
              <Mic size={14} aria-hidden /> Hold to talk
            </button>
          )}
          <button type="button" className="btn-ghost min-h-0 px-3 py-1" onClick={() => {
            setup.listener?.stop();
            toTyping("chose to type");
          }}>
            <Keyboard size={14} aria-hidden /> Type instead
          </button>
        </div>
      )}
      {phase === "talking" && (
        <button type="button" className="btn-ink mt-3" onPointerUp={releaseTalk} onPointerLeave={releaseTalk}>
          Release to finish
        </button>
      )}

      {phase === "typing" && (
        <div className="mt-2">
          <p className="text-sm text-muted">
            Type your answer ({why}): submitted in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}.
          </p>
          <label htmlFor="handsfree-typed" className="sr-only">
            Your answer
          </label>
          <textarea id="handsfree-typed" className="input mt-2 min-h-32" maxLength={3000} value={typed} onChange={(e) => setTyped(e.target.value)} />
          <button type="button" className="btn-primary mt-2" disabled={!typed.trim()} onClick={() => submit(typed)}>
            Submit answer
          </button>
        </div>
      )}
    </div>
  );
}

export function HandsFreeSummary({ summary }: { summary: HandsfreeSummary | undefined }) {
  if (!summary) return null;
  const parts = [`voice ${summary.voice}`, summary.push_to_talk ? `push-to-talk ${summary.push_to_talk}` : "", summary.typed ? `typed ${summary.typed}` : ""].filter(Boolean);
  return (
    <p className="mt-3 text-sm text-muted">
      Hands-free: answered by {parts.join(", ")}
      {summary.reasons.length ? ` (${summary.reasons.join("; ")})` : ""}.
    </p>
  );
}
