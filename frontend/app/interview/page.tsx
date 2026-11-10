"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Send, ShieldCheck } from "lucide-react";
import { get, postStream, type Track, type TurnResult } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { Badge, ErrorNote, NeedsCandidate, PageHeader } from "@/components/ui";

const CRITERIA = ["relevance", "depth", "structure", "clarity"] as const;
const MAX_ANSWER = 3000;

export default function InterviewPage() {
  const { candidate } = useCandidate();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [track, setTrack] = useState("");
  const [result, setResult] = useState<TurnResult | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setResult(null);
    setTracks([]);
    setError(null);
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

  const groups = tracks.reduce<Record<string, Track[]>>((acc, t) => {
    (acc[t.group] ??= []).push(t);
    return acc;
  }, {});
  const session = result?.session;
  const focus = tracks.find((t) => t.name === track)?.focus;

  if (!candidate)
    return (
      <>
        <PageHeader title="Mock interview" lead="Rehearse an interview in your field." />
        <NeedsCandidate />
      </>
    );

  return (
    <>
      <PageHeader
        title="Mock interview"
        lead="Five questions on a track from your field. Each question is checked by a critic before you see it; each answer is scored on relevance, depth, structure and clarity."
      />

      {!session && (
        <section className="card" aria-label="Choose a track">
          {Object.entries(groups).map(([group, list]) => (
            <fieldset key={group} className="mb-4">
              <legend className="mb-2 text-sm font-semibold">{group}</legend>
              <div className="flex flex-wrap gap-2">
                {list.map((t) => (
                  <button
                    key={t.name}
                    type="button"
                    aria-pressed={track === t.name}
                    onClick={() => setTrack(t.name)}
                    className={`rounded-full border px-3 py-1.5 text-sm ${
                      track === t.name ? "border-primary bg-primary text-white" : "border-line hover:bg-surface"
                    }`}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            </fieldset>
          ))}
          {focus && <p className="mb-4 text-sm text-muted">Covers {focus}.</p>}
          <button type="button" className="btn-primary" disabled={!track || busy} onClick={() => turn({ track })}>
            {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Mic size={16} aria-hidden />}
            Start interview
          </button>
        </section>
      )}

      {session && (
        <section aria-label="Interview" className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">{session.interview_type}</h2>
            <Badge state="info">
              Question {Math.min(session.history.length + (session.current ? 1 : 0), 5)} of 5
            </Badge>
            {result?.average != null && <Badge state="ok">Average {result.average}/5</Badge>}
          </div>

          {session.history.map((h, i) => (
            <article key={i} className="card space-y-3">
              <p className="font-medium">
                <span className="mr-2 text-muted">Q{i + 1}.</span>
                {h.question}
              </p>
              <p className="whitespace-pre-wrap rounded-lg bg-surface px-3 py-2 text-sm">{h.answer}</p>
              <div className="flex flex-wrap gap-2">
                {CRITERIA.map((c) => (
                  <span key={c} className="chip border-line text-ink">
                    {c} {h.evaluation[c]}/5
                  </span>
                ))}
              </div>
              {h.evaluation.improvements.length > 0 && (
                <ul className="list-disc pl-5 text-sm text-muted">
                  {h.evaluation.improvements.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              )}
              <details className="text-sm">
                <summary className="cursor-pointer text-primary-ink">Model answer</summary>
                <p className="mt-2 text-muted">{h.evaluation.model_answer}</p>
              </details>
            </article>
          ))}

          {session.current && !session.done && (
            <article className="card border-primary/50">
              <p className="font-medium">
                <span className="mr-2 text-muted">Q{session.history.length + 1}.</span>
                {session.current.question}
              </p>
              {session.current.is_followup && <p className="mt-1 text-xs text-muted">A follow-up on your last answer.</p>}
              <label className="label mt-4" htmlFor="answer">Your answer</label>
              <textarea
                id="answer"
                className="input min-h-32"
                maxLength={MAX_ANSWER}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Answer as you would aloud: what, how, and a result."
              />
              <div className="mt-3 flex items-center gap-3">
                <button type="button" className="btn-primary" disabled={busy || !answer.trim()} onClick={() => turn({ session, answer })}>
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Send size={16} aria-hidden />}
                  Send answer
                </button>
                <span className="text-xs text-muted tabular-nums">{answer.length}/{MAX_ANSWER}</span>
              </div>
            </article>
          )}

          {session.done && result?.summary && (
            <article className="card">
              <h3 className="font-semibold">Session summary</h3>
              <p className="mt-1 text-sm text-muted">
                Strongest: <span className="text-ink">{result.summary.strongest}</span> · Weakest:{" "}
                <span className="text-ink">{result.summary.weakest}</span>
              </p>
              <ul className="mt-3 space-y-1 text-sm">
                {Object.entries(result.summary.tips).map(([c, tip]) => (
                  <li key={c}>
                    <span className="font-medium capitalize">{c}:</span> {tip}
                  </li>
                ))}
              </ul>
              <button type="button" className="btn-ghost mt-4" onClick={() => setResult(null)}>
                New interview
              </button>
            </article>
          )}
        </section>
      )}

      {(busy || steps.length > 0) && (
        <ol aria-live="polite" className="mt-4 space-y-1 text-sm text-muted">
          {steps.map((s, i) => (
            <li key={i} className="flex items-center gap-2">
              <ShieldCheck size={14} aria-hidden /> {s}
            </li>
          ))}
          {busy && (
            <li className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" aria-hidden /> Working…
            </li>
          )}
        </ol>
      )}
      <ErrorNote message={error} />
      <div ref={bottom} />
    </>
  );
}
