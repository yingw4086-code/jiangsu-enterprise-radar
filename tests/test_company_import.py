from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from app.company_import import (
    CompanyImportConfirmationError,
    execute_company_registry_excel_import,
    list_company_import_logs,
    preview_company_registry_excel,
)
from app.company_registry import (
    CompanyRegistryRecord,
    list_company_registry_records,
    upsert_company_registry_record,
)


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


def workbook_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


class CompanyImportTest(unittest.TestCase):
    def test_preview_then_confirm_import_writes_registry_and_success_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_company_registry_record(
                db_path,
                CompanyRegistryRecord(
                    company_name="甲制造有限公司",
                    legal_person="原法人",
                ),
            )
            source = workbook_bytes(
                [
                    [
                        "甲 制造有限公司",
                        "91320684AA00000001",
                        "新法人",
                        "5000万元",
                        "2010-01-01",
                        "海门区甲路1号",
                        "制造与销售",
                        "存续",
                        "制造业",
                    ],
                    [
                        "乙科技有限公司",
                        "91320684AA00000002",
                        "李四",
                        "3000万元",
                        "2015-02-02",
                        "海门区乙路2号",
                        "技术研发",
                        "存续",
                        "科技推广和应用服务业",
                    ],
                ]
            )
            permits = [
                {"company_name": "甲制造有限公司"},
                {"construction_unit": "甲 制造有限公司"},
                {"company_name": "乙科技有限公司"},
            ]

            preview = preview_company_registry_excel(
                db_path,
                source,
                file_name="正式导入.xlsx",
                permit_items=permits,
            )
            self.assertEqual(len(list_company_registry_records(db_path)), 1)
            self.assertEqual(preview.total_count, 2)
            self.assertEqual(preview.inserted_count, 1)
            self.assertEqual(preview.updated_count, 1)
            self.assertEqual(preview.permit_matched_company_count, 2)
            self.assertEqual(preview.permit_matched_project_count, 3)
            self.assertEqual(
                [row.import_action for row in preview.rows],
                ["更新", "新增"],
            )

            result = execute_company_registry_excel_import(
                db_path,
                source,
                file_name=preview.file_name,
                expected_sha256=preview.file_sha256,
                expected_total_count=preview.total_count,
            )
            records = list_company_registry_records(db_path)
            logs = list_company_import_logs(db_path)

        self.assertEqual(result.total_count, 2)
        self.assertEqual(result.inserted_count, 1)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(len(records), 2)
        records_by_name = {record.company_name: record for record in records}
        self.assertEqual(records_by_name["甲制造有限公司"].legal_person, "新法人")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].file_name, "正式导入.xlsx")
        self.assertEqual(logs[0].success_count, 2)
        self.assertEqual(logs[0].failed_count, 0)
        self.assertEqual(logs[0].status, "success")

    def test_changed_file_is_rejected_and_failure_is_logged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            source = workbook_bytes(
                [["甲公司", "", "", "", "", "", "", "", ""]]
            )
            preview = preview_company_registry_excel(
                db_path,
                source,
                file_name="待确认.xlsx",
                permit_items=[{"company_name": "甲公司"}],
            )
            changed_source = workbook_bytes(
                [["乙公司", "", "", "", "", "", "", "", ""]]
            )

            with self.assertRaises(CompanyImportConfirmationError):
                execute_company_registry_excel_import(
                    db_path,
                    changed_source,
                    file_name="待确认.xlsx",
                    expected_sha256=preview.file_sha256,
                    expected_total_count=preview.total_count,
                )
            records = list_company_registry_records(db_path)
            logs = list_company_import_logs(db_path)

        self.assertEqual(records, [])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].success_count, 0)
        self.assertEqual(logs[0].failed_count, 1)
        self.assertEqual(logs[0].status, "failed")


if __name__ == "__main__":
    unittest.main()
