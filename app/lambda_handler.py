"""AWS Lambda entry point for CareerOS FastAPI application.

Wraps the FastAPI app with Mangum so it can be invoked by:
  - API Gateway HTTP API (v2)  ← recommended
  - API Gateway REST API (v1)
  - Lambda Function URLs

Local development
-----------------
Use uvicorn directly — this file is NOT imported locally:

    AWS_REGION=us-east-1 .venv/bin/uvicorn app.main:app --reload --port 8000

Deployment
----------
    bash deploy/deploy_backend.sh

Environment variables (Lambda)
------------------------------
AWS_REGION               Required — e.g. us-east-1
CAREEROS_RESUME_BUCKET   S3 bucket for resume storage
CAREEROS_CW_LOG_GROUP    CloudWatch log group (optional — Lambda logs anyway)
LOG_LEVEL                DEBUG / INFO / WARNING (default: INFO)
"""
from app.logging_config import configure_logging

# Configure structured logging before anything else is imported
configure_logging()

import logging  # noqa: E402
from mangum import Mangum  # noqa: E402
from app.main import app   # noqa: E402

_log = logging.getLogger(__name__)

# Mangum adapter — translates API Gateway events ↔ ASGI
_mangum = Mangum(app, lifespan="off")


def handler(event, context):
    """Entry point.

    Handles two event types:
    1. EventBridge scheduled events  →  run market refresh directly
    2. Everything else (API Gateway) →  delegate to Mangum / FastAPI
    """
    # EventBridge scheduled rule: {"source": "aws.events", "detail-type": "Scheduled Event"}
    if event.get("source") == "aws.events":
        _log.info("EventBridge scheduled trigger — running weekly market refresh")
        try:
            from app.services import market_service
            result = market_service.refresh_market_data(write=True)
            if result.get("roles_updated", 0) > 0:
                import app.services.role_engine as _re
                import app.services.skill_impact_engine as _sie
                _re.MARKET_DATA = market_service.get_market_data()
                _sie._market_data = None
            _log.info("Weekly market refresh complete: %s", result)
        except Exception as exc:
            _log.error("Weekly market refresh failed: %s", exc)
        return {"statusCode": 200, "body": "market refresh complete"}

    # Default: API Gateway / Function URL → Mangum
    return _mangum(event, context)
