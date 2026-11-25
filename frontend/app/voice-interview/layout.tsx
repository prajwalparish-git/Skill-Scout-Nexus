import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Proctored Voice Assessment",
  description: "Scenario question spoken aloud with 0-15 rubric evaluation and improvement points.",
};

export default function VoiceInterviewLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
