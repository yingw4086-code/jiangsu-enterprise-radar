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

from app.company_import import (  # noqa: E402
    COMPANY_IMPORT_LOG_COLUMNS,
    ensure_company_import_logs_table,
)


SCHEMA_VERSION = 11
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"


def migrate(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    database_path = Path(db_path).resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        if not _table_exists(connection, "construction_permits"):
            raise RuntimeError("数据库缺少 construction_permits 表")

        protected_counts = {
            table: _row_count(connection, table)
            for table in (
                "construction_permits",
                "marketing_records",
                "company_registry",
            )
            if _table_exists(connection, table)
        }
        logs_existed = _table_exists(connection, "company_import_logs")
        log_count_before = (
            _row_count(connection, "company_import_logs") if logs_existed else 0
        )

        with connection:
            ensure_company_import_logs_table(connection)
            _validate_columns(connection)
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

        for table, count_before in protected_counts.items():
            count_after = _row_count(connection, table)
            if count_after != count_before:
                raise RuntimeError(
                    f"迁移前后 {table} 行数不一致："
                    f"{count_before} -> {count_after}"
                )
        log_count_after = _row_count(connection, "company_import_logs")
        if log_count_after != log_count_before:
            raise RuntimeError(
                "迁移不应修改已有 company_import_logs："
                f"{log_count_before} -> {log_count_after}"
            )

        return {
            "database": str(database_path),
            "schema_version": max(current_version, SCHEMA_VERSION),
            "created_table": not logs_existed,
            "company_import_log_columns": list(COMPANY_IMPORT_LOG_COLUMNS),
            "protected_counts": protected_counts,
            "company_import_log_count": log_count_after,
        }
    finally:
        connection.close()


def _validate_columns(connection: sqlite3.Connection) -> None:
    columns = tuple(
        str(row[1])
        for row in connection.execute("PRAGMA table_info(company_import_logs)")
    )
    if columns != COMPANY_IMPORT_LOG_COLUMNS:
        raise RuntimeError(
            "company_import_logs 字段与设计不一致："
            f"expected={COMPANY_IMPORT_LOG_COLUMNS}, actual={columns}"
        )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def _row_count(connection: sqlite3.Connection, table_name: str) -> int:
    allowed = {
        "construction_permits",
        "marketing_records",
        "company_registry",
        "company_import_logs",
    }
    if table_name not in allowed:
        raise ValueError(f"不允许的表名：{table_name}")
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Create company import log table")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
