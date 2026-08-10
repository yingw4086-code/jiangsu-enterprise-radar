from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.company_registry import (
    COMPANY_REGISTRY_COLUMNS,
    CompanyRegistryRecord,
    upsert_company_registry_record,
)
from app.marketing_tracking import ensure_marketing_records_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "database" / "migrations" / "010_company_registry.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "company_registry_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompanyRegistryMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_existing_tables(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            self._create_schema9_database(db_path)

            first = migration.migrate(db_path)
            upsert_company_registry_record(
                db_path,
                CompanyRegistryRecord(
                    company_name="海门制造有限公司",
                    legal_person="张三",
                ),
            )
            second = migration.migrate(db_path)

            connection = sqlite3.connect(db_path)
            try:
                columns = tuple(
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(company_registry)"
                    )
                )
                schema_version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()[0]
                permit_count = connection.execute(
                    "SELECT COUNT(*) FROM construction_permits"
                ).fetchone()[0]
                marketing_count = connection.execute(
                    "SELECT COUNT(*) FROM marketing_records"
                ).fetchone()[0]
                registry_count = connection.execute(
                    "SELECT COUNT(*) FROM company_registry"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertTrue(first["created_table"])
        self.assertFalse(second["created_table"])
        self.assertEqual(first["permit_count_before"], 3)
        self.assertEqual(first["permit_count_after"], 3)
        self.assertEqual(second["marketing_count"], 1)
        self.assertEqual(second["company_registry_count"], 1)
        self.assertEqual(columns, COMPANY_REGISTRY_COLUMNS)
        self.assertEqual(schema_version, "10")
        self.assertEqual(permit_count, 3)
        self.assertEqual(marketing_count, 1)
        self.assertEqual(registry_count, 1)

    @staticmethod
    def _create_schema9_database(db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE construction_permits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL
                );
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '9');
                INSERT INTO construction_permits(project_name)
                VALUES('甲项目'), ('乙项目'), ('丙项目');
                """
            )
            ensure_marketing_records_table(connection)
            connection.execute(
                """
                INSERT INTO marketing_records(
                    enterprise_name, project_name, region, discovery_date,
                    customer_manager, status, follow_date,
                    estimated_credit_amount, notes
                ) VALUES('甲公司', '甲项目', '海门区', '2026-08-10',
                         '张经理', '未联系', '', 0, '')
                """
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
