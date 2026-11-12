"use client";

// Lenis smooth scrolling for the public pages. Skipped entirely when the visitor prefers
// reduced motion; the native scroll (with section scroll-margins) is used instead.
import { useEffect } from "react";
import Lenis from "lenis";
import "lenis/dist/lenis.css";

let instance: Lenis | null = null;

/** Pause and resume page scrolling (for dialogs); a no-op without Lenis. */
export const pauseScroll = () => instance?.stop();
export const resumeScroll = () => instance?.start();

export function SmoothScroll() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    instance = new Lenis({ autoRaf: true, anchors: { offset: -88 }, lerp: 0.12 });
    return () => {
      instance?.destroy();
      instance = null;
    };
  }, []);
  return null;
}
