"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays,
  FileText,
  Gauge,
  Home,
  ListChecks,
  MessagesSquare,
  Repeat2,
  type LucideIcon,
} from "lucide-react";
import { useCandidate } from "@/lib/candidate";
import { useAuth } from "./site/auth";
import { Brand } from "./site/Brand";
import { SiteFooter } from "./site/Footer";
import { SiteNav } from "./site/Nav";
import { SmoothScroll } from "./site/SmoothScroll";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/resume-builder", label: "Resume builder", icon: FileText },
  { href: "/quiz", label: "Quiz", icon: ListChecks },
  { href: "/interview", label: "Mock interview", icon: MessagesSquare },
  { href: "/plan", label: "Study plan", icon: CalendarDays },
];

/** Public pages: the floating top bar, full-bleed content and the footer, no app sidebar. */
const PUBLIC = new Set(["/", "/organizations", "/privacy", "/terms", "/cookies"]);

const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

/** The signed-in profile: who, readiness, and the controls to switch. */
function ProfileCard({ selectId }: { selectId: string }) {
  const { students, candidate, choose, error } = useCandidate();
  const { open } = useAuth();
  return (
    <div className="rounded-2xl border border-hair bg-bg p-3 shadow-[0_1px_2px_rgb(var(--ink)/0.04)]">
      {candidate ? (
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ink font-mono text-xs font-semibold text-bg" aria-hidden>
            {initials(candidate.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{candidate.name}</p>
            <p className="truncate font-mono text-[11px] text-muted">@{candidate.username}</p>
          </div>
        </div>
      ) : (
        <p className="text-sm font-medium">Guest</p>
      )}
      {candidate && (
        <div className="mt-3">
          <div className="flex justify-between text-xs text-muted">
            <span>Readiness</span>
            <span className="font-mono font-semibold text-ink tabular-nums">{candidate.readiness_score}/100</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-hair" aria-hidden>
            <div className="h-full rounded-full bg-ink" style={{ width: `${candidate.readiness_score}%` }} />
          </div>
        </div>
      )}
      <label htmlFor={selectId} className="mt-3 block text-xs font-medium text-muted">
        Profile
      </label>
      <select
        id={selectId}
        className="input mt-1 py-2 text-xs"
        value={candidate?.id ?? ""}
        onChange={(e) => choose(e.target.value || null)}
      >
        <option value="">Guest (nothing saved)</option>
        {students.map((s) => (
          <option key={s.id} value={s.id}>
            @{s.username} · {s.name}
          </option>
        ))}
      </select>
      <button type="button" className="btn-ghost mt-2 min-h-[2.25rem] w-full py-1.5 text-xs" onClick={() => open("signin")}>
        <Repeat2 size={14} aria-hidden /> Switch profile
      </button>
      {error && (
        <p role="alert" className="mt-2 text-xs text-bad">
          {error}
        </p>
      )}
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();

  if (PUBLIC.has(path))
    return (
      <>
        <SmoothScroll />
        <SiteNav />
        <main id="main-content" tabIndex={-1} className="focus:outline-none">
          {children}
        </main>
        <SiteFooter />
      </>
    );

  return (
    <>
      <div className="min-h-screen lg:flex">
        <header className="sticky top-0 z-40 border-b border-hair bg-bg/85 backdrop-blur-xl lg:h-screen lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r lg:bg-surface/50">
          <div className="flex flex-col gap-3 px-4 py-3 lg:h-full lg:gap-0 lg:px-4 lg:py-6">
            <div className="flex items-center justify-between gap-3">
              <Link href="/" className="rounded-lg text-ink" aria-label="Skill Scout Nexus, home">
                <Brand height={12} />
              </Link>
              <Link href="/" className="flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted hover:text-ink lg:hidden">
                <Home size={14} aria-hidden /> Home
              </Link>
            </div>
            <nav aria-label="Pages" className="-mx-1 overflow-x-auto lg:mx-0 lg:mt-8 lg:overflow-visible">
              <p className="eyebrow mb-2 hidden px-3 lg:block">Tools</p>
              <ul className="flex gap-1 px-1 lg:flex-col lg:px-0">
                {NAV.map(({ href, label, icon: Icon }) => {
                  const active = path.startsWith(href);
                  return (
                    <li key={href}>
                      <Link
                        href={href}
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm transition-colors ${
                          active
                            ? "border border-hair bg-bg font-semibold text-ink shadow-[0_1px_2px_rgb(var(--ink)/0.06)]"
                            : "border border-transparent text-muted hover:bg-bg/70 hover:text-ink"
                        }`}
                      >
                        <Icon size={16} aria-hidden />
                        {label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
              <Link
                href="/"
                className="mt-1 hidden items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-muted hover:bg-bg/70 hover:text-ink lg:flex"
              >
                <Home size={16} aria-hidden /> Home page
              </Link>
            </nav>
            <div className="hidden lg:mt-auto lg:block">
              <ProfileCard selectId="candidate" />
            </div>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="relative min-w-0 flex-1 focus:outline-none">
          <div aria-hidden className="surface-light pointer-events-none absolute inset-x-0 top-0 h-72" />
          <div className="relative mx-auto w-full max-w-6xl px-4 py-8 sm:px-8 sm:py-12">
            <div className="mb-6 lg:hidden">
              <ProfileCard selectId="candidate-mobile" />
            </div>
            {children}
          </div>
        </main>
      </div>
      <SiteFooter />
    </>
  );
}
