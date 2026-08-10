from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


TARGET_SCHEMA_VERSION = 6
DEFAULT_REGION = {
    "province": "江苏省",
    "city": "南通市",
    "district": "海门区",
    "region_key": "320684",
    "area_code": "320684",
}
REGION_COLUMN_DEFINITIONS = {
    "province": "TEXT NOT NULL DEFAULT '江苏省'",
    "city": "TEXT NOT NULL DEFAULT '南通市'",
    "district": "TEXT NOT NULL DEFAULT '海门区'",
    "region_key": "TEXT NOT NULL DEFAULT '320684'",
    "area_code": "TEXT NOT NULL DEFAULT '320684'",
}


def migrate(db_path: Path) -> dict[str, Any]:
    database_path = Path(db_path).resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction_permits'"
        ).fetchone()
        if table is None:
            raise RuntimeError("缺少 construction_permits 表，migration 已停止")

        columns_before = _table_columns(connection, "construction_permits")
        missing_columns = [
            column
            for column in REGION_COLUMN_DEFINITIONS
            if column not in columns_before
        ]
        row_count_before = _row_count(connection)
        if missing_columns:
            _assert_legacy_rows_are_haimen(connection, columns_before)

        connection.execute("BEGIN IMMEDIATE")
        for column in missing_columns:
            definition = REGION_COLUMN_DEFINITIONS[column]
            connection.execute(
                f'ALTER TABLE construction_permits ADD COLUMN "{column}" {definition}'
            )

        _backfill_haimen_region(connection)
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_permit_region_type_date
            ON construction_permits(region_key, permit_type, permit_date)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_permit_area_source
            ON construction_permits(area_code, source_url)
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
        current_version = _schema_version(connection)
        if current_version < TARGET_SCHEMA_VERSION:
            connection.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(TARGET_SCHEMA_VERSION),),
            )

        row_count_after = _row_count(connection)
        if row_count_after != row_count_before:
            raise RuntimeError(
                "migration 前后 construction_permits 行数不一致："
                f"{row_count_before} -> {row_count_after}"
            )
        incomplete_haimen_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM construction_permits
            WHERE (district_code = '320684' OR district = '海门区')
              AND (
                    province <> '江苏省'
                 OR city <> '南通市'
                 OR district <> '海门区'
                 OR region_key <> '320684'
                 OR area_code <> '320684'
              )
            """
        ).fetchone()[0]
        if incomplete_haimen_rows:
            raise RuntimeError(
                f"仍有 {incomplete_haimen_rows} 条海门记录未完成地区字段回填"
            )

        connection.commit()
        return {
            "database": str(database_path),
            "schema_version": max(current_version, TARGET_SCHEMA_VERSION),
            "added_columns": missing_columns,
            "row_count_before": row_count_before,
            "row_count_after": row_count_after,
            "haimen_count": connection.execute(
                "SELECT COUNT(*) FROM construction_permits WHERE region_key = '320684'"
            ).fetchone()[0],
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    escaped_name = table_name.replace('"', '""')
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{escaped_name}")')
    }


def _row_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM construction_permits").fetchone()[0])


def _schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _assert_legacy_rows_are_haimen(
    connection: sqlite3.Connection,
    columns: set[str],
) -> None:
    conditions: list[str] = []
    if "district_code" in columns:
        conditions.append(
            "COALESCE(NULLIF(TRIM(district_code), ''), '未披露') NOT IN ('320684', '未披露')"
        )
    if "district" in columns:
        conditions.append(
            "COALESCE(NULLIF(TRIM(district), ''), '未披露') NOT IN ('海门区', '未披露')"
        )
    if not conditions:
        return
    non_haimen_count = connection.execute(
        "SELECT COUNT(*) FROM construction_permits WHERE " + " OR ".join(conditions)
    ).fetchone()[0]
    if non_haimen_count:
        raise RuntimeError(
            f"检测到 {non_haimen_count} 条非海门历史记录，migration 已安全停止"
        )


def _backfill_haimen_region(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE construction_permits
        SET province = '江苏省',
            city = '南通市',
            district = '海门区',
            region_key = '320684',
            area_code = '320684'
        WHERE district_code = '320684'
           OR district = '海门区'
           OR region_key = '320684'
           OR area_code = '320684'
        """
    )


def build_parser() -> argparse.ArgumentParser:
    default_database = Path(__file__).resolve().parents[1] / "enterprise.db"
    parser = argparse.ArgumentParser(description="为许可证表增加幂等地区字段")
    parser.add_argument("--db-path", type=Path, default=default_database)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = migrate(args.db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
