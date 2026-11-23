// Microphone capture for the hands-free interview: the mic itself, raw capture resampled to
// 16 kHz mono, and WAV encoding (16-bit), the one format the server accepts. A 120 s answer is
// about 3.8 MB.

export const RATE = 16_000;

export type MicChoice = { stream: MediaStream } | { stream: null; reason: "microphone denied" | "microphone unavailable" };

/** The microphone, or why not. A permission prompt left unanswered must not hold the page:
 * after `waitMs` the interview goes ahead with typed answers (a stream granted later is closed). */
export async function openMic(waitMs = 10_000): Promise<MicChoice> {
  if (!navigator.mediaDevices?.getUserMedia) return { stream: null, reason: "microphone unavailable" };
  const asked = navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    video: false,
  });
  let late = false;
  try {
    const stream = await Promise.race([
      asked,
      new Promise<null>((resolve) => setTimeout(() => resolve(null), waitMs)),
    ]);
    if (stream) return { stream };
    late = true;
    void asked.then((s) => s.getTracks().forEach((t) => t.stop())).catch(() => undefined);
    return { stream: null, reason: "microphone unavailable" };
  } catch (e) {
    if (late) return { stream: null, reason: "microphone unavailable" };
    return { stream: null, reason: (e as DOMException).name === "NotAllowedError" ? "microphone denied" : "microphone unavailable" };
  }
}

export function concat(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

/** Linear resampling to 16 kHz (the browser's own rate is usually 44.1 or 48 kHz). */
export function resample(samples: Float32Array, from: number): Float32Array {
  if (from === RATE) return samples;
  const ratio = from / RATE;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const x = i * ratio;
    const j = Math.floor(x);
    const t = x - j;
    out[i] = (samples[j] ?? 0) * (1 - t) + (samples[j + 1] ?? samples[j] ?? 0) * t;
  }
  return out;
}

/** 16 kHz mono 16-bit PCM WAV. */
export function encodeWav(samples: Float32Array, rate = RATE): Blob {
  const data = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (at: number, s: string) => [...s].forEach((ch, i) => data.setUint8(at + i, ch.charCodeAt(0)));
  text(0, "RIFF");
  data.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  data.setUint32(16, 16, true);
  data.setUint16(20, 1, true); // PCM
  data.setUint16(22, 1, true); // mono
  data.setUint32(24, rate, true);
  data.setUint32(28, rate * 2, true);
  data.setUint16(32, 2, true);
  data.setUint16(34, 16, true);
  text(36, "data");
  data.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    data.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([data.buffer], { type: "audio/wav" });
}

/** Raw capture from the mic: every buffer to `onBuffer` (with its loudness), and the samples
 * kept since `begin()`. One per page; the AudioContext is resumed on demand. */
export class Capture {
  private ctx: AudioContext;
  private node: ScriptProcessorNode;
  private source: MediaStreamAudioSourceNode;
  private chunks: Float32Array[] = [];
  private keeping = false;
  onBuffer: ((rms: number) => void) | null = null;

  constructor(stream: MediaStream) {
    this.ctx = new AudioContext();
    this.source = this.ctx.createMediaStreamSource(stream);
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (e) => {
      const out = e.outputBuffer.getChannelData(0);
      out.fill(0);
      const buf = e.inputBuffer.getChannelData(0);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      if (this.keeping) this.chunks.push(new Float32Array(buf));
      this.onBuffer?.(Math.sqrt(sum / buf.length));
    };
    this.source.connect(this.node);
    this.node.connect(this.ctx.destination);
  }

  get bufferSeconds(): number {
    return 4096 / this.ctx.sampleRate;
  }

  async begin(): Promise<void> {
    if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => undefined);
    this.chunks = [];
    this.keeping = true;
  }

  /** Drop all but the last `seconds` kept so far (the lead-in before speech). */
  trim(seconds: number): void {
    const keep = Math.ceil(seconds / this.bufferSeconds);
    if (this.chunks.length > keep) this.chunks = this.chunks.slice(-keep);
  }

  /** Stop keeping; the kept samples at 16 kHz. */
  end(): Float32Array {
    this.keeping = false;
    const out = resample(concat(this.chunks), this.ctx.sampleRate);
    this.chunks = [];
    return out;
  }

  async resume(): Promise<void> {
    if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => undefined);
  }

  close(): void {
    this.node.disconnect();
    this.source.disconnect();
    void this.ctx.close().catch(() => undefined);
  }
}
