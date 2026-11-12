"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowUpRight, Check, Copy } from "lucide-react";
import { GITHUB_URL, SPRING } from "@/lib/site";
import { GitHubIcon } from "@/components/site/Brand";
import { Reveal } from "./Reveal";

const CLONE = `git clone ${GITHUB_URL}.git`;
const STACK = ["Next.js", "FastAPI", "LangGraph", "Streamlit", "SQLite"];

export function OpenSource() {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(CLONE);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked: the command stays selectable */
    }
  };

  return (
    <section aria-labelledby="oss-title" id="open-source" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <Reveal>
        <div className="on-ink relative overflow-hidden rounded-[2rem] bg-ink px-6 py-14 text-bg sm:px-12 sm:py-20">
          <div
            aria-hidden
            className="absolute inset-0 opacity-60"
            style={{ backgroundImage: "radial-gradient(80% 60% at 85% 0%, rgb(var(--bg) / 0.12), transparent 60%)" }}
          />
          <div className="relative grid grid-cols-1 gap-10 lg:grid-cols-[1.3fr_1fr] lg:items-end">
            <div>
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-bg/80">Open source</p>
              <h2 id="oss-title" className="mt-4 font-display text-4xl font-semibold leading-[1.02] tracking-[-0.035em] sm:text-5xl">
                Free to use. Free to read.
                <span className="text-bg/70"> Runs on your laptop.</span>
              </h2>
              <p className="mt-5 max-w-lg text-lg leading-relaxed text-bg/80">
                Every agent, prompt and rubric is in the repository. With no API keys it runs in mock
                mode, so every page works offline; add a free key for live AI.
              </p>
              <ul className="mt-8 flex flex-wrap gap-2">
                {STACK.map((s) => (
                  <li key={s} className="rounded-full border border-bg/40 px-3 py-1 font-mono text-[11px] text-bg/90">
                    {s}
                  </li>
                ))}
              </ul>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-2 rounded-2xl border border-bg/15 bg-bg/[0.06] p-2 pl-4">
                <code className="min-w-0 flex-1 select-all truncate font-mono text-xs text-bg/85">{CLONE}</code>
                <button
                  type="button"
                  onClick={copy}
                  className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl text-bg/80 hover:bg-bg/10 hover:text-bg"
                  aria-label={copied ? "Clone command copied" : "Copy the git clone command"}
                >
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                      key={copied ? "ok" : "copy"}
                      initial={{ scale: 0.6, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0.6, opacity: 0 }}
                      transition={SPRING}
                    >
                      {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
                    </motion.span>
                  </AnimatePresence>
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="btn h-11 flex-1 rounded-full bg-bg px-5 text-ink hover:bg-bg/90"
                >
                  <GitHubIcon size={16} /> View on GitHub<span className="sr-only"> (opens in a new tab)</span>
                </a>
                <a
                  href={`${GITHUB_URL}#quick-start`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn h-11 flex-1 rounded-full border border-bg/25 px-5 text-bg hover:bg-bg/10"
                >
                  Quick start guide <ArrowUpRight size={16} aria-hidden /><span className="sr-only"> (opens in a new tab)</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
