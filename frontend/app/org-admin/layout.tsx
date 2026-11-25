import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Organization Admin Portal",
  description: "Provision students, follow cohort readiness and prepare placement drives.",
};

export default function OrgAdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
