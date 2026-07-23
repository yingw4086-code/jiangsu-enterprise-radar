from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

from crawler.analyze_recent_permits import (
    ALLOWED_PRODUCTS,
    analyze_recent_permits,
    normalize_analysis,
)
from database.storage import upsert_planning_construction_permits
from tests.test_planning_permit_storage import permit_record


class FakeClient:
    def __init__(self):
        self.call_count = 0

    def complete_json(self, system_prompt: str, user_prompt: str):
        self.call_count += 1
        return {
            "ai_opportunity_level": "A",
            "financing_need": "可能存在融资需求",
            "recommended_products": ["固定资产贷款", "不在清单中的产品"],
            "marketing_summary": "项目已取得规划许可，可优先核实建设进度和资金安排。",
            "visit_suggestion": "建议联系财务负责人和项目负责人。",
            "reasoning_summary": "规划许可表明项目进入建设审批阶段。",
            "confidence": 86,
            "risk_notice": "公开信息未披露投资金额，需进一步核实。",
        }


class FailingClient:
    def complete_json(self, system_prompt: str, user_prompt: str):
        raise RuntimeError("test failure")


class RecentPermitAnalysisTest(unittest.TestCase):
    def test_second_run_uses_cache_without_calling_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_planning_construction_permits(db_path, [permit_record()])
            client = FakeClient()

            first = analyze_recent_permits(
                db_path,
                client=client,
                model_name="deepseek-chat",
                today=datetime(2026, 7, 23),
                request_interval_seconds=0,
            )
            second = analyze_recent_permits(
                db_path,
                client=client,
                model_name="deepseek-chat",
                today=datetime(2026, 7, 23),
                request_interval_seconds=0,
            )

            self.assertEqual(first.analyzed_count, 1)
            self.assertEqual(second.analyzed_count, 0)
            self.assertEqual(second.cached_count, 1)
            self.assertEqual(second.A_count, 1)
            self.assertEqual(client.call_count, 1)

    def test_changed_major_field_triggers_reanalysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_planning_construction_permits(db_path, [permit_record()])
            client = FakeClient()
            analyze_recent_permits(
                db_path,
                client=client,
                model_name="deepseek-chat",
                today=datetime(2026, 7, 23),
                request_interval_seconds=0,
            )

            upsert_planning_construction_permits(
                db_path,
                [permit_record(project_name="示例产业园二期")],
            )
            result = analyze_recent_permits(
                db_path,
                client=client,
                model_name="deepseek-chat",
                today=datetime(2026, 7, 23),
                request_interval_seconds=0,
            )

            self.assertEqual(result.analyzed_count, 1)
            self.assertEqual(result.cached_count, 0)
            self.assertEqual(client.call_count, 2)

    def test_api_failure_does_not_change_original_permit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            upsert_planning_construction_permits(db_path, [permit_record()])
            with closing(sqlite3.connect(db_path)) as conn:
                before = conn.execute(
                    "SELECT company_name, project_name, permit_number FROM construction_permits"
                ).fetchone()

            result = analyze_recent_permits(
                db_path,
                client=FailingClient(),
                model_name="deepseek-chat",
                today=datetime(2026, 7, 23),
                request_interval_seconds=0,
            )

            with closing(sqlite3.connect(db_path)) as conn:
                after = conn.execute(
                    "SELECT company_name, project_name, permit_number FROM construction_permits"
                ).fetchone()
                analysis_count = conn.execute("SELECT COUNT(*) FROM permit_ai_analyses").fetchone()[0]
            self.assertEqual(result.failed_count, 1)
            self.assertEqual(before, after)
            self.assertEqual(analysis_count, 0)

    def test_limit_is_capped_at_twenty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "enterprise.db"
            records = [
                permit_record(
                    permit_number=f"建字第3206842026GG{i:07d}号",
                    project_name=f"项目{i}",
                    source_url=f"https://example.gov.cn/permit/{i}",
                )
                for i in range(25)
            ]
            upsert_planning_construction_permits(db_path, records)
            client = FakeClient()

            result = analyze_recent_permits(
                db_path,
                limit=100,
                client=client,
                model_name="deepseek-chat",
                today=datetime(2026, 7, 23),
                request_interval_seconds=0,
            )

            self.assertEqual(result.candidate_count, 20)
            self.assertEqual(result.analyzed_count, 20)
            self.assertEqual(client.call_count, 20)

    def test_normalization_enforces_public_constraints(self):
        result = normalize_analysis(
            {
                "ai_opportunity_level": "D",
                "financing_need": "必然存在贷款需求",
                "recommended_products": list(ALLOWED_PRODUCTS) + ["违规产品"],
                "marketing_summary": "授信审批结论" + ("长" * 120),
                "visit_suggestion": "联系项目负责人",
                "reasoning_summary": "企业正式信用评级",
                "confidence": 0.87,
                "risk_notice": "准确贷款额度待确认",
            }
        )

        self.assertEqual(result["ai_opportunity_level"], "C")
        self.assertEqual(result["recommended_products"], list(ALLOWED_PRODUCTS))
        self.assertEqual(result["confidence"], 87)
        self.assertLessEqual(len(result["marketing_summary"]), 100)
        serialized = str(result)
        for prohibited in ("授信审批结论", "企业正式信用评级", "必然存在贷款需求", "准确贷款额度"):
            self.assertNotIn(prohibited, serialized)


if __name__ == "__main__":
    unittest.main()
