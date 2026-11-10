"use client";

import { useEffect, useState } from "react";
import { get, type DashboardPayload } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { BarList, LineChart } from "@/components/charts";
import { Badge, Empty, ErrorNote, NeedsCandidate, PageHeader } from "@/components/ui";

const TREND: Record<string, "ok" | "warn" | "todo" | "info"> = {
  improving: "ok",
  steady: "info",
  slipping: "warn",
  new: "todo",
};

const day = (ts: string) =>
  new Date(ts.replace(" ", "T") + (ts.endsWith("Z") ? "" : "Z")).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });

function readinessHeadline(scores: number[]): string {
  if (!scores.length) return "Readiness";
  const first = scores[0];
  const last = scores[scores.length - 1];
  if (scores.length === 1) return `Readiness is ${last}/100 from your first profile`;
  if (last === first) return `Readiness held at ${last}/100 over ${scores.length} profiles`;
  return `Readiness ${last > first ? "rose" : "fell"} from ${first} to ${last} over ${scores.length} profiles`;
}

export default function DashboardPage() {
  const { candidate } = useCandidate();
  const [d, setD] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setD(null);
    setError(null);
    if (!candidate) return;
    let current = true; // a reply for the previous candidate must not land on this one
    get<DashboardPayload>(`/api/dashboard/${candidate.id}`).then(
      (payload) => current && setD(payload),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [candidate]);

  if (!candidate)
    return (
      <>
        <PageHeader title="Dashboard" lead="Readiness, topic mastery and score trends." />
        <NeedsCandidate />
      </>
    );

  const scores = d?.readiness.map((r) => r.readiness_score) ?? [];
  const mastery = [...(d?.mastery ?? [])].sort((a, b) => b.weakness - a.weakness);
  const accuracy = d && d.answered.total ? Math.round((100 * d.answered.correct) / d.answered.total) : null;

  return (
    <>
      <PageHeader title="Dashboard" lead="How your readiness, quiz scores and interviews are moving." />
      <ErrorNote message={error} />
      {d && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Readiness", `${d.profile.readiness_score}/100`],
              ["Quizzes taken", d.quizzes_taken],
              ["Answered correctly", accuracy === null ? "–" : `${accuracy}%`],
              ["Study streak", `${d.streak.current} day${d.streak.current === 1 ? "" : "s"}`],
            ].map(([label, value]) => (
              <div key={label} className="card py-4">
                <p className="text-xs text-muted">{label}</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="card">
              <h2 className="font-semibold">{readinessHeadline(scores)}</h2>
              <p className="mb-3 text-xs text-muted">Readiness out of 100 at each profile.</p>
              <LineChart
                ariaLabel={`Readiness by profile: ${scores.join(", ")} of 100`}
                points={d.readiness.map((r) => ({ label: day(r.created_at), value: r.readiness_score }))}
                unit="/100"
              />
            </section>

            <section className="card">
              <h2 className="font-semibold">
                {mastery[0] ? `${mastery[0].topic} needs the most work` : "Topic mastery"}
              </h2>
              <p className="mb-3 text-xs text-muted">Weakness per topic, 0 strong to 100 weak; hover for recent scores.</p>
              <BarList
                ariaLabel="Weakness by topic"
                max={100}
                rows={mastery.map((m) => ({
                  label: m.topic,
                  value: Math.round(m.weakness * 100),
                  note: m.scores.length ? `Last scores: ${m.scores.slice(-4).map((s) => Math.round(s)).join("%, ")}%` : "No quiz yet",
                }))}
              />
            </section>
          </div>

          <section className="card mt-6 overflow-x-auto">
            <h2 className="mb-3 font-semibold">Topics and their trend</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="pb-2 font-medium">Topic</th>
                  <th className="pb-2 text-right font-medium">Quizzes</th>
                  <th className="pb-2 text-right font-medium">Latest</th>
                  <th className="pb-2 font-medium">Trend</th>
                </tr>
              </thead>
              <tbody>
                {mastery.map((m) => (
                  <tr key={m.topic} className="border-t border-hair">
                    <td className="py-2">{m.topic}</td>
                    <td className="py-2 text-right tabular-nums">{m.scores.length}</td>
                    <td className="py-2 text-right tabular-nums">
                      {m.scores.length ? `${Math.round(m.scores[m.scores.length - 1])}%` : "–"}
                    </td>
                    <td className="py-2">
                      <Badge state={TREND[m.trend] ?? "todo"}>{m.trend}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <section className="card">
              <h2 className="mb-3 font-semibold">Skills on the resume</h2>
              <div className="flex flex-wrap gap-1">
                {d.profile.matched_skills.map((s) => (<Badge key={s} state="ok">{s}</Badge>))}
                {d.profile.missing_skills.map((s) => (<Badge key={s} state="todo">{s}</Badge>))}
              </div>
              <p className="mt-2 text-xs text-muted">A filled check is on the resume; an empty circle is missing for {d.profile.target_role}.</p>
            </section>
            <section className="card">
              <h2 className="mb-3 font-semibold">Recent interviews</h2>
              {d.sessions.length ? (
                <ul className="space-y-1 text-sm">
                  {d.sessions.slice(0, 6).map((s, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span>{day(s.started)} · {s.interview_type}</span>
                      <span className="tabular-nums text-muted">{s.avg_overall?.toFixed(1)}/5</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>No interviews yet.</Empty>
              )}
            </section>
          </div>
        </>
      )}
    </>
  );
}
