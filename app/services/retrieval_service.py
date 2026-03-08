"""
Retrieval Service
=================
Queries an Amazon OpenSearch Serverless vector index to retrieve
semantically relevant context documents for a given query.

Public interface
----------------
    retrieve_context(query: str) -> list[str]

Configuration (environment variables)
--------------------------------------
    OPENSEARCH_ENDPOINT      Full HTTPS endpoint of the OpenSearch Serverless
                             collection, e.g.
                             https://<id>.us-east-1.aoss.amazonaws.com
    OPENSEARCH_INDEX         Target index name.  Default: "careercoach-docs"
    OPENSEARCH_VECTOR_FIELD  Name of the kNN vector field.  Default: "embedding"
    OPENSEARCH_TEXT_FIELD    Name of the field that holds the document text.
                             Default: "text"
    AWS_REGION               AWS region.  Default: "us-east-1"

AWS credentials are resolved from the standard boto3 chain
(env vars → ~/.aws/credentials → IAM instance profile).

The query is embedded with Amazon Titan Text Embeddings v2 via Bedrock before
being sent as a kNN search to OpenSearch Serverless.
"""
from __future__ import annotations

import json
import logging
import os

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, exceptions as os_exceptions
from requests_aws4auth import AWS4Auth

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REGION: str = os.getenv("AWS_REGION", "us-east-1")
_ENDPOINT: str = os.getenv("OPENSEARCH_ENDPOINT", "")
_INDEX: str = os.getenv("OPENSEARCH_INDEX", "careercoach-docs")
_VECTOR_FIELD: str = os.getenv("OPENSEARCH_VECTOR_FIELD", "embedding")
_TEXT_FIELD: str = os.getenv("OPENSEARCH_TEXT_FIELD", "text")
_TOP_K: int = 5

# Bedrock Titan Embeddings v2 — 1 024-dimensional dense vectors
_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"

def _get_os_client() -> OpenSearch:
    """Build an OpenSearch client pointed at the configured Serverless endpoint."""
    if not _ENDPOINT:
        raise EnvironmentError(
            "OPENSEARCH_ENDPOINT is not set. "
            "Export the full HTTPS URL of your OpenSearch Serverless collection."
        )

    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise EnvironmentError("No AWS credentials found. Configure AWS credentials before using retrieval.")

    frozen = credentials.get_frozen_credentials()
    awsauth = AWS4Auth(
        frozen.access_key,
        frozen.secret_key,
        _REGION,
        "aoss",
        session_token=frozen.token,
    )

    host = _ENDPOINT.rstrip("/").removeprefix("https://")

    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float]:
    """Convert *text* to a dense embedding vector using Bedrock Titan Embeddings v2.

    Args:
        text: The query or document text to embed.

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        Exception: Propagates boto3 errors so the caller can handle them.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=_REGION)
    body = json.dumps({"inputText": text})
    response = bedrock.invoke_model(
        modelId=_EMBED_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def retrieve_context(query: str) -> list[str]:
    """Perform a vector similarity search and return the top matching documents.

    Args:
        query: Natural-language query string (e.g. a skill name or question).

    Returns:
        A list of up to 5 document text strings ranked by similarity to the
        query.  Returns an empty list if the search fails or the index is
        empty.
    """
    try:
        query_vector = _embed(query)
    except Exception as exc:
        logger.error("Failed to embed query '%s': %s", query, exc)
        return []

    knn_query = {
        "size": _TOP_K,
        "_source": [_TEXT_FIELD],
        "query": {
            "knn": {
                _VECTOR_FIELD: {
                    "vector": query_vector,
                    "k": _TOP_K,
                }
            }
        },
    }

    try:
        client = _get_os_client()
        response = client.search(index=_INDEX, body=knn_query)
    except os_exceptions.NotFoundError:
        logger.warning("OpenSearch index '%s' not found.", _INDEX)
        return []
    except Exception as exc:
        logger.error("OpenSearch query failed: %s", exc)
        return []

    hits: list[dict] = response.get("hits", {}).get("hits", [])
    documents: list[str] = [
        hit["_source"].get(_TEXT_FIELD, "")
        for hit in hits
        if hit.get("_source", {}).get(_TEXT_FIELD)
    ]

    logger.debug(
        "retrieve_context: query=%r  hits=%d  returned=%d",
        query,
        len(hits),
        len(documents),
    )
    return documents
