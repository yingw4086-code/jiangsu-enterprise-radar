from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from app.permit_ownership import (
    FOREIGN_ENTERPRISE,
    PRIVATE_ENTERPRISE,
    STATE_OWNED_COMMERCIAL,
    classify_permit_owner,
)


UNKNOWN = "未披露"
UNKNOWN_CLASSIFICATION = "未知"
ALL_FILTER = "全部"

PRIVATE_OWNERSHIP = "民营企业"
STATE_OWNERSHIP = "国有企业"
FOREIGN_OWNERSHIP = "外资企业"
OWNERSHIP_TYPE_OPTIONS = (
    PRIVATE_OWNERSHIP,
    STATE_OWNERSHIP,
    FOREIGN_OWNERSHIP,
    UNKNOWN_CLASSIFICATION,
)

LARGE_COMPANY = "大型企业"
MEDIUM_COMPANY = "中型企业"
SMALL_COMPANY = "小型企业"
MICRO_COMPANY = "微型企业"
COMPANY_SCALE_OPTIONS = (
    LARGE_COMPANY,
    MEDIUM_COMPANY,
    SMALL_COMPANY,
    MICRO_COMPANY,
    UNKNOWN_CLASSIFICATION,
)

_OWNER_CATEGORY_MAPPING = {
    PRIVATE_ENTERPRISE: PRIVATE_OWNERSHIP,
    STATE_OWNED_COMMERCIAL: STATE_OWNERSHIP,
    FOREIGN_ENTERPRISE: FOREIGN_OWNERSHIP,
}
_EXPLICIT_OWNERSHIP_MAPPING = {
    "民营企业": PRIVATE_OWNERSHIP,
    "私营企业": PRIVATE_OWNERSHIP,
    "私营有限责任公司": PRIVATE_OWNERSHIP,
    "私营股份有限公司": PRIVATE_OWNERSHIP,
    "自然人投资或控股": PRIVATE_OWNERSHIP,
    "自然人独资": PRIVATE_OWNERSHIP,
    "国有企业": STATE_OWNERSHIP,
    "国有独资": STATE_OWNERSHIP,
    "国有控股": STATE_OWNERSHIP,
    "全民所有制": STATE_OWNERSHIP,
    "外资企业": FOREIGN_OWNERSHIP,
    "外商独资": FOREIGN_OWNERSHIP,
    "外商投资企业": FOREIGN_OWNERSHIP,
    "港澳台投资企业": FOREIGN_OWNERSHIP,
}
_EXPLICIT_SCALE_MAPPING = {
    "大型": LARGE_COMPANY,
    "大型企业": LARGE_COMPANY,
    "中型": MEDIUM_COMPANY,
    "中型企业": MEDIUM_COMPANY,
    "小型": SMALL_COMPANY,
    "小型企业": SMALL_COMPANY,
    "微型": MICRO_COMPANY,
    "微型企业": MICRO_COMPANY,
}
_INTEGER_PATTERN = re.compile(r"\d[\d,]*")
_CAPITAL_PATTERN = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|元)")

COMPANY_STRENGTH_LABELS = {
    "A": "A 强",
    "B": "B 良好",
    "C": "C 一般",
    "D": "D 信息不足",
}
COMPANY_STRENGTH_FINANCE_SCORES = {
    "A": 20,
    "B": 15,
    "C": 10,
    "D": 0,
}


@dataclass(frozen=True)
class EnhancedEnterpriseProfile:
    company_name: str
    unified_social_credit_code: str
    legal_person: str
    registered_capital: str
    establish_date: str
    company_address: str
    business_scope: str
    company_status: str
    industry: str
    ownership_type: str
    company_scale: str
    ownership_confidence: str
    ownership_basis: str
    company_scale_confidence: str
    company_scale_basis: str

    def to_fields(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompanyStrengthAssessment:
    strength_level: str
    strength_label: str
    finance_component_score: int
    rule_points: int
    disclosed_dimension_count: int
    assessment_basis: tuple[str, ...]

    def to_fields(self) -> dict[str, Any]:
        return {
            "enterprise_strength_level": self.strength_level,
            "enterprise_strength_label": self.strength_label,
            "enterprise_strength_score": self.finance_component_score,
            "enterprise_strength_rule_points": self.rule_points,
            "enterprise_strength_disclosed_dimensions": self.disclosed_dimension_count,
            "enterprise_strength_basis": list(self.assessment_basis),
        }


def build_enhanced_enterprise_profile(
    item: Mapping[str, Any],
) -> EnhancedEnterpriseProfile:
    company_name = _first_disclosed(
        item,
        "company_name",
        "construction_unit",
        "owner_name",
    )
    ownership_type, ownership_confidence, ownership_basis = _ownership(item)
    company_scale, scale_confidence, scale_basis = _company_scale(item)
    return EnhancedEnterpriseProfile(
        company_name=company_name,
        unified_social_credit_code=_first_disclosed(
            item,
            "unified_social_credit_code",
            "credit_code",
        ),
        legal_person=_first_disclosed(
            item,
            "legal_person",
            "legal_representative",
            "representative",
        ),
        registered_capital=_first_disclosed(
            item,
            "registered_capital",
            "registration_capital",
        ),
        establish_date=_first_disclosed(
            item,
            "establish_date",
            "established_date",
            "established_at",
            "founding_date",
        ),
        company_address=_first_disclosed(
            item,
            "company_address",
            "registered_address",
            "registration_address",
            "business_address",
        ),
        business_scope=_first_disclosed(item, "business_scope"),
        company_status=_first_disclosed(
            item,
            "company_status",
            "registration_status",
        ),
        industry=_first_disclosed(item, "industry", "registered_industry"),
        ownership_type=ownership_type,
        company_scale=company_scale,
        ownership_confidence=ownership_confidence,
        ownership_basis=ownership_basis,
        company_scale_confidence=scale_confidence,
        company_scale_basis=scale_basis,
    )


def enrich_enhanced_enterprise_profile(
    item: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a copy with enhanced fields without mutating permit source data."""

    return dict(item) | build_enhanced_enterprise_profile(item).to_fields()


def filter_enhanced_profiles(
    profiles: Iterable[EnhancedEnterpriseProfile],
    *,
    ownership_type: str = ALL_FILTER,
    company_scale: str = ALL_FILTER,
) -> list[EnhancedEnterpriseProfile]:
    if ownership_type != ALL_FILTER and ownership_type not in OWNERSHIP_TYPE_OPTIONS:
        return []
    if company_scale != ALL_FILTER and company_scale not in COMPANY_SCALE_OPTIONS:
        return []
    return [
        profile
        for profile in profiles
        if (ownership_type == ALL_FILTER or profile.ownership_type == ownership_type)
        and (company_scale == ALL_FILTER or profile.company_scale == company_scale)
    ]


def assess_company_strength(
    item: Mapping[str, Any],
    *,
    profile: EnhancedEnterpriseProfile | None = None,
    today: date | None = None,
) -> CompanyStrengthAssessment:
    selected_profile = profile or build_enhanced_enterprise_profile(item)
    current_day = today or date.today()
    points = 0
    disclosed_dimensions = 0
    basis = []

    capital_yuan = _registered_capital_yuan(selected_profile.registered_capital)
    if capital_yuan is not None:
        disclosed_dimensions += 1
        capital_points = _capital_points(capital_yuan)
        points += capital_points
        basis.append(
            f"注册资本已披露，资本维度得 {capital_points}/3 分。"
        )
    else:
        basis.append("注册资本未披露，资本维度不计分。")

    company_age = _company_age(selected_profile.establish_date, current_day)
    if company_age is not None:
        disclosed_dimensions += 1
        age_points = _age_points(company_age)
        points += age_points
        basis.append(
            f"企业成立约 {company_age} 年，存续年限维度得 {age_points}/3 分。"
        )
    else:
        basis.append("成立日期未披露，存续年限维度不计分。")

    if selected_profile.company_scale != UNKNOWN_CLASSIFICATION:
        disclosed_dimensions += 1
        scale_points = {
            LARGE_COMPANY: 3,
            MEDIUM_COMPANY: 2,
            SMALL_COMPANY: 1,
            MICRO_COMPANY: 0,
        }.get(selected_profile.company_scale, 0)
        points += scale_points
        basis.append(
            f"企业规模为{selected_profile.company_scale}，规模维度得 {scale_points}/3 分。"
        )
    else:
        basis.append("企业规模未知，规模维度不计分。")

    if disclosed_dimensions < 2:
        level = "D"
        basis.append("三个实力维度中不足两个有数据，等级设为 D 信息不足。")
    elif points >= 7:
        level = "A"
    elif points >= 5:
        level = "B"
    else:
        level = "C"
    return CompanyStrengthAssessment(
        strength_level=level,
        strength_label=COMPANY_STRENGTH_LABELS[level],
        finance_component_score=COMPANY_STRENGTH_FINANCE_SCORES[level],
        rule_points=points,
        disclosed_dimension_count=disclosed_dimensions,
        assessment_basis=tuple(basis),
    )


def enrich_company_strength(
    item: Mapping[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    assessment = assess_company_strength(item, today=today)
    return dict(item) | assessment.to_fields()


def _ownership(item: Mapping[str, Any]) -> tuple[str, str, str]:
    owner_category = str(item.get("owner_category") or "").strip()
    mapped_category = _OWNER_CATEGORY_MAPPING.get(owner_category)
    if mapped_category:
        confidence = _ownership_confidence(item)
        basis = str(item.get("ownership_basis") or "").strip()
        return (
            mapped_category,
            confidence,
            basis or f"采用已有主体所有制分类：{owner_category}",
        )

    for field in (
        "registration_type",
        "enterprise_nature",
        "company_type",
        "ownership_nature",
        "ownership_type",
    ):
        raw_value = str(item.get(field) or "").strip()
        mapped_value = _explicit_ownership(raw_value)
        if mapped_value:
            return mapped_value, "high", f"工商登记字段 {field} 明确披露为“{raw_value}”"

    inferred = classify_permit_owner(
        item.get("company_name") or item.get("construction_unit") or ""
    )
    mapped_inferred = _OWNER_CATEGORY_MAPPING.get(inferred.owner_category)
    if mapped_inferred:
        confidence = "medium" if inferred.ownership_confidence >= 80 else "low"
        return mapped_inferred, confidence, inferred.ownership_basis

    return (
        UNKNOWN_CLASSIFICATION,
        "low",
        "现有许可证没有可靠工商登记类型或控股信息；不依据“有限公司”推断民营性质",
    )


def _company_scale(item: Mapping[str, Any]) -> tuple[str, str, str]:
    for field in ("company_scale", "enterprise_scale", "business_scale"):
        raw_value = str(item.get(field) or "").strip()
        normalized = _EXPLICIT_SCALE_MAPPING.get(raw_value)
        if normalized:
            return normalized, "high", f"企业规模字段 {field} 明确披露为“{raw_value}”"

    for field in (
        "employee_count",
        "insured_employee_count",
        "social_security_count",
    ):
        employee_count = _positive_integer(item.get(field))
        if employee_count is None:
            continue
        scale = _scale_from_employee_count(employee_count)
        return (
            scale,
            "medium",
            f"按 {field}={employee_count} 人进行通用规模分层；正式认定仍需结合行业标准和营业收入",
        )

    return (
        UNKNOWN_CLASSIFICATION,
        "low",
        "缺少企业规模、从业人数及营业收入信息，无法可靠判断规模",
    )


def _explicit_ownership(value: str) -> str | None:
    if not value:
        return None
    if value in _EXPLICIT_OWNERSHIP_MAPPING:
        return _EXPLICIT_OWNERSHIP_MAPPING[value]
    for keyword, normalized in _EXPLICIT_OWNERSHIP_MAPPING.items():
        if keyword in value:
            return normalized
    return None


def _ownership_confidence(item: Mapping[str, Any]) -> str:
    try:
        value = int(item.get("ownership_confidence") or 0)
    except (TypeError, ValueError):
        return "low"
    if value >= 90:
        return "high"
    if value >= 80:
        return "medium"
    return "low"


def _scale_from_employee_count(employee_count: int) -> str:
    if employee_count >= 1000:
        return LARGE_COMPANY
    if employee_count >= 300:
        return MEDIUM_COMPANY
    if employee_count >= 20:
        return SMALL_COMPANY
    return MICRO_COMPANY


def _positive_integer(value: Any) -> int | None:
    text = str(value or "").strip()
    match = _INTEGER_PATTERN.search(text)
    if match is None:
        return None
    try:
        number = int(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return number if number > 0 else None


def _registered_capital_yuan(value: Any) -> Decimal | None:
    text = str(value or "").strip()
    match = _CAPITAL_PATTERN.search(text)
    if match is None:
        return None
    try:
        amount = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    multiplier = {
        "亿元": Decimal("100000000"),
        "万元": Decimal("10000"),
        "元": Decimal("1"),
    }[match.group(2)]
    amount_yuan = amount * multiplier
    return amount_yuan if amount_yuan > 0 else None


def _capital_points(capital_yuan: Decimal) -> int:
    if capital_yuan >= Decimal("100000000"):
        return 3
    if capital_yuan >= Decimal("30000000"):
        return 2
    return 1


def _company_age(value: Any, today: date) -> int | None:
    text = str(value or "").strip()
    try:
        established = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    if established > today:
        return None
    return today.year - established.year - (
        (today.month, today.day) < (established.month, established.day)
    )


def _age_points(company_age: int) -> int:
    if company_age >= 10:
        return 3
    if company_age >= 5:
        return 2
    if company_age >= 2:
        return 1
    return 0


def _first_disclosed(item: Mapping[str, Any], *field_names: str) -> str:
    for field_name in field_names:
        text = _clean(item.get(field_name))
        if text:
            return text
    return UNKNOWN


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {UNKNOWN, UNKNOWN_CLASSIFICATION, "未知", "None", "null"}:
        return ""
    return text
