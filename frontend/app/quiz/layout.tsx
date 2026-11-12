import type { Metadata } from "next";

// Gives the route its own page title (the root layout adds the site name).
export const metadata: Metadata = { title: "Quiz" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
