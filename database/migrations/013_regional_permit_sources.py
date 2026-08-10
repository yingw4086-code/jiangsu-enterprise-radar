from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 13
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "enterprise.db"
LEGACY_COLUMNS = (
    "id",
    "record_hash",
    "company_name",
    "project_name",
    "permit_type",
    "permit_date",
    "address",
    "construction_unit",
    "permit_number",
    "publish_date",
    "district",
    "district_code",
    "province",
    "city",
    "region_key",
    "area_code",
    "source_url",
)


def migrate(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    database_path = Path(db_path).resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    connection = sqlite3.connect(database_path)
    try:
        if not _table_exists(connection, "construction_permits"):
            raise RuntimeError("数据库缺少 construction_permits 表")
        before_count = _count(connection)
        before_haimen_count = _count(connection, "320684")
        before_fingerprint = _legacy_fingerprint(connection, "320684")
        existing_columns = _columns(connection)

        with connection:
            if "source_region" not in existing_columns:
                connection.execute(
                    "ALTER TABLE construction_permits "
                    "ADD COLUMN source_region TEXT NOT NULL DEFAULT ''"
                )
            if "source_time" not in existing_columns:
                connection.execute(
                    "ALTER TABLE construction_permits "
                    "ADD COLUMN source_time TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                UPDATE construction_permits
                SET source_region = CASE
                        WHEN source_region = '' THEN '江苏省/南通市/海门区'
                        ELSE source_region
                    END,
                    source_time = CASE
                        WHEN source_time = '' THEN COALESCE(
                            NULLIF(last_seen_at, ''),
                            NULLIF(first_seen_at, ''),
                            NULLIF(updated_at, ''),
                            NULLIF(created_at, ''),
                            ''
                        )
                        ELSE source_time
                    END
                WHERE region_key = '320684'
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_permit_region_source_time
                ON construction_permits(region_key, source_time)
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
            current = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            version = max(int(current[0]) if current else 0, SCHEMA_VERSION)
            connection.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(version),),
            )

        after_count = _count(connection)
        after_haimen_count = _count(connection, "320684")
        after_fingerprint = _legacy_fingerprint(connection, "320684")
        if before_count != after_count:
            raise RuntimeError(f"迁移改变了许可证行数：{before_count} -> {after_count}")
        if before_haimen_count != after_haimen_count:
            raise RuntimeError(
                f"迁移改变了海门行数：{before_haimen_count} -> {after_haimen_count}"
            )
        if before_fingerprint != after_fingerprint:
            raise RuntimeError("迁移修改了海门历史业务字段")

        return {
            "database": str(database_path),
            "schema_version": version,
            "total_count": after_count,
            "haimen_count": after_haimen_count,
            "haimen_legacy_fingerprint": after_fingerprint,
            "source_columns": ["source_region", "source_time"],
        }
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(construction_permits)")}


def _count(connection: sqlite3.Connection, region_key: str | None = None) -> int:
    if region_key is None:
        return int(connection.execute("SELECT COUNT(*) FROM construction_permits").fetchone()[0])
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM construction_permits WHERE region_key=?",
            (region_key,),
        ).fetchone()[0]
    )


def _legacy_fingerprint(connection: sqlite3.Connection, region_key: str) -> str:
    rows = connection.execute(
        f"SELECT {', '.join(LEGACY_COLUMNS)} FROM construction_permits "
        "WHERE region_key=? ORDER BY id",
        (region_key,),
    ).fetchall()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add regional permit source fields")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(json.dumps(migrate(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
