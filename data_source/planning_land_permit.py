from __future__ import annotations

from collections import Counter
from typing import Any

from data_source.official_permit_record import OfficialPermitRecord, from_validation_record
from data_source.permit_validation import (
    PermitSourceConfig,
    PermitValidationCrawler,
    classify_haimen,
)


PERMIT_TYPE = "建设用地规划许可证"
SOURCE_NAME = "海门区自然资源局行政许可"
SOURCE_URL = "https://www.haimen.gov.cn/hmsgtj/xzxk/xzxk.html"
TRUECMS_ENDPOINT = "https://www.haimen.gov.cn/truecms/messageController/getMessage.do"
COLUMN_ID = "754f6db5-d294-46d5-b25c-da3a86d102cd"

SOURCE_CONFIG = PermitSourceConfig(
    key="planning_land_independent",
    source_name=SOURCE_NAME,
    permit_type=PERMIT_TYPE,
    list_url=SOURCE_URL,
    base_url="https://www.haimen.gov.cn",
    column_id=COLUMN_ID,
    detail_path_prefix="/hmsgtj/xzxk/content/",
    scan_all_list_pages=False,
    fixed_district="海门区",
    fixed_district_code="320684",
)


class PlanningLandPermitCrawler:
    def __init__(
        self,
        *,
        timeout_seconds: int = 25,
        request_interval_seconds: float = 1.0,
        max_list_items: int = 30,
    ) -> None:
        self.max_list_items = max(1, min(max_list_items, 30))
        self.backend = PermitValidationCrawler(
            timeout_seconds=timeout_seconds,
            request_interval_seconds=request_interval_seconds,
            detail_limit=self.max_list_items,
        )

    @property
    def errors(self) -> list[str]:
        return self.backend.errors

    def collect(self) -> tuple[list[OfficialPermitRecord], dict[str, Any]]:
        items, source_total, group_requests, list_complete = self.backend._collect_list_items(
            SOURCE_CONFIG
        )
        selected = items[: self.max_list_items]
        records: list[OfficialPermitRecord] = []
        excluded: Counter[str] = Counter()
        detail_success_count = 0

        for item in selected:
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
                excluded["海门归属证据不足"] += 1
                continue
            records.append(from_validation_record(parsed, project_stage="拿地规划"))

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
            "list_records_fetched": len(selected),
            "list_group_request_count": group_requests,
            "list_scan_complete": list_complete,
            "detail_success_count": detail_success_count,
            "valid_count": len(records),
            "excluded_count": sum(excluded.values()),
            "excluded_reasons": dict(excluded),
            "errors": list(self.errors),
        }
        return records, report
