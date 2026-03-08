from __future__ import annotations

import io
import json
import logging
import re

import boto3
import pdfplumber
import requests

from app.services.github_service import analyze_github_deep as _deep_github

logger = logging.getLogger(__name__)

# ── fallback keyword lists ────────────────────────────────────────────────────
TECHNICAL_KEYWORDS = [
    "python","java","c++","c#","go","rust","ruby","php","swift","kotlin",
    "javascript","typescript","react","vue","angular","node","express",
    "fastapi","django","flask","spring","sql","mongodb","postgres","redis",
    "docker","kubernetes","aws","azure","gcp","terraform","linux",
    "tensorflow","pytorch","machine learning","pandas","spark","kafka",
    "graphql","rest","grpc","git","ci/cd","github actions","jenkins",
]

SOFT_KEYWORDS = [
    "communication","leadership","teamwork","problem solving",
    "critical thinking","adaptability","collaboration","mentoring",
]

YEARS_PATTERN = re.compile(r"\b([2-9]\d*)\s*\+?\s*(years|yrs)\b", re.IGNORECASE)

_BEDROCK_MODEL = "amazon.nova-pro-v1:0"
_REGION        = "us-east-1"


# ── helpers ───────────────────────────────────────────────────────────────────
def _extract_resume_text(resume_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(resume_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def _detect_keywords(text: str, keywords: list[str]) -> list[str]:
    lower = text.lower()
    return [kw for kw in keywords if kw in lower]


def _infer_experience_level(text: str) -> str:
    lower = text.lower()
    if "senior" in lower or "lead" in lower or "principal" in lower or "staff" in lower:
        return "advanced"
    if ("engineer" in lower or "developer" in lower) and YEARS_PATTERN.search(lower):
        return "intermediate"
    if "intern" in lower or "student" in lower:
        return "beginner"
    return "intermediate"


# ── LLM extraction ───────────────────────────────────────────────────────────
_LLM_PROMPT_TMPL = """
You are a senior technical recruiter and career coach.
Analyze the resume text below and return a single JSON object with EXACTLY this schema — no markdown, no explanation, only JSON:

{{
  "summary": "<2-3 sentence professional summary>",
  "years_of_experience": <integer or null>,
  "experience_level": "<Beginner|Intermediate|Advanced|Expert>",
  "technical_skills": ["skill1", "skill2", ...],
  "soft_skills": ["skill1", "skill2", ...],
  "skill_ratings": [
    {{"skill": "Python", "score": 85, "level": "Advanced", "evidence": "5 years, used in 3 ML projects"}},
    ...
  ],
  "projects": [
    {{
      "name": "Project name",
      "description": "1-2 sentence description",
      "technologies": ["tech1", "tech2"],
      "complexity": "Simple|Medium|Complex",
      "highlights": ["highlight1", "highlight2"]
    }},
    ...
  ],
  "education": ["B.S. Computer Science, MIT, 2022", ...],
  "certifications": ["AWS Certified Solutions Architect", ...],
  "strengths": ["strength1", "strength2", "strength3"],
  "improvement_areas": ["area1", "area2"]
}}

Rules:
- skill_ratings must cover ALL technical_skills mentioned, each with score 0-100
- Score meaning: 0-30=Beginner, 31-60=Intermediate, 61-85=Advanced, 86-100=Expert
- projects: extract EVERY distinct project, personal project, capstone, open-source contribution
- evidence: cite specific resume lines as brief justification for the rating
- improvement_areas: infer gaps from the experience level and skill set
- Return ONLY the JSON object, nothing else

RESUME:
{resume_text}
"""


def _llm_analyze_resume(resume_text: str) -> dict | None:
    """Call Bedrock Nova Pro to extract a structured profile from resume text."""
    prompt = _LLM_PROMPT_TMPL.format(resume_text=resume_text[:12000])
    try:
        client = boto3.client("bedrock-runtime", region_name=_REGION)
        body = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": 3000, "temperature": 0.1},
        }
        resp = client.invoke_model(
            modelId=_BEDROCK_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        raw = json.loads(resp["body"].read())
        text: str = raw["output"]["message"]["content"][0]["text"].strip()
        # Strip any markdown fences if the model adds them
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text.rstrip())
        return json.loads(text)
    except Exception as exc:
        logger.warning("LLM resume analysis failed, falling back to keyword scan: %s", exc)
        return None


# ── public API ────────────────────────────────────────────────────────────────
def analyze_resume(resume_bytes: bytes | None) -> dict:
    if not resume_bytes:
        return {
            "summary": None,
            "years_of_experience": None,
            "experience_level": "beginner",
            "technical_skills": [],
            "soft_skills": [],
            "skill_ratings": [],
            "projects": [],
            "education": [],
            "certifications": [],
            "strengths": [],
            "improvement_areas": [],
        }

    text = _extract_resume_text(resume_bytes)

    # Try LLM first, fall back to keyword scan
    llm = _llm_analyze_resume(text)
    if llm:
        return {
            "summary":             llm.get("summary"),
            "years_of_experience": llm.get("years_of_experience"),
            "experience_level":    (llm.get("experience_level") or "beginner").lower(),
            "technical_skills":    llm.get("technical_skills") or [],
            "soft_skills":         llm.get("soft_skills") or [],
            "skill_ratings":       llm.get("skill_ratings") or [],
            "projects":            llm.get("projects") or [],
            "education":           llm.get("education") or [],
            "certifications":      llm.get("certifications") or [],
            "strengths":           llm.get("strengths") or [],
            "improvement_areas":   llm.get("improvement_areas") or [],
        }

    # keyword fallback
    lower = text.lower()
    yrs_match = YEARS_PATTERN.search(lower)
    return {
        "summary": None,
        "years_of_experience": int(yrs_match.group(1)) if yrs_match else None,
        "experience_level": _infer_experience_level(text),
        "technical_skills": _detect_keywords(text, TECHNICAL_KEYWORDS),
        "soft_skills":       _detect_keywords(text, SOFT_KEYWORDS),
        "skill_ratings":     [],
        "projects":          [],
        "education":         [],
        "certifications":    [],
        "strengths":         [],
        "improvement_areas": [],
    }


def analyze_github(username: str | None) -> dict:
    """Wrapper: delegates to github_service.analyze_github_deep."""
    return _deep_github(username)


def analyze_profile(resume_bytes: bytes | None, github_username: str | None) -> dict:
    resume_result = analyze_resume(resume_bytes)
    github_result = analyze_github(github_username)

    # Merge GitHub primary languages into technical_skills
    combined_tech = list(resume_result["technical_skills"])
    for lang in github_result.get("primary_languages", []):
        if lang.lower() not in {s.lower() for s in combined_tech}:
            combined_tech.append(lang)

    return {
        **resume_result,
        "technical_skills": combined_tech,
        "github_analysis":  github_result,
    }
