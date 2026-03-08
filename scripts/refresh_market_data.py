#!/usr/bin/env python3
"""Standalone script to refresh live market-demand data.

Usage (from the repo root):
    AWS_REGION=us-east-1 .venv/bin/python scripts/refresh_market_data.py

The script pulls live job listings from RemoteOK (always) and Adzuna (when
``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY`` env vars are set), merges the result
with the static market_skills.json baseline (80 / 20 split), and writes the
merged data back to ``app/data/market_skills.json``.

Exit codes:
    0  — success
    1  — fetch/merge failed (partial results still written if possible)
"""

import json
import sys

# Ensure the project root is on sys.path when running as a script
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import market_service  # noqa: E402  (after sys.path tweak)


def main() -> int:
    print("CareerOS — refreshing live market data …")
    try:
        result = market_service.refresh_market_data(write=True)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))

    if result.get("roles_updated", 0) == 0:
        print(
            "WARNING: no roles were updated — check ADZUNA_APP_ID/KEY or RemoteOK connectivity.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\n✓ Updated {result['roles_updated']} roles from "
        f"{result['total_jobs_processed']} jobs in {result['elapsed_s']:.1f}s."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
