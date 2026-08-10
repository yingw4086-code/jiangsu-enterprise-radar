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
    PROJECT_TYPES,
    classify_project_type,
)


SCHEMA_VERSION = 7
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
        added_columns: list[str] = []

        with connection:
            if "project_type" not in columns:
                connection.execute(
                    "ALTER TABLE construction_permits "
                    "ADD COLUMN project_type TEXT NOT NULL DEFAULT 'unknown'"
                )
                added_columns.append("project_type")

            rows = connection.execute(
                """
                SELECT id, company_name, construction_unit, project_name
                FROM construction_permits
                """
            ).fetchall()
            classified = [
                (
                    classify_project_type(
                        company_name=row["company_name"],
                        construction_unit=row["construction_unit"],
                        project_name=row["project_name"],
                    ),
                    row["id"],
                )
                for row in rows
            ]
            connection.executemany(
                "UPDATE construction_permits SET project_type = ? WHERE id = ?",
                classified,
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_permit_region_project_type
                ON construction_permits(region_key, project_type)
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
            connection.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

        row_count_after = int(
            connection.execute("SELECT COUNT(*) FROM construction_permits").fetchone()[0]
        )
        counts = Counter(
            str(row[0])
            for row in connection.execute(
                "SELECT project_type FROM construction_permits"
            ).fetchall()
        )
        invalid_types = sorted(set(counts) - PROJECT_TYPES)
        if row_count_after != row_count_before:
            raise RuntimeError(
                f"迁移前后记录数不一致：{row_count_before} -> {row_count_after}"
            )
        if sum(counts.values()) != row_count_after or invalid_types:
            raise RuntimeError(f"project_type 分类结果无效：{dict(counts)}")

        return {
            "database": str(db_path),
            "schema_version": SCHEMA_VERSION,
            "added_columns": added_columns,
            "row_count_before": row_count_before,
            "row_count_after": row_count_after,
            "counts": {
                "enterprise": counts.get("enterprise", 0),
                "government": counts.get("government", 0),
                "unknown": counts.get("unknown", 0),
            },
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add and populate project_type")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
