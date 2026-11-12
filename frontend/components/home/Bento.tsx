"use client";

// The five pillars. Each card plays a small demo of its tool on hover (or focus).
import { motion, type Variants } from "motion/react";
import { ArrowUpRight, Check, ShieldCheck } from "lucide-react";
import { SPRING } from "@/lib/site";
import { ToolLink } from "@/components/site/auth";
import { trackSpotlight } from "@/components/site/Brand";
import { Reveal, SectionHead } from "./Reveal";

const lift: Variants = { rest: { y: 0 }, hover: { y: -4 } };

function Card({
  span,
  index,
  eyebrow,
  title,
  body,
  href,
  cta,
  children,
}: {
  span: string;
  index: number;
  eyebrow: string;
  title: string;
  body: string;
  href: string;
  cta: string;
  children: React.ReactNode;
}) {
  return (
    <Reveal delay={index * 0.05} className={span}>
      <motion.article
        initial="rest"
        animate="rest"
        whileHover="hover"
        variants={lift}
        transition={SPRING}
        onMouseMove={trackSpotlight}
        className="panel spotlight group relative flex h-full flex-col overflow-hidden p-6 transition-colors hover:border-line focus-within:border-line"
      >
        <div className="relative mb-6 min-h-[150px] flex-1 overflow-hidden rounded-xl border border-hair bg-surface/50 p-4">
          {children}
        </div>
        <p className="eyebrow">{eyebrow}</p>
        <h3 className="mt-2 font-display text-2xl font-semibold tracking-tight">{title}</h3>
        <p className="mt-2 text-[15px] leading-relaxed text-muted">{body}</p>
        <ToolLink
          href={href}
          className="mt-5 inline-flex items-center gap-1 self-start text-sm font-medium text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:rounded-[1.25rem] focus-visible:after:ring-2 focus-visible:after:ring-primary/60"
        >
          {cta}
          <ArrowUpRight size={15} className="transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden />
        </ToolLink>
      </motion.article>
    </Reveal>
  );
}

/* --- the five demos -------------------------------------------------------------------------- */

const KEYWORDS: [string, boolean][] = [
  ["Python", true],
  ["SQL", true],
  ["REST APIs", true],
  ["Docker", false],
  ["Git", true],
  ["System design", false],
  ["Testing", true],
  ["Kubernetes", false],
  ["Data structures", true],
];

function ParserDemo() {
  return (
    <div className="flex h-full flex-col justify-between gap-4" aria-hidden>
      <div className="flex flex-wrap gap-1.5">
        {KEYWORDS.map(([k, found], i) => (
          <span
            key={k}
            style={{ transitionDelay: `${i * 35}ms` }}
            className={`rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors duration-300 ${
              found
                ? "border-hair text-muted group-hover:border-ink group-hover:bg-ink group-hover:text-bg"
                : "border-hair text-muted group-hover:border-dashed group-hover:border-line"
            }`}
          >
            {k}
          </span>
        ))}
      </div>
      <div className="flex items-end justify-between font-mono text-[11px] text-muted">
        <span>ATS keywords · 6 of 9 found</span>
        <span className="text-3xl font-semibold text-ink tabular-nums transition-transform duration-300 group-hover:-translate-y-0.5">
          78
        </span>
      </div>
    </div>
  );
}

function QuizDemo() {
  const options = ["O(n)", "O(log n)", "O(n log n)"];
  return (
    <div aria-hidden>
      <p className="text-sm font-medium">Binary search on a sorted array runs in…</p>
      <ul className="mt-3 space-y-1.5">
        {options.map((o, i) => (
          <li
            key={o}
            className={`flex items-center justify-between rounded-lg border px-2.5 py-1.5 font-mono text-xs transition-colors duration-300 ${
              i === 1 ? "border-hair group-hover:border-ink group-hover:bg-ink group-hover:text-bg" : "border-hair text-muted"
            }`}
          >
            {o}
            {i === 1 && <Check size={13} className="opacity-0 transition-opacity duration-300 group-hover:opacity-100" />}
          </li>
        ))}
      </ul>
      <motion.span
        variants={{ rest: { opacity: 0, scale: 0.85, rotate: -6 }, hover: { opacity: 1, scale: 1, rotate: -6 } }}
        transition={{ ...SPRING, delay: 0.12 }}
        className="absolute right-3 top-3 flex items-center gap-1 rounded-md border border-ink px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink"
      >
        <ShieldCheck size={11} /> critic ok
      </motion.span>
    </div>
  );
}

const WAVE = [0.4, 0.7, 1, 0.6, 0.85, 0.45, 0.95, 0.55, 0.75, 0.35, 0.9, 0.5, 0.8, 0.4, 0.65, 0.3];

function VoiceDemo() {
  return (
    <div className="flex h-full flex-col justify-between" aria-hidden>
      <div className="flex h-20 items-center justify-between">
        {WAVE.map((h, i) => (
          <motion.span
            key={i}
            className="w-[5px] origin-center rounded-full bg-ink/70"
            style={{ height: `${h * 100}%` }}
            variants={{
              rest: { scaleY: 0.35 },
              hover: { scaleY: [0.3, 1, 0.45, 0.9, 0.3], transition: { duration: 1.2, repeat: Infinity, delay: i * 0.04 } },
            }}
          />
        ))}
      </div>
      <p className="mt-3 font-mono text-[11px] text-muted">speak or type · 5 questions</p>
    </div>
  );
}

const RUBRIC: [string, number][] = [
  ["Relevance", 80],
  ["Depth", 60],
  ["Structure", 80],
  ["Clarity", 100],
];

function RubricDemo() {
  return (
    <ul className="space-y-2.5" aria-hidden>
      {RUBRIC.map(([name, pct], i) => (
        <li key={name}>
          <div className="flex justify-between font-mono text-[11px] text-muted">
            <span>{name}</span>
            <span>{pct / 20}/5</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-hair">
            <motion.div
              className="h-full rounded-full bg-ink"
              variants={{ rest: { width: "18%" }, hover: { width: `${pct}%` } }}
              transition={{ ...SPRING, delay: i * 0.05 }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];
const TOPICS = ["OS", "DBMS", "OS", "Networks", "DSA", "DBMS", "Review"];

function PlannerDemo() {
  return (
    <div aria-hidden>
      <div className="grid grid-cols-7 gap-1.5">
        {DAYS.map((d, i) => (
          <div key={i} className="text-center">
            <p className="font-mono text-[10px] text-muted">{d}</p>
            <div
              style={{ transitionDelay: `${i * 60}ms` }}
              className={`mt-1 grid aspect-square place-items-center rounded-md border transition-colors duration-300 ${
                i < 5 ? "border-hair group-hover:border-ink group-hover:bg-ink group-hover:text-bg" : "border-dashed border-line"
              }`}
            >
              <Check size={12} className={`transition-opacity duration-300 ${i < 5 ? "opacity-0 group-hover:opacity-100" : "opacity-0"}`} style={{ transitionDelay: `${i * 60}ms` }} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 truncate font-mono text-[11px] text-muted">{TOPICS.join(" · ")}</p>
    </div>
  );
}

export function Bento() {
  return (
    <section aria-labelledby="features-title" id="features" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <SectionHead
        id="features-title"
        eyebrow="Five tools, one profile"
        title={
          <>
            Everything a placement drive tests.
            <span className="text-muted/80"> Nothing it doesn&apos;t.</span>
          </>
        }
        lead="Each tool feeds the next: resume gaps pick your quiz topics, quiz scores shape your plan, and the interview tells you how it all comes across."
      />
      <div className="mt-14 grid grid-cols-1 gap-4 md:grid-cols-6">
        <Card
          span="md:col-span-4"
          index={0}
          eyebrow="01 · Resume parser"
          title="Read like an ATS, explained like a mentor."
          body="Upload a PDF, DOCX or TXT and see the skills the role asks for that you have, the ones you don't, and an ATS score with fixes."
          href="/resume-builder"
          cta="Open the resume builder"
        >
          <ParserDemo />
        </Card>
        <Card
          span="md:col-span-2"
          index={1}
          eyebrow="02 · Critic quiz"
          title="Questions that were checked first."
          body="A critic agent rejects vague or wrong questions before you see them; difficulty follows your score."
          href="/quiz"
          cta="Take a quiz"
        >
          <QuizDemo />
        </Card>
        <Card
          span="md:col-span-2"
          index={2}
          eyebrow="03 · Mock interview"
          title="Rehearse out loud."
          body="Five questions for your track, with follow-ups when an answer is thin."
          href="/interview"
          cta="Start an interview"
        >
          <VoiceDemo />
        </Card>
        <Card
          span="md:col-span-2"
          index={3}
          eyebrow="04 · Rubric evaluator"
          title="Scored, not guessed."
          body="Relevance, depth, structure and clarity, each out of five, with a model answer to compare."
          href="/dashboard"
          cta="See your scores"
        >
          <RubricDemo />
        </Card>
        <Card
          span="md:col-span-2"
          index={4}
          eyebrow="05 · Study planner"
          title="A week that adapts."
          body="Weak topics get more days. Tick off a day and next week's plan moves on."
          href="/plan"
          cta="Open your plan"
        >
          <PlannerDemo />
        </Card>
      </div>
    </section>
  );
}
