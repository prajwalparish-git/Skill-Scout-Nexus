"use client";

// Project ideas matched to the student's skill gaps, each built from real GitHub repositories
// (metadata only, from GitHub's official Search API), with hackathon links; and the student's
// projects. "Start this project" puts an idea in the Project space as an Idea.
import { useCallback, useEffect, useState } from "react";
import { Building2, ExternalLink, FolderGit2, Lightbulb, Loader2, Play, Sparkles, Star, Trophy } from "lucide-react";
import { get, post, type IdeaSet, type InspirationRepo, type MyProject, type ProjectIdea, type ProjectIdeasPayload } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { Badge, ErrorNote, Loading, NeedsCandidate, PageHeader } from "@/components/ui";

const SOURCE: Record<IdeaSet["source"], string> = {
  live: "Repositories fetched from GitHub just now.",
  cache: "Repositories from GitHub, fetched within the last day.",
  seed: "GitHub was not reachable: built-in example repositories (offline).",
};

function RepoLink({ repo }: { repo: InspirationRepo }) {
  return (
    <a href={repo.url} target="_blank" rel="noopener noreferrer" className="inline-flex flex-wrap items-center gap-1.5 font-medium underline-offset-2 hover:underline">
      {repo.full_name}
      <span className="inline-flex items-center gap-0.5 text-xs font-normal text-muted">
        <Star size={11} aria-hidden /> {repo.stars.toLocaleString()}
      </span>
      {repo.licence && <span className="text-xs font-normal text-muted">· {repo.licence}</span>}
      {repo.company && (
        <span className="chip border-primary/40 py-0 text-[11px] text-primary-ink">
          <Building2 size={11} aria-hidden /> by {repo.company}
        </span>
      )}
      <ExternalLink size={12} aria-hidden />
    </a>
  );
}

function IdeaCard({
  idea,
  busy,
  started,
  onStart,
  onMore,
}: {
  idea: ProjectIdea;
  busy: boolean;
  started: boolean;
  onStart: () => void;
  onMore: () => void;
}) {
  return (
    <article className="card space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{idea.title}</h3>
        <span className="chip">{idea.label}</span>
      </div>
      <p className="text-sm">{idea.problem}</p>
      <p className="text-sm text-muted">{idea.why_it_fits}</p>
      <div className="space-y-2 rounded-xl bg-surface px-3 py-2 text-sm">
        <p className="eyebrow">Inspired by</p>
        {idea.derived_from.map((d) => (
          <div key={d.repo}>
            {d.meta ? <RepoLink repo={d.meta} /> : <span className="font-medium">{d.repo}</span>}
            <p className="text-muted">
              {d.takes} {d.differs}
            </p>
          </div>
        ))}
      </div>
      <p className="flex flex-wrap gap-1.5 text-xs">
        {idea.stack.map((s) => (
          <span key={s} className={`chip ${idea.gap_skills.includes(s) ? "border-warn/50 text-warn" : ""}`}>
            {s}
            {idea.gap_skills.includes(s) ? " · gap" : ""}
          </span>
        ))}
        <span className="chip">
          {idea.scope_weeks} week{idea.scope_weeks === 1 ? "" : "s"}
        </span>
      </p>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">Milestones and stretch goals</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          {idea.milestones.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ol>
        {idea.stretch_goals.length > 0 && <p className="mt-2 text-muted">Stretch: {idea.stretch_goals.join(" · ")}</p>}
      </details>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-primary" disabled={busy || started} onClick={onStart}>
          <Play size={16} aria-hidden /> {started ? "Added to your projects" : "Start this project"}
        </button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={onMore}>
          <Sparkles size={16} aria-hidden /> More like this
        </button>
      </div>
    </article>
  );
}

export default function ProjectsPage() {
  const { candidate, loading } = useCandidate();
  const [data, setData] = useState<ProjectIdeasPayload | null>(null);
  const [projects, setProjects] = useState<MyProject[]>([]);
  const [busy, setBusy] = useState(false);
  const [startingIndex, setStartingIndex] = useState<number | null>(null);
  const [started, setStarted] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const loadProjects = useCallback(() => {
    get<{ projects: MyProject[] }>("/api/projects").then(
      (r) => setProjects(r.projects),
      () => {},
    );
  }, []);
  useEffect(() => {
    if (!candidate) return;
    get<ProjectIdeasPayload>("/api/project-ideas").then(setData, (e: Error) => setNote(e.message));
    loadProjects();
  }, [candidate, loadProjects]);

  async function run(work: () => Promise<{ set: IdeaSet }>) {
    setBusy(true);
    setError(null);
    try {
      const r = await work();
      setData((d) => (d ? { ...d, set: r.set } : d));
      setStarted([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function start(set: IdeaSet, index: number) {
    if (startingIndex !== null || busy) return;
    setStartingIndex(index);
    setError(null);
    try {
      await post(`/api/project-ideas/${set.id}/${index}/start`, {});
      setStarted((s) => [...s, set.ideas[index].title]);
      loadProjects();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStartingIndex(null);
    }
  }

  const set = data?.set;
  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Project ideas for your skill gaps"
        lead="Ideas built from real open-source repositories on your gap topics, including ones companies publish, with hackathon projects for inspiration. Start one and it joins your projects as an idea."
      />
      {loading ? (
        <Loading label="Loading…" />
      ) : !candidate ? (
        <NeedsCandidate />
      ) : note ? (
        <p className="card text-sm">{note}</p>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-4">
            <section className="card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="flex items-center gap-2 font-semibold">
                    <Lightbulb size={16} aria-hidden /> Your gap topics
                  </h2>
                  <p className="mt-1 text-sm text-muted">{data?.topics.map((t) => t.skill || t.keyword).join(" · ") || "…"}</p>
                </div>
                <button type="button" className="btn-primary" disabled={busy} onClick={() => run(() => post<{ set: IdeaSet }>("/api/project-ideas", {}))}>
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Sparkles size={16} aria-hidden />}{" "}
                  {set ? "Suggest new ideas" : "Suggest projects"}
                </button>
              </div>
              {set && (
                <p className="mt-3 text-xs text-muted">
                  {SOURCE[set.source]}
                  {set.based_on ? ` More like: ${set.based_on}.` : ""} Only names, descriptions, stars, topics and licences are used; never code or
                  READMEs.
                </p>
              )}
            </section>
            <ErrorNote message={error} />
            {set?.ideas.map((idea, i) => (
              <IdeaCard
                key={`${set.id}-${i}`}
                idea={idea}
                busy={busy || startingIndex !== null}
                started={started.includes(idea.title)}
                onStart={() => start(set, i)}
                onMore={() => run(() => post<{ set: IdeaSet }>(`/api/project-ideas/${set.id}/${i}/more`, {}))}
              />
            ))}
            {set?.topics.map((t) => (
              <section key={t.topic} className="card space-y-3 text-sm" aria-label={`Inspiration for ${t.keyword}`}>
                <h3 className="font-semibold">Inspiration: {t.keyword}</h3>
                {t.company.length > 0 && (
                  <div>
                    <p className="eyebrow mb-1">Built by companies</p>
                    <ul className="space-y-1">
                      {t.company.map((r) => (
                        <li key={r.full_name}>
                          <RepoLink repo={r} />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {t.hackathon.length > 0 && (
                  <div>
                    <p className="eyebrow mb-1">Hackathon repos (GitHub)</p>
                    <ul className="space-y-1">
                      {t.hackathon.map((r) => (
                        <li key={r.full_name}>
                          <RepoLink repo={r} />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="flex flex-wrap items-center gap-2">
                  <Trophy size={14} aria-hidden /> Find winning projects on this topic:
                  {t.links.map((l) => (
                    <a key={l.name} href={l.url} target="_blank" rel="noopener noreferrer" className="btn-ghost min-h-0 px-2 py-1 text-xs">
                      {l.name} <ExternalLink size={12} aria-hidden />
                    </a>
                  ))}
                </p>
              </section>
            ))}
          </div>
          <aside className="card lg:sticky lg:top-24" aria-labelledby="my-projects">
            <h2 id="my-projects" className="flex items-center gap-2 font-semibold">
              <FolderGit2 size={16} aria-hidden /> My projects
            </h2>
            {projects.length === 0 ? (
              <p className="mt-2 text-sm text-muted">None yet. Start an idea to add it here.</p>
            ) : (
              <ul className="mt-3 space-y-2 text-sm">
                {projects.map((p) => (
                  <li key={p.id} className="rounded-xl border border-hair px-3 py-2">
                    <p className="flex flex-wrap items-center gap-2">
                      <Badge state={p.status === "Done" ? "ok" : p.status === "Idea" ? "todo" : "info"}>{p.status}</Badge>
                      <span className="font-medium">{p.name}</span>
                    </p>
                    {p.tech && <p className="mt-0.5 text-xs text-muted">{p.tech}</p>}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-muted">Edit projects, log progress and add them to your resume in the Project space.</p>
          </aside>
        </div>
      )}
    </>
  );
}
