import unittest
from unittest.mock import patch

from app.ai.provider import OpenAICompatibleClient
from streamlit.testing.v1 import AppTest


class DashboardSmokeTest(unittest.TestCase):
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
        self.assertEqual(metrics["当前真实许可证总数"], 205)
        self.assertEqual(metrics["最近30天新增许可证数量"], 10)
        self.assertEqual(metrics["最近90天新增许可证数量"], 25)

        default_table = app.dataframe[0].value
        self.assertTrue(
            set(default_table["主体性质"].astype(str)).issubset(
                {"民营企业", "外资或港澳台企业", "国有商业企业", "混合所有制"}
            )
        )
        self.assertNotIn("政府机关", set(default_table["主体性质"].astype(str)))
        self.assertNotIn("事业单位", set(default_table["主体性质"].astype(str)))

        app.selectbox[0].set_value("全部").run()
        opportunity_table = app.dataframe[0].value
        project_names = set(opportunity_table["项目名称"].astype(str))
        self.assertIn("冬泽特医食品生产基地新建项目", project_names)
        self.assertIn("立新小区九期", project_names)
        self.assertTrue(any("平谦现代产业园" in name for name in project_names))
        self.assertTrue(
            all(str(value).startswith("2026-") for value in opportunity_table["发现时间"])
        )
        self.assertNotIn("海门区政府网站", set(opportunity_table["数据来源"].astype(str)))

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
