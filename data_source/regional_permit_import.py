from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.region_service import RegionQueryService
from data_source.base import UNKNOWN, calculate_fresh_score


SUPPORTED_PERMIT_TYPES = frozenset(
    {
        "建设用地规划许可证",
        "建设工程规划许可证",
        "建设工程施工许可证",
    }
)
PROTECTED_REGION_KEYS = frozenset({"320684"})


class RegionalPermitImportError(ValueError):
    """Raised when a regional import file cannot be trusted or normalized."""


@dataclass(frozen=True)
class RegionalPermitRecord:
    project_name: str
    construction_unit: str
    permit_type: str
    publish_date: str
    project_address: str
    region_key: str
    source_region: str
    source_time: str
    source_url: str
    source_name: str
    source_key: str
    permit_number: str = UNKNOWN
    permit_date: str = UNKNOWN
    issuing_authority: str = UNKNOWN
    province: str = "江苏省"
    city: str = ""
    district: str = ""
    area_code: str = ""
    company_name: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def fresh_score(self) -> int:
        return calculate_fresh_score(
            self.permit_date if self.permit_date != UNKNOWN else self.publish_date
        )


def load_verified_import_records(
    input_path: Path,
    *,
    region_config_path: Path,
    source_config_path: Path,
) -> list[RegionalPermitRecord]:
    payload = _read_json(input_path, "区域许可证导入文件")
    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise RegionalPermitImportError("导入文件必须是数组或包含 items 数组的对象")

    region_service = RegionQueryService.from_file(region_config_path)
    sources = _load_verified_sources(source_config_path)
    records = [
        _parse_record(item, index, region_service, sources)
        for index, item in enumerate(raw_items)
    ]
    _reject_duplicates(records)
    return records


def _parse_record(
    raw: Any,
    index: int,
    region_service: RegionQueryService,
    sources: dict[str, dict[str, Any]],
) -> RegionalPermitRecord:
    if not isinstance(raw, dict):
        raise RegionalPermitImportError(f"第 {index + 1} 条记录不是对象")

    region_key = _required(raw, "region_key", index)
    if region_key in PROTECTED_REGION_KEYS:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录属于受保护海门区域，禁止通过区域批量入口导入"
        )
    try:
        region = region_service.get_by_region_key(region_key)
    except LookupError as exc:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录的 region_key 未配置：{region_key}"
        ) from exc

    source_key = _required(raw, "source_key", index)
    source = sources.get(source_key)
    if source is None:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录的数据源未验证：{source_key}"
        )
    if str(source.get("city") or "") != region.city:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录的数据源城市与 region_key 不一致"
        )

    permit_type = _required(raw, "permit_type", index)
    allowed_types = set(source.get("permit_types") or [])
    if permit_type not in SUPPORTED_PERMIT_TYPES or permit_type not in allowed_types:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录的许可证类型不在已验证范围：{permit_type}"
        )

    source_url = _required(raw, "source_url", index)
    host = (urlparse(source_url).hostname or "").lower()
    allowed_domains = {str(value).lower() for value in source.get("official_domains") or []}
    if urlparse(source_url).scheme != "https" or host not in allowed_domains:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录不是已验证的官方 HTTPS 域名：{source_url}"
        )

    source_region = _required(raw, "source_region", index)
    expected_region = f"{region.province}/{region.city}/{region.district}"
    if source_region != expected_region:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条 source_region 不匹配："
            f"expected={expected_region}, actual={source_region}"
        )

    publish_date = _date_text(_required(raw, "publish_date", index), "publish_date", index)
    permit_date_value = str(raw.get("permit_date") or UNKNOWN).strip() or UNKNOWN
    permit_date = (
        UNKNOWN
        if permit_date_value == UNKNOWN
        else _date_text(permit_date_value, "permit_date", index)
    )
    source_time = _datetime_text(_required(raw, "source_time", index), index)
    if date.fromisoformat(publish_date) > datetime.fromisoformat(source_time).date():
        raise RegionalPermitImportError(
            f"第 {index + 1} 条 publish_date 晚于 source_time，拒绝导入"
        )

    construction_unit = _required(raw, "construction_unit", index)
    return RegionalPermitRecord(
        project_name=_required(raw, "project_name", index),
        construction_unit=construction_unit,
        company_name=str(raw.get("company_name") or construction_unit).strip(),
        permit_type=permit_type,
        permit_number=str(raw.get("permit_number") or UNKNOWN).strip() or UNKNOWN,
        permit_date=permit_date,
        publish_date=publish_date,
        project_address=_required(raw, "address", index),
        issuing_authority=str(raw.get("issuing_authority") or UNKNOWN).strip() or UNKNOWN,
        province=region.province,
        city=region.city,
        district=region.district,
        region_key=region.region_key,
        area_code=region.area_code,
        source_region=source_region,
        source_time=source_time,
        source_url=source_url,
        source_name=_required(raw, "source_name", index),
        source_key=source_key,
        raw=dict(raw),
    )


def _load_verified_sources(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(path, "区域数据源配置")
    raw_sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(raw_sources, list):
        raise RegionalPermitImportError("区域数据源配置缺少 sources 数组")
    verified: dict[str, dict[str, Any]] = {}
    for source in raw_sources:
        if not isinstance(source, dict) or source.get("status") != "verified":
            continue
        source_key = str(source.get("source_key") or "").strip()
        if source_key:
            verified[source_key] = source
    return verified


def _reject_duplicates(records: list[RegionalPermitRecord]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (record.region_key, record.permit_number, record.source_url)
        if key in seen:
            raise RegionalPermitImportError(f"导入文件包含重复记录：{record.project_name}")
        seen.add(key)


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RegionalPermitImportError(f"{label}不存在：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RegionalPermitImportError(f"无法读取{label}：{path}") from exc


def _required(raw: dict[str, Any], field_name: str, index: int) -> str:
    value = str(raw.get(field_name) or "").strip()
    if not value:
        raise RegionalPermitImportError(f"第 {index + 1} 条记录缺少 {field_name}")
    return value


def _date_text(value: str, field_name: str, index: int) -> str:
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录的 {field_name} 不是 YYYY-MM-DD"
        ) from exc


def _datetime_text(value: str, index: int) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RegionalPermitImportError(
            f"第 {index + 1} 条记录的 source_time 不是 ISO 时间"
        ) from exc
    return parsed.isoformat(sep=" ")
