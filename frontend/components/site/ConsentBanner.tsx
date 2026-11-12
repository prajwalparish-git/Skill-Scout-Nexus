"use client";

// Cookie and browser-storage preferences: a bar at the bottom on the first visit, and again
// whenever "Manage cookies" is pressed. Not a modal: the page stays usable behind it.
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Cookie } from "lucide-react";
import { onConsentOpen, readConsent, saveConsent } from "@/lib/consent";
import { SPRING } from "@/lib/site";

export function ConsentBanner() {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false);
  const [notes, setNotes] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const box = useRef<HTMLElement>(null);
  const id = useId();

  // While open, the page keeps room for the banner at the bottom, so nothing (a button, a focused
  // field) is ever stuck behind it (WCAG 2.4.11).
  useEffect(() => {
    if (!open || !box.current) return;
    const body = document.body.style;
    const html = document.documentElement.style;
    const ro = new ResizeObserver(([e]) => {
      const room = `${Math.ceil(e.target.getBoundingClientRect().height) + 24}px`;
      body.paddingBottom = room;
      html.scrollPaddingBottom = room;
    });
    ro.observe(box.current);
    return () => {
      ro.disconnect();
      body.paddingBottom = "";
      html.scrollPaddingBottom = "";
    };
  }, [open]);

  useEffect(() => {
    if (!readConsent()) setOpen(true); // first visit: ask
    return onConsentOpen(() => {
      opener.current = document.activeElement as HTMLElement | null;
      setNotes(readConsent()?.feedbackNotes ?? false);
      setCustom(true);
      setOpen(true);
    });
  }, []);

  // Opened on request: put keyboard focus on the banner, so the choice is the next thing read.
  useEffect(() => {
    if (open && opener.current) heading.current?.focus();
  }, [open]);

  const choose = (feedbackNotes: boolean) => {
    saveConsent(feedbackNotes);
    setOpen(false);
    setCustom(false);
    opener.current?.focus?.();
    opener.current = null;
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.section
          ref={box}
          role="region"
          aria-labelledby={`${id}-title`}
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 24 }}
          transition={SPRING}
          className="glass fixed inset-x-3 bottom-3 z-[65] mx-auto max-w-3xl rounded-2xl p-4 shadow-2xl sm:bottom-4 sm:p-5"
        >
          <div className="flex items-start gap-3">
            <Cookie size={20} aria-hidden className="mt-0.5 shrink-0 text-ink" />
            <div className="min-w-0 flex-1">
              <h2 id={`${id}-title`} ref={heading} tabIndex={-1} className="font-display text-base font-semibold focus:outline-none">
                Cookies and browser storage
              </h2>
              <p className="mt-1 text-sm text-muted">
                No tracking or advertising, ever. Essential storage keeps you signed in and remembers your profile and
                study progress. Anything else is your choice.{" "}
                <Link href="/cookies" className="font-medium text-primary-ink underline underline-offset-2">
                  Read the Cookies Policy
                </Link>
              </p>

              {custom && (
                <fieldset className="mt-3 space-y-2 rounded-xl border border-hair p-3">
                  <legend className="px-1 text-xs font-medium text-muted">Your preferences</legend>
                  <label className="flex items-start gap-2.5 text-sm">
                    <input type="checkbox" checked disabled className="mt-0.5 h-4 w-4" aria-describedby={`${id}-ess`} />
                    <span>
                      <span className="font-medium">Essential</span> (always on)
                      <span id={`${id}-ess`} className="block text-xs text-muted">
                        Sign-in session, your chosen profile and study progress.
                      </span>
                    </span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-2.5 text-sm">
                    <input
                      type="checkbox"
                      checked={notes}
                      onChange={(e) => setNotes(e.target.checked)}
                      className="mt-0.5 h-4 w-4 accent-[rgb(var(--primary))]"
                      aria-describedby={`${id}-notes`}
                    />
                    <span>
                      <span className="font-medium">Feedback notes</span> (optional)
                      <span id={`${id}-notes`} className="block text-xs text-muted">
                        Keep a copy of the feedback you send, in this browser only. Turning it off deletes the copy.
                      </span>
                    </span>
                  </label>
                </fieldset>
              )}

              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className="btn-ink" onClick={() => choose(false)}>
                  Accept essential only
                </button>
                {custom ? (
                  <button type="button" className="btn-hair" onClick={() => choose(notes)}>
                    Save my preferences
                  </button>
                ) : (
                  <button type="button" className="btn-hair" aria-expanded={false} onClick={() => setCustom(true)}>
                    Customize preferences
                  </button>
                )}
              </div>
            </div>
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
