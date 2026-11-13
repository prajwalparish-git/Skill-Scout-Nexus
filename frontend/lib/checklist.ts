"use client";

// A personal "marked as done" set for library items (books, repos), kept in this browser only.
// Separate from the server-tracked weekly plan: the library is a reference catalogue, not an
// assigned list, so there is no meaningful "total" to compute a percentage against.
import { useCallback, useEffect, useState } from "react";

function readSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

export function useChecklist(key: string) {
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setChecked(readSet(key));
    setReady(true);
  }, [key]);

  const toggle = useCallback(
    (id: string) => {
      setChecked((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        try {
          localStorage.setItem(key, JSON.stringify([...next]));
        } catch {
          /* storage blocked: the marks last for this visit */
        }
        return next;
      });
    },
    [key],
  );

  return { checked, toggle, ready };
}
