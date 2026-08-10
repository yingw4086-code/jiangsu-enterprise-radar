from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


UNKNOWN_INDUSTRY = "待判断"
INDUSTRY_RULES = (
    ("新能源产业", ("新能源", "光伏", "风电", "储能", "锂电")),
    ("电子信息产业", ("半导体", "电子", "集成电路", "信息技术", "智能终端")),
    ("装备制造业", ("装备", "机械", "设备", "机器人", "数控")),
    ("新材料产业", ("新材料", "材料", "合金", "纤维", "复合材料")),
    ("生物医药产业", ("医药", "生物", "医疗器械", "药品")),
    ("食品制造业", ("食品", "饮料", "粮油", "营养")),
    ("建筑与房地产业", ("建筑", "建设", "房地产", "产业园", "厂房")),
    ("通用制造业", ("制造", "生产", "加工", "扩建", "技改")),
)


@dataclass(frozen=True)
class IndustryAssessment:
    industry_classification: str
    industry_classification_confidence: str
    industry_classification_basis: str

    def to_fields(self) -> dict[str, Any]:
        return asdict(self)


def assess_industry(item: Mapping[str, Any]) -> IndustryAssessment:
    raw_industry = str(item.get("industry") or "").strip()
    disclosed_fields = {
        str(value) for value in (item.get("registry_disclosed_fields") or [])
    }
    if raw_industry and raw_industry not in {"未披露", "未知", "待判断"}:
        if "industry" in disclosed_fields:
            return IndustryAssessment(
                industry_classification=raw_industry,
                industry_classification_confidence="high",
                industry_classification_basis="工商导入字段“行业分类”已明确披露",
            )

    search_parts = (
        raw_industry,
        str(item.get("business_scope") or ""),
        str(item.get("project_name") or ""),
        str(item.get("company_name") or item.get("construction_unit") or ""),
    )
    search_text = " ".join(search_parts)
    for category, keywords in INDUSTRY_RULES:
        matched = [keyword for keyword in keywords if keyword in search_text]
        if matched:
            return IndustryAssessment(
                industry_classification=category,
                industry_classification_confidence="medium",
                industry_classification_basis=(
                    "根据工商经营范围、项目名称或企业名称关键词判断："
                    + "、".join(matched)
                ),
            )

    return IndustryAssessment(
        industry_classification=UNKNOWN_INDUSTRY,
        industry_classification_confidence="low",
        industry_classification_basis="当前工商与项目字段缺少可解释的行业关键词",
    )


def enrich_industry_assessment(item: Mapping[str, Any]) -> dict[str, Any]:
    return dict(item) | assess_industry(item).to_fields()
