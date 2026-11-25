"use client";

// Tab 1: health at a glance: KPIs, the system and engine, AI providers and token usage, sessions.
import Link from "next/link";
import { Activity, BookOpen, Cpu, Database, ShieldAlert, Sparkles, Users } from "lucide-react";
import type { Overview, Row } from "@/lib/opsApi";
import { Facts, Kpi, Panel, Table, show, time } from "./shared";

const compact = (n: number) => (n < 1000 ? String(n) : n < 1_000_000 ? `${(n / 1000).toFixed(1)}k` : `${(n / 1_000_000).toFixed(1)}M`);

export function OverviewTab({ data }: { data: Overview }) {
  const t = data.totals;
  const sys = data.system;
  const tokens = { calls: 0, input: 0, output: 0 };
  for (const r of data.ai_usage) {
    tokens.calls += Number(r.calls ?? 0);
    tokens.input += Number(r.input_tokens ?? 0);
    tokens.output += Number(r.output_tokens ?? 0);
  }
  const events24 = Object.values(t.events_24h).reduce((a, b) => a + b, 0);
  return (
    <div className="grid grid-cols-1 gap-4">
      <section aria-label="Totals" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Accounts" value={t.students} icon={Users} hint={`${t.verified} email confirmed`} />
        <Kpi label="Live sessions" value={t.live_sessions} icon={ShieldAlert} />
        <Kpi label="Quiz attempts" value={t.quiz_attempts} icon={Activity} />
        <Kpi label="Sign-in events (24 h)" value={events24} icon={Activity} />
        <Kpi label="AI calls" value={tokens.calls} icon={Sparkles} />
        <Kpi label="AI tokens" value={compact(tokens.input + tokens.output)} icon={Cpu} hint={`${compact(tokens.input)} in · ${compact(tokens.output)} out`} />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel
          title="System & engine"
          icon={Cpu}
          right={
            <Link href="/docs?tab=developers" className="btn-ghost min-h-[2rem] px-3 py-1 text-xs">
              <BookOpen size={13} aria-hidden /> Developer guide
            </Link>
          }
        >
          <Facts
            items={[
              ["Mode", sys.mode],
              ["Mock AI", sys.mock_mode],
              ["Engine", sys.engine],
              ["Models", `${sys.models?.large || "—"} / ${sys.models?.small || "—"}`],
              ["Mail", sys.mail],
              ["App URL", sys.app_url],
              ["Preload allowed", sys.preload_allowed],
              ["Question bank", sys.question_bank],
              ["Database file", sys.database],
              ["Python", `${show(sys.python)} · ${show(sys.platform)}`],
            ]}
          />
        </Panel>
        <Panel title="Cloud sync & AI providers" icon={Database}>
          <Facts items={Object.entries(sys.sync).map(([k, v]) => [k.replace(/_/g, " "), k.endsWith("_at") ? time(v) : v])} />
          <div className="mt-4">
            <Table
              minWidth={420}
              rows={data.providers}
              cols={[
                ["label", "Provider"],
                [
                  "state",
                  "State",
                  (r: Row) => (
                    <span className={r.state === "ready" ? "text-ok" : r.state === "paused" ? "text-warn" : "text-muted"}>{show(r.state)}</span>
                  ),
                ],
                ["keys", "Keys"],
                ["detail", "Detail"],
              ]}
              empty="No providers configured."
            />
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="AI usage by agent" icon={Sparkles}>
          <Table
            minWidth={520}
            rows={data.ai_usage}
            cols={[
              ["agent_name", "Agent"],
              ["model_used", "Model"],
              ["calls", "Calls"],
              ["input_tokens", "In"],
              ["output_tokens", "Out"],
              ["avg_ms", "Avg ms"],
              ["rejected", "Rejected"],
            ]}
            empty="No AI calls recorded yet."
          />
        </Panel>
        <Panel title={`Live sessions (${data.sessions.length})`} icon={ShieldAlert}>
          <Table
            minWidth={520}
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
      </div>
    </div>
  );
}
