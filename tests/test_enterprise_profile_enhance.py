from __future__ import annotations

import unittest
from datetime import date

from app.enterprise_profile_enhance import (
    ALL_FILTER,
    COMPANY_SCALE_OPTIONS,
    FOREIGN_OWNERSHIP,
    LARGE_COMPANY,
    MEDIUM_COMPANY,
    MICRO_COMPANY,
    PRIVATE_OWNERSHIP,
    SMALL_COMPANY,
    STATE_OWNERSHIP,
    UNKNOWN,
    UNKNOWN_CLASSIFICATION,
    assess_company_strength,
    build_enhanced_enterprise_profile,
    enrich_company_strength,
    enrich_enhanced_enterprise_profile,
    filter_enhanced_profiles,
)


class EnhancedEnterpriseProfileTest(unittest.TestCase):
    def test_builds_requested_business_fields_from_explicit_data(self):
        profile = build_enhanced_enterprise_profile(
            {
                "company_name": "海门智能装备有限公司",
                "legal_representative": "张三",
                "registration_capital": "5000万元",
                "established_date": "2018-05-06",
                "registered_address": "江苏省南通市海门区示例路1号",
                "unified_social_credit_code": "91320684MA1234567X",
                "business_scope": "智能装备制造与销售",
                "company_status": "存续",
                "industry": "专用设备制造业",
                "registration_type": "自然人投资或控股",
                "company_scale": "中型",
            }
        )

        self.assertEqual(profile.company_name, "海门智能装备有限公司")
        self.assertEqual(profile.legal_person, "张三")
        self.assertEqual(profile.registered_capital, "5000万元")
        self.assertEqual(profile.establish_date, "2018-05-06")
        self.assertEqual(profile.company_address, "江苏省南通市海门区示例路1号")
        self.assertEqual(profile.unified_social_credit_code, "91320684MA1234567X")
        self.assertEqual(profile.business_scope, "智能装备制造与销售")
        self.assertEqual(profile.company_status, "存续")
        self.assertEqual(profile.industry, "专用设备制造业")
        self.assertEqual(profile.ownership_type, PRIVATE_OWNERSHIP)
        self.assertEqual(profile.company_scale, MEDIUM_COMPANY)
        self.assertEqual(profile.ownership_confidence, "high")
        self.assertEqual(profile.company_scale_confidence, "high")

    def test_existing_state_owned_category_and_explicit_foreign_type_are_mapped(self):
        state_owned = build_enhanced_enterprise_profile(
            {
                "company_name": "某建设投资有限公司",
                "owner_category": "state_owned_commercial",
                "ownership_confidence": 85,
                "ownership_basis": "人工核验国有控股",
            }
        )
        foreign = build_enhanced_enterprise_profile(
            {
                "company_name": "某制造企业",
                "company_type": "外商投资企业",
            }
        )

        self.assertEqual(state_owned.ownership_type, STATE_OWNERSHIP)
        self.assertEqual(state_owned.ownership_confidence, "medium")
        self.assertEqual(state_owned.ownership_basis, "人工核验国有控股")
        self.assertEqual(foreign.ownership_type, FOREIGN_OWNERSHIP)

    def test_limited_company_is_not_guessed_as_private(self):
        profile = build_enhanced_enterprise_profile(
            {
                "company_name": "海门示例科技有限公司",
                "project_address": "某项目施工地址",
            }
        )

        self.assertEqual(profile.ownership_type, UNKNOWN_CLASSIFICATION)
        self.assertIn("不依据“有限公司”", profile.ownership_basis)
        self.assertEqual(profile.company_address, UNKNOWN)
        self.assertEqual(profile.company_scale, UNKNOWN_CLASSIFICATION)

    def test_employee_count_provides_explainable_scale_reference(self):
        cases = (
            (1500, LARGE_COMPANY),
            (500, MEDIUM_COMPANY),
            (100, SMALL_COMPANY),
            (8, MICRO_COMPANY),
        )
        for employee_count, expected_scale in cases:
            with self.subTest(employee_count=employee_count):
                profile = build_enhanced_enterprise_profile(
                    {
                        "company_name": "示例企业",
                        "employee_count": employee_count,
                    }
                )
                self.assertEqual(profile.company_scale, expected_scale)
                self.assertEqual(profile.company_scale_confidence, "medium")
                self.assertIn("行业标准", profile.company_scale_basis)

    def test_filter_supports_ownership_and_company_scale(self):
        profiles = [
            build_enhanced_enterprise_profile(
                {
                    "company_name": "民营大型企业",
                    "registration_type": "私营企业",
                    "company_scale": "大型企业",
                }
            ),
            build_enhanced_enterprise_profile(
                {
                    "company_name": "国有中型企业",
                    "owner_category": "state_owned_commercial",
                    "company_scale": "中型企业",
                }
            ),
            build_enhanced_enterprise_profile({"company_name": "待核验企业"}),
        ]

        filtered = filter_enhanced_profiles(
            profiles,
            ownership_type=STATE_OWNERSHIP,
            company_scale=MEDIUM_COMPANY,
        )

        self.assertEqual([profile.company_name for profile in filtered], ["国有中型企业"])
        self.assertEqual(len(filter_enhanced_profiles(profiles)), 3)
        self.assertEqual(
            len(filter_enhanced_profiles(profiles, ownership_type=ALL_FILTER)),
            3,
        )
        self.assertEqual(filter_enhanced_profiles(profiles, company_scale="无效"), [])
        self.assertIn(UNKNOWN_CLASSIFICATION, COMPANY_SCALE_OPTIONS)

    def test_enrichment_adds_fields_without_mutating_input(self):
        original = {
            "company_name": "示例企业",
            "legal_person": "李四",
            "owner_category": "private_enterprise",
        }

        enriched = enrich_enhanced_enterprise_profile(original)

        self.assertNotIn("company_scale", original)
        self.assertEqual(enriched["legal_person"], "李四")
        self.assertEqual(enriched["ownership_type"], PRIVATE_OWNERSHIP)
        self.assertEqual(enriched["company_scale"], UNKNOWN_CLASSIFICATION)

    def test_company_strength_uses_capital_age_and_scale(self):
        cases = (
            (
                {
                    "registered_capital": "1亿元",
                    "establish_date": "2010-01-01",
                    "company_scale": "大型企业",
                },
                ("A", "A 强", 20),
            ),
            (
                {
                    "registered_capital": "5000万元",
                    "establish_date": "2018-01-01",
                    "company_scale": "中型企业",
                },
                ("B", "B 良好", 15),
            ),
            (
                {
                    "registered_capital": "500万元",
                    "establish_date": "2022-01-01",
                    "company_scale": "小型企业",
                },
                ("C", "C 一般", 10),
            ),
        )
        for values, expected in cases:
            with self.subTest(expected=expected):
                assessment = assess_company_strength(
                    {"company_name": "示例企业"} | values,
                    today=date(2026, 8, 10),
                )
                self.assertEqual(
                    (
                        assessment.strength_level,
                        assessment.strength_label,
                        assessment.finance_component_score,
                    ),
                    expected,
                )

    def test_company_strength_is_d_when_fewer_than_two_dimensions_exist(self):
        assessment = assess_company_strength(
            {
                "company_name": "信息不足企业",
                "registered_capital": "1亿元",
            },
            today=date(2026, 8, 10),
        )

        self.assertEqual(assessment.strength_label, "D 信息不足")
        self.assertEqual(assessment.finance_component_score, 0)
        self.assertEqual(assessment.disclosed_dimension_count, 1)
        self.assertIn("不足两个", "".join(assessment.assessment_basis))

    def test_strength_enrichment_is_runtime_only(self):
        original = {
            "company_name": "示例企业",
            "registered_capital": "1亿元",
            "establish_date": "2010-01-01",
            "company_scale": "大型企业",
        }

        enriched = enrich_company_strength(original, today=date(2026, 8, 10))

        self.assertNotIn("enterprise_strength_level", original)
        self.assertEqual(enriched["enterprise_strength_level"], "A")
        self.assertEqual(enriched["enterprise_strength_score"], 20)


if __name__ == "__main__":
    unittest.main()
