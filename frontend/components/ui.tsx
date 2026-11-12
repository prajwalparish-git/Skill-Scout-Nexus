import Link from "next/link";
import { AlertTriangle, CheckCircle2, Circle, Info, ListChecks, UserRound, XCircle, type LucideIcon } from "lucide-react";
import { SignInPrompt } from "./site/auth";

/** The top of every tool page: a small eyebrow, the title in the display face, a lead and actions. */
export function PageHeader({
  title,
  lead,
  eyebrow,
  actions,
}: {
  title: string;
  lead: string;
  eyebrow?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="relative mb-8 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <p className="eyebrow mb-3">{eyebrow}</p>}
        <h1 className="h1">{title}</h1>
        <p className="lead">{lead}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

type State = "ok" | "warn" | "bad" | "info" | "todo";
const STATES: Record<State, { icon: LucideIcon; cls: string }> = {
  ok: { icon: CheckCircle2, cls: "border-ok/40 text-ok" },
  warn: { icon: AlertTriangle, cls: "border-warn/40 text-warn" },
  bad: { icon: XCircle, cls: "border-bad/40 text-bad" },
  info: { icon: Info, cls: "border-info/40 text-info" },
  todo: { icon: Circle, cls: "border-line text-muted" },
};

/** A status always shows an icon and words, never colour alone. */
export function Badge({ state, children }: { state: State; children: React.ReactNode }) {
  const { icon: Icon, cls } = STATES[state];
  return (
    <span className={`chip ${cls}`}>
      <Icon size={12} aria-hidden />
      {children}
    </span>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-3 flex items-start gap-2 rounded-2xl border border-bad/40 bg-bad/[0.04] px-4 py-3 text-sm text-bad">
      <XCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
      {message}
    </p>
  );
}

export function Empty({ children, icon: Icon }: { children: React.ReactNode; icon?: LucideIcon }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[1.25rem] border border-dashed border-line px-6 py-10 text-center text-sm text-muted">
      {Icon && (
        <span className="grid h-11 w-11 place-items-center rounded-full border border-hair bg-surface text-ink" aria-hidden>
          <Icon size={18} />
        </span>
      )}
      <div className="max-w-md">{children}</div>
    </div>
  );
}

/** Shown by tool pages that need a profile. */
export function NeedsCandidate() {
  return (
    <div className="surface-light flex flex-col items-center gap-4 rounded-[1.5rem] border border-hair px-6 py-14 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-full border border-hair bg-bg text-ink shadow-sm" aria-hidden>
        <UserRound size={24} />
      </span>
      <div className="max-w-md">
        <h2 className="h2">Sign in to see your own progress</h2>
        <p className="mt-2 text-sm text-muted">
          Choose your profile to continue. New students create an account in the main app (sign up, then upload a
          resume), or choose a candidate in the menu.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        <SignInPrompt />
        <Link href="/quiz" className="btn-ghost mt-4">
          <ListChecks size={16} aria-hidden /> Try a quiz as a guest
        </Link>
      </div>
    </div>
  );
}

/** A key number: a small label over a large mono value, with an optional hint. */
export function Stat({ label, value, hint, icon: Icon }: { label: string; value: React.ReactNode; hint?: string; icon?: LucideIcon }) {
  return (
    <div className="card flex flex-col gap-1 py-4 sm:py-5">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted">
        {Icon && <Icon size={14} aria-hidden />}
        {label}
      </p>
      <p className="font-mono text-2xl font-semibold tabular-nums tracking-tight text-ink sm:text-3xl">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** A progress ring with its number in the middle (0..max). The number is also given in words. */
export function Ring({
  value,
  max = 100,
  size = 96,
  label,
  suffix,
}: {
  value: number;
  max?: number;
  size?: number;
  label: string;
  suffix?: string;
}) {
  const r = 40;
  const c = 2 * Math.PI * r;
  const share = Math.max(0, Math.min(1, value / max));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${label}: ${value} of ${max}`}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="50" cy="50" r={r} fill="none" strokeWidth="8" className="stroke-hair" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          strokeWidth="8"
          strokeLinecap="round"
          className="stroke-ink transition-[stroke-dashoffset] duration-700"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - share)}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-mono font-semibold tabular-nums text-ink" style={{ fontSize: size / 4.2 }} aria-hidden>
        {value}
        {suffix && <span className="sr-only">{suffix}</span>}
      </span>
    </div>
  );
}

/** Grey placeholder blocks while data loads. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-xl bg-surface ${className}`} />;
}

export function Loading({ label }: { label: string }) {
  return (
    <div role="status" className="space-y-4">
      <span className="sr-only">{label}</span>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}
