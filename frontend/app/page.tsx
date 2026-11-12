"use client";

// The public home page. Open to everyone; the tools behind it ask for a profile (ToolLink).
import { useEffect, useState } from "react";
import { MotionConfig } from "motion/react";
import { get, type Catalog } from "@/lib/api";
import { Bento } from "@/components/home/Bento";
import { Hero } from "@/components/home/Hero";
import { OpenSource } from "@/components/home/OpenSource";
import { OrgTeaser } from "@/components/home/OrgTeaser";
import { StudyHub } from "@/components/home/StudyHub";
import { Tracks } from "@/components/home/Tracks";
import { Workflow } from "@/components/home/Workflow";

export default function Home() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<Catalog>("/api/catalog").then(setCatalog, (e: Error) => setError(e.message));
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <Hero catalog={catalog} />
      <Bento />
      <Workflow />
      <Tracks catalog={catalog} error={error} />
      <StudyHub />
      <OrgTeaser />
      <OpenSource />
    </MotionConfig>
  );
}
