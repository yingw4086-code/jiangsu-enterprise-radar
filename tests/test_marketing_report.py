from __future__ import annotations

import unittest
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from app.marketing_report import (
    REPORT_TITLE,
    build_marketing_report,
    marketing_report_filename,
    marketing_report_to_text,
    render_marketing_report_pdf,
)


def marketing_item(**overrides):
    item = {
        "company_name": "海门智能装备有限公司",
        "project_name": "生产基地厂房扩建及设备采购项目",
        "project_type": "enterprise",
        "classification_confidence": "high",
        "permit_type": "建设工程规划许可证",
        "project_stage": "建设准备阶段",
        "industry": "智能装备制造",
        "province": "江苏省",
        "city": "南通市",
        "district": "海门区",
        "investment": "12000万元",
        "project_scale": "新建厂房及生产线",
        "finance_score": 95,
        "finance_level": "A",
        "project_value_score": 40,
        "enterprise_strength_score": 15,
        "registry_completeness_score": 10,
        "financing_need_score": 20,
        "time_window_score": 10,
        "loan_type": "固定资产贷款、项目贷款",
        "suggested_contact_time": "建议3个工作日内联系",
    }
    item.update(overrides)
    return item


class MarketingReportTest(unittest.TestCase):
    def test_report_has_all_eight_requested_sections(self):
        report = build_marketing_report(marketing_item(), today=date(2026, 8, 10))

        self.assertEqual(report.title, REPORT_TITLE)
        self.assertEqual(report.generated_date, "2026-08-10")
        self.assertEqual(report.estimated_investment, "1.2亿元（公开金额）")
        self.assertEqual(
            report.estimated_credit_need,
            "7,200万元–8,400万元（规则估算）",
        )
        self.assertIn("固定资产贷款", report.recommended_product)
        self.assertEqual(
            [section.title for section in report.sections],
            [
                "1. 企业基本情况",
                "2. 项目投资情况",
                "3. 当前项目阶段",
                "4. 预计融资需求",
                "5. 推荐银行产品",
                "6. 最佳营销时间窗口",
                "7. 首次拜访话术建议",
                "8. 风险提示",
            ],
        )

    def test_visit_script_and_product_rules_are_specific_and_explainable(self):
        report = build_marketing_report(marketing_item())
        sections = {section.title: section.content for section in report.sections}

        self.assertIn("固定资产贷款", sections["4. 预计融资需求"])
        self.assertIn("设备贷款", sections["4. 预计融资需求"])
        self.assertIn("流动资金贷款", sections["4. 预计融资需求"])
        self.assertIn("项目总投资", sections["7. 首次拜访话术建议"])
        self.assertIn("现场拜访", sections["7. 首次拜访话术建议"])
        self.assertIn("预计授信金额", sections["4. 预计融资需求"])
        self.assertIn("7,200万元–8,400万元", sections["4. 预计融资需求"])
        self.assertEqual(len(report.explanation_basis), 6)
        self.assertTrue(any("finance_score=95" in rule for rule in report.explanation_basis))
        self.assertTrue(any("企业实力=15/20" in rule for rule in report.explanation_basis))
        self.assertTrue(any("工商完整度=10/10" in rule for rule in report.explanation_basis))
        self.assertTrue(any("金额预测规则" in rule for rule in report.explanation_basis))

    def test_missing_credit_and_registration_data_are_risk_notices(self):
        report = build_marketing_report(
            marketing_item(investment="未披露", classification_confidence="low")
        )
        risk_section = report.sections[-1].content

        self.assertIn("成立时间未披露", risk_section)
        self.assertIn("注册资本未披露", risk_section)
        self.assertIn("不能形成企业信用评价", risk_section)
        self.assertIn("项目投资金额未披露", risk_section)
        self.assertIn("人工复核企业属性", risk_section)

    def test_text_export_keeps_report_sections_and_disclaimer(self):
        text = marketing_report_to_text(build_marketing_report(marketing_item()))

        self.assertIn(REPORT_TITLE, text)
        self.assertIn("8. 风险提示", text)
        self.assertIn("预计授信金额", text)
        self.assertIn("生成依据", text)
        self.assertIn("不作为授信审批依据", text)

    def test_pdf_export_is_readable_and_has_expected_metadata(self):
        report = build_marketing_report(marketing_item(), today=date(2026, 8, 10))

        pdf_bytes = render_marketing_report_pdf(report)
        reader = PdfReader(BytesIO(pdf_bytes))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 5000)
        self.assertGreaterEqual(len(reader.pages), 1)
        self.assertEqual(reader.metadata.title, REPORT_TITLE)
        self.assertIn("客户经理营销建议报告", extracted)
        self.assertIn("预计授信", extracted)
        self.assertIn("风险提示", extracted)
        self.assertIn("不作为授信审批依据", extracted)

    def test_pdf_filename_is_stable_and_safe(self):
        report = build_marketing_report(
            marketing_item(company_name="海门/智能 装备有限公司"),
            today=date(2026, 8, 10),
        )

        self.assertEqual(
            marketing_report_filename(report),
            "海门_智能_装备有限公司_客户经理营销建议报告_2026-08-10.pdf",
        )


if __name__ == "__main__":
    unittest.main()
