from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


UNKNOWN = "未披露"

PRIVATE_ENTERPRISE = "private_enterprise"
STATE_OWNED_COMMERCIAL = "state_owned_commercial"
GOVERNMENT_AGENCY = "government_agency"
PUBLIC_INSTITUTION = "public_institution"
MIXED_OWNERSHIP = "mixed_ownership"
FOREIGN_ENTERPRISE = "foreign_or_hk_macau_taiwan"
UNKNOWN_OWNERSHIP = "unknown"

OWNER_CATEGORIES = {
    PRIVATE_ENTERPRISE,
    STATE_OWNED_COMMERCIAL,
    GOVERNMENT_AGENCY,
    PUBLIC_INSTITUTION,
    MIXED_OWNERSHIP,
    FOREIGN_ENTERPRISE,
    UNKNOWN_OWNERSHIP,
}

OWNER_CATEGORY_LABELS = {
    PRIVATE_ENTERPRISE: "民营企业",
    STATE_OWNED_COMMERCIAL: "国有商业企业",
    GOVERNMENT_AGENCY: "政府机关",
    PUBLIC_INSTITUTION: "事业单位",
    MIXED_OWNERSHIP: "混合所有制",
    FOREIGN_ENTERPRISE: "外资或港澳台企业",
    UNKNOWN_OWNERSHIP: "待核验",
}

GOVERNMENT_KEYWORDS = (
    "人民政府",
    "政府办公室",
    "管理委员会",
    "管委会",
    "行政审批局",
    "自然资源和规划局",
    "住房和城乡建设局",
    "财政局",
    "公安局",
    "法院",
    "检察院",
    "街道办事处",
    "镇人民政府",
    "村民委员会",
    "居民委员会",
)

PUBLIC_INSTITUTION_KEYWORDS = (
    "事业单位",
    "公办学校",
    "公立医院",
    "公共卫生中心",
    "机关事务中心",
    "市政管理处",
    "公益服务中心",
)

STATE_OWNED_KEYWORDS = (
    "国有独资",
    "国有控股",
    "国资委",
    "国有资产经营",
    "国有资本投资",
    "城市建设投资",
    "城投集团",
    "城发集团",
    "交通产业集团",
    "水务集团",
    "政府投资平台",
    "国家电网",
    "国网",
    "国家石油天然气管网集团",
    "中远海运",
    "招商局",
)

PRIVATE_EVIDENCE_KEYWORDS = (
    "私营企业",
    "私营有限责任公司",
    "私营股份有限公司",
    "个人独资企业",
    "合伙企业",
    "自然人控股",
    "私人绝对控股",
    "私人相对控股",
)

MIXED_EVIDENCE_KEYWORDS = (
    "混合所有制",
    "国有资本与私人资本共同持股",
)

FOREIGN_EVIDENCE_KEYWORDS = (
    "外商独资企业",
    "外商投资企业",
    "港澳台商独资",
    "港澳台投资企业",
)

MISSING_OWNER_NAMES = {
    "",
    UNKNOWN,
    "未识别",
    "待核验",
    "建设单位暂未披露",
}


@dataclass(frozen=True)
class OwnershipClassification:
    owner_name: str
    owner_category: str
    ownership_type: str
    ownership_confidence: int
    ownership_basis: str
    marketing_eligible: bool
    marketing_priority: str
    exclusion_reason: str
    manual_review_required: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner_name": self.owner_name,
            "owner_category": self.owner_category,
            "ownership_type": self.ownership_type,
            "ownership_confidence": self.ownership_confidence,
            "ownership_basis": self.ownership_basis,
            "marketing_eligible": self.marketing_eligible,
            "marketing_priority": self.marketing_priority,
            "exclusion_reason": self.exclusion_reason,
            "manual_review_required": self.manual_review_required,
        }


def load_ownership_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    overrides: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            company_name = str(row.get("company_name") or "").strip()
            category = str(
                row.get("owner_category") or row.get("ownership_type") or ""
            ).strip()
            ownership_type = str(row.get("ownership_type") or category).strip()
            if (
                not company_name
                or category not in OWNER_CATEGORIES
                or ownership_type not in OWNER_CATEGORIES
            ):
                continue
            overrides[normalize_company_name(company_name)] = {
                key: str(value or "").strip()
                for key, value in row.items()
                if key
            }
    return overrides


def classify_permit_owner(
    company_name: Any,
    overrides: dict[str, dict[str, str]] | None = None,
) -> OwnershipClassification:
    owner_name = str(company_name or "").strip()
    normalized = normalize_company_name(owner_name)
    override = (overrides or {}).get(normalized)
    if override is not None:
        return _classification_from_override(owner_name, override)

    if owner_name in MISSING_OWNER_NAMES:
        return _build_classification(
            owner_name=UNKNOWN,
            category=UNKNOWN_OWNERSHIP,
            confidence=0,
            basis="建设单位缺失，无法判断所有制",
        )

    keyword = _first_keyword(owner_name, GOVERNMENT_KEYWORDS)
    if keyword:
        return _build_classification(
            owner_name=owner_name,
            category=GOVERNMENT_AGENCY,
            confidence=95,
            basis=f"建设单位名称明确包含政府机关关键词“{keyword}”",
        )

    keyword = _first_keyword(owner_name, PUBLIC_INSTITUTION_KEYWORDS)
    if keyword:
        return _build_classification(
            owner_name=owner_name,
            category=PUBLIC_INSTITUTION,
            confidence=95,
            basis=f"建设单位名称明确包含事业单位或公益机构关键词“{keyword}”",
        )

    keyword = _first_keyword(owner_name, STATE_OWNED_KEYWORDS)
    if keyword:
        return _build_classification(
            owner_name=owner_name,
            category=STATE_OWNED_COMMERCIAL,
            confidence=85,
            basis=f"建设单位名称明确包含国有商业主体关键词“{keyword}”",
        )

    if _is_local_construction_investment_platform(owner_name):
        return _build_classification(
            owner_name=owner_name,
            category=STATE_OWNED_COMMERCIAL,
            confidence=85,
            basis="海门地方建设投资平台名称特征明确",
        )

    keyword = _first_keyword(owner_name, PRIVATE_EVIDENCE_KEYWORDS)
    if keyword:
        return _build_classification(
            owner_name=owner_name,
            category=PRIVATE_ENTERPRISE,
            confidence=80,
            basis=f"主体信息明确包含民营所有制证据“{keyword}”",
        )

    keyword = _first_keyword(owner_name, MIXED_EVIDENCE_KEYWORDS)
    if keyword:
        return _build_classification(
            owner_name=owner_name,
            category=MIXED_OWNERSHIP,
            confidence=80,
            basis=f"主体信息明确包含混合所有制证据“{keyword}”",
        )

    keyword = _first_keyword(owner_name, FOREIGN_EVIDENCE_KEYWORDS)
    if keyword:
        return _build_classification(
            owner_name=owner_name,
            category=FOREIGN_ENTERPRISE,
            confidence=80,
            basis=f"主体信息明确包含外资或港澳台所有制证据“{keyword}”",
        )

    return _build_classification(
        owner_name=owner_name,
        category=UNKNOWN_OWNERSHIP,
        confidence=0,
        basis="现有许可证仅披露单位名称，没有可靠登记类型或控股信息",
    )


def owner_category_label(value: Any) -> str:
    return OWNER_CATEGORY_LABELS.get(str(value or ""), OWNER_CATEGORY_LABELS[UNKNOWN_OWNERSHIP])


def normalize_company_name(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def _classification_from_override(
    fallback_owner_name: str,
    override: dict[str, str],
) -> OwnershipClassification:
    category = override.get("owner_category") or override.get("ownership_type") or UNKNOWN_OWNERSHIP
    ownership_type = override.get("ownership_type") or category
    eligible = _parse_bool(
        override.get("marketing_eligible"),
        default=category in {
            PRIVATE_ENTERPRISE,
            STATE_OWNED_COMMERCIAL,
            MIXED_OWNERSHIP,
            FOREIGN_ENTERPRISE,
        },
    )
    priority = override.get("marketing_priority") or _category_defaults(category)[1]
    basis = override.get("classification_basis") or "人工分类表确认"
    owner_name = override.get("company_name") or fallback_owner_name or UNKNOWN
    exclusion_reason = ""
    if not eligible:
        exclusion_reason = (
            "政府机关或财政项目"
            if category == GOVERNMENT_AGENCY
            else "事业单位或公益项目"
            if category == PUBLIC_INSTITUTION
            else "人工分类结果暂不纳入营销"
        )
    return OwnershipClassification(
        owner_name=owner_name,
        owner_category=category,
        ownership_type=ownership_type,
        ownership_confidence=100,
        ownership_basis=basis,
        marketing_eligible=eligible,
        marketing_priority=priority,
        exclusion_reason=exclusion_reason,
        manual_review_required=category in {MIXED_OWNERSHIP, UNKNOWN_OWNERSHIP},
    )


def _build_classification(
    *,
    owner_name: str,
    category: str,
    confidence: int,
    basis: str,
) -> OwnershipClassification:
    eligible, priority, exclusion_reason, category_review = _category_defaults(category)
    return OwnershipClassification(
        owner_name=owner_name or UNKNOWN,
        owner_category=category,
        ownership_type=category,
        ownership_confidence=confidence,
        ownership_basis=basis,
        marketing_eligible=eligible,
        marketing_priority=priority,
        exclusion_reason=exclusion_reason,
        manual_review_required=category_review or confidence < 80,
    )


def _category_defaults(category: str) -> tuple[bool, str, str, bool]:
    if category == PRIVATE_ENTERPRISE:
        return True, "A", "", False
    if category == FOREIGN_ENTERPRISE:
        return True, "A", "", False
    if category == STATE_OWNED_COMMERCIAL:
        return True, "B", "", False
    if category == MIXED_OWNERSHIP:
        return True, "B", "", True
    if category == GOVERNMENT_AGENCY:
        return False, "排除", "政府机关或财政项目", False
    if category == PUBLIC_INSTITUTION:
        return False, "排除", "事业单位或公益项目", True
    return False, "待核验", "", True


def _is_local_construction_investment_platform(name: str) -> bool:
    is_local = any(keyword in name for keyword in ("南通市海门", "海门区", "海门市"))
    return is_local and "建设投资" in name


def _first_keyword(value: str, keywords: tuple[str, ...]) -> str:
    return next((keyword for keyword in keywords if keyword in value), "")


def _parse_bool(value: Any, *, default: bool) -> bool:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "是"}:
        return True
    if text in {"false", "0", "no", "n", "否"}:
        return False
    return default
