from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Mapping

from app.company_registry import assess_registry_completeness
from app.enterprise_profile_enhance import (
    COMPANY_STRENGTH_FINANCE_SCORES,
    assess_company_strength,
)

FINANCE_LEVEL_OPTIONS = ("A", "B", "C")
FINANCE_LEVEL_LABELS = {
    "A": "A 高价值机会",
    "B": "B 普通机会",
    "C": "C 观察",
}

INDUSTRIAL_MANUFACTURING_KEYWORDS = (
    "工业",
    "制造",
    "生产",
    "年产",
    "加工",
    "产业化",
)
PRODUCTION_BASE_KEYWORDS = ("生产基地",)
EQUIPMENT_INVESTMENT_KEYWORDS = (
    "设备",
    "装备",
    "生产线",
    "产线",
    "机器",
    "机械",
    "机组",
)
FACTORY_CONSTRUCTION_KEYWORDS = ("厂房", "工厂", "车间")
EXPANSION_KEYWORDS = (
    "生产扩建",
    "扩建",
    "改扩建",
    "扩产",
    "技改",
    "技术改造",
    "产能提升",
)

LAND_PERMIT_TYPE = "建设用地规划许可证"
PLANNING_PERMIT_TYPE = "建设工程规划许可证"
START_PERMIT_TYPE = "建设工程施工许可证"


@dataclass(frozen=True)
class FinanceAssessment:
    finance_score: int
    finance_level: str
    project_value_score: int
    enterprise_strength_score: int
    registry_completeness_score: int
    financing_need_score: int
    time_window_score: int
    loan_type: str
    finance_opportunity: str
    suggested_contact_time: str
    eligible_for_recommendation: bool

    def to_fields(self) -> dict[str, Any]:
        return asdict(self)


def score_finance_opportunity(
    item: Mapping[str, Any],
    *,
    today: date | None = None,
) -> FinanceAssessment:
    current_day = today or date.today()
    project_type = str(item.get("project_type") or "unknown")
    if project_type == "government":
        return FinanceAssessment(
            finance_score=0,
            finance_level="C",
            project_value_score=0,
            enterprise_strength_score=0,
            registry_completeness_score=0,
            financing_need_score=0,
            time_window_score=0,
            loan_type="",
            finance_opportunity="不进入融资推荐",
            suggested_contact_time="不进入融资推荐",
            eligible_for_recommendation=False,
        )

    project_text = " ".join(
        (
            str(item.get("project_name") or ""),
            str(item.get("industry") or ""),
            str(item.get("project_scale") or ""),
        )
    )
    project_value_score = _project_value_component(project_type, project_text)
    enterprise_strength_score = _enterprise_strength_component(item)
    registry_completeness_score = _registry_completeness_component(item)
    financing_need_score = _financing_need_component(
        project_text,
        str(item.get("permit_type") or ""),
    )

    publish_date = _parse_date(item.get("publish_date"))
    time_window_score = _time_window_component(publish_date, current_day)
    score = min(
        project_value_score
        + enterprise_strength_score
        + registry_completeness_score
        + financing_need_score
        + time_window_score,
        100,
    )
    level = _finance_level(score)
    loan_type, opportunity = _permit_finance_mapping(item.get("permit_type"))
    return FinanceAssessment(
        finance_score=score,
        finance_level=level,
        project_value_score=project_value_score,
        enterprise_strength_score=enterprise_strength_score,
        registry_completeness_score=registry_completeness_score,
        financing_need_score=financing_need_score,
        time_window_score=time_window_score,
        loan_type=loan_type,
        finance_opportunity=opportunity,
        suggested_contact_time=_suggested_contact_time(level, publish_date, current_day),
        eligible_for_recommendation=True,
    )


def enrich_finance_opportunities(
    items: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    enriched = []
    for item in items:
        assessment = score_finance_opportunity(item, today=today)
        enriched.append(dict(item) | assessment.to_fields())
    return enriched


def rank_finance_opportunities(
    items: list[dict[str, Any]],
    *,
    finance_level: str,
    today: date | None = None,
) -> list[dict[str, Any]]:
    if finance_level not in FINANCE_LEVEL_OPTIONS:
        return []
    enriched = enrich_finance_opportunities(items, today=today)
    eligible = [
        item
        for item in enriched
        if bool(item.get("eligible_for_recommendation"))
        and str(item.get("finance_level") or "") == finance_level
    ]
    return sorted(
        eligible,
        key=lambda item: (
            -int(item.get("finance_score") or 0),
            -(_parse_date(item.get("publish_date")) or date.min).toordinal(),
            str(item.get("company_name") or ""),
            str(item.get("project_name") or ""),
        ),
    )


def _finance_level(score: int) -> str:
    if score >= 70:
        return "A"
    if score >= 50:
        return "B"
    return "C"


def _project_value_component(project_type: str, project_text: str) -> int:
    score = 20 if project_type == "enterprise" else 0
    if _contains_any(project_text, INDUSTRIAL_MANUFACTURING_KEYWORDS):
        score += 10
    if _contains_any(project_text, PRODUCTION_BASE_KEYWORDS):
        score += 5
    if _contains_any(
        project_text,
        FACTORY_CONSTRUCTION_KEYWORDS
        + EQUIPMENT_INVESTMENT_KEYWORDS
        + EXPANSION_KEYWORDS,
    ):
        score += 5
    return min(score, 40)


def _enterprise_strength_component(item: Mapping[str, Any]) -> int:
    level = str(item.get("enterprise_strength_level") or "").strip()
    if level in COMPANY_STRENGTH_FINANCE_SCORES:
        return COMPANY_STRENGTH_FINANCE_SCORES[level]
    return assess_company_strength(item).finance_component_score


def _registry_completeness_component(item: Mapping[str, Any]) -> int:
    raw_percentage = item.get("registry_completeness_percentage")
    try:
        percentage = int(raw_percentage) if raw_percentage is not None else None
    except (TypeError, ValueError):
        percentage = None
    if percentage is None and not (
        bool(item.get("registry_data_available"))
        or str(item.get("registry_data_source") or "").strip()
    ):
        return 0
    if percentage is None:
        percentage = assess_registry_completeness(item).percentage
    return min(max((percentage + 5) // 10, 0), 10)


def _financing_need_component(project_text: str, permit_type: str) -> int:
    score = 5 if permit_type in {
        LAND_PERMIT_TYPE,
        PLANNING_PERMIT_TYPE,
        START_PERMIT_TYPE,
    } else 0
    has_specific_signal = False
    if _contains_any(project_text, FACTORY_CONSTRUCTION_KEYWORDS):
        score += 8
        has_specific_signal = True
    if _contains_any(project_text, EQUIPMENT_INVESTMENT_KEYWORDS):
        score += 7
        has_specific_signal = True
    if _contains_any(project_text, EXPANSION_KEYWORDS):
        score += 5
        has_specific_signal = True
    if not has_specific_signal and _contains_any(
        project_text,
        INDUSTRIAL_MANUFACTURING_KEYWORDS,
    ):
        score += 5
    return min(score, 20)


def _time_window_component(publish_date: date | None, today: date) -> int:
    if publish_date is None:
        return 0
    age = (today - publish_date).days
    if 0 <= age <= 30:
        return 10
    if 0 <= age <= 90:
        return 5
    return 0


def _permit_finance_mapping(permit_type: Any) -> tuple[str, str]:
    normalized = str(permit_type or "").strip()
    if normalized == LAND_PERMIT_TYPE:
        return "土地贷款", "土地融资机会"
    if normalized == PLANNING_PERMIT_TYPE:
        return "固定资产贷款、项目贷款", "固定资产贷款机会"
    if normalized == START_PERMIT_TYPE:
        return "设备贷款、流动资金贷款", "设备贷款/流动资金机会"
    return "项目贷款", "项目贷款机会"


def _suggested_contact_time(
    finance_level: str,
    publish_date: date | None,
    today: date,
) -> str:
    is_recent = publish_date is not None and 0 <= (today - publish_date).days <= 30
    if finance_level == "A":
        return "建议3个工作日内联系" if is_recent else "建议5个工作日内联系"
    if finance_level == "B":
        return "建议7个工作日内联系"
    return "建议30天内复核"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None
