from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.company_import import COMPANY_IMPORT_LOG_COLUMNS
from app.company_registry import ensure_company_registry_table
from app.marketing_tracking import ensure_marketing_records_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "011_company_import_logs.py"
)


def load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "company_import_logs_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompanyImportMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_existing_data(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            self._create_schema10_database(db_path)

            first = migration.migrate(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO company_import_logs(
                        import_time, file_name, total_count, success_count,
                        failed_count, inserted_count, updated_count, status,
                        error_message, file_sha256
                    ) VALUES('2026-08-10T18:30:00', '测试.xlsx', 2, 2, 0,
                             2, 0, 'success', '', 'ABC')
                    """
                )
                connection.commit()
            finally:
                connection.close()
            second = migration.migrate(db_path)

            connection = sqlite3.connect(db_path)
            try:
                columns = tuple(
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(company_import_logs)"
                    )
                )
                schema_version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()[0]
                counts = {
                    table: connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    for table in (
                        "construction_permits",
                        "marketing_records",
                        "company_registry",
                        "company_import_logs",
                    )
                }
            finally:
                connection.close()

        self.assertTrue(first["created_table"])
        self.assertFalse(second["created_table"])
        self.assertEqual(columns, COMPANY_IMPORT_LOG_COLUMNS)
        self.assertEqual(schema_version, "11")
        self.assertEqual(
            counts,
            {
                "construction_permits": 3,
                "marketing_records": 1,
                "company_registry": 1,
                "company_import_logs": 1,
            },
        )

    @staticmethod
    def _create_schema10_database(db_path: Path) -> None:
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
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '10');
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
            ensure_company_registry_table(connection)
            connection.execute(
                """
                INSERT INTO company_registry(
                    company_name, created_at, updated_at
                ) VALUES('甲公司', '2026-08-10T18:30:00',
                         '2026-08-10T18:30:00')
                """
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
