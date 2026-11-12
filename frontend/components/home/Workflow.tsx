"use client";

// The journey in four steps. Scrolling through the section fills the rail and swaps the stage.
import { useRef, useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll, useSpring } from "motion/react";
import { ArrowRight, FileText, MousePointer2 } from "lucide-react";
import { SPRING } from "@/lib/site";
import { SectionHead } from "./Reveal";

const STEPS = [
  {
    title: "First impression",
    body: "No wall, no account. Read what each tool does, browse the career tracks, or take a quiz as a guest.",
  },
  {
    title: "Sign up",
    body: "Create an account in the main app with your email; a code confirms it. One profile carries your scores across every tool.",
  },
  {
    title: "Parse your resume",
    body: "Upload it against the role you want. You get a readiness score, the skills you have, the gaps, and the fixes.",
  },
  {
    title: "Ace the mock interview",
    body: "Five questions for your track, each scored on relevance, depth, structure and clarity, with a model answer beside yours.",
  },
];

export function Workflow() {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.65", "end 0.55"] });
  const rail = useSpring(scrollYProgress, SPRING);
  useMotionValueEvent(scrollYProgress, "change", (p) => setActive(Math.min(STEPS.length - 1, Math.max(0, Math.floor(p * STEPS.length)))));

  return (
    <section aria-labelledby="how-title" id="how" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <SectionHead
        id="how-title"
        eyebrow="How it works"
        title={
          <>
            From first look
            <span className="text-muted/80"> to first offer.</span>
          </>
        }
      />

      <div ref={ref} className="mt-14 grid grid-cols-1 gap-10 lg:grid-cols-[1fr_1.1fr] lg:gap-16">
        <div className="hidden lg:block">
          <div className="sticky top-28">
            <div className="panel surface-light relative aspect-[4/3] overflow-hidden p-8">
              <p className="font-mono text-xs text-muted">
                <span className="text-ink tabular-nums">0{active + 1}</span> / 0{STEPS.length}
              </p>
              <AnimatePresence mode="wait">
                <motion.div
                  key={active}
                  initial={{ opacity: 0, y: 16, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -16, scale: 0.98 }}
                  transition={SPRING}
                  className="absolute inset-0 grid place-items-center p-10"
                  aria-hidden
                >
                  <Stage step={active} />
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>

        <ol className="relative">
          <span aria-hidden className="absolute bottom-2 left-[15px] top-2 w-px bg-hair" />
          <motion.span
            aria-hidden
            style={{ scaleY: rail }}
            className="absolute bottom-2 left-[15px] top-2 w-px origin-top bg-ink"
          />
          {STEPS.map((s, i) => {
            const on = i <= active;
            return (
              <li key={s.title} className="relative flex gap-6 pb-16 last:pb-0 lg:min-h-[34vh]">
                <span
                  className={`relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border font-mono text-xs transition-colors duration-300 ${
                    on ? "border-ink bg-ink text-bg" : "border-hair bg-bg text-muted"
                  }`}
                >
                  {i + 1}
                </span>
                {/* The current step is in ink, the others in muted: dimmed, but still >= 4.5:1. */}
                <div className="pt-0.5">
                  <h3
                    className={`font-display text-2xl font-semibold tracking-tight transition-colors duration-500 sm:text-3xl ${
                      i === active ? "text-ink" : "text-muted"
                    }`}
                  >
                    {s.title}
                  </h3>
                  <p className="mt-3 max-w-md text-[15px] leading-relaxed text-muted">{s.body}</p>
                  <div className="mt-6 lg:hidden" aria-hidden>
                    <div className="panel surface-light grid place-items-center p-6">
                      <Stage step={i} />
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

/** A small illustration of each step. */
function Stage({ step }: { step: number }) {
  if (step === 0)
    return (
      <div className="w-full max-w-xs">
        <div className="rounded-xl border border-hair bg-bg p-4 shadow-sm">
          <div className="h-2 w-16 rounded bg-ink/20" />
          <div className="mt-4 h-4 w-4/5 rounded bg-ink/80" />
          <div className="mt-2 h-4 w-3/5 rounded bg-ink/80" />
          <div className="mt-4 h-2 w-full rounded bg-ink/10" />
          <div className="mt-1.5 h-2 w-5/6 rounded bg-ink/10" />
          <div className="mt-4 flex gap-2">
            <div className="h-6 w-20 rounded-full bg-ink" />
            <div className="h-6 w-16 rounded-full border border-hair" />
          </div>
        </div>
        <MousePointer2 size={20} className="relative -mt-4 ml-24 fill-bg text-ink" />
      </div>
    );
  if (step === 1)
    return (
      <div className="w-full max-w-xs rounded-xl border border-hair bg-bg p-5 shadow-sm">
        <p className="font-mono text-[11px] text-muted">you@example.com</p>
        <p className="mt-4 text-xs text-muted">Enter the 9-digit code</p>
        <div className="mt-2 flex gap-1">
          {"481209773".split("").map((d, i) => (
            <span key={i} className={`grid h-8 flex-1 place-items-center rounded-md border border-hair font-mono text-sm ${i % 3 === 2 ? "mr-1.5" : ""}`}>
              {d}
            </span>
          ))}
        </div>
        <div className="mt-4 flex h-8 items-center justify-center gap-1 rounded-full bg-ink text-xs text-bg">
          Confirm <ArrowRight size={12} />
        </div>
      </div>
    );
  if (step === 2)
    return (
      <div className="flex w-full max-w-xs items-center gap-4">
        <div className="flex flex-1 items-center gap-2 rounded-xl border border-hair bg-bg p-3 font-mono text-[11px] shadow-sm">
          <FileText size={16} /> resume.pdf
        </div>
        <ArrowRight size={16} className="text-muted" />
        <div className="grid h-20 w-20 place-items-center rounded-full border-[6px] border-ink font-mono text-xl font-semibold">72</div>
      </div>
    );
  return (
    <div className="w-full max-w-xs rounded-xl border border-hair bg-bg p-5 shadow-sm">
      <p className="font-mono text-[11px] text-muted">session summary</p>
      <p className="mt-2 font-display text-4xl font-semibold tracking-tight">
        4.0<span className="text-lg text-muted"> / 5</span>
      </p>
      <div className="mt-4 grid grid-cols-4 gap-1.5">
        {[80, 60, 80, 100].map((h, i) => (
          <div key={i} className="flex h-16 items-end rounded bg-hair/60">
            <div className="w-full rounded bg-ink" style={{ height: `${h}%` }} />
          </div>
        ))}
      </div>
      <p className="mt-2 flex justify-between font-mono text-[9px] text-muted">
        <span>REL</span>
        <span>DEP</span>
        <span>STR</span>
        <span>CLA</span>
      </p>
    </div>
  );
}
