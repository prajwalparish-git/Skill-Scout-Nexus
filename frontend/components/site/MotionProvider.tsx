"use client";

// Site-wide motion preferences. With "reduce motion" on, every animation motion would run
// jumps straight to its end state (no springs, fades or slides), and transform and layout
// animations are skipped as well. CSS animations are handled by the media query in globals.css.
import { useEffect } from "react";
import { MotionConfig, MotionGlobalConfig } from "motion/react";

export function MotionProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      MotionGlobalConfig.skipAnimations = query.matches;
    };
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
