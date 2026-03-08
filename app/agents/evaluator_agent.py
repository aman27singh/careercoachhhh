"""
Evaluator Agent
===============
Responsibility:
  - Accept a user's submission text and the task context.
  - Use the LLM to grade the answer, identify mistakes, describe the
    correct approach, and suggest concrete improvements.
  - Return a structured TaskFeedback object.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
import uuid

from app.models import TaskFeedback
from app.services.llm_service import ask_llm
from app.services import user_store
from app.agents import verification_agent
logger = logging.getLogger(__name__)


# XP awarded per task: scales with rating, minimum 5 XP, maximum 20 XP.
def _xp_for_rating(rating: int) -> int:
    return max(5, min(20, rating // 5))


def run(
    submission_text: str,
    task_context: str = "System Design",
    user_id: str | None = None,
    task_id: str | None = None,
    skill: str | None = None,
) -> TaskFeedback:
    """Evaluate a user submission and return structured feedback.

    If *user_id* is provided the user's XP is incremented (proportional to
    the rating) and *task_id* is recorded in their ``completed_tasks`` set in
    DynamoDB.

    If *skill* is also provided and the submission scores >= 70, the skill is
    verified via the verification agent and stored in the user's ``skills``
    set.

    Args:
        submission_text: The user's written answer, code snippet, or project
                         description to be graded.
        task_context:    Topic / domain used to set the grading context
                         (e.g. "System Design", "Python", "Docker").
        user_id:         Optional user identifier.  When set, XP and task
                         completion are persisted to DynamoDB.
        task_id:         Optional task identifier.  Defaults to a UUID.
        skill:           Optional skill name being demonstrated.  When set
                         and score >= 70, triggers skill verification and
                         stores the verified skill in DynamoDB.

    Returns:
        TaskFeedback with rating (0-100), mistakes, correct_approach,
        and improvements.  Falls back to a safe default response if the
        LLM call fails.
    """
    prompt = (
        "You are a strict senior technical interviewer.\n"
        "Evaluate the candidate's answer below and return ONLY valid JSON.\n\n"
        "Grading rules:\n"
        "- Brutal and honest: score below 10 for off-topic or trivially wrong answers.\n"
        "- Vague or hand-wavy answers score below 50.\n"
        "- Full marks (90-100) only for comprehensive, technically precise answers.\n\n"
        f"Topic / context: {task_context}\n"
        f"Candidate's answer:\n{submission_text}\n\n"
        "Return JSON in exactly this format (no other text):\n"
        "{\n"
        '  "rating": <integer 0-100>,\n'
        '  "mistakes": ["<flaw 1>", "<flaw 2>", ...],\n'
        '  "correct_approach": "<what a strong answer would include>",\n'
        '  "improvements": ["<actionable next step 1>", ...]\n'
        "}"
    )

    try:
        raw = ask_llm(prompt)

        # Robustly extract the first complete {...} block
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in LLM response")

        data = json.loads(raw[start:end])

        feedback = TaskFeedback(
            rating=int(data.get("rating", 0)),
            mistakes=data.get("mistakes", []),
            correct_approach=data.get(
                "correct_approach", "Review technical documentation."
            ),
            improvements=data.get("improvements", []),
        )

        # ── Persist XP + completed task to DynamoDB ──────────────────────
        if user_id:
            _tid = task_id or str(uuid.uuid4())
            xp_delta = _xp_for_rating(feedback.rating)
            try:
                user_store.update_xp(user_id, xp_delta)
            except Exception as ddb_exc:
                logger.warning("Failed to update XP for user '%s': %s", user_id, ddb_exc)
            try:
                user_store.add_completed_task(user_id, _tid)
            except Exception as ddb_exc:
                logger.warning("Failed to record task '%s' for user '%s': %s", _tid, user_id, ddb_exc)
            # Track per-skill XP so mastery_tracker can compute finer levels
            if skill:
                try:
                    user_store.update_skill_xp(user_id, skill, xp_delta)
                except Exception as ddb_exc:
                    logger.warning("Failed to update skill XP for '%s'/'%s': %s", user_id, skill, ddb_exc)

        # ── Skill verification ────────────────────────────────────────────
        # If a specific skill was targeted and the score is good enough,
        # run verification and persist the result.
        if user_id and skill and feedback.rating >= 70:
            try:
                vr = verification_agent.verify_answer(
                    skill=skill,
                    question=task_context,
                    answer=submission_text,
                )
                if vr.verified:
                    user_store.add_verified_skill(user_id, skill)
                    logger.info(
                        "Skill '%s' verified for user '%s' (score=%d).",
                        skill, user_id, vr.score,
                    )
            except Exception as v_exc:
                logger.warning(
                    "Skill verification failed for '%s' / user '%s': %s",
                    skill, user_id, v_exc,
                )

        return feedback

    except Exception as exc:
        logger.error("Evaluator agent LLM grading failed: %s", exc)
        return TaskFeedback(
            rating=70,
            mistakes=["Unable to perform AI analysis at this time."],
            correct_approach="Please review standard documentation for this topic.",
            improvements=["Try providing more technical detail in your next answer."],
        )
