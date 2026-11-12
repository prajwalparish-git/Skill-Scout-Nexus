"use client";

// Sign-in for the web app. The API has no accounts of its own: "signing in" picks the
// candidate profile (lib/candidate), and new accounts are created in the main (Streamlit) app.
// Any page can open the dialog with useAuth().open(...); ToolLink gates the tools behind it.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, ArrowUpRight, Check, RefreshCw, Search, UserRound, X } from "lucide-react";
import { useCandidate } from "@/lib/candidate";
import { APP_URL, SPRING, isGuestTool } from "@/lib/site";
import { pauseScroll, resumeScroll } from "./SmoothScroll";
import { tabKeys } from "./tabKeys";

type Mode = "signin" | "signup";
type Ctx = { open: (mode?: Mode, next?: string) => void };

const AuthContext = createContext<Ctx>({ open: () => {} });
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<{ mode: Mode; next: string | null } | null>(null);
  const open = useCallback((mode: Mode = "signin", next?: string) => setState({ mode, next: next ?? null }), []);
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

/** A link to a tool: straight through with a profile, otherwise via the sign-in dialog. */
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

/** The button a tool page shows when it needs a profile. */
export function SignInPrompt() {
  const { open } = useAuth();
  return (
    <button type="button" className="btn-ink mt-4" onClick={() => open("signin")}>
      Sign in to continue <ArrowRight size={16} aria-hidden />
    </button>
  );
}

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
  const { students, candidate, choose, reload, error } = useCandidate();
  const [query, setQuery] = useState("");
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
    panel.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
      if (e.key !== "Tab" || !panel.current) return;
      const items = panel.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
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

  const q = query.trim().toLowerCase();
  const matches = students.filter((s) => !q || `${s.name} ${s.username} ${s.target_role}`.toLowerCase().includes(q));

  const signIn = (id: string) => {
    choose(id);
    onClose();
    router.push(next ?? "/dashboard");
  };

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
              {mode === "signin" ? "Welcome back" : "Start your preparation"}
            </h2>
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

        <div
          role="tablist"
          aria-label="Account"
          onKeyDown={tabKeys(["signin", "signup"] as const, mode, setMode)}
          className="relative mt-5 grid grid-cols-2 rounded-full border border-hair p-1 text-sm"
        >
          {(["signin", "signup"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              type="button"
              id={`auth-tab-${m}`}
              aria-controls={`auth-panel-${m}`}
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

        <AnimatePresence mode="wait" initial={false}>
          {mode === "signin" ? (
            <motion.div
              key="signin"
              role="tabpanel"
              id="auth-panel-signin"
              aria-labelledby="auth-tab-signin"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 12 }}
              transition={SPRING}
              className="mt-5"
            >
              <p className="text-sm text-muted">
                Choose your profile. Your quizzes, plan and interviews are saved to it.
              </p>
              <label className="relative mt-4 block">
                <span className="sr-only">Search profiles</span>
                <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
                <input
                  data-autofocus
                  className="input rounded-full pl-9"
                  placeholder="Name, @username or role"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>

              {error ? (
                <div role="alert" className="mt-4 rounded-xl border border-bad/40 p-3 text-sm text-bad">
                  {error}
                  <button type="button" onClick={reload} className="mt-2 flex items-center gap-1.5 font-medium underline-offset-2 hover:underline">
                    <RefreshCw size={14} aria-hidden /> Try again
                  </button>
                </div>
              ) : (
                <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto" aria-label="Profiles">
                  {matches.map((s) => {
                    const current = s.id === candidate?.id;
                    return (
                      <li key={s.id}>
                        <button
                          type="button"
                          onClick={() => signIn(s.id)}
                          className="group flex w-full items-center gap-3 rounded-xl border border-transparent px-3 py-2.5 text-left hover:border-hair hover:bg-surface"
                        >
                          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-hair font-mono text-xs uppercase">
                            {s.name
                              .split(/\s+/)
                              .slice(0, 2)
                              .map((w) => w[0])
                              .join("")}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium">{s.name}</span>
                            <span className="block truncate font-mono text-[11px] text-muted">
                              @{s.username} · {s.target_role}
                            </span>
                          </span>
                          {current ? (
                            <span className="flex items-center gap-1 font-mono text-[11px] text-muted">
                              <Check size={12} aria-hidden /> current
                            </span>
                          ) : (
                            <ArrowRight size={16} className="text-muted opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                          )}
                        </button>
                      </li>
                    );
                  })}
                  {!matches.length && (
                    <li className="rounded-xl border border-dashed border-line px-3 py-4 text-center text-sm text-muted">
                      {students.length ? "No profile matches that search." : "No profiles yet. Create one under Get started."}
                    </li>
                  )}
                </ul>
              )}
              <GuestLink next={next} onClose={onClose} />
            </motion.div>
          ) : (
            <motion.div
              key="signup"
              role="tabpanel"
              id="auth-panel-signup"
              aria-labelledby="auth-tab-signup"
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -12 }}
              transition={SPRING}
              className="mt-5"
            >
              <ol className="space-y-3 text-sm">
                {[
                  ["Create your account", "Sign up in the main app with your email; a code confirms it."],
                  ["Upload your resume", "PDF, DOCX or TXT, read against the role you want."],
                  ["Come back here", "Your profile appears under Sign in, with your readiness score."],
                ].map(([title, body], i) => (
                  <li key={title} className="flex gap-3">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-hair font-mono text-[11px]">
                      {i + 1}
                    </span>
                    <span>
                      <span className="block font-medium">{title}</span>
                      <span className="block text-muted">{body}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <a data-autofocus href={APP_URL} target="_blank" rel="noreferrer" className="btn-ink mt-6 w-full">
                Create an account in the main app <ArrowUpRight size={16} aria-hidden />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
              <button
                type="button"
                className="btn-hair mt-2 w-full"
                onClick={() => {
                  reload();
                  setMode("signin");
                }}
              >
                <UserRound size={16} aria-hidden /> I already have a profile: go to sign in
              </button>
              <GuestLink next={next} onClose={onClose} />
            </motion.div>
          )}
        </AnimatePresence>
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
