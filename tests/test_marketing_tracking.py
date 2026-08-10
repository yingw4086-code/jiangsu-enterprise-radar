from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.marketing_tracking import (
    MARKETING_RECORD_COLUMNS,
    MARKETING_STATUSES,
    MarketingTrackingValidationError,
    add_marketing_record,
    list_marketing_records,
    update_marketing_record,
)


class MarketingTrackingTest(unittest.TestCase):
    def test_statuses_match_phase35_contract(self):
        self.assertEqual(
            MARKETING_STATUSES,
            (
                "未联系",
                "已电话",
                "已拜访",
                "资料收集中",
                "授信审批中",
                "已放款",
                "暂缓",
            ),
        )

    def test_add_is_idempotent_and_schema_has_requested_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            first = add_marketing_record(
                db_path,
                enterprise_name="海门制造有限公司",
                project_name="生产基地项目",
                region="江苏省 / 南通市 / 海门区",
                discovery_date="2026-08-10",
            )
            second = add_marketing_record(
                db_path,
                enterprise_name="海门制造有限公司",
                project_name="生产基地项目",
                region="江苏省 / 南通市 / 海门区",
                discovery_date="2026-08-11",
            )

            connection = sqlite3.connect(db_path)
            try:
                columns = tuple(
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(marketing_records)"
                    )
                )
                count = connection.execute(
                    "SELECT COUNT(*) FROM marketing_records"
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(first.id, second.id)
            self.assertEqual(second.discovery_date, "2026-08-10")
            self.assertEqual(count, 1)
            self.assertEqual(columns, MARKETING_RECORD_COLUMNS)

    def test_update_filter_and_recent_follow_sort(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            older = add_marketing_record(
                db_path,
                enterprise_name="甲公司",
                project_name="甲项目",
                region="海门区",
                discovery_date="2026-08-01",
            )
            newer = add_marketing_record(
                db_path,
                enterprise_name="乙公司",
                project_name="乙项目",
                region="海门区",
                discovery_date="2026-08-02",
            )
            update_marketing_record(
                db_path,
                older.id,
                customer_manager="张经理",
                status="已电话",
                follow_date="2026-08-08",
                estimated_credit_amount=5_000_000,
                notes="已确认扩建计划",
            )
            update_marketing_record(
                db_path,
                newer.id,
                customer_manager="李经理",
                status="已电话",
                follow_date="2026-08-09",
                estimated_credit_amount=8_000_000,
                notes="待预约拜访",
            )

            all_records = list_marketing_records(db_path)
            phone_records = list_marketing_records(db_path, status="已电话")
            manager_records = list_marketing_records(
                db_path,
                customer_manager="张经理",
            )

            self.assertEqual([record.enterprise_name for record in all_records], ["乙公司", "甲公司"])
            self.assertEqual(len(phone_records), 2)
            self.assertEqual([record.enterprise_name for record in manager_records], ["甲公司"])
            self.assertEqual(phone_records[0].latest_follow_time, "2026-08-09")
            self.assertEqual(phone_records[0].estimated_credit_amount, 8_000_000)

    def test_invalid_status_amount_and_missing_record_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            with self.assertRaises(MarketingTrackingValidationError):
                add_marketing_record(
                    db_path,
                    enterprise_name="甲公司",
                    project_name="甲项目",
                    region="海门区",
                    status="无效状态",
                )
            with self.assertRaises(MarketingTrackingValidationError):
                add_marketing_record(
                    db_path,
                    enterprise_name="甲公司",
                    project_name="甲项目",
                    region="海门区",
                    estimated_credit_amount=-1,
                )
            with self.assertRaises(LookupError):
                update_marketing_record(
                    db_path,
                    999,
                    customer_manager="张经理",
                    status="已拜访",
                    follow_date="2026-08-10",
                    estimated_credit_amount=0,
                    notes="",
                )


if __name__ == "__main__":
    unittest.main()
