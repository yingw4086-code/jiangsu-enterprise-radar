from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.permit_data import load_planning_permit_dataset
from database.storage import upsert_planning_construction_permits
from tests.test_planning_permit_storage import permit_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "database" / "migrations" / "006_region_fields.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location("region_fields_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegionMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_legacy_rows(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            self._create_legacy_database(db_path, row_count=3)

            first = migration.migrate(db_path)
            second = migration.migrate(db_path)

            connection = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(construction_permits)"
                    )
                }
                region_rows = connection.execute(
                    """
                    SELECT province, city, district, region_key, area_code
                    FROM construction_permits
                    ORDER BY id
                    """
                ).fetchall()
                schema_version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(first["row_count_before"], 3)
            self.assertEqual(first["row_count_after"], 3)
            self.assertEqual(first["haimen_count"], 3)
            self.assertEqual(second["row_count_after"], 3)
            self.assertEqual(second["added_columns"], [])
            self.assertTrue(
                {"province", "city", "district", "region_key", "area_code"}.issubset(
                    columns
                )
            )
            self.assertEqual(
                region_rows,
                [("江苏省", "南通市", "海门区", "320684", "320684")] * 3,
            )
            self.assertEqual(schema_version, "6")

    def test_sqlite_query_isolated_by_region_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            upsert_planning_construction_permits(
                db_path,
                [
                    permit_record(project_name="海门项目"),
                    permit_record(
                        project_name="昆山项目",
                        permit_number="建字第3205832026GG0002001号",
                        source_url="https://example.gov.cn/permit/kunshan",
                    ),
                ],
            )
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    UPDATE construction_permits
                    SET province = '江苏省',
                        city = '苏州市',
                        district = '昆山市',
                        district_code = '320583',
                        region_key = '320583',
                        area_code = '320583'
                    WHERE project_name = '昆山项目'
                    """
                )
                connection.commit()
            finally:
                connection.close()

            haimen = load_planning_permit_dataset(
                db_path,
                root / "missing.json",
                region_key="320684",
            )
            kunshan = load_planning_permit_dataset(
                db_path,
                root / "missing.json",
                region_key="320583",
            )

            self.assertEqual(
                [item["project_name"] for item in haimen.items],
                ["海门项目"],
            )
            self.assertEqual(
                [item["project_name"] for item in kunshan.items],
                ["昆山项目"],
            )
            self.assertEqual(haimen.items[0]["region_key"], "320684")
            self.assertEqual(kunshan.items[0]["region_key"], "320583")

    @staticmethod
    def _create_legacy_database(db_path: Path, *, row_count: int) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE construction_permits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    permit_type TEXT NOT NULL,
                    permit_date TEXT NOT NULL,
                    district TEXT NOT NULL,
                    district_code TEXT NOT NULL,
                    source_url TEXT NOT NULL
                );
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '4');
                """
            )
            connection.executemany(
                """
                INSERT INTO construction_permits(
                    permit_type, permit_date, district, district_code, source_url
                ) VALUES(?, ?, ?, ?, ?)
                """,
                [
                    (
                        "建设工程规划许可证",
                        f"2026-07-{20 + index:02d}",
                        "海门区",
                        "320684",
                        f"https://example.gov.cn/{index}",
                    )
                    for index in range(row_count)
                ],
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
