import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Evaluation Benchmark Results",
  description: "Skill Scout Nexus scored against a single-prompt baseline on 20 frozen test cases.",
};

export default function ResultsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
