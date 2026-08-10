from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_source.project_classification import (  # noqa: E402
    CLASSIFICATION_CONFIDENCES,
    PROJECT_TYPES,
    classify_project,
)


SCHEMA_VERSION = 8
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"


def migrate(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction_permits'"
        ).fetchone()
        if table is None:
            raise RuntimeError("数据库缺少 construction_permits 表")

        row_count_before = int(
            connection.execute("SELECT COUNT(*) FROM construction_permits").fetchone()[0]
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(construction_permits)")
        }
        required_columns = {
            "company_name",
            "construction_unit",
            "project_name",
            "project_type",
            "region_key",
        }
        missing = sorted(required_columns - columns)
        if missing:
            raise RuntimeError(f"Schema 7 前置字段缺失：{missing}")

        added_columns: list[str] = []
        with connection:
            if "classification_confidence" not in columns:
                connection.execute(
                    "ALTER TABLE construction_permits "
                    "ADD COLUMN classification_confidence "
                    "TEXT NOT NULL DEFAULT 'low'"
                )
                added_columns.append("classification_confidence")

            rows = connection.execute(
                """
                SELECT id, company_name, construction_unit, project_name
                FROM construction_permits
                """
            ).fetchall()
            classified = []
            for row in rows:
                result = classify_project(
                    company_name=row["company_name"],
                    construction_unit=row["construction_unit"],
                    project_name=row["project_name"],
                )
                classified.append((result.project_type, result.confidence, row["id"]))
            connection.executemany(
                """
                UPDATE construction_permits
                SET project_type = ?, classification_confidence = ?
                WHERE id = ?
                """,
                classified,
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_permit_region_project_classification
                ON construction_permits(
                    region_key, project_type, classification_confidence
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            current_row = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            current_version = int(current_row[0]) if current_row else 0
            connection.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(max(current_version, SCHEMA_VERSION)),),
            )

        row_count_after = int(
            connection.execute("SELECT COUNT(*) FROM construction_permits").fetchone()[0]
        )
        type_counts = Counter(
            str(row[0])
            for row in connection.execute(
                "SELECT project_type FROM construction_permits"
            ).fetchall()
        )
        confidence_counts = Counter(
            str(row[0])
            for row in connection.execute(
                "SELECT classification_confidence FROM construction_permits"
            ).fetchall()
        )
        if row_count_after != row_count_before:
            raise RuntimeError(
                f"迁移前后记录数不一致：{row_count_before} -> {row_count_after}"
            )
        if set(type_counts) - PROJECT_TYPES or sum(type_counts.values()) != row_count_after:
            raise RuntimeError(f"project_type 分类结果无效：{dict(type_counts)}")
        if (
            set(confidence_counts) - CLASSIFICATION_CONFIDENCES
            or sum(confidence_counts.values()) != row_count_after
        ):
            raise RuntimeError(
                f"classification_confidence 结果无效：{dict(confidence_counts)}"
            )

        return {
            "database": str(db_path),
            "schema_version": max(current_version, SCHEMA_VERSION),
            "added_columns": added_columns,
            "row_count_before": row_count_before,
            "row_count_after": row_count_after,
            "project_type_counts": {
                "enterprise": type_counts.get("enterprise", 0),
                "government": type_counts.get("government", 0),
                "unknown": type_counts.get("unknown", 0),
            },
            "confidence_counts": {
                "high": confidence_counts.get("high", 0),
                "medium": confidence_counts.get("medium", 0),
                "low": confidence_counts.get("low", 0),
            },
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add classification_confidence and reclassify permits"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
