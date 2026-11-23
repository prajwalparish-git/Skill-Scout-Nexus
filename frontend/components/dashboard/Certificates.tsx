"use client";

import { useEffect, useRef, useState } from "react";
import { Award, CloudUpload, ExternalLink, Trash2, Upload } from "lucide-react";
import { API, get, post, upload, type Certificate } from "@/lib/api";
import { Badge, Empty, ErrorNote } from "@/components/ui";
import { useDrive } from "@/lib/drive";

const MAX_BYTES = 5 * 1024 * 1024; // the server's limit (piq/config.py CERTIFICATE_MAX_BYTES)
const TEXT_MAX = 120;

const shortDate = (iso: string) =>
  new Date(iso.length === 10 ? `${iso}T00:00:00` : iso.replace(" ", "T") + (iso.endsWith("Z") ? "" : "Z")).toLocaleDateString(
    undefined,
    { day: "numeric", month: "short", year: "numeric" },
  );

const size = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`);

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** The student's certificate PDFs as cards, with an upload form. Checks here are for quick
 * feedback only; the API checks the file (PDF by its first bytes, at most 5 MB) itself. */
export function Certificates({ candidateId }: { candidateId: string }) {
  const [items, setItems] = useState<Certificate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [drive] = useDrive(candidateId);
  const form = useRef<HTMLFormElement>(null);

  useEffect(() => {
    setItems(null);
    setError(null);
    let current = true; // a reply for a previous student must not land on this one
    get<Certificate[]>(`/api/certificates/${candidateId}`).then(
      (list) => current && setItems(list),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [candidateId]);

  async function onUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const file = data.get("file");
    if (!(file instanceof File) || !file.name) return setError("Choose a PDF file to upload.");
    if (!file.name.toLowerCase().endsWith(".pdf")) return setError("Upload a PDF file (its name must end in .pdf).");
    if (file.size > MAX_BYTES) return setError("A certificate can be at most 5 MB.");
    if (!data.get("issue_date")) data.delete("issue_date");
    setBusy(true);
    setError(null);
    try {
      const added = await upload<Certificate>(`/api/certificates/${candidateId}`, data);
      setItems((prev) => [added, ...(prev ?? [])]);
      form.current?.reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(c: Certificate) {
    if (!window.confirm(`Delete "${c.title}"? This cannot be undone.`)) return;
    setDeleting(c.id);
    setError(null);
    try {
      setItems(await post<Certificate[]>(`/api/certificates/${candidateId}/${c.id}/delete`, {}));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  async function onRetryDrive(c: Certificate) {
    setRetrying(c.id);
    setError(null);
    try {
      const r = await post<{ in_drive: boolean }>(`/api/drive/certificates/${c.id}/retry`, {});
      if (!r.in_drive) setError("Google Drive did not take it. Try again later.");
      setItems((prev) => prev?.map((x) => (x.id === c.id ? { ...x, in_drive: r.in_drive } : x)) ?? prev);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRetrying(null);
    }
  }

  return (
    <section className="card mt-6" aria-labelledby="dash-certificates">
      <h2 id="dash-certificates" className="h2">
        Your certificates
      </h2>
      <p className="mt-1 text-xs text-muted">PDFs only, up to 5 MB each. Only you can see them.</p>

      <form ref={form} onSubmit={onUpload} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto]">
        <div>
          <label className="label" htmlFor="cert-title">
            Title
          </label>
          <input id="cert-title" name="title" className="input" required maxLength={TEXT_MAX} placeholder="e.g. AWS Cloud Practitioner" />
        </div>
        <div>
          <label className="label" htmlFor="cert-issuer">
            Issued by
          </label>
          <input id="cert-issuer" name="issuer" className="input" required maxLength={TEXT_MAX} placeholder="e.g. Amazon Web Services" />
        </div>
        <div>
          <label className="label" htmlFor="cert-date">
            Issue date <span className="font-normal text-muted">(optional)</span>
          </label>
          <input id="cert-date" name="issue_date" type="date" className="input" max={today()} />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="cert-file">
            Certificate PDF
          </label>
          <input id="cert-file" name="file" type="file" accept="application/pdf,.pdf" required className="input py-2" />
        </div>
        <div className="flex items-end">
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            <Upload size={16} aria-hidden /> {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
      </form>

      <ErrorNote message={error} />

      <div className="mt-5">
        {items === null ? (
          !error && <p className="text-sm text-muted">Loading your certificates…</p>
        ) : items.length === 0 ? (
          <Empty icon={Award}>No certificates yet. Upload one above and it shows up here.</Empty>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((c) => (
              <li key={c.id} className="flex flex-col rounded-2xl border border-hair p-4">
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-hair bg-surface" aria-hidden>
                    <Award size={16} />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-semibold" title={c.title}>
                      {c.title}
                    </p>
                    <p className="truncate text-sm text-muted" title={c.issuer}>
                      {c.issuer}
                      {c.issue_date ? ` · ${shortDate(c.issue_date)}` : ""}
                    </p>
                  </div>
                </div>
                <p className="mt-3 truncate font-mono text-xs text-muted" title={c.filename}>
                  {c.filename} · {size(c.size_bytes)}
                </p>
                {drive.connected && (
                  <div className="mt-2">
                    {c.in_drive ? (
                      <Badge state="ok">In Drive</Badge>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onRetryDrive(c)}
                        disabled={retrying === c.id}
                        className="btn-ghost min-h-0 px-3 py-1 text-xs"
                      >
                        <CloudUpload size={13} aria-hidden /> {retrying === c.id ? "Copying…" : "Retry Drive"}
                      </button>
                    )}
                  </div>
                )}
                <div className="mt-3 flex gap-2">
                  <a
                    href={`${API}/api/certificates/${candidateId}/${c.id}/file`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-ghost min-h-0 flex-1 px-3 py-1.5"
                  >
                    <ExternalLink size={14} aria-hidden /> View
                  </a>
                  <button
                    type="button"
                    onClick={() => onDelete(c)}
                    disabled={deleting === c.id}
                    className="btn-ghost min-h-0 px-3 py-1.5 text-bad"
                    aria-label={`Delete ${c.title}`}
                  >
                    <Trash2 size={14} aria-hidden /> {deleting === c.id ? "Deleting…" : "Delete"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
