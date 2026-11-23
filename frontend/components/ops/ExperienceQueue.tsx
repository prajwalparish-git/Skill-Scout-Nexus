"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Flag, MessagesSquare, X } from "lucide-react";
import { get, post, ROUNDS, type ModerationPost } from "@/lib/api";

const LETTERS = "ABCD";

/** Interview posts from individual learners (no organization), for the operations view to
 * approve or reject. Organizations moderate their own students' posts in their admin portal. */
export function ExperienceQueue() {
  const [posts, setPosts] = useState<ModerationPost[] | null>(null);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [companies, setCompanies] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [processingId, setProcessingId] = useState<number | null>(null);

  const load = useCallback(() => {
    get<{ posts: ModerationPost[] }>("/api/ops/experiences").then(
      (r) => setPosts(r.posts),
      (e: Error) => setError(e.message),
    );
  }, []);
  useEffect(load, [load]);

  async function review(p: ModerationPost, approve: boolean) {
    if (processingId !== null) return;
    setProcessingId(p.id);
    setError(null);
    try {
      const company = companies[p.id];
      const r = await post<{ posts: ModerationPost[] }>(`/api/ops/experiences/${p.id}/review`, {
        approve,
        reason: reasons[p.id] ?? "",
        company: company && company !== p.company ? company : "",
      });
      setPosts(r.posts);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProcessingId(null);
    }
  }

  return (
    <section className="card" aria-labelledby="ops-posts-title">
      <h2 id="ops-posts-title" className="flex items-center gap-2 text-sm font-semibold">
        <MessagesSquare size={15} aria-hidden /> Interview posts to review ({posts?.length ?? "…"})
      </h2>
      <p className="mt-1 text-xs text-muted">
        From individual learners only; organizations review their own students&apos; posts. Nothing is shown to students until approved.
      </p>
      {error && <p className="mt-2 text-xs text-bad">{error}</p>}
      {posts?.length === 0 && <p className="mt-3 text-sm text-muted">Nothing waiting.</p>}
      <ul className="mt-3 space-y-3">
        {posts?.map((p) => (
          <li key={p.id} className="rounded-xl border border-hair p-3 text-sm">
            <p>
              <span className="font-semibold">{p.company}</span>
              {!p.known_company && <span className="ml-1 text-xs text-warn">(new company)</span>} · {p.role} · {ROUNDS[p.round]} ·{" "}
              {p.interview_month} · shown as <em>{p.label}</em>
              {p.status === "hidden" && <span className="ml-1 text-xs text-warn">hidden after reports</span>}
            </p>
            {p.flags.map((f) => (
              <p key={f} className="mt-1 flex items-start gap-1 text-xs text-warn">
                <Flag size={12} className="mt-0.5 shrink-0" aria-hidden /> {f}
              </p>
            ))}
            <ol className="mt-2 list-decimal space-y-1 pl-5">
              {p.questions.map((q, i) => (
                <li key={i}>
                  {q.text}
                  {q.kind === "mcq" && (
                    <span className="block text-xs text-muted">
                      {q.options?.map((o, j) => `${LETTERS[j]}. ${o}${j === q.correct_index ? " ✓" : ""}`).join(" · ")}
                    </span>
                  )}
                </li>
              ))}
            </ol>
            {p.process && (
              <div className="mt-2 rounded-lg border border-hair px-3 py-2 text-xs">
                <p className="font-medium">
                  Interview process · {p.process.result_label}
                </p>
                <p className="text-muted">
                  {p.process.rounds.map((r) => `${r.label}${r.minutes ? ` (${r.minutes} min)` : ""}, ${r.difficulty}`).join(" → ")}
                </p>
                {p.process.summary && <p className="mt-1">{p.process.summary}</p>}
              </div>
            )}
            {p.tip && <p className="mt-1 text-xs text-muted">Tip: {p.tip}</p>}
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <input
                className="input py-1.5 text-xs"
                aria-label="Company name"
                defaultValue={p.company}
                onChange={(e) => setCompanies((c) => ({ ...c, [p.id]: e.target.value }))}
              />
              <input
                className="input py-1.5 text-xs"
                aria-label="Reason (needed to reject)"
                placeholder="Reason (needed to reject; the student sees it)"
                onChange={(e) => setReasons((r) => ({ ...r, [p.id]: e.target.value }))}
              />
            </div>
            <div className="mt-2 flex gap-2">
              <button type="button" className="btn-ink min-h-0 px-3 py-1 text-xs" disabled={processingId !== null} onClick={() => review(p, true)}>
                <Check size={14} aria-hidden /> Approve
              </button>
              <button type="button" className="btn-ghost min-h-0 px-3 py-1 text-xs" disabled={processingId !== null} onClick={() => review(p, false)}>
                <X size={14} aria-hidden /> Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
