from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_source.planning_land_permit import (
    PERMIT_TYPE,
    PlanningLandPermitCrawler,
)
from database.official_permits import (
    export_public_official_permits,
    upsert_official_permits,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_CLOUD_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_land_permits.json"


def run(args: argparse.Namespace) -> dict[str, object]:
    crawler = PlanningLandPermitCrawler(
        timeout_seconds=args.timeout_seconds,
        request_interval_seconds=args.request_interval,
        max_list_items=args.limit,
    )
    records, report = crawler.collect()
    summary = upsert_official_permits(
        Path(args.db_path),
        records,
        permit_type=PERMIT_TYPE,
    )
    export_result = export_public_official_permits(
        Path(args.db_path),
        Path(args.cloud_output),
        permit_type=PERMIT_TYPE,
    )
    result = {
        **report,
        "inserted_count": summary.inserted_count,
        "updated_count": summary.updated_count,
        "skipped_count": summary.skipped_count,
        "database_total_count": summary.total_count,
        "cloud_export_count": export_result["export_count"],
        "cloud_output": export_result["output_path"],
        "cloud_written": export_result["written"],
        "samples": [record.to_public_dict() for record in records[:10]],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集海门建设用地规划许可证")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--cloud-output", default=str(DEFAULT_CLOUD_PATH))
    parser.add_argument("--limit", type=int, default=30, help="最多解析官网最新30条列表记录")
    parser.add_argument("--timeout-seconds", type=int, default=25)
    parser.add_argument("--request-interval", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    return 0 if int(result["database_total_count"]) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
