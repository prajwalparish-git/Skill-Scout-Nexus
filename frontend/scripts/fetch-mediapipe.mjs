// Self-hosts MediaPipe for the proctoring camera checks (lib/proctor/camera.ts): copies the WASM
// runtime from node_modules and downloads the two pinned models into public/mediapipe/ (git-
// ignored), each checked against its SHA-256. Runs after `npm install` and before `npm run build`.
//
// It NEVER fails the install or the build: offline, a blocked network, a timeout or a wrong
// checksum only print a warning and exit 0. The camera checks are then disabled (the page notes
// it); the tab, fullscreen and copy-lock checks still work.
//
// MEDIAPIPE_SKIP=1 skips the download; MEDIAPIPE_MODEL_BASE and MEDIAPIPE_OUT exist for checks.

import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, "..");
const OUT = process.env.MEDIAPIPE_OUT || join(FRONTEND, "public", "mediapipe");
const BASE = (process.env.MEDIAPIPE_MODEL_BASE || "https://storage.googleapis.com/mediapipe-models").replace(/\/$/, "");
const TIMEOUT_MS = 30_000;

// Pinned: a versioned path and its SHA-256 (Apache-2.0, Google MediaPipe).
const MODELS = [
  {
    file: "face_landmarker.task",
    path: "face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    sha256: "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
  },
  {
    file: "efficientdet_lite0.tflite",
    path: "object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite",
    sha256: "0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb",
  },
];

const WARNING =
  "MediaPipe models not available: camera checks will be disabled; tab, fullscreen and copy-lock checks still work.";

const sha256 = (data) => createHash("sha256").update(data).digest("hex");

async function verified(path, expected) {
  try {
    return sha256(await readFile(path)) === expected;
  } catch {
    return false;
  }
}

async function copyWasm() {
  const from = join(FRONTEND, "node_modules", "@mediapipe", "tasks-vision", "wasm");
  const to = join(OUT, "wasm");
  await mkdir(to, { recursive: true });
  for (const name of await readdir(from)) await copyFile(join(from, name), join(to, name));
}

async function fetchModel(m) {
  const target = join(OUT, "models", m.file);
  if (await verified(target, m.sha256)) return true; // already here and intact
  await mkdir(dirname(target), { recursive: true });
  const res = await fetch(`${BASE}/${m.path}`, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!res.ok) throw new Error(`${m.file}: HTTP ${res.status}`);
  const data = Buffer.from(await res.arrayBuffer());
  if (sha256(data) !== m.sha256) throw new Error(`${m.file}: checksum mismatch`);
  const part = `${target}.part`; // moved into place only once verified: never a partial file
  await writeFile(part, data);
  await rename(part, target);
  return true;
}

async function main() {
  const manifest = { ok: false, wasm: false, models: {}, note: "" };
  try {
    await copyWasm();
    manifest.wasm = true;
  } catch (e) {
    manifest.note = `WASM runtime not copied (${e.message}).`;
  }
  if (process.env.MEDIAPIPE_SKIP === "1") {
    manifest.note ||= "Skipped (MEDIAPIPE_SKIP=1).";
  } else {
    for (const m of MODELS) {
      try {
        manifest.models[m.file] = await fetchModel(m);
      } catch (e) {
        manifest.models[m.file] = false;
        const why = e.name === "TimeoutError" ? "timeout" : e.cause?.code || e.message;
        manifest.note ||= `Download failed (${why}).`;
        await rm(join(OUT, "models", `${m.file}.part`), { force: true });
      }
    }
  }
  manifest.ok = manifest.wasm && MODELS.every((m) => manifest.models[m.file] === true);
  await mkdir(OUT, { recursive: true });
  await writeFile(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
  if (manifest.ok) console.log("MediaPipe ready for the proctoring camera checks.");
  else console.warn(`WARNING: ${WARNING} ${manifest.note}`.trim());
}

main()
  .catch((e) => console.warn(`WARNING: ${WARNING} (${e.message})`))
  .finally(() => process.exit(0)); // never fails the install or the build
