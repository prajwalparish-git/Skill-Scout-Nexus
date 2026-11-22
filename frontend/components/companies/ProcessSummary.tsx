"use client";

// "Interview process (from N reports)": what approved reports say about a company's process.
import { ListOrdered, UserRound } from "lucide-react";
import { DIFFICULTY_LABELS, type ProcessSummary as Summary } from "@/lib/api";

function Spread({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {Object.entries(DIFFICULTY_LABELS).map(([k, v]) => (
        <span key={k} className="chip">
          {v} {Math.round(((counts[k] ?? 0) / total) * 100)}%
        </span>
      ))}
    </span>
  );
}

export function ProcessSummary({ summary }: { summary: Summary }) {
  if (!summary.reports) return null;
  return (
    <section className="card" aria-labelledby="process-title">
      <h3 id="process-title" className="flex items-center gap-2 font-semibold">
        <ListOrdered size={16} aria-hidden /> Interview process (from {summary.reports} report{summary.reports === 1 ? "" : "s"})
      </h3>
      <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted">Most common round order</dt>
          <dd className="font-medium">
            {summary.common_order?.join(" → ")}{" "}
            <span className="text-xs font-normal text-muted">
              ({summary.common_order_reports} of {summary.reports})
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Average number of rounds</dt>
          <dd className="font-medium">{summary.average_rounds}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted">Difficulty across all rounds</dt>
          <dd className="mt-1">{summary.difficulty && <Spread counts={summary.difficulty} />}</dd>
        </div>
        {summary.results && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-muted">Results reported</dt>
            <dd>
              {Object.entries(summary.results)
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")}
            </dd>
          </div>
        )}
      </dl>
      {summary.difficulty_by_round && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">Difficulty by round type</summary>
          <ul className="mt-2 space-y-1">
            {Object.entries(summary.difficulty_by_round).map(([type, counts]) => (
              <li key={type} className="flex flex-wrap items-center gap-2">
                <span className="w-32 font-medium">{type}</span> <Spread counts={counts} />
              </li>
            ))}
          </ul>
        </details>
      )}
      <ol className="mt-4 space-y-3">
        {summary.summaries?.map((s) => (
          <li key={s.id} className="rounded-xl border border-hair p-3 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <span className="chip border-warn/40 text-warn">
                <UserRound size={12} aria-hidden /> Reported by {s.label}
              </span>
              <span className="font-medium">{s.role}</span>
              <span className="text-xs text-muted">
                · {s.interview_month} · {s.result_label}
              </span>
            </p>
            <p className="mt-1 text-xs text-muted">
              {s.rounds.map((r) => `${r.label}${r.minutes ? ` (${r.minutes} min)` : ""}, ${DIFFICULTY_LABELS[r.difficulty].toLowerCase()}`).join(" → ")}
            </p>
            {s.summary && <p className="mt-2">{s.summary}</p>}
            {s.tip && <p className="mt-2 rounded-lg bg-surface px-3 py-2">Tip: {s.tip}</p>}
          </li>
        ))}
      </ol>
    </section>
  );
}
