"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Cpu, ExternalLink, HardDrive, KeyRound, Laptop, Loader2, LogOut, MonitorSmartphone, PlugZap, Smartphone, SlidersHorizontal } from "lucide-react";
import {
  get,
  post,
  type DeviceSession,
  type DriveStatus,
  type LocalAIPayload,
  type LocalAIProvider,
  type Prefs,
  type SettingsPayload,
  type Student,
} from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { useDrive } from "@/lib/drive";
import { ProctorRecord } from "@/components/proctor/Record";
import { ErrorNote, Loading, NeedsCandidate, PageHeader } from "@/components/ui";

const when = (raw: string | number | null) => {
  if (raw === null || raw === "") return "—";
  const d = typeof raw === "number" ? new Date(raw * 1000) : new Date(raw.replace(" ", "T") + (raw.endsWith("Z") ? "" : "Z"));
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

function Switch({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-t border-hair py-4 first:border-t-0 first:pt-0">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="mt-0.5 text-xs text-muted">{hint}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors disabled:opacity-40 ${
          checked ? "border-ink bg-ink" : "border-hair bg-surface"
        }`}
      >
        <span
          aria-hidden
          className={`absolute top-0.5 h-[18px] w-[18px] rounded-full transition-all ${checked ? "left-[22px] bg-bg" : "left-0.5 bg-muted"}`}
        />
      </button>
    </div>
  );
}

function Preferences() {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    get<SettingsPayload>("/api/auth/settings").then(setData, (e: Error) => setError(e.message));
  }, []);
  const save = async (change: Partial<Prefs>) => {
    if (!data) return;
    const before = data;
    setData({ ...data, prefs: { ...data.prefs, ...change } }); // shown at once, confirmed below
    try {
      setData(await post<SettingsPayload>("/api/auth/settings", change));
      setError(null);
    } catch (e) {
      setData(before); // not saved: show the setting as it still is
      setError((e as Error).message);
    }
  };
  return (
    <section className="card" aria-labelledby="prefs-title">
      <h2 id="prefs-title" className="flex items-center gap-2 font-semibold">
        <SlidersHorizontal size={16} aria-hidden /> Preferences
      </h2>
      <div className="mt-4">
        {!data && !error && <p className="text-sm text-muted">Loading…</p>}
        {data && (
          <>
            <Switch
              label="Prepare my next steps in the background"
              hint={
                data.preload_allowed
                  ? "Writes your roadmap, next quiz and next voice question ahead of time so they open instantly. It uses AI quota, so it is off unless you turn it on."
                  : "Turned off for everyone on this server."
              }
              checked={data.prefs.preload && data.preload_allowed}
              disabled={!data.preload_allowed}
              onChange={(v) => save({ preload: v })}
            />
            <Switch
              label="Email me when my account signs in on a new device"
              hint="With the browser, operating system, IP address and approximate location, so you can spot a sign-in that was not you."
              checked={data.prefs.login_alerts}
              onChange={(v) => save({ login_alerts: v })}
            />
          </>
        )}
      </div>
      <ErrorNote message={error} />
    </section>
  );
}

/** Google Drive: copies of certificates and resumes in the student's own Drive (only the files
 * this app puts there). Shown only when the server has the Google keys. Google sends the student
 * back to /settings?drive=connected (or drive=error&reason=...), read once and then cleared. */
function GoogleDrive({ studentId }: { studentId: string }) {
  const [status, setStatus] = useDrive(studentId);
  const [busy, setBusy] = useState<"connect" | "backup" | "disconnect" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const back = q.get("drive");
    if (!back) return;
    if (back === "connected") setNote("Google Drive connected. New certificates are copied there.");
    else setError(q.get("reason") || "Google Drive was not connected.");
    window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const act = async (kind: "connect" | "backup" | "disconnect") => {
    setBusy(kind);
    setError(null);
    setNote(null);
    try {
      if (kind === "connect") {
        const { url } = await post<{ url: string }>("/api/drive/connect", {});
        window.location.assign(url); // Google's consent page; it sends the student back here
        return;
      }
      if (kind === "backup") {
        const { copied } = await post<{ copied: number }>("/api/drive/backup-certificates", {});
        setNote(copied ? `${copied} certificate${copied === 1 ? "" : "s"} copied to Drive.` : "Every certificate is already in Drive.");
      } else {
        setStatus(await post<DriveStatus>("/api/drive/disconnect", {}));
        setNote("Disconnected. Files already in your Drive stay there.");
      }
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(null);
  };

  if (!status.enabled) return null;
  const spin = (k: typeof busy) => (busy === k ? <Loader2 size={14} className="animate-spin" aria-hidden /> : null);
  return (
    <section className="card" aria-labelledby="drive-title">
      <h2 id="drive-title" className="flex items-center gap-2 font-semibold">
        <HardDrive size={16} aria-hidden /> Google Drive
      </h2>
      <p className="mt-1 text-xs text-muted">
        Keep copies of your certificates and resumes in your own Google Drive. The app sees only the files it puts there, nothing else in your Drive.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {status.connected ? (
          <>
            <a href={status.folder_link} target="_blank" rel="noopener noreferrer" className="btn-ghost">
              <ExternalLink size={14} aria-hidden /> Open the folder
            </a>
            <button type="button" className="btn-ghost" disabled={busy !== null} onClick={() => act("backup")}>
              {spin("backup")} Back up certificates
            </button>
            <button type="button" className="btn-ghost text-bad" disabled={busy !== null} onClick={() => act("disconnect")}>
              {spin("disconnect")} Disconnect
            </button>
          </>
        ) : (
          <button type="button" className="btn-ink" disabled={busy !== null} onClick={() => act("connect")}>
            {spin("connect")} Connect Google Drive
          </button>
        )}
      </div>
      {note && (
        <p role="status" className="mt-3 text-sm text-ok">
          {note}
        </p>
      )}
      <ErrorNote message={error} />
    </section>
  );
}

/** My local model: Ollama or LM Studio on this computer, used when the cloud AI fails (or
 * first, when preferred). The server decides whether it is allowed; where it is not (the
 * deployed site), the card only explains why. */
function LocalModel() {
  const { refreshLocalModel } = useCandidate();
  const [data, setData] = useState<LocalAIPayload | null>(null);
  const [provider, setProvider] = useState<LocalAIProvider>("ollama");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [preferred, setPreferred] = useState(false);
  const [models, setModels] = useState<string[] | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const show = useCallback((p: LocalAIPayload) => {
    setData(p);
    const c = p.config;
    setProvider(c?.provider ?? "ollama");
    setBaseUrl(c?.base_url ?? p.defaults.ollama);
    setModel(c?.model ?? "");
    setPreferred(c?.preferred ?? false);
  }, []);

  useEffect(() => {
    get<LocalAIPayload>("/api/auth/local-ai").then(show, (e: Error) => setError(e.message));
  }, [show]);

  const act = async (kind: "test" | "save" | "remove") => {
    setBusy(kind);
    setError(null);
    setNote(null);
    try {
      if (kind === "test") {
        const r = await post<{ models: string[]; base_url: string }>("/api/auth/local-ai/test", { provider, base_url: baseUrl });
        setModels(r.models);
        setBaseUrl(r.base_url);
        if (!model && r.models.length) setModel(r.models[0]);
        setNote(r.models.length ? `Connected: ${r.models.length} model${r.models.length === 1 ? "" : "s"} found.` : "Connected, but no models are installed yet.");
      } else if (kind === "save") {
        show(await post<LocalAIPayload>("/api/auth/local-ai", { provider, base_url: baseUrl, model, preferred }));
        setNote("Saved.");
      } else {
        show(await post<LocalAIPayload>("/api/auth/local-ai/delete", {}));
        setModels(null);
        setNote("Removed.");
      }
      refreshLocalModel();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const options = Array.from(new Set([...(models ?? []), ...(model ? [model] : [])])).sort();
  const spin = (k: typeof busy) => (busy === k ? <Loader2 size={14} className="animate-spin" aria-hidden /> : null);

  return (
    <section className="card" aria-labelledby="local-ai-title">
      <h2 id="local-ai-title" className="flex items-center gap-2 font-semibold">
        <Cpu size={16} aria-hidden /> My local model
      </h2>
      <p className="mt-1 text-xs text-muted">
        Use an AI model installed on this computer (Ollama, or LM Studio&apos;s server) when the cloud AI fails or there is no network.
      </p>
      {!data && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}
      {data && !data.allowed && <p className="mt-4 rounded-xl border border-dashed border-line px-4 py-3 text-sm text-muted">{data.explainer}</p>}
      {data?.allowed && (
        <div className="mt-4 grid gap-3">
          <fieldset>
            <legend className="label">Runs in</legend>
            <div className="segmented">
              {data.providers.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="segment"
                  aria-pressed={provider === p.id}
                  onClick={() => {
                    setProvider(p.id);
                    setBaseUrl(data.config?.provider === p.id ? data.config.base_url : data.defaults[p.id]);
                    setModel(data.config?.provider === p.id ? data.config.model : "");
                    setModels(null);
                  }}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <div>
              <label className="label" htmlFor="local-ai-url">
                Address
              </label>
              <input
                id="local-ai-url"
                className="input font-mono"
                value={baseUrl}
                maxLength={200}
                onChange={(e) => setBaseUrl(e.target.value)}
                aria-describedby="local-ai-url-hint"
              />
              <p id="local-ai-url-hint" className="mt-1 text-xs text-muted">
                Only this computer: localhost, 127.0.0.1 or [::1].
              </p>
            </div>
            <div className="sm:pt-[1.625rem]">
              <button type="button" className="btn-ghost w-full" disabled={busy !== null} onClick={() => act("test")}>
                {spin("test") ?? <PlugZap size={14} aria-hidden />} Test connection
              </button>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="local-ai-model">
              Model
            </label>
            <select id="local-ai-model" className="input" value={model} disabled={!options.length} onChange={(e) => setModel(e.target.value)}>
              {!options.length && <option value="">Test the connection to list your models</option>}
              {options.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <Switch
            label="Use it first, before the cloud AI"
            hint="Off: it is used only when the cloud AI fails or there is no network."
            checked={preferred}
            onChange={setPreferred}
          />
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-ink" disabled={busy !== null || !model} onClick={() => act("save")}>
              {spin("save")} Save
            </button>
            {data.config && (
              <button type="button" className="btn-ghost" disabled={busy !== null} onClick={() => act("remove")}>
                {spin("remove")} Remove
              </button>
            )}
          </div>
          {data.using_local && <p className="text-xs text-ok">Your latest AI answer came from {data.using_local}.</p>}
        </div>
      )}
      <ErrorNote message={error} />
      {note && !error && (
        <p role="status" className="mt-3 text-sm text-ok">
          {note}
        </p>
      )}
    </section>
  );
}

function Devices() {
  const [rows, setRows] = useState<DeviceSession[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    get<DeviceSession[]>("/api/auth/sessions").then(setRows, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  const act = async (key: string, path: string) => {
    setBusy(key);
    setError(null);
    try {
      setRows(await post<DeviceSession[]>(path, {}));
    } catch (e) {
      setError((e as Error).message);
      load();
    } finally {
      setBusy(null);
    }
  };
  const others = rows?.filter((r) => !r.current).length ?? 0;
  return (
    <section className="card" aria-labelledby="devices-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="devices-title" className="flex items-center gap-2 font-semibold">
          <MonitorSmartphone size={16} aria-hidden /> Signed-in devices
        </h2>
        {others > 0 && (
          <button type="button" className="btn-ghost text-xs" disabled={busy !== null} onClick={() => act("others", "/api/auth/sessions/revoke-others")}>
            {busy === "others" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <LogOut size={14} aria-hidden />} Sign out all other devices
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">Sign out any device you no longer use or do not recognise.</p>
      {!rows && !error && <p className="mt-4 text-sm text-muted">Loading…</p>}
      <ul className="mt-4 space-y-2">
        {rows?.map((r) => {
          const Icon = /iOS|Android/.test(r.os) ? Smartphone : Laptop;
          return (
            <li key={r.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-hair px-3 py-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-hair bg-surface" aria-hidden>
                <Icon size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  {r.browser} on {r.os}
                  {r.current && <span className="chip ml-2 align-middle text-[11px]">This device</span>}
                </p>
                <p className="truncate font-mono text-[11px] text-muted">
                  {[r.ip, r.location].filter(Boolean).join(" · ") || "Unknown network"} · signed in {when(r.created_at)} · active{" "}
                  {when(r.last_seen)}
                </p>
              </div>
              {!r.current && (
                <button type="button" className="btn-ghost text-xs" disabled={busy !== null} onClick={() => act(r.id, `/api/auth/sessions/${r.id}/revoke`)}>
                  {busy === r.id ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <LogOut size={14} aria-hidden />} Sign out
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <ErrorNote message={error} />
    </section>
  );
}

function Password() {
  const { setCandidate } = useCandidate();
  const [form, setForm] = useState({ current: "", password: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <form
      className="card"
      aria-labelledby="pw-change-title"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        setDone(false);
        try {
          setCandidate((await post<{ student: Student }>("/api/auth/password", form)).student);
          setForm({ current: "", password: "", confirm: "" });
          setDone(true);
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h2 id="pw-change-title" className="flex items-center gap-2 font-semibold">
        <KeyRound size={16} aria-hidden /> Password
      </h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <label className="text-sm font-medium">
          Current password
          <input className="input mt-1 font-normal" type="password" autoComplete="current-password" required value={form.current} onChange={set("current")} />
        </label>
        <label className="text-sm font-medium">
          New password
          <input className="input mt-1 font-normal" type="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={set("password")} />
        </label>
        <label className="text-sm font-medium">
          Repeat it
          <input className="input mt-1 font-normal" type="password" autoComplete="new-password" required value={form.confirm} onChange={set("confirm")} />
        </label>
      </div>
      <p className="mt-2 text-xs text-muted">8-128 characters with letters and digits.</p>
      <ErrorNote message={error} />
      {done && (
        <p role="status" className="mt-3 text-sm text-ok">
          Your password was changed.
        </p>
      )}
      <button type="submit" className="btn-ink mt-4" disabled={busy}>
        {busy && <Loader2 size={16} className="animate-spin" aria-hidden />} Change password
      </button>
    </form>
  );
}

export default function SettingsPage() {
  const { candidate, loading } = useCandidate();
  return (
    <>
      <PageHeader eyebrow="Settings" title="Your account and preferences" lead="Choose what runs in the background, and keep an eye on where you are signed in." />
      {loading ? (
        <Loading label="Loading your settings…" />
      ) : !candidate ? (
        <NeedsCandidate />
      ) : (
        <div className="grid gap-4">
          <section className="card" aria-label="Account">
            <p className="text-sm font-semibold">{candidate.name}</p>
            <p className="font-mono text-xs text-muted">
              @{candidate.username} · {candidate.target_role}
            </p>
          </section>
          <Preferences />
          <LocalModel />
          <GoogleDrive studentId={candidate.id} />
          <ProctorRecord />
          <Devices />
          <Password />
          <section className="card" aria-label="Question sources">
            <p className="text-sm">
              Practice questions come from our own bank, students&apos; approved reports and openly licensed sources.{" "}
              <Link href="/credits" className="font-medium underline underline-offset-2">
                Question sources &amp; credits
              </Link>
            </p>
          </section>
        </div>
      )}
    </>
  );
}
