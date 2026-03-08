"""
Verification Agent
==================
Responsibility:
  - Generate a short challenge question (or coding task) for a named skill.
  - Evaluate the user's answer against that question using the LLM.
  - Return a structured VerificationResult with score, feedback, and a
    boolean ``verified`` flag (True when score >= VERIFY_THRESHOLD).

Public interface
----------------
    generate_challenge(skill: str) -> str
        Ask the LLM to produce a single challenge question for *skill*.

    verify_answer(skill: str, question: str, answer: str) -> VerificationResult
        Grade the user's answer to *question* and decide if the skill is
        verified.

    run(skill: str, answer: str) -> VerificationResult
        Convenience wrapper: generates the challenge internally then evaluates
        the answer in one call.  Useful when the question does not need to be
        shown to the user beforehand.

Scoring
-------
    score >= 70  → verified = True  (solid practical knowledge demonstrated)
    score <  70  → verified = False (needs more practice)

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging

from app.services.llm_service import ask_llm

logger = logging.getLogger(__name__)

# Minimum score (0–100) that counts as a verified skill.
VERIFY_THRESHOLD: int = 70


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class VerificationResult:
    """Structured result returned by the verification agent."""

    __slots__ = ("skill", "question", "score", "feedback", "verified", "strengths", "gaps")

    def __init__(
        self,
        skill: str,
        question: str,
        score: int,
        feedback: str,
        verified: bool,
        strengths: list[str],
        gaps: list[str],
    ) -> None:
        self.skill = skill
        self.question = question
        self.score = score
        self.feedback = feedback
        self.verified = verified
        self.strengths = strengths
        self.gaps = gaps

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "question": self.question,
            "score": self.score,
            "feedback": self.feedback,
            "verified": self.verified,
            "strengths": self.strengths,
            "gaps": self.gaps,
        }


# ---------------------------------------------------------------------------
# Challenge generation
# ---------------------------------------------------------------------------

def generate_challenge(skill: str) -> str:
    """Ask the LLM to produce a concise challenge question for *skill*.

    The question is designed to reveal practical understanding — not just
    definitions — in 1–4 sentences so the user can answer it in a short
    paragraph or ~10 lines of code.

    Args:
        skill: Name of the skill to challenge (e.g. "Docker", "SQL Indexing").

    Returns:
        A single challenge question string.  Falls back to a generic question
        on LLM failure.
    """
    prompt = (
        "You are a senior technical interviewer.\n"
        f"Generate ONE concise, practical challenge question for the skill: \"{skill}\".\n\n"
        "Rules:\n"
        "- The question must require demonstrated understanding, not just a definition.\n"
        "- It should be answerable in 1–3 short paragraphs or a small code snippet.\n"
        "- Do NOT include answer hints or multiple sub-questions.\n"
        "- Return ONLY the question — no preamble, no numbering, no quotes.\n"
    )

    try:
        question = ask_llm(prompt).strip()
        # Sanity: if the model returned multiple lines of boilerplate, take the last non-empty line
        lines = [l.strip() for l in question.splitlines() if l.strip()]
        return lines[-1] if lines else question
    except Exception as exc:
        logger.warning("generate_challenge failed for skill '%s': %s", skill, exc)
        return (
            f"Explain how you have used {skill} in a real project. "
            "Describe a specific problem you solved with it and how."
        )


# ---------------------------------------------------------------------------
# Answer evaluation
# ---------------------------------------------------------------------------

def verify_answer(skill: str, question: str, answer: str) -> VerificationResult:
    """Grade the user's *answer* to *question* and decide if *skill* is verified.

    Args:
        skill:    The skill being tested.
        question: The challenge question that was posed.
        answer:   The user's response.

    Returns:
        VerificationResult with score (0–100), narrative feedback, a list of
        demonstrated strengths, a list of knowledge gaps, and
        verified = (score >= VERIFY_THRESHOLD).
    """
    prompt = (
        "You are a strict senior technical interviewer grading a skill verification.\n\n"
        f"Skill being tested: {skill}\n"
        f"Challenge question: {question}\n"
        f"Candidate's answer:\n{answer}\n\n"
        "Grading criteria:\n"
        "- 90–100: Expert level. Answer is precise, complete, and demonstrates real experience.\n"
        "- 70–89:  Proficient. Answer is correct with minor omissions or imprecision.\n"
        "- 50–69:  Basic. Answer shows partial understanding but missing key concepts.\n"
        "- 0–49:   Insufficient. Answer is vague, incorrect, or shows no real knowledge.\n\n"
        "Return ONLY valid JSON in exactly this format (no other text):\n"
        "{\n"
        '  "score": <integer 0–100>,\n'
        '  "feedback": "<1–2 sentence overall assessment>",\n'
        '  "strengths": ["<what the candidate demonstrated well>", ...],\n'
        '  "gaps": ["<specific knowledge gap or error>", ...]\n'
        "}"
    )

    try:
        raw = ask_llm(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in LLM response")

        data = json.loads(raw[start:end])
        score = max(0, min(100, int(data.get("score", 0))))
        return VerificationResult(
            skill=skill,
            question=question,
            score=score,
            feedback=data.get("feedback", ""),
            verified=score >= VERIFY_THRESHOLD,
            strengths=data.get("strengths", []),
            gaps=data.get("gaps", []),
        )

    except Exception as exc:
        logger.error("verify_answer LLM call failed for skill '%s': %s", skill, exc)
        return VerificationResult(
            skill=skill,
            question=question,
            score=0,
            feedback="Verification could not be completed due to a service error. Please try again.",
            verified=False,
            strengths=[],
            gaps=["Evaluation service unavailable."],
        )


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def run(skill: str, answer: str) -> VerificationResult:
    """Generate a challenge for *skill* and immediately evaluate *answer*.

    This is the single-call path used when the frontend submits both the
    skill name and the answer without a prior challenge-generation step
    (e.g. when the challenge was composed by the evaluator internally).

    Args:
        skill:  Name of the skill to verify.
        answer: The user's answer or work sample.

    Returns:
        VerificationResult.
    """
    question = generate_challenge(skill)
    logger.debug("Verification challenge for '%s': %s", skill, question)
    return verify_answer(skill, question, answer)
