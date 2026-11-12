"use client";

// Types and helpers for GET /api/library (piq/study_library.py): the study books and the
// curated GitHub repositories shown on the plan page.
import { useEffect, useState } from "react";
import { get } from "./api";

export type Level = "Beginner" | "Intermediate" | "Advanced";
export type BookLink = { kind: "open" | "publisher" | "archive"; label: string; url: string };
export type Book = {
  id: string;
  title: string;
  author: string;
  edition: string;
  format: string;
  level: Level;
  domains: string[];
  topics: string[];
  why: string;
  links: BookLink[];
};
export type RepoCategory = { id: string; name: string; blurb: string };
export type Repo = {
  id: string;
  repo: string;
  url: string;
  category: string;
  level: Level;
  hours: number | null;
  why: string;
  domains: string[];
  topics: string[];
  skills: string[];
};
export type RoleEntry = { domain: string; topics: string[]; skills: string[] };
export type Library = {
  checked: string;
  levels: Level[];
  domains: { id: string; name: string }[];
  roles: Record<string, RoleEntry>;
  books: Book[];
  repo_categories: RepoCategory[];
  repos: Repo[];
};

export const LEVEL_RANK: Record<Level, number> = { Beginner: 1, Intermediate: 2, Advanced: 3 };
export const LINK_KIND_LABEL: Record<BookLink["kind"], string> = {
  open: "Free to read",
  publisher: "Publisher",
  archive: "Archive",
};

/** Loads the library once per page view. */
export function useLibrary(): { library: Library | null; error: string | null } {
  const [library, setLibrary] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    get<Library>("/api/library").then(
      (l) => current && setLibrary(l),
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, []);
  return { library, error };
}

/** How well an item fits a role: -1 when it is for another domain, else the number of topics
 *  (Aptitude excluded, every role has it) and skills they share. */
export function roleScore(item: { domains: string[]; topics: string[]; skills?: string[] }, role: RoleEntry | undefined): number {
  if (!role) return 0;
  if (!item.domains.includes(role.domain)) return -1;
  const topics = item.topics.filter((t) => t !== "Aptitude" && role.topics.includes(t)).length;
  const skills = (item.skills ?? []).filter((s) => role.skills.includes(s)).length;
  return topics + skills;
}

/** The skills and topics an item shares with a role: the reason it is suggested for it. */
export function sharedTerms(item: { topics: string[]; skills?: string[] }, role: RoleEntry | undefined): string[] {
  if (!role) return [];
  const skills = (item.skills ?? []).filter((s) => role.skills.includes(s));
  const topics = item.topics.filter((t) => t !== "Aptitude" && role.topics.includes(t) && !skills.includes(t));
  return [...skills, ...topics];
}

/** Fewer shared terms are enough outside computer science, where there are fewer repositories. */
export const minRoleFit = (role: RoleEntry | undefined) => (role?.domain === "cs" ? 3 : 1);

/** Case-insensitive match of every word of `q` against the given text parts. */
export function matches(q: string, ...parts: (string | string[])[]): boolean {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = parts.flat().join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** The link a book is opened with: a free copy first, then the publisher, then the archive. */
export function bestLink(b: Book): BookLink {
  const order = ["open", "publisher", "archive"];
  return [...b.links].sort((x, y) => order.indexOf(x.kind) - order.indexOf(y.kind))[0];
}

/** The one book to suggest for a study topic of a domain, or null. */
export function pickBook(lib: Library, domain: string, topic: string): Book | null {
  const pool = lib.books.filter((b) => b.domains.includes(domain) && b.topics.includes(topic));
  const rank = (b: Book) => ["open", "publisher", "archive"].indexOf(bestLink(b).kind) * 10 + LEVEL_RANK[b.level];
  return pool.sort((a, b) => rank(a) - rank(b))[0] ?? null;
}
