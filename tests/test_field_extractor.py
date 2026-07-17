import unittest

from app.parsers.field_extractor import extract_announcement_fields


class FieldExtractorTest(unittest.TestCase):
    def test_extracts_core_fields(self):
        fields = extract_announcement_fields(
            title="区数据局关于江苏海门示例装备有限公司年产高端装备零部件项目备案的通知",
            text="发布时间：2026年7月14日 企业名称：江苏海门示例装备有限公司 项目名称：年产高端装备零部件项目 审批事项：企业投资项目备案",
            url="https://example.com/a.html",
        )

        self.assertEqual(fields["company_name"], "江苏海门示例装备有限公司")
        self.assertEqual(fields["project_name"], "年产高端装备零部件项目")
        self.assertEqual(fields["approval_item"], "企业投资项目备案")
        self.assertEqual(fields["date"], "2026-07-14")

    def test_extracts_company_from_approval_title(self):
        fields = extract_announcement_fields(
            title="区数据局关于南通恒科体育用品有限公司年产篮球内胆100万个新建项目备案的批复",
            text="区数据局关于南通恒科体育用品有限公司年产篮球内胆100万个新建项目备案的批复",
            url="https://example.com/b.html",
            fallback_date="2025-07-01",
        )

        self.assertEqual(fields["company_name"], "南通恒科体育用品有限公司")
        self.assertEqual(fields["project_name"], "南通恒科体育用品有限公司年产篮球内胆100万个新建项目")
        self.assertEqual(fields["approval_item"], "项目备案")
        self.assertEqual(fields["date"], "2025-07-01")


if __name__ == "__main__":
    unittest.main()
