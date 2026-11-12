"use client";

// Privacy-first wrapper for any third-party embed (video, map, slides). Nothing is requested
// from the other site until the visitor presses the button, and the frame is sandboxed and sent
// no referrer. The app ships no embeds today; use this for any added later.
import { useState } from "react";
import { ExternalLink, ShieldCheck } from "lucide-react";

export function ClickToLoad({
  provider,
  title,
  src,
  height = 360,
  allow = "",
}: {
  provider: string;
  title: string;
  src: string;
  height?: number;
  allow?: string;
}) {
  const [loaded, setLoaded] = useState(false);
  if (loaded)
    return (
      <iframe
        title={title}
        src={src}
        height={height}
        className="w-full rounded-card border border-hair"
        loading="lazy"
        referrerPolicy="no-referrer"
        sandbox="allow-scripts allow-same-origin allow-popups"
        allow={allow}
      />
    );
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-card border border-dashed border-line p-6 text-center" style={{ minHeight: height }}>
      <ShieldCheck size={22} aria-hidden className="text-muted" />
      <p className="max-w-sm text-sm text-muted">
        This content comes from {provider}. Loading it sends your IP address and browser details to {provider}, under
        their own privacy policy.
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        <button type="button" className="btn-ink" onClick={() => setLoaded(true)}>
          Load {title} from {provider}
        </button>
        <a href={src} target="_blank" rel="noopener noreferrer" className="btn-hair">
          Open on {provider} <ExternalLink size={14} aria-hidden />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>
    </div>
  );
}
