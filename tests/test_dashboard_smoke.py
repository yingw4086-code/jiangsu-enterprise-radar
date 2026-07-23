import unittest
from unittest.mock import patch

from app.ai.provider import OpenAICompatibleClient
from streamlit.testing.v1 import AppTest


class DashboardSmokeTest(unittest.TestCase):
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
        self.assertIn("数据源验证中，暂未纳入V1版本", rendered_text)
        self.assertIn("不作为授信审批依据", rendered_text)


if __name__ == "__main__":
    unittest.main()
