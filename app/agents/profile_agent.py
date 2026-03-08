"""
Profile Agent
=============
Responsibility:
  - Accept resume text and/or GitHub profile data.
  - Use the LLM to extract and normalise the user's technical skills,
    soft skills, and experience level.
  - Return a clean structured dict ready for downstream agents.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging

from app.services.llm_service import ask_llm

logger = logging.getLogger(__name__)


def run(
    resume_text: str = "",
    github_data: dict | None = None,
) -> dict:
    """Extract and normalise user skills from available profile data.

    Args:
        resume_text:  Plain text extracted from a PDF résumé (may be empty).
        github_data:  Dict returned by profile_engine.analyze_github()
                      (keys: repo_count, primary_languages, language_breakdown).

    Returns:
        {
            "technical_skills": list[str],
            "soft_skills":       list[str],
            "experience_level":  "beginner" | "intermediate" | "advanced",
        }
    """
    context_parts: list[str] = []

    if resume_text.strip():
        # Limit to first 3 000 chars to stay within a single prompt
        context_parts.append(f"Resume text:\n{resume_text[:3000]}")

    if github_data:
        repos = github_data.get("repo_count", 0)
        primary = github_data.get("primary_languages", [])
        breakdown = github_data.get("language_breakdown", {})
        context_parts.append(
            f"GitHub profile: {repos} public repos.\n"
            f"Primary languages: {', '.join(primary) if primary else 'none'}.\n"
            f"Language breakdown: {breakdown}."
        )

    if not context_parts:
        logger.warning("Profile agent received no usable data; returning empty result.")
        return {
            "technical_skills": [],
            "soft_skills": [],
            "experience_level": "beginner",
        }

    context = "\n\n".join(context_parts)

    prompt = (
        "You are a senior career analyst. "
        "Extract skills from the professional profile data below.\n\n"
        "Return ONLY valid JSON with exactly this structure (no extra keys):\n"
        "{\n"
        '  "technical_skills": ["skill1", "skill2", ...],\n'
        '  "soft_skills":       ["skill1", "skill2", ...],\n'
        '  "experience_level":  "beginner" | "intermediate" | "advanced"\n'
        "}\n\n"
        f"Profile data:\n{context}\n\n"
        "Rules:\n"
        "- technical_skills: programming languages, frameworks, tools, cloud platforms.\n"
        "- soft_skills: interpersonal and leadership competencies.\n"
        "- experience_level: beginner (<2 yrs), intermediate (2-5 yrs), advanced (5+ yrs).\n"
        "Return ONLY the JSON object. No markdown, no explanation."
    )

    try:
        raw = ask_llm(prompt)
        # Robustly extract the first {...} block
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in LLM response")
        data = json.loads(raw[start:end])
        return {
            "technical_skills": data.get("technical_skills", []),
            "soft_skills": data.get("soft_skills", []),
            "experience_level": data.get("experience_level", "beginner"),
        }
    except Exception as exc:
        logger.error("Profile agent LLM extraction failed: %s", exc)
        # Graceful degradation: return empty skills so downstream agents still run
        return {
            "technical_skills": [],
            "soft_skills": [],
            "experience_level": "beginner",
        }
