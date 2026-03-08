"""
Autonomous Project Evaluation Agent
=====================================
Responsibility:
  - Accept a GitHub repo URL submitted by the user.
  - Fetch the repository structure and key files via the GitHub API.
  - Use the LLM to evaluate implementation quality against the project's
    evaluation_criteria (from project_agent).
  - Produce a structured score, specific feedback, and detected skill evidence.
  - Trigger mastery updates and XP awards upon completion.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.llm_service import ask_llm
from app.services import user_store, mastery_tracker
from app.services.github_service import analyze_github_deep

logger = logging.getLogger(__name__)

# Max chars of source code to include in the LLM prompt (keeps cost reasonable)
_MAX_CODE_CHARS = 6000

# Regex to extract GitHub owner/repo from a URL
_GITHUB_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/\s?#]+)", re.IGNORECASE
)


def run(
    user_id: str,
    github_repo_url: str,
    project: dict,
    skill: str,
) -> dict:
    """Autonomously evaluate a GitHub repository against a project specification.

    Args:
        user_id:         User identifier (used to persist outcome).
        github_repo_url: Full GitHub URL, e.g. https://github.com/alice/my-project
        project:         Dict from project_agent.run() (must contain
                         evaluation_criteria, skill, difficulty).
        skill:           Skill being assessed (e.g. "Docker").

    Returns:
        {
            "score":              int,          # 0 – 100
            "passed":             bool,         # Score >= 70
            "skill_evidence":     [str, ...],   # Specific patterns found
            "missing":            [str, ...],   # Required patterns NOT found
            "feedback":           str,          # Narrative feedback paragraph
            "xp_awarded":         int,
            "mastery_delta":      float,        # Change in mastery score
            "evaluation_details": [             # Per-criterion breakdown
                {"criterion": str, "met": bool, "note": str}
            ]
        }
    """
    # ── 1. Parse GitHub URL ───────────────────────────────────────────────────
    match = _GITHUB_URL_RE.search(github_repo_url)
    if not match:
        return _error_result("Invalid GitHub URL provided.")

    owner = match.group("owner")
    repo = match.group("repo")

    # ── 2. Fetch repo data via GitHub service ────────────────────────────────
    repo_data: dict[str, Any] = {}
    code_sample = ""
    try:
        # analyze_github_deep takes a GitHub username; for repo eval we pass owner
        repo_data = analyze_github_deep(username=owner)
        code_sample = repo_data.get("code_preview", "")[:_MAX_CODE_CHARS]
    except Exception as exc:
        logger.warning("evaluation_agent: GitHub fetch failed for %s/%s: %s", owner, repo, exc)

    readme = repo_data.get("readme", "")[:2000]
    languages = repo_data.get("language_breakdown", {})
    has_tests = repo_data.get("has_tests", False)
    file_tree = repo_data.get("file_tree", [])[:30]

    # ── 3. Build evaluation prompt ────────────────────────────────────────────
    criteria = project.get("evaluation_criteria", [])
    difficulty = project.get("difficulty", "beginner")

    criteria_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(criteria))
    context_block = (
        f"Project title: {project.get('title', 'Unknown')}\n"
        f"Skill being assessed: {skill}\n"
        f"Difficulty: {difficulty}\n\n"
        f"Evaluation criteria:\n{criteria_text}\n\n"
        f"Repository: {owner}/{repo}\n"
        f"Languages detected: {json.dumps(languages)}\n"
        f"Has test files: {has_tests}\n"
        f"File tree (sample): {json.dumps(file_tree)}\n\n"
    )
    if readme:
        context_block += f"README (first 2000 chars):\n{readme}\n\n"
    if code_sample:
        context_block += f"Code sample (first {_MAX_CODE_CHARS} chars):\n{code_sample}\n\n"

    prompt = (
        "You are an expert code reviewer evaluating a student's project submission.\n\n"
        + context_block
        + "Tasks:\n"
        "1. Score the submission 0-100 based on the evaluation criteria.\n"
        "2. List specific patterns or implementations you FOUND as evidence of the skill.\n"
        "3. List evaluation criteria that were NOT met.\n"
        "4. Write one paragraph of constructive feedback.\n"
        "5. For each criterion, state whether it was met and a brief note.\n\n"
        "Scoring guide:\n"
        "  - 90-100: All criteria met, goes beyond requirements.\n"
        "  - 70-89: Most criteria met, minor gaps.\n"
        "  - 50-69: Partial implementation, key aspects missing.\n"
        "  - < 50: Significant gaps or wrong approach.\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        "{\n"
        '  "score": 0,\n'
        '  "skill_evidence": ["str", ...],\n'
        '  "missing": ["str", ...],\n'
        '  "feedback": "str",\n'
        '  "evaluation_details": [\n'
        '    {"criterion": "str", "met": true, "note": "str"}\n'
        "  ]\n"
        "}"
    )

    try:
        raw = ask_llm(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        eval_result = json.loads(raw)
    except Exception as exc:
        logger.error("evaluation_agent: LLM eval failed: %s", exc)
        return _error_result(f"Evaluation service error: {exc}")

    score: int = int(eval_result.get("score", 0))
    passed: bool = score >= 70

    # ── 4. Award XP and update mastery ────────────────────────────────────────
    xp_awarded = 0
    mastery_delta = 0.0
    try:
        if passed:
            xp_awarded = _xp_for_score(score, difficulty)
            user_data = user_store.get_user(user_id) or {}
            current_xp = user_data.get("xp", 0)
            user_store.update_user(user_id, {"xp": current_xp + xp_awarded})

            # Update mastery
            mastery_snapshot = mastery_tracker.compute_mastery_for_all_skills(user_id)
            old_score = (user_data.get("skill_mastery", {}) or {}).get(skill, 0)
            new_score = mastery_snapshot.get(skill, old_score)
            mastery_delta = round(new_score - old_score, 3)

            logger.info(
                "evaluation_agent: user %s passed '%s', +%d XP, mastery Δ %.3f",
                user_id, project.get("title"), xp_awarded, mastery_delta,
            )
    except Exception as exc:
        logger.warning("evaluation_agent: XP/mastery update failed: %s", exc)

    return {
        "score": score,
        "passed": passed,
        "skill_evidence": eval_result.get("skill_evidence", []),
        "missing": eval_result.get("missing", []),
        "feedback": eval_result.get("feedback", ""),
        "xp_awarded": xp_awarded,
        "mastery_delta": mastery_delta,
        "evaluation_details": eval_result.get("evaluation_details", []),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _xp_for_score(score: int, difficulty: str) -> int:
    """XP scaling: higher difficulty and score → more XP."""
    base = score // 5  # 0–20 base
    multiplier = {"beginner": 1, "intermediate": 1.5, "advanced": 2}.get(difficulty, 1)
    return int(base * multiplier)


def _error_result(message: str) -> dict:
    return {
        "score": 0,
        "passed": False,
        "skill_evidence": [],
        "missing": [message],
        "feedback": message,
        "xp_awarded": 0,
        "mastery_delta": 0.0,
        "evaluation_details": [],
    }
