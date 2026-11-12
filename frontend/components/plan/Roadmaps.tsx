"use client";

// "Nexus Curated Roadmaps & Field Guides": free GitHub repositories by category, searchable
// and filterable by target role and skill, each with why it helps and an hours estimate.
import { useEffect, useId, useMemo, useState } from "react";
import { Clock, GitBranch, Search } from "lucide-react";
import { LEVEL_RANK, matches, minRoleFit, roleScore, sharedTerms, type Library, type Repo } from "@/lib/library";
import { Empty } from "@/components/ui";
import { ExtLink, FilterPill, LevelTag } from "./shared";

const MAX_SKILLS = 14;

export function Roadmaps({ library, role }: { library: Library; role: string | null }) {
  const [q, setQ] = useState("");
  const [roleName, setRoleName] = useState(role ?? "");
  const [category, setCategory] = useState("");
  const [skill, setSkill] = useState("");
  const id = useId();

  useEffect(() => setRoleName(role ?? ""), [role]);
  useEffect(() => setSkill(""), [roleName, category]);

  const roleEntry = roleName ? library.roles[roleName] : undefined;
  const rolesByDomain = useMemo(
    () =>
      library.domains
        .map((d) => ({ ...d, roles: Object.keys(library.roles).filter((r) => library.roles[r].domain === d.id) }))
        .filter((d) => d.roles.length),
    [library],
  );

  // Role and category narrow the pool; the skill chips come from that pool.
  const pool = useMemo(
    () =>
      library.repos
        .map((r) => ({ r, fit: roleScore(r, roleEntry) }))
        .filter(({ r, fit }) => (!roleEntry || (fit >= minRoleFit(roleEntry) || (fit >= 0 && r.topics.length + r.skills.length === 0))) && (!category || r.category === category))
        .filter(({ r }) => matches(q, r.repo, r.why, r.topics, r.skills, r.category)),
    [library, roleEntry, category, q],
  );
  const skills = useMemo(() => {
    const count = new Map<string, number>();
    for (const { r } of pool) for (const s of r.skills) count.set(s, (count.get(s) ?? 0) + 1);
    const wanted = new Set(roleEntry?.skills ?? []);
    return [...count.entries()]
      .sort((a, b) => Number(wanted.has(b[0])) - Number(wanted.has(a[0])) || b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, MAX_SKILLS)
      .map(([s]) => s);
  }, [pool, roleEntry]);

  const shown = useMemo(
    () =>
      pool
        .filter(({ r }) => !skill || r.skills.includes(skill))
        .sort((a, b) => b.fit - a.fit || LEVEL_RANK[a.r.level] - LEVEL_RANK[b.r.level] || a.r.repo.localeCompare(b.r.repo))
        .map(({ r }) => r),
    [pool, skill],
  );

  const grouped = library.repo_categories
    .map((c) => ({ ...c, repos: shown.filter((r) => r.category === c.id) }))
    .filter((c) => c.repos.length);
  const filtered = Boolean(q || roleName || category || skill);
  const reset = () => {
    setQ("");
    setRoleName("");
    setCategory("");
    setSkill("");
  };

  return (
    <section aria-labelledby={`${id}-h`} className="mt-14">
      <div className="flex items-start gap-3">
        <span className="rounded-lg bg-primary/10 p-2 text-primary-ink" aria-hidden>
          <GitBranch size={20} />
        </span>
        <div>
          <h2 id={`${id}-h`} className="font-display text-xl font-semibold tracking-tight">
            Nexus Curated Roadmaps &amp; Field Guides
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Free, open-source repositories picked for students: system design, interview practice, developer
            roadmaps, project-based learning and track specialisations. Hours are rough planning estimates.
          </p>
        </div>
      </div>

      <form role="search" aria-label="Filter repositories" className="mt-5 grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor={`${id}-q`} className="label">
            Search repositories
          </label>
          <div className="relative">
            <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              id={`${id}-q`}
              type="search"
              className="input pl-9"
              placeholder="Name, topic or skill, for example Docker"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label htmlFor={`${id}-r`} className="label">
            Target role
          </label>
          <select id={`${id}-r`} className="input" value={roleName} onChange={(e) => setRoleName(e.target.value)}>
            <option value="">All roles</option>
            {rolesByDomain.map((d) => (
              <optgroup key={d.id} label={d.name}>
                {d.roles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      </form>

      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Category">
        <FilterPill pressed={category === ""} onClick={() => setCategory("")}>
          All categories
        </FilterPill>
        {library.repo_categories.map((c) => (
          <FilterPill key={c.id} pressed={category === c.id} onClick={() => setCategory(category === c.id ? "" : c.id)}>
            {c.name}
          </FilterPill>
        ))}
      </div>

      {skills.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Skill">
          <span className="eyebrow" aria-hidden>
            Skill
          </span>
          {skills.map((s) => (
            <FilterPill key={s} pressed={skill === s} onClick={() => setSkill(skill === s ? "" : s)}>
              {s}
            </FilterPill>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {shown.length === 1 ? "1 repository" : `${shown.length} repositories`}
          {roleName && ` for ${roleName}`}
        </p>
        {filtered && (
          <button type="button" className="text-sm font-medium text-primary-ink underline underline-offset-2" onClick={reset}>
            Clear all filters
          </button>
        )}
      </div>

      {grouped.length === 0 ? (
        <div className="mt-3">
          <Empty>
            No repositories match yet.{" "}
            {roleEntry && roleEntry.domain !== "cs"
              ? "Community guides on GitHub lean towards software, so this track has fewer. Try All roles, or the free-books list."
              : "Try a different search or clear the filters."}
          </Empty>
        </div>
      ) : (
        grouped.map((c) => (
          <div key={c.id} className="mt-8">
            <h3 className="text-base font-semibold">{c.name}</h3>
            <p className="mt-0.5 text-sm text-muted">{c.blurb}</p>
            <ul className="mt-3 grid gap-3 md:grid-cols-2">
              {c.repos.map((r) => (
                <RepoCard key={r.id} repo={r} fits={sharedTerms(r, roleEntry)} role={roleName} />
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}

function RepoCard({ repo: r, fits, role }: { repo: Repo; fits: string[]; role: string }) {
  return (
    <li>
      <article className="card flex h-full flex-col">
        <h4 className="break-words font-mono text-sm font-semibold">{r.repo}</h4>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <LevelTag level={r.level} />
          <span className="chip border-line text-ink">
            <Clock size={12} aria-hidden />
            {r.hours ? `About ${r.hours.toLocaleString()} h` : "Reference list"}
          </span>
        </div>
        <p className="mt-2 flex-1 text-sm">{r.why}</p>
        {fits.length > 0 ? (
          <p className="mt-2 text-xs text-muted">
            <span className="font-medium text-ink">Fits {role}:</span> {fits.slice(0, 5).join(", ")}
          </p>
        ) : (
          r.skills.length > 0 && <p className="mt-2 text-xs text-muted">Skills: {r.skills.slice(0, 5).join(", ")}</p>
        )}
        <p className="mt-3 text-sm font-medium text-primary-ink">
          <ExtLink href={r.url}>
            View {r.repo} on GitHub
          </ExtLink>
        </p>
      </article>
    </li>
  );
}
