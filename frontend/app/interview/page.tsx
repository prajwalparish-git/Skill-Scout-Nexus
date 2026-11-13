"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Award, Check, Clock, Loader2, Mic, Send, ShieldCheck, TrendingDown } from "lucide-react";
import { get, postStream, type Evaluation, type Track, type TurnResult } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { Badge, ErrorNote, Loading, NeedsCandidate, PageHeader } from "@/components/ui";

const CRITERIA = ["relevance", "depth", "structure", "clarity"] as const;
const MAX_ANSWER = 3000;
const TOTAL = 5;

/** The four rubric scores (out of 5) as labelled bars; the numbers carry the meaning. */
function Rubric({ evaluation }: { evaluation: Evaluation }) {
  return (
    <dl className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
      {CRITERIA.map((c) => (
        <div key={c}>
          <div className="flex justify-between text-xs">
            <dt className="capitalize text-muted">{c}</dt>
            <dd className="font-mono font-semibold tabular-nums">{evaluation[c]}/5</dd>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-hair" aria-hidden>
            <div className="h-full rounded-full bg-ink" style={{ width: `${(evaluation[c] / 5) * 100}%` }} />
          </div>
        </div>
      ))}
    </dl>
  );
}

const elapsedLabel = (ms: number) => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

/** A row of bars that pulse while the critic is evaluating: a thinking indicator, not a mic. */
function ThinkingPulse() {
  return (
    <span className="flex items-end gap-[3px]" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <motion.span
          key={i}
          className="w-[3px] rounded-full bg-ok"
          animate={{ height: [4, 14, 4] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut", delay: i * 0.1 }}
        />
      ))}
    </span>
  );
}

export default function InterviewPage() {
  const { candidate, loading: candidateLoading } = useCandidate();
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [track, setTrack] = useState("");
  const [result, setResult] = useState<TurnResult | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // A live elapsed timer while the interview is in progress, ticking once a second.
  useEffect(() => {
    if (!startedAt || result?.session.done) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [startedAt, result?.session.done]);

  useEffect(() => {
    setResult(null);
    setTracks(null);
    setError(null);
    setStartedAt(null);
    if (!candidate) return;
    let current = true; // a reply for the previous candidate must not land on this one
    get<Track[]>(`/api/interview/tracks/${candidate.id}`).then(
      (t) => {
        if (!current) return;
        setTracks(t);
        setTrack(t[0]?.name ?? "");
      },
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [candidate]);

  // Braces: newer browsers return a Promise from scrollIntoView, and React would take a
  // returned value for the effect's cleanup function.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [result, steps]);

  async function turn(body: Record<string, unknown>) {
    if (!candidate) return;
    setBusy(true);
    setError(null);
    setSteps([]);
    try {
      await postStream("/api/interview/turn", { candidate_id: candidate.id, ...body }, (event, data) => {
        if (event === "step") setSteps((s) => [...s, String(data)]);
        else if (event === "result") {
          setResult(data as TurnResult);
          setAnswer("");
        } else if (event === "error") setError(data.detail);
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const groups = (tracks ?? []).reduce<Record<string, Track[]>>((acc, t) => {
    (acc[t.group] ??= []).push(t);
    return acc;
  }, {});
  const session = result?.session;
  const asked = session ? Math.min(session.history.length + (session.current ? 1 : 0), TOTAL) : 0;

  if (candidateLoading)
    return (
      <>
        <PageHeader eyebrow="Mock interview" title="Rehearse an interview in your field" lead="Five questions, each scored on a rubric." />
        <Loading label="Checking your profile…" />
      </>
    );

  if (!candidate)
    return (
      <>
        <PageHeader eyebrow="Mock interview" title="Rehearse an interview in your field" lead="Five questions, each scored on a rubric." />
        <NeedsCandidate />
      </>
    );

  return (
    <>
      <PageHeader
        eyebrow="Mock interview"
        title={session ? session.interview_type : "Rehearse an interview in your field"}
        lead="Five questions on a track from your field. A critic checks every question before you see it; each answer is scored on relevance, depth, structure and clarity."
      />
      <ErrorNote message={error} />

      {!session && !tracks && !error && <Loading label="Loading interview tracks…" />}

      {!session && tracks && (
        <section className="card" aria-label="Choose a track">
          {Object.entries(groups).map(([group, list]) => (
            <fieldset key={group} className="mb-6 last:mb-0">
              <legend className="eyebrow mb-3">{group}</legend>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {list.map((t) => {
                  const on = track === t.name;
                  return (
                    <button
                      key={t.name}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setTrack(t.name)}
                      className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition-colors ${
                        on ? "border-ink bg-surface" : "border-hair hover:border-line hover:bg-surface/50"
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${on ? "border-ink bg-ink text-bg" : "border-line"}`}
                      >
                        {on && <Check size={12} />}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold">{t.name}</span>
                        <span className="mt-0.5 block text-xs text-muted">{t.focus.charAt(0).toUpperCase() + t.focus.slice(1)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ))}
          <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-hair pt-5">
            <button
              type="button"
              className="btn-primary"
              disabled={!track || busy}
              onClick={() => {
                setStartedAt(Date.now());
                setNow(Date.now());
                turn({ track });
              }}
            >
              {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Mic size={16} aria-hidden />}
              Start mock interview{track ? `: ${track}` : ""}
            </button>
            <p className="text-xs text-muted">Answer in writing here; spoken answers are in the main app.</p>
          </div>
        </section>
      )}

      {session && (
        <section aria-label="Interview" className="space-y-4">
          <div className="card flex flex-wrap items-center justify-between gap-4 py-4">
            <ol className="flex items-center gap-1.5" aria-label={`Question ${asked} of ${TOTAL}`}>
              {Array.from({ length: TOTAL }, (_, i) => {
                const done = i < session.history.length;
                const now = !session.done && i === session.history.length;
                return (
                  <li
                    key={i}
                    aria-hidden
                    className={`h-2 w-10 rounded-full sm:w-14 ${done ? "bg-ink" : now ? "bg-ink/40" : "bg-hair"}`}
                  />
                );
              })}
            </ol>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted">
                Question {asked} of {TOTAL}
              </span>
              {startedAt && (
                <span className="flex items-center gap-1 font-mono text-xs text-muted" aria-hidden>
                  <Clock size={12} /> {elapsedLabel((now ?? startedAt) - startedAt)}
                </span>
              )}
              {result?.average != null && <Badge state="ok">Average {result.average}/5</Badge>}
            </div>
          </div>

          {session.history.map((h, i) => (
            <article key={i} className="card space-y-4">
              <p className="font-medium leading-relaxed">
                <span className="mr-2 font-mono text-xs text-muted">Q{i + 1}</span>
                {h.question}
              </p>
              <div className="rounded-2xl bg-surface px-4 py-3">
                <p className="eyebrow mb-1">Your answer</p>
                <p className="whitespace-pre-wrap text-sm">{h.answer}</p>
              </div>
              <Rubric evaluation={h.evaluation} />
              {h.evaluation.improvements.length > 0 && (
                <ul className="space-y-1 border-t border-hair pt-3 text-sm text-muted">
                  {h.evaluation.improvements.map((x) => (
                    <li key={x} className="flex gap-2">
                      <TrendingDown size={14} className="mt-1 shrink-0 rotate-180" aria-hidden /> {x}
                    </li>
                  ))}
                </ul>
              )}
              <details className="group text-sm">
                <summary className="cursor-pointer font-medium text-primary-ink">Compare with a model answer</summary>
                <p className="mt-2 rounded-2xl border border-hair px-4 py-3 text-muted">{h.evaluation.model_answer}</p>
              </details>
            </article>
          ))}

          {session.current && !session.done && (
            <article className="card border-ink/30 shadow-[0_12px_40px_-24px_rgb(var(--ink)/0.4)]">
              <p className="eyebrow">
                Question {session.history.length + 1}
                {session.current.is_followup && " · a follow-up on your last answer"}
              </p>
              <p className="mt-2 font-display text-xl font-medium leading-snug tracking-tight">{session.current.question}</p>
              <label className="label mt-5" htmlFor="answer">
                Your answer
              </label>
              <textarea
                id="answer"
                className="input min-h-40"
                maxLength={MAX_ANSWER}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                aria-describedby="answer-count"
                placeholder="Answer as you would aloud: what, how, and a result."
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button type="button" className="btn-primary" disabled={busy || !answer.trim()} onClick={() => turn({ session, answer })}>
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Send size={16} aria-hidden />}
                  Submit answer to question {session.history.length + 1}
                </button>
                <span id="answer-count" className="font-mono text-xs text-muted tabular-nums">
                  {answer.length} of {MAX_ANSWER} characters
                </span>
              </div>
            </article>
          )}

          {session.done && result?.summary && (
            <article className="card surface-light">
              <p className="eyebrow">Session summary</p>
              <h2 className="h2 mt-1">Well done, that is all five questions</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <p className="flex items-center gap-3 rounded-2xl border border-hair bg-bg px-4 py-3 text-sm">
                  <Award size={18} aria-hidden /> Strongest: <span className="font-semibold capitalize">{result.summary.strongest}</span>
                </p>
                <p className="flex items-center gap-3 rounded-2xl border border-hair bg-bg px-4 py-3 text-sm">
                  <TrendingDown size={18} aria-hidden /> Weakest: <span className="font-semibold capitalize">{result.summary.weakest}</span>
                </p>
              </div>
              <ul className="mt-4 space-y-2 text-sm">
                {Object.entries(result.summary.tips).map(([c, tip]) => (
                  <li key={c}>
                    <span className="font-semibold capitalize">{c}:</span> {tip}
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className="btn-primary mt-5"
                onClick={() => {
                  setResult(null);
                  setStartedAt(null);
                }}
              >
                Start a new mock interview
              </button>
            </article>
          )}
        </section>
      )}

      {/* Always mounted, so screen readers announce what is added: critic steps, then the next question. */}
      <div role="status" aria-live="polite" className="mt-4 text-sm text-muted">
        {(busy || steps.length > 0) && (
          <ol className="space-y-1.5 rounded-2xl border border-hair bg-bg px-4 py-3">
            {steps.map((s, i) => (
              <li key={i} className="flex items-center gap-2">
                <ShieldCheck size={14} className="text-ok" aria-hidden /> {s}
              </li>
            ))}
            {busy && (
              <li className="flex items-center gap-2">
                <ThinkingPulse /> Evaluating your answer…
              </li>
            )}
          </ol>
        )}
        {!busy && session?.current && !session.done && (
          <span className="sr-only">Question {Math.min(session.history.length + 1, TOTAL)} of {TOTAL} is ready.</span>
        )}
        {!busy && session?.done && <span className="sr-only">Interview finished. Your summary is below.</span>}
      </div>
      <div ref={bottom} />
    </>
  );
}
