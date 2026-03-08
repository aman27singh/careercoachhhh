"""
Resources Engine
================
Given a specific learning topic + skill context, uses Bedrock Nova Pro to
return in one call:
  - Curated learning resources (YouTube search links, official docs, free platforms, practice sites)
  - 2-3 real GitHub repos useful for studying or building projects on this topic

Design decisions
----------------
- YouTube links are search URLs so they never 404.
- GitHub repo names must be real, well-known repos the LLM has high confidence in.
- One Bedrock call returns both resources + repos as a combined JSON object.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse

import boto3

logger = logging.getLogger(__name__)

_REGION        = os.getenv("AWS_REGION", "us-east-1")
_BEDROCK_MODEL = "amazon.nova-pro-v1:0"

_PROMPT = """You are a senior software engineering mentor. A learner is studying:

Topic: {topic}
Skill: {skill}
Target role: {role}

Return a single JSON object with TWO keys: "resources" and "repos".

"resources": array of 6-8 learning resources. Rules:
- YouTube: URL must be https://www.youtube.com/results?search_query=URL_ENCODED_QUERY (never invent video IDs)
- Official docs: use only well-known root doc URLs (e.g. https://react.dev, https://docs.python.org/3/)
- Include at least: 1 YouTube, 1 official docs, 1 free platform (freeCodeCamp/roadmap.sh/MDN/The Odin Project), 1 practice site
- Each resource must be directly relevant to the topic

"repos": array of exactly 3 real GitHub repos. Rules:
- Only include repos you are highly confident exist at https://github.com/OWNER/REPO
- Each repo must be genuinely useful for LEARNING or BUILDING a project on this specific topic
- Mix: 1 "study the source" repo (popular library/framework), 1 "starter/boilerplate" repo, 1 "awesome list" or "project ideas" repo

Return ONLY the JSON object, no markdown fences, no commentary:
{{
  "resources": [
    {{"type": "youtube|docs|article|practice|course", "title": "...", "url": "...", "description": "one sentence"}},
    ...
  ],
  "repos": [
    {{"name": "owner/repo", "url": "https://github.com/owner/repo", "description": "what this repo is", "stars": "~Xk", "why": "why useful for this topic"}},
    ...
  ]
}}"""


def get_resources(topic: str, skill: str, role: str) -> dict:
    """Return curated resources + GitHub repos for a roadmap topic.

    Returns:
        dict with keys:
            resources: list[dict]  — {type, title, url, description}
            repos:     list[dict]  — {name, url, description, stars, why}
    """
    prompt = _PROMPT.format(
        topic=topic[:300],
        skill=skill[:100],
        role=role[:100],
    )

    try:
        client = boto3.client("bedrock-runtime", region_name=_REGION)
        body = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "inferenceConfig": {"maxTokens": 1500, "temperature": 0.2},
        })
        resp = client.invoke_model(
            modelId=_BEDROCK_MODEL, body=body,
            contentType="application/json", accept="application/json",
        )
        raw  = json.loads(resp["body"].read())
        text = raw["output"]["message"]["content"][0]["text"].strip()

        # Strip markdown fences if present
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM returned non-dict")

        resources = _clean_resources(payload.get("resources", []), topic)
        repos     = _clean_repos(payload.get("repos", []))
        return {"resources": resources, "repos": repos}

    except Exception as exc:
        logger.warning("resources_engine failed for '%s': %s", topic, exc)
        return {"resources": _fallback_resources(topic, skill), "repos": _fallback_repos(skill)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_resources(raw: list, topic: str) -> list[dict]:
    cleaned = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        url = r.get("url", "")
        if "youtube.com/watch" in url:
            q = urllib.parse.quote_plus(r.get("title", topic))
            url = f"https://www.youtube.com/results?search_query={q}"
        cleaned.append({
            "type":        r.get("type", "article"),
            "title":       r.get("title", ""),
            "url":         url,
            "description": r.get("description", ""),
        })
    return cleaned


def _clean_repos(raw: list) -> list[dict]:
    cleaned = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = r.get("name", "")
        url  = r.get("url", "") or (f"https://github.com/{name}" if name else "")
        if not url.startswith("https://github.com/"):
            continue
        cleaned.append({
            "name":        name,
            "url":         url,
            "description": r.get("description", ""),
            "stars":       r.get("stars", ""),
            "why":         r.get("why", ""),
        })
    return cleaned


def _fallback_resources(topic: str, skill: str) -> list[dict]:
    q = urllib.parse.quote_plus(f"{skill} {topic}")
    return [
        {"type": "youtube",  "title": f"YouTube: {skill} – {topic}", "url": f"https://www.youtube.com/results?search_query={q}", "description": "Search YouTube for tutorials on this topic."},
        {"type": "article",  "title": f"Google: {skill} {topic}",    "url": f"https://www.google.com/search?q={q}",              "description": "Search Google for articles and guides."},
        {"type": "practice", "title": "roadmap.sh",                   "url": "https://roadmap.sh",                                "description": "Interactive roadmaps and learning paths."},
    ]


def _fallback_repos(skill: str) -> list[dict]:
    q = urllib.parse.quote_plus(skill)
    return [
        {"name": f"Search: {skill}", "url": f"https://github.com/search?q={q}&type=repositories&sort=stars", "description": f"Top GitHub repos for {skill}", "stars": "—", "why": "Browse the most-starred repos to find projects to study."},
    ]
