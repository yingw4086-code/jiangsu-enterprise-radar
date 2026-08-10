from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REGION_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "regions.json"


class RegionConfigError(ValueError):
    """Raised when the region configuration is malformed or ambiguous."""


class RegionNotFoundError(LookupError):
    """Raised when no configured region matches a query."""


@dataclass(frozen=True)
class RegionConfig:
    region_key: str
    province: str
    city: str
    district: str
    area_code: str
    administrative_code: str = ""
    source_area_code: str = ""


class RegionQueryService:
    """Resolve configured regions by code or by province/city/district."""

    def __init__(self, regions: list[RegionConfig]) -> None:
        if not regions:
            raise RegionConfigError("区域配置不能为空")

        self._by_key: dict[str, RegionConfig] = {}
        self._by_name: dict[tuple[str, str, str], RegionConfig] = {}
        for region in regions:
            name_key = (region.province, region.city, region.district)
            if region.region_key in self._by_key:
                raise RegionConfigError(f"region_key 重复：{region.region_key}")
            if name_key in self._by_name:
                raise RegionConfigError(
                    "省/市/区县组合重复：" + "/".join(name_key)
                )
            self._by_key[region.region_key] = region
            self._by_name[name_key] = region

    @classmethod
    def from_file(
        cls,
        config_path: Path = DEFAULT_REGION_CONFIG_PATH,
    ) -> "RegionQueryService":
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise RegionConfigError(f"区域配置不存在：{config_path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RegionConfigError(f"无法读取区域配置：{config_path}") from exc

        raw_regions = _extract_regions(payload)
        return cls([_parse_region(item, index) for index, item in enumerate(raw_regions)])

    def get_by_region_key(self, region_key: str) -> RegionConfig:
        normalized = _required_text(region_key, "region_key")
        try:
            return self._by_key[normalized]
        except KeyError as exc:
            raise RegionNotFoundError(f"未配置 region_key：{normalized}") from exc

    def resolve_region_key(self, province: str, city: str, district: str) -> str:
        name_key = (
            _required_text(province, "province"),
            _required_text(city, "city"),
            _required_text(district, "district"),
        )
        try:
            return self._by_name[name_key].region_key
        except KeyError as exc:
            raise RegionNotFoundError(
                "未配置省/市/区县：" + "/".join(name_key)
            ) from exc

    def resolve_path(self, region_path: str) -> str:
        parts = [part.strip() for part in str(region_path or "").split("/")]
        if len(parts) != 3 or not all(parts):
            raise RegionConfigError("区域路径必须为：省/市/区县")
        return self.resolve_region_key(*parts)

    def list_regions(self) -> tuple[RegionConfig, ...]:
        return tuple(self._by_key.values())

    def list_provinces(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(region.province for region in self._by_key.values()))

    def list_cities(self, province: str) -> tuple[str, ...]:
        selected_province = _required_text(province, "province")
        cities = tuple(
            dict.fromkeys(
                region.city
                for region in self._by_key.values()
                if region.province == selected_province
            )
        )
        if not cities:
            raise RegionNotFoundError(f"未配置省份：{selected_province}")
        return cities

    def list_districts(self, province: str, city: str) -> tuple[str, ...]:
        selected_province = _required_text(province, "province")
        selected_city = _required_text(city, "city")
        districts = tuple(
            dict.fromkeys(
                region.district
                for region in self._by_key.values()
                if region.province == selected_province
                and region.city == selected_city
            )
        )
        if not districts:
            raise RegionNotFoundError(
                f"未配置省/市：{selected_province}/{selected_city}"
            )
        return districts


def _extract_regions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and "regions" in payload:
        payload = payload["regions"]
    elif isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RegionConfigError("regions.json 必须是区域对象、区域数组或包含 regions 数组的对象")
    return payload


def _parse_region(item: dict[str, Any], index: int) -> RegionConfig:
    try:
        area_code = _required_text(item.get("area_code"), "area_code")
        return RegionConfig(
            region_key=_required_text(item.get("region_key"), "region_key"),
            province=_required_text(item.get("province"), "province"),
            city=_required_text(item.get("city"), "city"),
            district=_required_text(item.get("district"), "district"),
            area_code=area_code,
            administrative_code=(
                str(item.get("administrative_code") or "").strip() or area_code
            ),
            source_area_code=(
                str(item.get("source_area_code") or "").strip() or area_code
            ),
        )
    except RegionConfigError as exc:
        raise RegionConfigError(f"第 {index + 1} 个区域配置无效：{exc}") from exc


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise RegionConfigError(f"{field_name} 不能为空")
    return normalized
