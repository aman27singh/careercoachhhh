"""
Skill Impact Scoring Engine
===========================
Core Innovation — dynamically ranks every skill gap by its real employability
value for the user's target role.

Formula
-------
    SkillImpactScore = (
        market_demand   * 0.40   # how in-demand is this skill for this role?
      + gap_severity    * 0.35   # does the user not have it yet?
      + career_relevance* 0.25   # how highly ranked is it within the role?
    ) * (1 - mastery_discount)   # reduce urgency if the user is already progressing

Factor definitions
------------------
market_demand    : raw frequency value from market_skills.json (0–1, from real
                   job listing analysis).

gap_severity     : 1.0  → skill completely absent from user's profile
                   0.4  → skill self-reported but not verified
                   0.0  → skill already verified via skill-verification flow

career_relevance : position-normalised rank within the role's skill list.
                   Top skill = 1.0; the least relevant skill in the role = 0.0.

mastery_discount : applied AFTER the weighted sum to scale down urgency when the
                   user is already progressing.
                   none          → 0.00  (full urgency)
                   self-reported → 0.20  (slight reduction)
                   verified      → 0.55  (significant reduction — still learn,
                                          but deprioritise vs unknown skills)

The final score is multiplied by 100 and rounded to 1 decimal place so it reads
as a 0–100 "impact score".

Re-ranking
----------
Call ``compute_impact_scores`` again after any skill verification event.  Because
the mastery_discount increases when a skill is verified, the ranked list
automatically shifts to prioritise the next most impactful gap — achieving the
Diagnose → Evaluate → Update → Re-rank loop described in the architecture.
"""
from __future__ import annotations

import logging

from app.services import mastery_tracker
from app.services import market_service

logger = logging.getLogger(__name__)

# ── Data ──────────────────────────────────────────────────────────────────────
_market_data: dict[str, dict[str, float]] | None = None


def _load_market_data() -> dict[str, dict[str, float]]:
    """Lazy-load market skill frequency data: /tmp → S3 → static fallback."""
    global _market_data
    if _market_data is None:
        _market_data = market_service.get_market_data()
        logger.info("Loaded market skill data: %d roles", len(_market_data))
    return _market_data


# ── Weights ───────────────────────────────────────────────────────────────────
_W_MARKET_DEMAND    = 0.40
_W_GAP_SEVERITY     = 0.35
_W_CAREER_RELEVANCE = 0.25

# Legacy binary severity values (used when no mastery_tracker data available)
_SEV_ABSENT        = 1.00
_SEV_SELF_REPORTED = 0.40
_SEV_VERIFIED      = 0.00

# Legacy binary discount values
_DISCOUNT_NONE          = 0.00
_DISCOUNT_SELF_REPORTED = 0.20
_DISCOUNT_VERIFIED      = 0.55


def _closest_role(target_role: str, available_roles: list[str]) -> str | None:
    """Case-insensitive fuzzy match for the target role against available roles."""
    target_lower = target_role.lower()
    for role in available_roles:
        if role.lower() == target_lower:
            return role
    # Partial match fallback
    for role in available_roles:
        if target_lower in role.lower() or role.lower() in target_lower:
            return role
    return None


def compute_impact_scores(
    user_skills: list[str],
    target_role: str,
    verified_skills: set[str] | None = None,
    skill_xp_map: dict[str, int] | None = None,
    github_mastery_signals: dict[str, float] | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """Compute and rank Skill Impact Scores for every skill in the target role.

    Uses mastery_tracker 5-level discounts when ``skill_xp_map`` or
    ``github_mastery_signals`` are provided; falls back to binary
    self-reported / verified logic otherwise.

    Args:
        user_skills:            Self-reported skills (case-insensitive).
        target_role:            Role to score against (e.g. "Backend Developer").
        verified_skills:        Skills verified via the skill-verification flow.
        skill_xp_map:           {skill: xp} from DynamoDB — enables 5-level mastery.
        github_mastery_signals: {skill: 0-1} from github_service.
        top_n:                  Return only the top-N ranked skills.

    Returns:
        Ranked list of dicts (highest impact first). Each dict contains::

            {
              "skill", "impact_score", "market_demand", "gap_severity",
              "career_relevance", "mastery_discount", "mastery_level",
              "mastery_level_name", "priority_rank",
            }
    """
    verified_skills        = verified_skills or set()
    skill_xp_map           = skill_xp_map or {}
    github_mastery_signals = github_mastery_signals or {}
    market_data            = _load_market_data()

    user_lower     = {s.lower().strip() for s in user_skills}
    verified_lower = {s.lower().strip() for s in verified_skills}

    matched_role = _closest_role(target_role, list(market_data.keys()))
    if not matched_role:
        logger.warning("Role '%s' not found in market data.", target_role)
        return []

    role_skills: dict[str, float] = market_data[matched_role]

    # Career relevance: rank-normalised position within the role
    sorted_skills = sorted(role_skills.items(), key=lambda x: x[1], reverse=True)
    n_skills = len(sorted_skills)
    relevance_map: dict[str, float] = {
        skill: 1.0 - (rank_idx / max(n_skills - 1, 1))
        for rank_idx, (skill, _) in enumerate(sorted_skills)
    }

    # Pre-compute 5-level mastery for all skills when rich data is available
    use_rich_mastery = bool(skill_xp_map or github_mastery_signals)
    rich_mastery: dict[str, dict] = {}
    if use_rich_mastery:
        rich_mastery = mastery_tracker.compute_mastery_for_all_skills(
            user_skills=list(user_lower),
            verified_skills=verified_lower,
            skill_xp_map=skill_xp_map,
            github_mastery_signals=github_mastery_signals,
        )

    results: list[dict] = []

    for skill, market_demand in role_skills.items():
        skill_lower = skill.lower().strip()

        if use_rich_mastery and skill_lower in rich_mastery:
            m                  = rich_mastery[skill_lower]
            level              = m["level"]
            mastery_discount   = m["mastery_discount"]
            mastery_level_name = m["level_name"]
            gap_severity       = max(0.0, 1.0 - (level / mastery_tracker.EXPERT))
        else:
            # Legacy binary fallback
            if skill_lower in verified_lower:
                gap_severity       = _SEV_VERIFIED
                mastery_discount   = _DISCOUNT_VERIFIED
                level              = mastery_tracker.PROFICIENT
                mastery_level_name = "proficient"
            elif skill_lower in user_lower:
                gap_severity       = _SEV_SELF_REPORTED
                mastery_discount   = _DISCOUNT_SELF_REPORTED
                level              = mastery_tracker.LEARNING
                mastery_level_name = "learning"
            else:
                gap_severity       = _SEV_ABSENT
                mastery_discount   = _DISCOUNT_NONE
                level              = mastery_tracker.UNKNOWN
                mastery_level_name = "unknown"

        career_relevance = relevance_map.get(skill, 0.0)

        raw_score = (
            market_demand      * _W_MARKET_DEMAND
            + gap_severity     * _W_GAP_SEVERITY
            + career_relevance * _W_CAREER_RELEVANCE
        )
        impact_score = raw_score * (1.0 - mastery_discount) * 100

        results.append({
            "skill":              skill,
            "impact_score":       round(impact_score, 1),
            "market_demand":      round(market_demand, 4),
            "gap_severity":       round(gap_severity, 2),
            "career_relevance":   round(career_relevance, 4),
            "mastery_discount":   round(mastery_discount, 2),
            "mastery_level":      level,
            "mastery_level_name": mastery_level_name,
            "priority_rank":      0,
        })

    results.sort(key=lambda x: x["impact_score"], reverse=True)
    for rank, item in enumerate(results, start=1):
        item["priority_rank"] = rank

    if top_n:
        results = results[:top_n]

    return results


def compute_alignment_score(
    user_skills: list[str],
    target_role: str,
    verified_skills: set[str] | None = None,
    top_n: int = 10,
) -> float:
    """Compute what % of the top-N role skills the user already covers.

    A skill counts as covered if it is self-reported OR verified.

    Args:
        user_skills:      Self-reported skills.
        target_role:      Target role name.
        verified_skills:  Verified skills (optional).
        top_n:            Number of top role skills to measure against.

    Returns:
        Alignment score as a percentage (0.0–100.0), rounded to 1 dp.
    """
    verified_skills = verified_skills or set()
    market_data = _load_market_data()

    matched_role = _closest_role(target_role, list(market_data.keys()))
    if not matched_role:
        return 0.0

    role_skills = market_data[matched_role]
    top_role_skills = sorted(role_skills.keys(), key=lambda s: role_skills[s], reverse=True)[:top_n]

    user_lower     = {s.lower().strip() for s in user_skills}
    verified_lower = {s.lower().strip() for s in verified_skills}
    covered = sum(
        1 for s in top_role_skills
        if s.lower() in user_lower or s.lower() in verified_lower
    )

    return round((covered / len(top_role_skills)) * 100, 1) if top_role_skills else 0.0


def get_top_priority_skill(
    user_skills: list[str],
    target_role: str,
    verified_skills: set[str] | None = None,
    skill_xp_map: dict[str, int] | None = None,
    github_mastery_signals: dict[str, float] | None = None,
) -> str | None:
    """Return the single highest-impact skill the user should learn next.

    Only considers skills the user does NOT yet have (mastery_level == UNKNOWN).
    """
    scores = compute_impact_scores(
        user_skills, target_role, verified_skills,
        skill_xp_map=skill_xp_map,
        github_mastery_signals=github_mastery_signals,
    )
    for item in scores:
        if item["mastery_level"] == mastery_tracker.UNKNOWN:
            return item["skill"]
    return scores[0]["skill"] if scores else None
