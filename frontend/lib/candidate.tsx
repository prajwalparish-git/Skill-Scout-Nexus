"use client";

// The signed-in student, shared by every page. The session lives in an HttpOnly cookie that only
// the API reads; this asks /api/auth/me who it belongs to.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { SIGNED_OUT, get, post, type AuthMode, type Student } from "./api";

type Me = { student: Student | null; mode: AuthMode; ops: boolean; local_ai: { model: string } | null };

type Ctx = {
  candidate: Student | null;
  /** The model name when the student's latest AI answer came from their own local model. */
  localModel: string | null;
  /** Re-ask only which AI answered last (cheap; leaves the student object alone). */
  refreshLocalModel: () => void;
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
  localModel: null,
  refreshLocalModel: () => {},
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
  const [localModel, setLocalModel] = useState<string | null>(null);

  const reload = useCallback(() => {
    get<Me>("/api/auth/me")
      .then((r) => {
        setCandidate(r.student);
        setMode(r.mode ?? ONLINE);
        setOps(Boolean(r.ops));
        setLocalModel(r.local_ai?.model ?? null);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const refreshLocalModel = useCallback(() => {
    get<Me>("/api/auth/me").then(
      (r) => setLocalModel(r.local_ai?.model ?? null),
      () => {}, // the indicator is a hint: a failed check leaves it as it was
    );
  }, []);

  useEffect(reload, [reload]);

  // Any call answered 401 means the session ended (expired, or signed out in another tab).
  useEffect(() => {
    const onSignedOut = () => {
      setCandidate(null);
      setLocalModel(null);
    };
    window.addEventListener(SIGNED_OUT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT, onSignedOut);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await post("/api/auth/logout", {});
    } finally {
      setCandidate(null);
      setOps(false);
      setLocalModel(null);
    }
  }, []);

  return (
    <CandidateContext.Provider
      value={{ candidate, localModel, refreshLocalModel, mode, ops, loading, error, reload, setCandidate, signOut }}
    >
      {children}
    </CandidateContext.Provider>
  );
}

export const useCandidate = () => useContext(CandidateContext);
