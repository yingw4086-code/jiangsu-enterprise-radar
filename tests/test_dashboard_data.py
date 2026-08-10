import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.dashboard_data import (
    DashboardRecord,
    filter_records,
    format_yuan,
    infer_financing_window,
    infer_project_stage,
    marketing_priority_stars,
    load_records,
    sort_marketing_tasks,
    suggest_visit_time,
    summarize,
)


class DashboardDataTest(unittest.TestCase):
    def test_loads_ai_json_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "financing_analysis_2026-07-14_083000.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-14 08:30:00",
                        "model": "fake-model",
                        "items": [
                            {
                                "enterprise_name": "江苏海门示例装备有限公司",
                                "project_name": "年产高端装备零部件项目",
                                "approval_item": "项目备案",
                                "date": "2026-07-14",
                                "source_url": "https://example.com/a",
                                "source_title": "项目备案公告",
                                "ai_analysis": {
                                    "has_financing_need": True,
                                    "expected_loan_types": ["项目贷款", "设备融资"],
                                    "customer_value_level": "A",
                                    "marketing_advice": "建议优先联系。",
                                    "reason": "制造业扩产。",
                                    "confidence": 0.9,
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            records = load_records(data_dir)
            summary = summarize(records, today=date(2026, 7, 14))
            filtered = filter_records(records, search="示例", level="A")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].customer_level, "A")
            self.assertEqual(records[0].financing_need, "存在")
            self.assertEqual(summary["today_new_projects"], 1)
            self.assertEqual(summary["a_level_count"], 1)
            self.assertEqual(len(filtered), 1)

    def test_load_records_supports_region_key_and_keeps_legacy_haimen_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "financing_analysis_2026-07-14_083000.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-14 08:30:00",
                        "items": [
                            {
                                "enterprise_name": "海门旧数据企业",
                                "project_name": "旧数据项目",
                            },
                            {
                                "enterprise_name": "昆山企业",
                                "project_name": "昆山项目",
                                "region_key": "320583",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            haimen_records = load_records(data_dir, region_key="320684")
            kunshan_records = load_records(data_dir, region_key="320583")

            self.assertEqual(
                [record.enterprise_name for record in haimen_records],
                ["海门旧数据企业"],
            )
            self.assertEqual(
                [record.enterprise_name for record in kunshan_records],
                ["昆山企业"],
            )

    def test_format_yuan(self):
        self.assertEqual(format_yuan(0), "未披露")
        self.assertEqual(format_yuan(50_000_000), "5000 万元")

    def test_marketing_tasks_sort_by_level_then_amount(self):
        records = [
            self._record("C企业", "C", "10亿元"),
            self._record("A小额企业", "A", "1000万元"),
            self._record("A大额企业", "A", "8亿元"),
            self._record("B企业", "B", "20亿元"),
        ]

        sorted_records = sort_marketing_tasks(records)

        self.assertEqual([record.enterprise_name for record in sorted_records], ["A大额企业", "A小额企业", "B企业", "C企业"])
        self.assertEqual(marketing_priority_stars(sorted_records[0]), "★★★★★")
        self.assertEqual(suggest_visit_time(sorted_records[0]), "建议 3 个工作日内拜访")
        self.assertEqual(infer_project_stage(sorted_records[0]), "建设准备期")
        self.assertEqual(infer_financing_window(sorted_records[0]), "中期（6-12个月）")

    def test_financing_window_options(self):
        immediate = self._record("施工企业", "A", "1亿元", approval_item="施工许可证")
        recent = self._record("规划企业", "A", "1亿元", approval_item="建设用地规划许可证")
        medium = self._record("备案企业", "A", "1亿元", approval_item="投资备案")
        unknown = self._record(
            "观察企业",
            "C",
            "未披露",
            approval_item="其他公告",
            project_name="普通信息",
            source_title="普通信息公告",
            reason="普通信息",
        )

        self.assertEqual(infer_financing_window(immediate), "立即（0-3个月）")
        self.assertEqual(infer_financing_window(recent), "近期（3-6个月）")
        self.assertEqual(infer_financing_window(medium), "中期（6-12个月）")
        self.assertEqual(infer_financing_window(unknown), "未知")

    def _record(
        self,
        enterprise_name: str,
        level: str,
        amount: str,
        approval_item: str = "项目备案",
        financing_need: str = "存在",
        project_name: str = "新能源电池基地项目",
        source_title: str = "项目备案公告",
        reason: str = "项目备案且投资规模较大。",
    ) -> DashboardRecord:
        return DashboardRecord(
            enterprise_name=enterprise_name,
            project_name=project_name,
            industry="新能源",
            investment_amount=amount,
            project_address="海门区",
            discovery_time="2026-07-14",
            data_source="海门区政府网站",
            customer_level=level,
            financing_need=financing_need,
            recommended_products="固定资产贷款、设备融资、流动资金贷款",
            approval_item=approval_item,
            source_url="https://example.com",
            source_title=source_title,
            marketing_advice="建议优先联系企业负责人。",
            reason=reason,
            confidence=0.9,
            raw={},
        )


if __name__ == "__main__":
    unittest.main()
