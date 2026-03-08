"""
LLM Service
===========
Single entry-point for all LLM calls in CareerCoach.
Backed by Amazon Bedrock (Amazon Nova Pro via Converse API).

Uses the Converse API which works with Amazon's own models without
requiring the Anthropic use case form.

All agents import and call ask_llm(prompt) — no other module
should interact with Bedrock or any LLM client directly.

Retry behaviour
---------------
Transient Bedrock errors (throttling, service unavailable) are
retried up to _MAX_RETRIES times with exponential back-off starting
at _RETRY_BASE_DELAY seconds.
"""
from __future__ import annotations

import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Amazon Nova Pro — Amazon's own model, no Anthropic use case form needed.
# Uses the Bedrock Converse API (works uniformly across all Bedrock models).
_MODEL_ID = "amazon.nova-pro-v1:0"
_REGION: str = os.getenv("AWS_REGION", "us-east-1")

# Retry configuration
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0   # seconds; doubles each attempt

# Bedrock error codes that are safe to retry
_RETRYABLE_CODES: frozenset[str] = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelStreamErrorException",
        "RequestTimeout",
    }
)

# The Bedrock runtime client is created once at import time.
# Credentials are resolved from the standard boto3 chain:
# env vars → ~/.aws/credentials → IAM instance profile.
_client = boto3.client("bedrock-runtime", region_name=_REGION)


def ask_llm(prompt: str) -> str:
    """Send *prompt* to Amazon Nova Pro on Bedrock and return the text reply.

    Uses the Converse API for clean cross-model compatibility.
    Retries up to _MAX_RETRIES times on transient Bedrock errors, using
    exponential back-off.  Logs the total invocation wall-clock time.

    Args:
        prompt: Plain-text prompt string.

    Returns:
        The model's text response as a single string.

    Raises:
        Exception: Re-raises the last error after all retries are exhausted,
                   so callers can apply their own fallback logic.
    """
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    inference_config = {"maxTokens": 2000}

    last_exc: Exception | None = None
    t_start = time.monotonic()

    for attempt in range(1, _MAX_RETRIES + 2):   # attempts: 1 … _MAX_RETRIES+1
        try:
            response = _client.converse(
                modelId=_MODEL_ID,
                messages=messages,
                inferenceConfig=inference_config,
            )

            text = response["output"]["message"]["content"][0]["text"]

            elapsed = time.monotonic() - t_start
            logger.info(
                "Bedrock converse succeeded — model=%s attempt=%d elapsed=%.2fs",
                _MODEL_ID,
                attempt,
                elapsed,
            )
            return text.strip()

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in _RETRYABLE_CODES and attempt <= _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Bedrock transient error '%s' on attempt %d — retrying in %.1fs…",
                    error_code,
                    attempt,
                    delay,
                )
                time.sleep(delay)
                last_exc = exc
                continue
            # Non-retryable or retries exhausted
            elapsed = time.monotonic() - t_start
            logger.error(
                "Bedrock converse failed — model=%s attempt=%d elapsed=%.2fs error=%s",
                _MODEL_ID,
                attempt,
                elapsed,
                exc,
            )
            raise

        except Exception as exc:
            elapsed = time.monotonic() - t_start
            logger.error(
                "Bedrock converse unexpected error — model=%s attempt=%d elapsed=%.2fs error=%s",
                _MODEL_ID,
                attempt,
                elapsed,
                exc,
            )
            raise

    # All retries exhausted for a retryable error
    elapsed = time.monotonic() - t_start
    logger.error(
        "Bedrock converse failed after %d attempts — elapsed=%.2fs",
        _MAX_RETRIES + 1,
        elapsed,
    )
    raise last_exc  # type: ignore[misc]
