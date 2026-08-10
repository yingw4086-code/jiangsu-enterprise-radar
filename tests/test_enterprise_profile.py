from __future__ import annotations

import unittest

from app.enterprise_profile import UNRATED, build_enterprise_profile, enrich_enterprise_profile


class EnterpriseProfileTest(unittest.TestCase):
    def test_builds_requested_profile_fields_from_permit(self):
        profile = build_enterprise_profile(
            {
                "company_name": "海门智能装备有限公司",
                "project_type": "enterprise",
                "owner_category": "private_enterprise",
                "province": "江苏省",
                "city": "南通市",
                "district": "海门区",
                "industry": "智能装备制造",
                "project_name": "智能装备生产基地",
                "permit_type": "建设工程规划许可证",
                "established_date": "2018-05-06",
                "registered_capital": "5000万元",
                "credit_rating": "AA",
            }
        )

        self.assertEqual(profile.company_name, "海门智能装备有限公司")
        self.assertEqual(profile.enterprise_type, "企业（民营企业）")
        self.assertEqual(profile.region, "江苏省 / 南通市 / 海门区")
        self.assertEqual(profile.project_stage, "建设准备阶段")
        self.assertEqual(profile.established_time, "2018-05-06")
        self.assertEqual(profile.registered_capital, "5000万元")
        self.assertEqual(profile.enterprise_credit_level, "AA")

    def test_missing_registration_and_credit_data_remain_disclosed_as_missing(self):
        profile = build_enterprise_profile(
            {
                "construction_unit": "某制造有限公司",
                "project_type": "enterprise",
                "permit_type": "建设用地规划许可证",
            }
        )

        self.assertEqual(profile.established_time, "未披露")
        self.assertEqual(profile.registered_capital, "未披露")
        self.assertEqual(profile.enterprise_credit_level, UNRATED)
        self.assertEqual(profile.project_stage, "拿地阶段")

    def test_customer_level_is_not_misrepresented_as_credit_rating(self):
        profile = build_enterprise_profile(
            {
                "company_name": "某企业",
                "project_type": "enterprise",
                "customer_level": "A",
            }
        )

        self.assertEqual(profile.enterprise_credit_level, UNRATED)

    def test_enrichment_does_not_mutate_original_item(self):
        original = {
            "company_name": "某企业",
            "project_type": "enterprise",
        }

        enriched = enrich_enterprise_profile(original)

        self.assertNotIn("enterprise_type", original)
        self.assertEqual(enriched["enterprise_type"], "企业")


if __name__ == "__main__":
    unittest.main()
