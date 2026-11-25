import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Critic-Checked Quiz",
  description: "Generator-critic verified multiple-choice assessments with question bank fallback.",
};

export default function CriticQuizLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
