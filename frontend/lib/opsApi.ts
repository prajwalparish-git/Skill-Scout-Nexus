// Typed client for the developer console (routers/ops.py, /api/ops/*). Every call needs the
// HttpOnly ssn_ops cookie set by POST /api/auth/ops-login.
import { download, get, post, qs, upload } from "./api";

export type Row = Record<string, string | number | boolean | null>;

export type Overview = {
  generated_at: number;
  totals: { students: number; verified: number; live_sessions: number; quiz_attempts: number; events_24h: Record<string, number> };
  students: Row[];
  events: Row[];
  sessions: Row[];
  ai_usage: Row[];
  providers: Row[];
  system: Record<string, unknown> & { sync: Record<string, unknown>; models: { large: string; small: string } };
};

export type CsvError = { line: number; error: string; question: string };
export type CsvSummary = {
  total_rows: number;
  valid_count: number;
  duplicate_count: number;
  invalid_count: number;
  updated_count?: number;
  sample_valid: Row[];
  errors: CsvError[];
  warnings: string[];
  mode: string;
  imported?: number;
  backup?: string | null;
};

export type QuestionStats = {
  mcq: { file: string; rows: number; by_difficulty: Record<string, number>; topics: number; streams: number; served: number; by_source: Record<string, number>; bytes: number };
  interview: { file: string; questions: number; by_round: Record<string, number>; by_source: Record<string, number>; bytes: number };
  backups: { name: string; bytes: number }[];
};

export type GithubStats = {
  repos: { topics: number; repos: number; by_kind: Record<string, number>; fetched: string };
  skills: number;
  skills_without_topic: number;
  orgs: number;
  cache_rows: number;
  token: boolean;
};

export type DbInfo = {
  which: "app" | "telemetry";
  path: string;
  exists: boolean;
  bytes: number;
  wal_bytes: number;
  sqlite_version: string;
  journal_mode?: string;
  integrity?: string;
  tables?: { name: string; rows: number }[];
  error?: string;
};
export type DbOverview = { app: DbInfo; telemetry: DbInfo; sync: Record<string, unknown> };
export type TablePage = { which: string; table: string; columns: string[]; redacted: string[]; rows: Row[]; total: number; limit: number; offset: number };
export type MaintenanceAction = "integrity_check" | "checkpoint" | "vacuum" | "sync_now" | "retry_set_aside";
export type MaintenanceResult = { action: MaintenanceAction; result: Record<string, { ok: boolean; detail: unknown }>; overview: DbOverview };

export type LogRecord = { id: number; ts: number; level: string; logger: string; message: string };
export type LogsPayload = { records: LogRecord[]; capacity: number; levels: string[] };
export type Outbox = { path: string; exists: boolean; bytes: number; lines: number; text: string; smtp?: boolean };

export type SettingRow = { name: string; category: string; configured: boolean; secret: boolean; display_value: string };
export type CacheMetrics = {
  ai: { entries: number; bytes: number; enabled: boolean };
  preload: { entries: number; bytes: number; enabled: boolean };
  github: { entries: number };
  question_bank: { entries: number };
  sessions: { live: number; ops: number };
};
export type SettingsPayload = {
  settings: SettingRow[];
  key_pools: { groq: number; gemini: number };
  providers: { name: string; label: string; state: string; keys: number }[];
  caches: CacheMetrics;
  mail: string;
};
export type CacheTarget = "ai" | "preload" | "github" | "question_bank" | "all";
export type OrgRow = {
  id: number;
  org_code: string;
  name: string;
  type: string;
  admin_name: string;
  admin_email: string;
  verified: boolean;
  students: number;
  proctoring: string;
  created_at: string;
};

/** One CSV-managed data file: where its template, export, preview and import live. */
export type CsvKind = {
  key: string;
  base: string; // e.g. /api/ops/questions/mcq
  modes: readonly [string, string];
  exportable: boolean;
  file: string; // the template's download name
};

export const CSV_KINDS = {
  mcq: { key: "mcq", base: "/api/ops/questions/mcq", modes: ["append", "replace"], exportable: true, file: "mcq_template.csv" },
  interview: { key: "interview", base: "/api/ops/questions/interview", modes: ["append", "replace"], exportable: false, file: "interview_template.csv" },
  repos: { key: "repos", base: "/api/ops/github/repos", modes: ["merge", "replace"], exportable: true, file: "github_repos_template.csv" },
  topics: { key: "topics", base: "/api/ops/github/topics", modes: ["merge", "replace"], exportable: true, file: "github_topics_template.csv" },
  orgs: { key: "orgs", base: "/api/ops/github/orgs", modes: ["merge", "replace"], exportable: true, file: "company_orgs_template.csv" },
} as const satisfies Record<string, CsvKind>;

const form = (file: File, mode: string) => {
  const f = new FormData();
  f.append("file", file);
  f.append("mode", mode);
  return f;
};

export const opsApi = {
  login: (password: string) => post<{ ops: boolean }>("/api/auth/ops-login", { password }),
  logoutAll: () => post<{ revoked: number }>("/api/ops/logout-all", {}),
  overview: () => get<Overview>("/api/ops/overview"),

  questionStats: () => get<QuestionStats>("/api/ops/questions/stats"),
  githubStats: () => get<GithubStats>("/api/ops/github/stats"),
  csvTemplate: (k: CsvKind) => download(`${k.base}/template`, k.file),
  csvExport: (k: CsvKind) => download(`${k.base}/export`, k.file.replace("_template", "")),
  csvPreview: (k: CsvKind, file: File, mode: string) => upload<CsvSummary>(`${k.base}/preview`, form(file, mode)),
  csvImport: (k: CsvKind, file: File, mode: string) => upload<CsvSummary>(`${k.base}/import`, form(file, mode)),

  dbOverview: () => get<DbOverview>("/api/ops/db/overview"),
  dbTable: (which: string, table: string, limit: number, offset: number, search: string) =>
    get<TablePage>(`/api/ops/db/table?${qs({ which, table, limit, offset, search })}`),
  dbMaintenance: (action: MaintenanceAction) => post<MaintenanceResult>("/api/ops/db/maintenance", { action }),
  dbBackup: (which: "app" | "telemetry") => download(`/api/ops/db/backup/${which}`, `${which}-backup.db`),

  logs: (level: string, logger: string, search: string, limit = 300) => get<LogsPayload>(`/api/ops/logs?${qs({ level, logger, search, limit })}`),
  logsDownload: () => download("/api/ops/logs/download", "server.log"),
  logsClear: () => post<{ cleared: number }>("/api/ops/logs/clear", {}),
  outbox: (tail = 300) => get<Outbox>(`/api/ops/mail-outbox?${qs({ tail })}`),
  outboxClear: () => post<{ cleared_bytes: number }>("/api/ops/mail-outbox/clear", {}),

  settings: () => get<SettingsPayload>("/api/ops/settings"),
  cacheClear: (target: CacheTarget) => post<{ target: string; cleared: Record<string, number>; after: CacheMetrics }>("/api/ops/cache/clear", { target }),
  smtpTest: () => post<{ ok: boolean; configured: boolean; detail: string }>("/api/ops/smtp/test", {}),
  orgs: () => get<{ organizations: OrgRow[] }>("/api/ops/orgs"),
  unlock: (username: string) => post<{ unlocked: boolean }>(`/api/ops/students/${encodeURIComponent(username)}/unlock`, {}),
  revokeSessions: (username: string) => post<{ revoked: number }>(`/api/ops/students/${encodeURIComponent(username)}/revoke-sessions`, {}),
  setStatus: (username: string, status: "active" | "suspended") =>
    post<{ status: string; revoked: number }>(`/api/ops/students/${encodeURIComponent(username)}/status`, { status }),
};
