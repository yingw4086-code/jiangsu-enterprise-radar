from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.official_permit_data import (
    load_official_permit_dataset,
    summarize_official_permits,
)
from data_source.construction_start_permit import (
    COLUMN_ID as START_COLUMN_ID,
    SOURCE_URL as START_SOURCE_URL,
    has_haimen_title_hint,
)
from data_source.official_permit_record import OfficialPermitRecord
from data_source.planning_land_permit import (
    COLUMN_ID as LAND_COLUMN_ID,
    SOURCE_URL as LAND_SOURCE_URL,
)
from database.official_permits import (
    export_public_official_permits,
    load_public_official_permits,
    upsert_official_permits,
)
from database.storage import (
    PLANNING_CONSTRUCTION_PERMIT_TYPE,
    count_construction_permits,
    upsert_planning_construction_permits,
)
from tests.test_planning_permit_storage import permit_record


LAND_PERMIT_TYPE = "建设用地规划许可证"
START_PERMIT_TYPE = "建设工程施工许可证"


def official_record(permit_type: str = LAND_PERMIT_TYPE, **overrides) -> OfficialPermitRecord:
    values = {
        "company_name": "海门测试建设有限公司",
        "construction_unit": "海门测试建设有限公司",
        "project_name": "测试产业项目",
        "permit_type": permit_type,
        "permit_number": "地字第3206142026YG0001001号",
        "permit_date": "2026-07-20",
        "publish_date": "2026-07-21",
        "project_address": "海门区三星镇",
        "issuing_authority": "南通市数据局",
        "district": "海门区",
        "district_code": "320684",
        "source_url": "https://example.gov.cn/permit/land-1",
        "source_name": "海门区自然资源局行政许可",
        "project_stage": "拿地规划",
        "raw": {"verified": True},
    }
    values.update(overrides)
    return OfficialPermitRecord(**values)


class OfficialPermitModuleTest(unittest.TestCase):
    def test_sources_are_independent_and_construction_uses_haimen_hint(self):
        self.assertIn("/hmsgtj/xzxk/", LAND_SOURCE_URL)
        self.assertIn("/ntsxzspj/pzjg/", START_SOURCE_URL)
        self.assertNotEqual(LAND_COLUMN_ID, START_COLUMN_ID)
        self.assertTrue(has_haimen_title_hint("南通大众燃气海门分输站接气工程施工许可"))
        self.assertFalse(has_haimen_title_hint("东南大学南通校区一期工程施工许可"))

    def test_upsert_is_type_scoped_and_preserves_planning_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_planning_construction_permits(db_path, [permit_record()])

            first = upsert_official_permits(
                db_path,
                [official_record()],
                permit_type=LAND_PERMIT_TYPE,
            )
            second = upsert_official_permits(
                db_path,
                [official_record()],
                permit_type=LAND_PERMIT_TYPE,
            )
            changed = upsert_official_permits(
                db_path,
                [official_record(project_address="海门区三星镇产业园")],
                permit_type=LAND_PERMIT_TYPE,
            )

            self.assertEqual(first.inserted_count, 1)
            self.assertEqual(second.skipped_count, 1)
            self.assertEqual(changed.updated_count, 1)
            self.assertEqual(count_construction_permits(db_path, LAND_PERMIT_TYPE), 1)
            self.assertEqual(
                count_construction_permits(db_path, PLANNING_CONSTRUCTION_PERMIT_TYPE),
                1,
            )

    def test_public_export_and_dashboard_loader(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            output_path = root / "land.json"
            upsert_official_permits(
                db_path,
                [official_record()],
                permit_type=LAND_PERMIT_TYPE,
            )

            export_result = export_public_official_permits(
                db_path,
                output_path,
                permit_type=LAND_PERMIT_TYPE,
            )
            dataset = load_official_permit_dataset(
                db_path,
                output_path,
                permit_type=LAND_PERMIT_TYPE,
            )
            exported = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertTrue(export_result["written"])
            self.assertEqual(export_result["export_count"], 1)
            self.assertEqual(dataset.storage_source, "本地SQLite")
            self.assertEqual(dataset.items[0]["project_name"], "测试产业项目")
            self.assertEqual(exported[0]["district_code"], "320684")
            self.assertNotIn("raw", exported[0])

    def test_summary_prefers_permit_date(self):
        items = [
            {
                "permit_date": "2026-07-20",
                "publish_date": "2025-01-01",
            },
            {
                "permit_date": "2025-01-01",
                "publish_date": "2026-07-20",
            },
        ]
        summary = summarize_official_permits(items, today=date(2026, 7, 23))
        self.assertEqual(summary["recent_30_days_count"], 1)
        self.assertEqual(summary["recent_90_days_count"], 1)

    def test_wrong_permit_type_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            summary = upsert_official_permits(
                db_path,
                [official_record(permit_type=START_PERMIT_TYPE)],
                permit_type=LAND_PERMIT_TYPE,
            )
            rows = load_public_official_permits(db_path, permit_type=LAND_PERMIT_TYPE)

            self.assertEqual(summary.inserted_count, 0)
            self.assertEqual(summary.skipped_count, 1)
            self.assertEqual(rows, [])

    def test_dashboard_loader_filters_official_permits_by_region_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            upsert_official_permits(
                db_path,
                [
                    official_record(project_name="海门项目"),
                    official_record(
                        project_name="昆山项目",
                        permit_number="地字第3205832026YG0002001号",
                        source_url="https://example.gov.cn/permit/kunshan",
                    ),
                ],
                permit_type=LAND_PERMIT_TYPE,
            )
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    UPDATE construction_permits
                    SET region_key='320583', area_code='320583'
                    WHERE project_name='昆山项目'
                    """
                )
                connection.commit()
            finally:
                connection.close()

            haimen = load_official_permit_dataset(
                db_path,
                root / "missing.json",
                permit_type=LAND_PERMIT_TYPE,
                region_key="320684",
            )
            kunshan = load_official_permit_dataset(
                db_path,
                root / "missing.json",
                permit_type=LAND_PERMIT_TYPE,
                region_key="320583",
            )

        self.assertEqual([item["project_name"] for item in haimen.items], ["海门项目"])
        self.assertEqual([item["project_name"] for item in kunshan.items], ["昆山项目"])


if __name__ == "__main__":
    unittest.main()
