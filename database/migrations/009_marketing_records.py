from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.marketing_tracking import (  # noqa: E402
    MARKETING_RECORD_COLUMNS,
    ensure_marketing_records_table,
)


SCHEMA_VERSION = 9
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"


def migrate(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    database_path = Path(db_path).resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        permit_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction_permits'"
        ).fetchone()
        if permit_table is None:
            raise RuntimeError("数据库缺少 construction_permits 表")

        permit_count_before = _row_count(connection, "construction_permits")
        table_existed = _table_exists(connection, "marketing_records")
        marketing_count_before = (
            _row_count(connection, "marketing_records") if table_existed else 0
        )

        with connection:
            ensure_marketing_records_table(connection)
            _validate_marketing_columns(connection)
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

        permit_count_after = _row_count(connection, "construction_permits")
        marketing_count_after = _row_count(connection, "marketing_records")
        if permit_count_after != permit_count_before:
            raise RuntimeError(
                "迁移前后 construction_permits 行数不一致："
                f"{permit_count_before} -> {permit_count_after}"
            )
        if marketing_count_after != marketing_count_before:
            raise RuntimeError(
                "迁移不应修改已有 marketing_records："
                f"{marketing_count_before} -> {marketing_count_after}"
            )

        return {
            "database": str(database_path),
            "schema_version": max(current_version, SCHEMA_VERSION),
            "created_table": not table_existed,
            "marketing_columns": list(MARKETING_RECORD_COLUMNS),
            "permit_count_before": permit_count_before,
            "permit_count_after": permit_count_after,
            "marketing_count": marketing_count_after,
        }
    finally:
        connection.close()


def _validate_marketing_columns(connection: sqlite3.Connection) -> None:
    columns = tuple(
        str(row[1])
        for row in connection.execute("PRAGMA table_info(marketing_records)")
    )
    if columns != MARKETING_RECORD_COLUMNS:
        raise RuntimeError(
            "marketing_records 字段与设计不一致："
            f"expected={MARKETING_RECORD_COLUMNS}, actual={columns}"
        )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def _row_count(connection: sqlite3.Connection, table_name: str) -> int:
    if table_name not in {"construction_permits", "marketing_records"}:
        raise ValueError(f"不允许的表名：{table_name}")
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Create marketing tracking records table")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
