"use client";

// Contribute a question to the open bank: a lightweight contributor sign-up (name, email, company
// joined, batch year), the question form (published under CC BY 4.0), the author's own
// contributions, opt-in credit and the season's top contributors.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Award, HandHeart, Loader2, MailCheck, PenLine, Send, Trophy } from "lucide-react";
import {
  DIFFICULTY_LABELS,
  get,
  post,
  type ContributeMe,
  type ContributeOptions,
  type Contribution,
  type Leaderboard,
  type Student,
} from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { useAuth } from "@/components/site/auth";
import { Badge, ErrorNote } from "@/components/ui";

const LETTERS = "ABCD";
const STATUS: Record<Contribution["status"], { state: "ok" | "info" | "warn"; text: string }> = {
  pending: { state: "info", text: "Waiting for review" },
  approved: { state: "ok", text: "Published" },
  rejected: { state: "warn", text: "Not published" },
  hidden: { state: "warn", text: "Hidden" },
};

/** The prominent "Contribute a question" button used across the app. */
export function ContributeButton({ className = "btn-primary" }: { className?: string }) {
  return (
    <Link href="/contribute" className={className}>
      <HandHeart size={16} aria-hidden /> Contribute a question
    </Link>
  );
}

type Step = { step: string; sent_to: string; outbox: boolean };

/** Contributor sign-up: no target role, resume or readiness score. Ends with the emailed code. */
export function ContributorSignUp() {
  const { setCandidate } = useCandidate();
  const { open } = useAuth();
  const [form, setForm] = useState({ name: "", username: "", email: "", company: "", batch: "", password: "", confirm: "" });
  const [consent, setConsent] = useState(false);
  const [step, setStep] = useState<Step | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function signUp(e: React.FormEvent) {
    e.preventDefault();
    if (!consent) return setError("Tick the consent box to create an account.");
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ student?: Student } & Partial<Step>>("/api/auth/signup-contributor", {
        name: form.name,
        username: form.username,
        email: form.email,
        password: form.password,
        confirm: form.confirm,
        company_joined: form.company,
        batch_year: form.batch,
      });
      if (r.student) setCandidate(r.student);
      else setStep(r as Step);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmCode(e: React.FormEvent) {
    e.preventDefault();
    if (!step) return;
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ student: Student }>("/api/auth/code", { step: step.step, code });
      setCandidate(r.student);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (step)
    return (
      <form className="card max-w-md space-y-3" onSubmit={confirmCode} aria-labelledby="code-title">
        <h2 id="code-title" className="flex items-center gap-2 font-semibold">
          <MailCheck size={16} aria-hidden /> Check your email
        </h2>
        <p className="text-sm text-muted">We sent a 9-digit code to {step.sent_to}. Type it to finish signing up.</p>
        <input className="input font-mono tracking-widest" inputMode="numeric" autoComplete="one-time-code" maxLength={11} value={code} onChange={(e) => setCode(e.target.value)} aria-label="Code" />
        <ErrorNote message={error} />
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy && <Loader2 size={16} className="animate-spin" aria-hidden />} Confirm
        </button>
      </form>
    );

  return (
    <form className="card max-w-2xl space-y-4" onSubmit={signUp} aria-labelledby="cs-title">
      <div>
        <h2 id="cs-title" className="font-semibold">
          Placed, an alumnus or working? Sign up as a contributor
        </h2>
        <p className="mt-1 text-sm text-muted">
          Only what we need: your name, email, the company you joined and your batch year. No target role, resume or readiness score. You
          are anonymous unless you choose a display name later.{" "}
          <button type="button" className="font-medium text-primary-ink underline underline-offset-2" onClick={() => open("signin")}>
            Already have an account? Sign in
          </button>
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">
          Your name
          <input className="input mt-1 font-normal" required maxLength={120} autoComplete="name" value={form.name} onChange={set("name")} />
        </label>
        <label className="text-sm font-medium">
          Username
          <input className="input mt-1 font-normal" required maxLength={20} autoComplete="username" value={form.username} onChange={set("username")} />
        </label>
        <label className="text-sm font-medium">
          Email
          <input className="input mt-1 font-normal" type="email" required autoComplete="email" value={form.email} onChange={set("email")} />
        </label>
        <label className="text-sm font-medium">
          Company you joined
          <input className="input mt-1 font-normal" required maxLength={120} placeholder="e.g. Infosys" value={form.company} onChange={set("company")} />
        </label>
        <label className="text-sm font-medium">
          Batch year
          <input className="input mt-1 font-normal" required inputMode="numeric" maxLength={4} placeholder="e.g. 2024" value={form.batch} onChange={set("batch")} />
        </label>
        <span />
        <label className="text-sm font-medium">
          Password
          <input className="input mt-1 font-normal" type="password" required autoComplete="new-password" value={form.password} onChange={set("password")} />
        </label>
        <label className="text-sm font-medium">
          Repeat it
          <input className="input mt-1 font-normal" type="password" required autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
        </label>
      </div>
      <p className="text-xs text-muted">At least 8 characters, with letters and digits.</p>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I agree to the{" "}
        <Link href="/terms" className="underline underline-offset-2">
          terms
        </Link>{" "}
        and the{" "}
        <Link href="/privacy" className="underline underline-offset-2">
          privacy policy
        </Link>
        .
      </label>
      <ErrorNote message={error} />
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <PenLine size={16} aria-hidden />} Create contributor account
      </button>
    </form>
  );
}

const EMPTY = { kind: "mcq" as "mcq" | "open", round: "aptitude", topic: "Aptitude", difficulty: "medium", text: "", options: ["", "", "", ""], correct: null as number | null, explanation: "", modelAnswer: "" };

/** The contribution form: an MCQ with its answer and explanation, or an open question with a model
 * answer. CC BY 4.0 is shown and must be accepted. */
export function ContributeForm({ options, onDone }: { options: ContributeOptions; onDone: () => void }) {
  const [f, setF] = useState(EMPTY);
  const [licence, setLicence] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const topics = options.topics[f.round] ?? [];

  function setRound(round: string) {
    setF((x) => ({ ...x, round, topic: options.topics[round]?.[0] ?? "", kind: round === "hr" ? "open" : x.kind }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const r = await post<{ id: number; removed: string[] }>("/api/contribute", {
        kind: f.kind,
        round: f.round,
        topic: f.topic,
        difficulty: f.difficulty,
        text: f.text,
        options: f.kind === "mcq" ? f.options : [],
        correct_index: f.kind === "mcq" ? f.correct : null,
        explanation: f.kind === "mcq" ? f.explanation : "",
        model_answer: f.kind === "open" ? f.modelAnswer : "",
        licence_accepted: licence,
      });
      setDone(`Thanks! It is waiting for a moderator's approval.${r.removed.length ? ` Removed automatically: ${r.removed.join(", ")}.` : ""}`);
      setF((x) => ({ ...EMPTY, round: x.round, topic: x.topic, kind: x.kind, difficulty: x.difficulty }));
      setLicence(false);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card space-y-4" onSubmit={submit} aria-labelledby="cf-title">
      <h2 id="cf-title" className="font-semibold">
        Add a question
      </h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm font-medium">
          Round
          <select className="input mt-1 font-normal" value={f.round} onChange={(e) => setRound(e.target.value)}>
            {Object.entries(options.rounds).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Topic
          <select className="input mt-1 font-normal" value={f.topic} onChange={(e) => setF({ ...f, topic: e.target.value })}>
            {topics.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Difficulty
          <select className="input mt-1 font-normal" value={f.difficulty} onChange={(e) => setF({ ...f, difficulty: e.target.value })}>
            {Object.entries(DIFFICULTY_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="segmented" role="group" aria-label="Kind of question">
        <button type="button" className="segment" aria-pressed={f.kind === "mcq"} disabled={f.round === "hr"} onClick={() => setF({ ...f, kind: "mcq" })}>
          Multiple choice
        </button>
        <button type="button" className="segment" aria-pressed={f.kind === "open"} onClick={() => setF({ ...f, kind: "open" })}>
          Open question
        </button>
      </div>
      <label className="block text-sm font-medium">
        Question
        <textarea className="input mt-1 min-h-20 font-normal" required maxLength={1000} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} />
      </label>
      {f.kind === "mcq" ? (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Options (tick the correct one)</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {f.options.map((o, j) => (
              <label key={j} className="flex items-center gap-2 text-sm">
                <input type="radio" name="contrib-correct" checked={f.correct === j} onChange={() => setF({ ...f, correct: j })} aria-label={`Option ${LETTERS[j]} is correct`} />
                <span className="font-mono text-xs text-muted">{LETTERS[j]}</span>
                <input className="input py-1.5" maxLength={300} value={o} placeholder={`Option ${LETTERS[j]}`} onChange={(e) => setF({ ...f, options: f.options.map((x, k) => (k === j ? e.target.value : x)) })} />
              </label>
            ))}
          </div>
          <label className="block text-sm font-medium">
            Explanation
            <textarea className="input mt-1 min-h-16 font-normal" required maxLength={1000} placeholder="Why the answer is right" value={f.explanation} onChange={(e) => setF({ ...f, explanation: e.target.value })} />
          </label>
        </fieldset>
      ) : (
        <label className="block text-sm font-medium">
          Model answer
          <textarea className="input mt-1 min-h-28 font-normal" required maxLength={2000} placeholder="A good answer, in your own words (at least 80 characters)" value={f.modelAnswer} onChange={(e) => setF({ ...f, modelAnswer: e.target.value })} />
        </label>
      )}
      <div className="rounded-xl border border-hair bg-surface p-3 text-sm">
        <p>
          <strong>Licence: CC BY 4.0.</strong> {options.licence_note}{" "}
          <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
            About CC BY 4.0
          </a>
        </p>
        <label className="mt-2 flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={licence} onChange={(e) => setLicence(e.target.checked)} /> I wrote this question myself and publish it under CC BY 4.0.
        </label>
      </div>
      <ErrorNote message={error} />
      {done && (
        <p role="status" className="text-sm text-ok">
          {done}
        </p>
      )}
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Send size={16} aria-hidden />} Send for review
      </button>
    </form>
  );
}

export function TopContributors({ board }: { board: Leaderboard }) {
  return (
    <section className="card" aria-labelledby="top-title">
      <h2 id="top-title" className="flex items-center gap-2 font-semibold">
        <Trophy size={16} aria-hidden /> Top contributors this season ({board.season})
      </h2>
      {board.top.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No credited contributions yet this season. Be the first.</p>
      ) : (
        <ol className="mt-3 space-y-1 text-sm">
          {board.top.map((t, i) => (
            <li key={t.name} className="flex items-center justify-between">
              <span>
                {i + 1}. {t.name}
              </span>
              <span className="text-muted">{t.approved} approved</span>
            </li>
          ))}
        </ol>
      )}
      <p className="mt-3 text-xs text-muted">Only contributors who chose to be credited are listed.</p>
    </section>
  );
}

/** The signed-in author's side: their contributions, credit choice and badge. */
export function MyContributions() {
  const [me, setMe] = useState<ContributeMe | null>(null);
  const [options, setOptions] = useState<ContributeOptions | null>(null);
  const [credit, setCredit] = useState({ opt: false, name: "" });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(() => {
    get<ContributeMe>("/api/contribute/me").then(
      (r) => {
        setMe(r);
        setCredit({ opt: r.profile.credit_opt_in, name: r.profile.display_name });
      },
      (e: Error) => setError(e.message),
    );
  }, []);
  useEffect(() => {
    load();
    get<ContributeOptions>("/api/contribute/options").then(setOptions, (e: Error) => setError(e.message));
  }, [load]);

  async function saveCredit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    try {
      await post("/api/contribute/credit", { credit_opt_in: credit.opt, display_name: credit.name });
      setSaved("Saved.");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-4">
        {options ? <ContributeForm options={options} onDone={load} /> : <p className="text-sm text-muted">Loading…</p>}
        <section className="card" aria-labelledby="mine-title">
          <h2 id="mine-title" className="font-semibold">
            My contributions
          </h2>
          {!me?.contributions.length ? (
            <p className="mt-2 text-sm text-muted">Nothing yet.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {me.contributions.map((c) => (
                <li key={c.id} className="rounded-xl border border-hair px-3 py-2 text-sm">
                  <p className="flex flex-wrap items-center gap-2">
                    <Badge state={STATUS[c.status].state}>{STATUS[c.status].text}</Badge>
                    <span className="text-xs text-muted">
                      {options?.rounds[c.round] ?? c.round} · {c.topic} · {c.difficulty} · {c.kind === "mcq" ? "multiple choice" : "open"} · {c.licence}
                    </span>
                  </p>
                  <p className="mt-1">{c.text}</p>
                  {c.reject_reason && <p className="mt-1 text-xs">Moderator: {c.reject_reason}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <aside className="space-y-4 lg:sticky lg:top-24">
        {me && (
          <form className="card space-y-3" onSubmit={saveCredit} aria-labelledby="credit-title">
            <h2 id="credit-title" className="font-semibold">
              How you are credited
            </h2>
            {me.profile.badge && (
              <p className="chip border-ok/40 text-ok">
                <Award size={12} aria-hidden /> {me.profile.badge}
              </p>
            )}
            <p className="text-sm">
              {me.profile.approved} approved question{me.profile.approved === 1 ? "" : "s"}. Shown as <strong>{me.profile.shown_as}</strong>.
            </p>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={credit.opt} onChange={(e) => setCredit({ ...credit, opt: e.target.checked })} /> Credit me by a display name
            </label>
            {credit.opt && (
              <label className="block text-sm font-medium">
                Display name
                <input className="input mt-1 font-normal" maxLength={40} value={credit.name} onChange={(e) => setCredit({ ...credit, name: e.target.value })} placeholder="e.g. Asha R." />
              </label>
            )}
            <p className="text-xs text-muted">Off by default: you are &quot;an anonymous contributor&quot; until you choose a name.</p>
            <ErrorNote message={error} />
            {saved && (
              <p role="status" className="text-sm text-ok">
                {saved}
              </p>
            )}
            <button type="submit" className="btn-ghost">
              Save
            </button>
          </form>
        )}
        {me && <TopContributors board={me.leaderboard} />}
      </aside>
    </div>
  );
}
