"use client";

// The "Question sources & credits" list: every source in data/questions/sources.json with its
// licence, attribution, pinned version and what we changed (GET /api/question-sources).
import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { get, type QuestionSources } from "@/lib/api";

export function CreditsList() {
  const [data, setData] = useState<QuestionSources | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<QuestionSources>("/api/question-sources").then(setData, (e: Error) => setError(e.message));
  }, []);

  if (error) return <p role="alert">Could not load the sources: {error}</p>;
  if (!data) return <p>Loading the sources…</p>;
  return (
    <div className="space-y-6">
      <p>{data.general_practice_note}</p>
      {data.sources.map((s) => (
        <section key={s.key} className="rounded-card border border-hair p-4" aria-labelledby={`src-${s.key}`}>
          <h3 id={`src-${s.key}`} className="font-semibold text-ink">
            {s.name}
          </h3>
          <p className="mt-1 text-sm">
            Licence:{" "}
            {s.licence_url ? (
              <a href={s.licence_url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                {s.licence_name}
              </a>
            ) : (
              s.licence_name
            )}
            {" · "}
            {s.multiple_choice.toLocaleString()} multiple-choice and {s.interview} interview questions in use
          </p>
          <p className="mt-2 text-sm">{s.attribution}</p>
          {s.modifications.length > 0 && (
            <p className="mt-2 text-sm">
              <strong>Modified:</strong> {s.modifications.join("; ")}.
            </p>
          )}
          {s.homepage && (
            <p className="mt-2 text-sm">
              <a href={s.homepage} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline underline-offset-2">
                Source repository <ExternalLink size={12} aria-hidden />
              </a>
              {s.commit && <span className="ml-2 font-mono text-xs">pinned at {s.commit.slice(0, 12)}</span>}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}
