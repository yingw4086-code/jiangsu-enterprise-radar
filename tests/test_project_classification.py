from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from data_source.project_classification import (
    ENTERPRISE_KEYWORDS,
    ENTERPRISE_PROJECT_SIGNALS,
    GOVERNMENT_KEYWORDS,
    classify_project,
    classify_project_type,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "database" / "migrations" / "007_project_type.py"
CONFIDENCE_MIGRATION_PATH = (
    PROJECT_ROOT / "database" / "migrations" / "008_classification_confidence.py"
)


def load_migration_module():
    spec = importlib.util.spec_from_file_location("project_type_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_confidence_migration_module():
    spec = importlib.util.spec_from_file_location(
        "classification_confidence_migration",
        CONFIDENCE_MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{CONFIDENCE_MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectClassificationRuleTest(unittest.TestCase):
    def test_enterprise_keyword_has_priority(self):
        self.assertEqual(
            classify_project_type(
                company_name="某市政府产业投资有限公司",
                project_name="市政道路项目",
            ),
            "enterprise",
        )

    def test_government_keywords_use_subject_and_project_text(self):
        cases = (
            {"company_name": "某区人民政府"},
            {"company_name": "未披露", "construction_unit": "市交通局"},
            {"company_name": "未披露", "project_name": "城市道路改造"},
            {"company_name": "未披露", "project_name": "学校扩建"},
            {"company_name": "未披露", "project_name": "医院政府建设项目"},
        )
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(classify_project_type(**case), "government")

    def test_private_hospital_company_remains_enterprise(self):
        self.assertEqual(
            classify_project_type(
                company_name="海门仁爱医院有限公司",
                project_name="医院扩建",
            ),
            "enterprise",
        )

    def test_unmatched_record_is_unknown(self):
        self.assertEqual(
            classify_project_type(
                company_name="海门经济技术开发区管理委员会",
                project_name="产业园项目",
            ),
            "unknown",
        )

    def test_all_phase22_enterprise_keywords_are_high_confidence(self):
        for keyword in ENTERPRISE_KEYWORDS:
            with self.subTest(keyword=keyword):
                result = classify_project(company_name=f"海门{keyword}")
                self.assertEqual(result.project_type, "enterprise")
                self.assertEqual(result.confidence, "high")

    def test_all_phase22_government_keywords_are_detected(self):
        for keyword in GOVERNMENT_KEYWORDS:
            with self.subTest(keyword=keyword):
                result = classify_project(
                    company_name="未披露",
                    project_name=f"海门{keyword}建设项目",
                )
                self.assertEqual(result.project_type, "government")
                self.assertEqual(result.confidence, "medium")

    def test_government_subject_keyword_is_high_confidence(self):
        result = classify_project(
            company_name="未披露",
            construction_unit="海门区财政局",
            project_name="办公楼改造",
        )
        self.assertEqual(result.project_type, "government")
        self.assertEqual(result.confidence, "high")

    def test_project_signals_raise_enterprise_to_medium_confidence(self):
        for signal in ENTERPRISE_PROJECT_SIGNALS:
            with self.subTest(signal=signal):
                result = classify_project(
                    company_name="未披露",
                    project_name=f"高端装备{signal}项目",
                )
                self.assertEqual(result.project_type, "enterprise")
                self.assertEqual(result.confidence, "medium")

    def test_government_keyword_precedes_project_enterprise_signal(self):
        result = classify_project(
            company_name="未披露",
            project_name="学校扩建项目",
        )
        self.assertEqual(result.project_type, "government")
        self.assertEqual(result.confidence, "medium")

    def test_unknown_has_low_confidence(self):
        result = classify_project(
            company_name="未披露",
            project_name="产业园新建项目",
        )
        self.assertEqual(result.project_type, "unknown")
        self.assertEqual(result.confidence, "low")


class ProjectTypeMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_all_rows(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            self._create_schema6_database(db_path)

            first = migration.migrate(db_path)
            second = migration.migrate(db_path)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    "SELECT company_name, project_type FROM construction_permits ORDER BY id"
                ).fetchall()
                schema_version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()[0]
                index_names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(construction_permits)")
                }
            finally:
                connection.close()

        self.assertEqual(first["row_count_before"], 4)
        self.assertEqual(first["row_count_after"], 4)
        self.assertEqual(
            first["counts"],
            {"enterprise": 1, "government": 2, "unknown": 1},
        )
        self.assertEqual(second["added_columns"], [])
        self.assertEqual(second["counts"], first["counts"])
        self.assertEqual([row[1] for row in rows], [
            "enterprise",
            "government",
            "government",
            "unknown",
        ])
        self.assertEqual(schema_version, "7")
        self.assertIn("idx_permit_region_project_type", index_names)

    @staticmethod
    def _create_schema6_database(db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE construction_permits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    construction_unit TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    region_key TEXT NOT NULL
                );
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '6');
                """
            )
            connection.executemany(
                """
                INSERT INTO construction_permits(
                    company_name, construction_unit, project_name, region_key
                ) VALUES (?, ?, ?, '320684')
                """,
                (
                    ("海门制造有限公司", "海门制造有限公司", "市政道路项目"),
                    ("海门区人民政府", "海门区人民政府", "办公楼项目"),
                    ("未披露", "未披露", "学校扩建项目"),
                    ("海门经济技术开发区管理委员会", "未披露", "产业园项目"),
                ),
            )
            connection.commit()
        finally:
            connection.close()


class ClassificationConfidenceMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_all_rows(self):
        migration = load_confidence_migration_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            self._create_schema7_database(db_path)

            first = migration.migrate(db_path)
            second = migration.migrate(db_path)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT project_type, classification_confidence
                    FROM construction_permits
                    ORDER BY id
                    """
                ).fetchall()
                schema_version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()[0]
                index_names = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(construction_permits)")
                }
            finally:
                connection.close()

        self.assertEqual(first["row_count_before"], 5)
        self.assertEqual(first["row_count_after"], 5)
        self.assertEqual(
            first["project_type_counts"],
            {"enterprise": 2, "government": 2, "unknown": 1},
        )
        self.assertEqual(
            first["confidence_counts"],
            {"high": 2, "medium": 2, "low": 1},
        )
        self.assertEqual(second["added_columns"], [])
        self.assertEqual(second["project_type_counts"], first["project_type_counts"])
        self.assertEqual(second["confidence_counts"], first["confidence_counts"])
        self.assertEqual(
            rows,
            [
                ("enterprise", "high"),
                ("government", "high"),
                ("government", "medium"),
                ("enterprise", "medium"),
                ("unknown", "low"),
            ],
        )
        self.assertEqual(schema_version, "8")
        self.assertIn("idx_permit_region_project_classification", index_names)

    @staticmethod
    def _create_schema7_database(db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE construction_permits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    construction_unit TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    project_type TEXT NOT NULL DEFAULT 'unknown',
                    region_key TEXT NOT NULL
                );
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '7');
                """
            )
            connection.executemany(
                """
                INSERT INTO construction_permits(
                    company_name, construction_unit, project_name,
                    project_type, region_key
                ) VALUES (?, ?, ?, 'unknown', '320684')
                """,
                (
                    ("海门新能源集团", "海门新能源集团", "市政道路项目"),
                    ("海门区人民政府", "海门区人民政府", "办公楼项目"),
                    ("未披露", "未披露", "学校扩建项目"),
                    ("未披露", "未披露", "年产高端装备项目"),
                    ("未披露", "未披露", "产业园新建项目"),
                ),
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
