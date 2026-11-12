import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Shell } from "@/components/Shell";
import { AuthProvider } from "@/components/site/auth";
import { ConsentBanner } from "@/components/site/ConsentBanner";
import { MotionProvider } from "@/components/site/MotionProvider";
import { CandidateProvider } from "@/lib/candidate";

// Self-hosted (OFL, licences beside the files): no font CDN, so the app still works offline.
const display = localFont({
  src: "./fonts/bricolage-grotesque/BricolageGrotesque-latin.woff2",
  variable: "--font-display",
  weight: "200 800",
  display: "swap",
});
const body = localFont({
  src: "./fonts/atkinson-hyperlegible-next/AtkinsonHyperlegibleNext-latin.woff2",
  variable: "--font-body",
  weight: "200 800",
  display: "swap",
});
const mono = localFont({
  src: "./fonts/jetbrains-mono/JetBrainsMono-latin.woff2",
  variable: "--font-mono",
  weight: "100 800",
  display: "swap",
});

// Each route sets its own title through its layout; this template adds the site name (WCAG 2.4.2).
export const metadata: Metadata = {
  title: { default: "Skill Scout Nexus", template: "%s · Skill Scout Nexus" },
  description: "Placement readiness: resume, quizzes, mock interviews and an adaptive weekly plan.",
  icons: { icon: "/brand/mark.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        {/* First stop for keyboard and screen-reader users: jump past the navigation. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-full focus:bg-ink focus:px-5 focus:py-2.5 focus:text-sm focus:font-medium focus:text-bg focus:shadow-lg focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-focus"
        >
          Skip to main content
        </a>
        <MotionProvider>
          <CandidateProvider>
            <AuthProvider>
              <Shell>{children}</Shell>
              <ConsentBanner />
            </AuthProvider>
          </CandidateProvider>
        </MotionProvider>
      </body>
    </html>
  );
}
