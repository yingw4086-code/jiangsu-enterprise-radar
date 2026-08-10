from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.permit_ownership import (
    FOREIGN_ENTERPRISE,
    GOVERNMENT_AGENCY,
    MIXED_OWNERSHIP,
    PRIVATE_ENTERPRISE,
    PUBLIC_INSTITUTION,
    STATE_OWNED_COMMERCIAL,
    UNKNOWN_OWNERSHIP,
)


PLANNING_PERMIT_TYPE = "建设工程规划许可证"
DEFAULT_REGION_KEY = "320684"
UNKNOWN = "未披露"
PROJECT_TYPE_FILTER_OPTIONS = ("企业项目", "政府项目", "全部")
PROJECT_TYPE_FILTER_VALUES = {
    "企业项目": "enterprise",
    "政府项目": "government",
}
CLASSIFICATION_CONFIDENCE_SORT_ORDER = {"high": 0, "medium": 1, "low": 2}
AI_LEVEL_SORT_ORDER = {"A": 0, "B": 1, "C": 2}
OWNER_VIEW_ELIGIBLE = "可营销企业"
OWNER_FILTER_OPTIONS = (
    OWNER_VIEW_ELIGIBLE,
    "只看民营企业",
    "民营及外资企业",
    "国有商业企业",
    "待核验",
    "已排除政府公益项目",
    "全部",
)
OWNER_CATEGORY_SORT_ORDER = {
    PRIVATE_ENTERPRISE: 0,
    FOREIGN_ENTERPRISE: 0,
    STATE_OWNED_COMMERCIAL: 1,
    MIXED_OWNERSHIP: 2,
}
MARKETING_PRIORITY_SORT_ORDER = {"A": 0, "B": 1}


@dataclass(frozen=True)
class PermitDataset:
    items: list[dict[str, Any]]
    storage_source: str
    last_updated: str
    source_path: str


def summarize_region_opportunities(items: list[dict[str, Any]]) -> dict[str, int]:
    project_types = [str(item.get("project_type") or "unknown") for item in items]
    return {
        "total_count": len(items),
        "enterprise_count": project_types.count("enterprise"),
        "government_count": project_types.count("government"),
        "high_confidence_opportunity_count": sum(
            project_type == "enterprise"
            and str(item.get("classification_confidence") or "low") == "high"
            for item, project_type in zip(items, project_types, strict=True)
        ),
    }


def filter_permits_by_project_type(
    items: list[dict[str, Any]],
    project_type_view: str,
) -> list[dict[str, Any]]:
    if project_type_view == "全部":
        return list(items)
    project_type = PROJECT_TYPE_FILTER_VALUES.get(project_type_view)
    if project_type is None:
        return []
    return [
        item
        for item in items
        if str(item.get("project_type") or "unknown") == project_type
    ]


def select_priority_enterprise_opportunities(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enterprise_items = filter_permits_by_project_type(items, "企业项目")
    return sorted(
        enterprise_items,
        key=lambda item: (
            CLASSIFICATION_CONFIDENCE_SORT_ORDER.get(
                str(item.get("classification_confidence") or "low"),
                99,
            ),
            -(_publish_date(item) or date.min).toordinal(),
            str(item.get("company_name") or ""),
            str(item.get("project_name") or ""),
        ),
    )


def load_planning_permit_dataset(
    db_path: Path,
    cloud_json_path: Path,
    *,
    region_key: str = DEFAULT_REGION_KEY,
) -> PermitDataset:
    selected_region = _validated_region_key(region_key)
    sqlite_items = _load_sqlite(db_path, selected_region)
    if sqlite_items:
        return PermitDataset(
            items=sqlite_items,
            storage_source="本地SQLite",
            last_updated=_latest_seen(sqlite_items),
            source_path=_display_path(db_path),
        )
    cloud_items = _load_cloud_json(cloud_json_path, selected_region)
    return PermitDataset(
        items=cloud_items,
        storage_source="Streamlit Cloud JSON" if cloud_items else "暂无正式数据",
        last_updated=_latest_seen(cloud_items),
        source_path=_display_path(cloud_json_path),
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


def summarize_homepage_permits(
    items: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, Any]:
    current_day = today or date.today()
    dated_items = [
        (item, effective_permit_date(item))
        for item in items
    ]
    valid_dates = [item_date for _, item_date in dated_items if item_date is not None]
    return {
        "today_count": sum(item_date == current_day for _, item_date in dated_items),
        "recent_30_days_count": sum(
            _date_within_days(item_date, 30, current_day)
            for _, item_date in dated_items
        ),
        "recent_90_days_count": sum(
            _date_within_days(item_date, 90, current_day)
            for _, item_date in dated_items
        ),
        "total_count": len(items),
        "latest_date": max(valid_dates).isoformat() if valid_dates else UNKNOWN,
    }


def select_homepage_opportunities(
    items: list[dict[str, Any]],
    *,
    recent_days: int = 90,
    limit: int = 15,
    today: date | None = None,
    ownership_view: str = OWNER_VIEW_ELIGIBLE,
) -> list[dict[str, Any]]:
    current_day = today or date.today()
    candidates = [
        item
        for item in filter_permits_by_ownership(items, ownership_view)
        if _date_within_days(effective_permit_date(item), recent_days, current_day)
    ]
    return sorted(
        candidates,
        key=lambda item: (
            OWNER_CATEGORY_SORT_ORDER.get(str(item.get("owner_category") or ""), 99),
            MARKETING_PRIORITY_SORT_ORDER.get(
                str(item.get("marketing_priority") or ""),
                99,
            ),
            0
            if _date_within_days(effective_permit_date(item), 30, current_day)
            else 1,
            -(effective_permit_date(item) or date.min).toordinal(),
            -_integer(item.get("fresh_score")),
            AI_LEVEL_SORT_ORDER.get(str(item.get("ai_opportunity_level") or ""), 99),
            str(item.get("project_name") or ""),
        ),
    )[: max(0, limit)]


def summarize_ownership_permits(
    items: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, int]:
    current_day = today or date.today()
    categories = [str(item.get("owner_category") or UNKNOWN_OWNERSHIP) for item in items]
    return {
        "private_count": categories.count(PRIVATE_ENTERPRISE),
        "state_owned_count": categories.count(STATE_OWNED_COMMERCIAL),
        "government_public_count": sum(
            category in {GOVERNMENT_AGENCY, PUBLIC_INSTITUTION}
            for category in categories
        ),
        "unknown_count": categories.count(UNKNOWN_OWNERSHIP),
        "recent_30_private_count": sum(
            str(item.get("owner_category") or "") == PRIVATE_ENTERPRISE
            and _date_within_days(effective_permit_date(item), 30, current_day)
            for item in items
        ),
        "recent_30_marketing_eligible_count": sum(
            _boolean(item.get("marketing_eligible"))
            and _date_within_days(effective_permit_date(item), 30, current_day)
            for item in items
        ),
    }


def filter_permits_by_ownership(
    items: list[dict[str, Any]],
    ownership_view: str,
) -> list[dict[str, Any]]:
    if ownership_view == "全部":
        return list(items)
    if ownership_view == OWNER_VIEW_ELIGIBLE:
        return [item for item in items if _boolean(item.get("marketing_eligible"))]
    if ownership_view == "只看民营企业":
        categories = {PRIVATE_ENTERPRISE}
    elif ownership_view == "民营及外资企业":
        categories = {PRIVATE_ENTERPRISE, FOREIGN_ENTERPRISE}
    elif ownership_view == "国有商业企业":
        categories = {STATE_OWNED_COMMERCIAL}
    elif ownership_view == "待核验":
        categories = {UNKNOWN_OWNERSHIP}
    elif ownership_view == "已排除政府公益项目":
        categories = {GOVERNMENT_AGENCY, PUBLIC_INSTITUTION}
    else:
        return []
    return [
        item
        for item in items
        if str(item.get("owner_category") or UNKNOWN_OWNERSHIP) in categories
    ]


def sort_classified_opportunities(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            OWNER_CATEGORY_SORT_ORDER.get(
                str(item.get("owner_category") or UNKNOWN_OWNERSHIP),
                99,
            ),
            MARKETING_PRIORITY_SORT_ORDER.get(
                str(item.get("marketing_priority") or ""),
                99,
            ),
            -(effective_permit_date(item) or date.min).toordinal(),
            -_integer(item.get("fresh_score")),
            str(item.get("project_name") or ""),
        ),
    )


def effective_permit_date(item: dict[str, Any]) -> date | None:
    value = str(item.get("permit_date") or "")
    if not value or value == UNKNOWN:
        value = str(item.get("publish_date") or "")
    return _parse_date(value)


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


def _load_sqlite(db_path: Path, region_key: str) -> list[dict[str, Any]]:
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
            "province",
            "city",
            "region_key",
            "area_code",
            "source_url",
            "source_name",
            "source_region",
            "source_time",
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
        project_type_field = (
            "permits.project_type"
            if "project_type" in columns
            else "'unknown' AS project_type"
        )
        classification_confidence_field = (
            "permits.classification_confidence"
            if "classification_confidence" in columns
            else "'low' AS classification_confidence"
        )
        profile_fields = {
            field: (
                f"permits.{field}"
                if field in columns
                else f"'{UNKNOWN}' AS {field}"
            )
            for field in (
                "investment",
                "project_scale",
                "project_stage",
                "legal_person",
                "registered_capital",
                "establish_date",
                "company_address",
                "company_scale",
            )
        }
        rows = conn.execute(
            f"""
            SELECT
                permits.company_name,
                permits.construction_unit,
                permits.project_name,
                permits.permit_type,
                permits.permit_number,
                permits.permit_date,
                permits.publish_date,
                permits.address AS project_address,
                permits.issuing_authority,
                permits.district,
                permits.district_code,
                permits.province,
                permits.city,
                permits.region_key,
                permits.area_code,
                permits.industry,
                {profile_fields["investment"]},
                {profile_fields["project_scale"]},
                {profile_fields["project_stage"]},
                {profile_fields["legal_person"]},
                {profile_fields["registered_capital"]},
                {profile_fields["establish_date"]},
                {profile_fields["company_address"]},
                {profile_fields["company_scale"]},
                permits.source_url,
                permits.source_name,
                permits.source_region,
                permits.source_time,
                permits.fresh_score,
                permits.first_seen_at,
                permits.last_seen_at,
                permits.owner_name,
                permits.owner_category,
                permits.ownership_type,
                permits.ownership_confidence,
                permits.ownership_basis,
                permits.marketing_eligible,
                permits.marketing_priority,
                permits.exclusion_reason,
                permits.manual_review_required,
                permits.classification_updated_at,
                {project_type_field},
                {classification_confidence_field},
                {ai_fields}
            FROM construction_permits AS permits
            {ai_join}
            WHERE permits.permit_type = ? AND permits.region_key = ?
            ORDER BY CASE WHEN permits.permit_date <> ? THEN permits.permit_date ELSE permits.publish_date END DESC
            """,
            (PLANNING_PERMIT_TYPE, region_key, UNKNOWN),
        ).fetchall()
        return [_normalize_item(dict(row)) for row in rows]
    except (OSError, sqlite3.Error):
        return []
    finally:
        if conn is not None:
            conn.close()


def _load_cloud_json(path: Path, region_key: str) -> list[dict[str, Any]]:
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
        and _item_region_key(item) == region_key
    ]


def _validated_region_key(region_key: str) -> str:
    value = str(region_key or "").strip()
    if not value:
        raise ValueError("region_key 不能为空")
    return value


def _item_region_key(item: dict[str, Any]) -> str:
    return str(
        item.get("region_key")
        or item.get("area_code")
        or item.get("district_code")
        or ""
    ).strip()


def _latest_seen(items: list[dict[str, Any]]) -> str:
    values = [str(item.get("last_seen_at") or "") for item in items]
    return max((value for value in values if value), default=UNKNOWN)


def _within_days(item: dict[str, Any], days: int, today: date) -> bool:
    parsed = effective_permit_date(item)
    if not parsed:
        return False
    age = (today - parsed).days
    return 0 <= age <= days


def _effective_date(item: dict[str, Any]) -> date | None:
    return effective_permit_date(item)


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["project_type"] = str(normalized.get("project_type") or "unknown")
    normalized["classification_confidence"] = str(
        normalized.get("classification_confidence") or "low"
    )
    normalized["industry"] = str(normalized.get("industry") or UNKNOWN)
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
    company_name = str(normalized.get("company_name") or "").strip()
    normalized["owner_name"] = str(normalized.get("owner_name") or company_name or UNKNOWN)
    normalized["owner_category"] = str(
        normalized.get("owner_category") or UNKNOWN_OWNERSHIP
    )
    normalized["ownership_type"] = str(
        normalized.get("ownership_type") or normalized["owner_category"]
    )
    normalized["ownership_confidence"] = _integer(
        normalized.get("ownership_confidence")
    )
    normalized["ownership_basis"] = str(
        normalized.get("ownership_basis")
        or "建设单位信息不足，无法判断所有制"
    )
    normalized["marketing_eligible"] = _boolean(
        normalized.get("marketing_eligible")
    )
    normalized["marketing_priority"] = str(
        normalized.get("marketing_priority") or "待核验"
    )
    normalized["exclusion_reason"] = str(
        normalized.get("exclusion_reason") or ""
    )
    normalized["manual_review_required"] = _boolean(
        normalized.get("manual_review_required"),
        default=True,
    )
    normalized["classification_updated_at"] = str(
        normalized.get("classification_updated_at") or ""
    )
    return normalized


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None


def _publish_date(item: dict[str, Any]) -> date | None:
    return _parse_date(str(item.get("publish_date") or ""))


def _date_within_days(
    value: date | None,
    days: int,
    today: date,
) -> bool:
    if value is None:
        return False
    age = (today - value).days
    return 0 <= age <= days


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _boolean(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "是"}:
        return True
    if text in {"false", "0", "no", "n", "否"}:
        return False
    return default


def _display_path(path: Path) -> str:
    normalized = path.resolve()
    parts = list(normalized.parts)
    for marker in ("database", "data"):
        if marker in parts:
            return Path(*parts[parts.index(marker):]).as_posix()
    return normalized.name
