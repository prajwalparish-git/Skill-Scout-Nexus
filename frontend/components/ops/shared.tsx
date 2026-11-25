"use client";

// Shared pieces of the developer console: panels, tables, KPI cards, formatters and an async
// button that shows its own progress and result.
import { useState } from "react";
import { Loader2, type LucideIcon } from "lucide-react";
import type { Row } from "@/lib/opsApi";

export const time = (v: unknown) => {
  if (v === null || v === undefined || v === "") return "—";
  const d =
    typeof v === "number"
      ? new Date(v * 1000)
      : new Date(String(v).includes("T") ? String(v) : String(v).replace(" ", "T") + (String(v).endsWith("Z") ? "" : "Z"));
  return isNaN(d.getTime())
    ? String(v)
    : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export const show = (v: unknown) =>
  v === null || v === undefined || v === "" ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "object" ? JSON.stringify(v) : String(v);

export const bytes = (n: number | undefined | null) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
};

export type Col = [key: string, label: string, render?: (r: Row) => React.ReactNode];

export function Table({ rows, cols, empty, minWidth = 640 }: { rows: Row[]; cols: Col[]; empty: string; minWidth?: number }) {
  if (!rows.length) return <p className="px-1 py-6 text-center text-sm text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs" style={{ minWidth }}>
        <thead>
          <tr className="border-b border-hair text-muted">
            {cols.map(([key, label]) => (
              <th key={key} scope="col" className="whitespace-nowrap px-2 py-2 font-medium">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-hair/60 align-top hover:bg-surface/40">
              {cols.map(([key, , render]) => (
                <td key={key} className="whitespace-nowrap px-2 py-1.5 font-mono">
                  {render ? render(r) : show(r[key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Panel({
  title,
  icon: Icon,
  children,
  right,
  lead,
}: {
  title: string;
  icon: LucideIcon;
  children: React.ReactNode;
  right?: React.ReactNode;
  lead?: React.ReactNode;
}) {
  return (
    <section className="card min-w-0" aria-label={title}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Icon size={15} aria-hidden /> {title}
          </h2>
          {lead && <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted">{lead}</p>}
        </div>
        {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
      </div>
      {children}
    </section>
  );
}

export function Kpi({ label, value, hint, icon: Icon }: { label: string; value: React.ReactNode; hint?: string; icon?: LucideIcon }) {
  return (
    <div className="card py-4">
      <p className="flex items-center gap-1.5 text-xs text-muted">
        {Icon && <Icon size={13} aria-hidden />}
        {label}
      </p>
      <p className="mt-1 font-mono text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-muted">{hint}</p>}
    </div>
  );
}

/** Definition list in two columns (system facts, sync state). */
export function Facts({ items }: { items: [string, unknown][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="break-all font-mono">{show(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A button running an async action: disabled while it runs, with an optional confirm prompt. */
export function ActionButton({
  onRun,
  children,
  icon: Icon,
  confirm,
  tone = "ghost",
  className = "",
  disabled,
}: {
  onRun: () => Promise<unknown>;
  children: React.ReactNode;
  icon?: LucideIcon;
  confirm?: string;
  tone?: "ghost" | "ink" | "danger";
  className?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const cls =
    tone === "ink" ? "btn-ink" : tone === "danger" ? "btn border border-bad/50 bg-bg text-bad hover:bg-bad/[0.06]" : "btn-ghost";
  return (
    <button
      type="button"
      disabled={busy || disabled}
      className={`${cls} min-h-[2.1rem] px-3.5 py-1.5 text-xs ${className}`}
      onClick={async () => {
        if (confirm && !window.confirm(confirm)) return;
        setBusy(true);
        try {
          await onRun();
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? <Loader2 size={13} className="animate-spin" aria-hidden /> : Icon ? <Icon size={13} aria-hidden /> : null}
      {children}
    </button>
  );
}

/** A one-line result under a set of actions. */
export function Notice({ note }: { note: { ok: boolean; text: string } | null }) {
  if (!note) return null;
  return (
    <p role="status" className={`mt-3 rounded-xl border px-3 py-2 text-xs ${note.ok ? "border-ok/40 text-ok" : "border-bad/40 text-bad"}`}>
      {note.text}
    </p>
  );
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
