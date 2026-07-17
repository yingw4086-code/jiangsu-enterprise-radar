from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

from app.models import FinancingAnalysis, ProjectAnnouncement


class JsonLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


class FinancingAnalyzer:
    def __init__(self, client: JsonLLMClient, model_name: str):
        self.client = client
        self.model_name = model_name

    def analyze_many(self, announcements: list[ProjectAnnouncement]) -> dict[str, Any]:
        if not announcements:
            return {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "model": self.model_name,
                "items": [],
            }

        response = self.client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(announcements),
        )
        return normalize_response(response, announcements, self.model_name)


SYSTEM_PROMPT = """你是银行对公客户经理的企业项目融资线索分析助手。
你只能基于用户提供的公开项目信息判断营销线索，不能编造未提供的事实。
请输出严格 JSON，不要输出 Markdown。
"""


def build_user_prompt(announcements: list[ProjectAnnouncement]) -> str:
    payload = [
        {
            "index": index,
            "enterprise_name": item.company_name,
            "project_name": item.project_name,
            "approval_item": item.approval_item,
            "date": item.date,
            "source_url": item.link,
            "source_title": item.title,
        }
        for index, item in enumerate(announcements, start=1)
    ]
    return (
        "请分析以下政府公开项目公告，判断银行融资营销机会。\n"
        "对每条数据输出：\n"
        "1. 是否存在融资需求 has_financing_need，布尔值。\n"
        "2. 预计贷款类型 expected_loan_types，数组，例如：项目贷款、固定资产贷款、设备融资、流动资金贷款、票据/结算服务、暂无明显贷款需求。\n"
        "3. 客户价值等级 customer_value_level，只能是 A、B、C。\n"
        "4. 营销建议 marketing_advice，给客户经理的一句话建议。\n"
        "5. 判断理由 reason，简短说明。\n"
        "6. 置信度 confidence，0 到 1 的数字。\n"
        "输出格式必须是：\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "index": 1,\n'
        '      "enterprise_name": "...",\n'
        '      "project_name": "...",\n'
        '      "has_financing_need": true,\n'
        '      "expected_loan_types": ["项目贷款"],\n'
        '      "customer_value_level": "A",\n'
        '      "marketing_advice": "...",\n'
        '      "reason": "...",\n'
        '      "confidence": 0.8\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"待分析数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def normalize_response(
    response: dict[str, Any],
    announcements: list[ProjectAnnouncement],
    model_name: str,
) -> dict[str, Any]:
    raw_items = response.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []
    by_index: dict[int, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        by_index[index] = item

    normalized_items = []
    for index, announcement in enumerate(announcements, start=1):
        raw = by_index.get(index, {})
        analysis = FinancingAnalysis(
            has_financing_need=_as_bool(raw.get("has_financing_need")),
            expected_loan_types=_as_string_list(raw.get("expected_loan_types")),
            customer_value_level=_normalize_level(raw.get("customer_value_level")),
            marketing_advice=_as_text(raw.get("marketing_advice")),
            reason=_as_text(raw.get("reason")),
            confidence=_as_confidence(raw.get("confidence")),
        )
        normalized_items.append(
            {
                "index": index,
                "enterprise_name": announcement.company_name,
                "project_name": announcement.project_name,
                "approval_item": announcement.approval_item,
                "date": announcement.date,
                "source_url": announcement.link,
                "source_title": announcement.title,
                "ai_analysis": analysis.to_json_dict(),
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": model_name,
        "items": normalized_items,
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "是", "有", "存在"}
    return bool(value)


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or ["暂无明显贷款需求"]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
    return ["暂无明显贷款需求"]


def _normalize_level(value: Any) -> str:
    level = str(value or "C").strip().upper()
    return level if level in {"A", "B", "C"} else "C"


def _as_text(value: Any) -> str:
    text = str(value or "").strip()
    return text or "模型未提供明确说明"


def _as_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))

