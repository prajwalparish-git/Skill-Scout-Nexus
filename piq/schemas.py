"""Pydantic models for every LLM output and the objects derived from them.

LLM-facing models (`*Extraction`, `WeeklyPlan`, `QuizSet`, `InterviewTurn`,
`AnswerEvaluation`, `QuizCritique`) describe exactly what the model must return.
Anything computable (scores, missing skills) is added in code, never asked of the LLM.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from piq.config import (
    BATCH_RE,
    DOMAIN_RE,
    EMAIL_RE,
    ORG_CODE_RE,
    ORG_QUIZ_CUTOFF_DEFAULT,
    ORG_VOICE_CUTOFF_DEFAULT,
    PHONE_RE,
    VOICE_RUBRIC_MAX,
)

# A syllabus topic of the student's domain (piq/syllabus.py). Which names are allowed depends
# on the student, so checks.check_plan and checks.check_quiz enforce it, not the schema.
Topic = Annotated[str, Field(min_length=1, max_length=60)]
Difficulty = Literal["easy", "medium", "hard"]
Score05 = Annotated[int, Field(ge=0, le=5)]


class ProfileExtraction(BaseModel):
    name: str
    education: str
    skills: list[str]
    projects: list[str]
    internships: list[str]
    matched_skills: list[str] = Field(
        description="Subset of the required skills the resume evidences"
    )
    resume_feedback: list[str] = Field(min_length=1, max_length=5)


class StudentProfile(ProfileExtraction):
    target_role: str
    missing_skills: list[str]
    readiness_score: int = Field(ge=0, le=100)


class DayPlan(BaseModel):
    day: int = Field(ge=1, le=7)
    topic: Topic
    subtopics: list[str] = Field(min_length=2, max_length=3)
    duration_min: int = Field(ge=30, le=240)
    practice_goal: str


class WeeklyPlan(BaseModel):
    week_no: int = Field(ge=1)
    rationale: str
    days: list[DayPlan] = Field(min_length=7, max_length=7)

    def minutes_by_topic(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.days:
            out[d.topic] = out.get(d.topic, 0) + d.duration_min
        return out


class Question(BaseModel):
    text: str = Field(min_length=10)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str
    bloom_level: Literal["remember", "understand", "apply", "analyze"]

    @field_validator("bloom_level", mode="before")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class QuizSet(BaseModel):
    topic: Topic
    difficulty: Difficulty
    questions: list[Question] = Field(min_length=1)


class QuestionVerdict(BaseModel):
    index: int
    valid: bool
    reason: str = ""


class QuizCritique(BaseModel):
    verdicts: list[QuestionVerdict]


class InterviewTurn(BaseModel):
    question: str = Field(min_length=5)
    intent: str
    is_followup: bool
    is_final: bool


class AnswerEvaluation(BaseModel):
    relevance: Score05
    depth: Score05
    structure: Score05
    clarity: Score05
    strengths: list[str]
    improvements: list[str]
    model_answer: str

    @property
    def scores(self) -> dict[str, int]:
        return {
            "relevance": self.relevance,
            "depth": self.depth,
            "structure": self.structure,
            "clarity": self.clarity,
        }

    @property
    def overall(self) -> float:
        return round(sum(self.scores.values()) / 4, 2)


class BulletRewrite(BaseModel):
    """One resume bullet in Google's XYZ form: accomplished X, measured by Y, by doing Z."""

    bullet: str = Field(min_length=10, max_length=320)


class FollowUpJudgement(BaseModel):
    """Evaluation only: does an interview question actually follow up on the last answer?"""

    references_answer: bool
    reason: str


class BaselineOutput(BaseModel):
    """Single-prompt baseline used only by the evaluation harness."""

    plan: WeeklyPlan
    quiz: QuizSet


class GitHubReadmeExtraction(BaseModel):
    """Structured intelligence the LLM extracts from a public GitHub README."""

    project_title: str = Field(min_length=1, max_length=120)
    one_line_pitch: str = Field(min_length=5, max_length=300)
    tech_stack: list[str] = Field(default_factory=list)
    star_bullets: list[str] = Field(min_length=1, max_length=3)
    viva_questions: list[str] = Field(min_length=1, max_length=2)


# --- organizations ----------------------------------------------------------------------------

OrgType = Literal["University", "Autonomous Institute", "Law/Commerce College", "Corporate L&D"]


class OrganizationForm(BaseModel):
    """What an organization's admin types when creating or editing the organization. Every
    check has a message safe to show; orgs.py turns the first one into a ServiceError."""

    org_code: str
    name: str = Field(max_length=200)
    org_type: OrgType
    official_domain: str = ""
    admin_name: str = Field(max_length=120)
    admin_email: str = Field(max_length=254)
    contact_phone: str = ""
    location: str = Field(default="", max_length=120)
    academic_batch: str = ""
    quiz_cutoff_pct: int = Field(default=ORG_QUIZ_CUTOFF_DEFAULT, ge=0, le=100)
    voice_cutoff_score: int = Field(default=ORG_VOICE_CUTOFF_DEFAULT, ge=0, le=VOICE_RUBRIC_MAX)

    @field_validator("org_code", mode="before")
    @classmethod
    def _code(cls, v: str) -> str:
        code = str(v or "").strip().upper()
        if not ORG_CODE_RE.match(code):
            raise ValueError(
                "Organization code: 3-30 capital letters, digits or hyphens, such as DBIT-BLR-2027."
            )
        return code

    @field_validator("name", "admin_name", mode="before")
    @classmethod
    def _required(cls, v: str) -> str:
        text = " ".join(str(v or "").split())
        if not text:
            raise ValueError("Organization name and admin name are required.")
        return text

    @field_validator("official_domain", mode="before")
    @classmethod
    def _domain(cls, v: str) -> str:
        domain = str(v or "").strip().lower().removeprefix("www.")
        if domain and not DOMAIN_RE.match(domain):
            raise ValueError("Official domain looks like dbit.co.in (no http:// and no path).")
        return domain

    @field_validator("admin_email", mode="before")
    @classmethod
    def _email(cls, v: str) -> str:
        email = str(v or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise ValueError("Enter a valid admin email address.")
        return email

    @field_validator("contact_phone", mode="before")
    @classmethod
    def _phone(cls, v: str) -> str:
        phone = " ".join(str(v or "").split())
        if phone and not PHONE_RE.match(phone):
            raise ValueError(
                "Contact phone: digits, spaces, - and ( ), with an optional leading +."
            )
        return phone

    @field_validator("academic_batch", mode="before")
    @classmethod
    def _batch(cls, v: str) -> str:
        batch = str(v or "").strip()
        if batch and not BATCH_RE.match(batch):
            raise ValueError("Academic batch looks like 2027 or 2026-2027.")
        return batch

    @field_validator("location", mode="before")
    @classmethod
    def _location(cls, v: str) -> str:
        return " ".join(str(v or "").split())


class Organization(BaseModel):
    """An organization as the portal shows it (never carries the admin's password hash)."""

    model_config = {"frozen": True}

    id: int
    org_code: str
    name: str
    org_type: str
    official_domain: str
    admin_name: str
    admin_email: str
    contact_phone: str
    location: str
    academic_batch: str
    quiz_cutoff_pct: int
    voice_cutoff_score: int
    created_at: str

    @property
    def short_name(self) -> str:
        """The name before a ' - ' or ',' (long names read badly in a sidebar)."""
        return self.name.split(" - ")[0].split(",")[0].strip() or self.name
