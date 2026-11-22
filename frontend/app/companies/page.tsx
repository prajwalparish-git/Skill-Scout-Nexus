"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, ExternalLink, Flag, Loader2, MessagesSquare, Search, UserRound } from "lucide-react";
import {
  get,
  post,
  ROUNDS,
  type CompanyDetail,
  type CompanySummary,
  type MyPost,
  type PracticeQuiz as Quiz,
} from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { useAuth } from "@/components/site/auth";
import { Badge, Empty, ErrorNote, PageHeader } from "@/components/ui";
import { PracticeQuiz } from "@/components/companies/PracticeQuiz";
import { ShareForm } from "@/components/companies/ShareForm";

const LETTERS = "ABCD";
const STATUS: Record<MyPost["status"], { state: "ok" | "info" | "warn" | "todo"; text: string }> = {
  pending: { state: "info", text: "Waiting for review" },
  approved: { state: "ok", text: "Published" },
  rejected: { state: "warn", text: "Not published" },
  hidden: { state: "warn", text: "Hidden after reports" },
};

function Company({ slug, onBack }: { slug: string; onBack: () => void }) {
  const [round, setRound] = useState<string>("");
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reported, setReported] = useState<number[]>([]);

  useEffect(() => {
    let live = true;
    setDetail(null);
    get<CompanyDetail>(`/api/companies/${slug}${round ? `?round=${round}` : ""}`).then(
      (d) => live && setDetail(d),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [slug, round]);

  async function practise(source: "reported" | "ai") {
    setBusy(source);
    setError(null);
    try {
      setQuiz(await get<Quiz>(`/api/companies/${slug}/practice?round=${round}&source=${source}`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function report(id: number) {
    try {
      await post(`/api/experiences/${id}/report`, {});
      setReported((r) => [...r, id]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (quiz) return <PracticeQuiz slug={slug} quiz={quiz} onClose={() => setQuiz(null)} />;

  const inRound = (detail?.posts ?? []).filter((p) => !round || p.round === round);
  const mcqs = inRound.reduce((n, p) => n + p.questions.filter((q) => q.kind === "mcq").length, 0);
  const opens = inRound.reduce((n, p) => n + p.questions.filter((q) => q.kind === "open").length, 0);
  return (
    <div className="space-y-4">
      <button type="button" className="btn-ghost" onClick={onBack}>
        <ArrowLeft size={16} aria-hidden /> All companies
      </button>
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="h2">{detail?.name ?? "…"}</h2>
          {detail?.careers_url && (
            <a href={detail.careers_url} target="_blank" rel="noopener noreferrer" className="btn-ghost text-xs">
              Official careers page <ExternalLink size={14} aria-hidden />
            </a>
          )}
        </div>
        <div className="segmented mt-4" role="group" aria-label="Round">
          <button type="button" className="segment" aria-pressed={!round} onClick={() => setRound("")}>
            All rounds
          </button>
          {Object.entries(ROUNDS).map(([k, v]) => (
            <button key={k} type="button" className="segment" aria-pressed={round === k} onClick={() => setRound(k)}>
              {v}
              {detail?.rounds[k] ? ` (${detail.rounds[k].posts})` : ""}
            </button>
          ))}
        </div>
        {round ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={!mcqs || busy !== null} onClick={() => practise("reported")}>
              {busy === "reported" ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <UserRound size={16} aria-hidden />} Quiz: {mcqs}{" "}
              reported question{mcqs === 1 ? "" : "s"}
            </button>
            <Link href={`/interview?company=${slug}&round=${round}`} className="btn-ghost">
              <MessagesSquare size={16} aria-hidden /> {opens ? `Mock interview: ${opens} reported` : "Mock interview (AI questions)"}
            </Link>
            {round !== "hr" && round !== "group_discussion" && (
              <button type="button" className="btn-ghost" disabled={busy !== null} onClick={() => practise("ai")}>
                {busy === "ai" ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Bot size={16} aria-hidden />} AI practice in this style
              </button>
            )}
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">Choose a round to practise it.</p>
        )}
        <p className="mt-3 text-xs text-muted">
          Reported questions are asked as students wrote them. AI practice is written by AI in the round&apos;s style and is never presented
          as questions the company asked.
        </p>
      </section>
      <ErrorNote message={error} />
      {detail && inRound.length === 0 && <Empty icon={MessagesSquare}>No approved posts here yet. Interviewed with them? Share it below.</Empty>}
      {inRound.map((p) => (
        <article key={p.id} className="card">
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span className="chip border-warn/40 text-warn">
              <UserRound size={12} aria-hidden /> Reported by {p.label}
            </span>
            <span className="font-semibold">{p.role}</span>
            <span className="text-muted">
              · {ROUNDS[p.round]} round · {p.interview_month}
            </span>
          </p>
          <ol className="mt-3 space-y-3">
            {p.questions.map((q, i) => (
              <li key={i} className="text-sm">
                <p className="font-medium">
                  {i + 1}. {q.text}
                </p>
                {q.kind === "mcq" && (
                  <>
                    <ul className="mt-1 grid gap-0.5 text-muted sm:grid-cols-2">
                      {q.options?.map((o, j) => (
                        <li key={j}>
                          <span className="font-mono text-xs">{LETTERS[j]}</span> {o}
                        </li>
                      ))}
                    </ul>
                    <details className="mt-1 text-xs">
                      <summary className="cursor-pointer text-muted">Show the reported answer</summary>
                      <p className="mt-1">
                        <span className="font-semibold">{LETTERS[q.correct_index ?? 0]}.</span> {q.explanation}
                      </p>
                    </details>
                  </>
                )}
              </li>
            ))}
          </ol>
          {p.tip && <p className="mt-3 rounded-lg bg-surface px-3 py-2 text-sm">Tip: {p.tip}</p>}
          <button
            type="button"
            className="btn-ghost mt-3 min-h-0 px-3 py-1 text-xs"
            disabled={reported.includes(p.id)}
            onClick={() => window.confirm("Report this post for abuse, personal details or copied text?") && report(p.id)}
          >
            <Flag size={12} aria-hidden /> {reported.includes(p.id) ? "Reported" : "Report"}
          </button>
        </article>
      ))}
    </div>
  );
}

export default function CompaniesPage() {
  const { candidate, loading } = useCandidate();
  const { open } = useAuth();
  const [companies, setCompanies] = useState<CompanySummary[] | null>(null);
  const [mine, setMine] = useState<MyPost[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const candidateId = candidate?.id;

  useEffect(() => {
    get<{ companies: CompanySummary[] }>("/api/companies").then(
      (r) => setCompanies(r.companies),
      (e: Error) => setError(e.message),
    );
  }, []);
  const loadMine = useCallback(() => {
    if (!candidateId) return setMine([]);
    get<{ posts: MyPost[] }>("/api/experiences/mine").then(
      (r) => setMine(r.posts),
      () => {},
    );
  }, [candidateId]);
  useEffect(loadMine, [loadMine]);

  const shown = useMemo(
    () => (companies ?? []).filter((c) => !search.trim() || c.name.toLowerCase().includes(search.trim().toLowerCase())),
    [companies, search],
  );

  return (
    <>
      <PageHeader
        eyebrow="Company questions"
        title="Interview questions, from students who were asked them"
        lead="Reported by students in their own words, by company and round, and approved by a moderator before anyone sees them. Practise them, or practise with AI questions in a company's style, always marked AI. Nothing here is copied from another website."
      />
      <ErrorNote message={error} />
      {selected && candidate ? (
        <Company slug={selected} onBack={() => setSelected(null)} />
      ) : (
        <section className="card" aria-labelledby="companies-title">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="companies-title" className="h2">
              Companies
            </h2>
            <label className="relative w-full max-w-xs">
              <span className="sr-only">Search companies</span>
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
              <input className="input pl-8" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
          </div>
          {!loading && !candidate && (
            <p className="mt-3 text-sm text-muted">
              <button type="button" className="font-medium text-primary-ink underline underline-offset-2" onClick={() => open("signin")}>
                Sign in
              </button>{" "}
              to read the posts and practise; anyone can see the counts.
            </p>
          )}
          {!companies && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}
          <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((c) => (
              <li key={c.slug}>
                <button
                  type="button"
                  disabled={!candidate}
                  onClick={() => setSelected(c.slug)}
                  className="w-full rounded-xl border border-hair px-4 py-3 text-left transition-colors hover:border-line disabled:cursor-default"
                >
                  <span className="block font-semibold">{c.name}</span>
                  <span className="block text-xs text-muted">
                    {c.posts ? `${c.posts} post${c.posts === 1 ? "" : "s"} · ${Object.keys(c.rounds).map((r) => ROUNDS[r]).join(", ")}` : "No posts yet"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {candidate && (
        <div className="mt-6 grid gap-6 lg:grid-cols-[3fr_2fr]">
          <ShareForm inOrg={Boolean(candidate.in_org)} onShared={loadMine} />
          <section className="card" aria-labelledby="mine-title">
            <h2 id="mine-title" className="font-semibold">
              My posts
            </h2>
            {mine.length === 0 ? (
              <p className="mt-2 text-sm text-muted">You have not shared an interview yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {mine.map((p) => (
                  <li key={p.id} className="rounded-xl border border-hair px-3 py-2 text-sm">
                    <p className="flex flex-wrap items-center gap-2">
                      <Badge state={STATUS[p.status].state}>{STATUS[p.status].text}</Badge>
                      <span className="font-medium">{p.company}</span>
                    </p>
                    <p className="text-xs text-muted">
                      {p.role} · {ROUNDS[p.round]} · {p.interview_month} · {p.questions} questions
                    </p>
                    {p.reject_reason && <p className="mt-1 text-xs">Moderator: {p.reject_reason}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </>
  );
}
