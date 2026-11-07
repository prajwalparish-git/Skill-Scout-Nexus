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
  type LucideIcon,
} from "lucide-react";
import { useCandidate } from "@/lib/candidate";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Home", icon: Home },
  { href: "/resume-builder", label: "Resume builder", icon: FileText },
  { href: "/quiz", label: "Quiz", icon: ListChecks },
  { href: "/interview", label: "Interview", icon: MessagesSquare },
  { href: "/plan", label: "Plan", icon: CalendarDays },
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { students, candidate, choose, error } = useCandidate();

  return (
    <div className="min-h-screen lg:flex">
      <aside className="border-b border-hair bg-surface lg:sticky lg:top-0 lg:h-screen lg:w-60 lg:shrink-0 lg:border-b-0 lg:border-r">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 lg:block lg:px-5 lg:py-6">
          <Link href="/" className="text-lg font-semibold text-primary-ink">
            Skill Scout Nexus
          </Link>
          <nav aria-label="Pages" className="flex flex-wrap gap-1 lg:mt-6 lg:flex-col">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? path === "/" : path.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm ${
                    active ? "bg-hair font-medium text-ink" : "text-muted hover:bg-hair/60 hover:text-ink"
                  }`}
                >
                  <Icon size={16} aria-hidden />
                  <span className={active ? "" : "hidden sm:inline"}>{label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="w-full sm:w-auto lg:mt-8">
            <label htmlFor="candidate" className="label text-xs text-muted">
              Candidate
            </label>
            <select
              id="candidate"
              className="input max-w-full sm:w-56"
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
            {candidate && (
              <p className="mt-2 text-xs text-muted">
                Readiness <span className="font-semibold text-ink">{candidate.readiness_score}/100</span>
              </p>
            )}
            {error && <p className="mt-2 text-xs text-bad">{error}</p>}
          </div>
        </div>
      </aside>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-8">{children}</main>
    </div>
  );
}
