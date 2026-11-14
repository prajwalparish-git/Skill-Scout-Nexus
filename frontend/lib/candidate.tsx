"use client";

// The signed-in student, shared by every page. The session lives in an HttpOnly cookie that only
// the API reads; this asks /api/auth/me who it belongs to.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { SIGNED_OUT, get, post, type AuthMode, type Student } from "./api";

type Ctx = {
  candidate: Student | null;
  /** How this install signs in (local: one student, password only). */
  mode: AuthMode;
  /** Signed in to the operations view. */
  ops: boolean;
  /** True until /api/auth/me has answered once. */
  loading: boolean;
  error: string | null;
  reload: () => void;
  setCandidate: (s: Student | null) => void;
  signOut: () => Promise<void>;
};

const ONLINE: AuthMode = { local: false, signup_open: true };

const CandidateContext = createContext<Ctx>({
  candidate: null,
  mode: ONLINE,
  ops: false,
  loading: true,
  error: null,
  reload: () => {},
  setCandidate: () => {},
  signOut: async () => {},
});

export function CandidateProvider({ children }: { children: React.ReactNode }) {
  const [candidate, setCandidate] = useState<Student | null>(null);
  const [mode, setMode] = useState<AuthMode>(ONLINE);
  const [ops, setOps] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    get<{ student: Student | null; mode: AuthMode; ops: boolean }>("/api/auth/me")
      .then((r) => {
        setCandidate(r.student);
        setMode(r.mode ?? ONLINE);
        setOps(Boolean(r.ops));
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(reload, [reload]);

  // Any call answered 401 means the session ended (expired, or signed out in another tab).
  useEffect(() => {
    const onSignedOut = () => setCandidate(null);
    window.addEventListener(SIGNED_OUT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT, onSignedOut);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await post("/api/auth/logout", {});
    } finally {
      setCandidate(null);
      setOps(false);
    }
  }, []);

  return (
    <CandidateContext.Provider value={{ candidate, mode, ops, loading, error, reload, setCandidate, signOut }}>
      {children}
    </CandidateContext.Provider>
  );
}

export const useCandidate = () => useContext(CandidateContext);
