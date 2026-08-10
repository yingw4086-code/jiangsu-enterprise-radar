from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_source.regional_permit_import import (  # noqa: E402
    load_verified_import_records,
)
from database.storage import (  # noqa: E402
    save_crawler_run,
    upsert_planning_construction_permits,
)


DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_INPUT_PATH = (
    PROJECT_ROOT / "data" / "region_imports" / "phase3_14_verified_permits.json"
)
DEFAULT_REGION_CONFIG_PATH = PROJECT_ROOT / "config" / "regions.json"
DEFAULT_SOURCE_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "regional_permit_sources.json"
)
HAIMEN_REGION_KEY = "320684"
LEGACY_COLUMNS = (
    "id", "record_hash", "company_name", "project_name", "permit_type",
    "permit_date", "address", "construction_unit", "permit_number",
    "publish_date", "district", "district_code", "province", "city",
    "region_key", "area_code", "source_url",
)


def import_regional_permits(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    input_path: Path = DEFAULT_INPUT_PATH,
    region_config_path: Path = DEFAULT_REGION_CONFIG_PATH,
    source_config_path: Path = DEFAULT_SOURCE_CONFIG_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    records = load_verified_import_records(
        input_path,
        region_config_path=region_config_path,
        source_config_path=source_config_path,
    )
    before = _database_snapshot(db_path)
    preview = {
        "validated_count": len(records),
        "by_city": dict(sorted(Counter(record.city for record in records).items())),
        "by_region_key": dict(
            sorted(Counter(record.region_key for record in records).items())
        ),
        "source_keys": sorted({record.source_key for record in records}),
    }
    if dry_run:
        return {
            "status": "dry_run",
            "database": str(Path(db_path).resolve()),
            "input": str(Path(input_path).resolve()),
            **preview,
            "haimen_before": before,
        }

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = upsert_planning_construction_permits(db_path, records)
    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    after = _database_snapshot(db_path)
    if before != after:
        raise RuntimeError(
            "区域导入修改了海门历史数据，事务结果不可接受："
            f"before={before}, after={after}"
        )
    save_crawler_run(
        db_path,
        started_at,
        finished_at,
        "regional_permit_import",
        summary,
        "success",
        metadata={
            "input": str(Path(input_path).resolve()),
            **preview,
            "haimen_snapshot": after,
        },
    )
    return {
        "status": "success",
        "database": str(Path(db_path).resolve()),
        "input": str(Path(input_path).resolve()),
        **preview,
        "inserted_count": summary.inserted_count,
        "updated_count": summary.updated_count,
        "skipped_count": summary.skipped_count,
        "haimen_before": before,
        "haimen_after": after,
        "database_counts": _region_counts(db_path),
    }


def _database_snapshot(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            f"SELECT {', '.join(LEGACY_COLUMNS)} FROM construction_permits "
            "WHERE region_key=? ORDER BY id",
            (HAIMEN_REGION_KEY,),
        ).fetchall()
    finally:
        connection.close()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return {
        "count": len(rows),
        "legacy_fingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def _region_counts(db_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT region_key, COUNT(*) FROM construction_permits "
            "GROUP BY region_key ORDER BY region_key"
        ).fetchall()
    finally:
        connection.close()
    return {str(region_key): int(count) for region_key, count in rows}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and import verified Jiangsu regional permits"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--regions", type=Path, default=DEFAULT_REGION_CONFIG_PATH)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCE_CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = import_regional_permits(
        db_path=args.db,
        input_path=args.input,
        region_config_path=args.regions,
        source_config_path=args.sources,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
