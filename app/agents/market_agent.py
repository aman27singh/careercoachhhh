"""
Market Intelligence Agent
=========================
Responsibility:
  - Fetch live job listing data (via market_service).
  - Use the LLM to detect EMERGING skills (mentioned in ≥ 5 postings but
    not yet in the standard role_engine baseline).
  - Compute demand weights for the current skill set.
  - Return a structured market intelligence snapshot.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.services.llm_service import ask_llm
from app.services import market_service, user_store

logger = logging.getLogger(__name__)

# Minimum job postings mentioning a skill before it's flagged as emerging
_EMERGING_THRESHOLD = 5


def run(
    user_skills: list[str],
    target_role: str,
    force_refresh: bool = False,
) -> dict:
    """Analyse the live job market for a given role and user skill set.

    Args:
        user_skills:   Skills the user currently has.
        target_role:   Role the user is targeting (e.g. "Full Stack Engineer").
        force_refresh: If True, re-fetch live job data even if cached.

    Returns:
        {
            "demand_map": {skill: demand_score},     # 0.0 – 1.0
            "emerging_skills": [                     # New skills gaining traction
                {
                    "skill": str,
                    "mention_count": int,
                    "trend": "rising" | "stable" | "declining",
                    "why_emerging": str
                }
            ],
            "top_skills_in_demand": [str, ...],      # Top 10 most in-demand
            "market_saturation": float,              # 0–1, how much user already covers
            "snapshot_date": str (ISO-8601),
            "total_jobs_analysed": int,
        }
    """
    # ── 1. Fetch market data ─────────────────────────────────────────────────
    raw_market: dict[str, Any] = {}
    try:
        raw_market = market_service.get_market_data()
    except Exception as exc:
        logger.warning("market_agent: market_service failed: %s", exc)

    # ── 2. Extract role-specific skills_freq from the market data dict ────────
    # market_skills.json: {"Role Name": {"skill": frequency, ...}, ...}
    # Find the closest matching role section
    role_lower = target_role.lower()
    role_data: dict[str, float] = {}
    for role_key, role_skills in raw_market.items():
        if isinstance(role_skills, dict) and role_lower in role_key.lower():
            role_data = role_skills
            break
    # Fallback: merge all roles
    if not role_data:
        for role_skills in raw_market.values():
            if isinstance(role_skills, dict):
                for skill, freq in role_skills.items():
                    role_data[skill] = max(role_data.get(skill, 0), float(freq))

    skills_freq: dict[str, int] = {
        skill: int(freq * 1000) for skill, freq in role_data.items()
    }
    top_skills: list[str] = sorted(skills_freq, key=lambda s: skills_freq[s], reverse=True)[:20]
    jobs_count = len(skills_freq)

    # ── 2. Build demand map (normalised 0–1) ─────────────────────────────────
    max_freq = max(skills_freq.values()) if skills_freq else 1
    demand_map: dict[str, float] = {
        skill: round(count / max_freq, 3)
        for skill, count in skills_freq.items()
    }

    # ── 3. Use LLM to detect emerging skills and analyse trends ──────────────
    emerging_skills: list[dict] = []
    if top_skills:
        skills_preview = json.dumps(
            {k: v for k, v in list(skills_freq.items())[:40]}
        )
        prompt = (
            "You are a senior tech recruiter scanning live job market data.\n\n"
            f"Target role: {target_role}\n"
            f"User's current skills: {', '.join(user_skills) if user_skills else 'none'}\n"
            f"Skills seen in job postings (skill: mention_count): {skills_preview}\n\n"
            "Tasks:\n"
            "1. Identify EMERGING skills: technologies mentioned in the data that are growing "
            "   in demand but are NOT yet mainstream (not Python, React, SQL, etc.).\n"
            "2. For each emerging skill, explain WHY it's relevant to this role in one sentence.\n"
            "3. Classify its trend: 'rising' | 'stable' | 'declining'.\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            "{\n"
            '  "emerging_skills": [\n'
            '    {"skill": "str", "mention_count": 0, "trend": "rising|stable|declining",\n'
            '     "why_emerging": "str"}\n'
            "  ]\n"
            "}"
        )
        try:
            raw = ask_llm(prompt)
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            parsed = json.loads(raw)
            emerging_skills = parsed.get("emerging_skills", [])[:8]
        except Exception as exc:
            logger.warning("market_agent: LLM emerging-skill detection failed: %s", exc)

    # ── 4. Market saturation (how much of top-10 the user already has) ───────
    user_lower = {s.lower() for s in user_skills}
    covered = sum(1 for s in top_skills[:10] if s.lower() in user_lower)
    saturation = round(covered / max(len(top_skills[:10]), 1), 2)

    result = {
        "demand_map": demand_map,
        "emerging_skills": emerging_skills,
        "top_skills_in_demand": top_skills[:10],
        "market_saturation": saturation,
        "snapshot_date": datetime.now(timezone.utc).isoformat(),
        "total_jobs_analysed": jobs_count,
    }
    return result
