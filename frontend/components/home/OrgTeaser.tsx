"use client";

// A short band on the home page that leads colleges and L&D teams to their own page.
import Link from "next/link";
import { ArrowRight, BarChart3, Building2, Upload } from "lucide-react";
import { trackSpotlight } from "@/components/site/Brand";
import { Reveal } from "./Reveal";

export function OrgTeaser() {
  return (
    <section aria-labelledby="org-teaser" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <Reveal>
        <Link
          href="/organizations"
          onMouseMove={trackSpotlight}
          className="panel spotlight group grid grid-cols-1 items-center gap-8 p-6 transition-colors hover:border-line sm:p-10 lg:grid-cols-[1.3fr_1fr]"
        >
          <div>
            <p className="eyebrow flex items-center gap-2">
              <Building2 size={13} aria-hidden /> For colleges &amp; L&amp;D teams
            </p>
            <h2 id="org-teaser" className="display mt-4 text-3xl leading-[1.05] sm:text-4xl">
              Running placements for a whole batch?
              <span className="text-muted/80"> There is a portal for that.</span>
            </h2>
            <p className="mt-4 max-w-xl text-muted">
              Create every account from one CSV, follow readiness across streams and export drive shortlists.
            </p>
            <span className="mt-6 inline-flex items-center gap-1.5 font-medium text-ink">
              See the admin portal
              <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3" aria-hidden>
            {[
              [Upload, "CSV", "batch accounts"],
              [BarChart3, "Funnel", "enrolled to ready"],
            ].map(([Icon, big, small]) => {
              const I = Icon as typeof Upload;
              return (
                <div key={big as string} className="rounded-2xl border border-hair bg-surface/50 p-4">
                  <I size={18} />
                  <p className="mt-6 font-display text-2xl font-semibold tracking-tight">{big as string}</p>
                  <p className="text-xs text-muted">{small as string}</p>
                </div>
              );
            })}
          </div>
        </Link>
      </Reveal>
    </section>
  );
}
