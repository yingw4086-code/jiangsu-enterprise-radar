from __future__ import annotations

import unittest
from datetime import date

from app.finance_scoring import (
    enrich_finance_opportunities,
    rank_finance_opportunities,
    score_finance_opportunity,
)


TODAY = date(2026, 8, 10)


def permit_item(**overrides):
    item = {
        "company_name": "海门制造有限公司",
        "project_name": "产业园建设项目",
        "industry": "制造业",
        "project_type": "enterprise",
        "permit_type": "建设工程规划许可证",
        "publish_date": "2026-08-01",
        "enterprise_strength_level": "D",
    }
    item.update(overrides)
    return item


def complete_registry_fields():
    return {
        "registry_data_available": True,
        "registry_disclosed_fields": [
            "unified_social_credit_code",
            "legal_person",
            "registered_capital",
            "establish_date",
            "company_address",
            "business_scope",
            "company_status",
            "industry",
        ],
        "unified_social_credit_code": "91320684MA12345678",
        "legal_person": "张三",
        "registered_capital": "1亿元",
        "establish_date": "2010-01-01",
        "company_address": "江苏省南通市海门区示例路1号",
        "business_scope": "智能装备制造与销售",
        "company_status": "存续",
        "industry": "制造业",
    }


class FinanceScoringTest(unittest.TestCase):
    def test_weighted_components_are_capped_at_requested_percentages(self):
        assessment = score_finance_opportunity(
            permit_item(
                project_name="工业制造生产基地设备升级厂房扩建项目",
                enterprise_strength_level="A",
                **complete_registry_fields(),
            ),
            today=TODAY,
        )

        self.assertEqual(assessment.project_value_score, 40)
        self.assertEqual(assessment.enterprise_strength_score, 20)
        self.assertEqual(assessment.registry_completeness_score, 10)
        self.assertEqual(assessment.financing_need_score, 20)
        self.assertEqual(assessment.time_window_score, 10)
        self.assertEqual(assessment.finance_score, 100)
        self.assertEqual(assessment.finance_level, "A")
        self.assertTrue(assessment.eligible_for_recommendation)

    def test_enterprise_strength_uses_twenty_percent_weight(self):
        expected = {"A": 20, "B": 15, "C": 10, "D": 0}
        for level, expected_score in expected.items():
            with self.subTest(level=level):
                assessment = score_finance_opportunity(
                    permit_item(enterprise_strength_level=level),
                    today=TODAY,
                )
                self.assertEqual(
                    assessment.enterprise_strength_score,
                    expected_score,
                )

    def test_government_project_is_excluded_from_recommendation(self):
        assessment = score_finance_opportunity(
            permit_item(
                project_type="government",
                project_name="年产设备生产基地厂房项目",
                enterprise_strength_level="A",
            ),
            today=TODAY,
        )

        self.assertEqual(assessment.finance_score, 0)
        self.assertEqual(assessment.finance_level, "C")
        self.assertEqual(assessment.loan_type, "")
        self.assertFalse(assessment.eligible_for_recommendation)
        self.assertEqual(
            (
                assessment.project_value_score,
                assessment.enterprise_strength_score,
                assessment.registry_completeness_score,
                assessment.financing_need_score,
                assessment.time_window_score,
            ),
            (0, 0, 0, 0, 0),
        )

    def test_registry_completeness_uses_ten_percent_weight(self):
        cases = (
            ({}, 0),
            (
                {
                    "registry_data_available": True,
                    "registry_disclosed_fields": [
                        "legal_person",
                        "registered_capital",
                    ],
                    "legal_person": "张三",
                    "registered_capital": "1亿元",
                },
                3,
            ),
            (complete_registry_fields(), 10),
        )
        for registry_fields, expected_score in cases:
            with self.subTest(expected_score=expected_score):
                assessment = score_finance_opportunity(
                    permit_item(**registry_fields),
                    today=TODAY,
                )
                self.assertEqual(
                    assessment.registry_completeness_score,
                    expected_score,
                )

    def test_publish_date_uses_ten_percent_time_window(self):
        base = permit_item(project_type="unknown", project_name="普通项目")
        cases = (
            ("2026-07-11", 10),
            ("2026-07-10", 5),
            ("2026-05-12", 5),
            ("2026-05-11", 0),
        )
        for publish_date, expected_score in cases:
            with self.subTest(publish_date=publish_date):
                assessment = score_finance_opportunity(
                    base | {"publish_date": publish_date},
                    today=TODAY,
                )
                self.assertEqual(assessment.time_window_score, expected_score)

    def test_finance_levels_keep_seventy_and_fifty_point_thresholds(self):
        level_a = score_finance_opportunity(
            permit_item(
                project_name="工业制造生产基地设备厂房项目",
                enterprise_strength_level="A",
                **complete_registry_fields(),
            ),
            today=TODAY,
        )
        level_b = score_finance_opportunity(
            permit_item(
                project_name="工业制造项目",
                enterprise_strength_level="D",
            ),
            today=TODAY,
        )
        level_c = score_finance_opportunity(
            permit_item(
                project_name="普通项目",
                industry="未披露",
                publish_date="2026-01-01",
                enterprise_strength_level="D",
            ),
            today=TODAY,
        )

        self.assertEqual((level_a.finance_score, level_a.finance_level), (100, "A"))
        self.assertEqual((level_b.finance_score, level_b.finance_level), (50, "B"))
        self.assertEqual((level_c.finance_score, level_c.finance_level), (25, "C"))

    def test_permit_stage_maps_to_requested_loan_products(self):
        cases = (
            ("建设用地规划许可证", "土地贷款", "土地融资机会"),
            (
                "建设工程规划许可证",
                "固定资产贷款、项目贷款",
                "固定资产贷款机会",
            ),
            (
                "建设工程施工许可证",
                "设备贷款、流动资金贷款",
                "设备贷款/流动资金机会",
            ),
        )
        for permit_type, loan_type, opportunity in cases:
            with self.subTest(permit_type=permit_type):
                assessment = score_finance_opportunity(
                    permit_item(permit_type=permit_type),
                    today=TODAY,
                )
                self.assertEqual(assessment.loan_type, loan_type)
                self.assertEqual(assessment.finance_opportunity, opportunity)

    def test_enrichment_returns_copies_and_component_fields(self):
        original = permit_item()

        enriched = enrich_finance_opportunities([original], today=TODAY)

        self.assertNotIn("finance_score", original)
        self.assertIn("finance_score", enriched[0])
        self.assertEqual(enriched[0]["finance_level"], "B")
        self.assertEqual(enriched[0]["project_value_score"], 30)
        self.assertEqual(enriched[0]["enterprise_strength_score"], 0)
        self.assertEqual(enriched[0]["registry_completeness_score"], 0)
        self.assertEqual(enriched[0]["financing_need_score"], 10)
        self.assertEqual(enriched[0]["time_window_score"], 10)

    def test_ranking_filters_level_excludes_government_and_sorts(self):
        items = [
            permit_item(
                company_name="甲公司",
                project_name="工业制造生产基地项目",
                publish_date="2026-08-01",
                enterprise_strength_level="A",
            ),
            permit_item(
                company_name="乙公司",
                project_name="工业制造生产基地项目",
                publish_date="2026-08-02",
                enterprise_strength_level="A",
            ),
            permit_item(
                company_name="丙公司",
                project_name="工业制造生产基地设备厂房扩建项目",
                enterprise_strength_level="A",
            ),
            permit_item(
                company_name="某政府",
                project_type="government",
                project_name="工业制造生产基地设备厂房项目",
                enterprise_strength_level="A",
            ),
        ]

        ranked = rank_finance_opportunities(items, finance_level="A", today=TODAY)

        self.assertEqual(
            [item["company_name"] for item in ranked],
            ["丙公司", "乙公司", "甲公司"],
        )
        self.assertTrue(all(item["project_type"] != "government" for item in ranked))


if __name__ == "__main__":
    unittest.main()
