import unittest

from data_source.planning_construction_permit_browser import parse_display_total


class PlanningConstructionPermitBrowserTest(unittest.TestCase):
    def test_parses_total_from_official_counter(self):
        self.assertEqual(parse_display_total("为您检索出211 条数据"), 211)
        self.assertEqual(parse_display_total("211"), 211)
        self.assertEqual(parse_display_total("暂无数据"), 0)


if __name__ == "__main__":
    unittest.main()
