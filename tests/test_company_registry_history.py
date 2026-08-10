from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from app.company_registry import (
    CompanyRegistryRecord,
    get_company_registry_record,
    import_company_registry_excel,
    upsert_company_registry_record,
)
from app.company_registry_history import list_company_registry_history


HEADERS = [
    "企业名称",
    "统一社会信用代码",
    "法人",
    "注册资本",
    "成立日期",
    "注册地址",
    "经营范围",
    "企业状态",
    "行业分类",
]


def workbook_bytes(row: list[str]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


class CompanyRegistryHistoryTest(unittest.TestCase):
    def test_excel_overwrite_is_audited_and_blank_fields_preserve_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_company_registry_record(
                db_path,
                CompanyRegistryRecord(
                    company_name="测试装备有限公司",
                    legal_person="原法人",
                    business_scope="原经营范围",
                    data_source="verified_fixture",
                ),
            )
            raw = workbook_bytes(
                ["测试装备有限公司", "", "新法人", "", "", "", "", "", ""]
            )

            first = import_company_registry_excel(
                db_path,
                raw,
                import_file_name="phase3_12.xlsx",
                file_sha256="ABCD",
            )
            second = import_company_registry_excel(
                db_path,
                raw,
                import_file_name="phase3_12.xlsx",
                file_sha256="ABCD",
            )
            stored = get_company_registry_record(db_path, "测试装备有限公司")
            history = list_company_registry_history(
                db_path, company_name="测试装备有限公司"
            )

        self.assertEqual(first.history_count, 1)
        self.assertEqual(second.history_count, 0)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.legal_person, "新法人")
        self.assertEqual(stored.business_scope, "原经营范围")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].field_name, "legal_person")
        self.assertEqual(history[0].old_value, "原法人")
        self.assertEqual(history[0].new_value, "新法人")
        self.assertEqual(history[0].change_type, "update")
        self.assertEqual(history[0].import_file_name, "phase3_12.xlsx")
        self.assertEqual(history[0].file_sha256, "ABCD")


if __name__ == "__main__":
    unittest.main()
