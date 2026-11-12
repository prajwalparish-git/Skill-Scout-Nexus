import { ExternalLink } from "lucide-react";
import type { Level } from "@/lib/library";

const BARS: Record<Level, number> = { Beginner: 1, Intermediate: 2, Advanced: 3 };

/** A difficulty tag: the word and filled bars, never colour alone. */
export function LevelTag({ level }: { level: Level }) {
  return (
    <span className="chip border-line text-ink">
      <span className="flex items-end gap-px" aria-hidden>
        {[1, 2, 3].map((n) => (
          <span key={n} className={`w-[3px] rounded-sm ${n <= BARS[level] ? "bg-ink" : "bg-line/50"}`} style={{ height: 4 + n * 2 }} />
        ))}
      </span>
      {level}
    </span>
  );
}

/** An external link that says it opens a new tab. */
export function ExtLink({ href, className = "", children }: { href: string; className?: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-1 rounded-sm underline-offset-2 hover:underline ${className}`}
    >
      {children}
      <ExternalLink size={12} aria-hidden className="shrink-0" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

/** A pill toggle button for filters. */
export function FilterPill({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-sm transition-colors ${
        pressed ? "border-ink bg-ink text-bg" : "border-line text-ink hover:bg-surface"
      }`}
    >
      {children}
    </button>
  );
}
