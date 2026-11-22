"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Flag, HandHeart, X } from "lucide-react";
import { get, post, type Contribution } from "@/lib/api";

const LETTERS = "ABCD";

/** Questions contributed by contributors and individual learners (CC BY 4.0), for the operations
 * view to approve or reject. Organizations review their own students' contributions. */
export function ContributionQueue() {
  const [items, setItems] = useState<Contribution[] | null>(null);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    get<{ contributions: Contribution[] }>("/api/ops/contributions").then(
      (r) => setItems(r.contributions),
      (e: Error) => setError(e.message),
    );
  }, []);
  useEffect(load, [load]);

  async function review(c: Contribution, approve: boolean) {
    setError(null);
    try {
      const r = await post<{ contributions: Contribution[] }>(`/api/ops/contributions/${c.id}/review`, { approve, reason: reasons[c.id] ?? "" });
      setItems(r.contributions);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card" aria-labelledby="ops-contrib-title">
      <h2 id="ops-contrib-title" className="flex items-center gap-2 text-sm font-semibold">
        <HandHeart size={15} aria-hidden /> Contributed questions to review ({items?.length ?? "…"})
      </h2>
      <p className="mt-1 text-xs text-muted">
        Published under CC BY 4.0 once approved: multiple choice joins the quiz bank, open questions the general-practice interviews. Check the
        answer, the explanation, and that it is the author&apos;s own words.
      </p>
      {error && <p className="mt-2 text-xs text-bad">{error}</p>}
      {items?.length === 0 && <p className="mt-3 text-sm text-muted">Nothing waiting.</p>}
      <ul className="mt-3 space-y-3">
        {items?.map((c) => (
          <li key={c.id} className="rounded-xl border border-hair p-3 text-sm">
            <p className="text-xs text-muted">
              {c.round} · {c.topic} · {c.difficulty} · {c.kind === "mcq" ? "multiple choice" : "open"} · {c.licence}
            </p>
            {c.flags?.map((f) => (
              <p key={f} className="mt-1 flex items-start gap-1 text-xs text-warn">
                <Flag size={12} className="mt-0.5 shrink-0" aria-hidden /> {f}
              </p>
            ))}
            <p className="mt-2 font-medium">{c.text}</p>
            {c.kind === "mcq" ? (
              <>
                <p className="mt-1 text-xs text-muted">{c.options.map((o, j) => `${LETTERS[j]}. ${o}${j === c.correct_index ? " ✓" : ""}`).join(" · ")}</p>
                <p className="mt-1 text-xs">Explanation: {c.explanation}</p>
              </>
            ) : (
              <p className="mt-1 text-xs">Model answer: {c.model_answer}</p>
            )}
            <input
              className="input mt-3 py-1.5 text-xs"
              aria-label="Reason (shown to the author when rejected)"
              placeholder="Reason (required to reject)"
              value={reasons[c.id] ?? ""}
              onChange={(e) => setReasons({ ...reasons, [c.id]: e.target.value })}
            />
            <div className="mt-2 flex gap-2">
              <button type="button" className="btn-primary min-h-0 px-3 py-1.5 text-xs" onClick={() => review(c, true)}>
                <Check size={14} aria-hidden /> Approve
              </button>
              <button type="button" className="btn-ghost min-h-0 px-3 py-1.5 text-xs" onClick={() => review(c, false)}>
                <X size={14} aria-hidden /> Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
