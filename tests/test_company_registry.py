from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from app.company_registry import (
    COMPANY_REGISTRY_COLUMNS,
    REGISTRY_REQUIRED_FIELDS,
    CompanyRegistryRecord,
    CompanyRegistryValidationError,
    assess_registry_completeness,
    enrich_items_with_company_registry,
    enrich_item_with_company_registry,
    enrich_registry_completeness,
    get_company_registry_record,
    list_company_registry_records,
    lookup_and_store_company_registry,
    upsert_company_registry_record,
)


def registry_record(**overrides):
    values = {
        "company_name": "海门智能装备有限公司",
        "unified_social_credit_code": "91320684MA12345678",
        "legal_person": "张三",
        "registered_capital": "1亿元",
        "establish_date": "2012-05-06",
        "company_address": "江苏省南通市海门区示例路1号",
        "business_scope": "智能装备研发、制造和销售",
        "company_status": "存续",
        "industry": "智能装备制造",
        "data_source": "public_test_fixture",
        "source_url": "https://example.gov.cn/company/1",
        "verified_at": "2026-08-10",
    }
    values.update(overrides)
    return CompanyRegistryRecord(**values)


@dataclass
class StubRegistryProvider:
    record: CompanyRegistryRecord | None
    provider_name: str = "stub_public_registry"

    def lookup(self, company_name: str) -> CompanyRegistryRecord | None:
        return self.record


class CompanyRegistryTest(unittest.TestCase):
    def test_upsert_is_repeatable_and_schema_contains_required_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            first = upsert_company_registry_record(db_path, registry_record())
            second = upsert_company_registry_record(
                db_path,
                registry_record(legal_person="李四", company_status="在营"),
            )
            records = list_company_registry_records(db_path)
            connection = sqlite3.connect(db_path)
            try:
                columns = tuple(
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(company_registry)"
                    )
                )
            finally:
                connection.close()

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.legal_person, "李四")
        self.assertEqual(second.company_status, "在营")
        self.assertEqual(len(records), 1)
        self.assertEqual(columns, COMPANY_REGISTRY_COLUMNS)
        self.assertTrue(set(REGISTRY_REQUIRED_FIELDS).issubset(columns))

    def test_get_missing_record_and_validation_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            self.assertIsNone(get_company_registry_record(db_path, "未收录企业"))
            with self.assertRaises(CompanyRegistryValidationError):
                upsert_company_registry_record(
                    db_path,
                    registry_record(unified_social_credit_code="INVALID"),
                )
            with self.assertRaises(CompanyRegistryValidationError):
                upsert_company_registry_record(
                    db_path,
                    registry_record(establish_date="2012/05/06"),
                )
            with self.assertRaises(CompanyRegistryValidationError):
                upsert_company_registry_record(
                    db_path,
                    registry_record(company_name="未披露"),
                )

    def test_sparse_update_does_not_erase_verified_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_company_registry_record(db_path, registry_record())

            updated = upsert_company_registry_record(
                db_path,
                CompanyRegistryRecord(
                    company_name="海门智能装备有限公司",
                    company_status="在营",
                ),
            )

        self.assertEqual(updated.company_status, "在营")
        self.assertEqual(updated.legal_person, "张三")
        self.assertEqual(updated.registered_capital, "1亿元")
        self.assertEqual(updated.data_source, "public_test_fixture")

    def test_enrichment_preserves_original_and_adds_registry_data(self):
        original = {
            "company_name": "海门智能装备有限公司",
            "project_name": "生产基地项目",
            "industry": "未披露",
        }

        enriched = enrich_item_with_company_registry(original, registry_record())

        self.assertNotIn("legal_person", original)
        self.assertEqual(enriched["legal_person"], "张三")
        self.assertEqual(enriched["registered_capital"], "1亿元")
        self.assertEqual(enriched["business_scope"], "智能装备研发、制造和销售")
        self.assertEqual(enriched["industry"], "智能装备制造")
        self.assertTrue(enriched["registry_data_available"])

    def test_project_company_name_is_matched_to_registry_automatically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_company_registry_record(db_path, registry_record())

            enriched = enrich_items_with_company_registry(
                [
                    {
                        "company_name": "海门 智能装备有限公司",
                        "project_name": "生产基地项目",
                    }
                ],
                db_path,
            )[0]

        self.assertEqual(enriched["legal_person"], "张三")
        self.assertEqual(enriched["company_match_status"], "matched")
        self.assertEqual(enriched["company_match_method"], "normalized_exact")

    def test_registry_completeness_levels_follow_requested_thresholds(self):
        full = registry_record().to_fields()
        cases = (
            (full, (100, "A")),
            (full | {"industry": ""}, (88, "B")),
            (
                full
                | {
                    "industry": "",
                    "company_status": "",
                },
                (75, "B"),
            ),
            (
                {
                    "legal_person": "张三",
                    "registered_capital": "1亿元",
                    "establish_date": "2012-05-06",
                    "company_address": "海门区示例路1号",
                },
                (50, "C"),
            ),
            ({"legal_person": "张三"}, (12, "D")),
        )
        for item, expected in cases:
            with self.subTest(expected=expected):
                assessment = assess_registry_completeness(item)
                self.assertEqual((assessment.percentage, assessment.level), expected)

        enriched = enrich_registry_completeness({"legal_person": "张三"})
        self.assertEqual(enriched["registry_completeness_label"], "D 待补充")

    def test_provider_interface_is_injected_and_does_not_require_an_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            provider = StubRegistryProvider(
                registry_record(data_source="stub_public_registry")
            )

            stored = lookup_and_store_company_registry(
                db_path,
                "海门智能装备有限公司",
                provider,
            )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.data_source, "stub_public_registry")
        self.assertEqual(stored.legal_person, "张三")

    def test_provider_name_is_used_when_record_does_not_supply_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            provider = StubRegistryProvider(
                CompanyRegistryRecord(
                    company_name="海门智能装备有限公司",
                    legal_person="张三",
                )
            )

            stored = lookup_and_store_company_registry(
                db_path,
                "海门智能装备有限公司",
                provider,
            )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.data_source, "stub_public_registry")


if __name__ == "__main__":
    unittest.main()
