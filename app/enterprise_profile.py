from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.permit_ownership import UNKNOWN_OWNERSHIP, owner_category_label


UNKNOWN = "未披露"
UNRATED = "未评级（缺少征信/财务数据）"

PROJECT_STAGE_BY_PERMIT = {
    "建设用地规划许可证": "拿地阶段",
    "建设工程规划许可证": "建设准备阶段",
    "建设工程施工许可证": "开工阶段",
}
PROJECT_TYPE_LABELS = {
    "enterprise": "企业",
    "government": "政府/公共机构",
    "unknown": "待核验",
}


@dataclass(frozen=True)
class EnterpriseProfile:
    company_name: str
    enterprise_type: str
    region: str
    industry: str
    project_name: str
    project_stage: str
    established_time: str
    registered_capital: str
    enterprise_credit_level: str

    def to_fields(self) -> dict[str, Any]:
        return asdict(self)


def build_enterprise_profile(item: Mapping[str, Any]) -> EnterpriseProfile:
    """Build a conservative profile from fields already present in a permit item."""

    return EnterpriseProfile(
        company_name=_first_disclosed(
            item,
            "company_name",
            "construction_unit",
            "owner_name",
        ),
        enterprise_type=_enterprise_type(item),
        region=_region(item),
        industry=_first_disclosed(item, "industry"),
        project_name=_first_disclosed(item, "project_name"),
        project_stage=_project_stage(item),
        established_time=_first_disclosed(
            item,
            "established_time",
            "established_at",
            "established_date",
            "founding_date",
        ),
        registered_capital=_first_disclosed(
            item,
            "registered_capital",
            "registration_capital",
        ),
        enterprise_credit_level=_first_disclosed(
            item,
            "enterprise_credit_level",
            "credit_level",
            "credit_rating",
            fallback=UNRATED,
        ),
    )


def enrich_enterprise_profile(item: Mapping[str, Any]) -> dict[str, Any]:
    return dict(item) | build_enterprise_profile(item).to_fields()


def _enterprise_type(item: Mapping[str, Any]) -> str:
    project_type = str(item.get("project_type") or "unknown")
    base_label = PROJECT_TYPE_LABELS.get(project_type, PROJECT_TYPE_LABELS["unknown"])
    owner_category = str(item.get("owner_category") or UNKNOWN_OWNERSHIP)
    if owner_category == UNKNOWN_OWNERSHIP:
        return base_label
    ownership_label = owner_category_label(owner_category)
    if project_type == "enterprise":
        return f"{base_label}（{ownership_label}）"
    return ownership_label


def _region(item: Mapping[str, Any]) -> str:
    parts = [
        _clean(item.get(field))
        for field in ("province", "city", "district")
    ]
    disclosed = [part for part in parts if part]
    return " / ".join(disclosed) if disclosed else UNKNOWN


def _project_stage(item: Mapping[str, Any]) -> str:
    disclosed = _clean(item.get("project_stage"))
    if disclosed:
        return disclosed
    permit_type = str(item.get("permit_type") or "").strip()
    return PROJECT_STAGE_BY_PERMIT.get(permit_type, "待核验")


def _first_disclosed(
    item: Mapping[str, Any],
    *field_names: str,
    fallback: str = UNKNOWN,
) -> str:
    for field_name in field_names:
        value = _clean(item.get(field_name))
        if value:
            return value
    return fallback


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {UNKNOWN, "未知", "None", "null"}:
        return ""
    return text
