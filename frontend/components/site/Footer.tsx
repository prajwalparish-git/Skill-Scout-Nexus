"use client";

// The site-wide footer: mission, every tool, the home sections, legal pages and the feedback form.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { GITHUB_URL, LEGAL, PAGES, SECTIONS, TOOLS } from "@/lib/site";
import { Brand, GitHubIcon } from "./Brand";
import { openConsentSettings } from "@/lib/consent";
import { ToolLink } from "./auth";
import { FeedbackForm } from "./Feedback";

const linkCls = "text-sm text-muted transition-colors hover:text-ink";

export function SiteFooter() {
  const path = usePathname();
  const home = (hash: string) => (path === "/" ? hash : `/${hash}`);

  return (
    <footer className="relative mt-24 border-t border-hair bg-surface/40">
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[1fr_1.05fr] lg:gap-16">
        <div className="flex flex-col">
          <Link href="/" className="self-start text-ink" aria-label="Skill Scout Nexus, home">
            <Brand height={16} />
          </Link>
          <p className="mt-5 max-w-sm font-display text-2xl font-semibold leading-tight tracking-tight text-ink">
            Free &amp; open source. A non-commercial college mini-project built for career readiness.
          </p>
          <p className="mt-3 max-w-sm text-sm text-muted">
            Resume scans, critic-checked quizzes, mock interviews and a weekly plan, in one place and
            free to run on your own laptop.
          </p>

          <nav aria-label="Footer" className="mt-10 grid grid-cols-2 gap-8 sm:grid-cols-3">
            <div>
              <h2 className="eyebrow">Tools</h2>
              <ul className="mt-4 space-y-2.5">
                {TOOLS.map((t) => (
                  <li key={t.href}>
                    <ToolLink href={t.href} className={linkCls}>
                      {t.label}
                    </ToolLink>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className="eyebrow">Explore</h2>
              <ul className="mt-4 space-y-2.5">
                <li>
                  <a href={home("#how")} className={linkCls}>
                    How it works
                  </a>
                </li>
                {SECTIONS.map((s) => (
                  <li key={s.hash}>
                    <a href={home(s.hash)} className={linkCls}>
                      {s.label}
                    </a>
                  </li>
                ))}
                {PAGES.map((pg) => (
                  <li key={pg.href}>
                    <Link href={pg.href} className={linkCls}>
                      {pg.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className="eyebrow">Legal</h2>
              <ul className="mt-4 space-y-2.5">
                {LEGAL.map((l) => (
                  <li key={l.href}>
                    <Link href={l.href} className={linkCls}>
                      {l.label}
                    </Link>
                  </li>
                ))}
                <li>
                  <button type="button" onClick={openConsentSettings} className={linkCls}>
                    Manage cookies
                  </button>
                </li>
                <li>
                  <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className={`${linkCls} inline-flex items-center gap-1`}>
                    Source <ArrowUpRight size={13} aria-hidden />
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                </li>
              </ul>
            </div>
          </nav>
        </div>

        <FeedbackForm />
      </div>

      <div className="border-t border-hair">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 font-mono text-[11px] text-muted sm:px-6">
          <span>© {new Date().getFullYear()} Skill Scout Nexus contributors</span>
          <a
            href={`${GITHUB_URL}/issues/new`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 hover:text-ink"
          >
            <GitHubIcon size={13} /> Open a GitHub issue
          </a>
        </div>
      </div>
    </footer>
  );
}
