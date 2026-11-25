// Typed API client for the Organization Admin Portal (/api/org/*).

import { get, post, patch, upload, download, saveFile, ApiError, API } from "./api";

export interface OrgAdmin {
  id: number;
  org_code: string;
  name: string;
  org_type: string;
  official_domain: string;
  location: string;
  academic_batch: string;
  admin_name: string;
  admin_email: string;
  contact_phone: string;
  quiz_cutoff_pct: number;
  voice_cutoff_score: number;
  admin_verified: boolean;
}

export interface OrgMeResponse {
  admin: OrgAdmin | null;
  proctor_mode?: string;
  seb_config_keys?: string;
}

export interface AdminStepResponse {
  pending: string;
  sent_to: string;
  outbox: boolean;
  purpose: string;
}

export interface OrgOverviewData {
  org: OrgAdmin;
  cutoffs: { quiz_cutoff_pct: number; voice_cutoff_score: number };
  proctor_mode: string;
  seb_config_keys: string;
  kpis: {
    enrolled: number;
    active: number;
    avg_resume_match: number | null;
    avg_quiz: number | null;
    avg_voice: number | null;
    ready: number;
  };
  funnel: { label: string; count: number; of_enrolled: number; of_previous: number }[];
  funnel_takeaway: string;
  tier_mix: { tier: string; count: number }[];
  momentum_mix: { stage: string; count: number }[];
  performance: {
    main_domain: { group: string; count: number; readiness: number; takeaway: string }[];
    subdomain: { group: string; count: number; readiness: number; takeaway: string }[];
    takeaway: string;
  };
  gap_matrix: {
    main_domain: { group: string; skill: string; share: number; count: number }[];
    subdomain: { group: string; skill: string; share: number; count: number }[];
    takeaway: string;
  };
  quiz_averages: number[];
  voice_averages: number[];
  weekly_trend: { week: string; avg: number; count: number }[];
  rubric_breakdown: Record<string, number>;
  weakest_criterion: string | null;
  top_performers: { name: string; domain: string; readiness: number | null; username: string }[];
  needs_attention: { name: string; domain: string; issue: string; readiness: number | null; username: string }[];
  mail_channel: string;
  error: string;
}

export interface ParsedCsvRow {
  line: number;
  name: string;
  email: string;
  main_domain: string;
  subdomain: string;
  target_role: string;
  batch_year: string;
  status: string;
  note: string;
  ready: boolean;
}

export interface PreviewCsvResponse {
  columns: string[];
  rows: ParsedCsvRow[];
}

export interface ProvisionResponse {
  created_count: number;
  emails_queued: number;
  mail_channel: string;
  credentials_csv: string;
  credentials: {
    username: string;
    name: string;
    email: string;
    temp_password: string;
    welcome_code: string;
  }[];
}

export interface StudentDirectoryRow {
  Username: string;
  Name: string;
  Email: string;
  "Main domain": string;
  Subdomain: string;
  "Target role": string;
  "Account status": string;
  "Momentum Status"?: string;
  Readiness: number | null;
  "Resume match (%)": number | null;
  "Missing skills"?: string;
  "Quiz average (%)": number | null;
  "Voice average (/15)"?: number | null;
  "Proctor flags"?: number;
  "Study plan"?: string;
  "Last active"?: string;
}

export interface Candidate360Data {
  account: {
    id: string;
    username: string;
    name: string;
    email: string;
    target_role: string;
    main_domain: string;
    subdomain: string;
    account_status: string;
    batch_year?: string;
  };
  row: {
    username: string;
    name: string;
    stream: string;
    target_role: string;
    readiness: number | null;
    quiz_average: number | null;
    rubric_average: number | null;
    main_domain: string;
    subdomain: string;
    account_status: string;
  };
  steps: { label: string; detail: string; done: boolean }[];
  tier: string;
  detail: {
    match_percent: number | null;
    matched: string[];
    missing: string[];
    plans: { week: number; total: number; done: number; percent: number }[];
    plan_percent: number | null;
    quizzes: { when: string; skill: string; difficulty: string; score: number; total: number; percent: number }[];
    topics: { skill: string; percent: number }[];
    voices: {
      when: string;
      rubric: number;
      content: number;
      clarity: number;
      confidence: number;
      flags: string[];
      feedback: string;
      transcript: string;
    }[];
  };
  proctor_history: {
    attempt_id: string;
    kind: string;
    label: string;
    started_at: string;
    strikes: number;
    camera: string;
    status: string;
    events: { kind: string; at_s: number; duration_s: number | null; severity: string; text: string }[];
  }[];
  error: string;
}

export interface OrgMeta {
  org_types: string[];
  streams: string[];
  roles_by_stream: Record<string, string[]>;
  account_statuses: string[];
  proctor_modes: { id: string; label: string }[];
}

export interface ExperienceQueueItem {
  id: string;
  company: string;
  role: string;
  round: string;
  interview_month: string;
  label: string;
  status: string;
  flags: string[];
  tip?: string;
  questions: { text: string; kind: string; options?: string[]; correct_index?: number }[];
  process?: {
    result_label: string;
    summary?: string;
    rounds: { label: string; minutes?: number; difficulty: string }[];
  };
}

export interface ContributionQueueItem {
  id: string;
  topic: string;
  round: string;
  difficulty: string;
  licence: string;
  flags: string[];
  text: string;
  kind: string;
  options?: string[];
  correct_index?: number;
  explanation?: string;
  model_answer?: string;
}

export const orgApi = {
  getMe: () => get<OrgMeResponse>("/api/org/me"),
  createOrg: (body: {
    org_code: string;
    name: string;
    org_type: string;
    official_domain?: string;
    location?: string;
    academic_batch?: string;
    admin_name: string;
    admin_email: string;
    password: string;
    confirm: string;
    contact_phone?: string;
  }) => post<AdminStepResponse>("/api/org/create", body),
  login: (body: { email: string; password: string }) =>
    post<AdminStepResponse | { org: OrgAdmin }>("/api/org/login", body),
  verify: (body: { pending: string; code: string }) => post<{ org: OrgAdmin }>("/api/org/verify", body),
  resend: (body: { pending: string }) => post<AdminStepResponse>("/api/org/resend", body),
  recover: (body: { email: string }) => post<AdminStepResponse>("/api/org/recover", body),
  recoverFinish: (body: { pending: string; code: string; password: string; confirm: string }) =>
    post<{ org: OrgAdmin }>("/api/org/recover/finish", body),
  logout: () => post<{ ok: boolean }>("/api/org/logout", {}),

  getOverview: () => get<OrgOverviewData>("/api/org/overview"),

  downloadTemplate: () => download("/api/org/provisioning/template.csv", "student-template.csv"),
  previewCsv: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return upload<PreviewCsvResponse>("/api/org/provisioning/preview", fd);
  },
  commitCsv: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return upload<ProvisionResponse>("/api/org/provisioning/commit", fd);
  },
  quickAdd: (body: {
    name: string;
    email: string;
    main_domain: string;
    subdomain?: string;
    target_role?: string;
    batch_year?: string;
  }) => post<ProvisionResponse>("/api/org/provisioning/quick-add", body),

  getStudents: (params?: {
    query?: string;
    main_domains?: string[];
    subdomains?: string[];
    statuses?: string[];
    tiers?: string[];
  }) => {
    const qs = new URLSearchParams();
    if (params?.query) qs.set("query", params.query);
    params?.main_domains?.forEach((d) => qs.append("main_domains", d));
    params?.subdomains?.forEach((s) => qs.append("subdomains", s));
    params?.statuses?.forEach((st) => qs.append("statuses", st));
    params?.tiers?.forEach((t) => qs.append("tiers", t));
    const str = qs.toString();
    return get<{ total: number; shown: number; students: StudentDirectoryRow[]; cutoffs: { quiz_cutoff_pct: number; voice_cutoff_score: number } }>(
      `/api/org/students${str ? `?${str}` : ""}`,
    );
  },
  downloadProgressReport: () => download("/api/org/students/progress-report.csv", "progress-report.csv"),
  getStudentDetail: (studentId: string) => get<Candidate360Data>(`/api/org/students/${studentId}`),
  downloadStudentPdf: (studentId: string, username: string) =>
    download(`/api/org/students/${studentId}/report.pdf`, `report-${username}.pdf`),
  resetCredentials: (studentId: string) =>
    post<{ credential: Record<string, string>; credentials_csv: string; mail_channel: string }>(
      `/api/org/students/${studentId}/reset-credentials`,
      {},
    ),
  reassignStudent: (studentId: string, body: { main_domain: string; subdomain?: string; target_role?: string }) =>
    post<{ stream: string; subdomain: string; role: string; degree: string }>(
      `/api/org/students/${studentId}/reassign`,
      body,
    ),
  setStudentStatus: (studentId: string, status: "active" | "suspended") =>
    post<{ status: string }>(`/api/org/students/${studentId}/status`, { status }),
  nudgeStudent: (studentId: string) => post<{ ok: boolean }>(`/api/org/students/${studentId}/nudge`, {}),

  getSettings: () => get<{ org: OrgAdmin; proctor_mode: string; seb_config_keys: string }>("/api/org/settings"),
  updateSettings: (body: {
    name?: string;
    location?: string;
    academic_batch?: string;
    quiz_cutoff_pct?: number;
    voice_cutoff_score?: number;
    proctor_mode?: string;
    seb_config_keys?: string;
  }) =>
    patch<{ org: OrgAdmin; proctor_mode: string; seb_config_keys: string }>(
      "/api/org/settings",
      body,
    ),
  shortlist: (body: { main_domains?: string[]; subdomains?: string[]; min_quiz?: number; min_voice?: number }) =>
    post<{ total: number; shortlisted_count: number; students: StudentDirectoryRow[] }>("/api/org/shortlist", body),
  downloadShortlistCsv: async (body: { main_domains?: string[]; subdomains?: string[]; min_quiz?: number; min_voice?: number }) => {
    const res = await fetch(`${API}/api/org/shortlist/csv`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new ApiError("Failed to download CSV", res.status);
    saveFile(await res.blob(), res.headers.get("content-disposition"), "placement-shortlist.csv");
  },
  downloadExecutivePdf: async (body: { main_domains?: string[]; subdomains?: string[]; min_quiz?: number; min_voice?: number }) => {
    const res = await fetch(`${API}/api/org/shortlist/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new ApiError("Failed to download PDF", res.status);
    saveFile(await res.blob(), res.headers.get("content-disposition"), "executive-summary.pdf");
  },

  getExperiences: () => get<{ posts: ExperienceQueueItem[] }>("/api/org/moderation/experiences"),
  reviewExperience: (postId: string, body: { approved: boolean; reason?: string; company?: string }) =>
    post<{ ok: boolean }>(`/api/org/moderation/experiences/${postId}/review`, body),

  getContributions: () => get<{ questions: ContributionQueueItem[] }>("/api/org/moderation/contributions"),
  reviewContribution: (contribId: string, body: { approved: boolean; reason?: string }) =>
    post<{ ok: boolean }>(`/api/org/moderation/contributions/${contribId}/review`, body),

  getMeta: () => get<OrgMeta>("/api/org/meta"),
};
