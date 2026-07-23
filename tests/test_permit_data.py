from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.permit_data import (
    effective_permit_date,
    filter_planning_permits,
    load_planning_permit_dataset,
    select_homepage_opportunities,
    summarize_homepage_permits,
    summarize_planning_permits,
)
from database.storage import save_permit_ai_analysis
from database.storage import upsert_planning_construction_permits
from tests.test_planning_permit_storage import permit_record


class PermitDataTest(unittest.TestCase):
    def test_sqlite_has_priority_over_cloud_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            json_path = root / "permits.json"
            upsert_planning_construction_permits(db_path, [permit_record(project_name="SQLite项目")])
            json_path.write_text(
                json.dumps([self._cloud_item("JSON项目")], ensure_ascii=False),
                encoding="utf-8",
            )

            dataset = load_planning_permit_dataset(db_path, json_path)

            self.assertEqual(dataset.storage_source, "本地SQLite")
            self.assertEqual(dataset.source_path, "enterprise.db")
            self.assertEqual(dataset.items[0]["project_name"], "SQLite项目")

    def test_empty_sqlite_falls_back_to_cloud_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            json_path = root / "permits.json"
            upsert_planning_construction_permits(db_path, [])
            json_path.write_text(
                json.dumps([self._cloud_item("云端项目")], ensure_ascii=False),
                encoding="utf-8",
            )

            dataset = load_planning_permit_dataset(db_path, json_path)

            self.assertEqual(dataset.storage_source, "Streamlit Cloud JSON")
            self.assertEqual(dataset.source_path, "permits.json")
            self.assertEqual(dataset.items[0]["project_name"], "云端项目")

    def test_recent_counts_prefer_permit_date(self):
        items = [
            self._cloud_item("近期", permit_date="2026-07-20", publish_date="2026-01-01"),
            self._cloud_item("历史", permit_date="2026-01-01", publish_date="2026-07-20"),
        ]
        summary = summarize_planning_permits(items, today=date(2026, 7, 22))
        self.assertEqual(summary["recent_30_days_count"], 1)
        self.assertEqual(summary["recent_90_days_count"], 1)

    def test_sqlite_loads_ai_fields_and_filters_by_level(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "enterprise.db"
            upsert_planning_construction_permits(db_path, [permit_record()])
            save_permit_ai_analysis(
                db_path,
                permit_id=1,
                input_hash="test-hash",
                analysis={
                    "ai_opportunity_level": "A",
                    "financing_need": "可能存在融资需求",
                    "recommended_products": ["固定资产贷款"],
                    "marketing_summary": "优先核实建设计划。",
                    "visit_suggestion": "联系财务负责人。",
                    "reasoning_summary": "项目处于规划许可阶段。",
                    "confidence": 85,
                    "risk_notice": "投资金额未披露。",
                },
                api_model="deepseek-chat",
            )

            dataset = load_planning_permit_dataset(db_path, root / "missing.json")
            filtered = filter_planning_permits(
                dataset.items,
                ai_level="A",
                recent_days=30,
                today=date(2026, 7, 23),
            )

            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["recommended_products"], ["固定资产贷款"])
            self.assertEqual(filtered[0]["confidence"], 85)
            self.assertEqual(filter_planning_permits(dataset.items, ai_level="B"), [])

    def test_homepage_uses_real_v1_cloud_dataset(self):
        project_root = Path(__file__).resolve().parents[1]
        cloud_path = project_root / "data" / "cloud" / "planning_construction_permits.json"
        dataset = load_planning_permit_dataset(
            project_root / "database" / "missing-for-cloud-test.db",
            cloud_path,
        )

        summary = summarize_homepage_permits(dataset.items, today=date(2026, 7, 23))
        top_items = select_homepage_opportunities(
            dataset.items,
            recent_days=90,
            limit=10,
            today=date(2026, 7, 23),
            ownership_view="全部",
        )
        project_names = {str(item.get("project_name") or "") for item in top_items}

        self.assertEqual(dataset.storage_source, "Streamlit Cloud JSON")
        self.assertEqual(dataset.source_path, "data/cloud/planning_construction_permits.json")
        self.assertEqual(summary["total_count"], 205)
        self.assertEqual(summary["recent_30_days_count"], 10)
        self.assertEqual(summary["recent_90_days_count"], 25)
        self.assertEqual(summary["latest_date"], "2026-07-20")
        self.assertEqual(len(top_items), 10)
        self.assertIn("冬泽特医食品生产基地新建项目", project_names)
        self.assertIn("立新小区九期", project_names)
        self.assertTrue(any("平谦现代产业园" in name for name in project_names))
        self.assertTrue(
            all((effective_permit_date(item) or date.min).year == 2026 for item in top_items)
        )
        self.assertTrue(
            all(item.get("source_name") != "海门区政府网站" for item in top_items)
        )

    def test_homepage_sort_uses_date_then_freshness_then_ai_level(self):
        items = [
            self._cloud_item("较旧A级", permit_date="2026-07-19") | {
                "fresh_score": 100,
                "ai_opportunity_level": "A",
            },
            self._cloud_item("较新B级", permit_date="2026-07-20") | {
                "fresh_score": 80,
                "ai_opportunity_level": "B",
            },
            self._cloud_item("较新A级", permit_date="2026-07-20") | {
                "fresh_score": 80,
                "ai_opportunity_level": "A",
            },
        ]

        selected = select_homepage_opportunities(
            items,
            limit=3,
            today=date(2026, 7, 23),
        )

        self.assertEqual(
            [item["project_name"] for item in selected],
            ["较新A级", "较新B级", "较旧A级"],
        )

    @staticmethod
    def _cloud_item(project_name: str, permit_date: str = "2026-07-20", publish_date: str = "2026-07-21"):
        return {
            "company_name": "示例公司",
            "project_name": project_name,
            "permit_type": "建设工程规划许可证",
            "permit_number": "未披露",
            "permit_date": permit_date,
            "publish_date": publish_date,
            "project_address": "海门区",
            "issuing_authority": "未披露",
            "district": "海门区",
            "district_code": "320684",
            "source_url": "https://example.gov.cn/item",
            "source_name": "江苏自然资源政务信息检索服务（海门）",
            "fresh_score": 100,
            "first_seen_at": "2026-07-22 10:00:00",
            "last_seen_at": "2026-07-22 10:00:00",
            "owner_name": "示例公司",
            "owner_category": "private_enterprise",
            "ownership_type": "private_enterprise",
            "ownership_confidence": 100,
            "ownership_basis": "测试人工确认",
            "marketing_eligible": True,
            "marketing_priority": "A",
            "exclusion_reason": "",
            "manual_review_required": False,
            "classification_updated_at": "2026-07-22 10:00:00",
        }


if __name__ == "__main__":
    unittest.main()
