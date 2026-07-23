from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


PLANNING_PERMIT_TYPE = "建设工程规划许可证"
UNKNOWN = "未披露"


@dataclass(frozen=True)
class PermitDataset:
    items: list[dict[str, Any]]
    storage_source: str
    last_updated: str


def load_planning_permit_dataset(db_path: Path, cloud_json_path: Path) -> PermitDataset:
    sqlite_items = _load_sqlite(db_path)
    if sqlite_items:
        return PermitDataset(
            items=sqlite_items,
            storage_source="本地SQLite",
            last_updated=_latest_seen(sqlite_items),
        )
    cloud_items = _load_cloud_json(cloud_json_path)
    return PermitDataset(
        items=cloud_items,
        storage_source="Streamlit Cloud JSON" if cloud_items else "暂无正式数据",
        last_updated=_latest_seen(cloud_items),
    )


def summarize_planning_permits(
    items: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, int]:
    current_day = today or date.today()
    return {
        "total_count": len(items),
        "recent_90_days_count": sum(_within_days(item, 90, current_day) for item in items),
        "recent_30_days_count": sum(_within_days(item, 30, current_day) for item in items),
    }


def filter_planning_permits(
    items: list[dict[str, Any]],
    ai_level: str = "全部",
    recent_days: int | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    current_day = today or date.today()
    filtered = []
    for item in items:
        level = str(item.get("ai_opportunity_level") or "")
        if ai_level != "全部" and level != ai_level:
            continue
        if recent_days is not None and not _within_days(item, recent_days, current_day):
            continue
        filtered.append(item)
    return sorted(
        filtered,
        key=lambda item: _effective_date(item) or date.min,
        reverse=True,
    )


def _load_sqlite(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn: sqlite3.Connection | None = None
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction_permits'"
        ).fetchone()
        if table is None:
            return []
        columns = {row[1] for row in conn.execute("PRAGMA table_info(construction_permits)")}
        required = {
            "publish_date",
            "issuing_authority",
            "district",
            "district_code",
            "source_url",
            "source_name",
            "fresh_score",
            "first_seen_at",
            "last_seen_at",
        }
        if not required.issubset(columns):
            return []
        has_ai_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='permit_ai_analyses'"
        ).fetchone() is not None
        if has_ai_table:
            ai_fields = """
                analyses.ai_opportunity_level,
                analyses.financing_need,
                analyses.recommended_products_json,
                analyses.marketing_summary,
                analyses.visit_suggestion,
                analyses.reasoning_summary,
                analyses.confidence,
                analyses.risk_notice
            """
            ai_join = "LEFT JOIN permit_ai_analyses AS analyses ON analyses.permit_id = permits.id"
        else:
            ai_fields = """
                NULL AS ai_opportunity_level,
                NULL AS financing_need,
                '[]' AS recommended_products_json,
                NULL AS marketing_summary,
                NULL AS visit_suggestion,
                NULL AS reasoning_summary,
                NULL AS confidence,
                NULL AS risk_notice
            """
            ai_join = ""
        rows = conn.execute(
            f"""
            SELECT
                permits.company_name,
                permits.project_name,
                permits.permit_type,
                permits.permit_number,
                permits.permit_date,
                permits.publish_date,
                permits.address AS project_address,
                permits.issuing_authority,
                permits.district,
                permits.district_code,
                permits.source_url,
                permits.source_name,
                permits.fresh_score,
                permits.first_seen_at,
                permits.last_seen_at,
                {ai_fields}
            FROM construction_permits AS permits
            {ai_join}
            WHERE permits.permit_type = ?
            ORDER BY CASE WHEN permits.permit_date <> ? THEN permits.permit_date ELSE permits.publish_date END DESC
            """,
            (PLANNING_PERMIT_TYPE, UNKNOWN),
        ).fetchall()
        return [_normalize_item(dict(row)) for row in rows]
    except (OSError, sqlite3.Error):
        return []
    finally:
        if conn is not None:
            conn.close()


def _load_cloud_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        _normalize_item(item)
        for item in payload
        if isinstance(item, dict)
        and item.get("permit_type") == PLANNING_PERMIT_TYPE
        and item.get("district_code") == "320684"
    ]


def _latest_seen(items: list[dict[str, Any]]) -> str:
    values = [str(item.get("last_seen_at") or "") for item in items]
    return max((value for value in values if value), default=UNKNOWN)


def _within_days(item: dict[str, Any], days: int, today: date) -> bool:
    parsed = _effective_date(item)
    if not parsed:
        return False
    age = (today - parsed).days
    return 0 <= age <= days


def _effective_date(item: dict[str, Any]) -> date | None:
    value = str(item.get("permit_date") or "")
    if not value or value == UNKNOWN:
        value = str(item.get("publish_date") or "")
    return _parse_date(value)


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    products = normalized.pop("recommended_products_json", normalized.get("recommended_products", []))
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except json.JSONDecodeError:
            products = []
    if not isinstance(products, list):
        products = []
    normalized["recommended_products"] = [
        str(product).strip() for product in products if str(product).strip()
    ]
    return normalized


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None
