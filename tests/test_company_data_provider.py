from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from app.company_data_provider import (
    CompanyDataProviderNotConfigured,
    CompanyExcelValidationError,
    ExcelCompanyDataProvider,
    NationalEnterpriseCreditProvider,
    ThirdPartyCompanyDataProvider,
)
from app.company_registry import (
    CompanyRegistryRecord,
    enrich_items_with_company_registry,
    enrich_registry_completeness,
    import_company_registry_excel,
    list_company_registry_records,
    upsert_company_registry_record,
)
from app.enterprise_profile_enhance import build_enhanced_enterprise_profile


HEADERS = [
    "企业名称",
    "统一社会信用代码",
    "法人",
    "注册资本",
    "成立日期",
    "注册地址",
    "经营范围",
    "企业状态",
    "行业",
]


def workbook_bytes(rows, headers=HEADERS):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


class CompanyDataProviderTest(unittest.TestCase):
    def test_reserved_network_providers_do_not_call_external_services(self):
        with self.assertRaises(CompanyDataProviderNotConfigured):
            NationalEnterpriseCreditProvider().lookup("示例企业")
        with self.assertRaises(CompanyDataProviderNotConfigured):
            ThirdPartyCompanyDataProvider().lookup("示例企业")

    def test_excel_provider_reads_requested_columns_and_normalizes_date(self):
        provider = ExcelCompanyDataProvider(
            workbook_bytes(
                [
                    [
                        "海门智能装备有限公司",
                        "91320684MA12345678",
                        "张三",
                        "1亿元",
                        datetime(2012, 5, 6),
                        "海门区示例路1号",
                        "智能装备制造",
                        "存续",
                        "装备制造业",
                    ]
                ]
            )
        )

        item = provider.load_records()[0]

        self.assertEqual(item.row_number, 2)
        self.assertEqual(item.record.establish_date, "2012-05-06")
        self.assertEqual(item.record.business_scope, "智能装备制造")
        self.assertEqual(item.record.company_status, "存续")
        self.assertEqual(item.record.industry, "装备制造业")
        self.assertEqual(item.record.data_source, "user_excel_import")
        self.assertEqual(
            provider.lookup("海门 智能装备有限公司").legal_person,
            "张三",
        )

    def test_excel_provider_accepts_industry_classification_header(self):
        headers = [*HEADERS[:-1], "行业分类"]
        provider = ExcelCompanyDataProvider(
            workbook_bytes(
                [["测试企业", "", "", "", "", "", "", "", "新能源产业"]],
                headers=headers,
            )
        )

        self.assertEqual(provider.load_records()[0].record.industry, "新能源产业")

    def test_excel_provider_rejects_missing_headers_and_duplicate_names(self):
        with self.assertRaises(CompanyExcelValidationError):
            ExcelCompanyDataProvider(
                workbook_bytes([], headers=["企业名称"])
            ).load_records()
        with self.assertRaises(CompanyExcelValidationError):
            ExcelCompanyDataProvider(
                workbook_bytes(
                    [
                        ["甲 公司", "", "", "", "", "", "", "", ""],
                        ["甲公司", "", "", "", "", "", "", "", ""],
                    ]
                )
            ).load_records()

    def test_excel_import_updates_normalized_match_without_blank_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_company_registry_record(
                db_path,
                CompanyRegistryRecord(
                    company_name="海门智能装备有限公司",
                    legal_person="原法人",
                    business_scope="智能装备制造",
                    company_status="存续",
                    data_source="verified_fixture",
                ),
            )
            result = import_company_registry_excel(
                db_path,
                workbook_bytes(
                    [
                        [
                            "海门 智能装备有限公司",
                            "91320684MA12345678",
                            "新法人",
                            "1亿元",
                            "2012/05/06",
                            "海门区示例路1号",
                            "",
                            "",
                            "装备制造业",
                        ]
                    ]
                ),
            )
            records = list_company_registry_records(db_path)
            enriched_item = enrich_registry_completeness(
                enrich_items_with_company_registry(
                    [
                        {
                            "company_name": "海门智能装备有限公司",
                            "project_name": "生产基地项目",
                            "industry": "项目行业",
                        }
                    ],
                    db_path,
                )[0]
            )
            profile = build_enhanced_enterprise_profile(enriched_item)

        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.inserted_count, 0)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(result.matched_existing_count, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].company_name, "海门智能装备有限公司")
        self.assertEqual(records[0].legal_person, "新法人")
        self.assertEqual(records[0].business_scope, "智能装备制造")
        self.assertEqual(profile.legal_person, "新法人")
        self.assertEqual(profile.registered_capital, "1亿元")
        self.assertEqual(enriched_item["registry_completeness_percentage"], 100)
        self.assertEqual(enriched_item["registry_completeness_level"], "A")


if __name__ == "__main__":
    unittest.main()
