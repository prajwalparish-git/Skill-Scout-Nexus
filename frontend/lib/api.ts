// Typed client for server.py. Calls go to this site's own /api/*: in production server.py serves the
// exported web app itself, and `npm run dev` proxies /api/* to it (next.config.mjs, API_ORIGIN), so the
// session cookie is first-party with no CORS.

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
      // A FormData body sets its own multipart Content-Type (with the boundary); JSON otherwise.
      const json: Record<string, string> = init?.body instanceof FormData ? {} : { "Content-Type": "application/json" };
      res = await fetch(`${API}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { ...json, ...(init?.headers ?? {}) },
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
export const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = <T>(path: string) =>
  request<T>(path, { method: "DELETE" });
/** POST a multipart form (a file upload). */
export const upload = <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form });

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
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
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
        if (data) {
          try {
            onEvent(event, JSON.parse(data));
          } catch {
            // Safely ignore non-JSON or HTML proxy error chunks
          }
        }
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

export const streamEvents = postStream;

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
  /** Belongs to an organization (its posts may name the college, once the batch is big enough). */
  in_org?: boolean;
  /** "contributor": a placed student, alumnus or professional who shares questions only. */
  account_kind?: "student" | "contributor";
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
/** A student's own model on their laptop (Settings > My local model). */
export type LocalAIProvider = "ollama" | "lmstudio";
export type LocalAIConfig = { provider: LocalAIProvider; base_url: string; model: string; preferred: boolean };
export type LocalAIPayload = {
  /** false on a server that refuses local models (the deployed site): show `explainer` instead. */
  allowed: boolean;
  explainer: string;
  config: LocalAIConfig | null;
  /** The model name when the student's latest AI answer came from it. */
  using_local: string | null;
  providers: { id: LocalAIProvider; name: string }[];
  defaults: Record<LocalAIProvider, string>;
};
export type SettingsPayload = { prefs: Prefs; preload_allowed: boolean };
export type RoleFit = {
  role: string;
  domain_id: string;
  domain_name: string;
  eligible_now: boolean;
  via: string;
};
export type QuizQuestion = {
  id: string;
  text: string;
  options: string[];
  /** The question's own difficulty (a quiz at your level may borrow from the nearest one). */
  difficulty?: string;
  /** Brought back because you missed it, or one like it, before. */
  review?: boolean;
};
export type Quiz = {
  topic: string;
  difficulty: string;
  questions: QuizQuestion[];
  /** The student's level on the topic (null for a guest). */
  level?: string | null;
  /** Asked at the student's level (no difficulty was chosen). */
  adaptive?: boolean;
  /** A signed-in student's quiz session: options are shuffled for it, and the submit names it. */
  quiz_session?: string | null;
};
export type Graded = {
  score_pct: number;
  correct: number;
  total: number;
  /** A student's level for the next quiz on the topic (a guest: the suggestion). */
  next_difficulty: string;
  level_before?: string | null;
  level_after?: string | null;
  level_changed?: boolean;
  review: {
    id: string;
    chosen: number | null;
    correct_index: number;
    is_correct: boolean;
    explanation: string;
    /** An open-bank question's source and licence, e.g. "AQuA-RAT · Apache-2.0 · modified". */
    credit?: string;
  }[];
  weakness: Record<string, number> | null;
  /** Set when the quiz was proctored. */
  proctoring?: ProctorOutcome | null;
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
  /** Topic -> the level its next quiz starts at (absent: medium). */
  levels?: Record<string, string>;
};
/** A certificate PDF the student uploaded; the file is at /api/certificates/{student}/{id}/file. */
export type Certificate = {
  id: number;
  title: string;
  issuer: string;
  issue_date: string | null;
  filename: string;
  size_bytes: number;
  uploaded_at: string;
  /** A copy is in the student's Google Drive. */
  in_drive: boolean;
};
/** GET /api/drive: whether the server offers Google Drive and whether this student connected it. */
export type DriveStatus = { enabled: boolean; connected: boolean; folder_link: string };
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
  /** Company practice: questions students reported, asked first and word for word. */
  script?: string[];
};

// --- company interview experiences (server_companies.py) ------------------------------------

/** GET /api/question-sources: where questions come from, their licences and what we changed. */
export type QuestionSource = {
  key: string;
  name: string;
  homepage: string;
  commit: string;
  licence_id: string;
  licence_name: string;
  licence_url: string;
  attribution: string;
  modifications: string[];
  multiple_choice: number;
  interview: number;
};
export type QuestionSources = { sources: QuestionSource[]; general_practice_note: string; licences_file: string };

export const ROUNDS: Record<string, string> = {
  aptitude: "Aptitude",
  technical: "Technical",
  coding: "Coding",
  hr: "HR",
  group_discussion: "Group discussion",
};
export type CompanySummary = {
  slug: string;
  name: string;
  careers_url: string;
  posts: number;
  questions: number;
  rounds: Record<string, { posts: number; questions: number }>;
  /** Approved interview-process reports. */
  processes: number;
  /** Open-bank questions its page offers for practice (general practice, not asked there). */
  practice_questions: number;
  /** "12 reported questions · 1,240 practice questions" (or "… · no reports yet"). */
  counts_line: string;
};
export type ReportedQuestion = {
  kind: "open" | "mcq";
  text: string;
  options?: string[];
  correct_index?: number;
  explanation?: string;
};
/** An approved post: who shared it is only ever a label ("a student, 2026"). */
export type ExperiencePost = {
  id: number;
  label: string;
  role: string;
  round: string;
  interview_month: string;
  tip: string;
  questions: ReportedQuestion[];
};
/** A test pattern, shown only when taken from the company's own page (with its link). */
export type TestPattern = { sections: string[]; source_url: string; checked: string };
/** General practice by round from the open question bank: never claimed as the company's. */
export type OpenPractice = {
  label: string;
  note: string;
  rounds: { aptitude: number; technical: number; hr: number };
  technical_interview: number;
  hr_questions: { text: string; model_answer: string; credit: string }[];
};
export type CompanyDetail = {
  slug: string;
  name: string;
  careers_url: string;
  test_pattern: TestPattern | null;
  open_practice: OpenPractice;
  rounds: Record<string, { posts: number; questions: number }>;
  /** Students have reported questions or an interview process for this company. */
  reported: boolean;
  posts: ExperiencePost[];
  process: ProcessSummary;
};

// --- interview process reports ----------------------------------------------------------------

export const PROCESS_ROUND_TYPES: Record<string, string> = {
  online_test: "Online test",
  aptitude: "Aptitude",
  coding: "Coding",
  technical: "Technical",
  managerial: "Managerial",
  hr: "HR",
  group_discussion: "Group discussion",
};
export const PROCESS_RESULTS: Record<string, string> = { selected: "Selected", not_selected: "Not selected", waiting: "Waiting" };
export const DIFFICULTY_LABELS: Record<string, string> = { easy: "Easy", medium: "Medium", hard: "Hard" };
export type ProcessRound = { type: string; minutes: number | null; difficulty: string; label?: string };
export type ReportedProcess = { rounds: ProcessRound[]; result: string; result_label: string; summary: string };
/** "Interview process (from N reports)": empty ({reports: 0}) until one is approved. */
export type ProcessSummary = {
  reports: number;
  common_order?: string[];
  common_order_reports?: number;
  average_rounds?: number;
  difficulty?: Record<string, number>;
  difficulty_by_round?: Record<string, Record<string, number>>;
  results?: Record<string, number>;
  summaries?: (ReportedProcess & { id: number; label: string; role: string; interview_month: string; tip: string })[];
};
export type PracticeQuiz = {
  company: string;
  round: string;
  /** "reported": students' questions; "open": the open question bank (general practice);
   * "ai": AI practice, never presented as reported. */
  source: "reported" | "ai" | "open";
  label: string;
  notes: string[];
  questions: { id: string; text: string; options: string[] }[];
};
export type PracticeResult = {
  correct: number;
  total: number;
  score_pct: number;
  source: string;
  review: {
    id: string;
    chosen: number | null;
    correct_index: number;
    is_correct: boolean;
    explanation: string;
    /** An open-bank question's source and licence, e.g. "AQuA-RAT · Apache-2.0 · modified". */
    credit?: string;
  }[];
};
export type MyPost = {
  id: number;
  company: string;
  role: string;
  round: string;
  interview_month: string;
  status: "pending" | "approved" | "rejected" | "hidden";
  reject_reason: string;
  questions: number;
  /** The post reports an interview process. */
  process: boolean;
};
export type ModerationPost = {
  id: number;
  company: string;
  known_company: boolean;
  role: string;
  round: string;
  interview_month: string;
  tip: string;
  status: string;
  flags: string[];
  label: string;
  questions: ReportedQuestion[];
  process: ReportedProcess | null;
};
export type TurnResult = {
  session: Session;
  average: number | null;
  summary?: { averages: Record<string, number>; strongest: string; weakest: string; tips: Record<string, string> };
  /** Set on the last turn of a proctored interview (or when it was breached). */
  proctoring?: ProctorOutcome | null;
  /** Hands-free: the next question spoken (a clip from the server, or the browser's voice). */
  speech?: QuestionSpeech;
  /** Hands-free: how the questions were answered, on the last turn. */
  handsfree?: HandsfreeSummary;
};
export type QuestionSpeech = { url?: string; mime?: string; browser?: boolean; text: string; source: string };
/** The same rules for every student (piq/config.py), frozen onto each run. */
export type HandsfreeRules = {
  think_s: number;
  max_answer_s: number;
  silence_s: number;
  retries: number;
  review_s: number;
  typed_max_s: number;
  no_speech_s: number;
  sample_rate: number;
};
export type HandsfreeReason =
  | "microphone unavailable"
  | "microphone denied"
  | "voice detection unavailable"
  | "transcription unavailable"
  | "no speech detected"
  | "chose to type";
export type Transcribed = { text: string; source: string; retries_left: number; fallback: string; duration_s: number };
export type HandsfreeSummary = { voice: number; push_to_talk: number; typed: number; reasons: string[] };
/** GET /api/proctor/policy: practice (proctoring optional), required, or required in Safe Exam Browser. */
export type ProctorPolicy = {
  mode: "practice" | "required" | "seb";
  required: boolean;
  seb: boolean;
  consent_text: string;
  max_strikes: number;
  heartbeat_s: number;
  clear: string[];
};
/** The server's count after an event batch: it decides severity and strikes. */
export type ProctorProgress = { strikes: number; breached: boolean; warning: string | null };
export type ProctorOutcome = { attempt_id: string; strikes: number; breached: boolean; flags: string[] };
export type ProctorEvent = {
  kind: string;
  severity: "clear" | "review";
  strike: boolean;
  at_s: number;
  duration_s: number | null;
  /** e.g. "looked away 14s at 03:42" */
  text: string;
};
/** One proctored attempt as the student (and their admin) sees it. */
export type ProctorAttempt = {
  id: string;
  kind: "quiz" | "interview";
  label: string;
  mode: "practice" | "required" | "seb";
  camera: "on" | "unavailable";
  camera_note: string;
  started: string;
  duration_s: number;
  strikes: number;
  breached: boolean;
  finished: boolean;
  clear: ProctorEvent[];
  review: ProctorEvent[];
};
/** A resume layout for a kind of employer (piq/resume_templates.py). */
export type ResumeTemplate = { id: string; name: string; best_for: string; one_page: boolean; fields: string[] };
/** The chosen template's sections, exactly as the PDF lays them out. */
export type ResumeLayout = {
  template: string;
  header: { title: string; name: string; subtitle: string; lines: string[] };
  sections: {
    key: string;
    heading: string;
    text: string;
    lines: string[];
    entries: { title: string; detail: string; bullets: string[] }[];
  }[];
  pages: number;
  one_page: boolean;
  /** Set when a one-page layout runs over (nothing is ever cut). */
  page_note: string;
};
/** A tailoring for the student to review: nothing changes until they accept it. */
export type Tailoring = {
  summary: string;
  /** "experience:0" / "projects:0" -> the entry's bullets in the new order. */
  bullets: Record<string, string[]>;
  changes: string[];
  matched_keywords: string[];
  missing_keywords: string[];
  layout: ResumeLayout;
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

// --- contributed questions (server_contribute.py) -------------------------------------------

export type ContributeOptions = {
  rounds: Record<string, string>;
  topics: Record<string, string[]>;
  licence: string;
  licence_note: string;
};
export type Contribution = {
  id: number;
  kind: "mcq" | "open";
  round: string;
  topic: string;
  difficulty: string;
  text: string;
  options: string[];
  correct_index: number | null;
  explanation: string;
  model_answer: string;
  licence: string;
  status: "pending" | "approved" | "rejected" | "hidden";
  reject_reason?: string;
  flags?: string[];
  created_at: string;
};
export type ContributorProfile = {
  kind: "student" | "contributor";
  company_joined: string;
  credit_opt_in: boolean;
  display_name: string;
  shown_as: string;
  approved: number;
  badge: string;
};
export type Leaderboard = { season: string; since: string; top: { name: string; approved: number }[] };
export type ContributeMe = { profile: ContributorProfile; contributions: Contribution[]; leaderboard: Leaderboard };

// --- project space and project ideas (server_projects.py) --------------------------------------

/** A GitHub repository, metadata only (never README text or code). */
export type InspirationRepo = {
  full_name: string;
  owner: string;
  owner_is_org: boolean;
  /** The company's name when a listed company organization owns it. */
  company: string;
  description: string;
  stars: number;
  language: string;
  topics: string[];
  licence: string;
  url: string;
  pushed_at: string;
};
export type DerivedFrom = { repo: string; takes: string; differs: string; meta: InspirationRepo | null };
export type ProjectIdea = {
  title: string;
  derivation: "combine" | "student_scale" | "indian_use_case" | "missing_feature";
  label: string;
  problem: string;
  why_it_fits: string;
  derived_from: DerivedFrom[];
  stack: string[];
  gap_skills: string[];
  scope_weeks: number;
  milestones: string[];
  stretch_goals: string[];
};
export type IdeaTopic = {
  topic: string;
  keyword: string;
  skill: string;
  popular: InspirationRepo[];
  company: InspirationRepo[];
  hackathon: InspirationRepo[];
  links: { name: string; url: string }[];
};
export type IdeaSet = {
  id: number;
  created_at: string;
  /** live: GitHub just now; cache: GitHub, within a day; seed: built-in examples (offline). */
  source: "live" | "cache" | "seed";
  based_on: string;
  topics: IdeaTopic[];
  ideas: ProjectIdea[];
};
export type ProjectIdeasPayload = { set: IdeaSet | null; topics: { topic: string; keyword: string; skill: string }[]; gaps: string[] };
export type MyProject = { id: number; name: string; status: string; tech: string; repo_url: string; on_resume: boolean; updated_at: string };
