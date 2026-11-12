import type { KeyboardEvent } from "react";

/** Arrow, Home and End keys for a WAI-ARIA tab list: moves selection and focus to the next tab. */
export function tabKeys<T extends string>(ids: readonly T[], active: T, select: (id: T) => void) {
  return (e: KeyboardEvent<HTMLElement>) => {
    const i = ids.indexOf(active);
    let n = i;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % ids.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + ids.length) % ids.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = ids.length - 1;
    else return;
    e.preventDefault();
    const tabs = e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]');
    select(ids[n]);
    tabs[n]?.focus();
  };
}
