from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.permit_ownership import (
    GOVERNMENT_AGENCY,
    PRIVATE_ENTERPRISE,
    STATE_OWNED_COMMERCIAL,
    UNKNOWN_OWNERSHIP,
    classify_permit_owner,
    load_ownership_overrides,
)
from database.permit_ownership import classify_and_update_permit_owners
from database.storage import upsert_planning_construction_permits
from tests.test_planning_permit_storage import permit_record


class PermitOwnershipRulesTest(unittest.TestCase):
    def test_limited_company_is_not_automatically_private(self):
        result = classify_permit_owner("海门示例科技有限公司")

        self.assertEqual(result.owner_category, UNKNOWN_OWNERSHIP)
        self.assertFalse(result.marketing_eligible)
        self.assertTrue(result.manual_review_required)

    def test_government_is_excluded_and_state_owned_business_is_retained(self):
        government = classify_permit_owner("南通市海门区三星镇人民政府")
        state_owned = classify_permit_owner("南通市海门正丰建设投资有限公司")

        self.assertEqual(government.owner_category, GOVERNMENT_AGENCY)
        self.assertFalse(government.marketing_eligible)
        self.assertEqual(government.marketing_priority, "排除")
        self.assertEqual(state_owned.owner_category, STATE_OWNED_COMMERCIAL)
        self.assertTrue(state_owned.marketing_eligible)
        self.assertEqual(state_owned.marketing_priority, "B")

    def test_missing_owner_requires_manual_review(self):
        result = classify_permit_owner("未披露")

        self.assertEqual(result.owner_name, "未披露")
        self.assertEqual(result.owner_category, UNKNOWN_OWNERSHIP)
        self.assertEqual(result.ownership_confidence, 0)
        self.assertTrue(result.manual_review_required)

    def test_manual_override_has_priority_over_name_rule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "overrides.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "company_name",
                        "unified_social_credit_code",
                        "ownership_type",
                        "owner_category",
                        "marketing_eligible",
                        "marketing_priority",
                        "classification_basis",
                        "verified_at",
                        "notes",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "company_name": "示例产业有限公司",
                        "ownership_type": PRIVATE_ENTERPRISE,
                        "owner_category": PRIVATE_ENTERPRISE,
                        "marketing_eligible": "true",
                        "marketing_priority": "A",
                        "classification_basis": "人工核验企业登记类型",
                    }
                )

            overrides = load_ownership_overrides(path)
            result = classify_permit_owner("示例产业有限公司", overrides)

        self.assertEqual(result.owner_category, PRIVATE_ENTERPRISE)
        self.assertEqual(result.ownership_confidence, 100)
        self.assertEqual(result.ownership_basis, "人工核验企业登记类型")
        self.assertTrue(result.marketing_eligible)


class PermitOwnershipPersistenceTest(unittest.TestCase):
    def test_classification_is_repeatable_and_preserves_original_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            overrides_path = root / "overrides.csv"
            report_path = root / "ownership_report.csv"
            overrides_path.write_text(
                "company_name,unified_social_credit_code,ownership_type,owner_category,"
                "marketing_eligible,marketing_priority,classification_basis,verified_at,notes\n",
                encoding="utf-8",
            )
            records = [
                permit_record(
                    company_name="南通市海门区三星镇人民政府",
                    project_name="政府项目",
                    permit_number="GOV-1",
                    source_url="https://example.gov.cn/gov",
                ),
                permit_record(
                    company_name="南通市海门正丰建设投资有限公司",
                    project_name="国有商业项目",
                    permit_number="SOE-1",
                    source_url="https://example.gov.cn/soe",
                ),
                permit_record(
                    company_name="示例科技有限公司",
                    project_name="待核验项目",
                    permit_number="UNK-1",
                    source_url="https://example.gov.cn/unknown",
                ),
                permit_record(
                    company_name="未披露",
                    project_name="主体缺失项目",
                    permit_number="MISS-1",
                    source_url="https://example.gov.cn/missing",
                ),
            ]
            upsert_planning_construction_permits(db_path, records)
            before = self._original_rows(db_path)

            first = classify_and_update_permit_owners(
                db_path,
                overrides_path,
                report_path,
            )
            second = classify_and_update_permit_owners(
                db_path,
                overrides_path,
                report_path,
            )
            after = self._original_rows(db_path)

            self.assertEqual(first.total_records, 4)
            self.assertEqual(first.government_count, 1)
            self.assertEqual(first.state_owned_count, 1)
            self.assertEqual(first.unknown_count, 2)
            self.assertEqual(first.updated_count, 4)
            self.assertEqual(second.updated_count, 0)
            self.assertEqual(second.unchanged_count, 4)
            self.assertEqual(before, after)
            self.assertTrue(report_path.exists())
            self.assertEqual(
                len(report_path.read_text(encoding="utf-8-sig").splitlines()),
                5,
            )

    @staticmethod
    def _original_rows(db_path: Path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                """
                SELECT
                    record_hash,
                    company_name,
                    project_name,
                    permit_type,
                    permit_number,
                    permit_date,
                    publish_date,
                    address,
                    raw_json
                FROM construction_permits
                ORDER BY id
                """
            ).fetchall()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
