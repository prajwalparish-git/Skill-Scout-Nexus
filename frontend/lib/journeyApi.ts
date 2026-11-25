// Typed API client for the Placement Journey & Evaluation endpoints (/api/journey/*).

import { get, post, upload, ApiError } from "./api";

export interface JourneyStatus {
  engine: {
    active_ai: string;
    ai: string;
    db: string;
    preloader: string;
    line: string;
  };
  services: {
    active_ai: string;
    voice: string;
    voice_detail: string;
    telemetry: string;
    ai_providers: { label: string; state: string; detail: string; keys: number }[];
  };
}

export interface DomainItem {
  id: string;
  name: string;
  roles: string[];
}

export interface StreamItem {
  stream: string;
  domains: DomainItem[];
}

export interface StreamsResponse {
  streams: string[];
  tree: StreamItem[];
  voice_streams: string[];
  categories: string[];
}

export interface ScanResponse {
  analysis: {
    matched_skills: string[];
    missing_gap_skills: string[];
    match_percentage: number;
    raw_text?: string;
  };
  saved: boolean;
}

export interface SavedScanData {
  saved: {
    matched: string[];
    missing: string[];
    match_percentage: number;
  } | null;
  gaps: string[];
  origin: string;
  target_role: string;
  stream: string;
  domain: string;
}

export interface SevenDayPlan {
  target_role: string;
  target_stream: string;
  addressed_gaps: string[];
  summary: string;
  is_provisional?: boolean;
  days: {
    day_number: number;
    focus_topic: string;
    learning_resource: { title: string; url: string; platform: string; estimated_time: string };
    micro_tasks: { task_description: string; estimated_minutes: number; verification_method: string }[];
  }[];
}

export interface RoadmapItem {
  week: number;
  plan: SevenDayPlan;
  done: string[];
}

export interface RoadmapsResponse {
  roadmaps: RoadmapItem[];
  gaps: string[];
  origin: string;
  role_skills: string[];
  target_role: string;
  stream: string;
}

export interface CriticQuizBatch {
  topic_or_skill: string;
  target_role: string;
  difficulty: string;
  source: string;
  attempts: number;
  critic_notes: string[];
  questions: {
    text: string;
    options: string[];
    correct_index: number;
    explanation: string;
    bloom_level?: string;
    difficulty?: string;
  }[];
}

export interface QuizGradeResponse {
  score: number;
  total: number;
  correct: boolean[];
  percent: number;
  saved: boolean;
}

export interface VoiceQuestionResponse {
  question: {
    question_text: string;
    target_role: string;
    stream: string;
    category: string;
    scenario_context?: string;
    expected_rubric_points?: string[];
  };
  speech: {
    audio_base64: string | null;
    media_type: string;
    voice: string;
  };
  browser_speech_html: string;
}

export interface VoiceAssessResponse {
  evaluation: {
    rubric: {
      content_knowledge: number;
      verbal_clarity_star: number;
      confidence_demeanour: number;
      total_score: number;
    };
    performance_tier: string;
    strengths: string[];
    areas_for_improvement: string[];
    gap_flags: {
      is_too_short: boolean;
      is_off_topic: boolean;
      overuses_buzzwords: boolean;
      flag_details: string[];
    };
  };
  saved: boolean;
  max_score: number;
}

export interface EvaluationResultsResponse {
  summary: Record<string, unknown> | null;
  scorecard: {
    overall_placementiq: number | null;
    overall_baseline: number | null;
    head_to_head_placementiq: number | null;
    head_to_head_baseline: number | null;
    groups: string[];
    parameters: {
      key: string;
      name: string;
      group: string;
      what: string;
      method: string;
      unit: string;
      higher_is_better: boolean;
      weight: number;
      baseline: number | null;
      placementiq: number | null;
      baseline_score: number | null;
      placementiq_score: number | null;
      note: string;
    }[];
  } | null;
}

export const journeyApi = {
  getStatus: () => get<JourneyStatus>("/api/journey/status"),
  getStreams: () => get<StreamsResponse>("/api/journey/streams"),
  getSamples: () => get<{ samples: string[] }>("/api/journey/samples"),

  getScan: () => get<SavedScanData>("/api/journey/scan"),
  scanResume: (role: string, file?: File, sampleName?: string) => {
    const fd = new FormData();
    fd.append("role", role);
    if (sampleName) {
      fd.append("sample_name", sampleName);
    } else if (file) {
      fd.append("file", file);
    }
    return upload<ScanResponse>("/api/journey/scan", fd);
  },

  getRoadmaps: () => get<RoadmapsResponse>("/api/journey/roadmaps"),
  buildRoadmap: (gaps: string[]) => post<{ roadmap: RoadmapItem; saved: boolean }>("/api/journey/roadmaps", { gaps }),
  setTasksDone: (week: number, done: string[]) =>
    post<{ ok: boolean }>(`/api/journey/roadmaps/${week}/tasks`, { done }),

  getCriticQuizSkills: () =>
    get<{
      skills: string[];
      sizes: number[];
      difficulties: string[];
      default_size: number;
      default_difficulty: string;
      target_role: string;
    }>("/api/journey/critic-quiz/skills"),
  generateCriticQuiz: (skill: string, difficulty = "medium", count = 5) =>
    post<CriticQuizBatch>("/api/journey/critic-quiz/generate", { skill, difficulty, count }),
  gradeCriticQuiz: (batch: CriticQuizBatch, answers: (number | null)[], attemptId?: string, proctorFlags: string[] = []) =>
    post<QuizGradeResponse>("/api/journey/critic-quiz/grade", {
      batch,
      answers,
      attempt_id: attemptId ?? null,
      proctor_flags: proctorFlags,
    }),

  getVoiceQuestion: (stream: string, category?: string, customQuestion?: string) =>
    post<VoiceQuestionResponse>("/api/journey/voice/question", {
      stream,
      category: category ?? null,
      custom_question: customQuestion ?? null,
    }),
  transcribeVoice: (blob: Blob) => {
    const fd = new FormData();
    fd.append("file", blob, "answer.wav");
    return upload<{ text: string }>("/api/journey/voice/transcribe", fd);
  },
  assessVoice: (
    question: VoiceQuestionResponse["question"],
    answer: string,
    attemptId?: string,
    proctorFlags: string[] = [],
  ) =>
    post<VoiceAssessResponse>("/api/journey/voice/assess", {
      question,
      answer,
      attempt_id: attemptId ?? null,
      proctor_flags: proctorFlags,
    }),

  getEvaluationResults: () => get<EvaluationResultsResponse>("/api/journey/evaluation-results"),
};
