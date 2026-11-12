"use client";

// The study loop: quiz scores raise or lower a topic's weakness, and the plan follows.
import { motion } from "motion/react";
import { ArrowRight, Check } from "lucide-react";
import { SPRING } from "@/lib/site";
import { ToolLink } from "@/components/site/auth";
import { Reveal, SectionHead } from "./Reveal";

const WEEK = [
  { day: "Mon", topic: "Operating systems", sub: "Scheduling, deadlocks", min: 45, done: true },
  { day: "Tue", topic: "DBMS", sub: "Indexing, normal forms", min: 40, done: true },
  { day: "Wed", topic: "Operating systems", sub: "Memory, paging", min: 45, done: true },
  { day: "Thu", topic: "Computer networks", sub: "TCP, routing", min: 35, done: false },
  { day: "Fri", topic: "Data structures", sub: "Trees, heaps", min: 30, done: false },
];

const WEAKNESS: [string, number, number][] = [
  ["Operating systems", 0.62, 0.41],
  ["DBMS", 0.55, 0.38],
  ["Networks", 0.3, 0.27],
];

export function StudyHub() {
  return (
    <section aria-labelledby="study-title" id="study" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-[1fr_1.15fr] lg:gap-16">
        <div>
          <SectionHead
            id="study-title"
            eyebrow="Study hub"
            title={
              <>
                A plan that reads
                <span className="text-muted/80"> your scores.</span>
              </>
            }
            lead="Every quiz moves a topic's weakness up or down. The weekly plan gives the weakest topics more days, with a goal for each one, and moves on when you tick a day off."
          />
          <Reveal delay={0.1} className="mt-8 flex flex-wrap gap-3">
            <ToolLink href="/plan" className="btn-ink group h-11 px-6">
              Open your plan
              <ArrowRight size={16} className="transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
            </ToolLink>
            <ToolLink href="/quiz" className="btn-hair h-11 px-6">
              Practise a topic
            </ToolLink>
          </Reveal>
        </div>

        <Reveal delay={0.05}>
          <div className="panel surface-light p-5 sm:p-6" aria-label="Sample weekly plan">
            <div className="flex items-baseline justify-between">
              <p className="font-display text-lg font-semibold tracking-tight">Week 3</p>
              <p className="font-mono text-[11px] text-muted">3 of 5 days done · sample</p>
            </div>
            <ul className="mt-4 divide-y divide-hair">
              {WEEK.map((d, i) => (
                <motion.li
                  key={d.day}
                  initial={{ opacity: 0, x: 12 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ ...SPRING, delay: i * 0.06 }}
                  className="flex items-center gap-4 py-3"
                >
                  <span className="w-9 font-mono text-[11px] text-muted">{d.day}</span>
                  <span
                    className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border ${d.done ? "border-ink bg-ink text-bg" : "border-line"}`}
                  >
                    {d.done && <Check size={11} aria-label="done" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-sm font-medium ${d.done ? "text-muted line-through decoration-line" : ""}`}>
                      {d.topic}
                    </span>
                    <span className="block truncate text-xs text-muted">{d.sub}</span>
                  </span>
                  <span className="font-mono text-[11px] tabular-nums text-muted">{d.min} min</span>
                </motion.li>
              ))}
            </ul>

            <div className="mt-5 rounded-xl border border-hair bg-bg p-4">
              <p className="eyebrow">Weakness after this week&apos;s quizzes</p>
              <ul className="mt-3 space-y-2.5">
                {WEAKNESS.map(([t, before, after], i) => (
                  <li key={t} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1">
                    <span className="text-sm">{t}</span>
                    <span className="font-mono text-[11px] tabular-nums text-muted">
                      {before.toFixed(2)} → <span className="text-ink">{after.toFixed(2)}</span>
                    </span>
                    <span className="col-span-2 h-1 overflow-hidden rounded-full bg-hair">
                      <motion.span
                        className="block h-full rounded-full bg-ink"
                        initial={{ width: `${before * 100}%` }}
                        whileInView={{ width: `${after * 100}%` }}
                        viewport={{ once: true }}
                        transition={{ ...SPRING, delay: 0.3 + i * 0.08 }}
                      />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
