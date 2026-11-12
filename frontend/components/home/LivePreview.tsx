"use client";

// The hero's product preview: the resume scanner and the mock interviewer with sample data.
// It tilts back into place as it scrolls in and follows the pointer a little on hover.
import { createContext, useContext, useEffect, useRef, useState } from "react";
import {
  AnimatePresence,
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "motion/react";
import { CheckCircle2, CircleDashed, FileText, Mic, Pause, Play, ShieldCheck } from "lucide-react";
import { SPRING } from "@/lib/site";
import { tabKeys } from "@/components/site/tabKeys";

/** The visitor's reduced-motion setting, read only after hydration so server and client agree. */
function useReduce(): boolean {
  const reduce = useReducedMotion();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted && !!reduce;
}

/** True when the looping animations must stand still: reduced motion, or the visitor paused them. */
const StillContext = createContext(false);

const TABS = [
  { id: "scan", label: "Resume scan" },
  { id: "voice", label: "Voice interview" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function LivePreview() {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReduce();
  const [tab, setTab] = useState<Tab>("scan");
  const [touched, setTouched] = useState(false);
  const [paused, setPaused] = useState(false);
  const still = reduce || paused;

  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const scrollTilt = useTransform(scrollYProgress, [0, 1], [24, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], [0.9, 1]);

  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const sx = useSpring(px, SPRING);
  const sy = useSpring(py, SPRING);
  const rotateX = useTransform([scrollTilt, sy], ([a, b]: number[]) => a - b * 5);
  const rotateY = useTransform(sx, (v) => v * 6);

  // The tabs take turns until the visitor picks one.
  useEffect(() => {
    if (touched || still) return;
    const t = setInterval(() => setTab((x) => (x === "scan" ? "voice" : "scan")), 6000);
    return () => clearInterval(t);
  }, [touched, still]);

  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (reduce || e.pointerType !== "mouse") return;
    const r = e.currentTarget.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  };
  const onLeave = () => {
    px.set(0);
    py.set(0);
  };

  return (
    <div ref={ref} className="mx-auto mt-16 max-w-5xl px-4 pb-20 sm:mt-20 sm:px-6" style={{ perspective: 1400 }}>
      <motion.div
        onPointerMove={onMove}
        onPointerLeave={onLeave}
        style={reduce ? undefined : { rotateX, rotateY, scale, transformStyle: "preserve-3d" }}
        className="panel relative overflow-hidden shadow-[0_40px_120px_-40px_rgb(var(--ink)/0.35)]"
      >
        {/* window chrome */}
        <div className="flex items-center gap-3 border-b border-hair bg-surface/60 px-4 py-2.5">
          <span className="flex gap-1.5" aria-hidden>
            {[0, 1, 2].map((d) => (
              <span key={d} className="h-2.5 w-2.5 rounded-full border border-line/60" />
            ))}
          </span>
          <div
            role="tablist"
            aria-label="Product preview"
            onKeyDown={tabKeys(["scan", "voice"] as const, tab, (id) => {
              setTouched(true);
              setTab(id);
            })}
            className="mx-auto flex rounded-full border border-hair bg-bg p-0.5"
          >
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                type="button"
                id={`preview-tab-${t.id}`}
                aria-controls="preview-panel"
                aria-selected={tab === t.id}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => {
                  setTouched(true);
                  setTab(t.id);
                }}
                className={`relative rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  tab === t.id ? "text-bg" : "text-muted hover:text-ink"
                }`}
              >
                {tab === t.id && (
                  <motion.span layoutId="preview-tab" className="absolute inset-0 rounded-full bg-ink" transition={SPRING} />
                )}
                <span className="relative">{t.label}</span>
              </button>
            ))}
          </div>
          {!reduce && (
            <button
              type="button"
              aria-pressed={paused}
              onClick={() => setPaused((p) => !p)}
              className="flex items-center gap-1.5 rounded-full border border-hair px-2.5 py-1 font-mono text-[11px] text-ink hover:bg-surface"
            >
              {paused ? <Play size={12} aria-hidden /> : <Pause size={12} aria-hidden />}
              {paused ? "Play animation" : "Pause animation"}
            </button>
          )}
          <span className="hidden font-mono text-[10px] text-muted lg:block">sample data</span>
        </div>

        <div
          id="preview-panel"
          role="tabpanel"
          aria-labelledby={`preview-tab-${tab}`}
          className="relative min-h-[380px] p-5 text-left sm:p-7"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -10, filter: "blur(4px)" }}
              transition={SPRING}
            >
              <StillContext.Provider value={still}>{tab === "scan" ? <ScanPanel /> : <VoicePanel />}</StillContext.Provider>
            </motion.div>
          </AnimatePresence>
        </div>
      </motion.div>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------- */

const MATCHED = ["Python", "SQL", "REST APIs", "Git", "Data structures"];
const MISSING = ["Docker", "System design", "OS concepts"];

function ScanPanel() {
  const reduce = useContext(StillContext);
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[1.1fr_1fr]">
      <div className="relative overflow-hidden rounded-xl border border-hair bg-surface/50 p-5">
        <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
          <FileText size={14} aria-hidden /> resume.pdf · Software Engineer
        </div>
        <div className="mt-5 space-y-2.5" aria-hidden>
          <div className="h-3 w-1/2 rounded bg-ink/80" />
          <div className="h-2 w-1/3 rounded bg-ink/20" />
          {[92, 84, 70, 88, 64, 78, 90, 58].map((w, i) => (
            <div key={i} className="flex items-center gap-2" style={{ width: `${w}%` }}>
              <div className="h-2 flex-1 rounded bg-ink/10" />
              {i % 3 === 1 && <span className="rounded border border-ink/30 px-1 font-mono text-[9px] text-ink">{MATCHED[i % 5]}</span>}
            </div>
          ))}
        </div>
        {!reduce && (
          <motion.div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 h-16 bg-gradient-to-b from-transparent via-ink/[0.07] to-transparent"
            initial={{ top: "-15%" }}
            animate={{ top: ["-15%", "100%"] }}
            transition={{ duration: 2.6, ease: "easeInOut", repeat: Infinity, repeatDelay: 0.4 }}
          />
        )}
      </div>

      <div className="flex flex-col gap-5">
        <div className="flex items-center gap-5">
          <Ring value={72} />
          <div>
            <p className="eyebrow">Readiness</p>
            <p className="mt-1 text-sm text-muted">Ready for a first round. Close three gaps for the next tier.</p>
          </div>
        </div>
        <div>
          <p className="eyebrow">Skills found</p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {MATCHED.map((s, i) => (
              <motion.li
                key={s}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ ...SPRING, delay: 0.15 + i * 0.06 }}
                className="chip border-ink/20 text-ink"
              >
                <CheckCircle2 size={12} aria-hidden /> {s}
              </motion.li>
            ))}
          </ul>
        </div>
        <div>
          <p className="eyebrow">Gaps for the role</p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {MISSING.map((s, i) => (
              <motion.li
                key={s}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ ...SPRING, delay: 0.5 + i * 0.06 }}
                className="chip border-dashed border-line text-muted"
              >
                <CircleDashed size={12} aria-hidden /> {s}
              </motion.li>
            ))}
          </ul>
        </div>
        <p className="mt-auto flex items-center gap-2 border-t border-hair pt-4 font-mono text-[11px] text-muted">
          <ShieldCheck size={14} aria-hidden /> critic · 3 of 3 checks passed
        </p>
      </div>
    </div>
  );
}

function Ring({ value }: { value: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });
  const [shown, setShown] = useState(0);
  const r = 34;
  const c = 2 * Math.PI * r;

  useEffect(() => {
    if (!inView) return;
    const ctl = animate(0, value, { duration: 1.2, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => setShown(Math.round(v)) });
    return () => ctl.stop();
  }, [inView, value]);

  return (
    <div ref={ref} className="relative h-20 w-20 shrink-0">
      <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="40" cy="40" r={r} fill="none" strokeWidth="6" className="stroke-hair" />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          strokeWidth="6"
          strokeLinecap="round"
          className="stroke-ink"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - shown / 100)}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-mono text-lg font-semibold tabular-nums">
        {shown}
        <span className="sr-only"> out of 100</span>
      </span>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------- */

const BARS = [0.35, 0.6, 0.9, 0.5, 0.75, 1, 0.65, 0.4, 0.8, 0.55, 0.95, 0.45, 0.7, 0.3, 0.85, 0.6, 0.4, 0.75, 0.5, 0.9, 0.35, 0.65, 0.55, 0.8];
const RUBRIC: [string, number][] = [
  ["Relevance", 4],
  ["Depth", 3],
  ["Structure", 4],
  ["Clarity", 5],
];

function VoicePanel() {
  const reduce = useContext(StillContext);
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[1.1fr_1fr]">
      <div className="flex flex-col rounded-xl border border-hair bg-surface/50 p-5">
        <p className="eyebrow">Question 2 of 5 · Technical</p>
        <p className="mt-3 font-display text-xl font-medium leading-snug tracking-tight">
          How does an index speed up a database query, and when does it slow one down?
        </p>
        <div className="mt-6 flex h-14 items-center gap-[3px]" aria-hidden>
          {BARS.map((h, i) => (
            <motion.span
              key={i}
              className="w-full origin-center rounded-full bg-ink/70"
              style={{ height: `${h * 100}%` }}
              animate={reduce ? undefined : { scaleY: [0.35, 1, 0.5, 0.9, 0.35] }}
              transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.045, ease: "easeInOut" }}
            />
          ))}
        </div>
        <div className="mt-4 flex items-center justify-between font-mono text-[11px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              {!reduce && <span className="absolute inset-0 animate-ping rounded-full bg-bad/60" />}
              <span className="relative h-2 w-2 rounded-full bg-bad" />
            </span>
            <Mic size={12} aria-hidden /> listening
          </span>
          <span className="tabular-nums">00:42</span>
        </div>
      </div>

      <div className="flex flex-col">
        <p className="eyebrow">Rubric</p>
        <ul className="mt-3 space-y-3.5">
          {RUBRIC.map(([name, score], i) => (
            <li key={name}>
              <div className="flex justify-between text-sm">
                <span>{name}</span>
                <span className="font-mono text-xs tabular-nums text-muted">{score}/5</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-hair">
                <motion.div
                  className="h-full rounded-full bg-ink"
                  initial={{ width: 0 }}
                  animate={{ width: `${score * 20}%` }}
                  transition={{ ...SPRING, delay: 0.15 + i * 0.08 }}
                />
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-5 rounded-xl border border-hair p-3 text-sm text-muted">
          <span className="font-medium text-ink">Next time:</span> name one case where an index hurts
          writes, then give the trade-off in a sentence.
        </p>
        <p className="mt-auto flex items-center justify-between border-t border-hair pt-4 font-mono text-[11px] text-muted">
          <span>average</span>
          <span className="text-ink">4.0 / 5</span>
        </p>
      </div>
    </div>
  );
}
