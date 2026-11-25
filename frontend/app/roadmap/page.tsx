"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Calendar,
  CheckCircle2,
  CheckSquare,
  Clock,
  ExternalLink,
  Loader2,
  Route,
  Sparkles,
  Square,
  Target,
} from "lucide-react";
import { PageHeader, ErrorNote } from "@/components/ui";
import { SignInPrompt } from "@/components/site/auth";
import { useCandidate } from "@/lib/candidate";
import {
  journeyApi,
  type RoadmapItem,
  type RoadmapsResponse,
} from "@/lib/journeyApi";

export default function RoadmapPage() {
  const { candidate, loading: authLoading } = useCandidate();

  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [data, setData] = useState<RoadmapsResponse | null>(null);
  const [selectedGaps, setSelectedGaps] = useState<string[]>([]);
  const [activeWeek, setActiveWeek] = useState<number>(1);
  const [savingTask, setSavingTask] = useState<string | null>(null);

  useEffect(() => {
    if (!candidate) return;
    loadRoadmaps();
  }, [candidate]);

  const loadRoadmaps = async () => {
    setLoading(true);
    try {
      const res = await journeyApi.getRoadmaps();
      setData(res);
      if (res.roadmaps.length) {
        setActiveWeek(res.roadmaps[res.roadmaps.length - 1].week);
      }
      if (res.gaps.length) {
        setSelectedGaps(res.gaps.slice(0, 5));
      } else if (res.role_skills.length) {
        setSelectedGaps(res.role_skills.slice(0, 5));
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleGap = (gap: string) => {
    if (selectedGaps.includes(gap)) {
      setSelectedGaps(selectedGaps.filter((g) => g !== gap));
    } else {
      setSelectedGaps([...selectedGaps, gap]);
    }
  };

  const handleGenerate = async () => {
    if (!selectedGaps.length) {
      setError("Pick at least one skill gap to address in your 7-day plan.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const res = await journeyApi.buildRoadmap(selectedGaps);
      await loadRoadmaps();
      setActiveWeek(res.roadmap.week);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const handleToggleTask = async (week: number, taskKey: string, currentDone: string[]) => {
    // One save at a time: each save sends the whole list, so two in flight would drop a tick.
    if (savingTask) return;
    setSavingTask(taskKey);
    const newDone = currentDone.includes(taskKey)
      ? currentDone.filter((k) => k !== taskKey)
      : [...currentDone, taskKey];

    try {
      await journeyApi.setTasksDone(week, newDone);
      if (data) {
        setData({
          ...data,
          roadmaps: data.roadmaps.map((r) =>
            r.week === week ? { ...r, done: newDone } : r
          ),
        });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingTask(null);
    }
  };

  if (authLoading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="animate-spin text-muted" size={32} />
      </div>
    );
  }

  if (!candidate) {
    return (
      <div>
        <PageHeader
          eyebrow="Placement Journey · Step 3"
          title="7-Day Study Roadmap"
          lead="A tailored day-by-day plan with free learning resources and verified proof tasks."
        />
        <div className="panel p-8 text-center max-w-lg mx-auto">
          <Route size={36} className="mx-auto text-muted mb-3" />
          <p className="font-semibold text-ink">Sign in to view and build roadmaps</p>
          <p className="text-xs text-muted mt-1">
            Track daily micro-tasks, access high-quality resources, and level up your skills.
          </p>
          <SignInPrompt />
        </div>
      </div>
    );
  }

  const currentRoadmap = data?.roadmaps.find((r) => r.week === activeWeek);
  const allAvailableSkills = data ? Array.from(new Set([...data.gaps, ...data.role_skills])) : [];

  const totalTasks = currentRoadmap
    ? currentRoadmap.plan.days.reduce((acc, d) => acc + d.micro_tasks.length, 0)
    : 0;
  const doneCount = currentRoadmap ? currentRoadmap.done.length : 0;
  const progressPct = totalTasks ? Math.round((doneCount / totalTasks) * 100) : 0;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Placement Journey · Step 3"
        title="7-Day Study Roadmap"
        lead="A structured daily curriculum for your diagnosed skill gaps: curated free materials and actionable micro-tasks."
      />

      <ErrorNote message={error} />

      {/* Generator Card */}
      <div className="panel p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-hair pb-3">
          <div>
            <p className="font-semibold text-sm">Skills to Cover in Next Plan</p>
            <p className="text-xs text-muted">
              {data?.gaps.length
                ? `Suggested from ${data.origin} for ${data.target_role}`
                : `Role skills for ${candidate.target_role}`}
            </p>
          </div>
          <button
            type="button"
            disabled={generating || !selectedGaps.length}
            onClick={handleGenerate}
            className="btn-ink text-xs flex items-center gap-2"
          >
            {generating ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                <span>Generating Week...</span>
              </>
            ) : (
              <>
                <Sparkles size={13} />
                <span>Generate 7-Day Plan</span>
              </>
            )}
          </button>
        </div>

        <div className="flex flex-wrap gap-2 pt-1">
          {allAvailableSkills.map((skill) => {
            const isSelected = selectedGaps.includes(skill);
            return (
              <button
                key={skill}
                type="button"
                onClick={() => handleToggleGap(skill)}
                className={`chip text-xs transition-colors ${
                  isSelected ? "bg-ink text-bg font-semibold border-ink" : "border-hair text-muted hover:text-ink"
                }`}
              >
                {skill}
              </button>
            );
          })}
        </div>
      </div>

      {/* Roadmaps Display */}
      {loading ? (
        <div className="py-16 text-center text-muted">
          <Loader2 className="mx-auto animate-spin" size={28} />
          <p className="mt-2 text-xs">Loading study roadmaps...</p>
        </div>
      ) : currentRoadmap ? (
        <div className="space-y-6">
          {/* Week Selector & Progress */}
          <div className="flex flex-wrap items-center justify-between gap-4 panel p-4">
            <div className="flex gap-2">
              {data?.roadmaps.map((r) => (
                <button
                  key={r.week}
                  type="button"
                  onClick={() => setActiveWeek(r.week)}
                  className={`px-3 py-1.5 text-xs rounded-xl font-medium transition-colors ${
                    activeWeek === r.week ? "bg-ink text-bg font-semibold" : "text-muted hover:bg-surface"
                  }`}
                >
                  Week {r.week}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-3 text-xs">
              <span className="text-muted">Progress:</span>
              <span className="font-mono font-semibold text-ink">
                {doneCount} / {totalTasks} tasks ({progressPct}%)
              </span>
              <div className="h-2 w-28 rounded-full bg-hair overflow-hidden">
                <div
                  className="h-full bg-ink rounded-full transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
          </div>

          {/* Days Grid */}
          <div className="space-y-4">
            {currentRoadmap.plan.days.map((day) => (
              <div key={day.day_number} className="panel p-5 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hair pb-3">
                  <div className="flex items-center gap-2">
                    <span className="chip border-ink/30 font-semibold text-xs">
                      Day {day.day_number}
                    </span>
                    <h4 className="font-semibold text-sm text-ink">{day.focus_topic}</h4>
                  </div>

                  {day.learning_resource && (
                    <a
                      href={day.learning_resource.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-xs text-primary-ink font-medium hover:underline"
                    >
                      <BookOpen size={13} />
                      <span>
                        {day.learning_resource.title} ({day.learning_resource.platform} · {day.learning_resource.estimated_time})
                      </span>
                      <ExternalLink size={11} />
                    </a>
                  )}
                </div>

                {/* Micro Tasks */}
                <div className="space-y-2">
                  <p className="eyebrow text-[10px]">Verification Micro-tasks</p>
                  {day.micro_tasks.map((task, tIdx) => {
                    const tKey = `d${day.day_number}:${tIdx}`;
                    const isDone = currentRoadmap.done.includes(tKey);
                    return (
                      <div
                        key={tKey}
                        onClick={() => handleToggleTask(currentRoadmap.week, tKey, currentRoadmap.done)}
                        className={`flex items-start gap-3 rounded-xl border p-3 cursor-pointer text-xs transition-colors ${
                          isDone
                            ? "border-ok/30 bg-ok/[0.03] text-muted line-through"
                            : "border-hair hover:bg-surface/50 text-ink"
                        }`}
                      >
                        <button type="button" className="mt-0.5 shrink-0 text-ink">
                          {isDone ? (
                            <CheckSquare size={16} className="text-ok" />
                          ) : (
                            <Square size={16} className="text-muted" />
                          )}
                        </button>
                        <div className="flex-1">
                          <p className="font-medium">{task.task_description}</p>
                          <p className="text-[10px] text-muted mt-0.5">
                            Est: {task.estimated_minutes} min · Proof: {task.verification_method}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="text-center pt-4">
            <Link href="/critic-quiz" className="btn-ink inline-flex items-center gap-2 text-xs">
              <span>Ready to test your knowledge? Take Critic-Checked Quiz</span>
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      ) : (
        <div className="panel p-12 text-center text-muted">
          <Route size={32} className="mx-auto mb-2 opacity-50" />
          <p className="font-medium text-ink">No Study Roadmap Yet</p>
          <p className="text-xs text-muted mt-1">
            Pick your priority skill gaps above and click &ldquo;Generate 7-Day Plan&rdquo; to build your tailored daily curriculum.
          </p>
        </div>
      )}
    </div>
  );
}
