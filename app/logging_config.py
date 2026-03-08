"""Structured logging for CareerOS.

Behaviour
---------
* **Local / uvicorn**: plain `logging.basicConfig` with INFO level.
* **AWS Lambda**: JSON formatter + optional `watchtower` CloudWatch Logs handler
  (enabled when the ``CAREEROS_CW_LOG_GROUP`` env var is set).
  Lambda automatically routes stdout → CloudWatch, so watchtower is optional
  but gives us a dedicated log group with metric filters.

Environment variables
---------------------
CAREEROS_CW_LOG_GROUP    CloudWatch log group name.  When set, a watchtower
                         handler is added (requires ``watchtower`` package).
CAREEROS_CW_LOG_STREAM   Log stream name (default: Lambda function name or
                         "careeros-local").
AWS_REGION               AWS region used by watchtower (default: us-east-1).
LOG_LEVEL                Override log level (default: INFO).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


# ── JSON log formatter ─────────────────────────────────────────────────────────

class _JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level":     record.levelname,
            "logger":    record.name,
            "message":   record.getMessage(),
        }
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        # Include any extra fields attached with `logger.info("…", extra={…})`
        for key, val in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            } and not key.startswith("_"):
                obj[key] = val
        return json.dumps(obj, default=str)


# ── Public entry point ─────────────────────────────────────────────────────────

_configured = False


def configure_logging() -> None:
    """Configure root logger.  Idempotent — safe to call multiple times."""
    global _configured
    if _configured:
        return
    _configured = True

    level_name  = os.getenv("LOG_LEVEL", "INFO").upper()
    level       = getattr(logging, level_name, logging.INFO)
    cw_group    = os.getenv("CAREEROS_CW_LOG_GROUP", "")
    is_lambda   = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME", ""))

    root = logging.getLogger()
    root.setLevel(level)

    # ── Console handler ────────────────────────────────────────────────────
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)

    if is_lambda or cw_group:
        # JSON formatter for structured CloudWatch queries
        stdout_handler.setFormatter(_JSONFormatter())
    else:
        # Human-readable for local development
        stdout_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
        )

    root.addHandler(stdout_handler)

    # ── Optional watchtower CloudWatch Logs handler ────────────────────────
    if cw_group:
        _add_cloudwatch_handler(root, level, cw_group)

    logging.getLogger("uvicorn.access").propagate = False  # avoid duplicate lines
    logging.info(
        "Logging configured: level=%s  cw_group=%s  lambda=%s",
        level_name, cw_group or "(none)", is_lambda,
    )


def _add_cloudwatch_handler(root: logging.Logger, level: int, log_group: str) -> None:
    region     = os.getenv("AWS_REGION", "us-east-1")
    log_stream = os.getenv(
        "CAREEROS_CW_LOG_STREAM",
        os.getenv("AWS_LAMBDA_FUNCTION_NAME", "careeros-local"),
    )
    try:
        import watchtower
        import boto3
        cw_handler = watchtower.CloudWatchLogHandler(
            boto3_client=boto3.client("logs", region_name=region),
            log_group_name=log_group,
            log_stream_name=log_stream,
            create_log_group=True,
        )
        cw_handler.setLevel(level)
        cw_handler.setFormatter(_JSONFormatter())
        root.addHandler(cw_handler)
        logging.info("CloudWatch Logs handler attached: group=%s stream=%s", log_group, log_stream)
    except ImportError:
        logging.warning(
            "watchtower not installed — CloudWatch Logs handler skipped. "
            "Run: pip install watchtower"
        )
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to attach CloudWatch Logs handler: %s", exc)
