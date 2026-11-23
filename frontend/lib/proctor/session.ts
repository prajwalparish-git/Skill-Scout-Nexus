// One proctored attempt in the browser: the browser checks (tab, window focus, fullscreen,
// copy/paste lock) and the event queue to /api/proctor (server_proctor.py). The server decides
// what is a strike; this only reports what happened and when. No image or video is ever sent.

import { API, post, type ProctorProgress } from "@/lib/api";

/** Event kinds the page may report (core/proctoring.py CATALOGUE, minus the server's own). */
export type EventKind =
  | "TAB_HIDDEN"
  | "WINDOW_BLUR"
  | "FULLSCREEN_EXIT"
  | "SECOND_FACE"
  | "PHONE_VISIBLE"
  | "NO_FACE"
  | "LOOKED_AWAY"
  | "OUT_OF_FRAME"
  | "LOW_LIGHT"
  | "CAMERA_LOST"
  | "PASTE_BLOCKED";

const CLEAR = new Set<EventKind>(["TAB_HIDDEN", "WINDOW_BLUR", "FULLSCREEN_EXIT", "SECOND_FACE", "PHONE_VISIBLE"]);
const BLUR_GRACE_MS = 2000; // a permission bubble or a notification is not leaving the test
const SAME_KIND_MS = 1500; // one burst of the same event is one report
const PASTE_EVERY_MS = 10_000;
const MAX_BATCH = 50;

type Pending = { kind: EventKind; at_s: number; duration_s?: number };

export class ProctorSession {
  private queue: Pending[] = [];
  private startedAt = performance.now();
  private lastOf = new Map<EventKind, number>();
  private blurTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private sending = false;
  private stopped = false;
  private undo: (() => void)[] = [];

  constructor(
    readonly attemptId: string,
    private heartbeatS: number,
    private onProgress: (p: ProctorProgress) => void,
    private onFullscreenLost: (lost: boolean) => void,
  ) {}

  /** Seconds since the attempt started (what every event is stamped with). */
  elapsed(): number {
    return (performance.now() - this.startedAt) / 1000;
  }

  begin(): void {
    const on = <K extends keyof DocumentEventMap>(target: Document, type: K, fn: (e: DocumentEventMap[K]) => void) => {
      target.addEventListener(type, fn, true);
      this.undo.push(() => target.removeEventListener(type, fn, true));
    };
    const onWin = <K extends keyof WindowEventMap>(type: K, fn: (e: WindowEventMap[K]) => void) => {
      window.addEventListener(type, fn, true);
      this.undo.push(() => window.removeEventListener(type, fn, true));
    };
    on(document, "visibilitychange", () => {
      if (document.visibilityState === "hidden") this.report("TAB_HIDDEN");
    });
    onWin("blur", () => {
      if (this.blurTimer) clearTimeout(this.blurTimer);
      this.blurTimer = setTimeout(() => {
        if (!document.hasFocus() && document.visibilityState === "visible") this.report("WINDOW_BLUR");
      }, BLUR_GRACE_MS);
    });
    onWin("focus", () => {
      if (this.blurTimer) clearTimeout(this.blurTimer);
    });
    on(document, "fullscreenchange", () => {
      const lost = !document.fullscreenElement;
      this.onFullscreenLost(lost);
      if (lost) this.report("FULLSCREEN_EXIT");
    });
    const block = (e: Event) => {
      e.preventDefault();
      if (e.type === "paste") this.report("PASTE_BLOCKED", undefined, PASTE_EVERY_MS);
    };
    for (const type of ["copy", "cut", "paste", "contextmenu", "dragstart", "drop"] as const) on(document, type, block);
    onWin("pagehide", () => this.beacon());
    this.heartbeat = setInterval(() => void this.flush(), Math.max(10, this.heartbeatS) * 1000);
    void this.flush(); // the first heartbeat
  }

  /** Report an event (duration in seconds for "for review" episodes). Clear events go at once. */
  report(kind: EventKind, durationS?: number, minGapMs = SAME_KIND_MS): void {
    if (this.stopped) return;
    const now = performance.now();
    if (now - (this.lastOf.get(kind) ?? -Infinity) < minGapMs) return;
    this.lastOf.set(kind, now);
    const at = durationS ? Math.max(0, this.elapsed() - durationS) : this.elapsed();
    this.queue.push({ kind, at_s: Math.round(at * 10) / 10, ...(durationS ? { duration_s: Math.round(durationS) } : {}) });
    if (CLEAR.has(kind)) void this.flush();
  }

  /** Send what is queued (an empty batch is the heartbeat) and pass on the server's count. */
  async flush(): Promise<void> {
    if (this.sending || this.stopped) return;
    this.sending = true;
    const batch = this.queue.splice(0, MAX_BATCH);
    try {
      const p = await post<ProctorProgress>(`/api/proctor/attempts/${this.attemptId}/events`, { events: batch });
      this.onProgress(p);
    } catch {
      this.queue.unshift(...batch); // offline for a moment: try again with the next heartbeat
    } finally {
      this.sending = false;
    }
    if (this.queue.length && this.queue.some((e) => CLEAR.has(e.kind))) void this.flush();
  }

  /** Leaving the page: hand the queue to the browser to deliver. */
  private beacon(): void {
    if (!this.queue.length || typeof navigator.sendBeacon !== "function") return;
    const body = new Blob([JSON.stringify({ events: this.queue.splice(0, MAX_BATCH) })], { type: "application/json" });
    navigator.sendBeacon(`${API}/api/proctor/attempts/${this.attemptId}/events`, body);
  }

  /** Stop the checks (after submit): send what is left, then remove every listener. */
  async stop(): Promise<void> {
    if (this.stopped) return;
    if (this.queue.length) await this.flush();
    this.stopped = true;
    if (this.heartbeat) clearInterval(this.heartbeat);
    if (this.blurTimer) clearTimeout(this.blurTimer);
    this.undo.forEach((u) => u());
    this.undo = [];
    if (document.fullscreenElement) await document.exitFullscreen().catch(() => undefined);
  }
}
