from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


UNKNOWN = "未披露"


@dataclass(frozen=True)
class OfficialPermitDataset:
    items: list[dict[str, Any]]
    storage_source: str
    last_updated: str


def load_official_permit_dataset(
    db_path: Path,
    cloud_json_path: Path,
    *,
    permit_type: str,
) -> OfficialPermitDataset:
    sqlite_items = _load_sqlite(db_path, permit_type)
    if sqlite_items:
        return OfficialPermitDataset(
            items=sqlite_items,
            storage_source="本地SQLite",
            last_updated=_latest_seen(sqlite_items),
        )
    cloud_items = _load_cloud_json(cloud_json_path, permit_type)
    return OfficialPermitDataset(
        items=cloud_items,
        storage_source="Streamlit Cloud JSON" if cloud_items else "暂无正式数据",
        last_updated=_latest_seen(cloud_items),
    )


def summarize_official_permits(
    items: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, int]:
    current_day = today or date.today()
    return {
        "total_count": len(items),
        "recent_90_days_count": sum(_within_days(item, 90, current_day) for item in items),
        "recent_30_days_count": sum(_within_days(item, 30, current_day) for item in items),
    }


def sort_official_permits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _effective_date(item) or date.min, reverse=True)


def _load_sqlite(db_path: Path, permit_type: str) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction_permits'"
        ).fetchone()
        if table is None:
            return []
        rows = conn.execute(
            """
            SELECT
                company_name,
                project_name,
                permit_type,
                permit_number,
                permit_date,
                publish_date,
                address AS project_address,
                issuing_authority,
                district,
                district_code,
                source_url,
                source_name,
                fresh_score,
                first_seen_at,
                last_seen_at
            FROM construction_permits
            WHERE permit_type = ? AND district_code = '320684'
            ORDER BY
                CASE WHEN permit_date <> ? THEN permit_date ELSE publish_date END DESC,
                id DESC
            """,
            (permit_type, UNKNOWN),
        ).fetchall()
        return [dict(row) for row in rows]
    except (OSError, sqlite3.Error):
        return []
    finally:
        if conn is not None:
            conn.close()


def _load_cloud_json(path: Path, permit_type: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        dict(item)
        for item in payload
        if isinstance(item, dict)
        and item.get("permit_type") == permit_type
        and item.get("district_code") == "320684"
    ]


def _latest_seen(items: list[dict[str, Any]]) -> str:
    values = [str(item.get("last_seen_at") or "") for item in items]
    return max((value for value in values if value), default=UNKNOWN)


def _within_days(item: dict[str, Any], days: int, today: date) -> bool:
    parsed = _effective_date(item)
    if parsed is None:
        return False
    age = (today - parsed).days
    return 0 <= age <= days


def _effective_date(item: dict[str, Any]) -> date | None:
    value = str(item.get("permit_date") or "")
    if not value or value == UNKNOWN:
        value = str(item.get("publish_date") or "")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None
