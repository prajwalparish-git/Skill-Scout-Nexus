// Typed client for server.py. Every call goes to NEXT_PUBLIC_API_URL (default localhost:8000).

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API}. Is server.py running?`, 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `Request failed (${res.status})`, res.status);
  }
  return res.json() as Promise<T>;
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  return p.toString();
}

/** POST, then read text/event-stream: calls onEvent(event, data) for each event. */
export async function postStream(
  path: string,
  body: unknown,
  onEvent: (event: string, data: any) => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API}. Is server.py running?`, 0);
  }
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(err.detail ?? `Request failed (${res.status})`, res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
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
};
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
