from __future__ import annotations

import csv
import io
import json
import math
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from app.parsers.html_links import html_to_text, normalize_space
from data_source.base import DEFAULT_USER_AGENT, UNKNOWN, parse_date, parse_date_object


TRUECMS_GROUP_SIZE = 30
TRUECMS_PAGE_SIZE = 10
HAIMEN_DISTRICT_CODE = "320684"
HAIMEN_ADDRESS_MARKERS = (
    "海门区",
    "海门街道",
    "三星镇",
    "常乐镇",
    "悦来镇",
    "四甲镇",
    "余东镇",
    "正余镇",
    "包场镇",
    "临江镇",
    "海永镇",
    "海门港新区",
    "叠石桥",
)


@dataclass(frozen=True)
class PermitSourceConfig:
    key: str
    source_name: str
    permit_type: str
    list_url: str
    base_url: str
    column_id: str
    detail_path_prefix: str
    scan_all_list_pages: bool
    fixed_district: str = ""
    fixed_district_code: str = ""

    @property
    def endpoint_url(self) -> str:
        return urllib.parse.urljoin(self.base_url, "/truecms/messageController/getMessage.do")


PERMIT_SOURCES = (
    PermitSourceConfig(
        key="planning_land",
        source_name="海门区自然资源局行政许可",
        permit_type="建设用地规划许可证",
        list_url="https://www.haimen.gov.cn/hmsgtj/xzxk/xzxk.html",
        base_url="https://www.haimen.gov.cn",
        column_id="754f6db5-d294-46d5-b25c-da3a86d102cd",
        detail_path_prefix="/hmsgtj/xzxk/content/",
        scan_all_list_pages=False,
        fixed_district="海门区",
        fixed_district_code=HAIMEN_DISTRICT_CODE,
    ),
    PermitSourceConfig(
        key="planning_construction",
        source_name="南通市数据局审批环节公示",
        permit_type="建设工程规划许可证",
        list_url="https://shuju.nantong.gov.cn/ntsxzspj/sphjgs/sphjgs.html",
        base_url="https://shuju.nantong.gov.cn",
        column_id="5a43294a-2028-49b7-ab9d-7fde4ef72632",
        detail_path_prefix="/ntsxzspj/sphjgs/content/",
        scan_all_list_pages=True,
    ),
    PermitSourceConfig(
        key="construction_start",
        source_name="南通市数据局批准结果",
        permit_type="建设工程施工许可证",
        list_url="https://shuju.nantong.gov.cn/ntsxzspj/pzjg/pzjg.html",
        base_url="https://shuju.nantong.gov.cn",
        column_id="1cfdefeb-e9aa-4eea-9737-d46421fc97ff",
        detail_path_prefix="/ntsxzspj/pzjg/content/",
        scan_all_list_pages=True,
    ),
)


@dataclass
class PermitListItem:
    title: str
    publish_date: str
    detail_url: str


@dataclass
class PermitValidationRecord:
    source_key: str
    source_name: str
    source_title: str
    permit_type: str
    source_url: str
    construction_unit: str = UNKNOWN
    company_name: str = UNKNOWN
    project_name: str = UNKNOWN
    project_address: str = UNKNOWN
    construction_location: str = UNKNOWN
    construction_unit_address: str = UNKNOWN
    district: str = UNKNOWN
    district_code: str = UNKNOWN
    issuing_authority: str = UNKNOWN
    permit_name: str = UNKNOWN
    permit_number: str = UNKNOWN
    permit_date: str = UNKNOWN
    publish_date: str = UNKNOWN
    project_scale: str = UNKNOWN
    investment_amount: str = UNKNOWN
    haimen_match: bool = False
    haimen_match_reason: str = "无可靠海门区证据，待人工核验"
    haimen_match_confidence: int = 0
    validation_status: str = "待人工核验"
    detail_success: bool = False
    attachment_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def event_date(self) -> str:
        return self.permit_date if self.permit_date != UNKNOWN else self.publish_date

    def to_csv_row(self) -> dict[str, Any]:
        return {
            "数据源": self.source_name,
            "企业名称": self.company_name,
            "建设单位": self.construction_unit,
            "项目名称": self.project_name,
            "许可证类型": self.permit_type,
            "许可证名称": self.permit_name,
            "许可证编号": self.permit_number,
            "发证日期": self.permit_date,
            "发布日期": self.publish_date,
            "项目地址": self.project_address,
            "建设地点": self.construction_location,
            "所属区县": self.district,
            "行政区划代码": self.district_code,
            "发证机关": self.issuing_authority,
            "建设单位地址": self.construction_unit_address,
            "项目规模": self.project_scale,
            "投资金额": self.investment_amount,
            "海门判断结果": "是" if self.haimen_match else "待人工核验",
            "海门判断原因": self.haimen_match_reason,
            "海门判断置信度": self.haimen_match_confidence,
            "来源链接": self.source_url,
            "详情解析成功": "是" if self.detail_success else "否",
        }


class _ListItemParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.title_parts: list[str] = []
        self.date_parts: list[str] = []
        self.in_anchor = False
        self.in_date = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "a":
            self.in_anchor = True
            self.href = attr_map.get("href", "")
        elif tag.lower() == "span":
            self.in_date = True

    def handle_data(self, data: str) -> None:
        if self.in_date:
            self.date_parts.append(data)
        elif self.in_anchor:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self.in_anchor = False
        elif tag.lower() == "span":
            self.in_date = False

    def item(self) -> PermitListItem | None:
        title = normalize_space(" ".join(self.title_parts))
        href = normalize_space(self.href)
        if not title or not href:
            return None
        return PermitListItem(
            title=title,
            publish_date=_parse_flexible_date(" ".join(self.date_parts)) or UNKNOWN,
            detail_url=urllib.parse.urljoin(self.base_url, href),
        )


class _DetailParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.rows: list[list[str]] = []
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.images: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._anchor_href = ""
        self._anchor_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if lowered in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "meta":
            key = (attr_map.get("name") or attr_map.get("property") or "").lower()
            if key:
                self.meta[key] = normalize_space(attr_map.get("content", ""))
        elif lowered == "tr":
            self._row = []
        elif lowered in {"th", "td"}:
            self._cell = []
        elif lowered == "a":
            self._anchor_href = attr_map.get("href", "")
            self._anchor_parts = []
        elif lowered == "img":
            source = attr_map.get("src", "")
            if source:
                self.images.append(urllib.parse.urljoin(self.base_url, source))
        elif lowered == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._cell is not None:
            self._cell.append(data)
        if self._anchor_href:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if lowered in {"th", "td"} and self._cell is not None:
            value = normalize_space(" ".join(self._cell))
            if self._row is None:
                self._row = []
            self._row.append(value)
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            cells = [cell for cell in self._row if cell]
            if cells:
                self.rows.append(cells)
            self._row = None
        elif lowered == "a" and self._anchor_href:
            self.links.append(
                (
                    urllib.parse.urljoin(self.base_url, self._anchor_href),
                    normalize_space(" ".join(self._anchor_parts)),
                )
            )
            self._anchor_href = ""
            self._anchor_parts = []


FIELD_ALIASES = {
    "construction_unit": ("建设单位名称", "建设单位", "项目单位", "行政相对人名称"),
    "company_name": ("企业名称", "行政相对人名称", "建设单位名称", "建设单位"),
    "project_name": ("建设项目名称", "项目名称", "工程名称"),
    "project_address": ("项目地址", "建设地址", "建设位置"),
    "construction_location": ("建设地点", "建设位置", "项目地点"),
    "construction_unit_address": ("建设单位地址", "行政相对人地址", "单位地址"),
    "district": ("所属区县", "行政区划", "所在区县", "区县"),
    "district_code": ("行政区划代码", "区划代码", "区域代码"),
    "issuing_authority": ("发证机关", "许可机关", "核发机关", "批准机关"),
    "permit_name": ("许可证书名称", "许可证名称", "许可事项名称", "事项名称"),
    "permit_number": ("许可证书编号", "许可证编号", "施工许可编号", "许可编号", "证书编号"),
    "permit_date": ("许可决定日期", "发证日期", "批准时间", "决定日期", "成文日期"),
    "publish_date": ("发布日期", "发布时间"),
    "project_scale": ("项目规模", "建设规模", "用地面积", "建筑面积", "合同价格"),
    "investment_amount": ("项目总投资", "计划总投资", "总投资", "投资金额", "合同价格"),
}


def parse_truecms_payload(text: str, base_url: str) -> tuple[int, list[PermitListItem]]:
    payload = (text or "").strip()
    json_start = payload.find("{")
    json_end = payload.rfind("}")
    if json_start < 0 or json_end <= json_start:
        raise ValueError("TrueCMS响应不包含JSON对象")
    data = json.loads(payload[json_start : json_end + 1])
    xml_text = str(data.get("result", "")).strip()
    if not xml_text:
        return 0, []
    root = ET.fromstring(xml_text)
    total_text = root.findtext("totalrecord", default="0")
    items: list[PermitListItem] = []
    for record_node in root.findall("./recordset/record"):
        fragment = record_node.text or ""
        parser = _ListItemParser(base_url)
        parser.feed(fragment)
        item = parser.item()
        if item:
            items.append(item)
    return int(total_text or 0), items


def parse_truecms_initial_page(
    html: str,
    base_url: str,
    detail_path_prefix: str,
) -> tuple[int, list[PermitListItem]]:
    total_match = re.search(r"\btotalRecord\s*:\s*(\d+)", html or "", re.I)
    items: list[PermitListItem] = []
    for fragment in re.findall(r"<li\b[^>]*>.*?</li>", html or "", re.I | re.S):
        if detail_path_prefix not in fragment:
            continue
        parser = _ListItemParser(base_url)
        parser.feed(fragment)
        item = parser.item()
        if item:
            items.append(item)
    return int(total_match.group(1)) if total_match else 0, items


def is_target_list_item(source: PermitSourceConfig, item: PermitListItem) -> bool:
    title = normalize_space(item.title)
    if source.key == "planning_land":
        # This is already the Haimen administrative-permit column. Its list
        # titles are truncated before the permit kind, so classify on details.
        return True
    if source.key == "planning_construction":
        return "建设工程规划许可证" in title and "批后公布" in title and "批前" not in title
    return bool(re.search(r"(?:工程)?施工许可(?:证)?(?:批后公布)?$", title))


def classify_haimen(record: PermitValidationRecord) -> PermitValidationRecord:
    district_code = re.sub(r"\D", "", record.district_code or "")
    if district_code == HAIMEN_DISTRICT_CODE:
        return _set_haimen(record, 100, "行政区划代码等于320684")
    if "海门区" in record.district or record.district == "海门":
        return _set_haimen(record, 95, f"所属区县明确为{record.district}")

    project_location = " ".join((record.project_address, record.construction_location))
    location_hit = next((marker for marker in HAIMEN_ADDRESS_MARKERS if marker in project_location), "")
    if location_hit:
        return _set_haimen(record, 90, f"项目地址或建设地点包含{location_hit}")
    if "海门" in record.issuing_authority:
        return _set_haimen(record, 85, f"发证机关包含海门：{record.issuing_authority}")

    unit_hit = next(
        (marker for marker in HAIMEN_ADDRESS_MARKERS if marker in record.construction_unit_address),
        "",
    )
    if unit_hit:
        record.haimen_match_confidence = 70
        record.haimen_match_reason = f"建设单位地址包含{unit_hit}，低于自动归类阈值"
        record.validation_status = "待人工核验"
        return record
    if "海门" in record.source_title:
        record.haimen_match_confidence = 60
        record.haimen_match_reason = "仅标题包含海门，低于自动归类阈值"
        record.validation_status = "待人工核验"
        return record
    record.haimen_match_reason = "未提取到置信度80分以上的海门区证据"
    record.validation_status = "待人工核验"
    return record


def _set_haimen(record: PermitValidationRecord, confidence: int, reason: str) -> PermitValidationRecord:
    record.haimen_match = True
    record.haimen_match_confidence = confidence
    record.haimen_match_reason = reason
    record.validation_status = "海门已确认"
    return record


class PermitValidationCrawler:
    def __init__(
        self,
        timeout_seconds: int = 20,
        request_interval_seconds: float = 1.0,
        detail_limit: int = 40,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.request_interval_seconds = max(1.0, request_interval_seconds)
        self.detail_limit = max(10, detail_limit)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self.curl_session: Any | None = None
        try:
            from curl_cffi import requests as curl_requests

            self.curl_session = curl_requests.Session(impersonate="chrome")
            self.curl_session.headers.update(dict(self.session.headers))
        except ImportError:
            pass
        self.errors: list[str] = []
        self._last_request_at = 0.0
        self._ocr_engine: Any | None = None

    def validate_all(self, csv_path: Path, today: date | None = None) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        csv_records: list[PermitValidationRecord] = []
        current_day = today or date.today()
        for source in PERMIT_SOURCES:
            report, sample_records = self.validate_source(source, current_day)
            reports.append(report)
            csv_records.extend(sample_records)
        write_validation_csv(csv_path, csv_records)
        return {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "database_written": False,
            "deepseek_called": False,
            "csv_path": str(csv_path),
            "csv_record_count": len(csv_records),
            "sources": reports,
            "errors": self.errors,
        }

    def validate_source(
        self,
        source: PermitSourceConfig,
        today: date,
    ) -> tuple[dict[str, Any], list[PermitValidationRecord]]:
        all_items, total_count, group_requests, list_complete = self._collect_list_items(source)
        target_items = [item for item in all_items if is_target_list_item(source, item)]
        if source.key == "planning_land":
            detail_items = target_items[:TRUECMS_GROUP_SIZE]
            successful_target_limit = len(detail_items)
        else:
            recent_items = [item for item in target_items if _within_days(item.publish_date, 90, today)]
            detail_items = list(recent_items)
            seen = {item.detail_url for item in detail_items}
            for item in target_items:
                if item.detail_url not in seen:
                    detail_items.append(item)
                    seen.add(item.detail_url)
            successful_target_limit = self.detail_limit

        detail_records: list[PermitValidationRecord] = []
        detail_attempted_count = 0
        detail_page_success_count = 0
        detail_request_failures = 0
        excluded_detail_reasons: Counter[str] = Counter()
        for item in detail_items:
            if source.key != "planning_land" and len(detail_records) >= successful_target_limit:
                break
            detail_attempted_count += 1
            record, failure_reason = self._fetch_and_parse_detail(source, item)
            if not record:
                if failure_reason.startswith("详情请求失败"):
                    detail_request_failures += 1
                excluded_detail_reasons[failure_reason or "详情结构未识别"] += 1
                continue
            detail_page_success_count += 1
            if record.permit_type != source.permit_type:
                excluded_detail_reasons[f"实际为{record.permit_type}"] += 1
                continue
            detail_records.append(classify_haimen(record))

        if source.key == "planning_land":
            candidate_count = len(target_items)
            parsed_result_count = len(detail_records)
            recent_base: list[PermitListItem | PermitValidationRecord] = detail_records
        else:
            candidate_count = len(target_items)
            parsed_result_count = len(detail_records)
            detail_by_url = {record.source_url: record for record in detail_records}
            recent_base = [detail_by_url.get(item.detail_url, item) for item in target_items]

        confirmed = [record for record in detail_records if record.haimen_match]
        pending = [record for record in detail_records if not record.haimen_match]
        recent_90 = sum(_record_within_days(item, 90, today) for item in recent_base)
        recent_30 = sum(_record_within_days(item, 30, today) for item in recent_base)
        latest_publish = _latest_date(item.publish_date for item in target_items)
        latest_permit = _latest_date(record.permit_date for record in detail_records)
        detail_not_attempted = max(0, candidate_count - detail_attempted_count)
        missing_detail_count = detail_attempted_count - detail_page_success_count

        samples = _select_samples(detail_records, 10)
        completeness = calculate_key_field_completeness(samples)
        report = {
            "source_key": source.key,
            "source_name": source.source_name,
            "permit_type": source.permit_type,
            "list_url": source.list_url,
            "endpoint_url": source.endpoint_url,
            "column_id": source.column_id,
            "source_total_count": total_count,
            "source_list_page_count": math.ceil(total_count / TRUECMS_PAGE_SIZE) if total_count else 0,
            "scanned_list_page_count": math.ceil(len(all_items) / TRUECMS_PAGE_SIZE) if all_items else 0,
            "list_group_request_count": group_requests,
            "list_scan_complete": list_complete,
            "list_item_parsed_count": len(all_items),
            "target_candidate_count": candidate_count,
            "detail_attempted_count": detail_attempted_count,
            "detail_page_success_count": detail_page_success_count,
            "parsed_result_count": parsed_result_count,
            "missing_detail_count": missing_detail_count,
            "detail_not_attempted_count": detail_not_attempted,
            "detail_request_failed_count": detail_request_failures,
            "excluded_detail_reasons": dict(excluded_detail_reasons),
            "non_target_list_item_count": max(0, len(all_items) - len(target_items)),
            "haimen_confirmed_count": len(confirmed),
            "haimen_pending_count": len(pending),
            "recent_90_days_count": recent_90,
            "recent_30_days_count": recent_30,
            "latest_publish_date": latest_publish,
            "latest_permit_date": latest_permit,
            "sample_count": len(samples),
            "key_field_completeness": completeness,
            "samples": [record.to_csv_row() for record in samples],
        }
        return report, samples

    def _collect_list_items(
        self,
        source: PermitSourceConfig,
    ) -> tuple[list[PermitListItem], int, int, bool]:
        list_response = self._request(source.list_url)
        if not list_response:
            return [], 0, 0, False
        list_html = self._decode_response(list_response)
        total_count, first_items = parse_truecms_initial_page(
            list_html,
            source.base_url,
            source.detail_path_prefix,
        )
        if not total_count or not first_items:
            self.errors.append(f"{source.source_name} 栏目页未解析出总数或首批列表")
            return [], total_count, 0, False
        items = list(first_items)
        group_requests = 0
        list_complete = len(items) >= total_count
        if source.scan_all_list_pages:
            total_groups = math.ceil(total_count / TRUECMS_GROUP_SIZE)
            for group_index in range(1, total_groups):
                start = group_index * TRUECMS_GROUP_SIZE + 1
                text = self._fetch_truecms_group(source, start, TRUECMS_GROUP_SIZE)
                group_requests += 1
                if not text:
                    list_complete = False
                    self.errors.append(
                        f"{source.source_name} 分页接口从startrecord={start}起不可用，停止继续请求"
                    )
                    break
                try:
                    _, group_items = parse_truecms_payload(text, source.base_url)
                    items.extend(group_items)
                except (ValueError, json.JSONDecodeError, ET.ParseError) as exc:
                    list_complete = False
                    self.errors.append(f"{source.source_name} 列表分组解析失败 start={start}: {exc}")
            list_complete = len({item.detail_url for item in items}) >= total_count

        unique: dict[str, PermitListItem] = {}
        for item in items:
            unique[item.detail_url] = item
        return list(unique.values()), total_count, group_requests, list_complete

    def _fetch_truecms_group(
        self,
        source: PermitSourceConfig,
        start_record: int,
        count: int,
    ) -> str:
        end_record = start_record + count - 1
        params = {
            "callback": "raw",
            "startrecord": str(start_record),
            "endrecord": str(end_record),
            "perpage": str(TRUECMS_PAGE_SIZE),
            "contentTemplate": "",
            "columnId": source.column_id,
            "_": str(int(time.time() * 1000)),
        }
        response = self._request(
            source.endpoint_url,
            params=params,
            referer=source.list_url,
            attempts=1,
        )
        if not response:
            return ""
        return self._decode_response(response)

    def _fetch_and_parse_detail(
        self,
        source: PermitSourceConfig,
        item: PermitListItem,
    ) -> tuple[PermitValidationRecord | None, str]:
        response = self._request(item.detail_url, referer=source.list_url)
        if not response:
            return None, "详情请求失败"
        html = self._decode_response(response)
        parser = _DetailParser(item.detail_url)
        parser.feed(html)
        html_text = html_to_text(html)
        attachment_urls = _attachment_urls(parser)
        attachment_texts: list[str] = []
        for attachment_url in attachment_urls[:2]:
            attachment_text = self._extract_attachment_text(attachment_url, item.detail_url)
            if attachment_text:
                attachment_texts.append(attachment_text)
        combined_text = "\n".join([item.title, html_text, *attachment_texts])
        fields = _extract_structured_fields(parser.rows, combined_text)
        record = _build_record(source, item, parser, fields, combined_text)
        record.detail_success = True
        record.attachment_count = len(attachment_urls)
        record.raw = {
            "meta": parser.meta,
            "attachment_urls": attachment_urls,
            "field_labels": sorted(fields),
        }
        return record, ""

    def _extract_attachment_text(self, url: str, referer: str) -> str:
        response = self._request(url, referer=referer)
        if not response:
            return ""
        content_type = response.headers.get("Content-Type", "").lower()
        lowered_url = urllib.parse.urlsplit(url).path.lower()
        if lowered_url.endswith(".pdf") or "application/pdf" in content_type:
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(response.content))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except (ImportError, OSError, ValueError) as exc:
                self.errors.append(f"PDF解析失败 url={url}: {exc}")
                return ""
        if lowered_url.endswith((".jpg", ".jpeg", ".png", ".bmp")) or content_type.startswith("image/"):
            try:
                if self._ocr_engine is None:
                    from rapidocr_onnxruntime import RapidOCR

                    self._ocr_engine = RapidOCR()
                rows, _ = self._ocr_engine(response.content)
                return "\n".join(str(row[1]) for row in (rows or []))
            except (ImportError, RuntimeError, TypeError, ValueError) as exc:
                self.errors.append(f"图片OCR失败 url={url}: {exc}")
        return ""

    def _request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        referer: str = "",
        attempts: int = 2,
    ) -> Any | None:
        headers = {"Referer": referer} if referer else None
        failures: list[str] = []
        clients = (
            (("curl_cffi", self.curl_session),)
            if self.curl_session is not None
            else (("requests", self.session),)
        )
        for attempt in range(max(1, attempts)):
            for client_name, client in clients:
                if client is None:
                    continue
                self._wait()
                try:
                    response = client.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout_seconds,
                    )
                    self._last_request_at = time.monotonic()
                    if response.status_code == 200:
                        return response
                    failures.append(f"{client_name}:HTTP {response.status_code}:attempt={attempt + 1}")
                except Exception as exc:  # Two HTTP clients expose different exception classes.
                    self._last_request_at = time.monotonic()
                    failures.append(f"{client_name}:{type(exc).__name__}:attempt={attempt + 1}")
        self.errors.append(f"请求失败 url={url}; {'; '.join(failures)}")
        return None

    def _wait(self) -> None:
        if not self._last_request_at:
            return
        remaining = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _decode_response(response: Any) -> str:
        content_type = response.headers.get("Content-Type", "")
        charset_match = re.search(r"charset=([\w-]+)", content_type, re.I)
        if charset_match:
            encoding = charset_match.group(1)
        else:
            encoding = (
                getattr(response, "apparent_encoding", None)
                or getattr(response, "charset_encoding", None)
                or getattr(response, "encoding", None)
                or "utf-8"
            )
        try:
            return response.content.decode(encoding, errors="replace")
        except LookupError:
            return response.content.decode("utf-8", errors="replace")


def _attachment_urls(parser: _DetailParser) -> list[str]:
    urls: list[str] = []
    for url, text in parser.links:
        path = urllib.parse.urlsplit(url).path.lower()
        if path.endswith((".pdf", ".jpg", ".jpeg", ".png", ".bmp")) or (
            "/upload/" in path and any(word in text for word in ("许可证", "证照", "附件", "签章"))
        ):
            urls.append(url)
    for url in parser.images:
        path = urllib.parse.urlsplit(url).path.lower()
        if "/upload/" in path or "/uploadpics/" in path:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _extract_structured_fields(rows: list[list[str]], text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    normalized_aliases = {
        field_name: tuple(_normalize_label(alias) for alias in aliases)
        for field_name, aliases in FIELD_ALIASES.items()
    }
    for row in rows:
        for index, cell in enumerate(row[:-1]):
            label = _normalize_label(cell)
            for field_name, aliases in normalized_aliases.items():
                if label in aliases or any(alias and alias in label for alias in aliases):
                    value = _clean_value(row[index + 1])
                    if value and field_name not in fields:
                        fields[field_name] = value
        for index in range(0, len(row) - 1, 2):
            label = _normalize_label(row[index])
            for field_name, aliases in normalized_aliases.items():
                if label in aliases:
                    value = _clean_value(row[index + 1])
                    if value and field_name not in fields:
                        fields[field_name] = value

    all_labels = sorted(
        ((field_name, alias) for field_name, aliases in FIELD_ALIASES.items() for alias in aliases),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )
    normalized_text = normalize_space(text)
    stop_pattern = "|".join(re.escape(alias) for _, alias in all_labels)
    for field_name, alias in all_labels:
        if field_name in fields:
            continue
        match = re.search(
            rf"{re.escape(alias)}\s*[:：]?\s*(.+?)(?=\s+(?:{stop_pattern})\s*[:：]?|$)",
            normalized_text,
        )
        if match:
            value = _clean_value(match.group(1))
            if value:
                fields[field_name] = value
    return fields


def _build_record(
    source: PermitSourceConfig,
    item: PermitListItem,
    parser: _DetailParser,
    fields: dict[str, str],
    combined_text: str,
) -> PermitValidationRecord:
    permit_name = fields.get("permit_name", UNKNOWN)
    permit_type = _detect_permit_type(f"{permit_name} {item.title} {combined_text}")
    if source.key != "planning_land" and source.permit_type in item.title:
        permit_type = source.permit_type
    if source.key == "construction_start" and "施工许可" in item.title:
        permit_type = source.permit_type

    company = fields.get("company_name", UNKNOWN)
    construction_unit = fields.get("construction_unit", company)
    title_company, title_project = _parse_title_entities(item.title, source)
    if company == UNKNOWN:
        company = construction_unit if construction_unit != UNKNOWN else title_company
    if construction_unit == UNKNOWN:
        construction_unit = company
    project_name = fields.get("project_name", UNKNOWN)
    if project_name == UNKNOWN:
        project_name = title_project
    project_name = _clean_project_name(project_name)

    publish_date = _parse_flexible_date(fields.get("publish_date", "")) or _meta_publish_date(parser.meta)
    publish_date = publish_date or _parse_flexible_date(item.publish_date) or UNKNOWN
    permit_date = _parse_flexible_date(fields.get("permit_date", "")) or _extract_permit_date(combined_text)
    permit_number = _extract_permit_number(fields.get("permit_number", ""), combined_text)
    district_code = _extract_district_code(fields.get("district_code", ""), combined_text, permit_number)
    project_address = fields.get("project_address", UNKNOWN)
    construction_location = fields.get("construction_location", project_address)
    district = fields.get("district", UNKNOWN)
    if district == UNKNOWN:
        district = _infer_district(" ".join((project_address, construction_location, combined_text)))
    if district == UNKNOWN and source.fixed_district:
        district = source.fixed_district
    if district_code == UNKNOWN and source.fixed_district_code:
        district_code = source.fixed_district_code

    return PermitValidationRecord(
        source_key=source.key,
        source_name=source.source_name,
        source_title=item.title,
        permit_type=permit_type,
        source_url=item.detail_url,
        construction_unit=construction_unit,
        company_name=company,
        project_name=project_name,
        project_address=project_address,
        construction_location=construction_location,
        construction_unit_address=fields.get("construction_unit_address", UNKNOWN),
        district=district,
        district_code=district_code,
        issuing_authority=fields.get("issuing_authority", UNKNOWN),
        permit_name=permit_name if permit_name != UNKNOWN else permit_type,
        permit_number=permit_number,
        permit_date=permit_date,
        publish_date=publish_date,
        project_scale=fields.get("project_scale", UNKNOWN),
        investment_amount=fields.get("investment_amount", UNKNOWN),
    )


def _parse_title_entities(title: str, source: PermitSourceConfig) -> tuple[str, str]:
    cleaned = normalize_space(title)
    company = UNKNOWN
    if source.key == "construction_start":
        parts = re.split(r"-{2,}|—{2,}|－{2,}", cleaned, maxsplit=1)
        if len(parts) == 2 and _looks_like_organization(parts[0]):
            company = parts[0].strip()
            cleaned = parts[1]
        cleaned = re.sub(r"(?:工程)?施工许可(?:证)?(?:批后公布)?$", "", cleaned).strip(" -—")
    elif source.key == "planning_construction":
        company_match = re.match(r"^(.*?(?:有限公司|集团|委员会|人民政府))[-—－](.+)$", cleaned)
        if company_match:
            company = company_match.group(1)
        cleaned = re.sub(r"建设工程规划许可证(?:调整|变更)?批后公布.*$", "", cleaned).strip(" -—")
        cleaned = re.sub(r"公示类型\s*[:：].*$", "", cleaned).strip(" -—")
    else:
        cleaned = re.sub(r"^关于(?:同意|准予)", "", cleaned)
        cleaned = re.sub(r"的行政许可.*$", "", cleaned)
    return company, cleaned or UNKNOWN


def _clean_project_name(value: str) -> str:
    if not value or value == UNKNOWN:
        return UNKNOWN
    cleaned = normalize_space(value)
    cleaned = re.sub(r"\s*公示类型\s*[:：].*$", "", cleaned)
    cleaned = re.sub(r"\s+(?:19|20)\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?$", "", cleaned)
    return cleaned.strip(" -—") or UNKNOWN


def _detect_permit_type(text: str) -> str:
    for permit_type in ("建设用地规划许可证", "建设工程规划许可证", "建设工程施工许可证"):
        if permit_type in text:
            return permit_type
    if "建筑工程施工许可证" in text or "工程施工许可" in text:
        return "建设工程施工许可证"
    return UNKNOWN


def _extract_permit_number(value: str, text: str) -> str:
    candidates = [value, text]
    patterns = (
        r"[建地]字第\s*[0-9A-Z-]{12,}\s*号",
        r"\b3206\d{14}\b",
        r"\b3206\d{8}[A-Z]{2}\d{4,}\b",
    )
    for candidate in candidates:
        compact = normalize_space(candidate)
        for pattern in patterns:
            match = re.search(pattern, compact, re.I)
            if match:
                return re.sub(r"\s+", "", match.group(0))
    cleaned = _clean_value(value)
    return cleaned if len(cleaned) >= 8 else UNKNOWN


def _extract_district_code(value: str, text: str, permit_number: str) -> str:
    for candidate in (value, text):
        match = re.search(r"(?:行政区划代码|区划代码|区域代码)\s*[:：]?\s*(\d{6})", candidate)
        if match:
            return match.group(1)
    if HAIMEN_DISTRICT_CODE in permit_number:
        return HAIMEN_DISTRICT_CODE
    cleaned = re.sub(r"\D", "", value or "")
    return cleaned[:6] if len(cleaned) >= 6 else UNKNOWN


def _extract_permit_date(text: str) -> str:
    compact_text = re.sub(r"(?<=\d)\s+(?=\d|年|月|日)", "", text or "")
    for label in FIELD_ALIASES["permit_date"]:
        match = re.search(
            rf"{re.escape(label)}\s*[:：]?\s*((?:19|20)\d{{2}}[年./-]\d{{1,2}}[月./-]\d{{1,2}}日?)",
            compact_text,
        )
        if match:
            return _parse_flexible_date(match.group(1)) or UNKNOWN
    return UNKNOWN


def _meta_publish_date(meta: dict[str, str]) -> str:
    for key in ("pubdate", "publishdate", "date", "article:published_time"):
        value = _parse_flexible_date(meta.get(key, ""))
        if value:
            return value
    return ""


def _parse_flexible_date(value: str) -> str:
    compact = re.sub(r"(?<=\d)\s+(?=\d|年|月|日)", "", value or "")
    return parse_date(compact)


def _infer_district(text: str) -> str:
    match = re.search(
        r"(海门区|崇川区|通州区|如东县|启东市|如皋市|海安市|南通经济技术开发区)",
        text,
    )
    return match.group(1) if match else UNKNOWN


def _normalize_label(value: str) -> str:
    return re.sub(r"[\s:：*＊（）()\[\]【】]+", "", normalize_space(value))


def _clean_value(value: str) -> str:
    cleaned = normalize_space(value).strip(" :：;；|｜")
    return cleaned if cleaned and cleaned != UNKNOWN else ""


def _looks_like_organization(value: str) -> bool:
    return any(marker in value for marker in ("公司", "集团", "委员会", "人民政府", "管理局", "建设局"))


def _within_days(value: str, days: int, today: date) -> bool:
    parsed = parse_date_object(value)
    if not parsed:
        return False
    age = (today - parsed).days
    return 0 <= age <= days


def _record_within_days(item: PermitListItem | PermitValidationRecord, days: int, today: date) -> bool:
    value = item.event_date() if isinstance(item, PermitValidationRecord) else item.publish_date
    return _within_days(value, days, today)


def _latest_date(values: Any) -> str:
    parsed = [parse_date_object(value) for value in values if value and value != UNKNOWN]
    valid = [value for value in parsed if value]
    return max(valid).isoformat() if valid else UNKNOWN


def _select_samples(records: list[PermitValidationRecord], count: int) -> list[PermitValidationRecord]:
    return sorted(
        records,
        key=lambda record: (
            record.haimen_match,
            record.haimen_match_confidence,
            parse_date_object(record.event_date()) or date.min,
        ),
        reverse=True,
    )[:count]


def calculate_key_field_completeness(records: list[PermitValidationRecord]) -> dict[str, Any]:
    if not records:
        return {"complete_fields": 0, "total_fields": 0, "rate": 0.0}
    required_fields = (
        "company_name",
        "project_name",
        "permit_number",
        "permit_date",
        "publish_date",
        "source_url",
    )
    complete = sum(
        1
        for record in records
        for field_name in required_fields
        if getattr(record, field_name) not in {"", UNKNOWN}
    )
    total = len(records) * len(required_fields)
    return {
        "complete_fields": complete,
        "total_fields": total,
        "rate": round(complete / total * 100, 2),
    }


def write_validation_csv(path: Path, records: list[PermitValidationRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [record.to_csv_row() for record in records]
    fieldnames = list(PermitValidationRecord("", "", "", "", "").to_csv_row())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path
