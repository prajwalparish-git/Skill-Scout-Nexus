"use client";

// Tab 4: the app and telemetry SQLite files, the cloud copy, maintenance and a read-only browser.
import { useCallback, useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  CloudUpload,
  Database,
  Download,
  EyeOff,
  HardDrive,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Table2,
  Undo2,
} from "lucide-react";
import { opsApi, type DbInfo, type DbOverview, type MaintenanceAction, type TablePage } from "@/lib/opsApi";
import { ActionButton, Facts, Notice, Panel, bytes, errText, show, time } from "./shared";

const PAGE = 50;

function DbCard({ info, title }: { info: DbInfo; title: string }) {
  const rows = (info.tables ?? []).reduce((a, t) => a + t.rows, 0);
  return (
    <Panel title={title} icon={HardDrive}>
      {!info.exists ? (
        <p className="text-xs text-muted">No file yet at {info.path} (created on first use).</p>
      ) : (
        <Facts
          items={[
            ["Path", info.path],
            ["Size", bytes(info.bytes)],
            ["WAL", bytes(info.wal_bytes)],
            ["Journal mode", info.journal_mode],
            ["Quick check", info.integrity],
            ["SQLite", info.sqlite_version],
            ["Tables / rows", `${info.tables?.length ?? 0} / ${rows}`],
            ...(info.error ? ([["Error", info.error]] as [string, unknown][]) : []),
          ]}
        />
      )}
    </Panel>
  );
}

export function DatabaseTab() {
  const [overview, setOverview] = useState<DbOverview | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [which, setWhich] = useState<"app" | "telemetry">("app");
  const [table, setTable] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TablePage | null>(null);
  const [tableError, setTableError] = useState<string | null>(null);

  const load = useCallback(() => {
    opsApi.dbOverview().then(setOverview, (e) => setNote({ ok: false, text: errText(e) }));
  }, []);
  useEffect(load, [load]);

  const tables = overview?.[which].tables ?? [];
  useEffect(() => {
    if (!table && tables.length) setTable(tables.find((t) => t.name === "students")?.name ?? tables[0].name);
  }, [tables, table]);

  useEffect(() => {
    if (!table) return;
    setTableError(null);
    opsApi.dbTable(which, table, PAGE, offset, query).then(setPage, (e) => {
      setPage(null);
      setTableError(errText(e));
    });
  }, [which, table, offset, query]);

  async function run(action: MaintenanceAction, label: string) {
    try {
      const r = await opsApi.dbMaintenance(action);
      setOverview(r.overview);
      const parts = Object.entries(r.result).map(([k, v]) => `${k}: ${v.ok ? "ok" : "failed"} (${show(v.detail)})`);
      setNote({ ok: Object.values(r.result).every((v) => v.ok), text: `${label} — ${parts.join(" · ")}` });
    } catch (e) {
      setNote({ ok: false, text: errText(e) });
    }
  }

  const sync = overview?.sync ?? {};
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {overview ? (
          <>
            <DbCard info={overview.app} title="App database" />
            <DbCard info={overview.telemetry} title="Telemetry database" />
            <Panel title="Cloud PostgreSQL sync" icon={CloudUpload}>
              <Facts items={Object.entries(sync).map(([k, v]) => [k.replace(/_/g, " "), k.endsWith("_at") ? time(v) : v])} />
            </Panel>
          </>
        ) : (
          <p className="text-sm text-muted">Loading…</p>
        )}
      </div>

      <Panel
        title="Maintenance"
        icon={ShieldCheck}
        lead="Integrity check and backups are read-only. Checkpoint and VACUUM briefly lock the file; run them when traffic is low."
        right={
          <ActionButton icon={RefreshCw} onRun={async () => load()}>
            Refresh
          </ActionButton>
        }
      >
        <div className="flex flex-wrap gap-2">
          <ActionButton icon={ShieldCheck} onRun={() => run("integrity_check", "Integrity check")}>
            Integrity check
          </ActionButton>
          <ActionButton icon={Database} onRun={() => run("checkpoint", "WAL checkpoint")}>
            WAL checkpoint
          </ActionButton>
          <ActionButton icon={Sparkles} confirm="VACUUM rewrites both database files. Continue?" onRun={() => run("vacuum", "Vacuum")}>
            Vacuum
          </ActionButton>
          <ActionButton icon={CloudUpload} onRun={() => run("sync_now", "Force cloud sync")}>
            Force cloud sync
          </ActionButton>
          <ActionButton icon={Undo2} onRun={() => run("retry_set_aside", "Retry set-aside")}>
            Retry set-aside
          </ActionButton>
          <ActionButton icon={Download} onRun={() => opsApi.dbBackup("app").catch((e) => setNote({ ok: false, text: errText(e) }))}>
            App DB backup
          </ActionButton>
          <ActionButton icon={Download} onRun={() => opsApi.dbBackup("telemetry").catch((e) => setNote({ ok: false, text: errText(e) }))}>
            Telemetry DB backup
          </ActionButton>
        </div>
        <Notice note={note} />
      </Panel>

      <Panel
        title="Table browser (read-only)"
        icon={Table2}
        lead="Newest rows first. Columns that could hold a secret (password, hash, salt, token, key, code, …) are redacted and never searched."
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="segmented" role="radiogroup" aria-label="Database">
            {(["app", "telemetry"] as const).map((w) => (
              <button
                key={w}
                type="button"
                role="radio"
                aria-checked={which === w}
                className={`segment px-3 py-1 text-xs capitalize ${which === w ? "bg-ink text-bg hover:text-bg" : ""}`}
                onClick={() => {
                  setWhich(w);
                  setTable("");
                  setOffset(0);
                  setPage(null);
                }}
              >
                {w}
              </button>
            ))}
          </div>
          <select
            className="input w-auto py-1.5 text-xs"
            value={table}
            onChange={(e) => {
              setTable(e.target.value);
              setOffset(0);
            }}
            aria-label="Table"
          >
            {tables.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.rows})
              </option>
            ))}
          </select>
          <form
            className="relative ml-auto"
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setQuery(search);
            }}
          >
            <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
            <input
              type="search"
              className="input w-56 py-1.5 pl-8 text-xs"
              placeholder="Search rows, press Enter"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search rows"
            />
          </form>
        </div>
        {tableError && <p className="mt-3 text-xs text-bad">{tableError}</p>}
        {page && (
          <>
            {page.redacted.length > 0 && (
              <p className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                <EyeOff size={12} aria-hidden /> Redacted:
                {page.redacted.map((c) => (
                  <span key={c} className="chip border-warn/40 text-warn">
                    {c}
                  </span>
                ))}
              </p>
            )}
            <div className="mt-3 overflow-x-auto rounded-xl border border-hair">
              <table className="w-full text-left text-[11px]" style={{ minWidth: Math.max(560, page.columns.length * 120) }}>
                <thead className="bg-surface/60">
                  <tr>
                    {page.columns.map((c) => (
                      <th key={c} scope="col" className={`whitespace-nowrap px-2 py-1.5 font-medium ${page.redacted.includes(c) ? "text-warn" : "text-muted"}`}>
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {page.rows.map((r, i) => (
                    <tr key={i} className="border-t border-hair/60 align-top">
                      {page.columns.map((c) => (
                        <td key={c} className={`max-w-[18rem] truncate px-2 py-1 font-mono ${r[c] === "[REDACTED]" ? "text-warn" : ""}`} title={show(r[c])}>
                          {show(r[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {!page.rows.length && <p className="px-3 py-6 text-center text-xs text-muted">No rows.</p>}
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-muted">
              <span>
                {page.total ? `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)} of ${page.total}` : "0 rows"}
                {query && ` matching “${query}”`}
              </span>
              <span className="flex gap-1.5">
                <button type="button" className="btn-ghost min-h-[1.9rem] px-2.5 py-1 text-xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                  <ChevronLeft size={13} aria-hidden /> Prev
                </button>
                <button
                  type="button"
                  className="btn-ghost min-h-[1.9rem] px-2.5 py-1 text-xs"
                  disabled={offset + PAGE >= page.total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Next <ChevronRight size={13} aria-hidden />
                </button>
              </span>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
