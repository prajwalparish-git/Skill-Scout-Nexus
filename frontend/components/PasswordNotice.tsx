"use client";

// An organization's student arrives on a temporary password; this asks for one of their own.
import { useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { post, type Student } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";

export function PasswordNotice() {
  const { candidate, setCandidate } = useCandidate();
  const [form, setForm] = useState({ current: "", password: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!candidate?.must_change_password) return null;

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCandidate((await post<{ student: Student }>("/api/auth/password", form)).student);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card mb-6 border-warn/40" aria-labelledby="pw-title">
      <h2 id="pw-title" className="flex items-center gap-2 text-sm font-semibold">
        <KeyRound size={16} aria-hidden /> Choose a password of your own
      </h2>
      <p className="mt-1 text-sm text-muted">You signed in with a temporary password. Set your own now (8-128 characters, letters and digits).</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-sm font-medium">
          Temporary password
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
      {error && (
        <p role="alert" className="mt-3 text-sm text-bad">
          {error}
        </p>
      )}
      <button type="submit" className="btn-ink mt-4" disabled={busy}>
        {busy && <Loader2 size={16} className="animate-spin" aria-hidden />} Save password
      </button>
    </form>
  );
}
