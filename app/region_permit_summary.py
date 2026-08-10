from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.region_service import RegionQueryService


@dataclass(frozen=True)
class RegionPermitSummary:
    province_total: int
    city_counts: dict[str, int]
    region_counts: dict[str, int]

    def city_count(self, city: str) -> int:
        return int(self.city_counts.get(city, 0))

    def region_count(self, region_key: str) -> int:
        return int(self.region_counts.get(region_key, 0))


def load_region_permit_summary(
    db_path: Path,
    region_config_path: Path,
    *,
    province: str = "江苏省",
) -> RegionPermitSummary:
    service = RegionQueryService.from_file(region_config_path)
    configured = {
        region.region_key: region
        for region in service.list_regions()
        if region.province == province
    }
    region_counts = {region_key: 0 for region_key in configured}
    if Path(db_path).exists():
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True
            )
            table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='construction_permits'"
            ).fetchone()
            if table is not None:
                for region_key, count in connection.execute(
                    "SELECT region_key, COUNT(*) FROM construction_permits "
                    "GROUP BY region_key"
                ):
                    key = str(region_key or "")
                    if key in region_counts:
                        region_counts[key] = int(count)
        except sqlite3.Error:
            pass
        finally:
            if connection is not None:
                connection.close()

    city_counts = {city: 0 for city in service.list_cities(province)}
    for region_key, count in region_counts.items():
        city_counts[configured[region_key].city] += count
    return RegionPermitSummary(
        province_total=sum(region_counts.values()),
        city_counts=city_counts,
        region_counts=region_counts,
    )
