"use client";

// The public page for colleges, institutes and L&D teams: what the admin portal does.
import { OrgCta, OrgFeatures, OrgHero, OrgSteps, OrgTrust } from "@/components/org/Sections";

export default function Organizations() {
  return (
    <>
      <OrgHero />
      <OrgFeatures />
      <OrgSteps />
      <OrgTrust />
      <OrgCta />
    </>
  );
}
