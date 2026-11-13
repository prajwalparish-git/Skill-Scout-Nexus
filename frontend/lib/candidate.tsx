"use client";

// The selected candidate, shared by every page and remembered in this browser.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get, type Student } from "./api";

const KEY = "ssn.candidate";

type Ctx = {
  students: Student[];
  candidate: Student | null;
  choose: (id: string | null) => void;
  reload: () => void;
  error: string | null;
  /** True until the stored candidate has been resolved against /api/students at least once. */
  loading: boolean;
};

const CandidateContext = createContext<Ctx>({
  students: [],
  candidate: null,
  choose: () => {},
  reload: () => {},
  error: null,
  loading: true,
});

function readStored(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function CandidateProvider({ children }: { children: React.ReactNode }) {
  const [students, setStudents] = useState<Student[]>([]);
  const [id, setId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    get<Student[]>("/api/students")
      .then((list) => {
        setStudents(list);
        setError(null);
        const stored = readStored();
        setId((cur) => cur ?? (list.some((s) => s.id === stored) ? stored : list[0]?.id ?? null));
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(reload, [reload]);

  const choose = (next: string | null) => {
    setId(next);
    try {
      if (next) localStorage.setItem(KEY, next);
      else localStorage.removeItem(KEY);
    } catch {
      /* storage blocked: the choice lasts for this visit */
    }
  };

  const candidate = students.find((s) => s.id === id) ?? null;
  return (
    <CandidateContext.Provider value={{ students, candidate, choose, reload, error, loading }}>
      {children}
    </CandidateContext.Provider>
  );
}

export const useCandidate = () => useContext(CandidateContext);
