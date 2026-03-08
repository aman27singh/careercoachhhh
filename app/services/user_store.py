"""
User Store
==========
DynamoDB-backed persistence for CareerCoach user state.

Table: careercoach-users
Partition key: user_id (S)

Each item shape:
    {
        "user_id":         "string",
        "xp":              Decimal (int),
        "level":           Decimal (int),
        "skills":          SS (string set) — optional, starts empty,
        "completed_tasks": SS (string set) — optional, starts empty,
        "streak":          Decimal (int),
    }

Public interface
----------------
    get_user(user_id: str) -> dict | None
    create_user(user_id: str) -> dict
    update_xp(user_id: str, amount: int) -> dict   # returns updated item
    add_completed_task(user_id: str, task_id: str) -> None

Configuration (environment variables)
--------------------------------------
    AWS_REGION               AWS region.             Default: us-east-1
    DYNAMODB_TABLE           DynamoDB table name.    Default: careercoach-users
    DYNAMODB_ENDPOINT_URL    Override endpoint URL   (optional, useful for local
                             DynamoDB via docker: http://localhost:8000)

All AWS credentials are resolved via the standard boto3 chain.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_REGION: str = os.getenv("AWS_REGION", "us-east-1")
_TABLE_NAME: str = os.getenv("DYNAMODB_TABLE", "careercoach-users")
_ENDPOINT_URL: str | None = os.getenv("DYNAMODB_ENDPOINT_URL")  # None → use AWS

# ---------------------------------------------------------------------------
# XP → Level mapping
# Each level requires 200 XP; level = (xp // 200) + 1, capped at 50.
# ---------------------------------------------------------------------------
_XP_PER_LEVEL: int = 200
_MAX_LEVEL: int = 50


def _xp_to_level(xp: int) -> int:
    return min(_MAX_LEVEL, (max(0, xp) // _XP_PER_LEVEL) + 1)


# ---------------------------------------------------------------------------
# DynamoDB resource (lazy singleton)
# ---------------------------------------------------------------------------
_table = None


def _get_table():
    global _table  # noqa: PLW0603
    if _table is None:
        kwargs: dict = {"region_name": _REGION}
        if _ENDPOINT_URL:
            kwargs["endpoint_url"] = _ENDPOINT_URL
        dynamodb = boto3.resource("dynamodb", **kwargs)
        _table = dynamodb.Table(_TABLE_NAME)
    return _table


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_user(user_id: str) -> dict | None:
    """Retrieve a user record by *user_id*.

    Returns the item as a plain dict (DynamoDB Decimals converted to int),
    or ``None`` if the user does not exist.
    """
    try:
        response = _get_table().get_item(Key={"user_id": user_id})
    except ClientError as exc:
        logger.error("DynamoDB get_item failed for user '%s': %s", user_id, exc)
        raise

    item = response.get("Item")
    if item is None:
        return None
    return _deserialise(item)


def create_user(user_id: str) -> dict:
    """Create a new user record with default values.

    Raises ``ValueError`` if the user already exists (conditional write).
    Returns the newly created user dict.
    """
    item = {
        "user_id": user_id,
        "xp": Decimal(0),
        "level": Decimal(1),
        "streak": Decimal(0),
        # DynamoDB does not allow empty SS attributes — omit skills/completed_tasks until populated
    }

    try:
        _get_table().put_item(
            Item=item,
            ConditionExpression=Attr("user_id").not_exists(),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError(f"User '{user_id}' already exists.") from exc
        logger.error("DynamoDB put_item failed for user '%s': %s", user_id, exc)
        raise

    logger.info("Created new user: %s", user_id)
    return _deserialise(item)


def update_xp(user_id: str, amount: int) -> dict:
    """Atomically add *amount* XP to *user_id* and recalculate level.

    The user record is created with ``create_user`` first if it does not exist.
    Returns the updated user dict.

    Args:
        user_id: Target user.
        amount:  XP delta (positive integer).

    Returns:
        Updated user record as a plain dict.
    """
    if amount <= 0:
        raise ValueError(f"XP amount must be positive, got {amount}.")

    # Ensure user exists
    if get_user(user_id) is None:
        create_user(user_id)

    try:
        response = _get_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="ADD xp :delta",
            ExpressionAttributeValues={":delta": Decimal(amount)},
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        logger.error("DynamoDB update_item (xp) failed for user '%s': %s", user_id, exc)
        raise

    attrs = response["Attributes"]
    new_xp = int(attrs.get("xp", 0))
    new_level = _xp_to_level(new_xp)

    # Update level if it changed
    try:
        _get_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET #lvl = :lvl",
            ExpressionAttributeNames={"#lvl": "level"},
            ExpressionAttributeValues={":lvl": Decimal(new_level)},
        )
    except ClientError as exc:
        logger.warning("Failed to sync level for user '%s': %s", user_id, exc)

    logger.info("Updated XP for user '%s': +%d XP → %d XP (level %d)", user_id, amount, new_xp, new_level)
    updated = _deserialise(attrs)
    updated["level"] = new_level
    return updated


def add_completed_task(user_id: str, task_id: str) -> None:
    """Add *task_id* to the user's ``completed_tasks`` string set.

    Creates the user record if it does not exist.
    No-op (idempotent) if *task_id* is already in the set.
    """
    # Ensure user exists
    if get_user(user_id) is None:
        create_user(user_id)

    try:
        _get_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="ADD completed_tasks :t",
            ExpressionAttributeValues={":t": {task_id}},
        )
    except ClientError as exc:
        logger.error(
            "DynamoDB update_item (completed_tasks) failed for user '%s': %s",
            user_id,
            exc,
        )
        raise

    logger.info("Recorded completed task '%s' for user '%s'.", task_id, user_id)


def add_verified_skill(user_id: str, skill: str) -> None:
    """Add *skill* to the user's ``skills`` string set (idempotent).

    Creates the user record if it does not exist.

    Args:
        user_id: Target user.
        skill:   Skill name as returned by the verification agent.
    """
    # Ensure user exists
    if get_user(user_id) is None:
        create_user(user_id)

    try:
        _get_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="ADD skills :s",
            ExpressionAttributeValues={":s": {skill}},
        )
    except ClientError as exc:
        logger.error(
            "DynamoDB update_item (skills) failed for user '%s': %s",
            user_id,
            exc,
        )
        raise

    logger.info("Verified skill '%s' stored for user '%s'.", skill, user_id)


def update_skill_xp(user_id: str, skill: str, amount: int) -> None:
    """Atomically increment skill-specific XP in the ``skill_xp`` map.

    DynamoDB stores ``skill_xp`` as a Map attribute:
        { "python": 120, "docker": 45, ... }

    Creates the user record if it does not exist.
    """
    if amount <= 0:
        return
    if get_user(user_id) is None:
        create_user(user_id)

    skill_key = skill.lower().strip()
    try:
        _get_table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="ADD skill_xp.#sk :delta",
            ExpressionAttributeNames={"#sk": skill_key},
            ExpressionAttributeValues={":delta": Decimal(amount)},
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("ValidationException", "ResourceNotFoundException"):
            # skill_xp map doesn't exist yet — initialise it
            try:
                _get_table().update_item(
                    Key={"user_id": user_id},
                    UpdateExpression="SET skill_xp = if_not_exists(skill_xp, :empty) ",
                    ExpressionAttributeValues={":empty": {}},
                )
                _get_table().update_item(
                    Key={"user_id": user_id},
                    UpdateExpression="ADD skill_xp.#sk :delta",
                    ExpressionAttributeNames={"#sk": skill_key},
                    ExpressionAttributeValues={":delta": Decimal(amount)},
                )
            except ClientError as inner_exc:
                logger.warning("skill_xp init failed for '%s': %s", user_id, inner_exc)
        else:
            logger.error("update_skill_xp failed for '%s'/'%s': %s", user_id, skill, exc)

    logger.info("Skill XP: user='%s' skill='%s' +%d", user_id, skill_key, amount)


def get_skill_xp_map(user_id: str) -> dict[str, int]:
    """Return the {skill: xp} map for the given user.  Empty dict if no data."""
    user = get_user(user_id)
    if not user:
        return {}
    raw = user.get("skill_xp", {})
    if isinstance(raw, dict):
        return {k: int(v) for k, v in raw.items()}
    return {}


def update_user_profile(user_id: str, target_role: str, user_skills: list[str]) -> None:
    """Persist the user's target role and current skill list to DynamoDB.

    Called during onboarding and whenever the role/skills are updated so that
    the closed-loop re-ranking always has the latest profile available without
    requiring the frontend to re-send every payload field.
    """
    table = _table()
    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET target_role = :r, user_skills = :s",
            ExpressionAttributeValues={
                ":r": target_role,
                ":s": user_skills,
            },
        )
        logger.info("update_user_profile: user='%s' role='%s' skills=%d", user_id, target_role, len(user_skills))
    except ClientError as exc:
        logger.error("update_user_profile failed for '%s': %s", user_id, exc)


def set_next_priority_skill(user_id: str, skill: str) -> None:
    """Store the current top-priority skill gap for the user.

    This is written after every task submission as part of the agentic loop
    so the frontend can immediately surface the most impactful next action.
    """
    table = _table()
    try:
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET next_priority_skill = :s",
            ExpressionAttributeValues={":s": skill},
        )
        logger.info("set_next_priority_skill: user='%s' -> '%s'", user_id, skill)
    except ClientError as exc:
        logger.error("set_next_priority_skill failed for '%s': %s", user_id, exc)


def add_learned_skill(user_id: str, skill: str) -> None:
    """Record a skill the user has practised via the Daily Quest.

    Uses a DynamoDB string set (``ADD learned_skills``) so the operation is
    idempotent — adding the same skill twice has no effect.
    Creates the user record if it doesn't exist yet.
    """
    if get_user(user_id) is None:
        create_user(user_id)
    try:
        _table().update_item(
            Key={"user_id": user_id},
            UpdateExpression="ADD learned_skills :s",
            ExpressionAttributeValues={":s": {skill}},
        )
        logger.info("add_learned_skill: user='%s' skill='%s'", user_id, skill)
    except ClientError as exc:
        logger.error("add_learned_skill failed for '%s'/'%s': %s", user_id, skill, exc)


def get_learned_skills(user_id: str) -> list[str]:
    """Return the list of skills the user has practised (from ``learned_skills`` set)."""
    user = get_user(user_id)
    if not user:
        return []
    raw = user.get("learned_skills", [])
    # DynamoDB string sets come back as Python sets after _deserialise
    if isinstance(raw, (set, list)):
        return sorted(raw)
    return []


def _deserialise(item: dict) -> dict:
    """Recursively convert DynamoDB Decimal fields to int/float."""
    def _convert(value):
        if isinstance(value, Decimal):
            return int(value) if value == int(value) else float(value)
        if isinstance(value, set):
            return list(value)
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_convert(v) for v in value]
        return value

    return {k: _convert(v) for k, v in item.items()}
