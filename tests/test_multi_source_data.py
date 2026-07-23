import unittest
from datetime import date

from data_source.base import (
    OpportunityRecord,
    calculate_fresh_score,
    parse_amount_to_yuan,
    split_products,
)
from data_source.multi_source_runner import build_dashboard_payload


class MultiSourceDataTest(unittest.TestCase):
    def test_amount_and_fresh_score(self):
        self.assertEqual(parse_amount_to_yuan("8亿元"), 800_000_000)
        self.assertEqual(parse_amount_to_yuan("5000万元"), 50_000_000)
        self.assertEqual(calculate_fresh_score("2026-07-20", today=date(2026, 7, 21)), 100)
        self.assertEqual(calculate_fresh_score("2026-06-25", today=date(2026, 7, 21)), 80)
        self.assertEqual(calculate_fresh_score("2026-04-30", today=date(2026, 7, 21)), 60)
        self.assertEqual(calculate_fresh_score("2025-12-01", today=date(2026, 7, 21)), 20)

    def test_opportunity_record_enriches_customer_manager_fields(self):
        record = OpportunityRecord(
            enterprise_name="江苏示例新能源有限公司",
            project_name="新能源电池基地项目",
            source="测试数据源",
            event_time="2026-07-20",
            amount="8亿元",
            industry="新能源",
            approval_type="施工许可证",
            stage="施工许可/开工阶段",
            source_url="https://example.com/a",
            source_title="新能源电池基地项目施工许可证",
        ).enrich()

        self.assertEqual(record.opportunity_level, "A")
        self.assertIn("固定资产贷款", split_products(record.recommended_loan_product))
        self.assertEqual(record.manager_view["是否值得拜访"], "是")
        self.assertIn("拜访话术", record.manager_view)

    def test_dashboard_payload_keeps_existing_json_shape(self):
        record = OpportunityRecord(
            enterprise_name="江苏示例设备有限公司",
            project_name="高端设备制造项目",
            source="发改投资项目备案信息",
            event_time="2026-07-20",
            amount="1.2亿元",
            industry="设备制造",
            approval_type="项目备案",
            stage="投资备案阶段",
            source_url="https://example.com/b",
            source_title="高端设备制造项目备案",
        ).enrich()

        payload = build_dashboard_payload([record])
        item = payload["items"][0]

        self.assertEqual(payload["model"], "multi_source_rule_scoring")
        self.assertEqual(item["enterprise_name"], "江苏示例设备有限公司")
        self.assertEqual(item["ai_analysis"]["customer_value_level"], record.opportunity_level)
        self.assertTrue(item["ai_analysis"]["expected_loan_types"])


if __name__ == "__main__":
    unittest.main()
