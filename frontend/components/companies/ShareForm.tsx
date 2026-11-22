"use client";

import { useState } from "react";
import { Loader2, Plus, Send, Trash2 } from "lucide-react";
import { post, ROUNDS } from "@/lib/api";
import { ErrorNote } from "@/components/ui";

type Q = { text: string; mcq: boolean; options: string[]; correct: number | null; explanation: string };
const NEW_Q: Q = { text: "", mcq: false, options: ["", "", "", ""], correct: null, explanation: "" };
const LETTERS = "ABCD";
const thisMonth = () => new Date().toISOString().slice(0, 7);

/** Share an interview in your own words: cleaned of personal details on the server, then
 * waiting for a moderator. The poster is only ever shown as a label, never by name. */
export function ShareForm({ inOrg, onShared }: { inOrg: boolean; onShared: () => void }) {
  const [form, setForm] = useState({ company: "", role: "", round: "technical", month: thisMonth(), tip: "", showCollege: true });
  const [questions, setQuestions] = useState<Q[]>([{ ...NEW_Q, options: ["", "", "", ""] }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const setQ = (i: number, patch: Partial<Q>) => setQuestions((l) => l.map((q, k) => (k === i ? { ...q, ...patch } : q)));

  async function share(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const r = await post<{ id: number; status: string; removed: string[] }>("/api/experiences", {
        company: form.company,
        role: form.role,
        round: form.round,
        interview_month: form.month,
        tip: form.tip,
        show_college: inOrg && form.showCollege,
        questions: questions
          .filter((q) => q.text.trim())
          .map((q) =>
            q.mcq
              ? { kind: "mcq", text: q.text, options: q.options, correct_index: q.correct, explanation: q.explanation }
              : { kind: "open", text: q.text, explanation: q.explanation },
          ),
      });
      setDone(
        `Thanks! Your post is waiting for a moderator's approval.${r.removed.length ? ` Removed automatically: ${r.removed.join(", ")}.` : ""}`,
      );
      setQuestions([{ ...NEW_Q, options: ["", "", "", ""] }]);
      setForm((f) => ({ ...f, tip: "" }));
      onShared();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card space-y-4" aria-labelledby="share-title" onSubmit={share}>
      <h2 id="share-title" className="font-semibold">
        Share your interview
      </h2>
      <p className="text-sm text-muted">
        Write the questions in your own words, as you remember them. Do not paste from websites, and leave out names and contact details
        (they are removed anyway). You are shown only as &quot;a student&quot; with your batch year
        {inOrg ? ", and your college once enough of your batch have shared" : ""}.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">
          Company
          <input className="input mt-1 font-normal" required maxLength={150} placeholder="e.g. TCS, Infosys, Zoho" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
        </label>
        <label className="text-sm font-medium">
          Role
          <input className="input mt-1 font-normal" required maxLength={150} placeholder="e.g. Systems Engineer" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
        </label>
        <label className="text-sm font-medium">
          Round
          <select className="input mt-1 font-normal" value={form.round} onChange={(e) => setForm({ ...form, round: e.target.value })}>
            {Object.entries(ROUNDS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Month of the interview
          <input className="input mt-1 font-normal" type="month" required max={thisMonth()} value={form.month} onChange={(e) => setForm({ ...form, month: e.target.value })} />
        </label>
      </div>
      <ol className="space-y-3">
        {questions.map((q, i) => (
          <li key={i} className="space-y-2 rounded-xl border border-hair p-3">
            <label className="text-sm font-medium">
              Question {i + 1}
              <textarea className="input mt-1 min-h-16 font-normal" maxLength={1200} value={q.text} onChange={(e) => setQ(i, { text: e.target.value })} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={q.mcq} onChange={(e) => setQ(i, { mcq: e.target.checked })} /> It was multiple choice
            </label>
            {q.mcq && (
              <fieldset className="grid gap-2 sm:grid-cols-2">
                <legend className="sr-only">Options for question {i + 1}</legend>
                {q.options.map((o, j) => (
                  <label key={j} className="flex items-center gap-2 text-sm">
                    <input type="radio" name={`correct-${i}`} checked={q.correct === j} onChange={() => setQ(i, { correct: j })} aria-label={`Option ${LETTERS[j]} is correct`} />
                    <span className="font-mono text-xs text-muted">{LETTERS[j]}</span>
                    <input className="input py-1.5" maxLength={300} value={o} onChange={(e) => setQ(i, { options: q.options.map((x, k) => (k === j ? e.target.value : x)) })} placeholder={`Option ${LETTERS[j]}`} />
                  </label>
                ))}
                <p className="text-xs text-muted sm:col-span-2">Tick the correct option.</p>
              </fieldset>
            )}
            {questions.length > 1 && (
              <button type="button" className="btn-ghost min-h-0 px-3 py-1 text-xs" onClick={() => setQuestions((l) => l.filter((_, k) => k !== i))}>
                <Trash2 size={14} aria-hidden /> Remove question {i + 1}
              </button>
            )}
          </li>
        ))}
      </ol>
      <button type="button" className="btn-ghost" disabled={questions.length >= 20} onClick={() => setQuestions((l) => [...l, { ...NEW_Q, options: ["", "", "", ""] }])}>
        <Plus size={16} aria-hidden /> Add a question
      </button>
      <label className="block text-sm font-medium">
        A tip for juniors (optional)
        <textarea className="input mt-1 min-h-16 font-normal" maxLength={800} value={form.tip} onChange={(e) => setForm({ ...form, tip: e.target.value })} />
      </label>
      {inOrg && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.showCollege} onChange={(e) => setForm({ ...form, showCollege: e.target.checked })} /> Show my college with my batch year
        </label>
      )}
      <ErrorNote message={error} />
      {done && (
        <p role="status" className="text-sm text-ok">
          {done}
        </p>
      )}
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Send size={16} aria-hidden />} Share my interview
      </button>
    </form>
  );
}
