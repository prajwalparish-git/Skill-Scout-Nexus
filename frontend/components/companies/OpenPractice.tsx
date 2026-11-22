"use client";

// "Practice by round" from the open question bank, on every company page. Always labelled
// general practice: these are never presented as questions the company asked.
import Link from "next/link";
import { BookOpen, ExternalLink, ListChecks, Loader2, MessagesSquare } from "lucide-react";
import type { OpenPractice as Practice, TestPattern } from "@/lib/api";

export function OpenPractice({
  slug,
  practice,
  busy,
  onQuiz,
}: {
  slug: string;
  practice: Practice;
  busy: string | null;
  onQuiz: (round: "aptitude" | "technical") => void;
}) {
  const r = practice.rounds;
  return (
    <section className="card" aria-labelledby="open-practice-title">
      <p className="chip border-ok/40 text-ok">
        <BookOpen size={12} aria-hidden /> {practice.label}
      </p>
      <h3 id="open-practice-title" className="mt-3 font-semibold">
        Practice by round
      </h3>
      <p className="mt-1 text-sm text-muted">{practice.note}</p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-3">
        <li className="rounded-xl border border-hair p-3">
          <p className="text-sm font-semibold">Aptitude</p>
          <p className="text-xs text-muted">{r.aptitude.toLocaleString()} questions with worked answers</p>
          <button type="button" className="btn-primary mt-3 w-full" disabled={!r.aptitude || busy !== null} onClick={() => onQuiz("aptitude")}>
            {busy === "open-aptitude" ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <ListChecks size={16} aria-hidden />} Quiz
          </button>
        </li>
        <li className="rounded-xl border border-hair p-3">
          <p className="text-sm font-semibold">Technical</p>
          <p className="text-xs text-muted">{r.technical.toLocaleString()} questions on your topics</p>
          <button type="button" className="btn-primary mt-3 w-full" disabled={!r.technical || busy !== null} onClick={() => onQuiz("technical")}>
            {busy === "open-technical" ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <ListChecks size={16} aria-hidden />} Quiz
          </button>
          {practice.technical_interview > 0 && (
            <Link href={`/interview?company=${slug}&round=technical&open=1`} className="btn-ghost mt-2 w-full">
              <MessagesSquare size={16} aria-hidden /> Mock interview
            </Link>
          )}
        </li>
        <li className="rounded-xl border border-hair p-3">
          <p className="text-sm font-semibold">HR</p>
          <p className="text-xs text-muted">{r.hr} common questions with model answers</p>
          <Link href={`/interview?company=${slug}&round=hr&open=1`} className="btn-primary mt-3 w-full">
            <MessagesSquare size={16} aria-hidden /> Mock interview
          </Link>
        </li>
      </ul>
      {practice.hr_questions.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium">Common HR questions with model answers</summary>
          <ol className="mt-3 space-y-3">
            {practice.hr_questions.map((q, i) => (
              <li key={q.text}>
                <p className="font-medium">
                  {i + 1}. {q.text}
                </p>
                <p className="mt-1 text-muted">{q.model_answer}</p>
                {q.credit && <p className="mt-0.5 text-[11px] text-muted">Question: {q.credit}. Model answer: our own.</p>}
              </li>
            ))}
          </ol>
        </details>
      )}
      <p className="mt-4 text-xs text-muted">
        From openly licensed sources.{" "}
        <Link href="/credits" className="underline underline-offset-2">
          Question sources &amp; credits
        </Link>
      </p>
    </section>
  );
}

/** A company's test pattern, only when taken from its own official page (linked). */
export function OfficialPattern({ pattern }: { pattern: TestPattern }) {
  return (
    <section className="card" aria-labelledby="pattern-title">
      <h3 id="pattern-title" className="font-semibold">
        Test pattern (from the company&apos;s official page)
      </h3>
      <ul className="mt-2 list-disc pl-5 text-sm">
        {pattern.sections.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
      <a href={pattern.source_url} target="_blank" rel="noopener noreferrer" className="btn-ghost mt-3 text-xs">
        Official source <ExternalLink size={14} aria-hidden />
      </a>
      {pattern.checked && <p className="mt-1 text-xs text-muted">Checked {pattern.checked}. Patterns change: confirm on the official page.</p>}
    </section>
  );
}
