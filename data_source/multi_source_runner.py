from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from data_source.base import OpportunityRecord, dedupe_records
from data_source.construction import ConstructionPermitCrawler
from data_source.environment import EnvironmentApprovalCrawler
from data_source.investment_project import InvestmentProjectCrawler
from data_source.jiangsu_natural_resource import JiangsuNaturalResourceCrawler
from data_source.tender import TenderCrawler


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "opportunities"
DEFAULT_AI_OUTPUT_DIR = PROJECT_ROOT / "data" / "ai"


def build_crawlers(max_items_per_source: int = 30):
    return [
        JiangsuNaturalResourceCrawler(max_items=max_items_per_source, timeout_seconds=8),
        InvestmentProjectCrawler(max_items=max_items_per_source, timeout_seconds=8, verify_ssl=False),
        EnvironmentApprovalCrawler(max_items=max_items_per_source, timeout_seconds=8, verify_ssl=False),
        ConstructionPermitCrawler(max_items=max_items_per_source, timeout_seconds=4, verify_ssl=False),
        TenderCrawler(max_items=max_items_per_source, timeout_seconds=8, verify_ssl=False),
    ]


def run_multi_source(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    ai_output_dir: Path = DEFAULT_AI_OUTPUT_DIR,
    max_items_per_source: int = 30,
    min_records: int = 50,
) -> dict[str, object]:
    crawlers = build_crawlers(max_items_per_source=max_items_per_source)
    all_records: list[OpportunityRecord] = []
    source_reports = []

    for crawler in crawlers:
        started = datetime.now()
        records = crawler.crawl()
        all_records.extend(records)
        source_reports.append(
            {
                "source": crawler.source_name,
                "source_type": crawler.source_type,
                "records": len(records),
                "errors": crawler.errors[:20],
                "duration_seconds": round((datetime.now() - started).total_seconds(), 2),
            }
        )

    records = dedupe_records(all_records)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    opportunity_path = output_dir / f"enterprise_opportunities_{timestamp}.json"
    dashboard_ai_path = ai_output_dir / f"financing_analysis_{timestamp}.json"
    report_path = output_dir / f"multi_source_report_{timestamp}.json"

    opportunity_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "record_count": len(records),
        "min_records_target": min_records,
        "target_met": len(records) >= min_records,
        "schema": {
            "企业名称": "",
            "项目名称": "",
            "来源": "",
            "时间": "",
            "金额": "",
            "行业": "",
            "地区": "",
            "机会等级": "",
            "推荐贷款产品": "",
        },
        "items": [record.to_unified_dict() for record in records],
    }
    dashboard_payload = build_dashboard_payload(records)
    report_payload = {
        "generated_at": opportunity_payload["generated_at"],
        "record_count": len(records),
        "min_records_target": min_records,
        "target_met": len(records) >= min_records,
        "source_reports": source_reports,
        "outputs": {
            "opportunity_json": str(opportunity_path),
            "dashboard_ai_json": str(dashboard_ai_path),
        },
    }

    write_json(opportunity_path, opportunity_payload)
    write_json(dashboard_ai_path, dashboard_payload)
    write_json(report_path, report_payload)
    return {
        "records": records,
        "source_reports": source_reports,
        "opportunity_path": opportunity_path,
        "dashboard_ai_path": dashboard_ai_path,
        "report_path": report_path,
        "target_met": len(records) >= min_records,
    }


def build_dashboard_payload(records: Iterable[OpportunityRecord]) -> dict[str, object]:
    items = [record.to_dashboard_item(index) for index, record in enumerate(records, start=1)]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": "multi_source_rule_scoring",
        "items": items,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def watch_daily(args: argparse.Namespace) -> None:
    last_run_date = ""
    print(f"多源企业机会雷达已启动，每天 {args.time} 自动运行。")
    while True:
        now = datetime.now()
        current_day = now.date().isoformat()
        if now.strftime("%H:%M") >= args.time and current_day != last_run_date:
            result = run_multi_source(
                output_dir=Path(args.output_dir),
                ai_output_dir=Path(args.ai_output_dir),
                max_items_per_source=args.max_items_per_source,
                min_records=args.min_records,
            )
            print_run_result(result)
            last_run_date = current_day
        time.sleep(60)


def print_run_result(result: dict[str, object]) -> None:
    records = result["records"]
    print(f"采集完成：{len(records)} 条企业机会")
    print(f"统一机会库：{result['opportunity_path']}")
    print(f"驾驶舱兼容 JSON：{result['dashboard_ai_path']}")
    print(f"测试报告：{result['report_path']}")
    print(f"是否达到 50 条目标：{'是' if result['target_met'] else '否'}")
    for item in result["source_reports"]:
        print(f"- {item['source']}：{item['records']} 条")
        if item["errors"]:
            print(f"  访问提示：{item['errors'][0]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="海门企业雷达多源数据采集")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("run-once", "watch"):
        cmd = subparsers.add_parser(command)
        cmd.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="统一机会 JSON 输出目录")
        cmd.add_argument("--ai-output-dir", default=str(DEFAULT_AI_OUTPUT_DIR), help="驾驶舱兼容 JSON 输出目录")
        cmd.add_argument("--max-items-per-source", type=int, default=30, help="每个数据源最多抓取条数")
        cmd.add_argument("--min-records", type=int, default=50, help="测试目标最少真实记录条数")

    subparsers.choices["watch"].add_argument("--time", default="02:00", help="每日自动运行时间，格式 HH:MM")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-once":
        result = run_multi_source(
            output_dir=Path(args.output_dir),
            ai_output_dir=Path(args.ai_output_dir),
            max_items_per_source=args.max_items_per_source,
            min_records=args.min_records,
        )
        print_run_result(result)
        return 0 if result["target_met"] else 1
    if args.command == "watch":
        watch_daily(args)
        return 0
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
