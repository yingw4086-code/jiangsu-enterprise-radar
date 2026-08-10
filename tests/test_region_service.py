from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.region_service import (
    RegionConfigError,
    RegionNotFoundError,
    RegionQueryService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RegionQueryServiceTest(unittest.TestCase):
    def test_current_haimen_config_resolves_by_key_and_names(self):
        service = RegionQueryService.from_file(PROJECT_ROOT / "config" / "regions.json")

        region = service.get_by_region_key("320684")

        self.assertEqual(region.province, "江苏省")
        self.assertEqual(region.city, "南通市")
        self.assertEqual(region.district, "海门区")
        self.assertEqual(region.area_code, "320684")
        self.assertEqual(region.administrative_code, "320614")
        self.assertEqual(region.source_area_code, "320684")
        self.assertEqual(
            service.resolve_region_key("江苏省", "南通市", "海门区"),
            "320684",
        )
        self.assertEqual(service.resolve_path("江苏省/南通市/海门区"), "320684")

    def test_future_region_array_supports_multiple_regions(self):
        payload = [
            {
                "region_key": "320684",
                "province": "江苏省",
                "city": "南通市",
                "district": "海门区",
                "area_code": "320684",
            },
            {
                "region_key": "320583",
                "province": "江苏省",
                "city": "苏州市",
                "district": "昆山市",
                "area_code": "320583",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "regions.json"
            config_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            service = RegionQueryService.from_file(config_path)

        self.assertEqual(service.get_by_region_key("320583").district, "昆山市")
        self.assertEqual(
            service.resolve_region_key("江苏省", "苏州市", "昆山市"),
            "320583",
        )

    def test_jiangsu_config_contains_all_prefecture_cities_and_districts(self):
        service = RegionQueryService.from_file(PROJECT_ROOT / "config" / "regions.json")

        self.assertEqual(service.list_provinces(), ("江苏省",))
        self.assertEqual(
            service.list_cities("江苏省"),
            (
                "南京市",
                "无锡市",
                "徐州市",
                "常州市",
                "苏州市",
                "南通市",
                "连云港市",
                "淮安市",
                "盐城市",
                "扬州市",
                "镇江市",
                "泰州市",
                "宿迁市",
            ),
        )
        self.assertEqual(len(service.list_regions()), 95)
        self.assertEqual(len(service.list_districts("江苏省", "南京市")), 11)
        self.assertEqual(len(service.list_districts("江苏省", "苏州市")), 9)
        self.assertEqual(
            service.list_districts("江苏省", "南通市"),
            ("崇川区", "通州区", "海门区", "启东市", "如东县", "如皋市", "海安市"),
        )

    def test_nanjing_suzhou_and_nantong_queries_resolve(self):
        service = RegionQueryService.from_file(PROJECT_ROOT / "config" / "regions.json")

        self.assertEqual(
            service.resolve_region_key("江苏省", "南京市", "玄武区"),
            "320102",
        )
        self.assertEqual(
            service.resolve_region_key("江苏省", "苏州市", "昆山市"),
            "320583",
        )
        self.assertEqual(
            service.resolve_region_key("江苏省", "南通市", "海门区"),
            "320684",
        )

    def test_unknown_and_invalid_queries_fail_explicitly(self):
        service = RegionQueryService.from_file(PROJECT_ROOT / "config" / "regions.json")

        with self.assertRaises(RegionNotFoundError):
            service.get_by_region_key("330102")
        with self.assertRaises(RegionNotFoundError):
            service.resolve_region_key("浙江省", "杭州市", "上城区")
        with self.assertRaises(RegionNotFoundError):
            service.list_cities("浙江省")
        with self.assertRaises(RegionNotFoundError):
            service.list_districts("江苏省", "杭州市")
        with self.assertRaises(RegionConfigError):
            service.resolve_path("江苏省/南通市")

    def test_duplicate_region_key_is_rejected(self):
        repeated = {
            "region_key": "320684",
            "province": "江苏省",
            "city": "南通市",
            "district": "海门区",
            "area_code": "320684",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "regions.json"
            config_path.write_text(
                json.dumps([repeated, {**repeated, "district": "其他区"}], ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RegionConfigError):
                RegionQueryService.from_file(config_path)


if __name__ == "__main__":
    unittest.main()
