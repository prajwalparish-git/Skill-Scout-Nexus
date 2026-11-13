"use client";

// Single-series charts in plain SVG: one hue (the primary teal), thin marks, a recessive grid,
// a hover tooltip on every mark, and text in ink tokens. Titles state the takeaway; each chart
// is paired with a table elsewhere on its page.
import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";

type Point = { label: string; value: number; note?: string };

function Tooltip({ left, top, children }: { left: string; top: string; children: React.ReactNode }) {
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -mt-2 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-hair bg-bg px-2 py-1 text-xs shadow-sm"
      style={{ left, top }}
    >
      {children}
    </div>
  );
}

/** A line over time (0-max), with markers and a crosshair tooltip. */
export function LineChart({ points, max = 100, unit = "", ariaLabel }: { points: Point[]; max?: number; unit?: string; ariaLabel: string }) {
  const [hover, setHover] = useState<number | null>(null);
  // Draw at the container's real width, so 11px labels stay 11px on a phone.
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(600);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = 200;
  const pad = { l: 36, r: 16, t: 12, b: 28 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const x = (i: number) => pad.l + (points.length < 2 ? iw / 2 : (i * iw) / (points.length - 1));
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const ticks = [0, max / 2, max];
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.value)}`).join(" ");

  return (
    <div ref={box} className="relative" onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={ariaLabel}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="rgb(var(--hair))" strokeWidth={1} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="rgb(var(--muted))">
              {t}
            </text>
          </g>
        ))}
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="rgb(var(--line))" strokeDasharray="3 3" />
        )}
        <motion.path
          d={path}
          fill="none"
          stroke="rgb(var(--primary))"
          strokeWidth={2}
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
        {points.map((p, i) => (
          <g key={i}>
            <motion.circle
              cx={x(i)}
              cy={y(p.value)}
              r={4.5}
              fill="rgb(var(--primary))"
              stroke="rgb(var(--bg))"
              strokeWidth={2}
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.3 + i * 0.05, type: "spring", stiffness: 350, damping: 30 }}
            />
            <rect
              x={x(i) - Math.max(12, iw / Math.max(points.length, 1) / 2)}
              y={pad.t}
              width={Math.max(24, iw / Math.max(points.length, 1))}
              height={ih}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              onKeyDown={(e) => e.key === "Escape" && setHover(null)}
              tabIndex={0}
              role="img"
              aria-label={`${p.label}: ${p.value}${unit}`}
            />
          </g>
        ))}
        {points.length > 0 && (
          <>
            <text x={x(0)} y={H - 8} fontSize={11} textAnchor={points.length < 2 ? "middle" : "start"} fill="rgb(var(--muted))">
              {points[0].label}
            </text>
            {points.length > 1 && (
              <text x={x(points.length - 1)} y={H - 8} fontSize={11} textAnchor="end" fill="rgb(var(--muted))">
                {points[points.length - 1].label}
              </text>
            )}
          </>
        )}
      </svg>
      {hover !== null && (
        <Tooltip left={`${(x(hover) / W) * 100}%`} top={`${(y(points[hover].value) / H) * 100}%`}>
          <span className="text-muted">{points[hover].label}</span>{" "}
          <span className="font-semibold text-ink">
            {points[hover].value}
            {unit}
          </span>
          {points[hover].note && <div className="text-muted">{points[hover].note}</div>}
        </Tooltip>
      )}
    </div>
  );
}

/** Horizontal bars (0-max) with the value beside each bar and a tooltip on hover. */
export function BarList({ rows, max, unit = "", ariaLabel }: { rows: Point[]; max: number; unit?: string; ariaLabel: string }) {
  const [hover, setHover] = useState<number | null>(null);
  return (
    <ul aria-label={ariaLabel} className="space-y-2">
      {rows.map((r, i) => (
        <li
          key={r.label}
          className="relative grid grid-cols-[minmax(6rem,10rem)_1fr_3.5rem] items-center gap-3 text-sm"
          onMouseEnter={() => setHover(i)}
          onMouseLeave={() => setHover(null)}
        >
          <span className="truncate text-ink" title={r.label}>
            {r.label}
          </span>
          <span className="h-3 rounded-r bg-surface">
            <motion.span
              className="block h-3 rounded-r-[4px] bg-primary"
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(1, (r.value / max) * 100)}%` }}
              transition={{ delay: i * 0.04, type: "spring", stiffness: 350, damping: 30 }}
            />
          </span>
          <span className="text-right tabular-nums text-muted">
            {r.value}
            {unit}
          </span>
          {hover === i && r.note && (
            <div role="tooltip" className="absolute left-1/2 top-0 z-10 -translate-y-full rounded-md border border-hair bg-bg px-2 py-1 text-xs shadow-sm">
              {r.note}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
