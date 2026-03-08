"""
Mastery Tracker
===============
Tracks per-skill mastery levels for each user based on real performance signals:
  - GitHub implementation depth (from github_service mastery_signals)
  - Task XP earned on a specific skill
  - Skill verification score
  - Self-reporting (skill appears in resume/profile)

Mastery Levels
--------------
    0  UNKNOWN     – no evidence at all
    1  LEARNING    – self-reported or just started (<50 skill XP, not verified)
    2  PRACTICING  – actively using (50–150 skill XP OR completed 3+ tasks)
    3  PROFICIENT  – demonstrated competency (150+ skill XP OR verified with 70+ score)
    4  EXPERT      – verified with 90+ score AND 200+ skill XP

The level feeds directly into the Skill Impact Scoring Engine as the
mastery_discount factor — higher mastery = skill deprioritised in the roadmap.

mastery_discount lookup
-----------------------
    UNKNOWN     → 0.00   (full urgency — learn this)
    LEARNING    → 0.10   (slight discount — on the path)
    PRACTICING  → 0.30   (moderate discount — making progress)
    PROFICIENT  → 0.55   (strong discount — mostly covered)
    EXPERT      → 0.80   (major discount — only review if market demand spikes)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Mastery level constants ────────────────────────────────────────────────────
UNKNOWN    = 0
LEARNING   = 1
PRACTICING = 2
PROFICIENT = 3
EXPERT     = 4

LEVEL_NAMES = {
    UNKNOWN:    "unknown",
    LEARNING:   "learning",
    PRACTICING: "practicing",
    PROFICIENT: "proficient",
    EXPERT:     "expert",
}

# Skill Impact Engine mastery_discount per level
MASTERY_DISCOUNT: dict[int, float] = {
    UNKNOWN:    0.00,
    LEARNING:   0.10,
    PRACTICING: 0.30,
    PROFICIENT: 0.55,
    EXPERT:     0.80,
}

# ── Thresholds ─────────────────────────────────────────────────────────────────
_XP_PRACTICING  = 50
_XP_PROFICIENT  = 150
_XP_EXPERT      = 200
_SCORE_PROFICIENT = 70
_SCORE_EXPERT     = 90


def compute_mastery_level(
    skill: str,
    skill_xp: int = 0,
    verification_score: int | None = None,
    is_verified: bool = False,
    is_self_reported: bool = False,
    github_signal: float | None = None,
) -> int:
    """Determine mastery level (0–4) for a single skill from available signals.

    Args:
        skill:              Skill name (used for logging only).
        skill_xp:           Total XP earned from tasks specifically on this skill.
        verification_score: Score (0–100) from the most recent verification check.
        is_verified:        True if skill has been formally verified.
        is_self_reported:   True if skill appears in resume/profile.
        github_signal:      0–1 mastery signal from github_service (optional).

    Returns:
        Integer mastery level 0–4.
    """
    # Expert: verified AND excellent score AND substantial XP
    if is_verified and (verification_score or 0) >= _SCORE_EXPERT and skill_xp >= _XP_EXPERT:
        return EXPERT

    # Proficient: formally verified (any score) OR (high score + solid XP) OR substantial XP alone
    if is_verified:            # verification itself is sufficient evidence for proficient
        return PROFICIENT
    if (verification_score or 0) >= _SCORE_PROFICIENT and skill_xp >= _XP_PRACTICING:
        return PROFICIENT
    if (verification_score or 0) >= _SCORE_PROFICIENT and skill_xp >= _XP_PRACTICING:
        return PROFICIENT
    if skill_xp >= _XP_PROFICIENT:
        return PROFICIENT

    # Proficient via strong GitHub signal
    if github_signal is not None and github_signal >= 0.70:
        return PROFICIENT

    # Practicing: decent XP or GitHub activity
    if skill_xp >= _XP_PRACTICING:
        return PRACTICING
    if github_signal is not None and github_signal >= 0.35:
        return PRACTICING
    if is_self_reported and skill_xp > 0:
        return PRACTICING

    # Learning: any evidence at all
    if is_self_reported or skill_xp > 0 or (github_signal is not None and github_signal > 0):
        return LEARNING

    return UNKNOWN


def compute_mastery_for_all_skills(
    user_skills: list[str],
    verified_skills: set[str] | None = None,
    skill_xp_map: dict[str, int] | None = None,
    github_mastery_signals: dict[str, float] | None = None,
) -> dict[str, dict]:
    """Compute mastery levels for a set of skills.

    Args:
        user_skills:            Self-reported skills.
        verified_skills:        Skills that passed verification.
        skill_xp_map:           {skill: xp_earned_on_skill_tasks}.
        github_mastery_signals: {skill: 0–1 signal} from github_service.

    Returns:
        {skill: {"level": int, "level_name": str, "mastery_discount": float}}
    """
    verified_skills         = verified_skills or set()
    skill_xp_map            = skill_xp_map or {}
    github_mastery_signals  = github_mastery_signals or {}

    all_skills = set(
        [s.lower() for s in user_skills]
        + [s.lower() for s in verified_skills]
        + list(skill_xp_map.keys())
        + list(github_mastery_signals.keys())
    )

    result: dict[str, dict] = {}
    for skill in all_skills:
        level = compute_mastery_level(
            skill=skill,
            skill_xp=skill_xp_map.get(skill, 0),
            is_verified=skill.lower() in {s.lower() for s in verified_skills},
            is_self_reported=skill.lower() in {s.lower() for s in user_skills},
            github_signal=github_mastery_signals.get(skill),
        )
        result[skill] = {
            "level":            level,
            "level_name":       LEVEL_NAMES[level],
            "mastery_discount": MASTERY_DISCOUNT[level],
        }

    return result


def discount_for_level(level: int) -> float:
    """Return the Skill Impact Engine mastery_discount for a given level int."""
    return MASTERY_DISCOUNT.get(level, 0.0)


def level_name(level: int) -> str:
    """Return the human-readable name for a mastery level."""
    return LEVEL_NAMES.get(level, "unknown")
