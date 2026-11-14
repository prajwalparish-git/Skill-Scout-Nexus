"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { ArrowRight, CalendarDays, CheckCircle2, Flame, ListChecks, MessagesSquare, Sparkles } from "lucide-react";
import { get, type DashboardPayload, type Mastery } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { BarList, LineChart } from "@/components/charts";
import { Badge, Empty, ErrorNote, Loading, NeedsCandidate, PageHeader, Ring, Stat } from "@/components/ui";

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

function tier(score: number): string {
  if (score >= 80) return "Interview-ready: keep your edge with timed quizzes and a mock interview a week.";
  if (score >= 60) return "Close: a few focused weeks on your weakest topics should take you over the line.";
  return "Building up: follow the weekly plan and quiz the weak topics it puts first.";
}

/** The single most useful thing to do next, from what this dashboard already knows. */
function nextAction(d: DashboardPayload, mastery: Mastery[]): { text: string; cta: string; href: string } {
  if (d.quizzes_taken === 0) {
    return d.profile.resume_feedback.length > 0
      ? { text: "Resume parsed. Take a 5-minute quiz next to see where you stand.", cta: "Take a quiz", href: "/quiz" }
      : { text: "Take your first quiz to start tracking readiness.", cta: "Take a quiz", href: "/quiz" };
  }
  if (mastery[0] && mastery[0].weakness > 0.3) {
    return { text: `${mastery[0].topic} is your weakest topic right now.`, cta: `Practise ${mastery[0].topic}`, href: "/quiz" };
  }
  if (d.sessions.length === 0) {
    return { text: "Your quiz scores are solid. A mock interview is the next step.", cta: "Start a mock interview", href: "/interview" };
  }
  return { text: "You're on track. Keep the streak going with another quiz.", cta: "Take a quiz", href: "/quiz" };
}

export default function DashboardPage() {
  const { candidate, loading: candidateLoading } = useCandidate();
  const [d, setD] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const candidateId = candidate?.id;

  // Keyed on the id: a refreshed copy of the same student does not reload the dashboard.
  useEffect(() => {
    setD(null);
    setError(null);
    if (!candidateId) return;
    let current = true; // a reply for the previous candidate must not land on this one
    get<DashboardPayload>(`/api/dashboard/${candidateId}`).then(
      (payload) => current && setD(payload),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [candidateId]);

  if (candidateLoading)
    return (
      <>
        <PageHeader eyebrow="Dashboard" title="Your progress, in one place" lead="Readiness, topic mastery and score trends." />
        <Loading label="Checking your profile…" />
      </>
    );

  if (!candidate)
    return (
      <>
        <PageHeader eyebrow="Dashboard" title="Your progress, in one place" lead="Readiness, topic mastery and score trends." />
        <NeedsCandidate />
      </>
    );

  const scores = d?.readiness.map((r) => r.readiness_score) ?? [];
  const mastery = [...(d?.mastery ?? [])].sort((a, b) => b.weakness - a.weakness);
  const accuracy = d && d.answered.total ? Math.round((100 * d.answered.correct) / d.answered.total) : null;
  const first = candidate.name.split(/\s+/)[0];

  return (
    <>
      <PageHeader
        eyebrow="Dashboard"
        title={`Hi ${first}, here is where you stand`}
        lead="How your readiness, quiz scores and interviews are moving, and what to do next."
        actions={
          <>
            <Link href="/plan" className="btn-ghost">
              <CalendarDays size={16} aria-hidden /> Open study plan
            </Link>
            <Link href="/quiz" className="btn-primary">
              <ListChecks size={16} aria-hidden /> Take a quiz
            </Link>
          </>
        }
      />
      <ErrorNote message={error} />
      {!d && !error && <Loading label="Loading your dashboard…" />}
      {d && (
        <>
          {(() => {
            const action = nextAction(d, mastery);
            return (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
                <Link href={action.href} className="card card-hover group flex items-center gap-4 border-ink/15 bg-ink text-bg">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-bg text-ink" aria-hidden>
                    <Sparkles size={18} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="eyebrow text-bg/60">Next best action</span>
                    <span className="mt-0.5 block text-sm font-semibold sm:text-base">{action.text}</span>
                  </span>
                  <span className="btn-ghost shrink-0 border-bg/30 bg-transparent text-bg">
                    {action.cta} <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </span>
                </Link>
              </motion.div>
            );
          })()}

          <section aria-label="Readiness" className="mt-3 grid gap-3 lg:grid-cols-[1.4fr_1fr_1fr]">
            <div className="card flex items-center gap-5 lg:row-span-2">
              <Ring value={d.profile.readiness_score} label="Readiness" size={112} suffix=" out of 100" />
              <div className="min-w-0">
                <p className="eyebrow">Readiness for</p>
                <p className="mt-1 font-display text-xl font-semibold tracking-tight">{d.profile.target_role}</p>
                <p className="mt-2 text-sm text-muted">{tier(d.profile.readiness_score)}</p>
              </div>
            </div>
            <Stat icon={ListChecks} label="Quizzes taken" value={d.quizzes_taken} />
            <Stat icon={CheckCircle2} label="Answered correctly" value={accuracy === null ? "–" : `${accuracy}%`} hint={`${d.answered.correct} of ${d.answered.total}`} />
            <Stat
              icon={Flame}
              label="Study streak"
              value={`${d.streak.current} day${d.streak.current === 1 ? "" : "s"}`}
              hint={`Longest: ${d.streak.longest} day${d.streak.longest === 1 ? "" : "s"}`}
            />
            <Stat icon={MessagesSquare} label="Mock interviews" value={d.sessions.length} hint={d.sessions[0] ? `Last: ${d.sessions[0].avg_overall?.toFixed(1)}/5` : undefined} />
          </section>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <section className="card" aria-labelledby="dash-readiness">
              <h2 id="dash-readiness" className="h2">{readinessHeadline(scores)}</h2>
              <p className="mb-4 mt-1 text-xs text-muted">Readiness out of 100 at each profile.</p>
              <LineChart
                ariaLabel={`Readiness by profile: ${scores.join(", ")} of 100`}
                points={d.readiness.map((r) => ({ label: day(r.created_at), value: r.readiness_score }))}
                unit="/100"
              />
            </section>

            <section className="card" aria-labelledby="dash-mastery">
              <h2 id="dash-mastery" className="h2">
                {mastery[0] ? `${mastery[0].topic} needs the most work` : "Topic mastery"}
              </h2>
              <p className="mb-4 mt-1 text-xs text-muted">Weakness per topic, 0 strong to 100 weak; hover for recent scores.</p>
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

          <section className="card mt-6 overflow-x-auto" aria-labelledby="dash-topics">
            <h2 id="dash-topics" className="h2 mb-4">Topics and their trend</h2>
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="pb-2 font-medium">Topic</th>
                  <th scope="col" className="pb-2 text-right font-medium">Quizzes</th>
                  <th scope="col" className="w-40 pb-2 pl-4 font-medium">Latest score</th>
                  <th scope="col" className="pb-2 font-medium">Trend</th>
                </tr>
              </thead>
              <tbody>
                {mastery.map((m) => {
                  const latest = m.scores.length ? Math.round(m.scores[m.scores.length - 1]) : null;
                  return (
                    <tr key={m.topic} className="border-t border-hair">
                      <td className="py-3 font-medium">{m.topic}</td>
                      <td className="py-3 text-right font-mono tabular-nums">{m.scores.length}</td>
                      <td className="py-3 pl-4">
                        {latest === null ? (
                          <span className="text-muted">–</span>
                        ) : (
                          <span className="flex items-center gap-2">
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-hair" aria-hidden>
                              <span className="block h-full rounded-full bg-ink" style={{ width: `${latest}%` }} />
                            </span>
                            <span className="w-10 text-right font-mono text-xs tabular-nums">{latest}%</span>
                          </span>
                        )}
                      </td>
                      <td className="py-3">
                        <Badge state={TREND[m.trend] ?? "todo"}>{m.trend}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <section className="card" aria-labelledby="dash-skills">
              <h2 id="dash-skills" className="h2 mb-4">Skills on the resume</h2>
              <div className="flex flex-wrap gap-1.5">
                {d.profile.matched_skills.map((s) => (
                  <Badge key={s} state="ok">
                    {s}
                  </Badge>
                ))}
                {d.profile.missing_skills.map((s) => (
                  <Badge key={s} state="todo">
                    {s}
                  </Badge>
                ))}
              </div>
              <p className="mt-3 text-xs text-muted">
                A filled check is on the resume; an empty circle is missing for {d.profile.target_role}.
              </p>
              {d.profile.resume_feedback.length > 0 && (
                <ul className="mt-4 space-y-1.5 border-t border-hair pt-4 text-sm">
                  {d.profile.resume_feedback.slice(0, 3).map((f) => (
                    <li key={f} className="flex gap-2">
                      <ArrowRight size={14} className="mt-1 shrink-0 text-muted" aria-hidden /> {f}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="card" aria-labelledby="dash-interviews">
              <div className="mb-4 flex items-center justify-between gap-2">
                <h2 id="dash-interviews" className="h2">Recent interviews</h2>
                <Link href="/interview" className="text-sm font-medium text-primary-ink underline-offset-2 hover:underline">
                  Start one
                </Link>
              </div>
              {d.sessions.length ? (
                <ul className="divide-y divide-hair text-sm">
                  {d.sessions.slice(0, 6).map((s, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 py-2.5">
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{s.interview_type}</span>
                        <span className="block text-xs text-muted">{day(s.started)}</span>
                      </span>
                      <span className="font-mono text-sm font-semibold tabular-nums">{s.avg_overall?.toFixed(1)}/5</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty icon={MessagesSquare}>No interviews yet. A mock interview is five questions, each scored on a rubric.</Empty>
              )}
            </section>
          </div>
        </>
      )}
    </>
  );
}
