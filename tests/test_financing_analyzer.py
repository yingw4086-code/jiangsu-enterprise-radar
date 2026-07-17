import unittest

from app.ai.financing_analyzer import FinancingAnalyzer
from app.ai.provider import parse_json_content
from app.models import ProjectAnnouncement


class FakeClient:
    def complete_json(self, system_prompt, user_prompt):
        return {
            "items": [
                {
                    "index": 1,
                    "enterprise_name": "江苏海门示例装备有限公司",
                    "project_name": "年产高端装备零部件项目",
                    "has_financing_need": True,
                    "expected_loan_types": ["项目贷款", "设备融资"],
                    "customer_value_level": "A",
                    "marketing_advice": "建议优先联系企业负责人，了解建设进度和设备采购计划。",
                    "reason": "项目备案且涉及制造业扩产，可能存在固定资产投入。",
                    "confidence": 0.86,
                }
            ]
        }


class FinancingAnalyzerTest(unittest.TestCase):
    def test_normalizes_llm_json_output(self):
        announcement = ProjectAnnouncement(
            company_name="江苏海门示例装备有限公司",
            project_name="年产高端装备零部件项目",
            approval_item="项目备案",
            date="2026-07-14",
            link="https://example.com/a.html",
            source_name="测试站点",
            title="项目备案公告",
            fetched_at="2026-07-14 08:30:00",
        )

        result = FinancingAnalyzer(FakeClient(), "fake-model").analyze_many([announcement])
        item = result["items"][0]

        self.assertEqual(item["enterprise_name"], "江苏海门示例装备有限公司")
        self.assertTrue(item["ai_analysis"]["has_financing_need"])
        self.assertEqual(item["ai_analysis"]["customer_value_level"], "A")
        self.assertIn("设备融资", item["ai_analysis"]["expected_loan_types"])

    def test_parse_json_content_from_markdown_fence(self):
        parsed = parse_json_content('```json\n{"items": []}\n```')
        self.assertEqual(parsed, {"items": []})


if __name__ == "__main__":
    unittest.main()

