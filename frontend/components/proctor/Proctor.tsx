"use client";

// The proctoring UI: the opt-in (or "required") line, the pre-check before a test, and the bar
// shown during it. Video stays on this device; only events and times reach the server.

import { useEffect, useId, useRef, useState } from "react";
import { Camera, CameraOff, Expand, Loader2, ShieldCheck, ShieldAlert, Sun } from "lucide-react";
import { luminance, openCamera, prepareModels, snapshot, THRESHOLDS, type FaceStatus } from "@/lib/proctor/camera";
import type { CameraChoice, Proctor } from "@/lib/proctor/useProctor";
import { ErrorNote } from "@/components/ui";

/** Above the Start button: "Proctor this quiz" for practice, a plain note when required. */
export function ProctorChoice({ proctor, what }: { proctor: Proctor; what: "quiz" | "interview" }) {
  const id = useId();
  const p = proctor.policy;
  if (!p) return null;
  if (p.required) {
    return (
      <p className="flex items-start gap-2 text-sm text-muted">
        <ShieldCheck size={16} className="mt-0.5 shrink-0" aria-hidden />
        Your organization proctors this {what}
        {p.seb ? " in Safe Exam Browser" : ""}. A short check runs before it starts.
      </p>
    );
  }
  return (
    <label htmlFor={id} className="flex items-start gap-2 text-sm">
      <input id={id} type="checkbox" className="mt-1" checked={proctor.optIn} onChange={(e) => proctor.setOptIn(e.target.checked)} />
      <span>
        Proctor this {what} <span className="text-muted">(practice for a proctored test; optional)</span>
      </span>
    </label>
  );
}

function Meter({ label, ok, children }: { label: string; ok: boolean | null; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      <span className={`chip ${ok === null ? "border-line text-muted" : ok ? "border-ok/40 text-ok" : "border-warn/40 text-warn"}`}>
        {ok === null ? "…" : ok ? "OK" : "Check"}
      </span>
      <span>
        <span className="font-medium">{label}</span> <span className="text-muted">{children}</span>
      </span>
    </li>
  );
}

/** Before a proctored test: camera preview, lighting and face check, the consent text. */
function PreCheck({ proctor }: { proctor: Proctor }) {
  const title = useId();
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [choice, setChoice] = useState<CameraChoice | null>(null);
  const [status, setStatus] = useState<FaceStatus | null>(null);
  const [models, setModels] = useState<boolean | null>(null);
  const [agreed, setAgreed] = useState(false);
  const starting = proctor.phase === "starting";

  const { adoptPreview } = proctor;
  useEffect(() => {
    let live = true;
    void openCamera().then((c) => {
      if (!live) return c.stream?.getTracks().forEach((t) => t.stop());
      adoptPreview(c.stream); // useProctor stops it on Cancel, or hands it to the test
      setChoice(c);
    });
    void prepareModels().then((ok) => live && setModels(ok));
    // A permission prompt left unanswered must not block the test: after a while it can start
    // without the camera (noted for review). Answering later still switches the camera on.
    const wait = setTimeout(() => {
      if (live) setChoice((c) => c ?? { stream: null, note: "camera permission not answered" });
    }, 8000);
    return () => {
      live = false;
      clearTimeout(wait);
    };
  }, [adoptPreview]);

  useEffect(() => {
    const v = video.current;
    if (!v || !choice?.stream) return;
    v.srcObject = choice.stream;
    void v.play().catch(() => undefined);
    const t = setInterval(async () => {
      if (!canvas.current) return;
      setStatus(models ? await snapshot(v, canvas.current) : { faces: -1, centred: false, luma: luminance(v, canvas.current) });
    }, 700);
    return () => clearInterval(t);
  }, [choice, models]);

  const dark = status?.luma != null && status.luma < THRESHOLDS.darkLuma;
  const policy = proctor.policy;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4" role="dialog" aria-modal="true" aria-labelledby={title}>
      <div className="card max-h-[92vh] w-full max-w-2xl overflow-y-auto">
        <h2 id={title} className="flex items-center gap-2 font-semibold">
          <ShieldCheck size={18} aria-hidden /> Before you start: proctoring check
        </h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div>
            {choice === null ? (
              <p className="grid aspect-[4/3] place-items-center rounded-2xl border border-hair text-sm text-muted">
                <Loader2 size={18} className="animate-spin" aria-hidden /> Asking for the camera…
              </p>
            ) : choice.stream ? (
              <video ref={video} muted playsInline className="aspect-[4/3] w-full rounded-2xl border border-hair bg-ink/5 object-cover [transform:scaleX(-1)]" aria-label="Your camera preview (stays on this device)" />
            ) : (
              <p className="grid aspect-[4/3] place-items-center gap-2 rounded-2xl border border-dashed border-line p-4 text-center text-sm text-muted">
                <CameraOff size={20} aria-hidden />
                No camera ({choice.note}). Camera checks will be skipped and noted for review; the test still runs.
              </p>
            )}
            <canvas ref={canvas} width={64} height={48} hidden />
            <p className="mt-2 text-xs text-muted">The picture is checked only in this browser. No video or image is sent or saved.</p>
          </div>
          <ul className="grid content-start gap-2">
            {choice?.stream ? (
              <>
                <Meter label="Lighting" ok={status?.luma == null ? null : !dark}>
                  {dark ? "too dark: face a window or turn on a light" : "fine"}
                </Meter>
                {models === false ? (
                  <Meter label="Face check" ok={false}>
                    unavailable on this server: camera checks will be skipped and noted
                  </Meter>
                ) : (
                  <Meter label="Your face" ok={!status || status.faces < 0 ? null : status.faces === 1 && status.centred}>
                    {!status || status.faces < 0
                      ? "loading the check…"
                      : status.faces === 0
                        ? "not found: sit facing the camera"
                        : status.faces > 1
                          ? "more than one face in view"
                          : status.centred
                            ? "in view"
                            : "move to the middle of the picture"}
                  </Meter>
                )}
                <li className="flex items-start gap-2 text-xs text-muted">
                  <Sun size={14} className="mt-0.5 shrink-0" aria-hidden /> These are hints, not requirements: you can start anyway.
                </li>
              </>
            ) : null}
            <li className="flex items-start gap-2 text-sm text-muted">
              <Expand size={16} className="mt-0.5 shrink-0" aria-hidden /> The test opens in fullscreen. Stay in it until you submit.
            </li>
          </ul>
        </div>
        <p className="mt-4 rounded-2xl border border-hair bg-surface/60 p-4 text-sm">{policy?.consent_text}</p>
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />I have read this and agree to start a proctored test.
        </label>
        <ErrorNote message={proctor.error} />
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={proctor.cancel} disabled={starting}>
            Cancel
          </button>
          <button type="button" className="btn-primary" disabled={!agreed || choice === null || starting} onClick={() => choice && proctor.confirm(choice)}>
            {starting ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Expand size={16} aria-hidden />} Start in fullscreen
          </button>
        </div>
      </div>
    </div>
  );
}

/** During the test: strikes in words, a way back to fullscreen, and a small self-view. */
function Bar({ proctor }: { proctor: Proctor }) {
  const self = useRef<HTMLVideoElement>(null);
  const { progress, camera, fullscreenLost, policy } = proctor;
  useEffect(() => {
    if (self.current && camera.stream) {
      self.current.srcObject = camera.stream;
      void self.current.play().catch(() => undefined);
    }
  }, [camera.stream]);
  const max = policy?.max_strikes ?? 3;
  return (
    <>
      <div role="status" aria-live="assertive" className="sticky top-2 z-30 mb-3 flex flex-wrap items-center gap-3 rounded-2xl border border-hair bg-bg/95 px-4 py-2 text-sm shadow-sm">
        {progress.strikes ? <ShieldAlert size={16} className="text-warn" aria-hidden /> : <ShieldCheck size={16} className="text-ok" aria-hidden />}
        <span className="font-medium">
          Proctored · strikes {progress.strikes} of {max}
        </span>
        {progress.warning && <span className="text-warn">{progress.warning}</span>}
        {fullscreenLost && !progress.breached && (
          <button type="button" className="btn-ink min-h-0 px-3 py-1 text-xs" onClick={proctor.returnToFullscreen}>
            <Expand size={13} aria-hidden /> Return to fullscreen
          </button>
        )}
      </div>
      <div className="fixed bottom-3 right-3 z-30 w-36 overflow-hidden rounded-xl border border-hair bg-bg/95 text-[11px] shadow-sm">
        {camera.stream ? (
          <video ref={self} muted playsInline className="aspect-[4/3] w-full object-cover [transform:scaleX(-1)]" aria-label="Your camera (checked on this device only)" />
        ) : null}
        <p className="flex items-center gap-1 px-2 py-1 text-muted">
          {camera.stream ? <Camera size={12} aria-hidden /> : <CameraOff size={12} aria-hidden />}
          {camera.stream ? "Checked on this device only" : `Camera checks skipped${camera.note ? `: ${camera.note}` : ""}`}
        </p>
      </div>
    </>
  );
}

/** Put once on a page that uses useProctor. */
export function ProctorLayer({ proctor }: { proctor: Proctor }) {
  if (proctor.phase === "checking" || proctor.phase === "starting") return <PreCheck proctor={proctor} />;
  if (proctor.phase === "running") return <Bar proctor={proctor} />;
  return null;
}

/** After a proctored test: what was recorded, with a link to the full record. */
export function ProctorSummary({ outcome }: { outcome: { strikes: number; breached: boolean } | null | undefined }) {
  if (!outcome) return null;
  return (
    <p className={`mt-3 flex items-start gap-2 text-sm ${outcome.breached ? "text-bad" : "text-muted"}`}>
      {outcome.breached ? <ShieldAlert size={16} className="mt-0.5 shrink-0" aria-hidden /> : <ShieldCheck size={16} className="mt-0.5 shrink-0" aria-hidden />}
      {outcome.breached
        ? `Submitted after ${outcome.strikes} proctoring strikes.`
        : `Proctored: ${outcome.strikes} strike${outcome.strikes === 1 ? "" : "s"}.`}{" "}
      <a href="/settings#proctoring" className="underline">
        See your proctoring record
      </a>
    </p>
  );
}
