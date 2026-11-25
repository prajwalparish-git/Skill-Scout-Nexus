import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Resume Scanner & Skill Gaps",
  description: "Diagnose your skill gaps against target roles using AI resume parsing.",
};

export default function ScannerLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
