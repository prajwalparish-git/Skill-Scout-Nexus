"use client";

// The visitor's cookie and browser-storage choice, kept in localStorage ("ssn.consent").
// Essential storage (the chosen profile here, the sign-in cookie in the main app) works without
// a choice, as strictly necessary storage may; optional storage waits for an explicit yes.
import { useEffect, useState } from "react";

export type Consent = {
  v: 1;
  essential: true;
  /** Keep a copy of the feedback you send, in this browser only. */
  feedbackNotes: boolean;
  at: string;
};

const KEY = "ssn.consent";
const CHANGED = "ssn:consent-changed";
const OPEN = "ssn:consent-open";
export const FEEDBACK_KEY = "ssn.feedback";

export function readConsent(): Consent | null {
  try {
    const c = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return c && c.v === 1 ? (c as Consent) : null;
  } catch {
    return null;
  }
}

export function saveConsent(feedbackNotes: boolean): Consent {
  const c: Consent = { v: 1, essential: true, feedbackNotes, at: new Date().toISOString() };
  try {
    localStorage.setItem(KEY, JSON.stringify(c));
    if (!feedbackNotes) localStorage.removeItem(FEEDBACK_KEY); // withdrawing removes what was kept
  } catch {
    /* storage blocked: the choice lasts for this visit */
  }
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: c }));
  return c;
}

/** Opens the preferences again (the footer's "Manage cookies"). */
export function openConsentSettings(): void {
  window.dispatchEvent(new Event(OPEN));
}

export function onConsentOpen(handler: () => void): () => void {
  window.addEventListener(OPEN, handler);
  return () => window.removeEventListener(OPEN, handler);
}

/** The current choice (null until the visitor has made one), kept in sync across components. */
export function useConsent(): Consent | null {
  const [consent, setConsent] = useState<Consent | null>(null);
  useEffect(() => {
    setConsent(readConsent());
    const onChange = (e: Event) => setConsent((e as CustomEvent<Consent>).detail);
    window.addEventListener(CHANGED, onChange);
    return () => window.removeEventListener(CHANGED, onChange);
  }, []);
  return consent;
}
