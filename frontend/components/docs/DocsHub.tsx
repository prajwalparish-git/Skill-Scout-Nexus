"use client";

// The documentation hub: three audience guides behind tabs (synced with ?tab=), a search across
// all of them, a sticky table of contents on wide screens and a collapsible picker on phones.
import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { motion } from "motion/react";
import { BookOpen, Building2, ChevronDown, Search, Terminal, UserRound, X, type LucideIcon } from "lucide-react";
import { SPRING } from "@/lib/site";
import { DEVELOPERS } from "./developers";
import { INDIVIDUAL } from "./individual";
import { ORGANIZATIONS } from "./organizations";
import type { DocSection, Guide } from "./primitives";

const GUIDES: Guide[] = [INDIVIDUAL, ORGANIZATIONS, DEVELOPERS];
const ICONS: Record<Guide["id"], LucideIcon> = { individual: UserRound, organizations: Building2, developers: Terminal };
type TabId = Guide["id"];

const isTab = (v: string | null): v is TabId => GUIDES.some((g) => g.id === v);

function matches(section: DocSection, words: string[]): boolean {
  if (!words.length) return true;
  const hay = `${section.title} ${section.summary} ${section.keywords}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

export function DocsHub() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const fromUrl = params.get("tab");
  const [tab, setTab] = useState<TabId>(isTab(fromUrl) ? fromUrl : "individual");
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<string>("");
  const [picker, setPicker] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Back / forward and links such as /docs?tab=developers change the tab.
  useEffect(() => {
    if (isTab(fromUrl) && fromUrl !== tab) setTab(fromUrl);
  }, [fromUrl]);

  const choose = (id: TabId) => {
    setTab(id);
    setPicker(false);
    router.replace(`${pathname}?tab=${id}`, { scroll: false });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // "/" focuses the search, as on most documentation sites.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.key === "/" && !(el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable))) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const words = useMemo(() => query.toLowerCase().split(/\s+/).filter(Boolean), [query]);
  const guide = GUIDES.find((g) => g.id === tab) ?? INDIVIDUAL;
  const visible = guide.sections.filter((s) => matches(s, words));
  const elsewhere = words.length
    ? GUIDES.filter((g) => g.id !== tab)
        .map((g) => ({ g, n: g.sections.filter((s) => matches(s, words)).length }))
        .filter((x) => x.n > 0)
    : [];

  // Highlight the section being read in the table of contents.
  const visibleKey = visible.map((s) => s.id).join("|");
  useEffect(() => {
    const els = visible.map((s) => document.getElementById(s.id)).filter((e): e is HTMLElement => Boolean(e));
    if (!els.length) return;
    setActive(els[0].id);
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id);
      },
      { rootMargin: "-96px 0px -60% 0px", threshold: 0 },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [visibleKey]);

  const Toc = ({ onPick }: { onPick?: () => void }) => (
    <ol className="space-y-0.5">
      {visible.map((s, i) => (
        <li key={s.id}>
          <a
            href={`#${s.id}`}
            onClick={onPick}
            aria-current={active === s.id ? "location" : undefined}
            className={`flex gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors ${
              active === s.id ? "bg-surface font-medium text-ink" : "text-muted hover:bg-surface/60 hover:text-ink"
            }`}
          >
            <span className="font-mono text-[11px] leading-5 text-muted">{String(i + 1).padStart(2, "0")}</span>
            <span>{s.title}</span>
          </a>
        </li>
      ))}
    </ol>
  );

  return (
    <div className="relative">
      <div aria-hidden className="hairline-grid pointer-events-none absolute inset-x-0 top-0 h-[420px]" />
      <div className="relative mx-auto max-w-6xl px-4 pb-8 pt-28 sm:px-6 sm:pt-32">
        <motion.header initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={SPRING} className="max-w-3xl">
          <p className="eyebrow flex items-center gap-2">
            <BookOpen size={13} aria-hidden /> Documentation
          </p>
          <h1 className="display mt-4 text-4xl leading-[1.04] sm:text-5xl">Everything Skill Scout Nexus does, explained.</h1>
          <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted sm:text-base">
            Three guides for three audiences: learners preparing for placements, organizations running a cohort, and developers operating an instance. Every
            command, CSV and code block can be copied with one click.
          </p>
        </motion.header>

        <div className="mt-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div role="tablist" aria-label="Choose a guide" className="segmented w-full sm:w-auto">
            {GUIDES.map((g) => {
              const Icon = ICONS[g.id];
              return (
                <button
                  key={g.id}
                  type="button"
                  role="tab"
                  id={`tab-${g.id}`}
                  aria-selected={tab === g.id}
                  aria-controls="docs-panel"
                  onClick={() => choose(g.id)}
                  className={`segment inline-flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap sm:flex-none ${
                    tab === g.id ? "bg-ink text-bg hover:text-bg" : ""
                  }`}
                >
                  <Icon size={14} aria-hidden />
                  <span className="hidden sm:inline">{g.label}</span>
                  <span className="sm:hidden">{g.short}</span>
                </button>
              );
            })}
          </div>
          <label className="relative block w-full lg:w-80">
            <span className="sr-only">Search the documentation</span>
            <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the docs…"
              className="input rounded-full pl-10 pr-10 [&::-webkit-search-cancel-button]:appearance-none"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-1 text-muted hover:text-ink"
                aria-label="Clear search"
              >
                <X size={14} aria-hidden />
              </button>
            ) : (
              <kbd className="pointer-events-none absolute right-3.5 top-1/2 hidden -translate-y-1/2 rounded-md border border-line px-1.5 font-mono text-[10px] text-muted sm:block">
                /
              </kbd>
            )}
          </label>
        </div>

        {elsewhere.length > 0 && (
          <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted" aria-live="polite">
            Also found in:
            {elsewhere.map(({ g, n }) => (
              <button key={g.id} type="button" className="chip border-line text-ink hover:border-ink/40" onClick={() => choose(g.id)}>
                {g.label} · {n}
              </button>
            ))}
          </p>
        )}

        <div className="mt-8 grid gap-8 lg:grid-cols-[250px_minmax(0,1fr)] lg:gap-12">
          <aside className="lg:sticky lg:top-24 lg:self-start" aria-label="On this page">
            {/* phones and tablets: a collapsible picker */}
            <div className="panel lg:hidden">
              <button
                type="button"
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-ink"
                aria-expanded={picker}
                aria-controls="docs-toc-mobile"
                onClick={() => setPicker((p) => !p)}
              >
                <span className="truncate">
                  <span className="eyebrow mr-2">On this page</span>
                  {visible.find((s) => s.id === active)?.title ?? guide.label}
                </span>
                <ChevronDown size={16} className={`shrink-0 transition-transform ${picker ? "rotate-180" : ""}`} aria-hidden />
              </button>
              {picker && (
                <div id="docs-toc-mobile" className="border-t border-hair p-2">
                  <Toc onPick={() => setPicker(false)} />
                </div>
              )}
            </div>
            {/* desktop: sticky table of contents */}
            <nav className="hidden lg:block">
              <p className="eyebrow mb-3 px-3">{guide.label}</p>
              <Toc />
              <p className="mt-6 px-3 text-xs leading-relaxed text-muted">{guide.lead}</p>
            </nav>
          </aside>

          <div id="docs-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="min-w-0">
            {visible.length === 0 ? (
              <div className="rounded-[1.25rem] border border-dashed border-line px-6 py-12 text-center text-sm text-muted">
                No section of this guide matches “{query}”.{" "}
                <button type="button" className="font-medium text-ink underline underline-offset-4" onClick={() => setQuery("")}>
                  Clear the search
                </button>
              </div>
            ) : (
              <div className="space-y-6">
                {visible.map((s, i) => (
                  <motion.section
                    key={`${tab}-${s.id}`}
                    id={s.id}
                    aria-labelledby={`${s.id}-title`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ ...SPRING, delay: Math.min(i, 4) * 0.03 }}
                    className="panel scroll-mt-24 p-5 sm:p-8"
                  >
                    <p className="eyebrow">
                      {guide.short} · {String(guide.sections.indexOf(s) + 1).padStart(2, "0")}
                    </p>
                    <h2 id={`${s.id}-title`} className="display mt-2 text-2xl sm:text-[1.75rem]">
                      <a href={`#${s.id}`} className="hover:underline hover:decoration-line hover:underline-offset-4">
                        {s.title}
                      </a>
                    </h2>
                    <p className="mt-2 text-[15px] text-muted">{s.summary}</p>
                    <div className="mt-2 border-t border-hair pt-2">{s.body}</div>
                  </motion.section>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
