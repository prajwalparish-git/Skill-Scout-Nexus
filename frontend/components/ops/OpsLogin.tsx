"use client";

// The developer console's own sign-in: DEV_SECRET only (POST /api/auth/ops-login), no account.
import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, KeyRound, Loader2, Terminal } from "lucide-react";
import { opsApi } from "@/lib/opsApi";
import { Brand } from "@/components/site/Brand";

export function OpsLogin({ onSignedIn }: { onSignedIn: () => void }) {
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!secret || busy) return;
    setBusy(true);
    setError(null);
    try {
      await opsApi.login(secret);
      setSecret("");
      onSignedIn();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative grid min-h-screen place-items-center px-4 py-12">
      <div aria-hidden className="hairline-grid pointer-events-none absolute inset-x-0 top-0 h-96" />
      <div className="relative w-full max-w-md">
        <Link href="/" className="mb-8 flex justify-center text-ink" aria-label="Skill Scout Nexus, home">
          <Brand height={16} />
        </Link>
        <form onSubmit={submit} className="panel p-6 shadow-[0_30px_80px_-40px_rgb(var(--ink)/0.35)] sm:p-8" aria-labelledby="ops-login-title">
          <span className="grid h-11 w-11 place-items-center rounded-full border border-hair bg-surface text-ink" aria-hidden>
            <Terminal size={18} />
          </span>
          <p className="eyebrow mt-5">Developer Console</p>
          <h1 id="ops-login-title" className="display mt-1 text-2xl">
            Sign in with the developer secret
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Enter the server&apos;s <code className="font-mono text-[0.85em] text-ink">DEV_SECRET</code>. It opens a 12-hour console session in this browser;
            every change you make is recorded in the audit log.
          </p>
          <label htmlFor="ops-secret" className="label mt-6">
            DEV_SECRET
          </label>
          <div className="relative">
            <KeyRound size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
            <input
              id="ops-secret"
              type="password"
              autoComplete="current-password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              className="input pl-10 font-mono"
              maxLength={200}
              required
              autoFocus
            />
          </div>
          {error && (
            <p role="alert" className="mt-3 rounded-xl border border-bad/40 bg-bad/[0.04] px-3 py-2 text-sm text-bad">
              {error}
            </p>
          )}
          <button type="submit" className="btn-ink mt-5 w-full" disabled={busy || !secret}>
            {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Terminal size={15} aria-hidden />}
            Open the console
          </button>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-hair pt-4 text-xs text-muted">
            <Link href="/docs?tab=developers" className="inline-flex items-center gap-1.5 hover:text-ink">
              <BookOpen size={13} aria-hidden /> Developer guide
            </Link>
            <Link href="/" className="inline-flex items-center gap-1.5 hover:text-ink">
              <ArrowLeft size={13} aria-hidden /> Back to the site
            </Link>
          </div>
        </form>
        <p className="mt-4 text-center text-[11px] text-muted">No DEV_SECRET configured on the server means there is no way in.</p>
      </div>
    </main>
  );
}
