from __future__ import annotations

import unittest

from app.finance_estimation import (
    ESTIMATION_NOT_APPLICABLE,
    enrich_finance_estimation,
    estimate_finance_need,
    estimation_confidence_label,
)


def estimation_item(**overrides):
    item = {
        "company_name": "海门制造有限公司",
        "project_name": "普通制造项目",
        "project_type": "enterprise",
        "permit_type": "建设工程规划许可证",
        "industry": "未披露",
        "investment": "未披露",
        "project_scale": "未披露",
    }
    item.update(overrides)
    return item


class FinanceEstimationTest(unittest.TestCase):
    def test_factory_uses_disclosed_investment_and_sixty_to_seventy_percent(self):
        estimation = estimate_finance_need(
            estimation_item(
                project_name="智能厂房建设项目",
                investment="10000万元",
            )
        )

        self.assertEqual(estimation.estimated_investment, "1亿元（公开金额）")
        self.assertEqual(
            estimation.estimated_credit_need,
            "6,000万元–7,000万元（规则估算）",
        )
        self.assertEqual(estimation.recommended_product, "固定资产贷款")
        self.assertEqual(estimation.estimation_confidence, "medium")
        self.assertEqual(estimation.credit_need_min_yuan, 60_000_000)
        self.assertEqual(estimation.credit_need_max_yuan, 70_000_000)

    def test_equipment_uses_seventy_percent_rule(self):
        estimation = estimate_finance_need(
            estimation_item(
                project_name="生产线设备采购项目",
                investment="2,000万元",
            )
        )

        self.assertEqual(estimation.estimated_investment, "2,000万元（公开金额）")
        self.assertEqual(
            estimation.estimated_credit_need,
            "1,400万元（规则估算）",
        )
        self.assertEqual(estimation.recommended_product, "设备贷款")

    def test_expansion_without_amount_returns_low_confidence_range(self):
        estimation = estimate_finance_need(
            estimation_item(project_name="生产扩建项目")
        )

        self.assertEqual(
            estimation.estimated_investment,
            "1,000万元–6,000万元（规则估算）",
        )
        self.assertEqual(
            estimation.estimated_credit_need,
            "200万元–2,100万元（规则估算）",
        )
        self.assertEqual(estimation.recommended_product, "流动资金贷款")
        self.assertEqual(estimation.estimation_confidence, "low")
        self.assertIn("公开投资金额缺失", "".join(estimation.estimation_basis))

    def test_industry_and_large_scale_keywords_adjust_inferred_range(self):
        estimation = estimate_finance_need(
            estimation_item(
                project_name="新能源生产基地厂房项目",
                industry="新能源装备制造",
            )
        )

        self.assertEqual(
            estimation.estimated_investment,
            "0.88亿元–3.5亿元（规则估算）",
        )
        self.assertIn("资本密集型", "".join(estimation.estimation_basis))
        self.assertIn("上调25%", "".join(estimation.estimation_basis))

    def test_permit_stage_is_used_when_project_keywords_are_absent(self):
        estimation = estimate_finance_need(
            estimation_item(
                project_name="普通项目",
                permit_type="建设用地规划许可证",
            )
        )

        self.assertEqual(
            estimation.estimated_investment,
            "0.8亿元–3亿元（规则估算）",
        )
        self.assertEqual(estimation.recommended_product, "土地贷款、项目贷款")
        self.assertIn("拿地阶段", "".join(estimation.estimation_basis))

    def test_government_project_is_not_estimated(self):
        estimation = estimate_finance_need(
            estimation_item(project_type="government")
        )

        self.assertFalse(estimation.eligible_for_estimation)
        self.assertEqual(estimation.estimated_investment, ESTIMATION_NOT_APPLICABLE)
        self.assertEqual(estimation.estimated_credit_need, ESTIMATION_NOT_APPLICABLE)
        self.assertEqual(estimation.recommended_product, ESTIMATION_NOT_APPLICABLE)
        self.assertEqual(
            estimation_confidence_label(estimation.estimation_confidence),
            "不适用",
        )

    def test_enrichment_adds_requested_fields_without_mutating_input(self):
        original = estimation_item(
            project_name="设备升级项目",
            project_scale="项目总投资1.2亿元，其中设备投资3000万元",
        )

        enriched = enrich_finance_estimation(original)

        self.assertNotIn("estimated_investment", original)
        self.assertEqual(enriched["estimated_investment"], "1.2亿元（公开金额）")
        self.assertEqual(enriched["estimated_credit_need"], "8,400万元（规则估算）")
        self.assertEqual(enriched["recommended_product"], "设备贷款")
        self.assertEqual(enriched["estimated_credit_need_min_yuan"], 84_000_000)
        self.assertEqual(enriched["estimated_credit_need_max_yuan"], 84_000_000)


if __name__ == "__main__":
    unittest.main()
