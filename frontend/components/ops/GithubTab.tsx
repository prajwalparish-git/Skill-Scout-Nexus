"use client";

// Tab 3: the GitHub inspiration data behind Project Ideas: the curated repo seed, the skill ->
// topic map and the company organizations.
import { useCallback, useEffect, useState } from "react";
import { Building2, FolderGit2, Tags } from "lucide-react";
import { CSV_KINDS, opsApi, type GithubStats } from "@/lib/opsApi";
import { CsvImporter } from "./CsvImporter";
import { Kpi, errText } from "./shared";

export function GithubTab() {
  const [stats, setStats] = useState<GithubStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    opsApi.githubStats().then(setStats, (e) => setError(errText(e)));
  }, []);
  useEffect(load, [load]);

  const k = stats?.repos.by_kind ?? {};
  return (
    <div className="grid grid-cols-1 gap-4">
      {error && <p className="text-sm text-bad">{error}</p>}
      <section aria-label="GitHub data statistics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi
          label="Curated repos"
          value={stats?.repos.repos ?? "…"}
          icon={FolderGit2}
          hint={stats ? `${k.popular ?? 0} popular · ${k.company ?? 0} company · ${k.hackathon ?? 0} hackathon` : undefined}
        />
        <Kpi label="Topics" value={stats?.repos.topics ?? "…"} icon={Tags} hint={stats ? `seed fetched ${stats.repos.fetched || "—"}` : undefined} />
        <Kpi label="Mapped skills" value={stats?.skills ?? "…"} icon={Tags} hint={stats ? `${stats.skills_without_topic} without a topic` : undefined} />
        <Kpi
          label="Company orgs"
          value={stats?.orgs ?? "…"}
          icon={Building2}
          hint={stats ? `${stats.cache_rows} cached searches · token ${stats.token ? "set" : "not set"}` : undefined}
        />
      </section>

      <CsvImporter
        kind={CSV_KINDS.repos}
        title="Curated repositories · data/project_inspiration_seed.json"
        icon={FolderGit2}
        lead="The offline / mock-mode seed for Project Ideas (metadata only, never code). Blank owner and url are derived from full_name; topics are separated by | or ;. Rows are keyed by (topic, kind, full_name)."
        columns="topic*, kind* (popular|company|hackathon), full_name*, owner, owner_is_org, company, description, stars, language, topics, licence, url, pushed_at"
        onDone={load}
      />
      <CsvImporter
        kind={CSV_KINDS.topics}
        title="Skill → GitHub topic · data/github_topics.json"
        icon={Tags}
        lead="Which GitHub topic a student's skill searches, and the keyword used for hackathon links. A blank topic means the skill has no project topic (aptitude, maths)."
        columns="skill*, topic*, keyword"
        onDone={load}
      />
      <CsvImporter
        kind={CSV_KINDS.orgs}
        title="Company GitHub organizations · data/company_orgs.json"
        icon={Building2}
        lead="A repository counts as “built by a company” only when its owner is one of these GitHub Organizations (lower-case logins)."
        columns="login*, name*"
        onDone={load}
      />
    </div>
  );
}
