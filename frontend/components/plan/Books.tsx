"use client";

// "Recommended Books & Deep Reading": textbooks and handbooks for a track and its weak topics.
import { useEffect, useId, useMemo, useState } from "react";
import { BookOpen, Search } from "lucide-react";
import { LEVEL_RANK, LINK_KIND_LABEL, matches, roleScore, type Book, type Level, type Library } from "@/lib/library";
import { Empty } from "@/components/ui";
import { ExtLink, FilterPill, LevelTag } from "./shared";

const PAGE = 8;
// Cover colours come from the theme tokens; each pair is checked for contrast in both modes.
const COVERS = [
  "bg-ink text-bg",
  "bg-primary text-white",
  "border border-line bg-surface text-ink",
  "border border-ink bg-bg text-ink",
];

function coverFor(b: Book): string {
  let h = 0;
  for (const c of b.topics[0] ?? b.id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return COVERS[h % COVERS.length];
}

function initials(title: string): string {
  const words = title.replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter((w) => w.length > 2 && !/^(the|and|for|with|into)$/i.test(w));
  return words.slice(0, 3).map((w) => w[0].toUpperCase()).join("") || title.slice(0, 2).toUpperCase();
}

function Cover({ book }: { book: Book }) {
  return (
    <div
      aria-hidden
      className={`relative flex h-[7.5rem] w-[5.25rem] shrink-0 flex-col justify-between overflow-hidden rounded-r-md rounded-l-[3px] p-2 shadow-sm ${coverFor(book)}`}
    >
      <span className="absolute inset-y-0 left-1.5 w-px bg-current opacity-25" />
      <span className="pl-2 font-mono text-[9px] uppercase tracking-wider opacity-90">{book.format}</span>
      <span className="pl-2 font-display text-xl font-bold leading-none tracking-tight">{initials(book.title)}</span>
    </div>
  );
}

export function Books({
  library,
  role,
  weakTopics,
  checked,
  onToggle,
}: {
  library: Library;
  role: string | null;
  weakTopics: string[];
  checked: Set<string>;
  onToggle: (id: string) => void;
}) {
  const roleEntry = role ? library.roles[role] : undefined;
  const [domain, setDomain] = useState(roleEntry?.domain ?? "");
  const [level, setLevel] = useState<Level | "">("");
  const [q, setQ] = useState("");
  const [weakOnly, setWeakOnly] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const id = useId();

  // A different candidate brings their own track.
  useEffect(() => {
    setDomain(roleEntry?.domain ?? "");
    setWeakOnly(false);
  }, [roleEntry?.domain]);
  useEffect(() => setShown(PAGE), [domain, level, q, weakOnly]);

  const weak = useMemo(() => new Set(weakTopics), [weakTopics]);
  const list = useMemo(() => {
    // Weak topics belong to the candidate's own track, so only books for that track fill them.
    const mine = roleEntry?.domain;
    return library.books
      .filter((b) => (!domain || b.domains.includes(domain)) && (!level || b.level === level))
      .filter((b) => matches(q, b.title, b.author, b.why, b.topics, b.edition))
      .map((b) => ({
        book: b,
        fills: mine && b.domains.includes(mine) ? b.topics.filter((t) => weak.has(t)) : [],
        fit: roleScore({ ...b, skills: [] }, roleEntry),
      }))
      .filter((x) => !weakOnly || x.fills.length > 0)
      .sort((a, b) => b.fills.length - a.fills.length || b.fit - a.fit || LEVEL_RANK[a.book.level] - LEVEL_RANK[b.book.level] || a.book.title.localeCompare(b.book.title));
  }, [library, domain, level, q, weakOnly, weak, roleEntry]);

  return (
    <section aria-labelledby={`${id}-h`} className="mt-12">
      <div className="flex items-start gap-3">
        <span className="rounded-lg bg-primary/10 p-2 text-primary-ink" aria-hidden>
          <BookOpen size={20} />
        </span>
        <div>
          <h2 id={`${id}-h`} className="font-display text-xl font-semibold tracking-tight">
            Recommended Books &amp; Deep Reading
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Textbooks and handbooks for each career track, with a free or official link wherever one exists.
            {weakTopics.length > 0 && " Books for your weak topics come first."}
          </p>
        </div>
      </div>

      <form role="search" aria-label="Filter books" className="mt-5 grid gap-3 sm:grid-cols-[1fr_16rem]" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor={`${id}-q`} className="label">
            Search books
          </label>
          <div className="relative">
            <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              id={`${id}-q`}
              type="search"
              className="input pl-9"
              placeholder="Title, author or topic, for example DBMS"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label htmlFor={`${id}-d`} className="label">
            Career track
          </label>
          <select id={`${id}-d`} className="input" value={domain} onChange={(e) => setDomain(e.target.value)}>
            <option value="">All tracks</option>
            {library.domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label="Difficulty">
        <FilterPill pressed={level === ""} onClick={() => setLevel("")}>
          All levels
        </FilterPill>
        {library.levels.map((l) => (
          <FilterPill key={l} pressed={level === l} onClick={() => setLevel(level === l ? "" : l)}>
            {l}
          </FilterPill>
        ))}
        {weakTopics.length > 0 && (
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[rgb(var(--primary))]"
              checked={weakOnly}
              onChange={(e) => setWeakOnly(e.target.checked)}
            />
            Only my weak topics ({weakTopics.join(", ")})
          </label>
        )}
      </div>

      <p role="status" aria-live="polite" className="mt-4 text-sm text-muted">
        {list.length === 1 ? "1 book" : `${list.length} books`}
        {domain && ` in ${library.domains.find((d) => d.id === domain)?.name}`}
      </p>

      {list.length === 0 ? (
        <div className="mt-3">
          <Empty>No books match these filters. Clear the search or choose another level or track.</Empty>
        </div>
      ) : (
        <ul className="mt-3 grid gap-3 md:grid-cols-2">
          {list.slice(0, shown).map(({ book, fills }) => {
            const done = checked.has(book.id);
            return (
            <li key={book.id}>
              <article className={`card flex h-full gap-4 ${done ? "bg-surface/40" : ""}`} aria-labelledby={`${id}-${book.id}`}>
                <label className="-m-1 flex h-fit shrink-0 cursor-pointer flex-col items-center gap-1 p-1">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[rgb(var(--primary))]"
                    checked={done}
                    onChange={() => onToggle(book.id)}
                    aria-label={`Mark "${book.title}" as read`}
                  />
                </label>
                <Cover book={book} />
                <div className="min-w-0 flex-1">
                  <h3 id={`${id}-${book.id}`} className={`font-semibold leading-snug ${done ? "text-muted line-through decoration-line" : ""}`}>
                    {book.title}
                  </h3>
                  <p className="mt-0.5 text-sm text-muted">{book.author}</p>
                  <p className="font-mono text-xs text-muted">{book.edition}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <LevelTag level={book.level} />
                    {fills.map((t) => (
                      <span key={t} className="chip border-warn text-warn">
                        Fills weak topic: {t}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2 text-sm">{book.why}</p>
                  <p className="mt-1 text-xs text-muted">Covers {book.topics.join(", ")}</p>
                  <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-sm font-medium text-primary-ink" aria-label={`Where to read ${book.title}`}>
                    {book.links.map((l) => (
                      <li key={l.url}>
                        <ExtLink href={l.url}>
                          <span className="font-mono text-[11px] font-normal text-muted">{LINK_KIND_LABEL[l.kind]}</span> {l.label}
                        </ExtLink>
                      </li>
                    ))}
                  </ul>
                </div>
              </article>
            </li>
            );
          })}
        </ul>
      )}

      {list.length > shown && (
        <button type="button" className="btn-ghost mt-4" onClick={() => setShown((n) => n + PAGE)}>
          Show {Math.min(PAGE, list.length - shown)} more books ({list.length - shown} left)
        </button>
      )}
      <p className="mt-4 text-xs text-muted">
        Links last checked {library.checked}. Editions and availability change, so confirm on the page you open.
      </p>
    </section>
  );
}
