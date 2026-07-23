import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from crawler.run_license import (
    collect_planning_construction_records_with_fallback,
    run_planning_construction_import,
)
from data_source.planning_construction_permit import (
    HAIMEN_PUBLISHER,
    PlanningSearchItem,
)


class PlanningConstructionImportCommandTest(unittest.TestCase):
    def _args(self, root: Path) -> SimpleNamespace:
        return SimpleNamespace(
            timeout_seconds=1,
            db_path=str(root / "enterprise.db"),
            debug_dir=str(root / "debug"),
        )

    def test_blocks_database_write_when_official_baseline_is_missing(self):
        diagnostics = {
            "all_pages_loaded": True,
            "source_total_count": 1,
            "parsed_list_count": 1,
            "valid_count": 0,
            "recent_90_days_count": 0,
            "recent_30_days_count": 0,
            "collection_method": "requests_api",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            args = self._args(Path(temp_dir))
            with patch(
                "crawler.run_license.collect_planning_construction_records_with_fallback",
                return_value=(diagnostics, []),
            ):
                result = run_planning_construction_import(args)

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["database_written"])
        self.assertEqual(result["inserted_count"], 0)

    def test_healthy_api_does_not_start_browser(self):
        items = [
            PlanningSearchItem(
                title=f"测试项目{i}建设工程规划许可证批后公布",
                publish_date="2026-07-21",
                publisher=HAIMEN_PUBLISHER,
                detail_url=(
                    "http://zrzy.jiangsu.gov.cn/nthm/gtzx/ghgs/"
                    f"jsxmphgb/202607/item{i}.htm"
                ),
            )
            for i in range(60)
        ]
        crawler = Mock()
        crawler.collect_all_search_items.return_value = (60, 10, items)
        crawler.errors = []
        crawler.max_pages = 100
        existing_rows = [{"source_url": item.detail_url} for item in items]

        with tempfile.TemporaryDirectory() as temp_dir:
            args = self._args(Path(temp_dir))
            with (
                patch("crawler.run_license.PlanningConstructionPermitCrawler", return_value=crawler),
                patch("crawler.run_license._collect_browser_search_items") as browser_fallback,
                patch(
                    "crawler.run_license.load_public_planning_construction_permits",
                    return_value=existing_rows,
                ),
            ):
                diagnostics, records = collect_planning_construction_records_with_fallback(args)

        browser_fallback.assert_not_called()
        self.assertEqual(diagnostics["collection_method"], "requests_api")
        self.assertEqual(diagnostics["skipped_existing_count"], 60)
        self.assertEqual(records, [])

    def test_abnormal_api_starts_browser_fallback(self):
        crawler = Mock()
        crawler.last_first_page_html = "<html>policy only</html>"
        crawler.collect_all_search_items.return_value = (1, 1, [])
        crawler.errors = []
        crawler.max_pages = 100
        browser_diagnostics = {
            "source_total_count": 211,
            "valid_count": 208,
            "all_pages_loaded": True,
            "latest_date": "2026-07-21",
            "collection_method": "playwright_browser",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args = self._args(root)
            with (
                patch("crawler.run_license.PlanningConstructionPermitCrawler", return_value=crawler),
                patch(
                    "crawler.run_license._collect_browser_search_items",
                    return_value=(browser_diagnostics, []),
                ) as browser_fallback,
                patch(
                    "crawler.run_license.load_public_planning_construction_permits",
                    return_value=[],
                ),
            ):
                diagnostics, records = collect_planning_construction_records_with_fallback(args)

            abnormal_html = root / "debug" / "planning_construction_abnormal_response.html"
            self.assertTrue(abnormal_html.exists())

        browser_fallback.assert_called_once()
        self.assertEqual(diagnostics["collection_method"], "playwright_browser")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
