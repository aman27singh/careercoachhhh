"""
Learning Feedback Agent
========================
Responsibility:
  - Act as the single source of truth for ALL learning progress signals:
    · XP accumulation and level-up detection
    · Skill mastery progression (0–5 scale)
    · Consistency tracking (daily streaks, weekly velocity)
    · Adaptive difficulty adjustment
    · Insight generation (LLM surfaces what the patterns mean)
  - Unifies what was previously split across game_engine, mastery_tracker,
    eval_engine, and scattered update_user() calls.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.services.llm_service import ask_llm
from app.services import user_store, mastery_tracker

logger = logging.getLogger(__name__)

# XP thresholds per level (index = level)
_LEVEL_THRESHOLDS = [0, 100, 250, 500, 900, 1400, 2000, 2750, 3600, 4600, 6000]

# Max mastery score
_MAX_MASTERY = 100


def record_activity(
    user_id: str,
    activity_type: str,
    skill: str | None = None,
    xp_delta: int = 0,
    mastery_delta: float = 0.0,
    metadata: dict | None = None,
) -> dict:
    """Record a learning activity and update all derived metrics.

    Args:
        user_id:       User identifier.
        activity_type: One of: "task_completed" | "challenge_passed" | "challenge_failed"
                       | "project_submitted" | "project_passed" | "skill_verified"
                       | "quest_completed" | "resource_consumed".
        skill:         Skill being developed (optional).
        xp_delta:      XP to add (positive) or subtract (negative, rarely).
        mastery_delta:  Mastery score adjustment for the skill.
        metadata:       Extra context (e.g. score, project_title, difficulty).

    Returns:
        {
            "user_id":          str,
            "new_xp":           int,
            "new_level":        int,
            "leveled_up":       bool,
            "streak":           int,
            "skill_mastery":    {skill: score},
            "consistency_score": float,   # 0–1 based on recent activity
            "insight":          str,      # LLM-generated motivational/analytical insight
        }
    """
    metadata = metadata or {}

    # ── 1. Fetch current state ────────────────────────────────────────────────
    try:
        db_user = user_store.get_user(user_id) or {}
    except Exception:
        db_user = {}

    current_xp: int = db_user.get("xp", 0)
    current_level: int = db_user.get("level", 1)
    streak: int = db_user.get("streak", 0)
    activity_dates: list[str] = db_user.get("activity_dates", [])
    skill_mastery: dict[str, float] = db_user.get("skill_mastery", {}) or {}

    # ── 2. Apply XP delta ─────────────────────────────────────────────────────
    new_xp = max(0, current_xp + xp_delta)
    new_level = _compute_level(new_xp)
    leveled_up = new_level > current_level

    # ── 3. Update streak ──────────────────────────────────────────────────────
    today = date.today().isoformat()
    if activity_dates and activity_dates[-1] == today:
        pass  # Already counted today
    else:
        yesterday = _yesterday()
        if activity_dates and activity_dates[-1] == yesterday:
            streak += 1
        else:
            streak = 1
        activity_dates.append(today)
        # Keep last 90 days only
        activity_dates = activity_dates[-90:]

    # ── 4. Update skill mastery ─────────────────────────────────────────────
    if skill and mastery_delta != 0:
        current_skill_score = skill_mastery.get(skill, 0.0)
        new_skill_score = max(0.0, min(float(_MAX_MASTERY), current_skill_score + mastery_delta))
        skill_mastery[skill] = new_skill_score

    # ── 5. Compute consistency score ─────────────────────────────────────────
    consistency_score = _compute_consistency(activity_dates)

    # ── 6. Persist ────────────────────────────────────────────────────────────
    updates = {
        "xp": new_xp,
        "level": new_level,
        "streak": streak,
        "activity_dates": activity_dates,
        "skill_mastery": skill_mastery,
        "consistency_score": consistency_score,
        "last_active": today,
    }
    try:
        user_store.update_user(user_id, updates)
    except Exception as exc:
        logger.error("feedback_agent: persist failed for user %s: %s", user_id, exc)

    # ── 7. Generate LLM insight ───────────────────────────────────────────────
    insight = _generate_insight(
        activity_type=activity_type,
        skill=skill,
        xp_delta=xp_delta,
        new_level=new_level,
        leveled_up=leveled_up,
        streak=streak,
        consistency_score=consistency_score,
        skill_mastery=skill_mastery,
    )

    logger.info(
        "feedback_agent: %s for user %s | XP %d→%d | Level %d%s | Streak %d",
        activity_type, user_id, current_xp, new_xp, new_level,
        " (LEVEL UP!)" if leveled_up else "",
        streak,
    )

    return {
        "user_id": user_id,
        "new_xp": new_xp,
        "new_level": new_level,
        "leveled_up": leveled_up,
        "streak": streak,
        "skill_mastery": skill_mastery,
        "consistency_score": consistency_score,
        "insight": insight,
    }


def get_progress_summary(user_id: str) -> dict:
    """Return a comprehensive progress snapshot for the user.

    Returns:
        {
            "xp": int,
            "level": int,
            "streak": int,
            "consistency_score": float,
            "skill_mastery": {skill: score},
            "completed_tasks_count": int,
            "next_level_xp": int,
            "xp_to_next_level": int,
        }
    """
    try:
        db_user = user_store.get_user(user_id) or {}
    except Exception:
        db_user = {}

    xp: int = db_user.get("xp", 0)
    level: int = db_user.get("level", 1)
    streak: int = db_user.get("streak", 0)
    activity_dates: list[str] = db_user.get("activity_dates", [])
    skill_mastery: dict[str, float] = db_user.get("skill_mastery", {}) or {}
    completed_tasks: list = db_user.get("completed_tasks", [])

    next_level_xp = _next_level_threshold(level)
    xp_to_next = max(0, next_level_xp - xp)
    consistency_score = _compute_consistency(activity_dates)

    return {
        "xp": xp,
        "level": level,
        "streak": streak,
        "consistency_score": consistency_score,
        "skill_mastery": skill_mastery,
        "completed_tasks_count": len(completed_tasks),
        "next_level_xp": next_level_xp,
        "xp_to_next_level": xp_to_next,
    }


# ── Private helpers ────────────────────────────────────────────────────────────

def _compute_level(xp: int) -> int:
    for lvl in range(len(_LEVEL_THRESHOLDS) - 1, -1, -1):
        if xp >= _LEVEL_THRESHOLDS[lvl]:
            return lvl + 1
    return 1


def _next_level_threshold(current_level: int) -> int:
    idx = current_level  # level 1 → index 1
    if idx < len(_LEVEL_THRESHOLDS):
        return _LEVEL_THRESHOLDS[idx]
    return _LEVEL_THRESHOLDS[-1]


def _yesterday() -> str:
    from datetime import timedelta
    return (date.today() - timedelta(days=1)).isoformat()


def _compute_consistency(activity_dates: list[str]) -> float:
    """Consistency = fraction of last 14 days with at least one activity."""
    if not activity_dates:
        return 0.0
    from datetime import timedelta
    today = date.today()
    last_14 = {(today - timedelta(days=i)).isoformat() for i in range(14)}
    active_days = sum(1 for d in activity_dates if d in last_14)
    return round(active_days / 14, 2)


def _generate_insight(
    activity_type: str,
    skill: str | None,
    xp_delta: int,
    new_level: int,
    leveled_up: bool,
    streak: int,
    consistency_score: float,
    skill_mastery: dict[str, float],
) -> str:
    """Generate a brief, motivating LLM insight based on the activity."""
    top_skills = sorted(skill_mastery.items(), key=lambda x: x[1], reverse=True)[:3]
    top_str = ", ".join(f"{s} ({v:.0f})" for s, v in top_skills) if top_skills else "none yet"

    prompt = (
        "You are an encouraging career coach. Write ONE motivating insight (max 2 sentences) "
        "based on the learner's latest activity. Be specific, not generic.\n\n"
        f"Activity: {activity_type}\n"
        f"Skill worked on: {skill or 'general'}\n"
        f"XP gained: {xp_delta}\n"
        f"Current level: {new_level}{' (just leveled up!)' if leveled_up else ''}\n"
        f"Current streak: {streak} days\n"
        f"Consistency: {consistency_score * 100:.0f}% over last 14 days\n"
        f"Top skills by mastery: {top_str}\n\n"
        "Write ONLY the insight text, no JSON, no intro phrase like 'Great job!'"
    )

    try:
        return ask_llm(prompt).strip()
    except Exception as exc:
        logger.debug("feedback_agent._generate_insight: LLM error: %s", exc)
        if leveled_up:
            return f"Level {new_level} reached! Your consistency is paying off."
        if streak > 7:
            return f"{streak}-day streak — you're building a powerful learning habit."
        return f"+{xp_delta} XP earned. Keep going!"
