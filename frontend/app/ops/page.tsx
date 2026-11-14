"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Activity, Cpu, Database, LogOut, RefreshCw, ShieldAlert, Users } from "lucide-react";
import { ApiError, get } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";

type Row = Record<string, string | number | boolean | null>;
type Overview = {
  generated_at: number;
  totals: { students: number; verified: number; live_sessions: number; quiz_attempts: number; events_24h: Record<string, number> };
  students: Row[];
  events: Row[];
  sessions: Row[];
  ai_usage: Row[];
  providers: Row[];
  system: Record<string, unknown> & { sync: Record<string, unknown> };
};

const time = (v: unknown) => {
  if (v === null || v === undefined || v === "") return "—";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(String(v).replace(" ", "T") + (String(v).endsWith("Z") ? "" : "Z"));
  return isNaN(d.getTime()) ? String(v) : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
};
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));

const KIND_TONE: Record<string, string> = {
  sign_in_failed: "text-bad",
  code_wrong: "text-bad",
  code_required: "text-warn",
  new_device: "text-warn",
  ops_sign_in: "text-warn",
};

function Table({ rows, cols, empty }: { rows: Row[]; cols: [string, string, ((r: Row) => React.ReactNode)?][]; empty: string }) {
  if (!rows.length) return <p className="px-1 py-6 text-center text-sm text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-xs">
        <thead>
          <tr className="border-b border-hair text-muted">
            {cols.map(([key, label]) => (
              <th key={key} scope="col" className="whitespace-nowrap px-2 py-2 font-medium">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-hair/60 align-top">
              {cols.map(([key, , render]) => (
                <td key={key} className="whitespace-nowrap px-2 py-1.5 font-mono">
                  {render ? render(r) : show(r[key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Panel({ title, icon: Icon, children, right }: { title: string; icon: typeof Users; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="card" aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Icon size={15} aria-hidden /> {title}
        </h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export default function OpsPage() {
  const { ops, loading, signOut } = useCandidate();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [kind, setKind] = useState("");

  const load = useCallback(() => {
    get<Overview>("/api/ops/overview").then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => (e instanceof ApiError && e.status === 401 ? setDenied(true) : setError(e.message)),
    );
  }, []);

  useEffect(() => {
    if (loading) return;
    if (!ops) {
      setDenied(true);
      return;
    }
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [loading, ops, load]);

  const kinds = useMemo(() => [...new Set((data?.events ?? []).map((e) => String(e.kind)))].sort(), [data]);
  const events = (data?.events ?? []).filter((e) => !kind || e.kind === kind);

  if (denied)
    return (
      <main className="grid min-h-screen place-items-center px-6 text-center">
        <div>
          <p className="display text-5xl">404</p>
          <p className="mt-2 text-sm text-muted">This page could not be found.</p>
          <Link href="/" className="btn-ghost mt-6">
            Go home
          </Link>
        </div>
      </main>
    );

  const t = data?.totals;
  const sys = data?.system;
  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Skill Scout Nexus</p>
          <h1 className="display mt-1 text-3xl">Operations</h1>
          <p className="mt-1 text-xs text-muted">Updated {data ? time(data.generated_at) : "…"} · refreshes every 15 s</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={load}>
            <RefreshCw size={14} aria-hidden /> Refresh
          </button>
          <button
            type="button"
            className="btn-ink text-xs"
            onClick={async () => {
              await signOut();
              window.location.href = "/";
            }}
          >
            <LogOut size={14} aria-hidden /> Sign out
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="mb-4 rounded-xl border border-bad/40 p-3 text-sm text-bad">
          {error}
        </p>
      )}
      {!data ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="grid gap-4">
          <section aria-label="Totals" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Accounts", t!.students],
              ["Email confirmed", t!.verified],
              ["Live sessions", t!.live_sessions],
              ["Quiz attempts", t!.quiz_attempts],
            ].map(([label, value]) => (
              <div key={label} className="card py-4">
                <p className="text-xs text-muted">{label}</p>
                <p className="mt-1 font-mono text-2xl font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="System" icon={Cpu}>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                {[
                  ["Mode", sys!.mode],
                  ["Mock AI", sys!.mock_mode],
                  ["Engine", sys!.engine],
                  ["Models", `${(sys!.models as Row).large || "—"} / ${(sys!.models as Row).small || "—"}`],
                  ["Mail", sys!.mail],
                  ["App URL", sys!.app_url],
                  ["Preload allowed", sys!.preload_allowed],
                  ["Question bank", sys!.question_bank],
                  ["Database file", sys!.database],
                  ["Python", `${sys!.python} · ${sys!.platform}`],
                ].map(([k, v]) => (
                  <div key={String(k)} className="contents">
                    <dt className="text-muted">{String(k)}</dt>
                    <dd className="break-all font-mono">{show(v)}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
            <Panel title="Cloud sync and AI providers" icon={Database}>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                {Object.entries(sys!.sync).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted">{k.replace(/_/g, " ")}</dt>
                    <dd className="font-mono">{k.endsWith("_at") ? time(v as string) : show(v)}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-4">
                <Table
                  rows={data.providers}
                  cols={[
                    ["label", "Provider"],
                    ["state", "State"],
                    ["keys", "Keys"],
                    ["detail", "Detail"],
                  ]}
                  empty="No providers configured."
                />
              </div>
            </Panel>
          </div>

          <Panel title={`Accounts (${data.students.length})`} icon={Users}>
            <Table
              rows={data.students}
              cols={[
                ["username", "Username"],
                ["name", "Name"],
                ["email", "Email"],
                ["role", "Role"],
                ["readiness", "Readiness"],
                ["verified", "Confirmed"],
                ["status", "Status"],
                ["sessions", "Sessions"],
                ["quizzes", "Quizzes"],
                ["failures", "Wrong tries"],
                ["locked", "Locked"],
                ["last_sign_in", "Last sign-in", (r) => time(r.last_sign_in)],
                ["created_at", "Created", (r) => time(r.created_at)],
              ]}
              empty="No accounts yet."
            />
          </Panel>

          <Panel
            title="Sign-in activity"
            icon={Activity}
            right={
              <select className="input w-auto py-1 text-xs" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by event">
                <option value="">All events</option>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {k.replace(/_/g, " ")} {t!.events_24h[k] ? `(${t!.events_24h[k]} today)` : ""}
                  </option>
                ))}
              </select>
            }
          >
            <Table
              rows={events}
              cols={[
                ["at", "When", (r) => time(r.at)],
                ["kind", "Event", (r) => <span className={KIND_TONE[String(r.kind)] ?? ""}>{String(r.kind).replace(/_/g, " ")}</span>],
                ["who", "Who"],
                ["browser", "Browser"],
                ["os", "OS"],
                ["ip", "IP"],
                ["location", "Location"],
                ["detail", "Detail"],
              ]}
              empty="Nothing yet."
            />
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title={`Live sessions (${data.sessions.length})`} icon={ShieldAlert}>
              <Table
                rows={data.sessions}
                cols={[
                  ["username", "User"],
                  ["browser", "Browser"],
                  ["os", "OS"],
                  ["ip", "IP"],
                  ["location", "Location"],
                  ["last_seen", "Active", (r) => time(r.last_seen)],
                ]}
                empty="No one is signed in."
              />
            </Panel>
            <Panel title="AI usage" icon={Cpu}>
              <Table
                rows={data.ai_usage}
                cols={[
                  ["agent_name", "Agent"],
                  ["model_used", "Model"],
                  ["calls", "Calls"],
                  ["input_tokens", "In tokens"],
                  ["output_tokens", "Out tokens"],
                  ["avg_ms", "Avg ms"],
                  ["rejected", "Rejected"],
                ]}
                empty="No AI calls recorded yet."
              />
            </Panel>
          </div>
        </div>
      )}
    </main>
  );
}
