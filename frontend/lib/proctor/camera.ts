// Camera checks for a proctored attempt, entirely in the browser with MediaPipe (self-hosted in
// /mediapipe by scripts/fetch-mediapipe.mjs). Frames are analysed in this tab and dropped: only
// event kinds and durations ever leave it, through ProctorSession.report.
//
// Clear (strikes, must hold ~2 s): a second face, a phone. For review only (never a strike):
// no face, looking away, out of the frame, too dark, the camera stopping. Each review episode is
// reported when it ends, with how long it lasted ("looked away 14s at 03:42").

import type { EventKind } from "@/lib/proctor/session";

type Report = (kind: EventKind, durationS?: number) => void;

const BASE = "/mediapipe";
const TICK_MS = 500; // about 2 checks a second keeps a laptop cool
const OBJECT_EVERY = 2; // the phone check runs every other tick
const LIGHT_EVERY = 4;

// Thresholds (seconds unless noted). Generous on purpose: a false strike is worse than a miss.
export const THRESHOLDS = {
  clearHoldS: 2, // a second face / phone must be seen this long (>= 3 checks in a row)
  noFaceS: 5,
  lookAwayS: 8,
  outOfFrameS: 5,
  lowLightS: 10,
  darkLuma: 40, // mean of 0-255 on a 64x48 frame
  phoneScore: 0.5,
  faceScore: 0.6,
  yawRatio: 0.35, // nose off the face's centre, as a share of the face's width
  pitchRatio: 0.3,
  gaze: 0.7, // blendshape eyeLook* score
  frameMargin: 0.12, // the face's centre must stay inside the middle of the picture
};

export type Availability = { ok: true } | { ok: false; note: string };

/** Whether this server has the MediaPipe files (scripts/fetch-mediapipe.mjs wrote a manifest). */
export async function modelsAvailable(): Promise<Availability> {
  try {
    const res = await fetch(`${BASE}/manifest.json`, { cache: "no-store" });
    if (!res.ok) return { ok: false, note: "camera checks disabled (models not installed)" };
    const m = (await res.json()) as { ok?: boolean };
    return m.ok ? { ok: true } : { ok: false, note: "camera checks disabled (models not installed)" };
  } catch {
    return { ok: false, note: "camera checks disabled (models not installed)" };
  }
}

/** The camera, or null with why (no device, denied, unsupported). */
export async function openCamera(): Promise<{ stream: MediaStream } | { stream: null; note: string }> {
  if (!navigator.mediaDevices?.getUserMedia) return { stream: null, note: "no camera support in this browser" };
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: false });
    return { stream };
  } catch (e) {
    const name = (e as DOMException).name;
    return { stream: null, note: name === "NotAllowedError" ? "camera permission denied" : "no camera found" };
  }
}

/** Mean brightness (0-255) of the current frame, from a tiny canvas. */
export function luminance(video: HTMLVideoElement, canvas: HTMLCanvasElement): number | null {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx || video.readyState < 2) return null;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
  return sum / (d.length / 4);
}

/** A condition that has to hold for a while: fires `onStart` once it has held `holdS`, and
 * `onEnd(seconds)` when it stops (or the monitor stops) after having fired. */
class Episode {
  private since: number | null = null;
  private fired = false;
  constructor(
    private holdS: number,
    private onStart: (() => void) | null,
    private onEnd: ((s: number) => void) | null,
  ) {}
  update(active: boolean, now: number): void {
    if (active) {
      this.since ??= now;
      if (!this.fired && (now - this.since) / 1000 >= this.holdS) {
        this.fired = true;
        this.onStart?.();
      }
    } else this.end(now);
  }
  end(now: number): void {
    if (this.fired && this.since !== null) this.onEnd?.((now - this.since) / 1000);
    this.since = null;
    this.fired = false;
  }
}

export type FaceStatus = { faces: number; centred: boolean; luma: number | null };

type Vision = typeof import("@mediapipe/tasks-vision");
type Landmarker = import("@mediapipe/tasks-vision").FaceLandmarker;
type Detector = import("@mediapipe/tasks-vision").ObjectDetector;

/** Loads MediaPipe once per page; null when the files are missing or fail to load. */
let loading: Promise<{ face: Landmarker; objects: Detector } | null> | null = null;
function loadModels(): Promise<{ face: Landmarker; objects: Detector } | null> {
  loading ??= (async () => {
    try {
      const vision: Vision = await import("@mediapipe/tasks-vision");
      const files = await vision.FilesetResolver.forVisionTasks(`${BASE}/wasm`);
      const face = await vision.FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${BASE}/models/face_landmarker.task`, delegate: "CPU" },
        runningMode: "VIDEO",
        numFaces: 3,
        minFaceDetectionConfidence: THRESHOLDS.faceScore,
        outputFaceBlendshapes: true,
      });
      const objects = await vision.ObjectDetector.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${BASE}/models/efficientdet_lite0.tflite`, delegate: "CPU" },
        runningMode: "VIDEO",
        scoreThreshold: THRESHOLDS.phoneScore,
        categoryAllowlist: ["cell phone"],
        maxResults: 2,
      });
      return { face, objects };
    } catch {
      return null;
    }
  })();
  return loading;
}

/** Load the models (for the pre-check): false when they cannot run here. */
export async function prepareModels(): Promise<boolean> {
  return (await loadModels()) !== null;
}

function faceSignals(result: import("@mediapipe/tasks-vision").FaceLandmarkerResult) {
  const faces = result.faceLandmarks.length;
  if (!faces) return { faces, away: false, centred: false };
  const lm = result.faceLandmarks[0];
  const nose = lm[1];
  const left = lm[234];
  const right = lm[454];
  const top = lm[10];
  const chin = lm[152];
  const width = Math.abs(right.x - left.x) || 1e-3;
  const height = Math.abs(chin.y - top.y) || 1e-3;
  const yaw = (nose.x - (left.x + right.x) / 2) / width;
  const pitch = (nose.y - (top.y + chin.y) / 2) / height;
  const shapes = result.faceBlendshapes[0]?.categories ?? [];
  const gaze = Math.max(0, ...shapes.filter((c) => c.categoryName.startsWith("eyeLook")).map((c) => c.score));
  const away = Math.abs(yaw) > THRESHOLDS.yawRatio || Math.abs(pitch) > THRESHOLDS.pitchRatio || gaze > THRESHOLDS.gaze;
  const m = THRESHOLDS.frameMargin;
  const centred = nose.x > m && nose.x < 1 - m && nose.y > m && nose.y < 1 - m;
  return { faces, away, centred };
}

/** One-off reading for the pre-check: faces in view, centred, brightness. */
export async function snapshot(video: HTMLVideoElement, canvas: HTMLCanvasElement): Promise<FaceStatus> {
  const luma = luminance(video, canvas);
  const models = await loadModels();
  if (!models || video.readyState < 2) return { faces: -1, centred: false, luma };
  const s = faceSignals(models.face.detectForVideo(video, performance.now()));
  return { faces: s.faces, centred: s.centred, luma };
}

/** Watch the camera during the attempt and report events. Returns stop(). */
export async function monitor(video: HTMLVideoElement, stream: MediaStream, report: Report): Promise<() => void> {
  const models = await loadModels();
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 48;
  const T = THRESHOLDS;
  const episodes = {
    second: new Episode(T.clearHoldS, () => report("SECOND_FACE"), null),
    phone: new Episode(T.clearHoldS, () => report("PHONE_VISIBLE"), null),
    noFace: new Episode(T.noFaceS, null, (s) => report("NO_FACE", s)),
    away: new Episode(T.lookAwayS, null, (s) => report("LOOKED_AWAY", s)),
    frame: new Episode(T.outOfFrameS, null, (s) => report("OUT_OF_FRAME", s)),
    dark: new Episode(T.lowLightS, null, (s) => report("LOW_LIGHT", s)),
  };
  let tick = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  const lost = () => !stopped && report("CAMERA_LOST");
  stream.getVideoTracks().forEach((t) => t.addEventListener("ended", lost));

  const step = () => {
    if (stopped) return;
    const now = performance.now();
    try {
      if (tick % LIGHT_EVERY === 0) {
        const luma = luminance(video, canvas);
        if (luma !== null) episodes.dark.update(luma < T.darkLuma, now);
      }
      if (models && video.readyState >= 2) {
        const s = faceSignals(models.face.detectForVideo(video, now));
        episodes.second.update(s.faces >= 2, now);
        episodes.noFace.update(s.faces === 0, now);
        episodes.away.update(s.faces >= 1 && s.away, now);
        episodes.frame.update(s.faces >= 1 && !s.centred, now);
        if (tick % OBJECT_EVERY === 0) {
          const phone = models.objects.detectForVideo(video, now).detections.length > 0;
          episodes.phone.update(phone, now);
        }
      }
    } catch {
      // a dropped frame is not an event
    }
    tick += 1;
    timer = setTimeout(step, TICK_MS);
  };
  step();

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    const now = performance.now();
    Object.values(episodes).forEach((e) => e.end(now)); // report review episodes still open
    stream.getVideoTracks().forEach((t) => t.removeEventListener("ended", lost));
  };
}
