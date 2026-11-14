"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { CalendarDays, CalendarPlus, Loader2 } from "lucide-react";
import { download, get, post, type PlanPayload } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { useChecklist } from "@/lib/checklist";
import { bestLink, pickBook, useLibrary, type Library } from "@/lib/library";
import { BarList } from "@/components/charts";
import { Books } from "@/components/plan/Books";
import { Roadmaps } from "@/components/plan/Roadmaps";
import { ExtLink, FilterPill } from "@/components/plan/shared";
import { Badge, Empty, ErrorNote, Loading, NeedsCandidate, PageHeader, Ring } from "@/components/ui";
import { SPRING_UI } from "@/lib/site";

const WEAK = 0.5; // piq/config.py WEAK_THRESHOLD

const VIEWS = [
  { id: "all", label: "All" },
  { id: "core", label: "Core modules" },
  { id: "books", label: "Books" },
  { id: "repos", label: "GitHub repos" },
] as const;
type View = (typeof VIEWS)[number]["id"];

/** The two reading sections under the plan: books, then curated repositories. */
function LibrarySections({
  library,
  error,
  role,
  weakTopics,
  view,
  checked,
  onToggle,
}: {
  library: Library | null;
  error: string | null;
  role: string | null;
  weakTopics: string[];
  view: View;
  checked: Set<string>;
  onToggle: (id: string) => void;
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
      {(view === "all" || view === "books") && (
        <Books library={library} role={role} weakTopics={weakTopics} checked={checked} onToggle={onToggle} />
      )}
      {(view === "all" || view === "repos") && <Roadmaps library={library} role={role} checked={checked} onToggle={onToggle} />}
    </>
  );
}

export default function PlanPage() {
  const { candidate, loading: candidateLoading } = useCandidate();
  const { library, error: libraryError } = useLibrary();
  const [data, setData] = useState<PlanPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const [view, setView] = useState<View>("all");
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const candidateId = candidate?.id;
  const { checked: checkedLibrary, toggle: toggleLibrary } = useChecklist(`ssn.plan.checklist.${candidateId ?? "guest"}`);

  // Keyed on the id: a refreshed copy of the same student does not reload the plan.
  useEffect(() => {
    setData(null);
    setError(null);
    if (!candidateId) return;
    let current = true; // a reply for the previous candidate must not land on this one
    get<PlanPayload>(`/api/plan/${candidateId}`).then(
      (payload) => current && setData(payload),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [candidateId]);

  async function exportCalendar() {
    if (!candidate) return;
    setExporting(true);
    setError(null);
    try {
      await download(`/api/plan/${candidate.id}/calendar.ics`, "study-plan.ics");
      setAnnounce("Calendar file downloaded. Open it to add the week to your calendar.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }

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

  // One save at a time: the server stores exactly the days sent, so two overlapping saves built
  // from the same list would undo each other.
  async function toggle(day: number) {
    if (!candidate || !data?.plan || saving) return;
    const done = data.done.includes(day) ? data.done.filter((d) => d !== day) : [...data.done, day];
    setSaving(true);
    try {
      const r = await post<{ done: number[] }>(`/api/plan/${candidate.id}/done`, { week_no: data.plan.week_no, days: done });
      setData((prev) => (prev ? { ...prev, done: r.done } : prev));
      setAnnounce(`Day ${day} marked ${r.done.includes(day) ? "done" : "not done"}. ${r.done.length} of 7 days done this week.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (candidateLoading)
    return (
      <>
        <PageHeader eyebrow="Study plan" title="A week that adapts to you" lead="Seven days of study weighted to your weakest topics." />
        <Loading label="Checking your profile…" />
      </>
    );

  if (!candidate)
    return (
      <>
        <PageHeader eyebrow="Study plan" title="A week that adapts to you" lead="Seven days of study weighted to your weakest topics." />
        <NeedsCandidate />
        <LibrarySections
          library={library}
          error={libraryError}
          role={null}
          weakTopics={[]}
          view={view}
          checked={checkedLibrary}
          onToggle={toggleLibrary}
        />
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
          <div className="flex flex-wrap gap-2">
            {plan && (
              <button type="button" className="btn-hair" disabled={exporting} onClick={exportCalendar}>
                {exporting ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <CalendarDays size={16} aria-hidden />}
                Add week {plan.week_no} to my calendar
              </button>
            )}
            <button type="button" className="btn-primary" disabled={busy || !data} onClick={generate}>
              {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <CalendarPlus size={16} aria-hidden />}
              {busy ? "Generating study plan…" : plan ? `Generate week ${data?.next_week} study plan` : "Generate my first week's study plan"}
            </button>
          </div>
        }
      />
      <p role="status" aria-live="polite" className="sr-only">
        {announce}
      </p>
      <ErrorNote message={error} />

      {plan && (
        <div className="sticky top-[7.5rem] z-10 mb-4 rounded-2xl border border-hair bg-bg/85 px-4 py-3 backdrop-blur-xl lg:top-4">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Overall plan completion</span>
            <span className="font-mono text-xs tabular-nums text-muted">
              {doneCount} of 7 days done ({Math.round((doneCount / 7) * 100)}%)
              {checkedLibrary.size > 0 && ` · ${checkedLibrary.size} library item${checkedLibrary.size === 1 ? "" : "s"} marked`}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-hair" aria-hidden>
            <motion.div
              className="h-full rounded-full bg-ink"
              animate={{ width: `${(doneCount / 7) * 100}%` }}
              transition={SPRING_UI}
            />
          </div>
        </div>
      )}

      <div className="mb-5 flex flex-wrap gap-2" role="group" aria-label="Show">
        {VIEWS.map((v) => (
          <FilterPill key={v.id} pressed={view === v.id} onClick={() => setView(v.id)}>
            {v.label}
          </FilterPill>
        ))}
      </div>

      {!data && !error && <Loading label="Loading your study plan…" />}
      {!plan && data && (
        <Empty icon={CalendarPlus}>
          No plan yet. Generate your first week: it puts your weakest topics first and is checked before you see it.
        </Empty>
      )}

      {plan && (view === "all" || view === "core") && (
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
                            disabled={saving}
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

      <LibrarySections
        library={library}
        error={libraryError}
        role={candidate.target_role}
        weakTopics={weakTopics}
        view={view}
        checked={checkedLibrary}
        onToggle={toggleLibrary}
      />
    </>
  );
}
