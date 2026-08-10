from __future__ import annotations

from collections import Counter
from typing import Any

from data_source.official_permit_record import OfficialPermitRecord, from_validation_record
from data_source.permit_validation import (
    PermitSourceConfig,
    PermitValidationCrawler,
    classify_haimen,
    is_target_list_item,
)


PERMIT_TYPE = "建设工程施工许可证"
SOURCE_NAME = "南通市数据局批准结果"
SOURCE_URL = "https://shuju.nantong.gov.cn/ntsxzspj/pzjg/pzjg.html"
TRUECMS_ENDPOINT = "https://shuju.nantong.gov.cn/truecms/messageController/getMessage.do"
COLUMN_ID = "1cfdefeb-e9aa-4eea-9737-d46421fc97ff"
HAIMEN_TITLE_HINTS = (
    "海门",
    "叠石桥",
    "三星镇",
    "常乐镇",
    "悦来镇",
    "四甲镇",
    "余东镇",
    "正余镇",
    "包场镇",
    "临江镇",
    "海永镇",
)

SOURCE_CONFIG = PermitSourceConfig(
    key="construction_start",
    source_name=SOURCE_NAME,
    permit_type=PERMIT_TYPE,
    list_url=SOURCE_URL,
    base_url="https://shuju.nantong.gov.cn",
    column_id=COLUMN_ID,
    detail_path_prefix="/ntsxzspj/pzjg/content/",
    scan_all_list_pages=True,
)


class ConstructionStartPermitCrawler:
    def __init__(
        self,
        *,
        timeout_seconds: int = 25,
        request_interval_seconds: float = 1.0,
    ) -> None:
        self.backend = PermitValidationCrawler(
            timeout_seconds=timeout_seconds,
            request_interval_seconds=request_interval_seconds,
            detail_limit=100,
        )

    @property
    def errors(self) -> list[str]:
        return self.backend.errors

    def collect(self) -> tuple[list[OfficialPermitRecord], dict[str, Any]]:
        items, source_total, group_requests, list_complete = self.backend._collect_list_items(
            SOURCE_CONFIG
        )
        permit_candidates = [item for item in items if is_target_list_item(SOURCE_CONFIG, item)]
        haimen_hints = [item for item in permit_candidates if has_haimen_title_hint(item.title)]
        records: list[OfficialPermitRecord] = []
        excluded: Counter[str] = Counter()
        detail_success_count = 0

        for item in haimen_hints:
            parsed, failure_reason = self.backend._fetch_and_parse_detail(SOURCE_CONFIG, item)
            if parsed is None:
                excluded[failure_reason or "详情解析失败"] += 1
                continue
            detail_success_count += 1
            if parsed.permit_type != PERMIT_TYPE:
                excluded[f"实际为{parsed.permit_type}"] += 1
                continue
            parsed = classify_haimen(parsed)
            if not parsed.haimen_match or parsed.haimen_match_confidence < 80:
                excluded["详情页没有置信度80以上的海门证据"] += 1
                continue
            records.append(from_validation_record(parsed, project_stage="开工建设"))

        report = {
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "endpoint_url": TRUECMS_ENDPOINT,
            "request_method": "GET",
            "request_params": {
                "columnId": COLUMN_ID,
                "startrecord": "按官网每30条分组",
                "endrecord": "按官网每30条分组",
                "perpage": "10",
            },
            "source_total_count": source_total,
            "list_records_fetched": len(items),
            "list_group_request_count": group_requests,
            "list_scan_complete": list_complete,
            "permit_candidate_count": len(permit_candidates),
            "haimen_title_hint_count": len(haimen_hints),
            "detail_success_count": detail_success_count,
            "valid_count": len(records),
            "excluded_count": sum(excluded.values()),
            "excluded_reasons": dict(excluded),
            "strict_filter_note": "仅详情页能以80分以上置信度确认海门归属的记录才入库",
            "errors": list(self.errors),
        }
        return records, report


def has_haimen_title_hint(title: str) -> bool:
    return any(marker in title for marker in HAIMEN_TITLE_HINTS)
