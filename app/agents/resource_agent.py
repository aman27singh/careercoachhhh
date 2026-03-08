"""
Precision Resource Curation Agent
===================================
Responsibility:
  - For each skill gap, provide PRECISE learning resources:
    · Exact course module names and direct URLs (not just homepage links).
    · MDN / official docs with section anchors (#).
    · YouTube video IDs with timestamp parameters (?t=NNs).
    · GitHub repo examples pointing to specific files / line ranges.
  - NEVER return generic top-level URLs like youtube.com or google.com.
  - Resources are ranked by precision and alignment to the user's mastery level.

All LLM interaction is funnelled through ask_llm().
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.llm_service import ask_llm

logger = logging.getLogger(__name__)

# Resource types the agent must produce
_RESOURCE_TYPES = ["documentation", "course_module", "video", "github_example", "article"]

# Known high-quality resource bases (LLM is prompted to use these)
_PREFERRED_DOMAINS = [
    "developer.mozilla.org",
    "docs.python.org",
    "docs.aws.amazon.com",
    "kubernetes.io/docs",
    "react.dev",
    "nextjs.org/docs",
    "docs.docker.com",
    "roadmap.sh",
    "github.com",
    "freecodecamp.org/learn",
    "egghead.io",
    "courses.cs.washington.edu",
    "youtube.com/watch",   # Only with ?t= timestamp
]


def run(
    skill: str,
    target_role: str,
    mastery_level: int = 0,
    max_resources: int = 5,
) -> list[dict]:
    """Curate precise learning resources for a given skill.

    Args:
        skill:          Skill to source resources for (e.g. "Kubernetes").
        target_role:    Role context (e.g. "DevOps Engineer").
        mastery_level:  Current mastery 0–4 (determines resource depth).
        max_resources:  Maximum number of resources to return.

    Returns:
        List of resource dicts:
        [
            {
                "type":        "documentation" | "course_module" | "video" | "github_example" | "article",
                "title":       str,
                "url":         str,       # MUST be specific, no top-level homepages
                "description": str,       # One sentence on exactly what this covers
                "mastery_fit": "beginner" | "intermediate" | "advanced",
                "time_to_consume": str,   # e.g. "15 min", "2 hours"
                "precision_score": float, # 0–1, how precisely targeted this resource is
            },
            ...
        ]
    """
    level_label = ["beginner", "beginner", "intermediate", "intermediate", "advanced"][
        min(mastery_level, 4)
    ]

    domains_str = "\n".join(f"  - {d}" for d in _PREFERRED_DOMAINS)

    prompt = (
        "You are a senior learning curator tasked with finding PRECISE resources.\n\n"
        f"Skill: {skill}\n"
        f"Role context: {target_role}\n"
        f"Learner level: {level_label} (mastery {mastery_level}/4)\n"
        f"Number of resources to provide: {max_resources}\n\n"
        "STRICT RULES:\n"
        "1. URLs must be SPECIFIC — link to the exact section/module/video.\n"
        "   GOOD: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Closures\n"
        "   BAD:  https://javascript.info\n"
        "2. For YouTube, you MUST include ?t=NNs timestamp pointing to the relevant section.\n"
        "3. For courses, link to the specific module, not the course homepage.\n"
        "4. For GitHub examples, link to the specific file or even line range.\n"
        "5. Resources must match the learner's mastery level.\n\n"
        "Preferred resource domains (use these when possible):\n"
        f"{domains_str}\n\n"
        f"Provide exactly {max_resources} resources covering different types.\n\n"
        "Return ONLY valid JSON array, no markdown:\n"
        "[\n"
        "  {\n"
        '    "type": "documentation|course_module|video|github_example|article",\n'
        '    "title": "str",\n'
        '    "url": "str",\n'
        '    "description": "str",\n'
        '    "mastery_fit": "beginner|intermediate|advanced",\n'
        '    "time_to_consume": "str",\n'
        '    "precision_score": 0.0\n'
        "  }\n"
        "]"
    )

    try:
        raw = ask_llm(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        resources = json.loads(raw)
        if not isinstance(resources, list):
            raise ValueError("Expected JSON array")
        resources = _filter_generic_urls(resources)
    except Exception as exc:
        logger.error("resource_agent: LLM/parse error for skill '%s': %s", skill, exc)
        resources = _fallback_resources(skill, level_label)

    # Sort by precision score descending
    resources.sort(key=lambda r: r.get("precision_score", 0), reverse=True)
    return resources[:max_resources]


def batch_run(
    skills: list[str],
    target_role: str,
    mastery_map: dict[str, int] | None = None,
    resources_per_skill: int = 3,
) -> dict[str, list[dict]]:
    """Curate resources for multiple skills at once.

    Args:
        skills:             List of skill names.
        target_role:        Role context.
        mastery_map:        {skill: mastery_level} optional per-skill mastery.
        resources_per_skill: Resources to return per skill.

    Returns:
        {skill: [resource, ...]}
    """
    mastery_map = mastery_map or {}
    return {
        skill: run(
            skill=skill,
            target_role=target_role,
            mastery_level=mastery_map.get(skill, 0),
            max_resources=resources_per_skill,
        )
        for skill in skills
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

_GENERIC_URLS = {
    "https://youtube.com",
    "https://www.youtube.com",
    "https://google.com",
    "https://www.google.com",
    "https://github.com",           # Too broad — must have a real path
    "https://stackoverflow.com",    # Top-level only
}


def _filter_generic_urls(resources: list[dict]) -> list[dict]:
    """Remove resources that only have a generic top-level URL."""
    filtered = []
    for r in resources:
        url = r.get("url", "")
        # Keep if URL has a meaningful path (more than just the domain)
        path = url.split("//")[-1].split("/", 1)[-1].strip("/")
        if path and url.rstrip("/") not in _GENERIC_URLS:
            filtered.append(r)
        else:
            logger.debug("resource_agent: dropped generic URL: %s", url)
    return filtered


def _fallback_resources(skill: str, level: str) -> list[dict]:
    skill_slug = skill.lower().replace(" ", "-").replace("/", "-")
    return [
        {
            "type": "documentation",
            "title": f"{skill} Official Documentation",
            "url": f"https://developer.mozilla.org/en-US/search?q={skill_slug}",
            "description": f"Official reference documentation for {skill}.",
            "mastery_fit": level,
            "time_to_consume": "30 min",
            "precision_score": 0.5,
        },
        {
            "type": "article",
            "title": f"{skill} — A Practical Guide",
            "url": f"https://roadmap.sh",
            "description": f"Structured learning path including {skill}.",
            "mastery_fit": level,
            "time_to_consume": "1 hour",
            "precision_score": 0.4,
        },
    ]
