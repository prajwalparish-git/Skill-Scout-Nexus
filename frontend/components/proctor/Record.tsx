"use client";

// The student's own proctoring record: every attempt with its events, split into clear-cut
// strikes and notes for review, the same as their organization's admin sees.

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { get, type ProctorAttempt } from "@/lib/api";
import { Badge, ErrorNote } from "@/components/ui";

const minutes = (s: number) => (s < 60 ? `${Math.round(s)}s` : `${Math.round(s / 60)} min`);
const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function ProctorRecord() {
  const [items, setItems] = useState<ProctorAttempt[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    get<ProctorAttempt[]>("/api/proctor/attempts").then(setItems, (e: Error) => setError(e.message));
  }, []);
  if (items && !items.length && !error) return null; // nothing proctored yet: no card
  return (
    <section id="proctoring" className="card" aria-labelledby="proctor-title">
      <h2 id="proctor-title" className="flex items-center gap-2 font-semibold">
        <ShieldCheck size={16} aria-hidden /> Your proctoring record
      </h2>
      <p className="mt-1 text-xs text-muted">
        What was recorded during your proctored tests: events and times only, never video or images. Your organization&apos;s admin sees the same.
        &ldquo;For review&rdquo; notes never count against you on their own.
      </p>
      {!items && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}
      <ul className="mt-4 grid gap-3">
        {items?.map((a) => (
          <li key={a.id} className="rounded-2xl border border-hair p-4">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">
                {a.kind === "quiz" ? "Quiz" : "Interview"}: {a.label}
              </p>
              <span className="text-xs text-muted">
                {when(a.started)} · {minutes(a.duration_s)} · {a.mode === "practice" ? "practice" : a.mode === "seb" ? "Safe Exam Browser" : "required"}
              </span>
              {a.breached ? <Badge state="bad">Submitted after {a.strikes} strikes</Badge> : <Badge state={a.strikes ? "warn" : "ok"}>{a.strikes} strike{a.strikes === 1 ? "" : "s"}</Badge>}
              {a.camera === "unavailable" && <Badge state="info">Camera checks skipped</Badge>}
            </div>
            {a.clear.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted">Clear-cut (strikes)</p>
                <ul className="mt-1 space-y-1 text-sm">
                  {a.clear.map((e, i) => (
                    <li key={i}>
                      {e.text}
                      {!e.strike && <span className="text-muted"> (same incident, not another strike)</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {a.review.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted">For review (never a strike)</p>
                <ul className="mt-1 space-y-1 text-sm text-muted">
                  {a.review.map((e, i) => (
                    <li key={i}>{e.text}</li>
                  ))}
                </ul>
              </div>
            )}
            {!a.clear.length && !a.review.length && <p className="mt-2 text-sm text-muted">Nothing was recorded.</p>}
          </li>
        ))}
      </ul>
      <ErrorNote message={error} />
    </section>
  );
}
