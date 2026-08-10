from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.company_import import execute_company_registry_excel_import
from app.company_registry import (
    enrich_items_with_company_registry,
    enrich_registry_completeness,
)
from app.company_registry_history import list_company_registry_history
from app.enterprise_profile_enhance import (
    assess_company_strength,
    build_enhanced_enterprise_profile,
    enrich_company_strength,
)
from app.finance_scoring import enrich_finance_opportunities
from app.industry_classification import enrich_industry_assessment
from app.marketing_report import build_marketing_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = PROJECT_ROOT / "database" / "enterprise.db"
WORKBOOK = (
    PROJECT_ROOT
    / "outputs"
    / "phase3_12"
    / "company_registry_profile_test_10.xlsx"
)
MIGRATION = (
    PROJECT_ROOT / "database" / "migrations" / "012_company_registry_history.py"
)


def load_migration_module():
    spec = importlib.util.spec_from_file_location("phase312_migration", MIGRATION)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 migration：{MIGRATION}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase312IntegrationTest(unittest.TestCase):
    def test_ten_company_import_links_profile_score_report_and_preserves_permits(self):
        self.assertTrue(WORKBOOK.exists())
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise_phase312_test.db"
            shutil.copy2(PRODUCTION_DB, db_path)
            connection = sqlite3.connect(db_path)
            permits_before = connection.execute(
                "SELECT COUNT(*) FROM construction_permits"
            ).fetchone()[0]
            haimen_before = connection.execute(
                "SELECT COUNT(*) FROM construction_permits WHERE region_key='320684'"
            ).fetchone()[0]
            registry_before = connection.execute(
                "SELECT COUNT(*) FROM company_registry"
            ).fetchone()[0]
            connection.close()

            migration_result = load_migration_module().migrate(db_path)
            raw = WORKBOOK.read_bytes()
            digest = hashlib.sha256(raw).hexdigest().upper()
            result = execute_company_registry_excel_import(
                db_path,
                raw,
                file_name=WORKBOOK.name,
                expected_sha256=digest,
                expected_total_count=10,
            )

            sample = {
                "company_name": "欧派智能装备（南通）有限公司",
                "construction_unit": "欧派智能装备（南通）有限公司",
                "project_name": "智能装备生产基地扩建项目",
                "project_type": "enterprise",
                "permit_type": "建设工程施工许可证",
                "publish_date": "2026-08-01",
                "region_key": "320684",
                "province": "江苏省",
                "city": "南通市",
                "district": "海门区",
            }
            enriched = enrich_items_with_company_registry([sample], db_path)[0]
            enriched = enrich_registry_completeness(enriched)
            enriched = enrich_industry_assessment(enriched)
            enriched = enrich_company_strength(enriched, today=date(2026, 8, 10))
            enriched = enrich_finance_opportunities(
                [enriched], today=date(2026, 8, 10)
            )[0]
            profile = build_enhanced_enterprise_profile(enriched)
            strength = assess_company_strength(
                enriched, profile=profile, today=date(2026, 8, 10)
            )
            report = build_marketing_report(enriched)
            history = list_company_registry_history(db_path, limit=1000)

            connection = sqlite3.connect(db_path)
            permits_after = connection.execute(
                "SELECT COUNT(*) FROM construction_permits"
            ).fetchone()[0]
            haimen_after = connection.execute(
                "SELECT COUNT(*) FROM construction_permits WHERE region_key='320684'"
            ).fetchone()[0]
            registry_after = connection.execute(
                "SELECT COUNT(*) FROM company_registry"
            ).fetchone()[0]
            history_after = connection.execute(
                "SELECT COUNT(*) FROM company_registry_history"
            ).fetchone()[0]
            connection.close()

        self.assertEqual(permits_after, permits_before)
        self.assertEqual(haimen_before, 225)
        self.assertEqual(haimen_after, haimen_before)
        self.assertEqual(registry_before, 10)
        self.assertEqual(registry_after, 10)
        self.assertGreaterEqual(migration_result["schema_version"], 12)
        self.assertEqual(result.total_count, 10)
        self.assertEqual(result.inserted_count, 0)
        self.assertEqual(result.updated_count, 10)
        self.assertEqual(result.history_count, 80)
        self.assertEqual(history_after, 80)
        self.assertEqual(len(history), 80)
        self.assertEqual(enriched["registry_completeness_percentage"], 100)
        self.assertEqual(enriched["registry_completeness_level"], "A")
        self.assertEqual(enriched["industry_classification"], "装备制造业")
        self.assertEqual(enriched["industry_classification_confidence"], "high")
        self.assertNotEqual(strength.strength_level, "D")
        self.assertGreater(enriched["finance_score"], 0)
        self.assertEqual(report.company_name, "欧派智能装备（南通）有限公司")
        self.assertEqual(len(report.sections), 8)


if __name__ == "__main__":
    unittest.main()
