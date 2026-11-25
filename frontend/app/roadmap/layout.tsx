import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "7-Day Study Roadmap",
  description: "A day-by-day plan for your skill gaps with free curated resources and proof tasks.",
};

export default function RoadmapLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
