from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


UNKNOWN = "未披露"
DEFAULT_REGION_KEY = "320684"
LEVEL_SORT_ORDER = {"A": 0, "B": 1, "C": 2}


@dataclass(frozen=True)
class DashboardRecord:
    enterprise_name: str
    project_name: str
    industry: str
    investment_amount: str
    project_address: str
    discovery_time: str
    data_source: str
    customer_level: str
    financing_need: str
    recommended_products: str
    approval_item: str
    source_url: str
    source_title: str
    marketing_advice: str
    reason: str
    confidence: float
    raw: dict[str, Any]

    def to_table_row(self) -> dict[str, Any]:
        return {
            "企业名称": self.enterprise_name,
            "项目名称": self.project_name,
            "所属行业": self.industry,
            "投资金额": self.investment_amount,
            "项目地址": self.project_address,
            "发现时间": self.discovery_time,
            "数据来源": self.data_source,
            "AI客户等级(A/B/C)": self.customer_level,
            "融资需求判断": self.financing_need,
            "推荐贷款产品": self.recommended_products,
        }


def load_records(
    ai_data_dir: Path,
    *,
    region_key: str | None = None,
) -> list[DashboardRecord]:
    selected_region = _validated_region_key(region_key)
    files = sorted(ai_data_dir.glob("financing_analysis_*.json"))
    records: list[DashboardRecord] = []
    for file_path in files:
        records.extend(_load_file(file_path, selected_region))
    return _dedupe_records(records)


def latest_json_files(ai_data_dir: Path, limit: int = 5) -> list[Path]:
    return sorted(ai_data_dir.glob("financing_analysis_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]


def summarize(records: list[DashboardRecord], today: date | None = None) -> dict[str, Any]:
    target_day = today or date.today()
    today_records = [record for record in records if _parse_date(record.discovery_time) == target_day]
    a_records = [record for record in records if record.customer_level == "A"]
    construction_project_records = [record for record in today_records if _is_construction_license_record(record)]
    construction_permit_records = [record for record in today_records if "建设工程施工许可证" in _record_text(record)]
    planning_permit_records = [
        record
        for record in today_records
        if "建设用地规划许可证" in _record_text(record) or "建设工程规划许可证" in _record_text(record)
    ]
    high_value_records = [
        record
        for record in records
        if record.customer_level == "A" or _record_score(record) >= 70
    ]
    focus_enterprises = {
        record.enterprise_name
        for record in records
        if record.enterprise_name != UNKNOWN and record.customer_level in {"A", "B"}
    }
    amount = sum(parse_amount_to_yuan(record.investment_amount) for record in records)
    return {
        "today_new_projects": len(today_records),
        "a_level_count": len(a_records),
        "estimated_financing_amount_yuan": amount,
        "focus_enterprise_count": len(focus_enterprises),
        "total_count": len(records),
        "today_construction_project_count": len(construction_project_records),
        "new_construction_permit_count": len(construction_permit_records),
        "new_planning_permit_count": len(planning_permit_records),
        "high_value_loan_opportunity_count": len(high_value_records),
    }


def filter_records(
    records: list[DashboardRecord],
    search: str = "",
    level: str = "全部",
    industry: str = "全部",
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[DashboardRecord]:
    search_text = search.strip().lower()
    result = []
    for record in records:
        if search_text:
            combined = f"{record.enterprise_name} {record.project_name} {record.source_title}".lower()
            if search_text not in combined:
                continue
        if level != "全部" and record.customer_level != level:
            continue
        if industry != "全部" and record.industry != industry:
            continue
        record_date = _parse_date(record.discovery_time)
        if start_date and record_date and record_date < start_date:
            continue
        if end_date and record_date and record_date > end_date:
            continue
        result.append(record)
    return result


def industry_options(records: list[DashboardRecord]) -> list[str]:
    values = sorted({record.industry for record in records if record.industry and record.industry != UNKNOWN})
    return ["全部"] + values


def sort_marketing_tasks(records: list[DashboardRecord]) -> list[DashboardRecord]:
    return sorted(
        records,
        key=lambda record: (
            LEVEL_SORT_ORDER.get(record.customer_level, 99),
            -parse_amount_to_yuan(record.investment_amount),
            -record.confidence,
            record.enterprise_name,
        ),
    )


def marketing_priority_stars(record: DashboardRecord) -> str:
    amount = parse_amount_to_yuan(record.investment_amount)
    if record.customer_level == "A" and amount >= 100_000_000:
        count = 5
    elif record.customer_level == "A":
        count = 4
    elif record.customer_level == "B":
        count = 3
    else:
        count = 2
    return "★" * count + "☆" * (5 - count)


def suggest_visit_time(record: DashboardRecord) -> str:
    stage = infer_project_stage(record)
    if record.customer_level == "A":
        if stage in {"建设准备期", "规划审批期"}:
            return "建议 3 个工作日内拜访"
        return "建议本周内电话沟通"
    if record.customer_level == "B":
        return "建议 1-2 周内跟进"
    return "纳入观察名单，月度复盘"


def infer_project_type(record: DashboardRecord) -> str:
    text = f"{record.approval_item} {record.project_name} {record.source_title}"
    if "备案" in text:
        return "项目备案"
    if "建设工程规划许可证" in text:
        return "建设工程规划许可"
    if "建设用地规划许可证" in text:
        return "建设用地规划许可"
    if "施工" in text:
        return "施工许可"
    return record.approval_item if record.approval_item != UNKNOWN else "建设项目"


def infer_project_stage(record: DashboardRecord) -> str:
    text = f"{record.approval_item} {record.project_name} {record.source_title}"
    if "施工" in text or "开工" in text:
        return "建设推进期"
    if "备案" in text or "批复" in text:
        return "建设准备期"
    if "用地" in text or "规划" in text:
        return "规划审批期"
    if "竣工" in text or "验收" in text:
        return "投产验收期"
    return "线索核实期"


def infer_financing_window(record: DashboardRecord) -> str:
    project_type = infer_project_type(record)
    current_stage = infer_project_stage(record)
    analysis_text = (
        f"{record.financing_need} {record.customer_level} {record.recommended_products} "
        f"{record.reason} {record.project_name} {record.approval_item} {record.source_title} "
        f"{project_type} {current_stage}"
    )

    if any(keyword in analysis_text for keyword in ["施工许可证", "开工", "设备采购", "建设工程"]):
        return "立即（0-3个月）"
    if any(keyword in analysis_text for keyword in ["土地", "规划许可证", "用地审批", "环评"]):
        return "近期（3-6个月）"
    if any(keyword in analysis_text for keyword in ["投资备案", "项目规划", "项目备案", "备案"]):
        return "中期（6-12个月）"
    return "未知"


def infer_risk_level(record: DashboardRecord) -> str:
    if record.confidence < 0.5:
        return "中"
    if record.customer_level == "C" or record.financing_need != "存在":
        return "中"
    if record.enterprise_name == UNKNOWN or record.project_name == UNKNOWN:
        return "中"
    return "低"


def format_yuan(value: float) -> str:
    if value <= 0:
        return "未披露"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f} 亿元"
    if value >= 10_000:
        return f"{value / 10_000:.0f} 万元"
    return f"{value:.0f} 元"


def parse_amount_to_yuan(value: str) -> float:
    if not value or value == UNKNOWN:
        return 0.0
    text = str(value).replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(亿元|亿|万元|万|元)", text)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2)
    if unit in {"亿元", "亿"}:
        return number * 100_000_000
    if unit in {"万元", "万"}:
        return number * 10_000
    return number


def infer_financing_opportunities(record: DashboardRecord) -> dict[str, bool]:
    products = record.recommended_products
    text = f"{record.project_name} {record.approval_item} {products} {record.reason}"
    return {
        "固定资产贷款": any(key in text for key in ["固定资产", "项目贷款", "新建", "扩建", "建设", "厂房"]),
        "流动资金贷款": any(key in text for key in ["流动资金", "周转", "生产", "订单", "运营"]),
        "设备贷款": any(key in text for key in ["设备", "装备", "产线", "生产线", "机器"]),
        "开户机会": record.customer_level in {"A", "B"} and record.financing_need == "存在",
        "工资代发机会": any(key in text for key in ["新建", "扩建", "生产", "厂房", "制造"]),
    }


def _is_construction_license_record(record: DashboardRecord) -> bool:
    return any(
        keyword in _record_text(record)
        for keyword in ["建设用地规划许可证", "建设工程规划许可证", "建设工程施工许可证"]
    )


def _record_text(record: DashboardRecord) -> str:
    return f"{record.approval_item} {record.project_name} {record.source_title} {record.data_source}"


def _record_score(record: DashboardRecord) -> float:
    raw_score = record.raw.get("opportunity_score")
    if raw_score is None:
        raw_score = record.raw.get("loan_opportunity_score")
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return 0.0


def _load_file(
    file_path: Path,
    region_key: str | None,
) -> list[DashboardRecord]:
    try:
        data = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []

    items = data.get("items", [])
    if not isinstance(items, list):
        return []

    records = []
    for item in items:
        if isinstance(item, dict) and _matches_region(item, region_key):
            records.append(_normalize_item(item, data.get("generated_at", "")))
    return records


def _validated_region_key(region_key: str | None) -> str | None:
    if region_key is None:
        return None
    value = str(region_key).strip()
    if not value:
        raise ValueError("region_key 不能为空")
    return value


def _matches_region(item: dict[str, Any], region_key: str | None) -> bool:
    if region_key is None:
        return True
    item_region = str(
        item.get("region_key")
        or item.get("area_code")
        or item.get("district_code")
        or ""
    ).strip()
    if item_region:
        return item_region == region_key
    return region_key == DEFAULT_REGION_KEY


def _normalize_item(item: dict[str, Any], generated_at: str) -> DashboardRecord:
    analysis = item.get("ai_analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}

    products = _string_list_to_text(analysis.get("expected_loan_types"))
    level = str(analysis.get("customer_value_level") or "C").strip().upper()
    if level not in {"A", "B", "C"}:
        level = "C"

    has_need = analysis.get("has_financing_need")
    financing_need = "存在" if has_need is True else "暂不明显" if has_need is False else UNKNOWN
    project_name = _first_text(item, "project_name", "项目名称")
    source_title = _first_text(item, "source_title", "原始标题")

    return DashboardRecord(
        enterprise_name=_first_text(item, "enterprise_name", "企业名称"),
        project_name=project_name,
        industry=_first_text(item, "industry", "所属行业", default=infer_industry(f"{project_name} {source_title}")),
        investment_amount=_first_text(item, "investment_amount", "投资金额"),
        project_address=_first_text(item, "project_address", "项目地址"),
        discovery_time=_first_text(item, "date", "发现时间", default=generated_at or UNKNOWN),
        data_source=_first_text(item, "data_source", "source_name", "数据来源", default=_source_from_url(str(item.get("source_url", "")))),
        customer_level=level,
        financing_need=financing_need,
        recommended_products=products,
        approval_item=_first_text(item, "approval_item", "审批事项"),
        source_url=str(item.get("source_url") or item.get("链接") or ""),
        source_title=source_title,
        marketing_advice=str(analysis.get("marketing_advice") or UNKNOWN),
        reason=str(analysis.get("reason") or UNKNOWN),
        confidence=_confidence(analysis.get("confidence")),
        raw=item,
    )


def infer_industry(text: str) -> str:
    rules = [
        ("纺织服装", ["纺织", "纤维", "面料", "家纺", "服装", "衬布"]),
        ("装备制造", ["装备", "设备", "机械", "电气", "零部件", "元件"]),
        ("新材料", ["材料", "弹性", "高性能", "复合"]),
        ("体育用品", ["体育", "篮球"]),
        ("矿业设备", ["矿业", "选矿"]),
        ("电子信息", ["电子", "智能", "芯片", "传感"]),
        ("食品医药", ["食品", "医药", "生物"]),
    ]
    for industry, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return industry
    return UNKNOWN


def _dedupe_records(records: list[DashboardRecord]) -> list[DashboardRecord]:
    seen: set[tuple[str, str, str]] = set()
    result = []
    for record in records:
        key = (record.enterprise_name, record.project_name, record.source_url)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _first_text(item: dict[str, Any], *keys: str, default: str = UNKNOWN) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _string_list_to_text(value: Any) -> str:
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(parts) if parts else UNKNOWN
    if value is None:
        return UNKNOWN
    return str(value).strip() or UNKNOWN


def _source_from_url(url: str) -> str:
    if "haimen.gov.cn" in url:
        return "海门区政府网站"
    return UNKNOWN


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: str) -> date | None:
    if not value or value == UNKNOWN:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", value)
    if match:
        year, month, day = match.groups()
        return date(int(year), int(month), int(day))
    return None
