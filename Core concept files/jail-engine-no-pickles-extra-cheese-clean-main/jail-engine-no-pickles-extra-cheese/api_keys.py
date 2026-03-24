"""
API key storage and usage metering (SQLite-backed).

This is intentionally simple and file-based so you can ship fast and swap in a
managed database later without changing the FastAPI layer.
"""

from __future__ import annotations

import os
import sqlite3
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict

DB_PATH = Path(os.environ.get("API_DB_PATH", "billing.sqlite")).resolve()

PLANS = {
    "free": {"daily": 50, "monthly": 50},
    "indie": {"monthly": 3000},
    "pro": {"monthly": 50000},
}


class UsageLimitExceeded(Exception):
    def __init__(self, message: str, plan: str, limit: int, window: str) -> None:
        super().__init__(message)
        self.plan = plan
        self.limit = limit
        self.window = window


@dataclass
class ApiKeyRecord:
    api_key: str
    plan: str
    email: Optional[str]
    created_at: str


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def ensure_schema() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            api_key TEXT PRIMARY KEY,
            plan TEXT NOT NULL,
            email TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usage (
            api_key TEXT NOT NULL,
            period_type TEXT NOT NULL, -- 'day' or 'month'
            window TEXT NOT NULL,       -- e.g. 2025-12-07 or 2025-12
            request_count INTEGER NOT NULL DEFAULT 0,
            token_estimate INTEGER NOT NULL DEFAULT 0,
            last_persona TEXT,
            last_backend TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (api_key, period_type, window)
        );
        """
    )
    conn.commit()
    conn.close()


def create_api_key(plan: str, email: str | None = None) -> ApiKeyRecord:
    plan = (plan or "free").lower()
    if plan not in PLANS:
        plan = "free"
    ensure_schema()
    api_key = secrets.token_urlsafe(32)
    created_at = datetime.utcnow().isoformat() + "Z"
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO api_keys (api_key, plan, email, created_at) VALUES (?, ?, ?, ?)",
        (api_key, plan, email, created_at),
    )
    conn.commit()
    conn.close()
    return ApiKeyRecord(api_key=api_key, plan=plan, email=email, created_at=created_at)


def get_api_key(api_key: str) -> Optional[ApiKeyRecord]:
    ensure_schema()
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT api_key, plan, email, created_at FROM api_keys WHERE api_key = ?",
        (api_key,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return ApiKeyRecord(api_key=row[0], plan=row[1], email=row[2], created_at=row[3])


def _bump_usage(
    cur: sqlite3.Cursor,
    api_key: str,
    period_type: str,
    window: str,
    token_estimate: int,
    persona: str | None,
    backend: str | None,
) -> Tuple[int, int]:
    cur.execute(
        """
        INSERT INTO usage (api_key, period_type, window, request_count, token_estimate, last_persona, last_backend, updated_at)
        VALUES (?, ?, ?, 0, 0, ?, ?, ?)
        ON CONFLICT(api_key, period_type, window)
        DO UPDATE SET updated_at=excluded.updated_at;
        """,
        (api_key, period_type, window, persona, backend, datetime.utcnow().isoformat() + "Z"),
    )
    cur.execute(
        """
        UPDATE usage
        SET request_count = request_count + 1,
            token_estimate = token_estimate + ?,
            last_persona = ?,
            last_backend = ?,
            updated_at = ?
        WHERE api_key = ? AND period_type = ? AND window = ?;
        """,
        (
            token_estimate,
            persona,
            backend,
            datetime.utcnow().isoformat() + "Z",
            api_key,
            period_type,
            window,
        ),
    )
    cur.execute(
        "SELECT request_count, token_estimate FROM usage WHERE api_key=? AND period_type=? AND window=?",
        (api_key, period_type, window),
    )
    return cur.fetchone()


def _current_windows() -> Dict[str, str]:
    now = datetime.utcnow()
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    return {"day": day, "month": month}


def check_and_increment_usage(
    api_key: str,
    plan: str,
    token_estimate: int,
    persona: str | None = None,
    backend: str | None = None,
) -> Dict[str, Dict[str, int]]:
    """
    Raises UsageLimitExceeded if the plan limit is exceeded.
    Returns usage snapshots for day/month after increment.
    """
    ensure_schema()
    conn = _connect()
    cur = conn.cursor()
    windows = _current_windows()

    snapshots: Dict[str, Dict[str, int]] = {}
    limits = PLANS.get(plan, PLANS["free"])

    try:
        # Always track both day and month for visibility
        day_counts = _bump_usage(cur, api_key, "day", windows["day"], token_estimate, persona, backend)
        month_counts = _bump_usage(cur, api_key, "month", windows["month"], token_estimate, persona, backend)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    snapshots["day"] = {"window": windows["day"], "request_count": day_counts[0], "token_estimate": day_counts[1]}
    snapshots["month"] = {"window": windows["month"], "request_count": month_counts[0], "token_estimate": month_counts[1]}

    # Enforce limits
    if "daily" in limits and day_counts[0] > limits["daily"]:
        conn.close()
        raise UsageLimitExceeded("Daily limit reached", plan, limits["daily"], windows["day"])
    if "monthly" in limits and month_counts[0] > limits["monthly"]:
        conn.close()
        raise UsageLimitExceeded("Monthly limit reached", plan, limits["monthly"], windows["month"])

    conn.close()
    return snapshots


def usage_snapshot(api_key: str) -> Dict[str, Dict[str, int]]:
    ensure_schema()
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT period_type, window, request_count, token_estimate FROM usage WHERE api_key=?",
        (api_key,),
    )
    rows = cur.fetchall()
    conn.close()
    snap: Dict[str, Dict[str, int]] = {}
    for period_type, window, count, tokens in rows:
        snap[period_type] = {"window": window, "request_count": count, "token_estimate": tokens}
    return snap


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # Rough heuristic: 4 chars per token
    return max(1, len(text) // 4)
