from __future__ import annotations

import unittest

from app.credit_analysis import (
    analyze_credit_opportunity,
    build_financing_report,
    enrich_credit_opportunity,
)


def finance_item(**overrides):
    item = {
        "company_name": "海门制造有限公司",
        "project_name": "智能制造项目",
        "project_type": "enterprise",
        "permit_type": "建设工程规划许可证",
        "industry": "装备制造",
        "finance_score": 75,
        "finance_level": "A",
        "loan_type": "固定资产贷款、项目贷款",
        "suggested_contact_time": "建议3个工作日内联系",
        "province": "江苏省",
        "city": "南通市",
        "district": "海门区",
    }
    item.update(overrides)
    return item


class CreditAnalysisTest(unittest.TestCase):
    def test_factory_equipment_and_expansion_rules_can_stack(self):
        analysis = analyze_credit_opportunity(
            finance_item(project_name="厂房扩建及生产线设备采购项目")
        )

        self.assertIn("固定资产贷款", analysis.estimated_financing_need)
        self.assertIn("设备贷款", analysis.estimated_financing_need)
        self.assertIn("流动资金贷款", analysis.estimated_financing_need)
        self.assertEqual(
            analysis.recommended_products,
            ("固定资产贷款", "设备贷款", "流动资金贷款", "项目贷款"),
        )

    def test_permit_stage_provides_conservative_fallback_need(self):
        analysis = analyze_credit_opportunity(
            finance_item(
                project_name="普通项目",
                industry="未披露",
                permit_type="建设用地规划许可证",
                loan_type="土地贷款",
            )
        )

        self.assertIn("拿地阶段", analysis.estimated_financing_need)
        self.assertEqual(analysis.recommended_products, ("土地贷款", "项目贷款"))

    def test_government_project_is_not_an_enterprise_credit_lead(self):
        analysis = analyze_credit_opportunity(
            finance_item(project_type="government", company_name="某政府")
        )

        self.assertFalse(analysis.eligible_for_analysis)
        self.assertEqual(analysis.recommended_products, ())
        self.assertIn("不进入", analysis.estimated_financing_need)

    def test_report_contains_all_seven_requested_sections(self):
        report = build_financing_report(finance_item())

        self.assertEqual(report.title, "《企业融资机会分析报告》")
        self.assertEqual(len(report.sections), 7)
        self.assertEqual(
            [section.title for section in report.sections],
            [
                "1. 企业基本情况",
                "2. 项目投资情况",
                "3. 当前建设阶段",
                "4. 可能融资需求",
                "5. 推荐银行产品",
                "6. 建议营销时间",
                "7. 客户经理拜访建议",
            ],
        )
        self.assertIn("不作为授信审批结论", report.sections[-1].content)
        self.assertIn("预计投资规模", report.sections[1].content)
        self.assertIn("预计授信金额", report.sections[3].content)

    def test_enrichment_is_runtime_only_and_does_not_mutate_input(self):
        original = finance_item(project_name="设备采购项目")

        enriched = enrich_credit_opportunity(original)

        self.assertNotIn("estimated_financing_need", original)
        self.assertIn("设备贷款", enriched["estimated_financing_need"])
        self.assertIn("设备贷款", enriched["recommended_bank_products"])


if __name__ == "__main__":
    unittest.main()
