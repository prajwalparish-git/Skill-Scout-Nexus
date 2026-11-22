"use client";

// "Interviewed at <Company>? Share your experience": the company page's own share panel. The
// company is fixed to the page's; section 1 adds questions, section 2 the interview process.
// It goes through the same cleaning, limits and moderation as every post.
import { useState } from "react";
import { ArrowDown, ArrowUp, Lock, Loader2, Plus, Send, Trash2 } from "lucide-react";
import { DIFFICULTY_LABELS, post, PROCESS_RESULTS, PROCESS_ROUND_TYPES, ROUNDS, type ProcessRound } from "@/lib/api";
import { ErrorNote } from "@/components/ui";
import { newQuestion, QuestionList, questionsPayload, sharedMessage, thisMonth, type Q, type Shared } from "./ShareForm";

const MAX_ROUNDS = 8;
const newRound = (): ProcessRound => ({ type: "technical", minutes: null, difficulty: "medium" });

export function SharePanel({ company, inOrg, onShared }: { company: string; inOrg: boolean; onShared: () => void }) {
  const [meta, setMeta] = useState({ role: "", month: thisMonth(), tip: "", showCollege: true });
  const [round, setRound] = useState("technical");
  const [questions, setQuestions] = useState<Q[]>([newQuestion()]);
  const [withProcess, setWithProcess] = useState(false);
  const [rounds, setRounds] = useState<ProcessRound[]>([{ type: "online_test", minutes: null, difficulty: "medium" }, newRound()]);
  const [result, setResult] = useState("waiting");
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const setR = (i: number, patch: Partial<ProcessRound>) => setRounds((l) => l.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const move = (i: number, by: number) =>
    setRounds((l) => {
      const out = [...l];
      [out[i], out[i + by]] = [out[i + by], out[i]];
      return out;
    });

  async function share(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(null);
    const qs = questionsPayload(questions);
    if (!qs.length && !withProcess) {
      setError("Add a question you were asked, or your interview process (or both).");
      return;
    }
    setBusy(true);
    try {
      const r = await post<Shared>("/api/experiences", {
        company,
        role: meta.role,
        round: qs.length ? round : "",
        interview_month: meta.month,
        tip: meta.tip,
        show_college: inOrg && meta.showCollege,
        questions: qs,
        process: withProcess ? { rounds, result, summary } : null,
      });
      setDone(sharedMessage(r));
      setQuestions([newQuestion()]);
      setSummary("");
      setMeta((m) => ({ ...m, tip: "" }));
      onShared();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card space-y-5" aria-labelledby="panel-title" onSubmit={share}>
      <div>
        <h2 id="panel-title" className="font-semibold">
          Interviewed at {company}? Share your experience
        </h2>
        <p className="mt-1 text-xs text-muted">
          In your own words; names and contact details are removed. A moderator approves it before anyone sees it, and you are shown only
          as &quot;a student&quot; with your batch year{inOrg ? " (and your college once enough of your batch have shared)" : ""}.
        </p>
      </div>
      <div className="text-sm font-medium">
        Company
        <p className="input mt-1 flex items-center gap-2 bg-surface font-normal text-muted" aria-label={`Company: ${company} (fixed to this page)`}>
          <Lock size={14} aria-hidden /> {company}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <label className="text-sm font-medium">
          Role
          <input className="input mt-1 font-normal" required maxLength={150} placeholder="e.g. Systems Engineer" value={meta.role} onChange={(e) => setMeta({ ...meta, role: e.target.value })} />
        </label>
        <label className="text-sm font-medium">
          Interview month
          <input className="input mt-1 font-normal" type="month" required max={thisMonth()} value={meta.month} onChange={(e) => setMeta({ ...meta, month: e.target.value })} />
        </label>
      </div>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold">1. Add a question</legend>
        <label className="block text-sm font-medium">
          Round
          <select className="input mt-1 font-normal" value={round} onChange={(e) => setRound(e.target.value)}>
            {Object.entries(ROUNDS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <QuestionList questions={questions} setQuestions={setQuestions} idPrefix="panel" />
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold">2. Your interview process</legend>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={withProcess} onChange={(e) => setWithProcess(e.target.checked)} /> Add how the interview went
        </label>
        {withProcess && (
          <>
            <ol className="space-y-2" aria-label="Rounds in order">
              {rounds.map((r, i) => (
                <li key={i} className="rounded-xl border border-hair p-2">
                  <p className="text-xs font-medium text-muted">Round {i + 1}</p>
                  <div className="mt-1 grid grid-cols-[1fr_5rem] gap-2">
                    <select className="input py-1.5" aria-label={`Round ${i + 1} type`} value={r.type} onChange={(e) => setR(i, { type: e.target.value })}>
                      {Object.entries(PROCESS_ROUND_TYPES).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <input
                      className="input py-1.5"
                      type="number"
                      min={5}
                      max={480}
                      placeholder="min"
                      aria-label={`Round ${i + 1} length in minutes (optional)`}
                      value={r.minutes ?? ""}
                      onChange={(e) => setR(i, { minutes: e.target.value ? Number(e.target.value) : null })}
                    />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    <div className="segmented" role="group" aria-label={`Round ${i + 1} difficulty`}>
                      {Object.entries(DIFFICULTY_LABELS).map(([k, v]) => (
                        <button key={k} type="button" className="segment" aria-pressed={r.difficulty === k} onClick={() => setR(i, { difficulty: k })}>
                          {v}
                        </button>
                      ))}
                    </div>
                    <span className="ml-auto flex gap-1">
                      <button type="button" className="btn-ghost min-h-0 px-2 py-1" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move round ${i + 1} up`}>
                        <ArrowUp size={14} aria-hidden />
                      </button>
                      <button type="button" className="btn-ghost min-h-0 px-2 py-1" disabled={i === rounds.length - 1} onClick={() => move(i, 1)} aria-label={`Move round ${i + 1} down`}>
                        <ArrowDown size={14} aria-hidden />
                      </button>
                      <button
                        type="button"
                        className="btn-ghost min-h-0 px-2 py-1"
                        disabled={rounds.length === 1}
                        onClick={() => setRounds((l) => l.filter((_, k) => k !== i))}
                        aria-label={`Remove round ${i + 1}`}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </span>
                  </div>
                </li>
              ))}
            </ol>
            <button type="button" className="btn-ghost" disabled={rounds.length >= MAX_ROUNDS} onClick={() => setRounds((l) => [...l, newRound()])}>
              <Plus size={16} aria-hidden /> Add a round
            </button>
            <label className="block text-sm font-medium">
              Result
              <select className="input mt-1 font-normal" value={result} onChange={(e) => setResult(e.target.value)}>
                {Object.entries(PROCESS_RESULTS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium">
              A short summary
              <textarea className="input mt-1 min-h-16 font-normal" maxLength={600} placeholder="How it went, what each round covered" value={summary} onChange={(e) => setSummary(e.target.value)} />
            </label>
          </>
        )}
      </fieldset>

      <label className="block text-sm font-medium">
        A tip for juniors (optional)
        <textarea className="input mt-1 min-h-12 font-normal" maxLength={800} value={meta.tip} onChange={(e) => setMeta({ ...meta, tip: e.target.value })} />
      </label>
      {inOrg && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={meta.showCollege} onChange={(e) => setMeta({ ...meta, showCollege: e.target.checked })} /> Show my college with my batch year
        </label>
      )}
      <ErrorNote message={error} />
      {done && (
        <p role="status" className="text-sm text-ok">
          {done}
        </p>
      )}
      <button type="submit" className="btn-primary w-full" disabled={busy}>
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Send size={16} aria-hidden />} Share
      </button>
    </form>
  );
}
