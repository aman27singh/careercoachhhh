"""
Embedding Service
=================
Semantic skill intelligence using Amazon Bedrock Titan Embeddings.

Replaces the OpenSearch / Vector DB component in the architecture diagram
with a lightweight, cost-effective alternative:
  - Embeddings via Bedrock ``amazon.titan-embed-text-v1``
  - In-process cosine similarity (no external vector DB needed)
  - Embedding cache persisted to S3 (config/skill_embeddings.json)
    to avoid repeated Bedrock calls on cold starts

Public API
----------
    embed_text(text)                          -> list[float]
    cosine_similarity(a, b)                   -> float  (0-1)
    rerank_skills_with_embeddings(            -> list[dict]
        skills, role, base_scores, weight)

Usage in the agentic loop
--------------------------
After task evaluation, ``skill_impact_engine`` re-computes scores.
``rerank_skills_with_embeddings`` is then called to blend the keyword-based
scores with semantic similarity to the target role — giving a richer,
LLM-informed re-ranking signal.
"""
from __future__ import annotations

import json
import logging
import math
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_REGION   = os.getenv("AWS_REGION", "us-east-1")
_BUCKET   = os.getenv("CAREEROS_RESUME_BUCKET", "careeros-resumes-985090322407")
_S3_KEY   = "config/skill_embeddings.json"
_MODEL_ID = "amazon.titan-embed-text-v1"

# ── In-process cache ──────────────────────────────────────────────────────────
_cache: dict[str, list[float]] = {}
_cache_loaded = False
_dirty = False   # True when new embeddings need to be persisted back to S3


# ── AWS clients ───────────────────────────────────────────────────────────────
def _bedrock():
    return boto3.client("bedrock-runtime", region_name=_REGION)


def _s3():
    return boto3.client("s3", region_name=_REGION)


# ── Cache helpers ─────────────────────────────────────────────────────────────
def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    try:
        resp = _s3().get_object(Bucket=_BUCKET, Key=_S3_KEY)
        _cache = json.loads(resp["Body"].read().decode())
        logger.info("Embedding cache loaded: %d entries", len(_cache))
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("NoSuchKey", "NoSuchBucket", "AccessDenied"):
            logger.info("No embedding cache in S3 — starting fresh (%s)", code)
        else:
            logger.warning("S3 embedding cache load error: %s", exc)
    except Exception as exc:
        logger.warning("Unexpected error loading embedding cache: %s", exc)
    finally:
        _cache_loaded = True


def _flush_cache() -> None:
    global _dirty
    if not _dirty:
        return
    try:
        _s3().put_object(
            Bucket=_BUCKET,
            Key=_S3_KEY,
            Body=json.dumps(_cache).encode(),
            ContentType="application/json",
        )
        _dirty = False
        logger.info("Embedding cache flushed to S3: %d entries", len(_cache))
    except Exception as exc:
        logger.warning("Failed to flush embedding cache to S3: %s", exc)


# ── Core functions ────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Return a 1536-dim embedding vector for *text*.

    Results are cached in memory and persisted to S3 to minimise
    Bedrock API calls across Lambda invocations.
    """
    global _dirty
    _load_cache()

    key = text.strip().lower()[:256]   # normalise cache key
    if key in _cache:
        return _cache[key]

    try:
        resp = _bedrock().invoke_model(
            modelId=_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text[:8000]}),
        )
        vec: list[float] = json.loads(resp["body"].read())["embedding"]
        _cache[key] = vec
        _dirty = True
        _flush_cache()   # best-effort persist
        return vec
    except Exception as exc:
        logger.warning("Bedrock embed failed for '%s': %s", text[:60], exc)
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity ∈ [0, 1] between two non-zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    return dot / (mag_a * mag_b) if (mag_a and mag_b) else 0.0


def rerank_skills_with_embeddings(
    skills: list[str],
    role: str,
    base_scores: dict[str, float],
    embed_weight: float = 0.25,
) -> list[dict]:
    """Blend keyword impact scores with semantic similarity to the target role.

    Args:
        skills:       Skill names to rank (gaps for the user).
        role:         Target job role (used as the semantic anchor).
        base_scores:  {skill: 0-100 score} from ``skill_impact_engine``.
        embed_weight: Fraction of score from embeddings (default 0.25).

    Returns:
        List of dicts sorted descending by ``final_score``::

            [{"skill": str, "base_score": float,
              "embed_score": float, "final_score": float}, ...]
    """
    role_anchor = f"Required skills and expertise for a {role} position"
    role_vec = embed_text(role_anchor)

    results: list[dict] = []
    for skill in skills:
        base  = float(base_scores.get(skill, 0.0))
        embed = 0.0

        if role_vec:
            try:
                skill_vec = embed_text(f"{skill} programming skill for software engineering")
                embed = cosine_similarity(skill_vec, role_vec) * 100
            except Exception:
                embed = base   # fallback to base if embedding fails

        final = round((1.0 - embed_weight) * base + embed_weight * embed, 1)
        results.append({
            "skill":       skill,
            "base_score":  round(base, 1),
            "embed_score": round(embed, 1),
            "final_score": final,
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results
