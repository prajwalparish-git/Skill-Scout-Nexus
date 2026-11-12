"use client";

// Career tracks from the live catalog (/api/catalog). Each role opens the resume builder for it.
import Link from "next/link";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowUpRight,
  Briefcase,
  Building2,
  Calculator,
  Cpu,
  FlaskConical,
  HardHat,
  HeartPulse,
  Landmark,
  Monitor,
  Plus,
  Scale,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { Catalog } from "@/lib/api";
import { SPRING } from "@/lib/site";
import { ErrorNote } from "@/components/ui";
import { trackSpotlight } from "@/components/site/Brand";
import { Reveal, SectionHead } from "./Reveal";

const ICONS: Record<string, LucideIcon> = {
  cs: Monitor,
  ece: Cpu,
  mech: Wrench,
  civil: HardHat,
  eee: Zap,
  biotech: FlaskConical,
  health: HeartPulse,
  commerce: Calculator,
  law: Scale,
  corp: Briefcase,
  govt_central: Landmark,
  govt_state: Building2,
};

export function Tracks({ catalog, error }: { catalog: Catalog | null; error: string | null }) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <section aria-labelledby="tracks-title" id="tracks" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <SectionHead
        id="tracks-title"
        eyebrow="Career tracks"
        title={
          <>
            Every stream,
            <span className="text-muted/80"> not just computer science.</span>
          </>
        }
        lead="Engineering, commerce, law, management, healthcare and government roles, each with its own topics, question bank and the keywords recruiters scan for."
      />

      {error && (
        <div className="mt-10 max-w-xl">
          <ErrorNote message={error} />
          <p className="mt-2 text-sm text-muted">The tracks load from the API; start server.py to see them.</p>
        </div>
      )}

      <div className="mt-14 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {!catalog &&
          !error &&
          Array.from({ length: 6 }, (_, i) => <div key={i} className="panel h-40 animate-pulse bg-surface/60" aria-hidden />)}

        {catalog?.domains.map((d, i) => {
          const Icon = ICONS[d.id] ?? Briefcase;
          const expanded = open === d.id;
          const questions = d.topics.reduce((m, t) => m + Object.values(t.bank).reduce((a, b) => a + b, 0), 0);
          return (
            <Reveal key={d.id} delay={(i % 3) * 0.05}>
              <article
                onMouseMove={trackSpotlight}
                className="panel spotlight flex h-full flex-col p-5 transition-colors hover:border-line"
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-xl border border-hair">
                    <Icon size={18} aria-hidden />
                  </span>
                  <span className="font-mono text-[11px] text-muted">
                    {d.roles.length} roles · {questions.toLocaleString()} q
                  </span>
                </div>
                <h3 className="mt-5 font-display text-xl font-semibold tracking-tight">{d.name}</h3>
                <p className="mt-1.5 line-clamp-2 text-sm text-muted">{d.description}</p>
                <button
                  type="button"
                  className="mt-4 inline-flex items-center gap-1.5 self-start text-sm font-medium text-ink"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : d.id)}
                >
                  <motion.span animate={{ rotate: expanded ? 45 : 0 }} transition={SPRING} className="inline-flex">
                    <Plus size={15} aria-hidden />
                  </motion.span>
                  {expanded ? "Hide roles" : "Show roles"}
                </button>
                <AnimatePresence initial={false}>
                  {expanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={SPRING}
                      className="overflow-hidden"
                    >
                      <ul className="mt-3 space-y-0.5 border-t border-hair pt-3">
                        {d.roles.map((r) => (
                          <li key={r.name}>
                            <Link
                              className="group flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-surface"
                              href={`/resume-builder?domain=${d.id}&role=${encodeURIComponent(r.name)}`}
                            >
                              {r.name}
                              <ArrowUpRight size={14} className="text-muted opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </motion.div>
                  )}
                </AnimatePresence>
              </article>
            </Reveal>
          );
        })}
      </div>
    </section>
  );
}
