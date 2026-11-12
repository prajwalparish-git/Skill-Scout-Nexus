import type { Config } from "tailwindcss";

// Colours are CSS variables (app/globals.css) so light and dark follow the system setting;
// the values mirror piq/config.py PALETTE and SEMANTIC_COLORS.
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        surface: v("surface"),
        ink: v("ink"),
        muted: v("muted"),
        line: v("line"),
        hair: v("hair"),
        primary: v("primary"),
        "primary-ink": v("primary-ink"),
        focus: v("focus"),
        ok: v("ok"),
        warn: v("warn"),
        bad: v("bad"),
        info: v("info"),
      },
      borderRadius: { card: "0.75rem" },
      // Faces come from next/font/local in app/layout.tsx.
      fontFamily: {
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
