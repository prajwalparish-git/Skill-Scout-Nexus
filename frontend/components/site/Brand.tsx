/* eslint-disable @next/next/no-img-element */
// The brand lock-up from static/brand (copied to public/brand). The wordmark is used as a mask
// so it takes the text colour and reads in both light and dark themes.

const WORDMARK_RATIO = 17087 / 2100;

/** GitHub's mark (lucide no longer ships brand icons). */
export function GitHubIcon({ size = 16, className = "" }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} fill="currentColor" aria-hidden className={className}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

/** Mouse handler that moves a `.spotlight` element's light to the cursor. */
export function trackSpotlight(e: React.MouseEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--x", `${e.clientX - r.left}px`);
  e.currentTarget.style.setProperty("--y", `${e.clientY - r.top}px`);
}

export function Brand({ height = 15, className = "" }: { height?: number; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <img src="/brand/mark.svg" alt="" width={height * 1.85} height={height * 1.85} className="shrink-0" />
      <span
        aria-hidden
        className="block bg-current"
        style={{
          height,
          width: Math.round(height * WORDMARK_RATIO),
          maskImage: "url(/brand/wordmark.svg)",
          WebkitMaskImage: "url(/brand/wordmark.svg)",
          maskSize: "contain",
          WebkitMaskSize: "contain",
          maskRepeat: "no-repeat",
          WebkitMaskRepeat: "no-repeat",
        }}
      />
      <span className="sr-only">Skill Scout Nexus</span>
    </span>
  );
}
