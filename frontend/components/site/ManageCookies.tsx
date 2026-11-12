"use client";

import { openConsentSettings } from "@/lib/consent";

/** Re-opens the cookie and storage preferences. */
export function ManageCookiesButton({ className = "btn-hair" }: { className?: string }) {
  return (
    <button type="button" className={className} onClick={openConsentSettings}>
      Manage cookies
    </button>
  );
}
