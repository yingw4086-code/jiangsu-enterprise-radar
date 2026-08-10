from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from app.official_permit_data import load_official_permit_dataset
from app.permit_data import load_planning_permit_dataset
from app.region_service import RegionQueryService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "database" / "enterprise.db"
CLOUD_PLANNING_PATH = (
    PROJECT_ROOT / "data" / "cloud" / "planning_construction_permits.json"
)
CLOUD_LAND_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_land_permits.json"
CLOUD_START_PATH = (
    PROJECT_ROOT / "data" / "cloud" / "construction_start_permits.json"
)
LAND_PERMIT_TYPE = "建设用地规划许可证"
START_PERMIT_TYPE = "建设工程施工许可证"


class Phase313RegionQueryTest(unittest.TestCase):
    def test_nanjing_suzhou_and_haimen_queries_do_not_cross_regions(self):
        service = RegionQueryService.from_file(
            PROJECT_ROOT / "config" / "regions.json"
        )
        region_keys = {
            "南京玄武": service.resolve_region_key("江苏省", "南京市", "玄武区"),
            "苏州昆山": service.resolve_region_key("江苏省", "苏州市", "昆山市"),
            "南通海门": service.resolve_region_key("江苏省", "南通市", "海门区"),
        }

        totals = {}
        for label, region_key in region_keys.items():
            planning = load_planning_permit_dataset(
                DATABASE_PATH,
                CLOUD_PLANNING_PATH,
                region_key=region_key,
            )
            land = load_official_permit_dataset(
                DATABASE_PATH,
                CLOUD_LAND_PATH,
                permit_type=LAND_PERMIT_TYPE,
                region_key=region_key,
            )
            start = load_official_permit_dataset(
                DATABASE_PATH,
                CLOUD_START_PATH,
                permit_type=START_PERMIT_TYPE,
                region_key=region_key,
            )
            totals[label] = (len(planning.items), len(land.items), len(start.items))
            for item in [*planning.items, *land.items, *start.items]:
                self.assertEqual(str(item.get("region_key")), region_key)

        self.assertEqual(region_keys["南京玄武"], "320102")
        self.assertEqual(region_keys["苏州昆山"], "320583")
        self.assertEqual(region_keys["南通海门"], "320684")
        self.assertEqual(totals["南京玄武"], (0, 0, 0))
        self.assertEqual(totals["苏州昆山"], (0, 0, 0))
        self.assertEqual(totals["南通海门"], (205, 19, 1))

        connection = sqlite3.connect(DATABASE_PATH)
        try:
            total = connection.execute(
                "SELECT COUNT(*) FROM construction_permits"
            ).fetchone()[0]
            region_counts = connection.execute(
                """
                SELECT region_key, COUNT(*)
                FROM construction_permits
                GROUP BY region_key
                """
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(total, 236)
        self.assertEqual(
            region_counts,
            [
                ("320115", 2),
                ("320116", 2),
                ("320509", 5),
                ("320613", 2),
                ("320684", 225),
            ],
        )


if __name__ == "__main__":
    unittest.main()
