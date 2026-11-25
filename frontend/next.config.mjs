import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

/** @type {import('next').NextConfig} */

// Where the API runs. In dev mode with Next.js dev server, rewrites forward /api/* here.
// In production single-port mode, server.py serves frontend/out directly on http://localhost:8000.
const API_ORIGIN = process.env.API_ORIGIN ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function nextConfig(phase) {
  const isDev = phase === PHASE_DEVELOPMENT_SERVER;

  /** @type {import('next').NextConfig} */
  const config = {
    reactStrictMode: true,
    turbopack: { root: dirname(fileURLToPath(import.meta.url)) },
    images: { unoptimized: true },
    experimental: {
      turbopackPluginRuntimeStrategy: "forceWorkerThreads",
      cpus: 1,
    },
  };

  if (isDev) {
    config.rewrites = async () => [
      { source: "/api/:path*", destination: `${API_ORIGIN.replace(/\/$/, "")}/api/:path*` },
    ];
  } else {
    // Static export mode for unified single-port serving by server.py
    config.output = "export";
    config.trailingSlash = true;
  }

  return config;
}
