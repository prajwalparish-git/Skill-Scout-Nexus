import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */

// Where the API runs. The browser only ever calls this site's /api/*; the server forwards it here.
// NEXT_PUBLIC_API_URL is the older name, still read so an existing deploy keeps working.
const API_ORIGIN = process.env.API_ORIGIN ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // This folder is the project root: a lockfile higher up (a home folder's stray
  // package-lock.json) must not be taken for it.
  turbopack: { root: dirname(fileURLToPath(import.meta.url)) },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN.replace(/\/$/, "")}/api/:path*` }];
  },
};

export default nextConfig;
