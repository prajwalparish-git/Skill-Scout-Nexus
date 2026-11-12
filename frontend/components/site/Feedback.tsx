"use client";

// "Feedback to devs": rating, category and a message. Saved in this browser at once (the
// confirmation is instant), and one click files the same text as a GitHub issue. The API has no
// feedback route, so nothing is sent anywhere unless the visitor opens the issue themselves.
import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Bug, CheckCircle2, Lightbulb, Paintbrush, Send } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FEEDBACK_KEY, useConsent } from "@/lib/consent";
import { CONSENT_TEXT, GITHUB_URL, SPRING } from "@/lib/site";
import { GitHubIcon, trackSpotlight } from "./Brand";

const KEY = FEEDBACK_KEY;
const MAX = 800;
const CATEGORIES = [
  { id: "bug", label: "Bug", icon: Bug },
  { id: "ui", label: "UI suggestion", icon: Paintbrush },
  { id: "feature", label: "Feature", icon: Lightbulb },
] as const;
const RATINGS = [
  [1, "Poor"],
  [2, "Fair"],
  [3, "Good"],
  [4, "Great"],
  [5, "Excellent"],
] as const;

type Category = (typeof CATEGORIES)[number]["id"];
type Entry = { rating: number; category: Category; message: string; page: string; at: string };

function save(entry: Entry): boolean {
  try {
    const list: Entry[] = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    localStorage.setItem(KEY, JSON.stringify([entry, ...list].slice(0, 50)));
    return true;
  } catch {
    return false; // storage blocked: the GitHub link still works
  }
}

// `page` comes from usePathname(), identical on the server and in the browser, so the link
// renders the same on both (window is not available during server rendering).
function issueUrl(rating: number | null, category: Category, message: string, page: string): string {
  const label = CATEGORIES.find((c) => c.id === category)!.label;
  const title = `[${label}] ${message.trim().split("\n")[0].slice(0, 70) || "Feedback"}`;
  const body = [
    message.trim() || "_Describe it here._",
    "",
    "---",
    `Category: ${label}`,
    rating ? `Rating: ${rating}/5` : null,
    `Page: ${page}`,
  ]
    .filter((l) => l !== null)
    .join("\n");
  return `${GITHUB_URL}/issues/new?${new URLSearchParams({ title, body })}`;
}

export function FeedbackForm() {
  const [rating, setRating] = useState<number | null>(null);
  const [category, setCategory] = useState<Category>("ui");
  const [message, setMessage] = useState("");
  const [toast, setToast] = useState<{ ok: boolean; issue: string } | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [errors, setErrors] = useState<{ rating?: string; message?: string; consent?: string }>({});
  const consent = useConsent();
  const page = usePathname() ?? "/";
  const consentBox = useRef<HTMLInputElement>(null);
  const uid = useId();
  const ratingBox = useRef<HTMLFieldSetElement>(null);
  const textBox = useRef<HTMLTextAreaElement>(null);
  const ids = {
    rating: `${uid}-rating-error`,
    message: `${uid}-message-error`,
    consent: `${uid}-consent-error`,
    count: `${uid}-count`,
    title: `${uid}-title`,
  };

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    // Say what is missing, next to the field, and move focus to the first problem (WCAG 3.3.1).
    const next = {
      rating: rating === null ? "Choose a rating from 1 to 5." : undefined,
      message: message.trim().length < 3 ? "Write at least a few words so the devs can act on it." : undefined,
      consent: agreed ? undefined : "Tick the consent box to send feedback.",
    };
    setErrors(next);
    if (next.rating) return void ratingBox.current?.querySelector<HTMLInputElement>("input")?.focus();
    if (next.message) return void textBox.current?.focus();
    if (next.consent) return void consentBox.current?.focus();
    // A copy stays in this browser only if the visitor allowed "feedback notes".
    const ok = !!consent?.feedbackNotes && save({ rating: rating!, category, message: message.trim(), page, at: new Date().toISOString() });
    setToast({ ok, issue: issueUrl(rating, category, message, page) });
    setRating(null);
    setMessage("");
    setAgreed(false);
    setErrors({});
  };

  return (
    <form
      onSubmit={submit}
      onMouseMove={trackSpotlight}
      className="panel spotlight relative p-5"
      aria-labelledby={ids.title}
      noValidate
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={ids.title} className="font-display text-lg font-semibold tracking-tight">
          Feedback to the devs
        </h2>
      </div>

      <fieldset ref={ratingBox} className="mt-4" aria-describedby={errors.rating ? ids.rating : undefined}>
        <legend className="mb-2 text-xs text-muted">How is it so far? (required)</legend>
        <div className="flex flex-wrap gap-1.5">
          {RATINGS.map(([n, word]) => (
            <label key={n} className="cursor-pointer">
              <input
                type="radio"
                name="rating"
                value={n}
                checked={rating === n}
                aria-invalid={errors.rating ? true : undefined}
                onChange={() => {
                  setRating(n);
                  setErrors((x) => ({ ...x, rating: undefined }));
                }}
                className="peer sr-only"
              />
              <span
                className="flex items-center gap-1.5 rounded-full border border-hair px-3 py-1 font-mono text-xs text-muted transition-colors hover:border-line hover:text-ink peer-checked:border-ink peer-checked:bg-ink peer-checked:text-bg peer-focus-visible:ring-2 peer-focus-visible:ring-primary/60"
                title={word}
              >
                {n}
                <span className="sr-only"> out of 5, {word}</span>
              </span>
            </label>
          ))}
        </div>
        {errors.rating && (
          <p id={ids.rating} role="alert" className="mt-2 text-xs font-medium text-bad">
            {errors.rating}
          </p>
        )}
      </fieldset>

      <fieldset className="mt-4">
        <legend className="mb-2 text-xs text-muted">What is it about?</legend>
        <div className="grid grid-cols-3 gap-1 rounded-full border border-hair p-1">
          {CATEGORIES.map(({ id, label, icon: Icon }) => (
            <label key={id} className="relative cursor-pointer">
              <input
                type="radio"
                name="category"
                value={id}
                checked={category === id}
                onChange={() => setCategory(id)}
                className="peer sr-only"
              />
              {category === id && (
                <motion.span layoutId="feedback-cat" className="absolute inset-0 rounded-full bg-ink" transition={SPRING} />
              )}
              <span
                className={`relative flex items-center justify-center gap-1.5 rounded-full px-2 py-1.5 text-xs font-medium transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-primary/60 ${
                  category === id ? "text-bg" : "text-muted hover:text-ink"
                }`}
              >
                <Icon size={13} aria-hidden />
                <span className="truncate">{label}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mt-4">
        <div className="mb-2 flex justify-between text-xs text-muted">
          <label htmlFor={`${uid}-message`}>Message (required)</label>
          <span id={ids.count} className="font-mono tabular-nums">
            {message.length} of {MAX} characters
          </span>
        </div>
        <textarea
          id={`${uid}-message`}
          ref={textBox}
          className="input min-h-[88px] resize-y rounded-xl bg-bg"
          maxLength={MAX}
          value={message}
          aria-invalid={errors.message ? true : undefined}
          aria-describedby={[ids.count, errors.message ? ids.message : ""].filter(Boolean).join(" ")}
          onChange={(e) => {
            setMessage(e.target.value);
            setErrors((x) => ({ ...x, message: undefined }));
          }}
          placeholder="What worked, what broke, what you wish it did…"
        />
        {errors.message && (
          <p id={ids.message} role="alert" className="mt-2 text-xs font-medium text-bad">
            {errors.message}
          </p>
        )}
      </div>

      <div className="mt-4">
        <label className="flex cursor-pointer items-start gap-2.5 text-xs">
          <input
            ref={consentBox}
            type="checkbox"
            checked={agreed}
            aria-invalid={errors.consent ? true : undefined}
            aria-describedby={errors.consent ? ids.consent : undefined}
            onChange={(e) => {
              setAgreed(e.target.checked);
              setErrors((x) => ({ ...x, consent: undefined }));
            }}
            className="mt-0.5 h-4 w-4 shrink-0 accent-[rgb(var(--primary))]"
          />
          <span>{CONSENT_TEXT}</span>
        </label>
        <p className="mt-1 pl-[1.625rem] text-xs">
          <Link href="/privacy" className="font-medium text-primary-ink underline underline-offset-2">
            Read the Privacy Policy
          </Link>
        </p>
        {errors.consent && (
          <p id={ids.consent} role="alert" className="mt-2 text-xs font-medium text-bad">
            {errors.consent}
          </p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button type="submit" className="btn-ink">
          <Send size={14} aria-hidden /> Send feedback to the developers
        </button>
        <a
          href={issueUrl(rating, category, message, page)}
          target="_blank"
          rel="noopener noreferrer"
          className="btn rounded-full px-3 text-muted hover:text-ink"
        >
          <GitHubIcon size={14} /> Open a GitHub issue
        </a>
      </div>

      <div aria-live="polite" className="fixed bottom-4 right-4 z-[70] sm:bottom-6 sm:right-6">
        <AnimatePresence>
          {toast && (
            <motion.div
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              transition={SPRING}
              className="flex max-w-xs items-start gap-2.5 rounded-2xl bg-ink px-4 py-3 text-sm text-bg shadow-2xl"
            >
              <CheckCircle2 size={18} className="mt-0.5 shrink-0" aria-hidden />
              <span>
                <span className="block font-medium">Thanks, feedback received.</span>
                <span className="block text-bg/70">
                  {toast.ok ? "A copy is saved in this browser." : "Nothing was stored (see Manage cookies)."}{" "}
                  <a href={toast.issue} target="_blank" rel="noreferrer" className="font-medium text-bg underline underline-offset-2">
                    Send it to GitHub
                  </a>{" "}
                  to reach the devs directly.
                </span>
              </span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </form>
  );
}
