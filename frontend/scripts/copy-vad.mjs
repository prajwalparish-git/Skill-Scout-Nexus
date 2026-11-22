// Self-hosts voice-activity detection for the hands-free interview (lib/handsfree/listen.ts):
// copies the Silero VAD model and audio worklet from @ricky0123/vad-web and the ONNX Runtime
// WASM from onnxruntime-web into public/vad/ (git-ignored). Everything ships inside those npm
// packages, so nothing is downloaded. Runs after `npm install` and before `npm run build`.
//
// It NEVER fails the install or the build: a missing file only prints a warning and leaves a
// manifest that says so; the page then detects the end of an answer by loudness instead, and
// push-to-talk and typing still work.
//
// VAD_OUT exists for checks (another output folder); VAD_FROM points at other node_modules.

import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, "..");
const MODULES = process.env.VAD_FROM || join(FRONTEND, "node_modules");
const OUT = process.env.VAD_OUT || join(FRONTEND, "public", "vad");

const FILES = [
  ["@ricky0123/vad-web/dist/silero_vad_v5.onnx", "silero_vad_v5.onnx"],
  ["@ricky0123/vad-web/dist/vad.worklet.bundle.min.js", "vad.worklet.bundle.min.js"],
  ["onnxruntime-web/dist/ort-wasm-simd-threaded.wasm", "ort-wasm-simd-threaded.wasm"],
  ["onnxruntime-web/dist/ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.mjs"],
];

const WARNING =
  "Voice detection files not available: the hands-free interview will detect the end of an answer by loudness; push-to-talk and typing still work.";

async function main() {
  const manifest = { ok: false, files: {}, note: "" };
  await mkdir(OUT, { recursive: true });
  for (const [from, to] of FILES) {
    try {
      await copyFile(join(MODULES, from), join(OUT, to));
      manifest.files[to] = true;
    } catch (e) {
      manifest.files[to] = false;
      manifest.note ||= `${to} not copied (${e.code || e.message}).`;
    }
  }
  manifest.ok = Object.values(manifest.files).every(Boolean);
  await writeFile(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
  if (manifest.ok) console.log("Voice detection ready for the hands-free interview.");
  else console.warn(`WARNING: ${WARNING} ${manifest.note}`.trim());
}

main()
  .catch((e) => console.warn(`WARNING: ${WARNING} (${e.message})`))
  .finally(() => process.exit(0)); // never fails the install or the build
