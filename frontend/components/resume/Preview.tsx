import type { ResumeLayout } from "@/lib/api";

const LISTED = new Set(["certifications", "achievements", "exam_scores"]);

/** The resume as the chosen template lays it out: one column, the PDF's headings and order. */
export function ResumePreview({ layout, className = "" }: { layout: ResumeLayout; className?: string }) {
  const h = layout.header;
  const left = layout.template === "product" || layout.template === "government";
  return (
    <article
      className={`rounded-xl border border-hair bg-white px-5 py-6 font-sans text-[13px] leading-relaxed text-neutral-900 shadow-[0_1px_2px_rgb(0_0_0/0.04)] sm:px-8 ${className}`}
      aria-label="Resume preview"
    >
      <header className={left ? "text-left" : "text-center"}>
        {h.title && <p className="mb-1 text-center text-sm font-bold uppercase tracking-wide">{h.title}</p>}
        <p className="text-xl font-bold">{h.name || "Your name"}</p>
        {h.subtitle && <p className="text-xs font-semibold uppercase tracking-wide text-neutral-600">{h.subtitle}</p>}
        {h.lines.filter(Boolean).map((l) => (
          <p key={l} className="break-words text-xs text-neutral-600">
            {l}
          </p>
        ))}
      </header>
      {layout.sections.map((s) => (
        <section key={s.key} className="mt-4">
          <h3 className="border-b border-neutral-300 pb-0.5 text-[12px] font-bold uppercase tracking-wide">{s.heading}</h3>
          {s.text && <p className="mt-1.5">{s.text}</p>}
          {s.entries.map((e, i) => (
            <div key={`${e.title}-${i}`} className="mt-2">
              <p className="font-semibold">{e.title}</p>
              {e.detail && <p className="text-xs italic text-neutral-600">{e.detail}</p>}
              {e.bullets.length > 0 && (
                <ul className="mt-0.5 list-disc pl-5">
                  {e.bullets.map((b, k) => (
                    <li key={k}>{b}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {s.lines.length > 0 &&
            (LISTED.has(s.key) ? (
              <ul className="mt-1.5 list-disc pl-5">
                {s.lines.map((l, k) => (
                  <li key={k}>{l}</li>
                ))}
              </ul>
            ) : (
              <div className="mt-1.5 space-y-0.5">
                {s.lines.map((l, k) => (
                  <p key={k}>{l}</p>
                ))}
              </div>
            ))}
        </section>
      ))}
    </article>
  );
}
