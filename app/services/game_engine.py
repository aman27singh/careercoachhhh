from __future__ import annotations

import math

from app.models import UserMetrics

BASE_XP = 50


def calculate_xp_gain(quality_score: int, streak: int) -> int:
    quality_bonus = 0
    if quality_score >= 80:
        quality_bonus = 20
    elif quality_score >= 60:
        quality_bonus = 10

    streak_bonus = (streak // 3) * 30
    return BASE_XP + quality_bonus + streak_bonus


def calculate_level(total_xp: int) -> int:
    return math.floor(total_xp / 100) + 1


def calculate_rank(level: int) -> str:
    if level <= 2:
        return "Bronze"
    if level <= 4:
        return "Silver"
    if level <= 6:
        return "Gold"
    return "Platinum"


def calculate_execution_score(completed: int, assigned: int) -> float:
    if assigned <= 0:
        return 0.0
    return (completed / assigned) * 100.0


def apply_task_submission(
    metrics: UserMetrics,
    quality_score: int,
    streak: int,
    assigned_increment: int = 1,
    completed_increment: int = 1,
) -> UserMetrics:
    xp_gain = calculate_xp_gain(quality_score, streak)
    metrics.xp += xp_gain
    metrics.streak = streak
    metrics.total_assigned_tasks += assigned_increment
    metrics.total_completed_tasks += completed_increment
    metrics.level = calculate_level(metrics.xp)
    metrics.rank = calculate_rank(metrics.level)
    metrics.execution_score = calculate_execution_score(
        metrics.total_completed_tasks,
        metrics.total_assigned_tasks,
    )
    return metrics
