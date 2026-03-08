"""
GitHub Intelligence Service
============================
Deep analysis of a developer's GitHub profile beyond just repo count and
languages — extracts real signals of implementation depth, commit cadence,
framework usage, project complexity and code quality indicators.

This replaces the basic analyze_github() in profile_engine with a multi-signal
analysis that feeds into mastery level estimation.

GitHub API endpoints used (all public, no token required for up to 60 req/hr):
  GET /users/{username}
  GET /users/{username}/repos?per_page=100&sort=pushed
  (individual repo language breakdown already available in repo metadata)

With GITHUB_TOKEN env var set → 5,000 req/hr (recommended for production).
"""
from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict

import requests

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_TOKEN: str | None = os.getenv("GITHUB_TOKEN")

# Framework/tool detection: patterns found in repo names, descriptions, topics
_FRAMEWORK_SIGNALS: dict[str, list[str]] = {
    "react":        ["react", "next.js", "nextjs", "vite", "create-react"],
    "vue":          ["vue", "nuxt"],
    "angular":      ["angular", "ng-"],
    "node":         ["nodejs", "express", "nest", "nestjs", "hapi"],
    "fastapi":      ["fastapi", "fast-api"],
    "django":       ["django"],
    "flask":        ["flask"],
    "spring":       ["spring", "springboot"],
    "docker":       ["docker", "dockerfile", "compose"],
    "kubernetes":   ["kubernetes", "k8s", "helm"],
    "aws":          ["aws", "lambda", "cdk", "terraform", "serverless"],
    "tensorflow":   ["tensorflow", "keras", "deep-learning", "neural"],
    "pytorch":      ["pytorch", "torch"],
    "machine learning": ["ml-", "-ml", "machine-learning", "sklearn", "scikit"],
    "sql":          ["postgres", "mysql", "sqlite", "supabase", "prisma"],
    "mongodb":      ["mongo", "mongoose"],
    "redis":        ["redis", "cache"],
    "graphql":      ["graphql", "apollo"],
    "rust":         ["rust", "cargo"],
    "go":           ["golang", "go-"],
}

# Language name normalisation → canonical form
_LANG_MAP: dict[str, str] = {
    "JavaScript": "javascript",
    "TypeScript": "javascript",   # counts as JS skill
    "Python":     "python",
    "Java":       "java",
    "C++":        "c++",
    "C#":         "c#",
    "Go":         "go",
    "Rust":       "rust",
    "Ruby":       "ruby",
    "PHP":        "php",
    "Swift":      "swift",
    "Kotlin":     "kotlin",
    "Dart":       "dart",
    "Shell":      "bash",
    "HTML":       None,   # not a skill we track
    "CSS":        None,
}


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if _TOKEN:
        h["Authorization"] = f"Bearer {_TOKEN}"
    return h


def _get(url: str, params: dict | None = None) -> dict | list | None:
    """Fetch a GitHub API URL. Returns None on any error."""
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403:
            logger.warning("GitHub API rate limit hit or forbidden: %s", url)
        elif resp.status_code == 404:
            logger.info("GitHub resource not found: %s", url)
        else:
            logger.warning("GitHub API %d for %s", resp.status_code, url)
    except requests.RequestException as exc:
        logger.warning("GitHub API request failed: %s", exc)
    return None


def _detect_frameworks(repos: list[dict]) -> list[str]:
    """Detect frameworks/tools from repo names, descriptions, and topics."""
    found: set[str] = set()
    for repo in repos:
        text = " ".join(filter(None, [
            (repo.get("name") or "").lower(),
            (repo.get("description") or "").lower(),
            " ".join(repo.get("topics") or []),
        ]))
        for framework, signals in _FRAMEWORK_SIGNALS.items():
            if any(signal in text for signal in signals):
                found.add(framework)
    return sorted(found)


def _compute_activity_score(repos: list[dict], user_info: dict) -> dict:
    """Compute activity signals: commit cadence proxy, contribution volume."""
    # Proxy for commit history: total stars received & fork count indicate impact
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)
    total_forks = sum(r.get("forks_count", 0) for r in repos)
    original_repos = [r for r in repos if not r.get("fork")]
    repos_with_description = sum(1 for r in original_repos if r.get("description"))

    # Public contributions from user profile
    public_gists = user_info.get("public_gists", 0) if user_info else 0
    followers    = user_info.get("followers", 0) if user_info else 0

    # Quality signal: % of repos that have a description (proxy for care taken)
    description_ratio = (
        repos_with_description / len(original_repos) if original_repos else 0
    )

    return {
        "total_stars":         total_stars,
        "total_forks":         total_forks,
        "original_repo_count": len(original_repos),
        "public_gists":        public_gists,
        "followers":           followers,
        "description_ratio":   round(description_ratio, 2),
    }


def _estimate_mastery_signals(
    language_breakdown: dict[str, int],
    detected_frameworks: list[str],
    activity: dict,
) -> dict[str, float]:
    """Produce a mastery signal (0–1) per detected skill.

    Not a definitive mastery score—used as input to mastery_tracker to
    determine starting mastery level when no task/verification data exists.

    Scale:
        0.0–0.3  → basic exposure (1–3 repos in this language)
        0.3–0.6  → practitioner (4–10 repos or framework detected)
        0.6–0.9  → proficient (10+ repos AND framework detected)
        0.9–1.0  → demonstrated expertise (stars / forks / followers signal)
    """
    signals: dict[str, float] = {}

    total_repos = sum(language_breakdown.values()) or 1

    for lang_raw, count in language_breakdown.items():
        canonical = _LANG_MAP.get(lang_raw, lang_raw.lower())
        if canonical is None:
            continue
        share = count / total_repos
        base  = min(0.9, share * 2 + (count / 20))   # repo-count based baseline
        # Boost if popular framework detected for this language
        boost = 0.15 if canonical in detected_frameworks else 0.0
        # Star/fork boost (mild)
        reputation_boost = min(0.10, (activity["total_stars"] / 100) * 0.1)
        signals[canonical] = min(1.0, round(base + boost + reputation_boost, 3))

    # Frameworks detected but not the primary language
    for fw in detected_frameworks:
        if fw not in signals:
            signals[fw] = 0.3   # at least some exposure

    return signals


def analyze_github_deep(username: str | None) -> dict:
    """Deep GitHub profile analysis.

    Args:
        username: GitHub handle.  Returns empty result if None.

    Returns:
        Dict with keys:
            repo_count, primary_languages, language_breakdown,
            detected_frameworks, activity, mastery_signals,
            original_repo_count, account_age_days (if available)
    """
    if not username:
        return {
            "repo_count": 0,
            "primary_languages": [],
            "language_breakdown": {},
            "detected_frameworks": [],
            "activity": {},
            "mastery_signals": {},
        }

    username = username.strip().lstrip("@")
    # Strip full GitHub URL if pasted
    if "github.com/" in username:
        username = username.rstrip("/").split("github.com/")[-1].split("/")[0]

    logger.info("Starting deep GitHub analysis for user: %s", username)

    # ── 1. User profile ────────────────────────────────────────────────────
    user_info = _get(f"{_GITHUB_API}/users/{username}") or {}

    # ── 2. Repositories (up to 100, sorted by last push) ──────────────────
    repos = _get(
        f"{_GITHUB_API}/users/{username}/repos",
        params={"per_page": 100, "sort": "pushed", "type": "owner"},
    ) or []

    if not isinstance(repos, list):
        repos = []

    # ── 3. Language breakdown ──────────────────────────────────────────────
    lang_counter: Counter = Counter()
    for repo in repos:
        lang = repo.get("language")
        if lang:
            lang_counter[lang] += 1

    language_breakdown = dict(lang_counter.most_common(10))
    primary_languages  = [_LANG_MAP.get(l, l.lower()) for l, _ in lang_counter.most_common(3) if _LANG_MAP.get(l, l.lower())]

    # ── 4. Framework detection ─────────────────────────────────────────────
    detected_frameworks = _detect_frameworks(repos)

    # ── 5. Activity signals ────────────────────────────────────────────────
    activity = _compute_activity_score(repos, user_info)

    # ── 6. Mastery signals ─────────────────────────────────────────────────
    mastery_signals = _estimate_mastery_signals(
        language_breakdown, detected_frameworks, activity
    )

    result = {
        "repo_count":          len(repos),
        "primary_languages":   primary_languages,
        "language_breakdown":  language_breakdown,
        "detected_frameworks": detected_frameworks,
        "activity":            activity,
        "mastery_signals":     mastery_signals,
    }

    logger.info(
        "GitHub analysis complete for %s: %d repos, languages=%s, frameworks=%s",
        username,
        len(repos),
        primary_languages,
        detected_frameworks,
    )
    return result
