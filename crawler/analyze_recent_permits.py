from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.ai.provider import OpenAICompatibleClient, config_from_env
from database.storage import (
    load_recent_planning_permit_analysis_candidates,
    save_permit_ai_analysis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
API_KEY_ENV = "PROJECT_RADAR_LLM_API_KEY"
ALLOWED_PRODUCTS = (
    "固定资产贷款",
    "项目贷款",
    "流动资金贷款",
    "银行承兑汇票",
    "结算账户",
    "工资代发",
)
INPUT_FIELDS = (
    "company_name",
    "project_name",
    "permit_type",
    "permit_number",
    "permit_date",
    "publish_date",
    "project_address",
    "issuing_authority",
    "district",
    "district_code",
    "source_url",
)


class JsonLLMClient(Protocol):
    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AnalysisSummary:
    candidate_count: int
    analyzed_count: int
    cached_count: int
    failed_count: int
    A_count: int
    B_count: int
    C_count: int
    api_model: str


SYSTEM_PROMPT = """你是银行对公客户经理的政府公开项目营销线索分析助手。
只能依据提供的建设工程规划许可证公开信息进行谨慎判断，不得补充未提供的事实。
AI机会等级仅表示营销联系优先级，不是授信审批结论或企业正式信用评级。
不得声称企业必然存在贷款需求，不得给出所谓准确贷款额度。
请只输出一个严格JSON对象，不要输出Markdown或分析过程。
"""


def analyze_recent_permits(
    db_path: Path,
    days: int = 30,
    limit: int = 20,
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    client: JsonLLMClient | None = None,
    model_name: str | None = None,
    today: datetime | None = None,
    request_interval_seconds: float = 0.2,
) -> AnalysisSummary:
    _load_env_file(env_path)
    selected_limit = min(max(1, int(limit)), 20)
    selected_days = max(0, int(days))
    candidates = load_recent_planning_permit_analysis_candidates(
        db_path,
        days=selected_days,
        limit=selected_limit,
        today=today,
    )

    pending: list[tuple[dict[str, Any], str]] = []
    level_counts = {"A": 0, "B": 0, "C": 0}
    cached_count = 0
    for item in candidates:
        input_hash = permit_analysis_input_hash(item)
        cached_level = str(item.get("ai_opportunity_level") or "").upper()
        if item.get("analysis_input_hash") == input_hash and cached_level in level_counts:
            cached_count += 1
            level_counts[cached_level] += 1
        else:
            pending.append((item, input_hash))

    selected_model = (
        model_name
        or os.getenv("PROJECT_RADAR_LLM_MODEL", "").strip()
        or "未配置"
    )
    if pending and client is None:
        try:
            config = config_from_env(
                api_key_env=API_KEY_ENV,
                base_url=None,
                model=model_name,
                timeout_seconds=90,
                verify_ssl=True,
                response_format="json_object",
            )
            client = OpenAICompatibleClient(config)
            selected_model = config.model
        except Exception:
            return AnalysisSummary(
                candidate_count=len(candidates),
                analyzed_count=0,
                cached_count=cached_count,
                failed_count=len(pending),
                A_count=level_counts["A"],
                B_count=level_counts["B"],
                C_count=level_counts["C"],
                api_model=selected_model,
            )

    analyzed_count = 0
    failed_count = 0
    for index, (item, input_hash) in enumerate(pending):
        try:
            assert client is not None
            response = client.complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(item),
            )
            analysis = normalize_analysis(response)
            save_permit_ai_analysis(
                db_path,
                permit_id=int(item["permit_id"]),
                input_hash=input_hash,
                analysis=analysis,
                api_model=selected_model,
            )
            analyzed_count += 1
            level_counts[analysis["ai_opportunity_level"]] += 1
        except Exception as exc:
            failed_count += 1
            print(
                f"analysis_failed permit_id={item.get('permit_id')} "
                f"error_type={type(exc).__name__}"
            )
        if index < len(pending) - 1 and request_interval_seconds > 0:
            time.sleep(request_interval_seconds)

    return AnalysisSummary(
        candidate_count=len(candidates),
        analyzed_count=analyzed_count,
        cached_count=cached_count,
        failed_count=failed_count,
        A_count=level_counts["A"],
        B_count=level_counts["B"],
        C_count=level_counts["C"],
        api_model=selected_model,
    )


def permit_analysis_input_hash(item: dict[str, Any]) -> str:
    payload = {field: str(item.get(field) or "").strip() for field in INPUT_FIELDS}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_user_prompt(item: dict[str, Any]) -> str:
    public_data = {field: item.get(field) for field in INPUT_FIELDS}
    return (
        "请分析以下海门区建设工程规划许可证公开信息，并返回如下JSON字段：\n"
        "{\n"
        '  "ai_opportunity_level": "A或B或C",\n'
        '  "financing_need": "可能存在融资需求/暂未发现明显融资需求/信息不足需核实",\n'
        '  "recommended_products": ["仅从指定产品中选择"],\n'
        '  "marketing_summary": "100字以内的营销机会判断",\n'
        '  "visit_suggestion": "建议如何拜访，并说明优先联系岗位",\n'
        '  "reasoning_summary": "简要说明公开信息中的判断依据",\n'
        '  "confidence": 0到100的整数,\n'
        '  "risk_notice": "信息不足、主体不清晰或其他风险提示"\n'
        "}\n"
        f"指定产品：{json.dumps(ALLOWED_PRODUCTS, ensure_ascii=False)}\n"
        "A/B/C只代表营销联系优先级。无法确认的内容请明确写需核实。\n"
        f"项目公开信息：{json.dumps(public_data, ensure_ascii=False)}"
    )


def normalize_analysis(response: dict[str, Any]) -> dict[str, Any]:
    level = str(response.get("ai_opportunity_level") or "C").strip().upper()
    if level not in {"A", "B", "C"}:
        level = "C"

    financing_need = _normalize_financing_need(response.get("financing_need"))
    products = _normalize_products(response.get("recommended_products"))
    marketing_summary = _safe_text(
        response.get("marketing_summary"),
        "公开信息有限，建议先核实项目建设计划及资金安排。",
        100,
    )
    visit_suggestion = _safe_text(
        response.get("visit_suggestion"),
        "建议先联系企业财务负责人或项目负责人，核实建设进度与资金安排。",
        240,
    )
    reasoning_summary = _safe_text(
        response.get("reasoning_summary"),
        "依据建设工程规划许可证公开信息判断，具体需求仍需企业确认。",
        240,
    )
    risk_notice = _safe_text(
        response.get("risk_notice"),
        "公开信息有限，项目主体、进度和融资安排需进一步核实。",
        240,
    )
    confidence = _normalize_confidence(response.get("confidence"))
    return {
        "ai_opportunity_level": level,
        "financing_need": financing_need,
        "recommended_products": products,
        "marketing_summary": marketing_summary,
        "visit_suggestion": visit_suggestion,
        "reasoning_summary": reasoning_summary,
        "confidence": confidence,
        "risk_notice": risk_notice,
    }


def _normalize_financing_need(value: Any) -> str:
    if isinstance(value, bool):
        return "可能存在融资需求" if value else "暂未发现明显融资需求"
    text = _safe_text(value, "信息不足需核实", 80)
    if text in {"是", "有", "存在", "可能有"}:
        return "可能存在融资需求"
    if text in {"否", "无", "不存在"}:
        return "暂未发现明显融资需求"
    return text


def _normalize_products(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("，", ",").replace("、", ",").split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    selected = {str(item).strip() for item in values}
    return [product for product in ALLOWED_PRODUCTS if product in selected]


def _normalize_confidence(value: Any) -> int:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 < confidence <= 1:
        confidence *= 100
    return int(round(max(0, min(100, confidence))))


def _safe_text(value: Any, default: str, max_length: int) -> str:
    text = " ".join(str(value or "").split()) or default
    replacements = {
        "授信审批结论": "营销线索判断",
        "企业正式信用评级": "营销机会等级",
        "必然存在贷款需求": "可能存在融资需求",
        "准确贷款额度": "融资规模需进一步核实",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text[:max_length]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="分析近期建设工程规划许可证营销机会")
    parser.add_argument("--days", type=int, default=30, help="分析最近多少天，默认30天")
    parser.add_argument("--limit", type=int, default=20, help="最多分析20条")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite数据库路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = analyze_recent_permits(
        Path(args.db_path),
        days=args.days,
        limit=args.limit,
    )
    print(f"candidate_count={summary.candidate_count}")
    print(f"analyzed_count={summary.analyzed_count}")
    print(f"cached_count={summary.cached_count}")
    print(f"failed_count={summary.failed_count}")
    print(f"A_count={summary.A_count}")
    print(f"B_count={summary.B_count}")
    print(f"C_count={summary.C_count}")
    print(f"api_model={summary.api_model}")
    return 0 if summary.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
