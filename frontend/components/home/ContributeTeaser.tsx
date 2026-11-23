"use client";

// A short band on the home page inviting placed students, alumni and professionals to contribute
// questions to the open bank.
import Link from "next/link";
import { ArrowRight, HandHeart } from "lucide-react";
import { trackSpotlight } from "@/components/site/Brand";
import { Reveal } from "./Reveal";

export function ContributeTeaser() {
  return (
    <section aria-labelledby="contribute-teaser" className="mx-auto max-w-6xl px-4 pt-20 sm:px-6 sm:pt-28">
      <Reveal>
        <Link
          href="/contribute"
          onMouseMove={trackSpotlight}
          className="panel spotlight group grid grid-cols-1 items-center gap-6 p-6 transition-colors hover:border-line sm:p-10 lg:grid-cols-[1.4fr_1fr]"
        >
          <div>
            <p className="eyebrow flex items-center gap-2">
              <HandHeart size={13} aria-hidden /> Placed, an alumnus or working?
            </p>
            <h2 id="contribute-teaser" className="display mt-4 text-3xl leading-[1.05] sm:text-4xl">
              Contribute a question
              <span className="text-muted/80"> for the next batch.</span>
            </h2>
            <p className="mt-4 max-w-xl text-muted">
              Add an aptitude, technical or HR question with its answer, in your own words. A moderator checks it; you stay anonymous unless
              you choose a display name.
            </p>
          </div>
          <span className="btn-primary justify-self-start lg:justify-self-end">
            <HandHeart size={16} aria-hidden /> Contribute a question
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" aria-hidden />
          </span>
        </Link>
      </Reveal>
    </section>
  );
}
