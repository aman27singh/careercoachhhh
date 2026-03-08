import json
from datetime import date, timedelta
from pathlib import Path

from app.models import UserMetrics
from app.services.game_engine import apply_task_submission

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "users"


def _get_writable_data_dir() -> Path:
    """Return a writable data directory.

    Lambda's /var/task is read-only; fall back to /tmp which is always writable.
    """
    try:
        _DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _test = _DEFAULT_DATA_DIR / ".write_test"
        _test.write_text("ok")
        _test.unlink()
        return _DEFAULT_DATA_DIR
    except OSError:
        fallback = Path("/tmp/careeros/users")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = _get_writable_data_dir()


def _user_file(user_id: str) -> Path:
    return DATA_DIR / f"{user_id}.json"


def create_user_if_not_exists(user_id: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _user_file(user_id)
    if path.exists():
        return
    metrics = UserMetrics(
        user_id=user_id,
        xp=0,
        level=1,
        rank="unranked",
        streak=0,
        total_completed_tasks=0,
        total_assigned_tasks=0,
        execution_score=0.0,
        last_submission_date=None,
    )
    path.write_text(json.dumps(metrics.model_dump(), indent=2))


def load_user_metrics(user_id: str) -> UserMetrics:
    create_user_if_not_exists(user_id)
    path = _user_file(user_id)
    data = json.loads(path.read_text())
    return UserMetrics(**data)


def save_user_metrics(user_id: str, metrics: UserMetrics | dict) -> None:
    create_user_if_not_exists(user_id)
    path = _user_file(user_id)
    if isinstance(metrics, UserMetrics):
        data = metrics.model_dump()
    elif isinstance(metrics, dict):
        data = metrics
    else:
        raise TypeError("metrics must be UserMetrics or dict")
    path.write_text(json.dumps(data, indent=2))


def update_metrics_on_task_submission(
    user_id: str,
    quality_score: int,
    assigned_increment: int = 1,
    completed_increment: int = 1,
) -> UserMetrics:
    metrics = load_user_metrics(user_id)
    today = date.today().isoformat()
    if not metrics.last_submission_date:
        streak = 1
    else:
        last_date = date.fromisoformat(metrics.last_submission_date)
        today_date = date.fromisoformat(today)
        yesterday = today_date - timedelta(days=1)
        if last_date == yesterday:
            streak = metrics.streak + 1
        elif last_date == today_date:
            streak = metrics.streak
        else:
            streak = 1

    metrics.last_submission_date = today
    apply_task_submission(
        metrics,
        quality_score=quality_score,
        streak=streak,
        assigned_increment=assigned_increment,
        completed_increment=completed_increment,
    )
    save_user_metrics(user_id, metrics)
    return metrics
