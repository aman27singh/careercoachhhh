"""
Skill Extraction Agent
======================
Responsibility:
  - Unify skill data from ALL available sources:
      • Resume text (PDF-extracted)
      • GitHub profile analysis (repos, languages, contribution signals)
      • Manual skill declarations (user-entered list)
  - Use the LLM to normalise, deduplicate, and infer proficiency levels.
  - Produce a rich structured skill profile that feeds every downstream agent.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.llm_service import ask_llm
from app.services import user_store

logger = logging.getLogger(__name__)

# Proficiency tiers so callers have a stable contract
PROFICIENCY_LEVELS = ("beginner", "familiar", "proficient", "advanced", "expert")


def run(
    user_id: str,
    resume_text: str = "",
    github_data: dict | None = None,
    manual_skills: list[str] | None = None,
) -> dict:
    """Extract, unify, and score the user's technical skill profile.

    Sources are combined before the LLM pass so the model can resolve
    conflicts (e.g. "React" on resume + "JavaScript / TypeScript" from GitHub
    → unifiedskill set with inferred proficiency).

    Args:
        user_id:       User identifier (used to persist the result).
        resume_text:   Raw text extracted from the user's PDF resume.
        github_data:   Dict from github_service.analyze_github_deep():
                       keys: repo_count, primary_languages, language_breakdown,
                             mastery_signals (list of dicts).
        manual_skills: Skills the user manually declared in onboarding.

    Returns:
        {
            "skills": [
                {
                    "name": str,
                    "category": "language" | "framework" | "tool" | "cloud" | "soft" | "other",
                    "proficiency": "beginner" | "familiar" | "proficient" | "advanced" | "expert",
                    "source": "resume" | "github" | "manual" | "inferred",
                    "confidence": float  # 0.0 – 1.0
                },
                ...
            ],
            "experience_level": "beginner" | "intermediate" | "advanced",
            "primary_domain":   str,   # e.g. "Backend Engineering"
            "summary":          str,   # One-sentence profile summary
        }
    """
    context_parts: list[str] = []

    # ── Source 1: Resume ─────────────────────────────────────────────────────
    if resume_text.strip():
        context_parts.append(
            f"RESUME (first 3000 chars):\n{resume_text[:3000]}"
        )

    # ── Source 2: GitHub ──────────────────────────────────────────────────────
    if github_data:
        repos = github_data.get("repo_count", 0)
        primary = github_data.get("primary_languages", [])
        breakdown = github_data.get("language_breakdown", {})
        mastery_signals = github_data.get("mastery_signals", [])

        gh_lines = [
            f"GITHUB PROFILE: {repos} public repos.",
            f"Primary languages: {', '.join(primary) if primary else 'none'}.",
            f"Language breakdown: {json.dumps(breakdown)}.",
        ]
        if mastery_signals:
            top_signals = mastery_signals[:10]
            gh_lines.append(f"Mastery signals (sample): {json.dumps(top_signals)}")
        context_parts.append("\n".join(gh_lines))

    # ── Source 3: Manual declarations ────────────────────────────────────────
    if manual_skills:
        context_parts.append(
            f"MANUALLY DECLARED SKILLS: {', '.join(manual_skills)}"
        )

    if not context_parts:
        logger.warning("skill_agent: no usable input for user %s", user_id)
        return _empty_profile()

    combined_context = "\n\n".join(context_parts)

    prompt = (
        "You are a senior engineering recruiter and skill assessor.\n"
        "Analyse ALL the profile data below from multiple sources and extract a unified skill set.\n\n"
        "Rules:\n"
        "1. Deduplicate skills that appear under different names (e.g. 'JS' and 'JavaScript' → 'JavaScript').\n"
        "2. Infer proficiency from evidence: years, project complexity, repo quality signals.\n"
        "3. Assign source: 'resume' / 'github' / 'manual' / 'inferred'.\n"
        "4. Confidence: 1.0 = directly evidenced; 0.5 = inferred from context; 0.2 = guessed.\n"
        "5. Identify the primary technical domain (e.g. 'Backend Engineering', 'ML/AI', 'DevOps').\n"
        "6. Write a one-sentence professional summary.\n\n"
        "Return ONLY valid JSON in exactly this structure (no markdown):\n"
        "{\n"
        '  "skills": [\n'
        '    {"name": "str", "category": "language|framework|tool|cloud|soft|other",\n'
        '     "proficiency": "beginner|familiar|proficient|advanced|expert",\n'
        '     "source": "resume|github|manual|inferred", "confidence": 0.0}\n'
        "  ],\n"
        '  "experience_level": "beginner|intermediate|advanced",\n'
        '  "primary_domain": "str",\n'
        '  "summary": "str"\n'
        "}\n\n"
        f"Profile data:\n{combined_context}"
    )

    try:
        raw = ask_llm(prompt)
        # Strip possible markdown fences
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(raw)
        _validate_profile(result)
    except Exception as exc:
        logger.error("skill_agent LLM/parse error for user %s: %s", user_id, exc)
        # Fall back: build a basic profile from raw inputs
        result = _heuristic_profile(resume_text, github_data, manual_skills)

    # ── Persist flat skill list to DynamoDB ──────────────────────────────────
    try:
        flat_skills = [s["name"] for s in result.get("skills", [])]
        if flat_skills:
            existing = user_store.get_user(user_id) or {}
            merged = list(set(existing.get("learned_skills", []) + flat_skills))
            user_store.update_user(user_id, {"learned_skills": merged})
            logger.info(
                "skill_agent: persisted %d unified skills for user %s",
                len(flat_skills),
                user_id,
            )
    except Exception as exc:
        logger.warning("skill_agent: DynamoDB persist failed: %s", exc)

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_profile() -> dict:
    return {
        "skills": [],
        "experience_level": "beginner",
        "primary_domain": "Unknown",
        "summary": "No profile data available.",
    }


def _validate_profile(result: dict) -> None:
    """Raise ValueError if the result is structurally invalid."""
    if "skills" not in result or not isinstance(result["skills"], list):
        raise ValueError("Missing or invalid 'skills' list")
    if result.get("experience_level") not in ("beginner", "intermediate", "advanced"):
        result["experience_level"] = "beginner"


def _heuristic_profile(
    resume_text: str,
    github_data: dict | None,
    manual_skills: list[str] | None,
) -> dict:
    """Build a minimal profile without LLM when the call fails."""
    skills: list[dict] = []

    # Manual skills are the most reliable fallback
    for s in (manual_skills or []):
        skills.append({
            "name": s.strip(),
            "category": "other",
            "proficiency": "familiar",
            "source": "manual",
            "confidence": 0.8,
        })

    # Add primary languages from GitHub
    if github_data:
        for lang in github_data.get("primary_languages", [])[:5]:
            skills.append({
                "name": lang,
                "category": "language",
                "proficiency": "proficient",
                "source": "github",
                "confidence": 0.7,
            })

    return {
        "skills": skills,
        "experience_level": "beginner",
        "primary_domain": "Software Engineering",
        "summary": "Profile assembled from available data.",
    }
