from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.company_registry_history import COMPANY_REGISTRY_HISTORY_COLUMNS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "012_company_registry_history.py"
)


def load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "company_registry_history_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompanyRegistryHistoryMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_permits(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE construction_permits(id INTEGER PRIMARY KEY, name TEXT);
                INSERT INTO construction_permits(name) VALUES('保留项目');
                CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '11');
                """
            )
            connection.commit()
            connection.close()

            first = migration.migrate(db_path)
            second = migration.migrate(db_path)

            connection = sqlite3.connect(db_path)
            columns = tuple(
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(company_registry_history)"
                )
            )
            permit_count = connection.execute(
                "SELECT COUNT(*) FROM construction_permits"
            ).fetchone()[0]
            history_count = connection.execute(
                "SELECT COUNT(*) FROM company_registry_history"
            ).fetchone()[0]
            version = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            connection.close()

        self.assertTrue(first["created_table"])
        self.assertFalse(second["created_table"])
        self.assertEqual(columns, COMPANY_REGISTRY_HISTORY_COLUMNS)
        self.assertEqual(permit_count, 1)
        self.assertEqual(history_count, 0)
        self.assertEqual(version, "12")


if __name__ == "__main__":
    unittest.main()
