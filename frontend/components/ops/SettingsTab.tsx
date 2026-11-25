"use client";

// Tab 7: the masked configuration matrix, key pools, Test SMTP, cache controls and ops security.
import { useCallback, useEffect, useState } from "react";
import { BookCheck, Brain, Eraser, FolderGit2, KeyRound, Layers, LogOut, Mail, Settings2, ShieldOff, Timer } from "lucide-react";
import { opsApi, type CacheTarget, type SettingsPayload } from "@/lib/opsApi";
import { ActionButton, Notice, Panel, bytes, errText } from "./shared";

export function SettingsTab({ onSignedOut, signOut }: { onSignedOut: () => void; signOut: () => Promise<void> }) {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [smtp, setSmtp] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    opsApi.settings().then(setData, (e) => setNote({ ok: false, text: errText(e) }));
  }, []);
  useEffect(load, [load]);

  const clear = (target: CacheTarget, label: string) => async () => {
    try {
      const r = await opsApi.cacheClear(target);
      const parts = Object.entries(r.cleared).map(([k, v]) => `${k}: ${v}`);
      setNote({ ok: true, text: `${label} cleared (${parts.join(", ")}).` });
      load();
    } catch (e) {
      setNote({ ok: false, text: errText(e) });
    }
  };

  const groups = data
    ? data.settings.reduce<Record<string, SettingsPayload["settings"]>>((acc, s) => {
        (acc[s.category] ??= []).push(s);
        return acc;
      }, {})
    : {};
  const c = data?.caches;
  const caches: { target: CacheTarget; label: string; icon: typeof Brain; value: string; hint: string }[] = c
    ? [
        { target: "ai", label: "AI cache", icon: Brain, value: `${c.ai.entries}`, hint: `${bytes(c.ai.bytes)} · ${c.ai.enabled ? "on" : "off"}` },
        { target: "preload", label: "Preload cache", icon: Timer, value: `${c.preload.entries}`, hint: `${bytes(c.preload.bytes)} · ${c.preload.enabled ? "on" : "off"}` },
        { target: "github", label: "GitHub search cache", icon: FolderGit2, value: `${c.github.entries}`, hint: "cached queries (24 h)" },
        { target: "question_bank", label: "Question bank cache", icon: BookCheck, value: `${c.question_bank.entries}`, hint: "questions loaded; reloads from disk" },
      ]
    : [];

  return (
    <div className="grid grid-cols-1 gap-4">
      <Panel
        title="Environment & providers"
        icon={Settings2}
        lead="What this server was started with. Secrets only ever show as “Configured (masked)” or “Not set”; change them in .env or the host's secret settings and restart."
        right={
          <span className="font-mono text-[11px] text-muted">
            Groq keys {data?.key_pools.groq ?? "…"} · Gemini keys {data?.key_pools.gemini ?? "…"} · mail: {data?.mail ?? "…"}
          </span>
        }
      >
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Object.entries(groups).map(([cat, rows]) => (
            <div key={cat} className="rounded-xl border border-hair">
              <p className="eyebrow border-b border-hair px-3 py-2">{cat}</p>
              <dl className="divide-y divide-hair/60 text-xs">
                {rows.map((s) => (
                  <div key={s.name} className="grid grid-cols-[minmax(0,13rem)_1fr] gap-3 px-3 py-1.5">
                    <dt className="flex items-center gap-1.5 font-mono text-[11px] text-ink">
                      {s.secret && <KeyRound size={11} className="shrink-0 text-muted" aria-label="secret" />}
                      <span className="truncate">{s.name}</span>
                    </dt>
                    <dd className={`break-all font-mono text-[11px] ${s.configured ? (s.secret ? "text-ok" : "text-ink") : "text-muted"}`}>{s.display_value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
        {data && (
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-hair pt-4">
            {data.providers.map((p) => (
              <span key={p.name} className={`chip ${p.state === "ready" ? "border-ok/40 text-ok" : p.state === "paused" ? "border-warn/40 text-warn" : "border-line text-muted"}`}>
                {p.label}: {p.state}
                {p.keys ? ` · ${p.keys} key${p.keys > 1 ? "s" : ""}` : ""}
              </span>
            ))}
            <ActionButton
              icon={Mail}
              className="ml-auto"
              onRun={async () => {
                try {
                  const r = await opsApi.smtpTest();
                  setSmtp({ ok: r.ok, text: r.detail });
                } catch (e) {
                  setSmtp({ ok: false, text: errText(e) });
                }
              }}
            >
              Test SMTP
            </ActionButton>
          </div>
        )}
        <Notice note={smtp} />
      </Panel>

      <Panel title="Caches" icon={Layers} lead="Clearing a cache is safe: the next request rebuilds it (AI answers cost a new call).">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {caches.map((k) => (
            <div key={k.target} className="flex flex-col rounded-xl border border-hair p-3">
              <p className="flex items-center gap-1.5 text-xs text-muted">
                <k.icon size={13} aria-hidden /> {k.label}
              </p>
              <p className="mt-1 font-mono text-xl font-semibold tabular-nums">{k.value}</p>
              <p className="text-[11px] text-muted">{k.hint}</p>
              <ActionButton icon={Eraser} className="mt-3 self-start" onRun={clear(k.target, k.label)}>
                Clear
              </ActionButton>
            </div>
          ))}
          {c && (
            <div className="flex flex-col rounded-xl border border-bad/30 p-3">
              <p className="flex items-center gap-1.5 text-xs text-muted">
                <Eraser size={13} aria-hidden /> Everything
              </p>
              <p className="mt-1 text-[11px] text-muted">
                {c.sessions.live} live student session(s) · {c.sessions.ops} console session(s) are not affected.
              </p>
              <ActionButton icon={Eraser} tone="danger" className="mt-auto self-start" confirm="Clear every cache?" onRun={clear("all", "All caches")}>
                Clear all
              </ActionButton>
            </div>
          )}
        </div>
        <Notice note={note} />
      </Panel>

      <Panel title="Ops security" icon={ShieldOff} lead="Console sessions last 12 hours. Revoking signs out every browser that holds one, this one included.">
        <div className="flex flex-wrap gap-2">
          <ActionButton
            icon={ShieldOff}
            tone="danger"
            confirm="Sign out every developer-console session (including this one)?"
            onRun={async () => {
              await opsApi.logoutAll();
              onSignedOut();
            }}
          >
            Revoke all ops sessions
          </ActionButton>
          <ActionButton
            icon={LogOut}
            onRun={async () => {
              await signOut();
              onSignedOut();
            }}
          >
            Sign out
          </ActionButton>
        </div>
      </Panel>
    </div>
  );
}
