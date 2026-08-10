import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ai.provider import OpenAICompatibleClient
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = PROJECT_ROOT / "database" / "enterprise.db"
PHASE311_WORKBOOK = (
    PROJECT_ROOT
    / "outputs"
    / "phase3_11"
    / "company_registry_production_verification_10.xlsx"
)


class DashboardSmokeTest(unittest.TestCase):
    def test_region_selector_switches_nanjing_suzhou_and_back_to_haimen(self):
        app = AppTest.from_file("dashboard.py", default_timeout=20)
        app.run()
        self.assertFalse(app.exception)

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        self.assertEqual(selectboxes["省"].value, "江苏省")
        self.assertEqual(selectboxes["市"].value, "南通市")
        self.assertEqual(selectboxes["区县"].value, "海门区")

        selectboxes["市"].set_value("南京市").run()
        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        self.assertIn("玄武区", selectboxes["区县"].options)
        selectboxes["区县"].set_value("玄武区").run()
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(int(metrics["当前区域项目总数"]), 0)

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        selectboxes["市"].set_value("苏州市").run()
        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        self.assertIn("昆山市", selectboxes["区县"].options)
        selectboxes["区县"].set_value("昆山市").run()
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(int(metrics["当前区域项目总数"]), 0)

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        selectboxes["市"].set_value("南通市").run()
        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        selectboxes["区县"].set_value("海门区").run()
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(int(metrics["当前区域项目总数"]), 225)

    def test_homepage_uses_real_permits_without_ai_call(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()

        self.assertFalse(app.exception)
        metrics = {metric.label: int(metric.value) for metric in app.metric}
        self.assertEqual(metrics["当前区域项目总数"], 225)
        self.assertEqual(metrics["企业项目数量"], 177)
        self.assertEqual(metrics["政府项目数量"], 1)
        self.assertEqual(metrics["高可信机会数量"], 151)

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        self.assertEqual(selectboxes["省"].value, "江苏省")
        self.assertEqual(selectboxes["市"].value, "南通市")
        self.assertEqual(selectboxes["区县"].value, "海门区")

        selected_finance_level = selectboxes["融资等级筛选"].value
        finance_table = app.dataframe[0].value
        self.assertEqual(
            tuple(finance_table.columns),
            (
                "企业名称",
                "项目名称",
                "行业",
                "融资评分",
                "推荐贷款类型",
                "建议联系时间",
            ),
        )
        if selected_finance_level == "A":
            self.assertTrue((finance_table["融资评分"].astype(int) >= 70).all())
        else:
            self.assertEqual(selected_finance_level, "B")
            self.assertTrue(
                finance_table["融资评分"].astype(int).between(50, 69).all()
            )

        selectboxes["融资等级筛选"].set_value("B").run()
        finance_table_b = app.dataframe[0].value
        self.assertTrue(
            finance_table_b["融资评分"].astype(int).between(50, 69).all()
        )

        priority_table = app.dataframe[1].value
        self.assertEqual(
            tuple(priority_table.columns),
            ("企业名称", "项目名称", "所属行业", "发布时间", "项目类型", "置信度"),
        )
        self.assertEqual(set(priority_table["项目类型"].astype(str)), {"企业项目"})
        confidence_order = {"高": 0, "中": 1, "低": 2}
        confidence_values = [
            confidence_order[value]
            for value in priority_table["置信度"].astype(str)
        ]
        self.assertEqual(confidence_values, sorted(confidence_values))

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        selectboxes["项目类型筛选"].set_value("政府项目").run()
        government_table = app.dataframe[2].value
        self.assertEqual(len(government_table), 1)
        self.assertEqual(set(government_table["项目类型"].astype(str)), {"政府项目"})

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        selectboxes["项目类型筛选"].set_value("全部").run()
        all_table = app.dataframe[2].value
        self.assertEqual(len(all_table), 225)

    def test_enterprise_name_opens_profile_and_generates_credit_report(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            self.assertFalse(app.exception)
            self.assertGreater(len(app.button), 0)

            app.button[0].click().run()
            self.assertFalse(app.exception)

            rendered_text = "\n".join(
                element.value
                for collection in (app.markdown, app.caption, app.info)
                for element in collection
            )
            self.assertIn("企业画像与 AI 授信分析", rendered_text)
            metrics = {metric.label: metric.value for metric in app.metric}
            self.assertIn("融资评分", metrics)
            self.assertIn("机会等级", metrics)
            self.assertIn("推荐贷款产品", metrics)
            self.assertIn("预计投资规模", metrics)
            self.assertIn("预计融资需求", metrics)
            self.assertIn("金额预测推荐产品", metrics)
            self.assertIn("规则估算", str(metrics["预计投资规模"]))
            self.assertIn("规则估算", str(metrics["预计融资需求"]))
            self.assertTrue(
                any(button.label == "加入营销跟踪" for button in app.button)
            )

            profile_table = app.dataframe[0].value
            self.assertEqual(tuple(profile_table.columns), ("画像字段", "内容"))
            self.assertEqual(
                set(profile_table["画像字段"].astype(str)),
                {
                    "企业名称",
                    "企业类型",
                    "所属地区",
                    "所属行业",
                    "项目名称",
                    "项目阶段",
                    "成立时间",
                    "注册资本",
                    "企业信用等级",
                },
            )

            report_button = next(
                button for button in app.button if button.label == "生成 AI 分析报告"
            )
            report_button.click().run()
            self.assertFalse(app.exception)

            marketing_button = next(
                button for button in app.button if button.label == "生成营销报告"
            )
            marketing_button.click().run()
            self.assertFalse(app.exception)

        report_text = "\n".join(
            element.value
            for collection in (app.markdown, app.caption, app.warning)
            for element in collection
        )
        self.assertIn("《企业融资机会分析报告》", report_text)
        for section in (
            "1. 企业基本情况",
            "2. 项目投资情况",
            "3. 当前建设阶段",
            "4. 可能融资需求",
            "5. 推荐银行产品",
            "6. 建议营销时间",
            "7. 客户经理拜访建议",
        ):
            self.assertIn(section, report_text)
        self.assertIn("《客户经理营销建议报告》", report_text)
        for section in (
            "1. 企业基本情况",
            "2. 项目投资情况",
            "3. 当前项目阶段",
            "4. 预计融资需求",
            "5. 推荐银行产品",
            "6. 最佳营销时间窗口",
            "7. 首次拜访话术建议",
            "8. 风险提示",
        ):
            self.assertIn(section, report_text)
        download_buttons = app.get("download_button")
        self.assertEqual(
            len(download_buttons),
            1,
            msg=(
                f"buttons={[button.label for button in app.button]}; "
                f"errors={[element.value for element in app.error]}; "
                f"exceptions={[element.value for element in app.exception]}"
            ),
        )
        self.assertEqual(download_buttons[0].label, "下载PDF")
        self.assertIn("不作为授信审批依据", report_text)

    def test_my_customer_list_page_supports_status_filter_without_ai_call(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            app.sidebar.radio[0].set_value("我的客户列表").run()

        self.assertFalse(app.exception)
        rendered_text = "\n".join(
            element.value
            for collection in (app.markdown, app.caption, app.info)
            for element in collection
        )
        self.assertIn("我的客户列表", rendered_text)
        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        self.assertIn("跟进状态筛选", selectboxes)
        self.assertEqual(selectboxes["跟进状态筛选"].value, "全部")
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(int(metrics["客户项目数量"]), 0)
        self.assertEqual(metrics["最近跟进时间"], "尚未跟进")

    def test_enterprise_profile_page_supports_ownership_and_scale_filters(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            app.sidebar.radio[0].set_value("企业画像").run()

        self.assertFalse(app.exception)
        rendered_text = "\n".join(
            element.value
            for collection in (app.markdown, app.caption, app.warning)
            for element in collection
        )
        self.assertIn("企业工商画像", rendered_text)
        self.assertIn("企业基本信息", rendered_text)
        self.assertIn("项目情况", rendered_text)
        self.assertEqual(len(app.file_uploader), 1)
        self.assertEqual(app.file_uploader[0].label, "上传企业名单.xlsx")
        self.assertTrue(
            any(
                button.label == "下载工商信息导入模板"
                for button in app.get("download_button")
            )
        )

        selectboxes = {selectbox.label: selectbox for selectbox in app.selectbox}
        self.assertEqual(selectboxes["按企业性质筛选"].value, "全部")
        self.assertEqual(selectboxes["按规模筛选"].value, "全部")
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(int(metrics["当前区域项目总数"]), 225)
        self.assertEqual(int(metrics["已匹配企业项目"]), 29)
        self.assertEqual(int(metrics["已匹配企业数"]), 10)
        self.assertEqual(metrics["工商信息覆盖率"], "12.9%")
        self.assertGreater(int(metrics["企业数量"]), 0)
        self.assertGreater(int(metrics["企业项目数量"]), 0)
        self.assertEqual(int(metrics["有工商字段项目数"]), 0)
        self.assertIn("融资评分", metrics)
        self.assertIn("企业实力等级", metrics)
        self.assertIn("工商信息完整度", metrics)
        self.assertIn("企业规模判断", metrics)
        self.assertIn("行业判断", metrics)
        self.assertIn("预计融资金额", metrics)
        self.assertIn("推荐产品", metrics)
        self.assertIn(
            "最近工商数据导入日志",
            [expander.label for expander in app.expander],
        )

        profile_table = app.dataframe[0].value
        self.assertEqual(
            tuple(profile_table.columns),
            (
                "企业名称",
                "统一社会信用代码",
                "法人",
                "注册资本",
                "成立年份",
                "注册地址",
                "经营范围",
                "企业状态",
                "所属行业",
                "行业判断",
                "行业判断置信度",
                "企业性质",
                "企业规模",
                "企业实力等级",
                "工商信息完整度",
                "项目名称",
                "融资评分",
                "预计融资金额",
                "推荐产品",
            ),
        )
        self.assertEqual(set(profile_table["企业规模"].astype(str)), {"未知"})
        self.assertEqual(set(profile_table["企业实力等级"].astype(str)), {"D 信息不足"})
        self.assertEqual(set(profile_table["工商信息完整度"].astype(str)), {"0% D"})

        selectboxes["按企业性质筛选"].set_value("国有企业").run()
        self.assertFalse(app.exception)
        state_owned_table = app.dataframe[0].value
        self.assertGreater(len(state_owned_table), 0)
        self.assertEqual(
            set(state_owned_table["企业性质"].astype(str)),
            {"国有企业"},
        )

    def test_company_import_requires_preview_and_second_confirmation(self):
        connection = sqlite3.connect(PRODUCTION_DB)
        try:
            registry_count_before = connection.execute(
                "SELECT COUNT(*) FROM company_registry"
            ).fetchone()[0]
        finally:
            connection.close()

        app = AppTest.from_file("dashboard.py", default_timeout=20)
        app.run()
        app.sidebar.radio[0].set_value("企业画像").run()
        app.file_uploader[0].set_value(
            (
                PHASE311_WORKBOOK.name,
                PHASE311_WORKBOOK.read_bytes(),
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet",
            )
        ).run()
        preview_button = next(
            button
            for button in app.button
            if button.label == "确认文件并生成预览"
        )
        preview_button.click().run()

        self.assertFalse(app.exception)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(int(metrics["待导入记录"]), 10)
        self.assertEqual(int(metrics["预计新增"]), 0)
        self.assertEqual(int(metrics["预计更新"]), 10)
        self.assertEqual(int(metrics["匹配许可证企业"]), 10)
        self.assertTrue(
            any(
                checkbox.label
                == "我已核对预览内容，并确认写入 company_registry"
                for checkbox in app.checkbox
            )
        )
        execute_button = next(
            button
            for button in app.button
            if button.label == "确认导入 company_registry"
        )
        self.assertTrue(execute_button.disabled)

        connection = sqlite3.connect(PRODUCTION_DB)
        try:
            registry_count_after = connection.execute(
                "SELECT COUNT(*) FROM company_registry"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(registry_count_before, 10)
        self.assertEqual(registry_count_after, registry_count_before)

    def test_government_projects_have_separate_audit_page(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            app.sidebar.radio[0].set_value("政府公益项目").run()

        self.assertFalse(app.exception)
        rendered_text = "\n".join(
            element.value
            for collection in (app.markdown, app.caption, app.info)
            for element in collection
        )
        self.assertIn("政府公益项目", rendered_text)
        self.assertIn("不进入首页默认重点机会", rendered_text)

    def test_opportunity_list_uses_real_permits_and_ownership_filter(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            app.sidebar.radio[0].set_value("企业机会列表").run()

        self.assertFalse(app.exception)
        rendered_text = "\n".join(
            element.value
            for collection in (app.markdown, app.caption, app.info)
            for element in collection
        )
        self.assertIn("真实建设工程规划许可证", rendered_text)
        table = app.dataframe[0].value
        self.assertTrue(
            set(table["主体性质"].astype(str)).issubset(
                {"民营企业", "外资或港澳台企业", "国有商业企业", "混合所有制"}
            )
        )
        self.assertNotIn("海门区政府网站", set(table["数据来源"].astype(str)))

        app.selectbox[0].set_value("待核验").run()
        pending_table = app.dataframe[0].value
        self.assertEqual(set(pending_table["主体性质"].astype(str)), {"待核验"})

    def test_planning_construction_permit_page_renders(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            self.assertFalse(app.exception)

            app.sidebar.radio[0].set_value("海门建设工程规划许可证").run()

            self.assertFalse(app.exception)
            rendered_text = "\n".join(
                element.value
                for collection in (app.markdown, app.caption, app.info)
                for element in collection
            )
        self.assertIn("海门建设工程规划许可证", rendered_text)
        self.assertIn("已在独立标签页展示", rendered_text)
        self.assertIn("不作为授信审批依据", rendered_text)

    def test_land_and_construction_start_pages_render_without_ai_call(self):
        with patch.object(
            OpenAICompatibleClient,
            "complete_json",
            side_effect=AssertionError("Dashboard不得调用AI API"),
        ):
            app = AppTest.from_file("dashboard.py", default_timeout=20)
            app.run()
            self.assertFalse(app.exception)

            for page_name in (
                "海门建设用地规划许可证",
                "海门建设工程施工许可证",
            ):
                app.sidebar.radio[0].set_value(page_name).run()
                self.assertFalse(app.exception)
                rendered_text = "\n".join(
                    element.value
                    for collection in (app.markdown, app.caption, app.info)
                    for element in collection
                )
                self.assertIn(page_name, rendered_text)
                self.assertIn("不作为授信审批依据", rendered_text)

    def test_legacy_json_is_kept_on_separate_page(self):
        app = AppTest.from_file("dashboard.py", default_timeout=20)
        app.run()
        app.sidebar.radio[0].set_value("旧版项目数据").run()

        self.assertFalse(app.exception)
        rendered_text = "\n".join(
            element.value
            for collection in (app.markdown, app.caption, app.info)
            for element in collection
        )
        self.assertIn("旧版项目数据", rendered_text)
        self.assertIn("不参与首页统计和重点机会排序", rendered_text)


if __name__ == "__main__":
    unittest.main()
