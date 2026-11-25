"use client";

// Building blocks of the documentation hub: copyable code blocks, callouts, tables and steps,
// in the site's hairline / mono language. Every code, CSV and command block has a copy button.
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Copy, Info, Lightbulb, ShieldCheck, type LucideIcon } from "lucide-react";

export type DocSection = {
  id: string;
  title: string;
  /** One line under the title, also searched. */
  summary: string;
  /** Extra words the search should find this section by. */
  keywords: string;
  body: React.ReactNode;
};

export type Guide = {
  id: "individual" | "organizations" | "developers";
  label: string;
  short: string;
  lead: string;
  sections: DocSection[];
};

/** Copies `text`; falls back to a hidden textarea where the Clipboard API is unavailable
 * (a plain-http address other than localhost). */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the textarea */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

export function CopyButton({ text, label = "Copy", className = "" }: { text: string; label?: string; className?: string }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <button
      type="button"
      onClick={async () => {
        setState((await copyText(text)) ? "done" : "failed");
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setState("idle"), 1800);
      }}
      className={`inline-flex items-center gap-1.5 rounded-full border border-hair bg-bg/80 px-2.5 py-1 font-mono text-[11px] text-muted transition-colors hover:border-line hover:text-ink ${className}`}
      aria-label={state === "done" ? "Copied" : `${label} to clipboard`}
    >
      {state === "done" ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
      <span aria-live="polite">{state === "done" ? "Copied" : state === "failed" ? "Select & copy" : label}</span>
    </button>
  );
}

/** A code, CSV or command block with its language label and a copy button. */
export function CodeBlock({ code, lang = "bash", title }: { code: string; lang?: string; title?: string }) {
  const text = code.replace(/^\n+|\s+$/g, "");
  return (
    <figure className="group my-4 overflow-hidden rounded-2xl border border-hair bg-surface/50">
      <figcaption className="flex items-center justify-between gap-3 border-b border-hair px-4 py-2">
        <span className="truncate font-mono text-[11px] uppercase tracking-[0.14em] text-muted">{title ?? lang}</span>
        <CopyButton text={text} />
      </figcaption>
      <pre className="overflow-x-auto px-4 py-3.5 font-mono text-[12.5px] leading-relaxed text-ink">
        <code>{text}</code>
      </pre>
    </figure>
  );
}

/** Inline code. */
export function C({ children }: { children: React.ReactNode }) {
  return <code className="rounded-md border border-hair bg-surface/70 px-1.5 py-0.5 font-mono text-[0.85em] text-ink">{children}</code>;
}

const TONES: Record<string, { icon: LucideIcon; cls: string }> = {
  info: { icon: Info, cls: "border-info/30 bg-info/[0.04]" },
  tip: { icon: Lightbulb, cls: "border-ok/30 bg-ok/[0.04]" },
  warn: { icon: AlertTriangle, cls: "border-warn/40 bg-warn/[0.05]" },
  privacy: { icon: ShieldCheck, cls: "border-primary/30 bg-primary/[0.04]" },
};

export function Callout({ tone = "info", title, children }: { tone?: keyof typeof TONES; title: string; children: React.ReactNode }) {
  const { icon: Icon, cls } = TONES[tone];
  return (
    <aside className={`my-4 rounded-2xl border px-4 py-3.5 ${cls}`}>
      <p className="flex items-center gap-2 text-sm font-semibold text-ink">
        <Icon size={15} aria-hidden /> {title}
      </p>
      <div className="mt-1.5 text-sm leading-relaxed text-muted">{children}</div>
    </aside>
  );
}

/** A numbered walkthrough. */
export function Steps({ items }: { items: { title: string; body: React.ReactNode }[] }) {
  return (
    <ol className="my-4 space-y-3">
      {items.map((s, i) => (
        <li key={s.title} className="flex gap-3">
          <span
            className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-line font-mono text-[11px] font-semibold text-ink"
            aria-hidden
          >
            {i + 1}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">{s.title}</p>
            <div className="mt-0.5 text-sm leading-relaxed text-muted">{s.body}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function DataTable({ head, rows, mono = 0 }: { head: string[]; rows: React.ReactNode[][]; mono?: number }) {
  return (
    <div className="my-4 overflow-x-auto rounded-2xl border border-hair">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="bg-surface/60">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="whitespace-nowrap px-3.5 py-2.5 font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-hair align-top">
              {r.map((cell, j) => (
                <td key={j} className={`px-3.5 py-2.5 ${j < mono ? "whitespace-nowrap font-mono text-[12.5px] text-ink" : "text-muted"}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-7 font-display text-lg font-semibold tracking-tight text-ink">{children}</h3>;
}

export function P({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 text-[15px] leading-relaxed text-muted">{children}</p>;
}

export function List({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="mt-3 space-y-1.5 text-[15px] leading-relaxed text-muted">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="mt-[0.6rem] h-1 w-1 shrink-0 rounded-full bg-line" aria-hidden />
          <span className="min-w-0">{it}</span>
        </li>
      ))}
    </ul>
  );
}

/** A link to a page of the app, shown with its path. */
export function Route({ href, children }: { href: string; children?: React.ReactNode }) {
  return (
    <a href={href} className="font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink">
      {children ?? href}
    </a>
  );
}
