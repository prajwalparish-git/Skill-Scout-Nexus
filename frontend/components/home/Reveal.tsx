"use client";

import { motion } from "motion/react";
import { SPRING } from "@/lib/site";

/** Fades and lifts its children in once, when they scroll into view. */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ ...SPRING, delay }}
    >
      {children}
    </motion.div>
  );
}

export function SectionHead({
  id,
  eyebrow,
  title,
  lead,
  center = false,
}: {
  id: string;
  eyebrow: string;
  title: React.ReactNode;
  lead?: string;
  center?: boolean;
}) {
  return (
    <Reveal className={center ? "mx-auto max-w-2xl text-center" : "max-w-2xl"}>
      <p className="eyebrow">{eyebrow}</p>
      <h2 id={id} className="display mt-4 text-4xl leading-[1.02] sm:text-5xl">
        {title}
      </h2>
      {lead && <p className="mt-5 text-lg leading-relaxed text-muted">{lead}</p>}
    </Reveal>
  );
}
