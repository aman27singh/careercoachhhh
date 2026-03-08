"""
Project Generation Agent
========================
Responsibility:
  - Generate a personalised hands-on project for the user's highest-priority
    skill gap.
  - Ensure UNIQUENESS per user — projects are seeded from user_id + skill
    + role context so no two users get the same project.
  - Support a 3-level progressive HINT system (nudge → partial → full).
  - Scale difficulty to the user's current mastery level.
  - Projects are structured for later autonomous evaluation by evaluation_agent.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import hashlib
import json
import logging
import random

from app.services.llm_service import ask_llm

logger = logging.getLogger(__name__)

# Difficulty labels mapped from mastery level (0-4)
_DIFFICULTY_MAP = {
    0: "beginner",
    1: "beginner",
    2: "intermediate",
    3: "intermediate",
    4: "advanced",
}

# Project archetypes shuffled via user-seed to ensure uniqueness
_PROJECT_ARCHETYPES = [
    "CLI tool",
    "REST API service",
    "Web application",
    "Data pipeline",
    "Automation script",
    "Library / SDK",
    "Dashboard",
    "Bot (Slack/Discord/Telegram)",
    "AI-powered tool",
    "DevOps workflow",
    "Mobile-first responsive app",
    "Browser extension",
]


def run(
    user_id: str,
    skill: str,
    target_role: str,
    mastery_level: int = 0,
    completed_projects: list[str] | None = None,
) -> dict:
    """Generate a unique personalised project for the user.

    Args:
        user_id:             User identifier (used as randomness seed).
        skill:               The skill the project should teach / test.
        target_role:         Role the user is targeting (shapes project domain).
        mastery_level:       Current mastery 0–4 (determines difficulty).
        completed_projects:  List of project titles the user already completed
                             (agent avoids regenerating the same project).

    Returns:
        {
            "title":          str,
            "skill":          str,
            "difficulty":     "beginner" | "intermediate" | "advanced",
            "description":    str,       # 2-3 sentence overview
            "objectives":     [str, ...],# 3-5 learning objectives
            "deliverables":   [str, ...],# What the user must build/submit
            "evaluation_criteria": [str],# How evaluation_agent will grade it
            "estimated_hours": int,
            "hints":          {
                "level_1": str,  # Gentle nudge — concept hint
                "level_2": str,  # Directional hint — approach
                "level_3": str,  # Near-solution hint — concrete steps
            },
            "archetype":      str,       # CLI tool / REST API / etc.
            "unique_seed":    str,       # Reproducible ID for this project
        }
    """
    difficulty = _DIFFICULTY_MAP.get(mastery_level, "beginner")
    completed_projects = completed_projects or []

    # ── Deterministic but unique archetype selection ───────────────────────────
    # hash(user_id + skill) → stable index so the same user always gets the
    # same project for a given skill, but different from other users.
    seed_str = f"{user_id}:{skill}:{target_role}"
    seed_hash = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed_hash)
    archetypes_shuffled = _PROJECT_ARCHETYPES.copy()
    rng.shuffle(archetypes_shuffled)

    # Pick the first archetype whose title isn't already completed
    archetype = archetypes_shuffled[0]
    for arch in archetypes_shuffled:
        candidate_title_prefix = f"{skill} {arch}"
        if not any(candidate_title_prefix.lower() in p.lower() for p in completed_projects):
            archetype = arch
            break

    unique_seed = hashlib.sha256(f"{seed_str}:{archetype}".encode()).hexdigest()[:12]

    prompt = (
        "You are a senior engineering mentor designing a hands-on project.\n\n"
        f"Skill to teach: {skill}\n"
        f"Target role: {target_role}\n"
        f"Difficulty: {difficulty} (mastery level {mastery_level}/4)\n"
        f"Project archetype: {archetype}\n"
        f"Already completed projects: {json.dumps(completed_projects[:5]) if completed_projects else 'none'}\n\n"
        "Design a project that:\n"
        "1. Is a concrete, buildable project (not a tutorial re-do).\n"
        "2. Directly develops the specified skill in the context of the target role.\n"
        "3. Has clear, measurable deliverables a code evaluator can assess.\n"
        "4. Matches the difficulty level.\n"
        "5. Has 3 progressive hints: level_1 (concept nudge), level_2 (approach direction), "
        "   level_3 (near-solution with concrete sub-steps).\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        "{\n"
        '  "title": "str",\n'
        '  "description": "str (2-3 sentences)",\n'
        '  "objectives": ["str", ...],\n'
        '  "deliverables": ["str", ...],\n'
        '  "evaluation_criteria": ["str", ...],\n'
        '  "estimated_hours": 0,\n'
        '  "hints": {\n'
        '    "level_1": "str",\n'
        '    "level_2": "str",\n'
        '    "level_3": "str"\n'
        "  }\n"
        "}"
    )

    try:
        raw = ask_llm(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(raw)
    except Exception as exc:
        logger.error("project_agent LLM/parse error: %s", exc)
        result = _fallback_project(skill, target_role, difficulty, archetype)

    # Inject stable metadata
    result["skill"] = skill
    result["difficulty"] = difficulty
    result["archetype"] = archetype
    result["unique_seed"] = unique_seed

    logger.info(
        "project_agent: generated '%s' for user %s (seed %s)",
        result.get("title", "unknown"),
        user_id,
        unique_seed,
    )
    return result


def get_hint(project: dict, hint_level: int) -> str:
    """Retrieve a specific hint level (1, 2, or 3) from a generated project.

    Args:
        project:    Dict returned by run().
        hint_level: 1 = gentle nudge, 2 = direction, 3 = near-solution.

    Returns:
        The hint text, or a message if the level is invalid.
    """
    hints = project.get("hints", {})
    key = f"level_{hint_level}"
    return hints.get(key, f"No hint available at level {hint_level}.")


# ── Fallback ───────────────────────────────────────────────────────────────────

def _fallback_project(
    skill: str,
    role: str,
    difficulty: str,
    archetype: str,
) -> dict:
    return {
        "title": f"Build a {archetype} using {skill}",
        "description": (
            f"Create a {difficulty}-level {archetype} that demonstrates practical "
            f"use of {skill} in a {role} context."
        ),
        "objectives": [
            f"Understand core {skill} concepts.",
            f"Apply {skill} in a real {archetype} scenario.",
            "Write clean, well-documented code.",
        ],
        "deliverables": [
            "Working source code in a GitHub repository.",
            "README with setup instructions.",
            "At least one passing test.",
        ],
        "evaluation_criteria": [
            "Code uses the skill correctly.",
            "Project runs without errors.",
            "README is present and clear.",
        ],
        "estimated_hours": 4 if difficulty == "beginner" else 8,
        "hints": {
            "level_1": f"Think about what problem a {skill}-based {archetype} solves.",
            "level_2": f"Break the {archetype} into layers: input, processing, output.",
            "level_3": f"Start with a minimal version: get one feature working end-to-end first.",
        },
    }
