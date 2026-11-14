"use client";

// Sign-in for the web app. Sign-up ends with a 9-digit code by email; after that the password
// alone signs in, and the code is asked too when the email was never confirmed or after more
// than two wrong tries. The session lives in an HttpOnly cookie. Any page can open the dialog
// with useAuth().open(...); ToolLink gates the tools behind it.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Loader2, MailCheck, X } from "lucide-react";
import { get, post, type Catalog, type Student } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { SPRING, isGuestTool } from "@/lib/site";
import { pauseScroll, resumeScroll } from "./SmoothScroll";
import { tabKeys } from "./tabKeys";

type Mode = "signin" | "signup" | "recover";
type Ctx = { open: (mode?: "signin" | "signup", next?: string) => void };
/** The answer to a request that sent a code: a signed token for the next call, and where it went. */
type Step = { step: string; sent_to: string; outbox: boolean; welcome: boolean; purpose: "login" | "recover" };
/** What a sign-in or sign-up request answers: signed in, a code to type, or the operations view. */
type Answer = Step | { student: Student } | { ops: true };

const AuthContext = createContext<Ctx>({ open: () => {} });
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<{ mode: Mode; next: string | null } | null>(null);
  const open = useCallback(
    (mode: "signin" | "signup" = "signin", next?: string) => setState({ mode, next: next ?? null }),
    [],
  );
  const value = useMemo(() => ({ open }), [open]);
  return (
    <AuthContext.Provider value={value}>
      {children}
      <AnimatePresence>
        {state && (
          <AuthDialog
            key="auth"
            mode={state.mode}
            next={state.next}
            setMode={(mode) => setState((s) => (s ? { ...s, mode } : s))}
            onClose={() => setState(null)}
          />
        )}
      </AnimatePresence>
    </AuthContext.Provider>
  );
}

/** A link to a tool: straight through when signed in, otherwise via the sign-in dialog. */
export function ToolLink({
  href,
  className,
  children,
  "aria-label": ariaLabel,
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
  "aria-label"?: string;
}) {
  const { candidate } = useCandidate();
  const { open } = useAuth();
  if (candidate)
    return (
      <Link href={href} className={className} aria-label={ariaLabel}>
        {children}
      </Link>
    );
  return (
    <button type="button" className={className} aria-label={ariaLabel} onClick={() => open("signin", href)}>
      {children}
    </button>
  );
}

/** The button a tool page shows when it needs a signed-in student. */
export function SignInPrompt() {
  const { open } = useAuth();
  return (
    <button type="button" className="btn-ink mt-4" onClick={() => open("signin")}>
      Sign in to continue <ArrowRight size={16} aria-hidden />
    </button>
  );
}

/** Runs one request at a time and keeps its error for the form to show. */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function Problem({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="mt-3 rounded-xl border border-bad/40 p-3 text-sm text-bad">
      {message}
    </p>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="mt-3 block text-sm font-medium">
      {label}
      <span className="mt-1 block font-normal">{children}</span>
      {hint && <span className="mt-1 block text-xs font-normal text-muted">{hint}</span>}
    </label>
  );
}

function Submit({ busy, children }: { busy: boolean; children: React.ReactNode }) {
  return (
    <button type="submit" className="btn-ink mt-5 w-full" disabled={busy}>
      {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

function SignInForm({ onAnswer, onRecover }: { onAnswer: (a: Answer) => void; onRecover: () => void }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => onAnswer(await post<Answer>("/api/auth/login", { identifier, password })));
      }}
    >
      <Field label="Username or email">
        <input
          data-autofocus
          className="input"
          autoComplete="username"
          required
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
        />
      </Field>
      <Field label="Password">
        <input
          className="input"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Problem message={error} />
      <Submit busy={busy}>Continue</Submit>
      <button type="button" className="mt-3 w-full text-center text-sm text-muted underline-offset-2 hover:text-ink hover:underline" onClick={onRecover}>
        Forgot your password?
      </button>
    </form>
  );
}

function SignUpForm({ onAnswer }: { onAnswer: (a: Answer) => void }) {
  const [form, setForm] = useState({ name: "", username: "", email: "", password: "", confirm: "", target_role: "" });
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  useEffect(() => {
    get<Catalog>("/api/catalog").then(setCatalog, (e: Error) => setCatalogError(e.message));
  }, []);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => onAnswer(await post<Answer>("/api/auth/signup", form)));
      }}
    >
      <Field label="Full name">
        <input data-autofocus className="input" autoComplete="name" required maxLength={120} value={form.name} onChange={set("name")} />
      </Field>
      <Field label="Username" hint="3-20 lower-case letters or digits; dots, - and _ are allowed.">
        <input className="input" autoComplete="username" required value={form.username} onChange={set("username")} />
      </Field>
      <Field label="Email" hint="A 9-digit code is sent here to confirm it.">
        <input className="input" type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
      </Field>
      <Field label="The role you are aiming for">
        <select className="input" required value={form.target_role} onChange={set("target_role")}>
          <option value="">{catalog ? "Choose a role" : "Loading roles…"}</option>
          {catalog?.domains.map((d) => (
            <optgroup key={d.id} label={d.name}>
              {d.roles.map((r) => (
                <option key={r.name} value={r.name}>
                  {r.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </Field>
      <Field label="Password" hint="8-128 characters with letters and digits.">
        <input className="input" type="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={set("password")} />
      </Field>
      <Field label="Repeat the password">
        <input className="input" type="password" autoComplete="new-password" required value={form.confirm} onChange={set("confirm")} />
      </Field>
      <Problem message={error ?? catalogError} />
      <Submit busy={busy}>Create account</Submit>
      <p className="mt-3 text-center text-xs text-muted">
        By creating an account you accept the{" "}
        <Link href="/terms" className="underline underline-offset-2 hover:text-ink">
          Terms
        </Link>{" "}
        and the{" "}
        <Link href="/privacy" className="underline underline-offset-2 hover:text-ink">
          Privacy Policy
        </Link>
        .
      </p>
    </form>
  );
}

function RecoverForm({ onStep, onBack }: { onStep: (s: Step) => void; onBack: () => void }) {
  const [identifier, setIdentifier] = useState("");
  const { busy, error, run } = useAction();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => onStep(await post<Step>("/api/auth/recover", { identifier })));
      }}
    >
      <p className="text-sm text-muted">Enter your username or email and we will send a 9-digit code to set a new password.</p>
      <Field label="Username or email">
        <input data-autofocus className="input" autoComplete="username" required value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
      </Field>
      <Problem message={error} />
      <Submit busy={busy}>Send the code</Submit>
      <button type="button" className="mt-3 flex w-full items-center justify-center gap-1.5 text-sm text-muted underline-offset-2 hover:text-ink hover:underline" onClick={onBack}>
        <ArrowLeft size={14} aria-hidden /> Back to sign in
      </button>
    </form>
  );
}

/** The 9-digit code, typed as XXX-XXX-XXX. */
const groupCode = (v: string) => v.replace(/\D/g, "").slice(0, 9).replace(/(\d{3})(?=\d)/g, "$1-");

function CodeStep({
  info,
  onStep,
  onDone,
  onBack,
}: {
  info: Step;
  onStep: (s: Step) => void;
  onDone: (s: Student) => void;
  onBack: () => void;
}) {
  const recovering = info.purpose === "recover";
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [resent, setResent] = useState(false);
  const { busy, error, run } = useAction();
  const resend = useAction();

  const where = info.outbox
    ? "Email is not set up on this server, so the code was written to its local mail outbox (data/.mail_outbox.log)."
    : info.welcome
      ? "Enter the 9-digit code from your welcome email."
      : info.sent_to
        ? `We emailed a 9-digit code to ${info.sent_to}. It expires in 10 minutes.`
        : "If that account exists, a 9-digit code is on its way. It expires in 10 minutes.";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const r = recovering
            ? await post<{ student: Student }>("/api/auth/recover/finish", { step: info.step, code, password, confirm })
            : await post<{ student: Student }>("/api/auth/code", { step: info.step, code });
          onDone(r.student);
        });
      }}
    >
      <p className="flex items-start gap-2 text-sm text-muted">
        <MailCheck size={18} className="mt-0.5 shrink-0 text-ink" aria-hidden />
        <span>{where}</span>
      </p>
      <Field label="9-digit code">
        <input
          data-autofocus
          className="input font-mono tracking-[0.2em]"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="000-000-000"
          required
          value={code}
          onChange={(e) => setCode(groupCode(e.target.value))}
        />
      </Field>
      {recovering && (
        <>
          <Field label="New password" hint="8-128 characters with letters and digits.">
            <input className="input" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Field label="Repeat the new password">
            <input className="input" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </Field>
        </>
      )}
      <Problem message={error} />
      <Submit busy={busy}>{recovering ? "Set password and sign in" : "Verify and sign in"}</Submit>
      <div className="mt-3 flex items-center justify-between text-sm">
        <button type="button" className="flex items-center gap-1.5 text-muted underline-offset-2 hover:text-ink hover:underline" onClick={onBack}>
          <ArrowLeft size={14} aria-hidden /> Start over
        </button>
        <button
          type="button"
          className="text-muted underline-offset-2 hover:text-ink hover:underline disabled:opacity-50"
          disabled={resend.busy}
          onClick={() =>
            resend.run(async () => {
              onStep(await post<Step>(`/api/auth/resend?purpose=${info.purpose}`, { step: info.step }));
              setResent(true);
            })
          }
        >
          Send a new code
        </button>
      </div>
      {resent && !resend.error && (
        <p role="status" className="mt-2 text-xs text-muted">
          A new code was sent. The old one no longer works.
        </p>
      )}
      <Problem message={resend.error} />
    </form>
  );
}

const TITLES: Record<Mode, string> = {
  signin: "Welcome back",
  signup: "Start your preparation",
  recover: "Recover your account",
};

function AuthDialog({
  mode,
  next,
  setMode,
  onClose,
}: {
  mode: Mode;
  next: string | null;
  setMode: (m: Mode) => void;
  onClose: () => void;
}) {
  const router = useRouter();
  const { setCandidate, reload, mode: install } = useCandidate();
  const [pending, setPending] = useState<Step | null>(null);
  const signupOpen = install.signup_open;
  if (mode === "signup" && !signupOpen) mode = "signin";
  const panel = useRef<HTMLDivElement>(null);
  // The latest onClose, read by the key handler: the parent passes a new function on every
  // render, and re-running the focus effect for it would throw focus out of the dialog.
  const close = useRef(onClose);
  close.current = onClose;

  // Focus moves into the dialog, Escape closes it, the page behind stops scrolling, and
  // focus returns to whatever opened it.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    pauseScroll();
    const html = document.documentElement;
    const overflow = html.style.overflow;
    html.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
      if (e.key !== "Tab" || !panel.current) return;
      const items = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      html.style.overflow = overflow;
      resumeScroll();
      before?.focus?.();
    };
  }, []);

  // Each form or step puts focus on its first field when it appears.
  const view = pending ? `code-${pending.purpose}` : mode;
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
  }, [view]);

  const done = (student: Student) => {
    setCandidate(student);
    onClose();
    router.push(next ?? "/dashboard");
  };

  const answer = (a: Answer) => {
    if ("student" in a) done(a.student);
    else if ("ops" in a) {
      reload();
      onClose();
      router.push("/ops");
    } else setPending(a);
  };

  const tabs = !pending && mode !== "recover" && signupOpen;
  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center sm:p-6">
      <motion.div
        aria-hidden
        className="absolute inset-0 bg-ink/30 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        data-lenis-prevent
        className="panel relative max-h-[88vh] w-full overflow-y-auto rounded-b-none p-6 shadow-2xl sm:max-w-md sm:rounded-b-[1.25rem] sm:p-7"
        initial={{ opacity: 0, y: 40, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 24, scale: 0.98 }}
        transition={SPRING}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="eyebrow">Skill Scout Nexus</p>
            <h2 id="auth-title" className="display mt-2 text-2xl">
              {pending ? (pending.purpose === "recover" ? "Set a new password" : "Check your email") : TITLES[mode]}
            </h2>
            {install.local && !pending && (
              <p className="mt-1 text-xs text-muted">This copy runs on this computer for one student: the password alone signs in.</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-2 text-muted hover:bg-surface hover:text-ink"
            aria-label="Close sign-in dialog"
          >
            <X size={18} aria-hidden />
          </button>
        </div>

        {tabs && (
          <div
            role="tablist"
            aria-label="Account"
            onKeyDown={tabKeys(["signin", "signup"] as const, mode as "signin" | "signup", setMode)}
            className="relative mt-5 grid grid-cols-2 rounded-full border border-hair p-1 text-sm"
          >
            {(["signin", "signup"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                type="button"
                id={`auth-tab-${m}`}
                aria-controls="auth-panel"
                aria-selected={mode === m}
                tabIndex={mode === m ? 0 : -1}
                onClick={() => setMode(m)}
                className={`relative z-10 rounded-full py-1.5 font-medium transition-colors ${mode === m ? "text-bg" : "text-muted hover:text-ink"}`}
              >
                {mode === m && (
                  <motion.span layoutId="auth-tab" className="absolute inset-0 -z-10 rounded-full bg-ink" transition={SPRING} />
                )}
                {m === "signin" ? "Sign in" : "Get started"}
              </button>
            ))}
          </div>
        )}

        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={view}
            id="auth-panel"
            role={tabs ? "tabpanel" : undefined}
            aria-labelledby={tabs ? `auth-tab-${mode}` : undefined}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={SPRING}
            className="mt-5"
          >
            {pending ? (
              <CodeStep info={pending} onStep={setPending} onDone={done} onBack={() => setPending(null)} />
            ) : mode === "signin" ? (
              <SignInForm onAnswer={answer} onRecover={() => setMode("recover")} />
            ) : mode === "signup" ? (
              <SignUpForm onAnswer={answer} />
            ) : (
              <RecoverForm onStep={setPending} onBack={() => setMode("signin")} />
            )}
          </motion.div>
        </AnimatePresence>

        <GuestLink next={next} onClose={onClose} />
      </motion.div>
    </div>
  );
}

function GuestLink({ next, onClose }: { next: string | null; onClose: () => void }) {
  const target = next && isGuestTool(next) ? next : "/quiz";
  return (
    <p className="mt-5 border-t border-hair pt-4 text-center text-xs text-muted">
      Just looking?{" "}
      <Link href={target} onClick={onClose} className="font-medium text-ink underline-offset-2 hover:underline">
        Continue as a guest
      </Link>{" "}
      (nothing is saved).
      <span className="mt-2 block">
        A free, non-commercial college mini-project.{" "}
        <Link href="/privacy" onClick={onClose} className="underline underline-offset-2 hover:text-ink">
          Privacy
        </Link>
        {" · "}
        <Link href="/terms" onClick={onClose} className="underline underline-offset-2 hover:text-ink">
          Terms
        </Link>
        {" · "}
        <Link href="/cookies" onClick={onClose} className="underline underline-offset-2 hover:text-ink">
          Cookies
        </Link>
      </span>
    </p>
  );
}
