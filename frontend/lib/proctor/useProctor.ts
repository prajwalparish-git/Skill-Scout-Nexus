"use client";

// A proctored quiz or interview on a page: the policy (practice, required, Safe Exam Browser),
// the pre-check, then the attempt (browser checks + camera checks) until the page ends it.

import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, type ProctorPolicy, type ProctorProgress } from "@/lib/api";
import { modelsAvailable, monitor } from "@/lib/proctor/camera";
import { ProctorSession } from "@/lib/proctor/session";

export type Phase = "idle" | "checking" | "starting" | "running";
export type CameraChoice = { stream: MediaStream } | { stream: null; note: string };

export type ProctorState =
  | { status: "idle" }
  | { status: "checking"; label: string; preview: MediaStream | null; error: string | null }
  | { status: "starting"; label: string; preview: MediaStream | null }
  | {
      status: "running";
      attemptId: string;
      cameraStream: MediaStream | null;
      cameraNote: string;
      strikes: number;
      breached: boolean;
      warning: string | null;
      fullscreenLost: boolean;
    }
  | { status: "error"; message: string };

type Options = { kind: "quiz" | "interview"; signedIn: boolean; onBreach: () => void };

export type Proctor = ReturnType<typeof useProctor>;

export function useProctor({ kind, signedIn, onBreach }: Options) {
  const [policy, setPolicy] = useState<ProctorPolicy | null>(null);
  const [optIn, setOptIn] = useState(false);
  const [state, setState] = useState<ProctorState>({ status: "idle" });
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<ProctorProgress>({ strikes: 0, breached: false, warning: null });
  const [fullscreenLost, setFullscreenLost] = useState(false);
  const [camera, setCamera] = useState<{ stream: MediaStream | null; note: string }>({ stream: null, note: "" });
  const [error, setError] = useState<string | null>(null);
  const [attemptId, setAttemptId] = useState<string | null>(null);

  const session = useRef<ProctorSession | null>(null);
  const stopCamera = useRef<(() => void) | null>(null);
  const pending = useRef<{ label: string; run: () => Promise<void> } | null>(null);
  const preview = useRef<MediaStream | null>(null); // the pre-check's camera, until Start takes it
  const cameraStreamRef = useRef<MediaStream | null>(null); // active camera stream during running test
  const runningAttemptId = useRef<string | null>(null);
  const breachRef = useRef(onBreach);
  breachRef.current = onBreach;
  const breached = useRef(false);

  useEffect(() => {
    setPolicy(null);
    if (!signedIn) return;
    let live = true;
    get<ProctorPolicy>("/api/proctor/policy").then(
      (p) => live && setPolicy(p),
      () => live && setPolicy(null),
    );
    return () => {
      live = false;
    };
  }, [signedIn]);

  const wanted = Boolean(signedIn && policy && (policy.required || optIn));

  /** Show the pre-check; `run` starts the test once the attempt exists. */
  const open = useCallback((label: string, run: () => Promise<void>) => {
    pending.current = { label, run };
    setError(null);
    setPhase("checking");
    setState({ status: "checking", label, preview: preview.current, error: null });
  }, []);

  /** The pre-check opened the camera: this hook stops it unless the test takes it over. */
  const adoptPreview = useCallback((stream: MediaStream | null) => {
    preview.current = stream;
    setState((prev) => (prev.status === "checking" ? { ...prev, preview: stream } : prev));
  }, []);

  const cancel = useCallback(() => {
    preview.current?.getTracks().forEach((t) => t.stop());
    preview.current = null;
    cameraStreamRef.current?.getTracks().forEach((t) => t.stop());
    cameraStreamRef.current = null;
    runningAttemptId.current = null;
    pending.current = null;
    setAttemptId(null);
    setPhase("idle");
    setState({ status: "idle" });
  }, []);

  const handleFullscreenLost = useCallback((lost: boolean) => {
    setFullscreenLost(lost);
    setState((prev) => (prev.status === "running" ? { ...prev, fullscreenLost: lost } : prev));
  }, []);

  const onProgress = useCallback((p: ProctorProgress) => {
    setProgress(p);
    setState((prev) =>
      prev.status === "running" ? { ...prev, strikes: p.strikes, breached: p.breached, warning: p.warning } : prev,
    );
    if (p.breached && !breached.current) {
      breached.current = true;
      breachRef.current();
    }
  }, []);

  /** From the pre-check's Start button (a user gesture: fullscreen is only allowed in one). */
  const confirm = useCallback(
    (choice: CameraChoice) => {
      const job = pending.current;
      if (!job || !policy) return;
      const full = document.documentElement.requestFullscreen?.().catch(() => undefined); // in the click
      setPhase("starting");
      setError(null);
      setState({ status: "starting", label: job.label, preview: choice.stream });
      void (async () => {
        await full;
        let stream = choice.stream;
        let note = choice.stream ? "" : choice.note;
        if (stream) {
          const models = await modelsAvailable();
          if (!models.ok) {
            stream = null; // the preview stays with the pre-check (stopped on cancel)
            note = models.note;
          }
        }
        try {
          const started = await post<{ attempt_id: string }>("/api/proctor/attempts", {
            kind,
            label: job.label,
            camera: stream ? "on" : "unavailable",
            camera_note: note,
            consent: true,
          });
          breached.current = false;
          setProgress({ strikes: 0, breached: false, warning: null });
          const isFsLost = !document.fullscreenElement;
          const s = new ProctorSession(started.attempt_id, policy.heartbeat_s, onProgress, handleFullscreenLost);
          session.current = s;
          s.begin();
          setFullscreenLost(isFsLost);
          setAttemptId(started.attempt_id);
          runningAttemptId.current = started.attempt_id;
          if (stream) {
            preview.current = null; // the test owns it now
            cameraStreamRef.current = stream;
          } else {
            preview.current?.getTracks().forEach((t) => t.stop());
            preview.current = null;
            cameraStreamRef.current = null;
          }
          setCamera({ stream, note });
          if (stream) {
            const video = document.createElement("video");
            video.muted = true;
            video.playsInline = true;
            video.srcObject = stream;
            await video.play().catch(() => undefined);
            stopCamera.current = await monitor(video, stream, (k, d) => s.report(k, d));
          }
          setPhase("running");
          setState({
            status: "running",
            attemptId: started.attempt_id,
            cameraStream: stream,
            cameraNote: note,
            strikes: 0,
            breached: false,
            warning: null,
            fullscreenLost: isFsLost,
          });
          pending.current = null;
          await job.run();
        } catch (e) {
          // keep the preview for another try; Cancel or leaving the page stops it
          if (document.fullscreenElement) await document.exitFullscreen().catch(() => undefined);
          const msg = (e as Error).message;
          setError(msg);
          setPhase("checking");
          setState({ status: "checking", label: job.label, preview: preview.current, error: msg });
        }
      })();
    },
    [kind, policy, onProgress, handleFullscreenLost],
  );

  /** End the checks (after the submit or the last turn). */
  const end = useCallback(async () => {
    stopCamera.current?.();
    stopCamera.current = null;
    await session.current?.stop();
    session.current = null;
    cameraStreamRef.current?.getTracks().forEach((t) => t.stop());
    cameraStreamRef.current = null;
    camera.stream?.getTracks().forEach((t) => t.stop());
    preview.current?.getTracks().forEach((t) => t.stop());
    preview.current = null;
    runningAttemptId.current = null;
    setCamera({ stream: null, note: "" });
    setFullscreenLost(false);
    setAttemptId(null);
    setPhase("idle");
    setState({ status: "idle" });
  }, [camera.stream]);

  /** The live attempt's id, read at call time: strictly returns the active attemptId when running,
   * and null otherwise. Requests made right after Start (before React re-renders) still carry it. */
  const currentAttemptId = useCallback(() => {
    if (state.status === "idle" || state.status === "error") return null;
    return runningAttemptId.current;
  }, [state.status]);

  const returnToFullscreen = useCallback(() => {
    void document.documentElement.requestFullscreen?.().catch(() => undefined);
  }, []);

  // Leaving the page mid-test: stop the camera (both preview and active monitor) and listeners.
  useEffect(
    () => () => {
      stopCamera.current?.();
      stopCamera.current = null;
      void session.current?.stop();
      session.current = null;
      runningAttemptId.current = null;
      preview.current?.getTracks().forEach((t) => t.stop());
      preview.current = null;
      cameraStreamRef.current?.getTracks().forEach((t) => t.stop());
      cameraStreamRef.current = null;
    },
    [],
  );

  return {
    state,
    policy,
    wanted,
    optIn,
    setOptIn,
    phase,
    progress,
    fullscreenLost,
    camera,
    error,
    attemptId,
    lastAttemptId: attemptId,
    currentAttemptId,
    open,
    adoptPreview,
    cancel,
    confirm,
    end,
    returnToFullscreen,
  };
}
