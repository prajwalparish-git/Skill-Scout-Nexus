"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Laptop, Loader2, LogOut, MonitorSmartphone, Smartphone, SlidersHorizontal } from "lucide-react";
import { get, post, type DeviceSession, type Prefs, type SettingsPayload, type Student } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
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
          <Devices />
          <Password />
        </div>
      )}
    </>
  );
}
