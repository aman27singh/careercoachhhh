#!/usr/bin/env python3
"""
scripts/index_documents.py
==========================
Indexes project documents into an Amazon OpenSearch Serverless vector index
so they can be retrieved by ``app/services/retrieval_service.py``.

What it does
------------
1. Discovers JSON files from ``app/data/`` (and any extra paths supplied on
   the command line).
2. Converts each file into one or more plain-text documents with metadata.
3. Generates a 1 024-dim embedding for every document using Amazon Bedrock
   Titan Text Embeddings v2.
4. Bulk-inserts batches of ``{text, embedding, metadata}`` documents into
   the target OpenSearch Serverless index, creating the index (with the
   correct kNN mapping) if it does not already exist.

Usage
-----
    # From the project root:
    python scripts/index_documents.py

    # Index extra JSON files, larger batches, verbose output:
    python scripts/index_documents.py \\
        --extra-files path/to/extra.json \\
        --batch-size 50 \\
        --verbose

    # Preview documents without touching AWS:
    python scripts/index_documents.py --dry-run

Configuration (environment variables)
--------------------------------------
    OPENSEARCH_ENDPOINT      Full HTTPS URL of the OpenSearch Serverless
                             collection (required unless --dry-run).
                             e.g. https://<id>.us-east-1.aoss.amazonaws.com
    OPENSEARCH_INDEX         Index name.  Default: careercoach-docs
    OPENSEARCH_VECTOR_FIELD  kNN vector field name.  Default: embedding
    OPENSEARCH_TEXT_FIELD    Text field name.  Default: text
    AWS_REGION               AWS region.  Default: us-east-1

AWS credentials are resolved from the standard boto3 chain
(env vars → ~/.aws/credentials → IAM instance profile).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Iterator

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.helpers import bulk
from requests_aws4auth import AWS4Auth

# ---------------------------------------------------------------------------
# Project root on sys.path so ``app/`` is importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("index_documents")

# ---------------------------------------------------------------------------
# Configuration (mirrors retrieval_service.py)
# ---------------------------------------------------------------------------
_REGION: str = os.getenv("AWS_REGION", "us-east-1")
_ENDPOINT: str = os.getenv("OPENSEARCH_ENDPOINT", "")
_INDEX: str = os.getenv("OPENSEARCH_INDEX", "careercoach-docs")
_VECTOR_FIELD: str = os.getenv("OPENSEARCH_VECTOR_FIELD", "embedding")
_TEXT_FIELD: str = os.getenv("OPENSEARCH_TEXT_FIELD", "text")

_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
_EMBEDDING_DIMENSION = 1024
_DEFAULT_BATCH_SIZE = 25

# Well-known data files inside the project
_DATA_DIR = _PROJECT_ROOT / "app" / "data"

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------

def _make_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=_REGION)


def _make_os_client() -> OpenSearch:
    """Build a signed OpenSearch client for Serverless (SigV4, service=aoss)."""
    if not _ENDPOINT:
        raise EnvironmentError(
            "OPENSEARCH_ENDPOINT is not set. "
            "Export the full HTTPS URL of your OpenSearch Serverless collection "
            "before running this script."
        )

    host = _ENDPOINT.rstrip("/").removeprefix("https://")

    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise EnvironmentError(
            "No AWS credentials found. Configure credentials before indexing."
        )
    frozen = credentials.get_frozen_credentials()
    awsauth = AWS4Auth(
        frozen.access_key,
        frozen.secret_key,
        _REGION,
        "aoss",
        session_token=frozen.token,
    )

    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=60,
        retry_on_timeout=True,
        max_retries=3,
    )

# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

_INDEX_MAPPING = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 512,
        }
    },
    "mappings": {
        "properties": {
            _TEXT_FIELD: {"type": "text"},
            _VECTOR_FIELD: {
                "type": "knn_vector",
                "dimension": _EMBEDDING_DIMENSION,
                "method": {
                    "name": "hnsw",
                    "space_type": "l2",
                    "engine": "nmslib",
                },
            },
            "metadata": {"type": "object", "dynamic": True},
        }
    },
}


def ensure_index(client: OpenSearch, recreate: bool = False) -> None:
    """Create the kNN index if it does not exist (or recreate it on request)."""
    exists = client.indices.exists(index=_INDEX)

    if exists and recreate:
        logger.info("Deleting existing index '%s'…", _INDEX)
        client.indices.delete(index=_INDEX)
        exists = False

    if not exists:
        logger.info("Creating index '%s' with kNN mapping…", _INDEX)
        client.indices.create(index=_INDEX, body=_INDEX_MAPPING)
        logger.info("Index created.")
    else:
        logger.info("Index '%s' already exists — skipping creation.", _INDEX)

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed(text: str, bedrock_client) -> list[float]:
    """Embed *text* with Bedrock Titan v2 → 1 024-dim float vector."""
    body = json.dumps({"inputText": text})
    response = bedrock_client.invoke_model(
        modelId=_EMBED_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]

# ---------------------------------------------------------------------------
# Document loaders
# ---------------------------------------------------------------------------

def load_market_skills(path: Path) -> list[dict]:
    """
    Convert market_skills.json into indexable documents.

    Produces two document types per role:
      • One **role summary** listing all required skills and their market
        frequency.
      • One **skill entry** per (role, skill) pair so individual skills are
        also retrievable.
    """
    with open(path) as fh:
        data: dict = json.load(fh)

    docs: list[dict] = []

    for role, skills in data.items():
        # --- role summary document ---
        skill_lines = ", ".join(
            f"{skill} ({round(freq * 100, 1)}%)"
            for skill, freq in sorted(skills.items(), key=lambda x: x[1], reverse=True)
        )
        docs.append(
            {
                "text": (
                    f"Role: {role}. "
                    f"Required skills and market frequency: {skill_lines}."
                ),
                "metadata": {
                    "source": path.name,
                    "doc_type": "role_summary",
                    "role": role,
                },
            }
        )

        # --- per-skill documents ---
        for skill, frequency in skills.items():
            pct = round(frequency * 100, 1)
            docs.append(
                {
                    "text": (
                        f"{skill} is required for the {role} role "
                        f"and appears in {pct}% of job postings."
                    ),
                    "metadata": {
                        "source": path.name,
                        "doc_type": "role_skill",
                        "role": role,
                        "skill": skill,
                        "frequency": frequency,
                    },
                }
            )

    logger.info("market_skills loader → %d documents from '%s'", len(docs), path.name)
    return docs


def load_user_profile(path: Path) -> list[dict]:
    """Convert a user profile JSON into a single summary document."""
    with open(path) as fh:
        data: dict = json.load(fh)

    user_id = data.get("user_id", path.stem)
    rank = data.get("rank", "unknown")
    level = data.get("level", 1)
    xp = data.get("xp", 0)
    streak = data.get("streak", 0)

    skill_dist = data.get("skill_distribution", {})
    skill_summary = ", ".join(
        f"{area} {score}%" for area, score in skill_dist.items()
    )

    knowledge = data.get("knowledge_map", [])
    knowledge_summary = ", ".join(
        f"{k['name']} {k['value']}%" for k in knowledge if "name" in k
    )

    text = (
        f"User {user_id} is at Level {level}, Rank {rank}, with {xp} XP "
        f"and a {streak}-day streak. "
        f"Skill distribution: {skill_summary}. "
        f"Knowledge map: {knowledge_summary}."
    )

    docs = [
        {
            "text": text,
            "metadata": {
                "source": path.name,
                "doc_type": "user_profile",
                "user_id": user_id,
                "level": level,
                "rank": rank,
            },
        }
    ]

    logger.info("user_profile loader → %d document from '%s'", len(docs), path.name)
    return docs


def load_generic_json(path: Path) -> list[dict]:
    """
    Generic fallback for arbitrary JSON files.

    Handles three shapes:
      • List of objects  → one document per object (``str(obj)`` as text).
      • Dict of dicts    → one document per top-level key.
      • Anything else    → one document for the whole file.
    """
    with open(path) as fh:
        data = json.load(fh)

    docs: list[dict] = []

    if isinstance(data, list):
        for i, item in enumerate(data):
            docs.append(
                {
                    "text": json.dumps(item, ensure_ascii=False),
                    "metadata": {
                        "source": path.name,
                        "doc_type": "generic_list_item",
                        "index": i,
                    },
                }
            )
    elif isinstance(data, dict):
        for key, value in data.items():
            docs.append(
                {
                    "text": f"{key}: {json.dumps(value, ensure_ascii=False)}",
                    "metadata": {
                        "source": path.name,
                        "doc_type": "generic_dict_entry",
                        "key": str(key),
                    },
                }
            )
    else:
        docs.append(
            {
                "text": json.dumps(data, ensure_ascii=False),
                "metadata": {"source": path.name, "doc_type": "generic"},
            }
        )

    logger.info("generic loader → %d documents from '%s'", len(docs), path.name)
    return docs


def load_learning_resources(path: Path) -> list[dict]:
    """
    Convert learning_resources.json into richly indexed documents.

    For each topic entry the loader produces:
      1. A **summary** document combining the title, description, tools, and
         a condensed list of key concepts — best for broad topic queries.
      2. One **concept** document per key-concept entry — best for specific
         skill or technique queries.
      3. One **tips** document per entry — surface practical advice.
    """
    with open(path) as fh:
        entries: list[dict] = json.load(fh)

    docs: list[dict] = []

    for entry in entries:
        title = entry.get("title", "Unknown")
        category = entry.get("category", "general")
        description = entry.get("description", "")
        key_concepts: list[str] = entry.get("key_concepts", [])
        tools: list[str] = entry.get("tools", [])
        tips: list[str] = entry.get("tips", [])

        base_meta = {
            "source": path.name,
            "category": category,
            "title": title,
        }

        # 1 — summary document
        concepts_summary = "; ".join(key_concepts[:5])  # first 5 for brevity
        tools_text = ", ".join(tools) if tools else "various"
        docs.append({
            "text": (
                f"{title}. {description} "
                f"Key concepts include: {concepts_summary}. "
                f"Common tools: {tools_text}."
            ),
            "metadata": {**base_meta, "doc_type": "learning_summary"},
        })

        # 2 — one document per key concept
        for concept in key_concepts:
            docs.append({
                "text": f"{title} — {concept}",
                "metadata": {**base_meta, "doc_type": "learning_concept"},
            })

        # 3 — tips document (one per entry)
        if tips:
            docs.append({
                "text": (
                    f"{title} practical tips: "
                    + " ".join(f"{i+1}. {tip}" for i, tip in enumerate(tips))
                ),
                "metadata": {**base_meta, "doc_type": "learning_tips"},
            })

    logger.info(
        "learning_resources loader → %d documents from '%s'", len(docs), path.name
    )
    return docs


# Map filename patterns to dedicated loaders
_LOADERS = {
    "market_skills.json": load_market_skills,
    "learning_resources.json": load_learning_resources,
}

_USER_PATTERN = "users/"  # path contains this → user profile loader


def load_file(path: Path) -> list[dict]:
    """Dispatch *path* to the appropriate loader."""
    if path.name in _LOADERS:
        return _LOADERS[path.name](path)
    if _USER_PATTERN in path.as_posix():
        return load_user_profile(path)
    return load_generic_json(path)


def discover_files(extra: list[Path]) -> list[Path]:
    """Return all JSON files to index (built-ins + any extras from CLI)."""
    found: list[Path] = []

    # Walk app/data/ recursively
    if _DATA_DIR.exists():
        found.extend(sorted(_DATA_DIR.rglob("*.json")))

    # Any extra paths passed on the command line
    for p in extra:
        resolved = p.resolve()
        if resolved not in found:
            found.append(resolved)

    return found

# ---------------------------------------------------------------------------
# Batch insert
# ---------------------------------------------------------------------------

def _doc_batches(
    docs: list[dict], size: int
) -> Iterator[list[dict]]:
    """Yield successive *size*-length slices of *docs*."""
    for start in range(0, len(docs), size):
        yield docs[start : start + size]


def bulk_index(
    os_client: OpenSearch,
    bedrock_client,
    docs: list[dict],
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Embed and bulk-insert all *docs*.

    Returns (indexed_count, error_count).
    """
    indexed = 0
    errors = 0
    total = len(docs)

    for batch_num, batch in enumerate(_doc_batches(docs, batch_size), start=1):
        logger.info(
            "Batch %d — embedding %d / %d documents…",
            batch_num,
            min(batch_num * batch_size, total),
            total,
        )

        actions: list[dict] = []
        for doc in batch:
            text = doc["text"]
            metadata = doc.get("metadata", {})

            if dry_run:
                logger.debug("[DRY RUN] Would embed: %s…", text[:80])
                continue

            try:
                embedding = embed(text, bedrock_client)
            except Exception as exc:
                logger.warning("Embedding failed for doc '%s…': %s", text[:60], exc)
                errors += 1
                continue

            actions.append(
                {
                    "_index": _INDEX,
                    "_id": str(uuid.uuid4()),
                    "_source": {
                        _TEXT_FIELD: text,
                        _VECTOR_FIELD: embedding,
                        "metadata": metadata,
                    },
                }
            )

        if dry_run or not actions:
            continue

        try:
            success, failed = bulk(os_client, actions, raise_on_error=False)
            indexed += success
            if failed:
                logger.warning("%d documents failed to index in this batch.", len(failed))
                errors += len(failed)
        except Exception as exc:
            logger.error("Bulk insert failed for batch %d: %s", batch_num, exc)
            errors += len(actions)

        # Brief pause to avoid overwhelming the collection with back-to-back batches
        time.sleep(0.2)

    return indexed, errors

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index CareerCoach documents into OpenSearch Serverless.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--extra-files",
        nargs="*",
        metavar="FILE",
        default=[],
        help="Additional JSON files to index on top of app/data/.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Documents per bulk request (default: {_DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--recreate-index",
        action="store_true",
        help="Delete and re-create the index before indexing (DESTRUCTIVE).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and log documents without calling AWS.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level output.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── 1. Discover files ────────────────────────────────────────────────
    extra_paths = [Path(f) for f in args.extra_files]
    files = discover_files(extra_paths)

    if not files:
        logger.error("No JSON files found under '%s'. Exiting.", _DATA_DIR)
        sys.exit(1)

    logger.info("Files to index: %s", [f.name for f in files])

    # ── 2. Load documents ────────────────────────────────────────────────
    all_docs: list[dict] = []
    for path in files:
        try:
            all_docs.extend(load_file(path))
        except Exception as exc:
            logger.error("Failed to load '%s': %s — skipping.", path, exc)

    if not all_docs:
        logger.error("No documents produced. Exiting.")
        sys.exit(1)

    logger.info("Total documents to index: %d", len(all_docs))

    if args.dry_run:
        logger.info("[DRY RUN] First 3 documents:")
        for doc in all_docs[:3]:
            logger.info("  text : %s", doc["text"][:120])
            logger.info("  meta : %s", doc["metadata"])
        logger.info("[DRY RUN] Skipping embedding and indexing.")
        return

    # ── 3. Build AWS clients ─────────────────────────────────────────────
    bedrock_client = _make_bedrock_client()
    os_client = _make_os_client()

    # ── 4. Ensure index exists ───────────────────────────────────────────
    ensure_index(os_client, recreate=args.recreate_index)

    # ── 5. Embed + bulk insert ───────────────────────────────────────────
    logger.info(
        "Starting indexing — %d documents, batch size %d…",
        len(all_docs),
        args.batch_size,
    )
    start_time = time.time()

    indexed, errors = bulk_index(
        os_client=os_client,
        bedrock_client=bedrock_client,
        docs=all_docs,
        batch_size=args.batch_size,
        dry_run=False,
    )

    elapsed = round(time.time() - start_time, 1)
    logger.info(
        "Done — %d indexed, %d errors, %.1fs elapsed.",
        indexed,
        errors,
        elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
