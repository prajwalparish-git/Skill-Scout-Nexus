"use client";

import { useState } from "react";
import { Check, Loader2, Target, X } from "lucide-react";
import { post, type Tailoring } from "@/lib/api";
import { Badge, ErrorNote } from "@/components/ui";
import { ResumePreview } from "./Preview";

const JD_MIN = 80;
const JD_MAX = 6000;

/** Tailor to a job description: what would change is shown first, and applied only on Accept.
 * Signed-in students only (it runs an AI agent); nothing is saved, the description included. */
export function TailorPanel({
  body,
  signedIn,
  onAccept,
}: {
  body: Record<string, unknown>;
  signedIn: boolean;
  onAccept: (t: Tailoring) => void;
}) {
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Tailoring | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function tailor() {
    setBusy(true);
    setError(null);
    try {
      setDraft(await post<Tailoring>("/api/resume/tailor", { ...body, job_description: jd }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="tailor-title">
      <h2 id="tailor-title" className="flex items-center gap-2 font-semibold">
        <Target size={16} aria-hidden /> Tailor to a job description
      </h2>
      <p className="mt-1 text-sm text-muted">
        Paste the job&apos;s description. Your summary is rewritten and your bullets reordered and reworded to fit it, never adding
        experience, skills or numbers you did not write. Nothing changes until you accept, and the description is not saved.
      </p>
      {!signedIn ? (
        <p className="mt-3 text-sm text-muted">Sign in to tailor your resume.</p>
      ) : (
        <>
          <label htmlFor="tailor-jd" className="label mt-3">
            Job description
          </label>
          <textarea id="tailor-jd" className="input min-h-32" maxLength={JD_MAX} value={jd} onChange={(e) => setJd(e.target.value)} />
          <p className="mt-1 text-xs text-muted">
            {jd.trim().length < JD_MIN ? `At least ${JD_MIN} characters.` : `${jd.length.toLocaleString()} of ${JD_MAX.toLocaleString()} characters.`}
          </p>
          <button type="button" className="btn-primary mt-3" disabled={busy || jd.trim().length < JD_MIN} onClick={tailor}>
            {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Target size={16} aria-hidden />} Tailor my resume
          </button>
        </>
      )}
      <ErrorNote message={error} />
      {draft && (
        <div className="mt-5 space-y-4 border-t border-hair pt-4" aria-live="polite">
          <div>
            <h3 className="text-sm font-semibold">What would change</h3>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
              {(draft.changes.length ? draft.changes : ["Nothing: your resume already fits this job's order."]).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
          {draft.matched_keywords.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold">The job asks for, and your resume shows</h3>
              <div className="mt-1 flex flex-wrap gap-1">
                {draft.matched_keywords.map((k) => (
                  <Badge key={k} state="ok">
                    {k}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {draft.missing_keywords.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold">The job asks for, and your resume does not show</h3>
              <p className="text-xs text-muted">Add one only if you can back it up; nothing was added for you.</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {draft.missing_keywords.map((k) => (
                  <Badge key={k} state="todo">
                    {k}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          <div className="max-h-96 overflow-y-auto rounded-xl">
            <ResumePreview layout={draft.layout} />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                onAccept(draft);
                setDraft(null);
              }}
            >
              <Check size={16} aria-hidden /> Accept the tailoring
            </button>
            <button type="button" className="btn-ghost" onClick={() => setDraft(null)}>
              <X size={16} aria-hidden /> Discard
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
