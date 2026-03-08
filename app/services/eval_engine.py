"""
Eval engine
===========
Thin wrapper maintained for backward compatibility with existing route handlers.
All business logic and LLM interaction now lives in app/agents/evaluator_agent.py.
"""
from app.models import TaskFeedback
from app.agents import evaluator_agent


def evaluate_submission(
    submission_text: str,
    task_context: str = "System Design",
    user_id: str | None = None,
    task_id: str | None = None,
    skill: str | None = None,
) -> TaskFeedback:
    """Evaluate a user submission and return structured AI feedback."""
    return evaluator_agent.run(
        submission_text=submission_text,
        task_context=task_context,
        user_id=user_id,
        task_id=task_id,
        skill=skill,
    )
