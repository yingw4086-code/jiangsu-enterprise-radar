from __future__ import annotations

import unittest

from app.industry_classification import assess_industry, enrich_industry_assessment


class IndustryClassificationTest(unittest.TestCase):
    def test_registry_industry_has_priority_and_high_confidence(self):
        assessment = assess_industry(
            {
                "industry": "专用设备制造业",
                "registry_disclosed_fields": ["industry"],
                "project_name": "新能源项目",
            }
        )

        self.assertEqual(assessment.industry_classification, "专用设备制造业")
        self.assertEqual(assessment.industry_classification_confidence, "high")
        self.assertIn("明确披露", assessment.industry_classification_basis)

    def test_keywords_produce_explainable_industry_judgment(self):
        enriched = enrich_industry_assessment(
            {
                "company_name": "测试新能源有限公司",
                "project_name": "储能设备生产基地",
            }
        )

        self.assertEqual(enriched["industry_classification"], "新能源产业")
        self.assertEqual(enriched["industry_classification_confidence"], "medium")
        self.assertIn("储能", enriched["industry_classification_basis"])

    def test_missing_information_remains_pending(self):
        assessment = assess_industry({"company_name": "测试企业"})

        self.assertEqual(assessment.industry_classification, "待判断")
        self.assertEqual(assessment.industry_classification_confidence, "low")


if __name__ == "__main__":
    unittest.main()
