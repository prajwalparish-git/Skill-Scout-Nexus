"use client";

// One CSV-managed data file: download the template or the current data, upload, dry-run preview
// (counts, sample, errors), choose the mode, commit. The backend backs the old file up first.
import { useRef, useState } from "react";
import { CheckCircle2, Download, FileSpreadsheet, FileUp, Loader2, RotateCcw, Upload, type LucideIcon } from "lucide-react";
import { opsApi, type CsvKind, type CsvSummary } from "@/lib/opsApi";
import { ActionButton, Notice, errText, show } from "./shared";

const MODE_HELP: Record<string, string> = {
  append: "adds the new valid rows; duplicates are skipped",
  merge: "adds new rows and updates matching ones",
  replace: "the file becomes exactly the valid rows of this upload",
};

export function CsvImporter({
  kind,
  title,
  lead,
  columns,
  icon: Icon = FileSpreadsheet,
  onDone,
}: {
  kind: CsvKind;
  title: string;
  lead: React.ReactNode;
  columns: string;
  icon?: LucideIcon;
  onDone?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<string>(kind.modes[0]);
  const [preview, setPreview] = useState<CsvSummary | null>(null);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    if (input.current) input.current.value = "";
  };

  async function runPreview(f: File, m: string) {
    setBusy("preview");
    setNote(null);
    try {
      setPreview(await opsApi.csvPreview(kind, f, m));
    } catch (e) {
      setPreview(null);
      setNote({ ok: false, text: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function commit() {
    if (!file || !preview) return;
    if (mode === "replace" && !window.confirm(`Replace the whole file with the ${preview.valid_count} valid rows of this upload? A backup is kept.`)) return;
    setBusy("import");
    try {
      const r = await opsApi.csvImport(kind, file, mode);
      setNote({ ok: true, text: `Imported ${r.imported ?? r.valid_count} row(s) (${mode}). Backup: ${r.backup ?? "none (new file)"}. Caches cleared.` });
      reset();
      onDone?.();
    } catch (e) {
      setNote({ ok: false, text: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  const sampleCols = preview?.sample_valid[0] ? Object.keys(preview.sample_valid[0]).slice(0, 6) : [];

  return (
    <section className="card min-w-0" aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-2xl">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Icon size={15} aria-hidden /> {title}
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-muted">{lead}</p>
          <p className="mt-2 break-words font-mono text-[11px] text-muted">{columns}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton icon={Download} onRun={() => opsApi.csvTemplate(kind).catch((e) => setNote({ ok: false, text: errText(e) }))}>
            Template
          </ActionButton>
          {kind.exportable && (
            <ActionButton icon={FileSpreadsheet} onRun={() => opsApi.csvExport(kind).catch((e) => setNote({ ok: false, text: errText(e) }))}>
              Export current
            </ActionButton>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-dashed border-line p-3">
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          id={`csv-${kind.key}`}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            setPreview(null);
            if (f) void runPreview(f, mode);
          }}
        />
        <label htmlFor={`csv-${kind.key}`} className="btn-ghost min-h-[2.1rem] cursor-pointer px-3.5 py-1.5 text-xs">
          <FileUp size={13} aria-hidden /> {file ? "Choose another file" : "Choose CSV"}
        </label>
        <span className="min-w-0 truncate font-mono text-xs text-muted">{file ? `${file.name} · ${(file.size / 1024).toFixed(1)} KB` : "UTF-8 CSV, up to 10 MB"}</span>
        <div className="segmented ml-auto" role="radiogroup" aria-label="Import mode">
          {kind.modes.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              className={`segment px-3 py-1 text-xs capitalize ${mode === m ? "bg-ink text-bg hover:text-bg" : ""}`}
              onClick={() => {
                setMode(m);
                if (file) void runPreview(file, m);
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1.5 text-[11px] text-muted">
        <span className="font-medium capitalize text-ink">{mode}</span>: {MODE_HELP[mode]}.
      </p>

      {busy === "preview" && (
        <p className="mt-3 flex items-center gap-2 text-xs text-muted">
          <Loader2 size={13} className="animate-spin" aria-hidden /> Checking every row (dry run, nothing is written)…
        </p>
      )}

      {preview && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Rows", preview.total_rows, ""],
              ["Valid", preview.valid_count, "text-ok"],
              ["Duplicates", preview.duplicate_count, preview.duplicate_count ? "text-warn" : ""],
              ["Invalid", preview.invalid_count, preview.invalid_count ? "text-bad" : ""],
            ].map(([label, value, cls]) => (
              <div key={String(label)} className="rounded-xl border border-hair px-3 py-2">
                <p className="text-[11px] text-muted">{label}</p>
                <p className={`font-mono text-lg font-semibold tabular-nums ${cls}`}>{value}</p>
              </div>
            ))}
          </div>
          {typeof preview.updated_count === "number" && preview.updated_count > 0 && (
            <p className="text-xs text-muted">{preview.updated_count} valid row(s) update an existing entry.</p>
          )}
          {preview.warnings.length > 0 && (
            <ul className="space-y-1 rounded-xl border border-warn/40 bg-warn/[0.04] p-3 text-xs text-warn">
              {preview.warnings.slice(0, 8).map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          {preview.errors.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-bad/30">
              <table className="w-full min-w-[480px] text-left text-xs">
                <thead className="bg-bad/[0.04] text-bad">
                  <tr>
                    <th scope="col" className="px-2 py-1.5 font-medium">Line</th>
                    <th scope="col" className="px-2 py-1.5 font-medium">Problem</th>
                    <th scope="col" className="px-2 py-1.5 font-medium">Row</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.errors.map((e) => (
                    <tr key={`${e.line}-${e.error}`} className="border-t border-hair">
                      <td className="px-2 py-1 font-mono">{e.line}</td>
                      <td className="px-2 py-1">{e.error}</td>
                      <td className="max-w-[22rem] truncate px-2 py-1 font-mono text-muted">{e.question || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {sampleCols.length > 0 && (
            <details className="rounded-xl border border-hair">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium">First valid rows</summary>
              <div className="overflow-x-auto border-t border-hair">
                <table className="w-full min-w-[560px] text-left text-[11px]">
                  <thead>
                    <tr className="text-muted">
                      {sampleCols.map((c) => (
                        <th key={c} scope="col" className="px-2 py-1.5 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample_valid.map((r, i) => (
                      <tr key={i} className="border-t border-hair/60">
                        {sampleCols.map((c) => (
                          <td key={c} className="max-w-[16rem] truncate px-2 py-1 font-mono">
                            {show(r[c])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn-ink min-h-[2.1rem] px-4 py-1.5 text-xs" disabled={!preview.valid_count || busy !== null} onClick={commit}>
              {busy === "import" ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <Upload size={13} aria-hidden />}
              Commit {preview.valid_count} row(s) · {mode}
            </button>
            <button type="button" className="btn-ghost min-h-[2.1rem] px-3.5 py-1.5 text-xs" onClick={reset} disabled={busy !== null}>
              <RotateCcw size={13} aria-hidden /> Discard
            </button>
            {!preview.valid_count && <span className="text-xs text-muted">Nothing new to import.</span>}
          </div>
        </div>
      )}
      {note && (
        <div className="flex items-start gap-2">
          {note.ok && <CheckCircle2 size={14} className="mt-4 text-ok" aria-hidden />}
          <div className="flex-1">
            <Notice note={note} />
          </div>
        </div>
      )}
    </section>
  );
}
