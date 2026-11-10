"use client";

import { useEffect, useState } from "react";
import { CalendarPlus, Loader2 } from "lucide-react";
import { get, post, type PlanPayload } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { BarList } from "@/components/charts";
import { Badge, Empty, ErrorNote, NeedsCandidate, PageHeader } from "@/components/ui";

const WEAK = 0.5; // piq/config.py WEAK_THRESHOLD

export default function PlanPage() {
  const { candidate } = useCandidate();
  const [data, setData] = useState<PlanPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    if (!candidate) return;
    let current = true; // a reply for the previous candidate must not land on this one
    get<PlanPayload>(`/api/plan/${candidate.id}`).then(
      (payload) => current && setData(payload),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [candidate]);

  async function generate() {
    if (!candidate) return;
    setBusy(true);
    setError(null);
    try {
      setData(await post<PlanPayload>(`/api/plan/${candidate.id}/next`, {}));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggle(day: number) {
    if (!candidate || !data?.plan) return;
    const done = data.done.includes(day) ? data.done.filter((d) => d !== day) : [...data.done, day];
    try {
      const r = await post<{ done: number[] }>(`/api/plan/${candidate.id}/done`, { week_no: data.plan.week_no, days: done });
      setData({ ...data, done: r.done });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!candidate)
    return (
      <>
        <PageHeader title="Weekly plan" lead="Seven days of study weighted to your weakest topics." />
        <NeedsCandidate />
      </>
    );

  const plan = data?.plan;
  const minutes = plan
    ? Object.entries(
        plan.days.reduce<Record<string, number>>((acc, d) => ({ ...acc, [d.topic]: (acc[d.topic] ?? 0) + d.duration_min }), {}),
      ).sort((a, b) => b[1] - a[1])
    : [];
  const weakness = data ? Object.entries(data.weakness).sort((a, b) => b[1] - a[1]) : [];
  const topWeak = weakness[0];

  return (
    <>
      <PageHeader
        title="Weekly plan"
        lead="Seven days of study weighted to your weakest topics. A critic checks that weak topics get at least half the time before you see it."
      />
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <button type="button" className="btn-primary" disabled={busy || !data} onClick={generate}>
          {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <CalendarPlus size={16} aria-hidden />}
          {plan ? `Plan week ${data?.next_week}` : "Plan my first week"}
        </button>
        {plan && <span className="text-sm text-muted">{data?.done.length ?? 0} of 7 days done this week</span>}
      </div>
      <ErrorNote message={error} />

      {!plan && data && <Empty>No plan yet. Plan your first week to get started.</Empty>}

      {plan && (
        <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
          <section aria-label={`Week ${plan.week_no}`} className="space-y-3">
            <p className="text-sm text-muted">{plan.rationale}</p>
            {plan.days.map((d) => {
              const done = data!.done.includes(d.day);
              return (
                <article key={d.day} className="card flex gap-4">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 accent-[rgb(var(--primary))]"
                    checked={done}
                    onChange={() => toggle(d.day)}
                    aria-label={`Day ${d.day} done`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold">Day {d.day}: {d.topic}</h3>
                      <span className="text-sm text-muted">{d.duration_min} min</span>
                      {done && <Badge state="ok">Done</Badge>}
                      {(data!.weakness[d.topic] ?? 0) > WEAK && <Badge state="warn">Weak topic</Badge>}
                    </div>
                    <p className="mt-1 text-sm text-muted">{d.subtopics.join(" · ")}</p>
                    <p className="mt-1 text-sm">{d.practice_goal}</p>
                  </div>
                </article>
              );
            })}
          </section>

          <aside className="space-y-6">
            <section className="card">
              <h2 className="text-sm font-semibold">
                {minutes[0] ? `${minutes[0][0]} gets the most time this week` : "Minutes by topic"}
              </h2>
              <div className="mt-3">
                <BarList
                  ariaLabel="Minutes by topic this week"
                  max={Math.max(...minutes.map((m) => m[1]), 1)}
                  unit=" min"
                  rows={minutes.map(([t, m]) => ({ label: t, value: m, note: `${t}: ${m} minutes over the week` }))}
                />
              </div>
            </section>
            <section className="card">
              <h2 className="text-sm font-semibold">
                {topWeak ? `${topWeak[0]} is your weakest topic` : "Weakness by topic"}
              </h2>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="pb-1 font-medium">Topic</th>
                    <th className="pb-1 text-right font-medium">Weakness</th>
                    <th className="pb-1 text-right font-medium">Avg score</th>
                  </tr>
                </thead>
                <tbody>
                  {weakness.map(([t, w]) => (
                    <tr key={t} className="border-t border-hair">
                      <td className="py-1.5">{t}</td>
                      <td className="py-1.5 text-right tabular-nums">{w.toFixed(2)}</td>
                      <td className="py-1.5 text-right tabular-nums text-muted">
                        {data!.scores[t] != null ? `${Math.round(data!.scores[t])}%` : "no quiz"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted">0 is strong, 1 is weak; above {WEAK} counts as weak.</p>
            </section>
          </aside>
        </div>
      )}
    </>
  );
}
