"use client";

// The developer console: a DEV_SECRET sign-in gate, then seven tabs over /api/ops/*.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  Database,
  FolderGit2,
  Gauge,
  ListChecks,
  LogOut,
  RefreshCw,
  ScrollText,
  Settings2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { ApiError } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { opsApi, type Overview } from "@/lib/opsApi";
import { Brand } from "@/components/site/Brand";
import { Loading } from "@/components/ui";
import { OpsLogin } from "@/components/ops/OpsLogin";
import { OverviewTab } from "@/components/ops/OverviewTab";
import { QuestionsTab } from "@/components/ops/QuestionsTab";
import { GithubTab } from "@/components/ops/GithubTab";
import { DatabaseTab } from "@/components/ops/DatabaseTab";
import { LogsTab } from "@/components/ops/LogsTab";
import { ModerationTab } from "@/components/ops/ModerationTab";
import { SettingsTab } from "@/components/ops/SettingsTab";
import { time } from "@/components/ops/shared";

type Tab = "overview" | "questions" | "github" | "database" | "logs" | "moderation" | "settings";
const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "questions", label: "Question Banks", icon: ListChecks },
  { id: "github", label: "GitHub Data", icon: FolderGit2 },
  { id: "database", label: "Database", icon: Database },
  { id: "logs", label: "Logs & Outbox", icon: ScrollText },
  { id: "moderation", label: "Moderation & Users", icon: ShieldCheck },
  { id: "settings", label: "Settings & Caches", icon: Settings2 },
];

export default function OpsPage() {
  const { ops, loading, reload, signOut } = useCandidate();
  const [signedIn, setSignedIn] = useState(false);
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    if (!loading) setSignedIn(ops);
  }, [loading, ops]);

  const load = useCallback(() => {
    opsApi.overview().then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => {
        if (e instanceof ApiError && e.status === 401) {
          setSignedIn(false);
          setData(null);
        } else setError(e.message);
      },
    );
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [signedIn, load]);

  const signedOut = useCallback(() => {
    setSignedIn(false);
    setData(null);
    setTab("overview");
    reload();
  }, [reload]);

  if (loading)
    return (
      <main className="mx-auto max-w-7xl px-4 py-10 sm:px-8">
        <Loading label="Loading the developer console" />
      </main>
    );

  if (!signedIn)
    return (
      <OpsLogin
        onSignedIn={() => {
          setSignedIn(true);
          reload();
        }}
      />
    );

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-hair bg-bg/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-8">
          <Link href="/" className="rounded-lg text-ink" aria-label="Skill Scout Nexus, home">
            <Brand height={12} />
          </Link>
          <span className="chip border-warn/40 font-mono text-[10px] uppercase tracking-[0.14em] text-warn">Developer Console</span>
          <span className="hidden font-mono text-[11px] text-muted md:inline">Updated {data ? time(data.generated_at) : "…"} · every 15 s</span>
          <div className="ml-auto flex gap-2">
            <Link href="/docs?tab=developers" className="btn-ghost min-h-[2.1rem] px-3 py-1.5 text-xs">
              <BookOpen size={13} aria-hidden /> <span className="hidden sm:inline">Docs</span>
            </Link>
            <button type="button" className="btn-ghost min-h-[2.1rem] px-3 py-1.5 text-xs" onClick={load}>
              <RefreshCw size={13} aria-hidden /> <span className="hidden sm:inline">Refresh</span>
            </button>
            <button
              type="button"
              className="btn-ink min-h-[2.1rem] px-3 py-1.5 text-xs"
              onClick={async () => {
                await signOut();
                signedOut();
              }}
            >
              <LogOut size={13} aria-hidden /> Sign out
            </button>
          </div>
        </div>
        <nav aria-label="Console sections" className="mx-auto max-w-7xl overflow-x-auto px-4 sm:px-8">
          <div role="tablist" className="flex gap-1 pb-2">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`ops-tab-${id}`}
                aria-selected={tab === id}
                aria-controls="ops-panel"
                onClick={() => setTab(id)}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors ${
                  tab === id ? "bg-ink text-bg" : "text-muted hover:bg-surface hover:text-ink"
                }`}
              >
                <Icon size={13} aria-hidden /> {label}
              </button>
            ))}
          </div>
        </nav>
      </header>

      <main id="main-content" className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8">
        <h1 className="sr-only">Developer Console — {TABS.find((t) => t.id === tab)?.label}</h1>
        {error && (
          <p role="alert" className="mb-4 rounded-xl border border-bad/40 p-3 text-sm text-bad">
            {error}
          </p>
        )}
        <div id="ops-panel" role="tabpanel" aria-labelledby={`ops-tab-${tab}`}>
          {tab === "questions" ? (
            <QuestionsTab />
          ) : tab === "github" ? (
            <GithubTab />
          ) : tab === "database" ? (
            <DatabaseTab />
          ) : tab === "settings" ? (
            <SettingsTab onSignedOut={signedOut} signOut={signOut} />
          ) : !data ? (
            <Loading label="Loading the overview" />
          ) : tab === "overview" ? (
            <OverviewTab data={data} />
          ) : tab === "logs" ? (
            <LogsTab data={data} />
          ) : (
            <ModerationTab data={data} reload={load} />
          )}
        </div>
      </main>
    </div>
  );
}
