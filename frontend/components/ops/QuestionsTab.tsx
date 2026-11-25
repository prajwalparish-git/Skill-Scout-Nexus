"use client";

// Tab 2: the question banks: stats, the MCQ importer and the interview importer.
import { useCallback, useEffect, useState } from "react";
import { Archive, BookCheck, ListChecks, MessagesSquare } from "lucide-react";
import { CSV_KINDS, opsApi, type QuestionStats } from "@/lib/opsApi";
import { CsvImporter } from "./CsvImporter";
import { Kpi, Panel, bytes, errText } from "./shared";

export function QuestionsTab() {
  const [stats, setStats] = useState<QuestionStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    opsApi.questionStats().then(setStats, (e) => setError(errText(e)));
  }, []);
  useEffect(load, [load]);

  const d = stats?.mcq.by_difficulty ?? {};
  return (
    <div className="grid grid-cols-1 gap-4">
      {error && <p className="text-sm text-bad">{error}</p>}
      <section aria-label="Bank statistics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="MCQ rows (file)" value={stats?.mcq.rows ?? "…"} icon={ListChecks} hint={stats ? `${d.easy ?? 0} easy · ${d.medium ?? 0} medium · ${d.hard ?? 0} hard` : undefined} />
        <Kpi label="Served to quizzes" value={stats?.mcq.served ?? "…"} icon={BookCheck} hint="own + open bank + contributions" />
        <Kpi label="MCQ topics" value={stats?.mcq.topics ?? "…"} icon={ListChecks} hint={stats ? `${stats.mcq.streams} streams · ${bytes(stats.mcq.bytes)}` : undefined} />
        <Kpi
          label="Interview questions"
          value={stats?.interview.questions ?? "…"}
          icon={MessagesSquare}
          hint={stats ? Object.entries(stats.interview.by_round).map(([k, v]) => `${v} ${k}`).join(" · ") : undefined}
        />
      </section>

      <CsvImporter
        kind={CSV_KINDS.mcq}
        title="MCQ bank · data/questions/mcq_bank.csv"
        icon={ListChecks}
        lead="Each row is checked like the quiz loader does: four distinct options, an answer letter A–D, a difficulty of easy, medium or hard and a usable question. Rows whose question already exists are counted as duplicates."
        columns="stream, domain, role, topic*, difficulty*, question*, option_a*, option_b*, option_c*, option_d*, correct_option*, explanation, bloom_level"
        onDone={load}
      />
      <CsvImporter
        kind={CSV_KINDS.interview}
        title="Interview bank · data/questions/open_interview.json"
        icon={MessagesSquare}
        lead="Open questions with model answers for mock interviews. The round comes from `round` (hr / technical) or `interview_type`; the source must be listed in data/questions/sources.json; text from forbidden sites is refused."
        columns="category, role, interview_type, difficulty, question*, key_evaluation_points, model_answer*, round, topic, source, licence"
        onDone={load}
      />

      <Panel title="Backups (data/.backups/)" icon={Archive} lead="Made automatically before every import; the newest five per file are kept. Restore one by copying it over the data file.">
        {stats?.backups.length ? (
          <ul className="grid gap-1 font-mono text-xs sm:grid-cols-2">
            {stats.backups.map((b) => (
              <li key={b.name} className="flex justify-between gap-3 rounded-lg border border-hair px-2.5 py-1.5">
                <span className="truncate">{b.name}</span>
                <span className="shrink-0 text-muted">{bytes(b.bytes)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">No backups yet.</p>
        )}
      </Panel>
    </div>
  );
}
