"use client";

// Tab 5: the live server log, the auth & ops audit events and the local mail outbox.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Download, Inbox, RefreshCw, ScrollText, Trash2 } from "lucide-react";
import { opsApi, type LogRecord, type Outbox, type Overview } from "@/lib/opsApi";
import { ActionButton, Notice, Panel, Table, bytes, errText, time } from "./shared";

const LEVEL_TONE: Record<string, string> = { DEBUG: "text-muted", INFO: "text-info", WARNING: "text-warn", ERROR: "text-bad", CRITICAL: "text-bad" };
const KIND_TONE: Record<string, string> = {
  sign_in_failed: "text-bad",
  code_wrong: "text-bad",
  ops_sign_in_failed: "text-bad",
  code_required: "text-warn",
  new_device: "text-warn",
  ops_sign_in: "text-warn",
  ops_action: "text-info",
};

function ServerLogs() {
  const [level, setLevel] = useState("");
  const [logger, setLogger] = useState("");
  const [search, setSearch] = useState("");
  const [auto, setAuto] = useState(true);
  const [records, setRecords] = useState<LogRecord[]>([]);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    opsApi.logs(level, logger, search).then(
      (r) => setRecords(r.records),
      (e) => setNote({ ok: false, text: errText(e) }),
    );
  }, [level, logger, search]);

  useEffect(() => {
    load();
    if (!auto) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load, auto]);

  return (
    <Panel
      title="Live server logs"
      icon={ScrollText}
      lead="The last 1,000 records held in memory (newest first). Tokens, API keys, database passwords and secret=… pairs are redacted before storage."
      right={
        <>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="accent-current" /> Auto-refresh 5 s
          </label>
          <ActionButton icon={RefreshCw} onRun={async () => load()}>
            Refresh
          </ActionButton>
          <ActionButton icon={Download} onRun={() => opsApi.logsDownload().catch((e) => setNote({ ok: false, text: errText(e) }))}>
            .log
          </ActionButton>
          <ActionButton
            icon={Trash2}
            tone="danger"
            confirm="Clear the in-memory log buffer?"
            onRun={async () => {
              const r = await opsApi.logsClear();
              setNote({ ok: true, text: `Cleared ${r.cleared} record(s).` });
              load();
            }}
          >
            Clear
          </ActionButton>
        </>
      }
    >
      <div className="flex flex-wrap gap-2">
        <select className="input w-auto py-1.5 text-xs" value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Minimum level">
          <option value="">All levels</option>
          {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => (
            <option key={l} value={l}>
              {l} and above
            </option>
          ))}
        </select>
        <input className="input w-44 py-1.5 text-xs" placeholder="Logger prefix (e.g. core.)" value={logger} onChange={(e) => setLogger(e.target.value)} aria-label="Logger prefix" />
        <input className="input w-56 py-1.5 text-xs" type="search" placeholder="Search messages" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search messages" />
        <span className="ml-auto self-center font-mono text-[11px] text-muted">{records.length} shown</span>
      </div>
      <Notice note={note} />
      <div className="mt-3 max-h-[28rem] overflow-auto rounded-xl border border-hair bg-surface/40 p-2 font-mono text-[11px] leading-relaxed">
        {records.length === 0 ? (
          <p className="p-4 text-center text-muted">No log records match.</p>
        ) : (
          records.map((r) => (
            <div key={r.id} className="grid grid-cols-[auto_auto_auto_1fr] gap-x-2 border-b border-hair/50 px-1 py-0.5 last:border-0">
              <span className="text-muted">{time(r.ts)}</span>
              <span className={`w-16 font-semibold ${LEVEL_TONE[r.level] ?? ""}`}>{r.level}</span>
              <span className="max-w-[12rem] truncate text-muted">{r.logger}</span>
              <span className="whitespace-pre-wrap break-words">{r.message}</span>
            </div>
          ))
        )}
      </div>
    </Panel>
  );
}

function AuditEvents({ events, today }: { events: Overview["events"]; today: Record<string, number> }) {
  const [kind, setKind] = useState("");
  const kinds = useMemo(() => [...new Set(events.map((e) => String(e.kind)))].sort(), [events]);
  const rows = events.filter((e) => !kind || e.kind === kind);
  return (
    <Panel
      title="Auth & ops audit events"
      icon={Activity}
      lead="Sign-ins, codes, new devices and every change made from this console (ops_action)."
      right={
        <select className="input w-auto py-1 text-xs" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by event">
          <option value="">All events</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {k.replace(/_/g, " ")} {today[k] ? `(${today[k]} today)` : ""}
            </option>
          ))}
        </select>
      }
    >
      <Table
        rows={rows}
        cols={[
          ["at", "When", (r) => time(r.at)],
          ["kind", "Event", (r) => <span className={KIND_TONE[String(r.kind)] ?? ""}>{String(r.kind).replace(/_/g, " ")}</span>],
          ["who", "Who"],
          ["detail", "Detail"],
          ["browser", "Browser"],
          ["os", "OS"],
          ["ip", "IP"],
          ["location", "Location"],
        ]}
        empty="Nothing yet."
      />
    </Panel>
  );
}

function MailOutbox() {
  const [box, setBox] = useState<Outbox | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => {
    opsApi.outbox().then(setBox, (e) => setNote({ ok: false, text: errText(e) }));
  }, []);
  useEffect(load, [load]);
  return (
    <Panel
      title="Local mail outbox"
      icon={Inbox}
      lead="Emails written to MAIL_OUTBOX_PATH when SMTP is not configured (and welcome emails always). It can hold sign-in codes and temporary passwords: clear it after use."
      right={
        <>
          <ActionButton icon={RefreshCw} onRun={async () => load()}>
            Refresh
          </ActionButton>
          <ActionButton
            icon={Trash2}
            tone="danger"
            confirm="Empty the local mail outbox file?"
            onRun={async () => {
              const r = await opsApi.outboxClear();
              setNote({ ok: true, text: `Cleared ${bytes(r.cleared_bytes)}.` });
              load();
            }}
          >
            Clear
          </ActionButton>
        </>
      }
    >
      {box && (
        <p className="font-mono text-[11px] text-muted">
          {box.path} · {box.exists ? `${bytes(box.bytes)}, ${box.lines} lines (last 300 shown)` : "no file yet"}
        </p>
      )}
      <Notice note={note} />
      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-hair bg-surface/40 p-3 font-mono text-[11px] leading-relaxed">
        {box?.text || "The outbox is empty."}
      </pre>
    </Panel>
  );
}

export function LogsTab({ data }: { data: Overview }) {
  return (
    <div className="grid grid-cols-1 gap-4">
      <ServerLogs />
      <AuditEvents events={data.events} today={data.totals.events_24h} />
      <MailOutbox />
    </div>
  );
}
