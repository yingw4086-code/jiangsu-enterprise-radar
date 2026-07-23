from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from database.storage import (
    PLANNING_CONSTRUCTION_PERMIT_TYPE,
    load_public_planning_construction_permits,
    upsert_planning_construction_permits,
)


def permit_record(**overrides):
    values = {
        "company_name": "海门示例建设有限公司",
        "construction_unit": "海门示例建设有限公司",
        "project_name": "示例产业园一期",
        "permit_type": PLANNING_CONSTRUCTION_PERMIT_TYPE,
        "permit_number": "建字第3206142026GG0001001号",
        "permit_date": "2026-07-20",
        "publish_date": "2026-07-21",
        "project_address": "海门区三星镇",
        "issuing_authority": "南通市海门自然资源和规划局",
        "source_url": "https://example.gov.cn/permit/1",
        "source_name": "江苏自然资源政务信息检索服务（海门）",
        "fresh_score": 100,
        "raw": {"areaCode": "320684"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PlanningPermitStorageTest(unittest.TestCase):
    def test_insert_skip_update_and_public_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            record = permit_record()

            first = upsert_planning_construction_permits(db_path, [record])
            second = upsert_planning_construction_permits(db_path, [record])
            changed = upsert_planning_construction_permits(
                db_path,
                [permit_record(project_address="海门区三星镇产业园")],
            )
            rows = load_public_planning_construction_permits(db_path)

            self.assertEqual(first.inserted_count, 1)
            self.assertEqual(second.inserted_count, 0)
            self.assertEqual(second.skipped_count, 1)
            self.assertEqual(changed.updated_count, 1)
            self.assertEqual(changed.total_count, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["district"], "海门区")
            self.assertEqual(rows[0]["district_code"], "320684")
            self.assertEqual(rows[0]["project_address"], "海门区三星镇产业园")

    def test_source_url_is_second_priority_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            first = permit_record(permit_number="未披露")
            second = permit_record(permit_number="未披露", company_name="更新后的建设单位")

            upsert_planning_construction_permits(db_path, [first])
            summary = upsert_planning_construction_permits(db_path, [second])

            self.assertEqual(summary.inserted_count, 0)
            self.assertEqual(summary.updated_count, 1)
            self.assertEqual(summary.total_count, 1)


if __name__ == "__main__":
    unittest.main()
