// Layout for the legal pages: a narrow, readable column under the top bar.
import Link from "next/link";
import { LEGAL } from "@/lib/site";

export const LEGAL_UPDATED = "12 November 2026";

export function LegalPage({
  title,
  lead,
  current,
  children,
}: {
  title: string;
  lead: string;
  current: string;
  children: React.ReactNode;
}) {
  return (
    <article className="surface-light">
      <div className="mx-auto max-w-2xl px-4 pb-8 pt-36 sm:px-6 sm:pt-44">
        <nav aria-label="Legal pages" className="flex gap-1">
          {LEGAL.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              aria-current={l.href === current ? "page" : undefined}
              className={`rounded-full px-3 py-1 text-sm ${
                l.href === current ? "bg-ink text-bg" : "text-muted hover:bg-ink/[0.06] hover:text-ink"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <h1 className="display mt-10 text-5xl leading-[1.02]">{title}</h1>
        <p className="mt-5 text-lg leading-relaxed text-muted">{lead}</p>
        <p className="eyebrow mt-6">Last updated {LEGAL_UPDATED}</p>
        <aside aria-label="About this project" className="mt-8 rounded-card border border-line bg-surface p-4 text-sm">
          <p>
            <strong className="font-semibold">Skill Scout Nexus is a free, non-commercial, open-source academic college
            mini-project.</strong>{" "}
            It is provided &ldquo;as is&rdquo;, without warranty, for educational and career-readiness purposes. Nothing is
            sold, and no data is used for advertising.
          </p>
        </aside>
        <div className="legal mt-12 space-y-10 border-t border-hair pt-10">{children}</div>
      </div>
    </article>
  );
}

export function Clause({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="font-display text-2xl font-semibold tracking-tight">{title}</h2>
      <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-muted [&_strong]:font-medium [&_strong]:text-ink [&_code]:font-mono [&_code]:text-[13px] [&_code]:text-ink [&_li]:ml-5 [&_li]:list-disc [&_li]:pl-1">
        {children}
      </div>
    </section>
  );
}
