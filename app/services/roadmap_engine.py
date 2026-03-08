"""
Roadmap engine
==============
Thin wrapper maintained for backward compatibility with existing route handlers.
All business logic and LLM interaction now lives in app/agents/roadmap_agent.py.
"""
from __future__ import annotations

from app.agents import roadmap_agent


def generate_roadmap(
    missing_skills: list[dict],
    role_context: str = "Backend Developer",
) -> dict:
    """Generate a 30-day learning roadmap from a ranked list of missing skills."""
    return roadmap_agent.run(
        missing_skills=missing_skills,
        role_context=role_context,
    )
