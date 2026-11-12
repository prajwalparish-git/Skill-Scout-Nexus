"use client";

import { motion } from "motion/react";
import { ArrowDown, ArrowRight } from "lucide-react";
import type { Catalog } from "@/lib/api";
import { SPRING } from "@/lib/site";
import { useAuth } from "@/components/site/auth";
import { LivePreview } from "./LivePreview";

// Each line: muted lead-in, then the word that carries it in full ink.
const LINES = [
  ["Your resume,", "read."],
  ["Your interview,", "rehearsed."],
  ["Your week,", "planned."],
];

export function Hero({ catalog }: { catalog: Catalog | null }) {
  const { open } = useAuth();
  let i = 0;

  const roles = catalog?.domains.reduce((n, d) => n + d.roles.length, 0) ?? 0;
  const questions =
    catalog?.domains.reduce(
      (n, d) => n + d.topics.reduce((m, t) => m + Object.values(t.bank).reduce((a, b) => a + b, 0), 0),
      0,
    ) ?? 0;
  const stats = catalog
    ? [
        [catalog.domains.length, "career domains"],
        [roles, "roles"],
        [questions.toLocaleString(), "practice questions"],
      ]
    : null;

  return (
    <section aria-labelledby="hero-title" className="relative overflow-x-clip pt-36 sm:pt-44">
      <div aria-hidden className="hairline-grid absolute inset-0 -z-10" />
      <div aria-hidden className="surface-light absolute inset-0 -z-10" />

      <div className="mx-auto max-w-6xl px-4 text-center sm:px-6">
        <motion.p
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={SPRING}
          className="glass mx-auto inline-flex items-center gap-2 rounded-full px-3 py-1"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
          <span className="eyebrow">Open source · Career readiness</span>
        </motion.p>

        <h1 id="hero-title" className="display mx-auto mt-8 max-w-5xl text-[clamp(2.6rem,7.4vw,5.6rem)] leading-[0.98]">
          {LINES.map(([lead, word]) => (
            <span key={word} className="block">
              {[...lead.split(" "), word].map((w, j, all) => {
                const delay = 0.08 + i++ * 0.055;
                const strong = j === all.length - 1;
                return (
                  <span key={j} className="inline-block overflow-hidden pb-[0.1em] align-bottom">
                    <motion.span
                      className={`inline-block ${strong ? "text-ink" : "text-muted/80"}`}
                      initial={{ y: "105%" }}
                      animate={{ y: 0 }}
                      transition={{ ...SPRING, delay }}
                    >
                      {w}
                      {j < all.length - 1 && " "}
                    </motion.span>
                  </span>
                );
              })}
            </span>
          ))}
        </h1>

        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...SPRING, delay: 0.55 }}
          className="mx-auto mt-7 max-w-xl text-lg leading-relaxed text-muted"
        >
          Skill Scout Nexus reads your resume against the role you want, quizzes you with
          critic-checked questions, scores a mock interview on a rubric, and turns the results into
          next week&apos;s plan.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...SPRING, delay: 0.65 }}
          className="mt-9 flex flex-wrap items-center justify-center gap-3"
        >
          <button type="button" className="btn-ink group h-11 px-6 text-[15px]" onClick={() => open("signup")}>
            Get started, it&apos;s free
            <ArrowRight size={16} className="transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
          </button>
          <a href="#how" className="btn-hair h-11 px-6 text-[15px]">
            See how it works <ArrowDown size={16} aria-hidden />
          </a>
        </motion.div>

        <motion.dl
          initial={{ opacity: 0 }}
          animate={{ opacity: stats ? 1 : 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mx-auto mt-10 flex min-h-5 flex-wrap justify-center gap-x-8 gap-y-2 font-mono text-xs text-muted"
        >
          {stats?.map(([n, label]) => (
            <div key={label} className="flex items-baseline gap-1.5">
              <dt className="order-2">{label}</dt>
              <dd className="order-1 text-ink tabular-nums">{n}</dd>
            </div>
          ))}
        </motion.dl>
      </div>

      <LivePreview />
    </section>
  );
}
