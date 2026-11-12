"use client";

import { useEffect, useState } from "react";
import { CalendarPlus, Loader2 } from "lucide-react";
import { get, post, type PlanPayload } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { bestLink, pickBook, useLibrary, type Library } from "@/lib/library";
import { BarList } from "@/components/charts";
import { Books } from "@/components/plan/Books";
import { Roadmaps } from "@/components/plan/Roadmaps";
import { ExtLink } from "@/components/plan/shared";
import { Badge, Empty, ErrorNote, Loading, NeedsCandidate, PageHeader, Ring } from "@/components/ui";

const WEAK = 0.5; // piq/config.py WEAK_THRESHOLD

/** The two reading sections under the plan: books, then curated repositories. */
function LibrarySections({
  library,
  error,
  role,
  weakTopics,
}: {
  library: Library | null;
  error: string | null;
  role: string | null;
  weakTopics: string[];
}) {
  if (error)
    return (
      <div className="mt-12">
        <ErrorNote message={`The reading library could not load: ${error}`} />
      </div>
    );
  if (!library)
    return (
      <p role="status" className="mt-12 text-sm text-muted">
        Loading the reading library…
      </p>
    );
  return (
    <>
      <Books library={library} role={role} weakTopics={weakTopics} />
      <Roadmaps library={library} role={role} />
    </>
  );
}

export default function PlanPage() {
  const { candidate } = useCandidate();
  const { library, error: libraryError } = useLibrary();
  const [data, setData] = useState<PlanPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");

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
    setAnnounce("Generating your study plan.");
    try {
      const next = await post<PlanPayload>(`/api/plan/${candidate.id}/next`, {});
      setData(next);
      setAnnounce(`Week ${next.plan?.week_no ?? ""} study plan is ready.`);
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
      setAnnounce(`Day ${day} marked ${r.done.includes(day) ? "done" : "not done"}. ${r.done.length} of 7 days done this week.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!candidate)
    return (
      <>
        <PageHeader eyebrow="Study plan" title="A week that adapts to you" lead="Seven days of study weighted to your weakest topics." />
        <NeedsCandidate />
        <LibrarySections library={library} error={libraryError} role={null} weakTopics={[]} />
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
  const weakTopics = weakness.filter(([, w]) => w > WEAK).map(([t]) => t);
  const domain = library?.roles[candidate.target_role]?.domain;
  const doneCount = data?.done.length ?? 0;
  const totalMinutes = plan ? plan.days.reduce((n, d) => n + d.duration_min, 0) : 0;

  return (
    <>
      <PageHeader
        eyebrow="Study plan"
        title={plan ? `Week ${plan.week_no}` : "A week that adapts to you"}
        lead="Seven days of study weighted to your weakest topics. A critic checks that weak topics get at least half the time before you see it."
        actions={
          <button type="button" className="btn-primary" disabled={busy || !data} onClick={generate}>
            {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <CalendarPlus size={16} aria-hidden />}
            {busy ? "Generating study plan…" : plan ? `Generate week ${data?.next_week} study plan` : "Generate my first week's study plan"}
          </button>
        }
      />
      <p role="status" aria-live="polite" className="sr-only">
        {announce}
      </p>
      <ErrorNote message={error} />

      {!data && !error && <Loading label="Loading your study plan…" />}
      {!plan && data && (
        <Empty icon={CalendarPlus}>
          No plan yet. Generate your first week: it puts your weakest topics first and is checked before you see it.
        </Empty>
      )}

      {plan && (
        <>
          <section aria-label="This week at a glance" className="card surface-light mb-6 flex flex-wrap items-center gap-6">
            <Ring value={doneCount} max={7} label="Days done this week" size={96} />
            <div className="min-w-0 flex-1">
              <p className="eyebrow">This week</p>
              <p className="mt-1 font-display text-xl font-semibold tracking-tight">
                {doneCount} of 7 days done · {Math.round(totalMinutes / 60)} h planned
              </p>
              <p className="mt-2 max-w-2xl text-sm text-muted">{plan.rationale}</p>
            </div>
          </section>

          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <section aria-label={`Week ${plan.week_no}, day by day`}>
              <ol className="space-y-3">
                {plan.days.map((d) => {
                  const done = data!.done.includes(d.day);
                  const weak = (data!.weakness[d.topic] ?? 0) > WEAK;
                  const book = library && domain ? pickBook(library, domain, d.topic) : null;
                  return (
                    <li key={d.day}>
                      <article className={`card flex gap-4 ${done ? "bg-surface/40" : ""}`}>
                        <label className="-m-1 flex h-fit cursor-pointer flex-col items-center gap-1 p-1">
                          <input
                            type="checkbox"
                            className="h-5 w-5 accent-[rgb(var(--primary))]"
                            checked={done}
                            onChange={() => toggle(d.day)}
                            aria-label={`Day ${d.day}: ${d.topic}, mark as done`}
                          />
                          <span className="font-mono text-[10px] text-muted" aria-hidden>
                            D{d.day}
                          </span>
                        </label>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className={`font-semibold ${done ? "text-muted line-through decoration-line" : ""}`}>
                              Day {d.day}: {d.topic}
                            </h3>
                            <span className="chip border-line font-mono text-ink">{d.duration_min} min</span>
                            {done && <Badge state="ok">Done</Badge>}
                            {weak && <Badge state="warn">Weak topic</Badge>}
                          </div>
                          {d.subtopics.length > 0 && (
                            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Subtopics">
                              {d.subtopics.map((t) => (
                                <li key={t} className="rounded-full bg-surface px-2.5 py-0.5 text-xs">
                                  {t}
                                </li>
                              ))}
                            </ul>
                          )}
                          <p className="mt-2 text-sm">{d.practice_goal}</p>
                          {book && (
                            <p className="mt-2 text-sm text-muted">
                              Deep reading:{" "}
                              <ExtLink href={bestLink(book).url} className="font-medium text-primary-ink">
                                {book.title}
                              </ExtLink>
                            </p>
                          )}
                        </div>
                      </article>
                    </li>
                  );
                })}
              </ol>
            </section>

            <aside className="space-y-6">
              <section className="card" aria-labelledby="plan-minutes">
                <h2 id="plan-minutes" className="text-sm font-semibold">
                  {minutes[0] ? `${minutes[0][0]} gets the most time this week` : "Minutes by topic"}
                </h2>
                <div className="mt-4">
                  <BarList
                    ariaLabel="Minutes by topic this week"
                    max={Math.max(...minutes.map((m) => m[1]), 1)}
                    unit=" min"
                    rows={minutes.map(([t, m]) => ({ label: t, value: m, note: `${t}: ${m} minutes over the week` }))}
                  />
                </div>
              </section>
              <section className="card" aria-labelledby="plan-weakness">
                <h2 id="plan-weakness" className="text-sm font-semibold">
                  {topWeak ? `${topWeak[0]} is your weakest topic` : "Weakness by topic"}
                </h2>
                <table className="mt-3 w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted">
                      <th scope="col" className="pb-1 font-medium">Topic</th>
                      <th scope="col" className="pb-1 text-right font-medium">Weakness</th>
                      <th scope="col" className="pb-1 text-right font-medium">Avg score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {weakness.map(([t, w]) => (
                      <tr key={t} className="border-t border-hair">
                        <td className="py-2">{t}</td>
                        <td className="py-2 text-right font-mono tabular-nums">{w.toFixed(2)}</td>
                        <td className="py-2 text-right font-mono tabular-nums text-muted">
                          {data!.scores[t] != null ? `${Math.round(data!.scores[t])}%` : "no quiz"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-3 text-xs text-muted">0 is strong, 1 is weak; above {WEAK} counts as weak.</p>
              </section>
            </aside>
          </div>
        </>
      )}

      <LibrarySections library={library} error={libraryError} role={candidate.target_role} weakTopics={weakTopics} />
    </>
  );
}
