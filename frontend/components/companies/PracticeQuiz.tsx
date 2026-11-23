"use client";

import { useState } from "react";
import { BookOpen, Bot, Check, Loader2, UserRound, X } from "lucide-react";
import { post, ROUNDS, type PracticeQuiz as Quiz, type PracticeResult } from "@/lib/api";
import { ErrorNote } from "@/components/ui";

const LETTERS = "ABCD";

/** The source of practice questions, always visible: reported by students, general practice from
 * the open question bank (never claimed as the company's), or AI practice. */
export function SourceBadge({ source }: { source: "reported" | "ai" | "open" }) {
  if (source === "open")
    return (
      <span className="chip border-ok/40 text-ok">
        <BookOpen size={12} aria-hidden /> General practice (open question bank)
      </span>
    );
  return source === "ai" ? (
    <span className="chip border-primary/40 text-primary-ink">
      <Bot size={12} aria-hidden /> AI practice, not reported by a student
    </span>
  ) : (
    <span className="chip border-warn/40 text-warn">
      <UserRound size={12} aria-hidden /> Reported by students
    </span>
  );
}

/** A company practice quiz, taken and graded inline. Its score stays apart from the student's
 * topic levels and weekly plan. */
export function PracticeQuiz({ slug, quiz, onClose }: { slug: string; quiz: Quiz; onClose: () => void }) {
  const [answers, setAnswers] = useState<(number | null)[]>(quiz.questions.map(() => null));
  const [result, setResult] = useState<PracticeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await post<PracticeResult>(`/api/companies/${slug}/practice/submit`, {
          round: quiz.round,
          source: quiz.source,
          answers: quiz.questions.map((q, i) => ({ id: q.id, choice: answers[i] })),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-4" aria-label={`${quiz.company} practice`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          {quiz.company} · {ROUNDS[quiz.round] ?? quiz.round}
        </h2>
        <SourceBadge source={quiz.source} />
      </div>
      {quiz.notes.map((n) => (
        <p key={n} className="text-xs text-muted">
          {n}
        </p>
      ))}
      {result && (
        <p role="status" className="rounded-xl bg-surface px-4 py-3 text-sm">
          <span className="font-semibold">
            {result.correct} of {result.total} right ({result.score_pct}%).
          </span>{" "}
          Company practice is kept apart: it does not change your topic levels or weekly plan.
        </p>
      )}
      <ol className="space-y-3">
        {quiz.questions.map((q, i) => {
          const r = result?.review[i];
          return (
            <li key={q.id} className="rounded-xl border border-hair p-4">
              <fieldset>
                <legend className="font-medium">
                  {i + 1}. {q.text}
                </legend>
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {q.options.map((o, j) => {
                    const right = r && j === r.correct_index;
                    const wrong = r && answers[i] === j && !r.is_correct;
                    return (
                      <label
                        key={j}
                        className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                          right ? "border-ok bg-ok/[0.06]" : wrong ? "border-bad bg-bad/[0.05]" : answers[i] === j ? "border-ink" : "border-hair"
                        }`}
                      >
                        <input
                          type="radio"
                          name={q.id}
                          className="accent-[rgb(var(--ink))]"
                          checked={answers[i] === j}
                          disabled={!!result}
                          onChange={() => setAnswers((a) => a.map((x, k) => (k === i ? j : x)))}
                        />
                        <span className="font-mono text-xs text-muted">{LETTERS[j]}</span> {o}
                        {right && <Check size={14} className="ml-auto text-ok" aria-label="correct answer" />}
                        {wrong && <X size={14} className="ml-auto text-bad" aria-label="your answer" />}
                      </label>
                    );
                  })}
                </div>
                {r && <p className="mt-2 text-xs text-muted">{r.explanation}</p>}
                {r?.credit && <p className="mt-1 text-[11px] text-muted">Source: {r.credit}</p>}
              </fieldset>
            </li>
          );
        })}
      </ol>
      <ErrorNote message={error} />
      <div className="flex flex-wrap gap-2">
        {!result && (
          <button type="button" className="btn-primary" disabled={busy} onClick={submit}>
            {busy && <Loader2 size={16} className="animate-spin" aria-hidden />} Submit answers
          </button>
        )}
        <button type="button" className="btn-ghost" onClick={onClose}>
          Back to the company
        </button>
      </div>
    </section>
  );
}
