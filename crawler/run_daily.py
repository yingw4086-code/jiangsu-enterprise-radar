from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from database.storage import (
    UpsertSummary,
    load_opportunities,
    save_crawler_run,
    upsert_construction_permits,
    upsert_opportunities,
)
from data_source.base import OpportunityRecord
from data_source.jiangsu_license import JiangsuLicenseCrawler
from data_source.multi_source_runner import build_dashboard_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_AI_OUTPUT_DIR = PROJECT_ROOT / "data" / "ai"
DEFAULT_OPPORTUNITY_OUTPUT_DIR = PROJECT_ROOT / "data" / "opportunities"
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "crawler.log"


def run_daily(args: argparse.Namespace) -> dict[str, Any]:
    logger = configure_logging(Path(args.log_path))
    run_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    db_path = Path(args.db_path)
    source_name = "江苏自然资源建设项目许可证"

    logger.info("Daily crawler started. db=%s", db_path)
    crawler = JiangsuLicenseCrawler(
        max_items=args.limit,
        timeout_seconds=args.timeout_seconds,
        enable_provincial_search=True,
    )
    records: list[OpportunityRecord] = []
    permit_records = []
    status = "success"
    error_message = ""

    try:
        permit_records = crawler.crawl_licenses()
        records = [record.to_opportunity_record() for record in permit_records]
        permit_summary = upsert_construction_permits(db_path, permit_records)
        summary = upsert_opportunities(db_path, records)
        exported_records = load_opportunities(db_path, limit=args.export_limit)
        opportunity_path = export_opportunity_json(
            records=exported_records,
            output_dir=Path(args.opportunity_output_dir),
            timestamp=timestamp,
            source=source_name,
            summary=summary,
            crawler_errors=crawler.errors,
        )
        dashboard_json_path = export_dashboard_json(
            records=exported_records,
            output_dir=Path(args.ai_output_dir),
            timestamp=timestamp,
        )
        if len(records) < args.min_records:
            status = "warning"
            error_message = f"Fetched {len(records)} records, below minimum {args.min_records}."
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        summary = UpsertSummary(fetched_count=len(records), inserted_count=0, updated_count=0, total_count=0)
        opportunity_path = ""
        dashboard_json_path = ""
        logger.exception("Daily crawler failed.")

    run_finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_crawler_run(
        db_path=db_path,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        source=source_name,
        summary=summary,
        status=status,
        error_message=error_message,
        metadata={
            "crawler_errors": crawler.errors,
            "opportunity_json": str(opportunity_path),
            "dashboard_json": str(dashboard_json_path),
            "construction_permit_count": len(permit_records),
            "construction_permit_inserted_count": permit_summary.inserted_count if status != "failed" else 0,
            "construction_permit_updated_count": permit_summary.updated_count if status != "failed" else 0,
        },
    )

    result = {
        "status": status,
        "source": source_name,
        "fetched_count": summary.fetched_count,
        "inserted_count": summary.inserted_count,
        "updated_count": summary.updated_count,
        "total_count": summary.total_count,
        "db_path": str(db_path),
        "opportunity_json": str(opportunity_path),
        "dashboard_json": str(dashboard_json_path),
        "log_path": str(args.log_path),
        "error_message": error_message,
        "crawler_errors": crawler.errors,
        "construction_permit_count": len(permit_records),
    }
    logger.info("Daily crawler finished. %s", json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def export_opportunity_json(
    records: list[OpportunityRecord],
    output_dir: Path,
    timestamp: str,
    source: str,
    summary: UpsertSummary,
    crawler_errors: list[str],
) -> Path:
    output_path = output_dir / f"enterprise_opportunities_daily_{timestamp}.json"
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "record_count": len(records),
        "db_total_count": summary.total_count,
        "inserted_count": summary.inserted_count,
        "updated_count": summary.updated_count,
        "crawler_errors": crawler_errors,
        "items": [record.to_unified_dict() for record in records],
    }
    write_json(output_path, payload)
    return output_path


def export_dashboard_json(records: list[OpportunityRecord], output_dir: Path, timestamp: str) -> Path:
    output_path = output_dir / f"financing_analysis_daily_{timestamp}.json"
    payload = build_dashboard_payload(records)
    payload["model"] = "sqlite_daily_rule_scoring"
    write_json(output_path, payload)
    return output_path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def configure_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("crawler.run_daily")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="海门企业雷达每日后台采集任务")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite 数据库路径")
    parser.add_argument("--ai-output-dir", default=str(DEFAULT_AI_OUTPUT_DIR), help="驾驶舱兼容 JSON 输出目录")
    parser.add_argument("--opportunity-output-dir", default=str(DEFAULT_OPPORTUNITY_OUTPUT_DIR), help="统一机会 JSON 输出目录")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="日志文件路径")
    parser.add_argument("--limit", type=int, default=80, help="本次建设项目许可证最多采集条数")
    parser.add_argument("--export-limit", type=int, default=300, help="从 SQLite 导出给驾驶舱的最大记录数")
    parser.add_argument("--timeout-seconds", type=int, default=8, help="单个网页访问超时秒数")
    parser.add_argument("--min-records", type=int, default=1, help="低于该条数时标记为 warning")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_daily(args)
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
