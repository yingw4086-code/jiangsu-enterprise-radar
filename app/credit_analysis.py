from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.enterprise_profile import EnterpriseProfile, UNKNOWN, build_enterprise_profile
from app.finance_estimation import estimate_finance_need


FACTORY_KEYWORDS = ("厂房", "工厂", "车间")
EQUIPMENT_KEYWORDS = ("设备采购", "设备", "装备", "生产线", "产线", "机器", "机械")
EXPANSION_KEYWORDS = ("生产扩建", "扩建", "扩产", "技改", "技术改造", "产能提升")

PERMIT_STAGE_PRODUCTS = {
    "建设用地规划许可证": ("土地贷款", "项目贷款"),
    "建设工程规划许可证": ("固定资产贷款", "项目贷款"),
    "建设工程施工许可证": ("设备贷款", "流动资金贷款", "项目贷款"),
}


@dataclass(frozen=True)
class CreditOpportunityAnalysis:
    estimated_financing_need: str
    recommended_products: tuple[str, ...]
    suggested_marketing_time: str
    visit_advice: str
    eligible_for_analysis: bool


@dataclass(frozen=True)
class ReportSection:
    title: str
    content: str


@dataclass(frozen=True)
class EnterpriseFinancingReport:
    title: str
    sections: tuple[ReportSection, ...]
    analysis_method: str = "本地规则分析"


def analyze_credit_opportunity(
    item: Mapping[str, Any],
    *,
    profile: EnterpriseProfile | None = None,
) -> CreditOpportunityAnalysis:
    selected_profile = profile or build_enterprise_profile(item)
    if str(item.get("project_type") or "unknown") == "government":
        return CreditOpportunityAnalysis(
            estimated_financing_need="政府/公共机构项目不进入企业融资推荐",
            recommended_products=(),
            suggested_marketing_time="不进入企业融资推荐",
            visit_advice="如需参与，应按政府项目及公共融资合规流程另行评估。",
            eligible_for_analysis=False,
        )

    project_text = " ".join(
        (
            selected_profile.project_name,
            selected_profile.industry,
            str(item.get("project_scale") or ""),
        )
    )
    needs: list[str] = []
    products: list[str] = []
    if _contains_any(project_text, FACTORY_KEYWORDS):
        needs.append("厂房建设资金需求：预测固定资产贷款")
        products.append("固定资产贷款")
    if _contains_any(project_text, EQUIPMENT_KEYWORDS):
        needs.append("设备采购资金需求：预测设备贷款")
        products.append("设备贷款")
    if _contains_any(project_text, EXPANSION_KEYWORDS):
        needs.append("生产扩建资金需求：预测流动资金贷款")
        products.append("流动资金贷款")

    permit_type = str(item.get("permit_type") or "").strip()
    stage_products = PERMIT_STAGE_PRODUCTS.get(permit_type, ("项目贷款",))
    products.extend(stage_products)
    products.extend(_split_products(item.get("loan_type")))
    products = _deduplicate(products)

    if not needs:
        needs.append(_stage_financing_need(permit_type, products))

    score = _integer(item.get("finance_score"))
    level = str(item.get("finance_level") or "C")
    return CreditOpportunityAnalysis(
        estimated_financing_need="；".join(needs),
        recommended_products=tuple(products),
        suggested_marketing_time=str(
            item.get("suggested_contact_time") or "建议30天内复核"
        ),
        visit_advice=_visit_advice(selected_profile, score, level),
        eligible_for_analysis=True,
    )


def enrich_credit_opportunity(item: Mapping[str, Any]) -> dict[str, Any]:
    analysis = analyze_credit_opportunity(item)
    return dict(item) | {
        "estimated_financing_need": analysis.estimated_financing_need,
        "recommended_bank_products": list(analysis.recommended_products),
        "credit_visit_advice": analysis.visit_advice,
    }


def build_financing_report(
    item: Mapping[str, Any],
    *,
    profile: EnterpriseProfile | None = None,
) -> EnterpriseFinancingReport:
    selected_profile = profile or build_enterprise_profile(item)
    analysis = analyze_credit_opportunity(item, profile=selected_profile)
    estimation = estimate_finance_need(item)
    investment = _disclosed(item.get("investment"))
    project_scale = _disclosed(item.get("project_scale"))
    score = _integer(item.get("finance_score"))
    level = str(item.get("finance_level") or "C")
    permit_type = _disclosed(item.get("permit_type"))
    products = "、".join(analysis.recommended_products) or "不进入企业融资推荐"

    return EnterpriseFinancingReport(
        title="《企业融资机会分析报告》",
        sections=(
            ReportSection(
                "1. 企业基本情况",
                f"企业名称：{selected_profile.company_name}；企业类型：{selected_profile.enterprise_type}；"
                f"所属地区：{selected_profile.region}；所属行业：{selected_profile.industry}；"
                f"成立时间：{selected_profile.established_time}；注册资本：{selected_profile.registered_capital}；"
                f"企业信用等级：{selected_profile.enterprise_credit_level}。",
            ),
            ReportSection(
                "2. 项目投资情况",
                f"项目名称：{selected_profile.project_name}；公开投资金额：{investment}；"
                f"公开建设规模：{project_scale}；预计投资规模：{estimation.estimated_investment}；"
                f"融资机会评分：{score}分（{level}级）。",
            ),
            ReportSection(
                "3. 当前建设阶段",
                f"许可证类型：{permit_type}；判断阶段：{selected_profile.project_stage}。",
            ),
            ReportSection(
                "4. 可能融资需求",
                f"{analysis.estimated_financing_need}；"
                f"预计授信金额：{estimation.estimated_credit_need}。",
            ),
            ReportSection("5. 推荐银行产品", products),
            ReportSection("6. 建议营销时间", analysis.suggested_marketing_time),
            ReportSection("7. 客户经理拜访建议", analysis.visit_advice),
        ),
    )


def _stage_financing_need(permit_type: str, products: list[str]) -> str:
    if permit_type == "建设用地规划许可证":
        return "项目处于拿地阶段，预测土地取得及项目前期资金需求"
    if permit_type == "建设工程规划许可证":
        return "项目处于建设准备阶段，预测固定资产及项目建设资金需求"
    if permit_type == "建设工程施工许可证":
        return "项目处于开工阶段，预测设备采购、项目建设及流动资金需求"
    return f"项目资金需求待访谈核验，初步可关注：{'、'.join(products)}"


def _visit_advice(profile: EnterpriseProfile, score: int, level: str) -> str:
    focus = ["项目总投资及自有资金比例", "建设进度", "现有授信和担保安排"]
    if profile.established_time == UNKNOWN:
        focus.append("成立时间")
    if profile.registered_capital == UNKNOWN:
        focus.append("注册资本")
    if profile.enterprise_credit_level.startswith("未评级"):
        focus.append("征信及近三年财务数据")
    priority = "优先安排现场拜访" if level == "A" or score >= 70 else "先电话核实项目真实性和资金计划"
    return f"{priority}，重点核验{'、'.join(focus)}；规则分析结果仅作为营销线索，不作为授信审批结论。"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _split_products(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("/", "、").split("、") if part.strip()]


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _disclosed(value: Any) -> str:
    text = str(value or "").strip()
    return text if text and text not in {UNKNOWN, "未知"} else UNKNOWN


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
