from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping


FACTORY_KEYWORDS = (
    "厂房",
    "工厂",
    "车间",
    "生产基地",
    "产业园",
    "仓库",
)
EQUIPMENT_KEYWORDS = (
    "设备采购",
    "设备",
    "装备",
    "生产线",
    "产线",
    "机器",
    "机械",
    "机组",
    "智能化",
    "自动化",
)
EXPANSION_KEYWORDS = (
    "生产扩建",
    "扩建",
    "改扩建",
    "扩产",
    "产能提升",
    "技改",
    "技术改造",
)
HIGH_CAPITAL_KEYWORDS = (
    "新能源",
    "半导体",
    "芯片",
    "集成电路",
    "光伏",
    "风电",
    "储能",
    "钢铁",
    "化工",
    "新材料",
    "汽车",
    "电池",
)
LIGHT_INDUSTRY_KEYWORDS = ("食品", "饮料", "纺织", "家纺", "服装")
LARGE_SCALE_KEYWORDS = ("生产基地", "产业园", "年产", "总部", "二期", "三期")
RETROFIT_KEYWORDS = ("技改", "技术改造", "设备升级", "改造项目")

LAND_PERMIT_TYPE = "建设用地规划许可证"
PLANNING_PERMIT_TYPE = "建设工程规划许可证"
START_PERMIT_TYPE = "建设工程施工许可证"

ESTIMATION_NOT_APPLICABLE = "不进入企业融资推荐"
ESTIMATION_CONFIDENCE_LABELS = {
    "medium": "中（存在公开金额，授信比例仍为规则估算）",
    "low": "低（公开金额缺失，投资和授信均为规则区间）",
    "not_applicable": "不适用",
}

_CATEGORY_RANGES_WAN = {
    "factory": (Decimal("5000"), Decimal("20000")),
    "equipment": (Decimal("2000"), Decimal("10000")),
    "expansion": (Decimal("1000"), Decimal("6000")),
    "land_stage": (Decimal("8000"), Decimal("30000")),
    "planning_stage": (Decimal("5000"), Decimal("20000")),
    "start_stage": (Decimal("3000"), Decimal("15000")),
    "generic": (Decimal("2000"), Decimal("10000")),
}
_CREDIT_RATIOS = {
    "factory": (Decimal("0.60"), Decimal("0.70")),
    "equipment": (Decimal("0.70"), Decimal("0.70")),
    "expansion": (Decimal("0.20"), Decimal("0.35")),
    "land_stage": (Decimal("0.50"), Decimal("0.60")),
    "planning_stage": (Decimal("0.60"), Decimal("0.70")),
    "start_stage": (Decimal("0.50"), Decimal("0.70")),
    "generic": (Decimal("0.40"), Decimal("0.60")),
}
_MONEY_PATTERN = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|元)")


@dataclass(frozen=True)
class FinanceEstimation:
    estimated_investment: str
    estimated_credit_need: str
    recommended_product: str
    estimation_confidence: str
    estimation_basis: tuple[str, ...]
    investment_min_yuan: int | None
    investment_max_yuan: int | None
    credit_need_min_yuan: int | None
    credit_need_max_yuan: int | None
    eligible_for_estimation: bool

    def to_fields(self) -> dict[str, Any]:
        return {
            "estimated_investment": self.estimated_investment,
            "estimated_credit_need": self.estimated_credit_need,
            "recommended_product": self.recommended_product,
            "finance_estimation_confidence": self.estimation_confidence,
            "finance_estimation_basis": list(self.estimation_basis),
            "estimated_investment_min_yuan": self.investment_min_yuan,
            "estimated_investment_max_yuan": self.investment_max_yuan,
            "estimated_credit_need_min_yuan": self.credit_need_min_yuan,
            "estimated_credit_need_max_yuan": self.credit_need_max_yuan,
            "eligible_for_finance_estimation": self.eligible_for_estimation,
        }


def estimate_finance_need(item: Mapping[str, Any]) -> FinanceEstimation:
    """Estimate a financing range from disclosed amounts and explainable rules."""

    if str(item.get("project_type") or "unknown").strip() == "government":
        return FinanceEstimation(
            estimated_investment=ESTIMATION_NOT_APPLICABLE,
            estimated_credit_need=ESTIMATION_NOT_APPLICABLE,
            recommended_product=ESTIMATION_NOT_APPLICABLE,
            estimation_confidence="not_applicable",
            estimation_basis=("政府/公共机构项目不进入企业融资金额预测。",),
            investment_min_yuan=None,
            investment_max_yuan=None,
            credit_need_min_yuan=None,
            credit_need_max_yuan=None,
            eligible_for_estimation=False,
        )

    text = _project_text(item)
    categories = _detected_categories(text)
    permit_type = str(item.get("permit_type") or "").strip()
    primary_rule = categories[0] if categories else _permit_stage_rule(permit_type)
    products = _recommended_products(categories, permit_type)
    basis = [
        _category_basis(categories, primary_rule),
        f"许可证阶段：{permit_type or '未披露'}。",
    ]

    disclosed_amount, disclosed_field = _disclosed_investment(item)
    if disclosed_amount is not None:
        investment_min = disclosed_amount
        investment_max = disclosed_amount
        confidence = "medium"
        basis.append(f"投资规模采用字段“{disclosed_field}”中的公开金额。")
    else:
        investment_min, investment_max = _CATEGORY_RANGES_WAN[primary_rule]
        multiplier, multiplier_basis = _capital_multiplier(text)
        investment_min = _rounded_wan(investment_min * multiplier)
        investment_max = _rounded_wan(investment_max * multiplier)
        investment_min *= Decimal("10000")
        investment_max *= Decimal("10000")
        confidence = "low"
        basis.append(
            "公开投资金额缺失，按项目关键词和许可证阶段的基础区间估算。"
        )
        basis.extend(multiplier_basis)

    minimum_ratio, maximum_ratio = _CREDIT_RATIOS[primary_rule]
    credit_min = _rounded_yuan(investment_min * minimum_ratio)
    credit_max = _rounded_yuan(investment_max * maximum_ratio)
    basis.append(_ratio_basis(primary_rule, minimum_ratio, maximum_ratio))
    basis.append("金额仅用于营销线索排序，需以企业可研、合同和财务资料复核。")

    investment_note = "公开金额" if disclosed_amount is not None else "规则估算"
    return FinanceEstimation(
        estimated_investment=(
            f"{_format_yuan_range(investment_min, investment_max)}（{investment_note}）"
        ),
        estimated_credit_need=f"{_format_yuan_range(credit_min, credit_max)}（规则估算）",
        recommended_product="、".join(products),
        estimation_confidence=confidence,
        estimation_basis=tuple(basis),
        investment_min_yuan=int(investment_min),
        investment_max_yuan=int(investment_max),
        credit_need_min_yuan=int(credit_min),
        credit_need_max_yuan=int(credit_max),
        eligible_for_estimation=True,
    )


def enrich_finance_estimation(item: Mapping[str, Any]) -> dict[str, Any]:
    estimation = estimate_finance_need(item)
    return dict(item) | estimation.to_fields()


def enrich_finance_estimations(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [enrich_finance_estimation(item) for item in items]


def estimation_confidence_label(value: str) -> str:
    return ESTIMATION_CONFIDENCE_LABELS.get(value, ESTIMATION_CONFIDENCE_LABELS["low"])


def _project_text(item: Mapping[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "")
        for field in (
            "project_name",
            "industry",
            "project_scale",
            "company_name",
            "construction_unit",
        )
    )


def _detected_categories(text: str) -> tuple[str, ...]:
    categories = []
    if _contains_any(text, FACTORY_KEYWORDS):
        categories.append("factory")
    if _contains_any(text, EQUIPMENT_KEYWORDS):
        categories.append("equipment")
    if _contains_any(text, EXPANSION_KEYWORDS):
        categories.append("expansion")
    return tuple(categories)


def _permit_stage_rule(permit_type: str) -> str:
    if permit_type == LAND_PERMIT_TYPE:
        return "land_stage"
    if permit_type == PLANNING_PERMIT_TYPE:
        return "planning_stage"
    if permit_type == START_PERMIT_TYPE:
        return "start_stage"
    return "generic"


def _recommended_products(
    categories: tuple[str, ...],
    permit_type: str,
) -> tuple[str, ...]:
    products = []
    if "factory" in categories:
        products.append("固定资产贷款")
    if "equipment" in categories:
        products.append("设备贷款")
    if "expansion" in categories:
        products.append("流动资金贷款")
    if not products:
        if permit_type == LAND_PERMIT_TYPE:
            products.extend(("土地贷款", "项目贷款"))
        elif permit_type == PLANNING_PERMIT_TYPE:
            products.extend(("固定资产贷款", "项目贷款"))
        elif permit_type == START_PERMIT_TYPE:
            products.extend(("设备贷款", "流动资金贷款"))
        else:
            products.append("项目贷款")
    return tuple(dict.fromkeys(products))


def _category_basis(categories: tuple[str, ...], primary_rule: str) -> str:
    labels = {
        "factory": "厂房建设类",
        "equipment": "设备采购类",
        "expansion": "生产扩建类",
        "land_stage": "拿地阶段项目",
        "planning_stage": "建设准备阶段项目",
        "start_stage": "开工阶段项目",
        "generic": "一般项目",
    }
    if categories:
        detected = "、".join(labels[category] for category in categories)
        return f"项目关键词识别：{detected}；金额比例按“{labels[primary_rule]}”主规则计算。"
    return f"项目关键词未形成专项类别，采用“{labels[primary_rule]}”阶段规则。"


def _disclosed_investment(
    item: Mapping[str, Any],
) -> tuple[Decimal | None, str | None]:
    for field in ("investment", "investment_amount", "project_scale"):
        amount = _parse_money(item.get(field))
        if amount is not None:
            return amount, field
    return None, None


def _parse_money(value: Any) -> Decimal | None:
    text = str(value or "").strip()
    if not text or text in {"未披露", "未知", "None", "null"}:
        return None
    amounts = []
    for amount_text, unit in _MONEY_PATTERN.findall(text):
        try:
            amount = Decimal(amount_text.replace(",", ""))
        except InvalidOperation:
            continue
        multiplier = {
            "亿元": Decimal("100000000"),
            "万元": Decimal("10000"),
            "元": Decimal("1"),
        }[unit]
        if amount > 0:
            amounts.append(amount * multiplier)
    return max(amounts) if amounts else None


def _capital_multiplier(text: str) -> tuple[Decimal, list[str]]:
    multiplier = Decimal("1")
    basis = []
    if _contains_any(text, HIGH_CAPITAL_KEYWORDS):
        multiplier *= Decimal("1.40")
        basis.append("资本密集型行业关键词使基础投资区间上调40%。")
    elif _contains_any(text, LIGHT_INDUSTRY_KEYWORDS):
        multiplier *= Decimal("0.80")
        basis.append("轻工行业关键词使基础投资区间下调20%。")
    if _contains_any(text, LARGE_SCALE_KEYWORDS):
        multiplier *= Decimal("1.25")
        basis.append("生产基地、产业园、年产或分期建设关键词使区间上调25%。")
    if _contains_any(text, RETROFIT_KEYWORDS):
        multiplier *= Decimal("0.75")
        basis.append("技改或设备升级关键词使区间下调25%。")
    multiplier = min(max(multiplier, Decimal("0.60")), Decimal("2.00"))
    if not basis:
        basis.append("未识别到行业或规模调整信号，保持基础投资区间。")
    return multiplier, basis


def _ratio_basis(
    rule: str,
    minimum_ratio: Decimal,
    maximum_ratio: Decimal,
) -> str:
    labels = {
        "factory": "厂房建设",
        "equipment": "设备采购",
        "expansion": "生产扩建流动资金",
        "land_stage": "拿地阶段",
        "planning_stage": "建设准备阶段",
        "start_stage": "开工阶段",
        "generic": "一般项目",
    }
    if minimum_ratio == maximum_ratio:
        ratio_text = f"{int(minimum_ratio * 100)}%"
    else:
        ratio_text = f"{int(minimum_ratio * 100)}%-{int(maximum_ratio * 100)}%"
    return f"{labels[rule]}授信比例按预计投资规模的{ratio_text}计算。"


def _rounded_wan(value: Decimal) -> Decimal:
    return (value / Decimal("100")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    ) * Decimal("100")


def _rounded_yuan(value: Decimal) -> Decimal:
    return (value / Decimal("10000")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    ) * Decimal("10000")


def _format_yuan_range(minimum: Decimal, maximum: Decimal) -> str:
    if minimum == maximum:
        return _format_yuan(minimum)
    if maximum >= Decimal("100000000"):
        return f"{_format_yi(minimum)}–{_format_yi(maximum)}"
    return f"{_format_wan(minimum)}–{_format_wan(maximum)}"


def _format_yuan(value: Decimal) -> str:
    if value >= Decimal("100000000"):
        return _format_yi(value)
    return _format_wan(value)


def _format_yi(value: Decimal) -> str:
    amount = value / Decimal("100000000")
    return f"{_decimal_text(amount)}亿元"


def _format_wan(value: Decimal) -> str:
    amount = value / Decimal("10000")
    if amount == amount.to_integral_value():
        return f"{int(amount):,}万元"
    return f"{_decimal_text(amount)}万元"


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
