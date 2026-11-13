// Site-wide constants for the public pages: links, the tools and the main app's address.

export const GITHUB_URL = "https://github.com/prajwalparish-git/Skill-Scout-Nexus";

/** The Streamlit app, where accounts are created (sign-up and resume onboarding). */
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:8501";

/** Sections of the home page, linked from the top bar and the footer. */
export const SECTIONS = [
  { hash: "#features", label: "Features" },
  { hash: "#tracks", label: "Career Tracks" },
  { hash: "#study", label: "Study Hub" },
  { hash: "#open-source", label: "Open Source" },
] as const;

/** Other public pages in the top bar and the footer. */
export const PAGES = [{ href: "/organizations", label: "For Organizations" }] as const;

/** The tools behind sign-in. `guest` tools also work without a profile (nothing is saved). */
export const TOOLS = [
  { href: "/resume-builder", label: "Resume builder", guest: true },
  { href: "/quiz", label: "Quiz", guest: true },
  { href: "/interview", label: "Mock interview", guest: false },
  { href: "/plan", label: "Study plan", guest: false },
  { href: "/dashboard", label: "Dashboard", guest: false },
] as const;

export const LEGAL = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/cookies", label: "Cookies" },
] as const;

export const isGuestTool = (href: string) => TOOLS.some((t) => t.guest && href.startsWith(t.href));

/** Form consent, never pre-ticked (same sentence as piq/config.py CONSENT_TEXT). */
export const CONSENT_TEXT =
  "I understand this is a college mini-project and consent to processing my input for AI skill evaluation as outlined in the Privacy Policy.";

/** The spring every interactive element uses. */
export const SPRING = { type: "spring", stiffness: 300, damping: 30 } as const;

/** The snappier spring for in-app controls: nav pills, question transitions, tap feedback. */
export const SPRING_UI = { type: "spring", stiffness: 350, damping: 30 } as const;
