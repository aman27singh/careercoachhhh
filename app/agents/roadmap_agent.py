"""
Roadmap Agent
=============
Responsibility:
  - Accept a ranked list of missing skills and a target role.
  - Use the LLM to generate a personalised 7-day learning plan for the
    highest-priority skill; remaining weeks use deterministic templates
    to keep response latency acceptable.
  - Assemble and return a structured 30-day roadmap with capstone and
    review milestones.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging

from app.services.llm_service import ask_llm
from app.services.retrieval_service import retrieve_context

logger = logging.getLogger(__name__)


def _build_context_block(docs: list[str]) -> str:
    """Format retrieved documents into a numbered CONTEXT section for the prompt."""
    if not docs:
        return ""
    lines = ["CONTEXT (retrieved from knowledge base):"]
    for i, doc in enumerate(docs, start=1):
        lines.append(f"[{i}] {doc.strip()}")
    lines.append("")  # blank separator before the rest of the prompt
    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------------------
# Deterministic fallback templates (used for weeks 2-4 and on LLM failure)
# ---------------------------------------------------------------------------

_TASK_TEMPLATES: dict[int, str] = {
    1: "{skill} Fundamentals",
    2: "{skill} Core Concepts & Architecture",
    3: "{skill} Hands-on Practice",
    4: "{skill} Mini Project",
    5: "{skill} Advanced Concepts",
    6: "{skill} Real-world Use Cases",
    7: "{skill} Self-assessment & Checkpoint",
}

_DESC_TEMPLATES: dict[int, str] = {
    1: "Learn the fundamentals and basics of {skill}.",
    2: "Study core concepts, architecture, and key design patterns.",
    3: "Write code, follow tutorials, and get hands-on experience.",
    4: "Build a small project to solidify understanding.",
    5: "Explore advanced topics and best practices.",
    6: "Study real-world applications and case studies.",
    7: "Test your knowledge with a self-assessment and review weak areas.",
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(
    missing_skills: list[dict],
    role_context: str = "Software Engineer",
) -> dict:
    """Build a full 30-day personalised learning roadmap.

    Args:
        missing_skills: Ranked list of dicts with at minimum ``skill`` and
                        ``importance`` keys (output of gap_agent or role_engine).
        role_context:   Target role label used when constructing LLM prompts.

    Returns:
        {
            "roadmap":      list of WeekPlan dicts,
            "capstone":     CapstoneDay dict,
            "review":       CapstoneDay dict,
            "total_days":   int,
            "total_skills": int,
        }
    """
    sorted_skills = sorted(
        missing_skills, key=lambda x: x.get("importance", 0), reverse=True
    )
    top_skills = sorted_skills[:4]

    roadmap: list[dict] = []
    for week_num, skill_dict in enumerate(top_skills, start=1):
        skill_name = skill_dict.get("skill", "Skill")
        importance = skill_dict.get("importance", 0)

        # Only call the LLM for week 1 (highest priority) to reduce latency
        days = (
            generate_week_plan(skill_name, role_context)
            if week_num == 1
            else _deterministic_week_plan(skill_name)
        )

        roadmap.append(
            {
                "week": week_num,
                "focus_skill": skill_name,
                "importance": importance,
                "days": days,
            }
        )

    return {
        "roadmap": roadmap,
        "capstone": {
            "day": 29,
            "task": "Capstone Project",
            "description": "Build a capstone project combining all learned skills.",
        },
        "review": {
            "day": 30,
            "task": "Mock Interview & Review",
            "description": "Conduct a mock interview and review all concepts.",
        },
        "total_days": 30,
        "total_skills": len(top_skills),
    }


def generate_week_plan(skill: str, role_context: str) -> list[dict]:
    """Use the LLM to generate an AI-powered 7-day learning plan for *skill*.

    Falls back to the deterministic template if the LLM fails or returns
    malformed output.

    Args:
        skill:        The skill to build a plan for.
        role_context: Contextual role label for the prompt.

    Returns:
        List of exactly 7 day-plan dicts:
        [{"day": int, "task": str, "description": str}, ...]
    """
    # Retrieve relevant knowledge-base context before building the prompt
    retrieval_query = f"learning roadmap for {skill} targeting {role_context}"
    context_docs = retrieve_context(retrieval_query)
    context_block = _build_context_block(context_docs)

    prompt = (
        "Return ONLY valid JSON. "
        "Generate exactly 7 objects for a 7-day learning plan. "
        "Each object must follow this exact format: "
        '{"day": <number 1-7>, "task": "<short title>", "description": "<1-2 sentences>"}.\n\n'
        + context_block
        + f"Skill to learn: {skill}\n"
        f"Learner's target role: {role_context}\n\n"
        "Constraints:\n"
        "- Day 1: fundamentals/setup.\n"
        "- Day 7: self-assessment or checkpoint project.\n"
        "- Each day builds on the previous.\n"
        "Return a JSON array only. No explanation. No markdown."
    )

    try:
        raw_text = ask_llm(prompt)

        start = raw_text.find("[")
        end = raw_text.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("No JSON array found in LLM response")

        week_plan: list[dict] = json.loads(raw_text[start : end + 1])

        if not isinstance(week_plan, list):
            raise ValueError("LLM response is not a JSON array")
        if len(week_plan) < 7:
            raise ValueError(
                f"Expected 7 day entries, got {len(week_plan)}"
            )

        return week_plan[:7]

    except Exception as exc:
        logger.warning("Roadmap agent LLM generation failed: %s — using fallback.", exc)

    return _deterministic_week_plan(skill)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _deterministic_week_plan(skill: str) -> list[dict]:
    """Generate a static 7-day plan using the built-in templates."""
    return [
        {
            "day": day,
            "task": _TASK_TEMPLATES[day].format(skill=skill),
            "description": _DESC_TEMPLATES[day].format(skill=skill),
        }
        for day in range(1, 8)
    ]
