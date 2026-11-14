// Typed client for server.py. Calls go to this site's own /api/*, which next.config.mjs proxies to
// the API (API_ORIGIN): the session cookie is then first-party, with no CORS, here and when deployed.

export const API = "";

/** Fired when a call comes back 401: the session ended, so the app drops the signed-in student. */
export const SIGNED_OUT = "ssn:signed-out";
const signedOut = () => {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SIGNED_OUT));
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

const TIMEOUT_MS = 30_000;

/** The API's `detail` as one sentence: a string as is, a validation list as its first message. */
function detailOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") return detail[0].msg;
  return `Request failed (${status})`;
}

/** The error a failed (non-2xx) response carries; a 401 also signs the app out. */
export async function failure(res: Response): Promise<ApiError> {
  if (res.status === 401) signedOut();
  const body = await res.json().catch(() => null);
  return new ApiError(detailOf(body, res.status), res.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Aborts a hung request after TIMEOUT_MS; the timer is cleared once the reply has been read.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    let res: Response;
    try {
      res = await fetch(`${API}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        throw new ApiError("The server took too long to respond.", 0);
      }
      throw new ApiError("Cannot reach the server. Is the API running?", 0);
    }
    if (!res.ok) throw await failure(res);
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError("The server sent a reply this page could not read.", res.status);
    }
  } finally {
    clearTimeout(timer);
  }
}

/** Hands `blob` to the browser as a download, named from Content-Disposition when it has one. */
export function saveFile(blob: Blob, disposition: string | null, fallback: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = /filename="([^"]+)"/.exec(disposition ?? "")?.[1] ?? fallback;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000); // revoking at once can cancel the download
}

/** GET a file from the API and save it (a calendar, a PDF). */
export async function download(path: string, fallback: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`);
  } catch {
    throw new ApiError("Cannot reach the server. Is the API running?", 0);
  }
  if (!res.ok) throw await failure(res);
  saveFile(await res.blob(), res.headers.get("content-disposition"), fallback);
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  return p.toString();
}

/**
 * POST, then read text/event-stream: calls onEvent(event, data) for each event.
 * Aborts on inactivity (no bytes for TIMEOUT_MS), not on total duration: a multi-step
 * critic pipeline can legitimately run past 30s as long as it keeps emitting steps.
 * `cancel` (e.g. the page unmounting) stops the stream quietly: the promise resolves.
 */
export async function postStream(
  path: string,
  body: unknown,
  onEvent: (event: string, data: any) => void,
  cancel?: AbortSignal,
): Promise<void> {
  const controller = new AbortController();
  if (cancel?.aborted) return;
  const onCancel = () => controller.abort();
  cancel?.addEventListener("abort", onCancel, { once: true });
  let idle = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const resetIdle = () => {
    clearTimeout(idle);
    idle = setTimeout(() => controller.abort(), TIMEOUT_MS);
  };
  const cleanup = () => {
    clearTimeout(idle);
    cancel?.removeEventListener("abort", onCancel);
  };

  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e) {
    cleanup();
    if (cancel?.aborted) return;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError("The server took too long to respond.", 0);
    }
    throw new ApiError("Cannot reach the server. Is the API running?", 0);
  }
  if (!res.ok || !res.body) {
    cleanup();
    throw await failure(res);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      resetIdle();
      buffer += decoder.decode(value, { stream: true });
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) onEvent(event, JSON.parse(data));
      }
    }
  } catch (e) {
    if (cancel?.aborted) return;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError("The server stopped responding.", 0);
    }
    throw e;
  } finally {
    cleanup();
  }
}

// --- shapes returned by server.py ----------------------------------------------------------

export type Project = { title: string; tech: string; bullets: string[] };
export type Role = {
  name: string;
  category: string;
  description: string;
  recommended_degree: string;
  ats_keywords: string[];
  sample_projects: Project[];
};
export type Domain = {
  id: string;
  name: string;
  icon: string;
  description: string;
  topics: { name: string; bank: Record<string, number> }[];
  roles: Role[];
};
export type Catalog = {
  domains: Domain[];
  degrees: { code: string; name: string }[];
  statuses: string[];
};
export type Student = {
  id: string;
  name: string;
  username: string;
  target_role: string;
  readiness_score: number;
  /** An organization's student on the temporary password they were sent. */
  must_change_password: boolean;
};
/** How this install signs in: local = one student, password only (no email). */
export type AuthMode = { local: boolean; signup_open: boolean };
/** One of the student's signed-in devices. */
export type DeviceSession = {
  id: string;
  browser: string;
  os: string;
  ip: string;
  location: string;
  created_at: string;
  last_seen: number | null;
  current: boolean;
};
export type Prefs = { preload: boolean; login_alerts: boolean };
export type SettingsPayload = { prefs: Prefs; preload_allowed: boolean };
export type RoleFit = {
  role: string;
  domain_id: string;
  domain_name: string;
  eligible_now: boolean;
  via: string;
};
export type QuizQuestion = { id: string; text: string; options: string[] };
export type Quiz = { topic: string; difficulty: string; questions: QuizQuestion[] };
export type Graded = {
  score_pct: number;
  correct: number;
  total: number;
  next_difficulty: string;
  review: { id: string; chosen: number | null; correct_index: number; is_correct: boolean; explanation: string }[];
  weakness: Record<string, number> | null;
};
export type DayPlan = {
  day: number;
  topic: string;
  subtopics: string[];
  duration_min: number;
  practice_goal: string;
};
export type PlanPayload = {
  plan: { week_no: number; rationale: string; days: DayPlan[] } | null;
  done: number[];
  weakness: Record<string, number>;
  scores: Record<string, number>;
  next_week: number;
  minutes_by_week: { week: number; minutes: Record<string, number> }[];
};
export type Mastery = { topic: string; scores: number[]; weakness: number; trend: string };
export type DashboardPayload = {
  profile: {
    name: string;
    target_role: string;
    readiness_score: number;
    matched_skills: string[];
    missing_skills: string[];
    resume_feedback: string[];
  };
  readiness: { created_at: string; readiness_score: number }[];
  quizzes_taken: number;
  answered: { correct: number; total: number };
  streak: { current: number; longest: number };
  mastery: Mastery[];
  quiz_history: { attempted_at: string; topic: string; difficulty: string; score_pct: number }[];
  sessions: { started: string; interview_type: string; avg_overall: number }[];
};
export type Track = { name: string; focus: string; group: string };
export type Evaluation = {
  relevance: number;
  depth: number;
  structure: number;
  clarity: number;
  strengths: string[];
  improvements: string[];
  model_answer: string;
};
export type Session = {
  session_id: string;
  interview_type: string;
  past: unknown[];
  history: { question: string; answer: string; evaluation: Evaluation }[];
  current: { question: string; intent: string; is_followup: boolean; is_final: boolean } | null;
  done: boolean;
};
export type TurnResult = {
  session: Session;
  average: number | null;
  summary?: { averages: Record<string, number>; strongest: string; weakest: string; tips: Record<string, string> };
};
export type Ats = {
  score: number;
  matched_keywords: string[];
  missing_keywords: string[];
  action_verbs_count: number;
  has_metrics: boolean;
  suggestions: string[];
  degree_fit: string;
};
