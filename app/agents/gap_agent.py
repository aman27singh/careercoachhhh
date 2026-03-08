"""
Gap Agent
=========
Responsibility:
  - Accept the user's current skills and a target role.
  - Receive a pre-computed list of market-based skill gaps (from role_engine).
  - Use the LLM to enrich the top gaps with concise, personalised
    "why it matters" explanations and confirm prioritisation.
  - Return the enriched, ranked list of missing skills.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging

from app.services.llm_service import ask_llm
from app.services.retrieval_service import retrieve_context
from app.services import skill_impact_engine

logger = logging.getLogger(__name__)

# How many top gaps to send to the LLM for enrichment (keeps latency low)
_ENRICH_TOP_N = 5


def _build_context_block(docs: list[str]) -> str:
    """Format retrieved documents into a numbered CONTEXT section for the prompt."""
    if not docs:
        return ""
    lines = ["CONTEXT (retrieved from knowledge base):"]
    for i, doc in enumerate(docs, start=1):
        lines.append(f"[{i}] {doc.strip()}")
    lines.append("")  # blank separator before the rest of the prompt
    return "\n".join(lines) + "\n"


def run(
    user_skills: list[str],
    selected_role: str,
    market_gaps: list[dict],
) -> list[dict]:
    """Enrich and rank skill gaps with LLM-generated context.

    Args:
        user_skills:   Skills the user already has.
        selected_role: The role the user is targeting.
        market_gaps:   Pre-ranked gaps from role_engine (sorted by importance desc).
                       Each item is a MissingSkill-shaped dict.

    Returns:
        The same list, with top-N gaps having their ``why_this_skill_matters``
        field overwritten with a more personalised LLM explanation.
        Falls back to the original list if the LLM call fails.
    """
    if not market_gaps:
        return []

    # ── Re-rank gaps using Skill Impact Scores ──────────────────────────────
    # This replaces the static importance sort with a dynamic, multi-factor
    # score: market_demand × 0.40 + gap_severity × 0.35 + career_relevance × 0.25
    # adjusted by the user's mastery level.
    try:
        impact_scores = skill_impact_engine.compute_impact_scores(
            user_skills=user_skills,
            target_role=selected_role,
        )
        # Build lookup: lowercase skill → impact_score dict
        impact_map = {item["skill"].lower(): item for item in impact_scores}

        # Enrich each market gap with impact score data, then re-sort
        for gap in market_gaps:
            key = gap["skill"].lower()
            impact = impact_map.get(key)
            if impact:
                gap["importance"]      = int(impact["impact_score"])
                gap["market_signal"]   = (
                    f"Impact Score {impact['impact_score']:.1f}/100 — "
                    f"market demand {impact['market_demand']:.0%}, "
                    f"career relevance {impact['career_relevance']:.0%}"
                )

        # Sort by updated importance (impact score) descending
        market_gaps = sorted(market_gaps, key=lambda g: g.get("importance", 0), reverse=True)
        logger.info(
            "Gap agent re-ranked %d skills via Skill Impact Scores for role '%s'",
            len(market_gaps),
            selected_role,
        )
    except Exception as exc:
        logger.warning("Skill impact re-ranking failed, using original order: %s", exc)

    top_gaps = market_gaps[:_ENRICH_TOP_N]
    skill_names = [g["skill"] for g in top_gaps]

    skills_summary = (
        ", ".join(user_skills) if user_skills else "no skills listed"
    )

    # Retrieve relevant knowledge-base context before building the prompt
    retrieval_query = f"{selected_role} skill requirements: {', '.join(skill_names)}"
    context_docs = retrieve_context(retrieval_query)
    context_block = _build_context_block(context_docs)

    prompt = (
        "You are a career advisor performing a skill-gap analysis.\n\n"
        + context_block
        + f"Candidate's current skills: {skills_summary}\n"
        f"Target role: {selected_role}\n"
        f"Top missing skills (identified from market data): {', '.join(skill_names)}\n\n"
        "For each missing skill, provide:\n"
        "  1. A concise one-sentence explanation of why this skill is critical for the target role.\n"
        "  2. Whether it is high-priority given the candidate's existing skill set (true/false).\n\n"
        "Return ONLY a valid JSON array — one object per skill — in this exact format:\n"
        "[\n"
        '  {"skill": "<name>", "priority_confirmed": true, "why": "<one sentence>"},\n'
        "  ...\n"
        "]\n"
        "No markdown. No explanation. Just the JSON array."
    )

    try:
        raw = ask_llm(prompt)
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON array found in LLM response")
        enrichments: list[dict] = json.loads(raw[start:end])

        # Build lookup: lowercase skill name → enrichment dict
        enrichment_map = {
            e.get("skill", "").lower(): e for e in enrichments
        }

        # Apply enrichments to the top-N gaps in-place
        for gap in top_gaps:
            key = gap["skill"].lower()
            enrich = enrichment_map.get(key, {})
            if enrich.get("why"):
                gap["why_this_skill_matters"] = enrich["why"]

        return market_gaps

    except Exception as exc:
        logger.error("Gap agent LLM enrichment failed: %s", exc)
        # Return unchanged market gaps — pipeline continues without enrichment
        return market_gaps
