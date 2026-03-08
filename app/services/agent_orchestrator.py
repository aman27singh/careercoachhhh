"""
Agent Orchestrator
==================
Central coordination layer for the CareerCoach AI pipeline.

Pipelines exposed:
  - run_career_plan_pipeline()  — full end-to-end flow
        resume / GitHub  ──▶  profile_agent
                          └──▶  gap_agent  ──▶  roadmap_agent

  - run_skill_gap_pipeline()    — lighter flow for when skills are already known
        user_skills  ──▶  gap_agent  ──▶  roadmap_agent

Individual agents can still be called directly for single-stage operations
(e.g. evaluator_agent.run() is invoked by eval_engine independently).
"""
from __future__ import annotations

import logging

from app.agents import evaluator_agent, gap_agent, profile_agent, roadmap_agent
from app.services.profile_engine import _extract_resume_text, analyze_github
from app.services.role_engine import analyze_role as _market_analyze_role

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Full pipeline: resume / GitHub → profile → gap → roadmap
# ---------------------------------------------------------------------------

def run_career_plan_pipeline(
    *,
    resume_bytes: bytes | None = None,
    github_username: str | None = None,
    selected_role: str,
) -> dict:
    """End-to-end pipeline from raw profile data to a full career plan.

    Args:
        resume_bytes:     Raw PDF bytes (optional).
        github_username:  GitHub handle (optional).
        selected_role:    The role the user is targeting.

    Returns:
        {
            "alignment_score": float,
            "missing_skills":  list[dict],   # enriched MissingSkill dicts
            "roadmap":         list[dict],
            "capstone":        dict,
            "review":          dict,
        }
    """
    # ── Stage 1: Extract raw text / GitHub data ──────────────────────────
    resume_text = ""
    github_data: dict = {}

    if resume_bytes:
        try:
            resume_text = _extract_resume_text(resume_bytes)
        except Exception as exc:
            logger.warning("Could not extract resume text: %s", exc)

    if github_username:
        try:
            github_data = analyze_github(github_username)
        except Exception as exc:
            logger.warning("Could not fetch GitHub data: %s", exc)

    # ── Stage 2: Profile Agent → structured skills ────────────────────────
    profile_result = profile_agent.run(
        resume_text=resume_text,
        github_data=github_data or None,
    )
    user_skills: list[str] = profile_result.get("technical_skills", [])

    # ── Stage 3: Gap Agent (market data + LLM enrichment) ────────────────
    market_result = _market_analyze_role(
        user_skills=user_skills,
        selected_role=selected_role,
    )
    alignment_score: float = market_result.get("alignment_score", 0.0)
    market_gaps: list[dict] = market_result.get("missing_skills", [])

    enriched_gaps = gap_agent.run(
        user_skills=user_skills,
        selected_role=selected_role,
        market_gaps=market_gaps,
    )

    # ── Stage 4: Roadmap Agent ────────────────────────────────────────────
    roadmap_result = roadmap_agent.run(
        missing_skills=enriched_gaps,
        role_context=selected_role,
    )

    return {
        "alignment_score": alignment_score,
        "missing_skills": enriched_gaps,
        "roadmap": roadmap_result["roadmap"],
        "capstone": roadmap_result["capstone"],
        "review": roadmap_result["review"],
    }


# ---------------------------------------------------------------------------
# Lightweight pipeline: known skills → gap → roadmap
# ---------------------------------------------------------------------------

def run_skill_gap_pipeline(
    *,
    user_skills: list[str],
    selected_role: str,
) -> dict:
    """Gap analysis + roadmap for when the caller already has the skill list.

    Used by the ``/generate-career-plan`` route where the frontend sends
    skills directly (no profile scan required in this flow).

    Args:
        user_skills:   List of skill strings the user already has.
        selected_role: The target role to analyse against.

    Returns:
        {
            "alignment_score": float,
            "missing_skills":  list[dict],
            "roadmap":         list[dict],
            "capstone":        dict,
            "review":          dict,
        }
    """
    # ── Stage 1: Market-data gap analysis ────────────────────────────────
    market_result = _market_analyze_role(
        user_skills=user_skills,
        selected_role=selected_role,
    )
    alignment_score: float = market_result.get("alignment_score", 0.0)
    market_gaps: list[dict] = market_result.get("missing_skills", [])

    # ── Stage 2: Gap Agent — LLM enrichment ──────────────────────────────
    enriched_gaps = gap_agent.run(
        user_skills=user_skills,
        selected_role=selected_role,
        market_gaps=market_gaps,
    )

    # ── Stage 3: Roadmap Agent ────────────────────────────────────────────
    roadmap_result = roadmap_agent.run(
        missing_skills=enriched_gaps,
        role_context=selected_role,
    )

    return {
        "alignment_score": alignment_score,
        "missing_skills": enriched_gaps,
        "roadmap": roadmap_result["roadmap"],
        "capstone": roadmap_result["capstone"],
        "review": roadmap_result["review"],
    }
