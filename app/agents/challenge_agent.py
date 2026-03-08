"""
Adaptive Daily Challenge Agent
================================
Responsibility:
  - Generate a daily micro-challenge ("Eat the Frog" / "Today's Quest")
    calibrated to the user's CURRENT mastery level for their priority skill.
  - Challenge difficulty adapts: if the user consistently passes, it levels up;
    if they fail, it steps back.
  - Evaluate text-based challenge responses and update mastery accordingly.
  - Track challenge streaks for consistency bonuses.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from app.services.llm_service import ask_llm
from app.services import user_store, mastery_tracker

logger = logging.getLogger(__name__)

# Mastery level → challenge type
_CHALLENGE_TYPES = {
    0: "conceptual",      # Explain the concept in plain English
    1: "fill-in-blank",   # Complete a short code snippet
    2: "debug",           # Fix a broken snippet
    3: "design",          # Design a small component / API
    4: "optimization",    # Optimise or refactor given code
}

# XP per challenge: scales with mastery level
_XP_MAP = {0: 5, 1: 8, 2: 12, 3: 16, 4: 20}


def generate(
    user_id: str,
    skill: str,
    mastery_level: int = 0,
) -> dict:
    """Generate a daily challenge for the given skill and mastery level.

    Args:
        user_id:       User identifier (used to check if today's challenge
                       was already issued).
        skill:         Skill to challenge the user on.
        mastery_level: Current mastery 0–4 (determines type and difficulty).

    Returns:
        {
            "challenge_id":   str,
            "skill":          str,
            "type":           str,   # conceptual / fill-in-blank / debug / ...
            "difficulty":     str,
            "question":       str,
            "context_code":   str | None,  # Starter code if applicable
            "expected_concepts": [str],    # Key ideas the answer must address
            "xp_available":   int,
            "today":          str (YYYY-MM-DD),
        }
    """
    today = date.today().isoformat()
    challenge_type = _CHALLENGE_TYPES.get(mastery_level, "conceptual")
    xp_available = _XP_MAP.get(mastery_level, 5)

    prompt = (
        "You are a Socratic coding mentor.\n"
        f"Skill: {skill}\n"
        f"Student mastery level: {mastery_level}/4\n"
        f"Challenge type: {challenge_type}\n"
        f"Today's date: {today}\n\n"
        "Design a single, focused daily challenge that:\n"
        "1. Takes 10-20 minutes to complete.\n"
        "2. Tests deep understanding, not just syntax recall.\n"
        "3. Matches the challenge type precisely.\n"
        "4. For code challenges: include a short context_code snippet.\n"
        "5. List 2-4 key concepts the answer MUST address.\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        "{\n"
        '  "question": "str",\n'
        '  "context_code": "str or null",\n'
        '  "expected_concepts": ["str", ...]\n'
        "}"
    )

    try:
        raw = ask_llm(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        llm_data = json.loads(raw)
    except Exception as exc:
        logger.error("challenge_agent.generate: LLM error: %s", exc)
        llm_data = _fallback_challenge(skill, challenge_type)

    import hashlib
    challenge_id = hashlib.sha256(
        f"{user_id}:{skill}:{today}:{mastery_level}".encode()
    ).hexdigest()[:16]

    return {
        "challenge_id": challenge_id,
        "skill": skill,
        "type": challenge_type,
        "difficulty": ["beginner", "beginner", "intermediate", "intermediate", "advanced"][
            min(mastery_level, 4)
        ],
        "question": llm_data.get("question", ""),
        "context_code": llm_data.get("context_code"),
        "expected_concepts": llm_data.get("expected_concepts", []),
        "xp_available": xp_available,
        "today": today,
    }


def evaluate(
    user_id: str,
    challenge: dict,
    answer_text: str,
) -> dict:
    """Evaluate the user's answer to a daily challenge.

    Args:
        user_id:       User identifier (XP and streak are persisted).
        challenge:     Dict returned by generate().
        answer_text:   The user's typed response.

    Returns:
        {
            "passed":          bool,
            "score":           int,     # 0–100
            "xp_earned":       int,
            "streak":          int,
            "feedback":        str,
            "correct_answer":  str,
            "next_difficulty": int,     # Suggested mastery_level for tomorrow
        }
    """
    skill = challenge.get("skill", "Unknown")
    challenge_type = challenge.get("type", "conceptual")
    expected = challenge.get("expected_concepts", [])
    question = challenge.get("question", "")
    xp_available = challenge.get("xp_available", 5)
    context_code = challenge.get("context_code", "")

    prompt = (
        "You are a strict but fair coding mentor evaluating a daily challenge.\n\n"
        f"Skill: {skill}\n"
        f"Challenge type: {challenge_type}\n"
        f"Question: {question}\n"
    )
    if context_code:
        prompt += f"Context code:\n{context_code}\n\n"
    prompt += (
        f"Expected key concepts: {', '.join(expected)}\n"
        f"Student's answer:\n{answer_text}\n\n"
        "Evaluate and return ONLY valid JSON:\n"
        "{\n"
        '  "score": 0,\n'
        '  "passed": false,\n'
        '  "feedback": "str",\n'
        '  "correct_answer": "str"\n'
        "}"
    )

    try:
        raw = ask_llm(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        eval_data = json.loads(raw)
    except Exception as exc:
        logger.error("challenge_agent.evaluate: LLM error: %s", exc)
        eval_data = {"score": 0, "passed": False, "feedback": "Evaluation failed.", "correct_answer": ""}

    passed: bool = bool(eval_data.get("passed", False))
    score: int = int(eval_data.get("score", 0))
    xp_earned = xp_available if passed else xp_available // 3

    # ── Persist XP and streak ────────────────────────────────────────────────
    streak = 0
    current_mastery_level = challenge.get("difficulty", "beginner")
    next_difficulty = challenge.get("difficulty", 0)

    try:
        db_user = user_store.get_user(user_id) or {}
        current_xp = db_user.get("xp", 0)
        streak = db_user.get("challenge_streak", 0)

        if passed:
            streak += 1
            # Auto-level difficulty after 3 consecutive passes
            mastery_level = min((db_user.get("mastery_level", 0) or 0) + (1 if streak % 3 == 0 else 0), 4)
        else:
            streak = 0
            mastery_level = max((db_user.get("mastery_level", 0) or 0) - 1, 0)

        next_difficulty = mastery_level
        user_store.update_user(user_id, {
            "xp": current_xp + xp_earned,
            "challenge_streak": streak,
            "mastery_level": mastery_level,
        })
    except Exception as exc:
        logger.warning("challenge_agent.evaluate: persist failed: %s", exc)

    return {
        "passed": passed,
        "score": score,
        "xp_earned": xp_earned,
        "streak": streak,
        "feedback": eval_data.get("feedback", ""),
        "correct_answer": eval_data.get("correct_answer", ""),
        "next_difficulty": next_difficulty,
    }


# ── Fallback ───────────────────────────────────────────────────────────────────

def _fallback_challenge(skill: str, challenge_type: str) -> dict:
    return {
        "question": (
            f"Explain how you would use {skill} in a production {challenge_type} scenario. "
            "Include concrete examples."
        ),
        "context_code": None,
        "expected_concepts": [
            f"Core {skill} concept",
            "real-world use case",
            "tradeoffs or limitations",
        ],
    }
