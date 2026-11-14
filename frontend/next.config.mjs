/** @type {import('next').NextConfig} */

// Where the API runs. The browser only ever calls this site's /api/*; the server forwards it here.
const API_ORIGIN = process.env.API_ORIGIN ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // No ESLint dependency: `next build` type-checks; ruff and pytest guard the Python side.
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN.replace(/\/$/, "")}/api/:path*` }];
  },
};

export default nextConfig;
