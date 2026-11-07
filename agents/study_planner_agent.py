"""Study Planner Agent for Skill Scout Nexus (Layer 2 Multi-Agent Orchestration).

Responsibilities:
- Takes missing gap skills and target stream/role.
- Generates an adaptive 7-day study roadmap (Day 1 to Day 7).
- Each day contains:
  - Specific learning objectives (focused on candidate's skill gaps)
  - Curated free resources & official documentation links
  - Daily micro-tasks / hands-on practice problems
- Supports LLM generation with validation + robust deterministic offline fallback.
- Returns strict Pydantic model (`SevenDayRoadmap`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from piq import llm
from piq.config import settings

# Curated reference links for technical & domain skills (Free / Official documentation)
CURATED_RESOURCES: dict[str, list[dict[str, str]]] = {
    # CS Core & Languages
    "Java": [
        {
            "title": "Dev.java Official Documentation",
            "url": "https://dev.java/learn/",
            "type": "Documentation",
        },
        {
            "title": "Baeldung Java Tutorials",
            "url": "https://www.baeldung.com/java-tutorial",
            "type": "Tutorial",
        },
    ],
    "Python": [
        {
            "title": "Official Python Tutorial",
            "url": "https://docs.python.org/3/tutorial/",
            "type": "Documentation",
        },
        {"title": "Real Python Tutorials", "url": "https://realpython.com/", "type": "Article"},
    ],
    "Data Structures": [
        {
            "title": "GeeksforGeeks DSA Guide",
            "url": "https://www.geeksforgeeks.org/data-structures/",
            "type": "Guide",
        },
        {
            "title": "NeetCode DSA Roadmap",
            "url": "https://neetcode.io/roadmap",
            "type": "Interactive",
        },
    ],
    "Algorithms": [
        {
            "title": "VisuAlgo Visualising Algorithms",
            "url": "https://visualgo.net/en",
            "type": "Interactive",
        },
        {
            "title": "LeetCode Practice Problems",
            "url": "https://leetcode.com/explore/",
            "type": "Practice",
        },
    ],
    "SQL": [
        {
            "title": "PostgreSQL Official Documentation",
            "url": "https://www.postgresql.org/docs/",
            "type": "Documentation",
        },
        {
            "title": "SQLZoo Interactive SQL Tutorial",
            "url": "https://sqlzoo.net/",
            "type": "Interactive",
        },
    ],
    "Database Design": [
        {
            "title": "Database Star ER Diagrams & Normalization",
            "url": "https://www.databasestar.com/database-normalization/",
            "type": "Article",
        },
        {
            "title": "Use The Index, Luke (SQL Indexing)",
            "url": "https://use-the-index-luke.com/",
            "type": "Guide",
        },
    ],
    "Operating Systems": [
        {
            "title": "OSTEP (Operating Systems: Three Easy Pieces)",
            "url": "https://pages.cs.wisc.edu/~remzi/OSTEP/",
            "type": "Book",
        },
        {
            "title": "Linux Journey (Free Linux OS Guide)",
            "url": "https://linuxjourney.com/",
            "type": "Tutorial",
        },
    ],
    "Computer Networks": [
        {
            "title": "Beej's Guide to Network Programming",
            "url": "https://beej.us/guide/bgnet/",
            "type": "Guide",
        },
        {
            "title": "MDN Web Docs: An Overview of HTTP",
            "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
            "type": "Documentation",
        },
    ],
    "Object-Oriented Programming": [
        {
            "title": "Refactoring Guru: OOP Design Patterns",
            "url": "https://refactoring.guru/design-patterns",
            "type": "Guide",
        },
        {
            "title": "Clean Code & SOLID Principles Overview",
            "url": "https://www.freecodecamp.org/news/solid-principles-explained-in-plain-english/",
            "type": "Article",
        },
    ],
    "REST APIs": [
        {
            "title": "RESTful API Design Best Practices (GitHub Docs)",
            "url": "https://docs.github.com/en/rest",
            "type": "Documentation",
        },
        {
            "title": "Postman API Design Guide",
            "url": "https://www.postman.com/api-platform/api-design/",
            "type": "Guide",
        },
    ],
    "Spring Boot": [
        {
            "title": "Spring Boot Reference Guides",
            "url": "https://spring.io/guides",
            "type": "Documentation",
        },
    ],
    "React": [
        {
            "title": "React.dev Learn React Official",
            "url": "https://react.dev/learn",
            "type": "Documentation",
        },
    ],
    "Node.js": [
        {
            "title": "Node.js Official Documentation Guides",
            "url": "https://nodejs.org/en/docs/guides",
            "type": "Documentation",
        },
    ],
    "Git": [
        {"title": "Pro Git Book (Free)", "url": "https://git-scm.com/book/en/v2", "type": "Book"},
    ],
    "Machine Learning": [
        {
            "title": "Scikit-Learn User Guide",
            "url": "https://scikit-learn.org/stable/user_guide.html",
            "type": "Documentation",
        },
        {
            "title": "Google Machine Learning Crash Course",
            "url": "https://developers.google.com/machine-learning/crash-course",
            "type": "Course",
        },
    ],
    "Aptitude": [
        {
            "title": "IndiaBIX Quantitative Aptitude",
            "url": "https://www.indiabix.com/aptitude/questions-and-answers/",
            "type": "Practice",
        },
    ],
    "Logical Reasoning": [
        {
            "title": "IndiaBIX Logical Reasoning",
            "url": "https://www.indiabix.com/logical-reasoning/questions-and-answers/",
            "type": "Practice",
        },
    ],
}

DEFAULT_RESOURCE = {
    "title": "W3Schools & GeeksforGeeks Tech Guides",
    "url": "https://www.geeksforgeeks.org/",
    "type": "Guide",
}


class ResourceLink(BaseModel):
    title: str = Field(description="Name or title of learning resource")
    url: str = Field(description="Direct URL to documentation or tutorial")
    resource_type: str = Field(
        default="Documentation",
        description="Type: Documentation, Tutorial, Interactive, Video, Practice",
    )


class DailyRoadmap(BaseModel):
    day: int = Field(ge=1, le=7, description="Day index (1 through 7)")
    focus_skill: str = Field(description="Primary skill or concept targeted today")
    learning_objectives: list[str] = Field(
        min_length=1, description="2-3 specific tangible objectives for the day"
    )
    resources: list[ResourceLink] = Field(
        min_length=1, description="Curated free links or documentation"
    )
    micro_tasks: list[str] = Field(
        min_length=1, description="Practical micro-tasks/exercises to reinforce learning"
    )
    estimated_hours: float = Field(
        ge=0.5, le=8.0, default=2.0, description="Recommended study investment"
    )


class SevenDayRoadmap(BaseModel):
    target_role: str = Field(description="Role being prepared for")
    target_stream: str = Field(description="Academic domain / stream")
    addressed_gaps: list[str] = Field(description="Gap skills prioritized across the 7 days")
    summary: str = Field(description="Strategic executive summary of this 7-day study sprint")
    days: list[DailyRoadmap] = Field(
        min_length=7, max_length=7, description="Exact 7-day sequenced daily plans"
    )


def _get_curated_resources_for_skill(skill: str) -> list[ResourceLink]:
    """Retrieves verified links for a skill or falls back gracefully."""
    links: list[ResourceLink] = []
    # Direct match or partial match
    for k, v in CURATED_RESOURCES.items():
        if k.lower() in skill.lower() or skill.lower() in k.lower():
            for item in v:
                links.append(
                    ResourceLink(
                        title=item["title"],
                        url=item["url"],
                        resource_type=item.get("type", "Documentation"),
                    )
                )
    if not links:
        links.append(
            ResourceLink(
                title=f"{skill} Reference Documentation",
                url=f"https://devdocs.io/#q={skill.replace(' ', '+')}",
                resource_type="Documentation",
            )
        )
    return links[:3]


def build_fallback_roadmap(
    missing_skills: list[str], target_role: str, target_stream: str
) -> SevenDayRoadmap:
    """Builds a deterministic, rich 7-day roadmap when LLM is in mock mode or unavailable."""
    # Ensure we have skills to distribute
    skills_pool = (
        list(missing_skills)
        if missing_skills
        else ["Core Concepts", "Problem Solving", "System Design", "Best Practices"]
    )

    # Expand or cycle skills to fill 7 days
    day_skills = []
    for i in range(7):
        day_skills.append(skills_pool[i % len(skills_pool)])

    days: list[DailyRoadmap] = []
    for day_num, skill in enumerate(day_skills, start=1):
        resources = _get_curated_resources_for_skill(skill)

        if day_num == 7:
            focus = f"{skill} & Comprehensive Review"
            objs = [
                f"Consolidate all notes and code snippets on {skill}",
                "Complete a timed mock quiz covering all 7 days of concepts",
                "Review edge cases and common campus placement interview questions",
            ]
            tasks = [
                f"Build a mini capstone/summary cheat sheet synthesizing {skill} principles",
                "Attempt 10 multiple-choice questions without looking at documentation",
            ]
        elif day_num % 2 == 1:
            focus = f"{skill}: Fundamentals & Architecture"
            objs = [
                f"Understand core syntax, architectural structure, and lifecycle of {skill}",
                f"Identify typical production trade-offs and performance traits in {skill}",
            ]
            tasks = [
                f"Write 2-3 code snippets or step-by-step notes explaining fundamental {skill} "
                f"mechanics",
                f"Solve 3 practice questions or exercises from {resources[0].title}",
            ]
        else:
            focus = f"{skill}: Hands-on Implementation"
            objs = [
                f"Apply {skill} to solve a realistic problem or design a practical module",
                f"Implement error handling and edge cases standard in {target_role} expectations",
            ]
            tasks = [
                f"Build a runnable prototype demonstrating {skill} best practices",
                "Self-review code against official style guide and complexity criteria",
            ]

        days.append(
            DailyRoadmap(
                day=day_num,
                focus_skill=focus,
                learning_objectives=objs,
                resources=resources,
                micro_tasks=tasks,
                estimated_hours=2.0 if day_num != 7 else 3.0,
            )
        )

    gaps_str = ", ".join(missing_skills[:5]) if missing_skills else "role readiness competencies"
    summary = (
        f"A targeted 7-day adaptive sprint engineered for {target_role} ({target_stream}). "
        f"This roadmap bridges critical gap skills ({gaps_str}) with daily conceptual objectives, "
        "curated documentation, and practical micro-tasks designed for placement mastery."
    )

    return SevenDayRoadmap(
        target_role=target_role,
        target_stream=target_stream,
        addressed_gaps=missing_skills,
        summary=summary,
        days=days,
    )


def generate_study_roadmap(
    missing_gap_skills: list[str],
    target_role: str,
    target_stream: str = "Computer Science & Engineering",
    student_id: str | None = None,
) -> SevenDayRoadmap:
    """Main interface function for Study Planner Agent.

    Args:
        missing_gap_skills: List of identified gap skills.
        target_role: Target role (e.g. 'Java Backend Developer').
        target_stream: Candidate's detected academic stream or domain.
        student_id: Optional ID for logging purposes.

    Returns:
        SevenDayRoadmap: Complete 7-day actionable study plan.
    """
    cfg = settings()

    # Mock mode: the deterministic generator. Live: the AI router picks a provider, and any
    # failure (none answers) falls through to the same generator below.
    if cfg.mock_mode:
        return build_fallback_roadmap(missing_gap_skills, target_role, target_stream)

    # LLM-guided roadmap generation with strict schema enforcement
    skills_context = (
        ", ".join(missing_gap_skills)
        if missing_gap_skills
        else "General core technical fundamentals"
    )
    system_prompt = (
        "You are an expert technical placement coach and curriculum designer. "
        "Generate a structured, rigorous 7-day study roadmap (Day 1 through Day 7) "
        "targeting the candidate's exact skill gaps for the specified role. "
        "Ensure every day has precise technical learning objectives, reputable free/official "
        "documentation URLs, "
        "and practical micro-tasks that can be completed in 1.5 - 3 hours."
    )
    user_prompt = (
        f"Target Role: {target_role}\n"
        f"Target Stream: {target_stream}\n"
        f"Missing Gap Skills: {skills_context}\n\n"
        "Produce a SevenDayRoadmap strictly adhering to the schema."
    )

    try:
        roadmap, _ = llm.call(
            SevenDayRoadmap,
            agent="planner",
            system=system_prompt,
            user=user_prompt,
            context={"role": target_role, "gaps": missing_gap_skills, "stream": target_stream},
            student_id=student_id,
            size="small",
            temperature=0.3,
        )
        # Ensure curated links are augmented if LLM provided generic placeholders
        for day in roadmap.days:
            if not day.resources or any("example.com" in r.url for r in day.resources):
                day.resources = _get_curated_resources_for_skill(day.focus_skill)
        return roadmap
    except Exception:
        # Graceful, fault-tolerant failover to deterministic roadmap
        return build_fallback_roadmap(missing_gap_skills, target_role, target_stream)
