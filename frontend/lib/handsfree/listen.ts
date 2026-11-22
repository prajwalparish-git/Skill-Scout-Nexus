// Detecting the end of a spoken answer, the same rule for everyone: speech, then `silence_s` of
// silence, or the max answer time (what was said is kept). Two tiers:
//   1. Silero VAD (@ricky0123/vad-web, self-hosted in /vad by scripts/copy-vad.mjs);
//   2. loudness (RMS against the room's noise floor), when the model cannot load.
// Push-to-talk (hold) is the manual fallback; typing is the last one.

import { Capture, RATE } from "@/lib/handsfree/audio";

export type Tier = "silero" | "loudness";
export type Heard = { audio: Float32Array | null; spoke: boolean; ended: "silence" | "max" | "stopped" };
export type ListenOptions = {
  silenceS: number;
  maxS: number;
  noSpeechS: number;
  onSpeaking?: (speaking: boolean) => void; // drives the "ending in…" indicator
  onNoSpeech?: () => void;
};

export interface Listener {
  tier: Tier;
  listen(o: ListenOptions): Promise<Heard>;
  stop(): void; // end the current answer now (keeps what was said)
  level(): number; // 0..1, for the meter
  destroy(): void;
}

const LOUD_MIN = 0.015;

export async function vadFilesReady(): Promise<boolean> {
  try {
    const res = await fetch("/vad/manifest.json", { cache: "no-store" });
    return res.ok && Boolean(((await res.json()) as { ok?: boolean }).ok);
  } catch {
    return false;
  }
}

/** The best listener this browser can run, on the mic opened before the test. */
export async function createListener(stream: MediaStream, capture: Capture, silenceS: number): Promise<Listener> {
  if (await vadFilesReady()) {
    try {
      return await sileroListener(stream, capture, silenceS);
    } catch {
      // the model or ONNX Runtime did not load: loudness below
    }
  }
  return loudnessListener(capture);
}

type Handlers = { start: () => void; end: (audio: Float32Array) => void; misfire: () => void };

async function sileroListener(stream: MediaStream, capture: Capture, silenceS: number): Promise<Listener> {
  const { MicVAD } = await import("@ricky0123/vad-web");
  let on: Handlers | null = null;
  let level = 0;
  capture.onBuffer = (rms) => (level = Math.min(1, rms * 8));
  const vad = await MicVAD.new({
    model: "v5",
    baseAssetPath: "/vad/",
    onnxWASMBasePath: "/vad/",
    startOnLoad: false,
    redemptionMs: silenceS * 1000,
    submitUserSpeechOnPause: true,
    getStream: async () => stream,
    pauseStream: async () => undefined, // the mic stays open between questions
    resumeStream: async (s) => s,
    onSpeechRealStart: () => on?.start(),
    onSpeechEnd: (audio) => on?.end(audio),
    onVADMisfire: () => on?.misfire(),
  });
  let stopNow: (() => void) | null = null;
  return {
    tier: "silero",
    level: () => level,
    stop: () => stopNow?.(),
    destroy: () => void vad.destroy(),
    listen: (o) =>
      new Promise<Heard>((resolve) => {
        let spoke = false;
        let done = false;
        let reason: Heard["ended"] = "silence";
        const finish = (h: Heard) => {
          if (done) return;
          done = true;
          clearTimeout(maxTimer);
          clearTimeout(quietTimer);
          on = null;
          void vad.pause();
          o.onSpeaking?.(false);
          resolve(h);
        };
        const cut = (why: Heard["ended"]) => {
          reason = why;
          void vad.pause(); // submitUserSpeechOnPause: a running answer arrives via onSpeechEnd
          setTimeout(() => finish({ audio: null, spoke, ended: why }), 400);
        };
        on = {
          start: () => {
            spoke = true;
            o.onSpeaking?.(true);
          },
          end: (audio) => finish({ audio, spoke: true, ended: reason }),
          misfire: () => o.onSpeaking?.(false),
        };
        const maxTimer = setTimeout(() => cut("max"), o.maxS * 1000);
        const quietTimer = setTimeout(() => !spoke && o.onNoSpeech?.(), o.noSpeechS * 1000);
        stopNow = () => cut("stopped");
        void vad.start();
      }),
  };
}

function loudnessListener(capture: Capture): Listener {
  let level = 0;
  let stopNow: (() => void) | null = null;
  return {
    tier: "loudness",
    level: () => level,
    stop: () => stopNow?.(),
    destroy: () => undefined,
    listen: (o) =>
      new Promise<Heard>((resolve) => {
        let floor = 0;
        let samples = 0;
        let spoke = false;
        let quietFor = 0;
        let done = false;
        const finish = (ended: Heard["ended"]) => {
          if (done) return;
          done = true;
          capture.onBuffer = (rms) => (level = Math.min(1, rms * 8));
          clearTimeout(maxTimer);
          clearTimeout(quietTimer);
          const audio = capture.end();
          o.onSpeaking?.(false);
          resolve({ audio: spoke && audio.length > RATE / 4 ? audio : null, spoke, ended });
        };
        capture.onBuffer = (rms) => {
          level = Math.min(1, rms * 8);
          if (samples < 4) {
            floor = (floor * samples + rms) / (samples + 1); // the room, in the first moments
            samples += 1;
            return;
          }
          const loud = rms > Math.max(LOUD_MIN, floor * 3);
          if (loud) {
            if (!spoke) o.onSpeaking?.(true);
            spoke = true;
            quietFor = 0;
          } else if (spoke) {
            quietFor += capture.bufferSeconds;
            if (quietFor >= o.silenceS) finish("silence");
          } else capture.trim(0.5); // keep only a short lead-in before speech
        };
        void capture.begin();
        const maxTimer = setTimeout(() => finish("max"), o.maxS * 1000);
        const quietTimer = setTimeout(() => !spoke && o.onNoSpeech?.(), o.noSpeechS * 1000);
        stopNow = () => finish("stopped");
      }),
  };
}

/** Push-to-talk: record while held. */
export async function holdToTalk(capture: Capture): Promise<{ release: () => Float32Array }> {
  await capture.begin();
  return { release: () => capture.end() };
}
