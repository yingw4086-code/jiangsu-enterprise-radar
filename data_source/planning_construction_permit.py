from __future__ import annotations

import math
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Any

import requests

from app.parsers.html_links import html_to_text, normalize_space
from data_source.base import (
    BaseCrawler,
    DEFAULT_USER_AGENT,
    UNKNOWN,
    calculate_fresh_score,
    parse_date,
    parse_date_object,
)


SEARCH_INDEX_URL = "http://zrzy.jiangsu.gov.cn/elsearch/search/index"
SEARCH_API_URL = "http://zrzy.jiangsu.gov.cn/elsearch/search/list"
SEARCH_AREA_CODE = "320684"
SEARCH_KEYWORD = "建设工程规划许可证"
HAIMEN_PUBLISHER = "南通市海门自然资源和规划局"
PLANNING_COLUMN_PATH = "/nthm/gtzx/ghgs/jsxmphgb/"
SERVER_PAGE_SIZE = 10


@dataclass
class PlanningSearchItem:
    title: str
    publish_date: str
    publisher: str
    detail_url: str
    category: str = ""
    excerpt: str = ""


@dataclass
class PlanningSearchPage:
    page: int
    total_count: int
    page_size: int
    items: list[PlanningSearchItem] = field(default_factory=list)
    raw_html: str = field(default="", repr=False)


@dataclass
class PlanningConstructionPermitRecord:
    title: str
    publish_date: str
    publisher: str
    detail_url: str
    area_code: str = SEARCH_AREA_CODE
    construction_unit: str = UNKNOWN
    company_name: str = UNKNOWN
    project_name: str = UNKNOWN
    project_address: str = UNKNOWN
    permit_name: str = SEARCH_KEYWORD
    permit_number: str = UNKNOWN
    issue_date: str = UNKNOWN
    issuing_authority: str = UNKNOWN
    source_url: str = ""
    source_name: str = "江苏自然资源政务信息检索服务（海门）"
    district: str = "海门区"
    district_code: str = SEARCH_AREA_CODE
    category: str = ""
    image_urls: list[str] = field(default_factory=list)
    detail_loaded: bool = False
    ocr_used: bool = False
    haimen_confidence: int = 0
    haimen_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def event_date(self) -> str:
        return self.issue_date if self.issue_date != UNKNOWN else self.publish_date

    @property
    def permit_type(self) -> str:
        return SEARCH_KEYWORD

    @property
    def permit_date(self) -> str:
        return self.issue_date

    @property
    def fresh_score(self) -> int:
        return calculate_fresh_score(self.event_date())

    def to_dict(self) -> dict[str, Any]:
        return {
            "标题": self.title,
            "发布日期": self.publish_date,
            "发布部门": self.publisher,
            "详情页链接": self.detail_url,
            "建设单位": self.construction_unit,
            "企业名称": self.company_name,
            "项目名称": self.project_name,
            "项目地址": self.project_address,
            "许可证名称": self.permit_name,
            "许可证编号": self.permit_number,
            "发证日期": self.issue_date,
            "发证机关": self.issuing_authority,
            "areaCode": self.area_code,
            "来源网址": self.source_url or self.detail_url,
            "数据来源": self.source_name,
            "所属区县": self.district,
            "行政区划代码": self.district_code,
            "fresh_score": self.fresh_score,
            "海门认定置信度": self.haimen_confidence,
            "海门认定原因": self.haimen_reason,
            "详情解析成功": self.detail_loaded,
            "本地OCR已使用": self.ocr_used,
            "详情图片": self.image_urls,
        }


class _SearchListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[PlanningSearchItem] = []
        self._results_depth = 0
        self._current: dict[str, Any] | None = None
        self._field = ""
        self._in_sign = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())
        lowered = tag.lower()
        if lowered == "ul" and "item" in classes:
            self._results_depth = 1
            return
        if self._results_depth and lowered == "ul":
            self._results_depth += 1
        if not self._results_depth:
            return
        if lowered == "li" and self._current is None:
            self._current = {
                "href": "",
                "title": [],
                "category": [],
                "excerpt": [],
                "time": [],
            }
        elif self._current is not None and lowered == "a" and not self._current["href"]:
            self._current["href"] = attr_map.get("href", "")
        elif self._current is not None and lowered == "div":
            if "item-title" in classes:
                self._field = "title"
            elif "item-content" in classes:
                self._field = "excerpt"
            elif "item-time" in classes:
                self._field = "time"
        elif self._current is not None and lowered == "span" and "sign" in classes:
            self._in_sign = True

    def handle_data(self, data: str) -> None:
        if self._current is None or not self._field:
            return
        if self._field == "title" and self._in_sign:
            self._current["category"].append(data)
            return
        self._current[self._field].append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "span" and self._in_sign:
            self._in_sign = False
            return
        if self._current is not None and lowered == "div" and self._field:
            self._field = ""
            return
        if self._current is not None and lowered == "li":
            self._append_current()
            self._current = None
        if self._results_depth and lowered == "ul":
            self._results_depth -= 1

    def _append_current(self) -> None:
        assert self._current is not None
        title = re.sub(r"\s+", "", "".join(self._current["title"]))
        href = normalize_space(self._current["href"])
        time_text = normalize_space(" ".join(self._current["time"]))
        if not title or not href:
            return
        date_match = re.search(r"20\d{2}-\d{2}-\d{2}", time_text)
        publisher = time_text[: date_match.start()].strip() if date_match else time_text
        self.items.append(
            PlanningSearchItem(
                title=title,
                publish_date=date_match.group(0) if date_match else UNKNOWN,
                publisher=publisher or UNKNOWN,
                detail_url=urllib.parse.urljoin("http://zrzy.jiangsu.gov.cn", href),
                category=normalize_space(" ".join(self._current["category"])),
                excerpt=normalize_space(" ".join(self._current["excerpt"])),
            )
        )


class _DetailPageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.meta: dict[str, str] = {}
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        lowered = tag.lower()
        if lowered == "meta":
            name = attr_map.get("name", "").strip().lower()
            if name:
                self.meta[name] = attr_map.get("content", "").strip()
        elif lowered == "img":
            source = attr_map.get("src", "").strip()
            if source and "uploadpics" not in source and not source.endswith("2016gjy-xian.png"):
                absolute = urllib.parse.urljoin(self.base_url, source)
                if PLANNING_COLUMN_PATH in absolute and absolute not in self.image_urls:
                    self.image_urls.append(absolute)


def parse_search_page(html: str, page: int = 1) -> PlanningSearchPage:
    parser = _SearchListParser()
    parser.feed(html or "")
    total_match = re.search(r"\btotal\s*:\s*[\"']?(\d+)", html or "", re.I)
    size_match = re.search(r"\bpageSize\s*:\s*[\"']?(\d+)", html or "", re.I)
    return PlanningSearchPage(
        page=page,
        total_count=int(total_match.group(1)) if total_match else 0,
        page_size=int(size_match.group(1)) if size_match else SERVER_PAGE_SIZE,
        items=parser.items,
        raw_html=html,
    )


def parse_title_entities(title: str) -> tuple[str, str]:
    base = normalize_space(title)
    base = re.sub(r"建设工程规划许可证(?:变更|调整)?批后公布.*$", "", base).strip(" -—－")
    company_pattern = re.compile(r"^(.*?(?:股份有限公司|有限责任公司|集团有限公司|有限公司))[-—－]?(.*)$")
    match = company_pattern.match(base)
    if match:
        company = normalize_space(match.group(1))
        return company, base
    return UNKNOWN, base or UNKNOWN


def parse_ocr_fields(text: str) -> dict[str, str]:
    aliases = {
        "construction_unit": ("建设单位名称", "建设单位", "项目单位"),
        "project_name": ("项目名称", "工程名称"),
        "project_address": ("建设位置", "建设地点", "项目地址"),
        "permit_number": ("许可证书编号", "许可证编号", "许可证号"),
        "issue_date": ("发证日期", "许可日期"),
        "issuing_authority": ("发证机关", "核发机关"),
    }
    lines = [normalize_space(line) for line in (text or "").splitlines() if normalize_space(line)]
    result: dict[str, str] = {}
    pending = ""
    for line in lines:
        if pending:
            result[pending] = line
            pending = ""
            continue
        for field_name, labels in aliases.items():
            matched = next((label for label in labels if line.startswith(label)), "")
            if not matched:
                continue
            value = line[len(matched) :].lstrip("：: ")
            if value:
                result[field_name] = value
            else:
                pending = field_name
            break
    if "issue_date" in result:
        result["issue_date"] = parse_date(result["issue_date"]) or result["issue_date"]
    return result


def plausible_organization(value: str) -> bool:
    if not value or value == UNKNOWN or len(value) < 4:
        return False
    return any(
        marker in value
        for marker in ("公司", "集团", "政府", "委员会", "管理局", "建设局", "中心", "学校", "医院", "合作社")
    )


def plausible_address(value: str) -> bool:
    if not value or value == UNKNOWN or len(value) < 4:
        return False
    return any(marker in value for marker in ("海门", "路", "街道", "镇", "村", "大道", "园区", "新区", "地块"))


def normalize_permit_number(value: str) -> str:
    compact = re.sub(r"\s+", "", value or "").upper()
    match = re.search(r"(?:建字第)?(?=[0-9A-Z]*\d{8})[0-9A-Z]{15,}(?:号)?", compact)
    if not match or "GG" not in match.group(0):
        return UNKNOWN
    return match.group(0)


def plausible_issuing_authority(value: str) -> bool:
    if not value or value == UNKNOWN:
        return False
    return any(marker in value for marker in ("自然资源", "规划局", "行政审批", "人民政府"))


def is_planning_construction_result(item: PlanningSearchItem, detail_meta: dict[str, str] | None = None) -> tuple[bool, str]:
    meta = detail_meta or {}
    channel = meta.get("lanmu", "")
    if SEARCH_KEYWORD not in item.title:
        return False, "标题不是建设工程规划许可证"
    if "批后公布" not in item.title:
        return False, "不是许可批后公布"
    if PLANNING_COLUMN_PATH not in item.detail_url:
        return False, "非海门建设项目批后公布栏目"
    if channel and channel != "建设项目批后公布":
        return False, "详情页栏目不匹配"
    return True, ""


def confirm_haimen(
    item: PlanningSearchItem,
    area_code: str,
    project_address: str = "",
    issuing_authority: str = "",
) -> tuple[bool, int, str]:
    if area_code == SEARCH_AREA_CODE:
        return True, 100, "搜索请求areaCode=320684，接口结果已限定海门"
    if item.publisher == HAIMEN_PUBLISHER:
        return True, 100, "发布部门为南通市海门自然资源和规划局"
    if "海门" in project_address:
        return True, 95, "详情页项目地址位于海门"
    if "海门" in issuing_authority:
        return True, 90, "发证机关为海门相关部门"
    if "海门" in item.title:
        return True, 60, "标题包含海门，仅作辅助判断"
    return False, 0, "没有可靠的海门区域证据"


def filter_planning_construction_items(
    items: list[PlanningSearchItem],
) -> tuple[list[PlanningSearchItem], int, dict[str, int]]:
    valid_items: list[PlanningSearchItem] = []
    haimen_confirmed_count = 0
    filtered_reasons: dict[str, int] = {}
    for item in items:
        confirmed, _, region_reason = confirm_haimen(item, SEARCH_AREA_CODE)
        if not confirmed:
            filtered_reasons[region_reason] = filtered_reasons.get(region_reason, 0) + 1
            continue
        haimen_confirmed_count += 1
        valid, permit_reason = is_planning_construction_result(item)
        if not valid:
            filtered_reasons[permit_reason] = filtered_reasons.get(permit_reason, 0) + 1
            continue
        valid_items.append(item)
    valid_items.sort(
        key=lambda item: parse_date_object(item.publish_date) or date.min,
        reverse=True,
    )
    return valid_items, haimen_confirmed_count, filtered_reasons


class PlanningConstructionPermitCrawler(BaseCrawler):
    source_name = "江苏自然资源政务信息检索服务（海门）"
    source_type = "建设工程规划许可证"

    def __init__(
        self,
        timeout_seconds: int = 20,
        request_interval_seconds: float = 1.0,
        max_pages: int = 30,
        enable_ocr: bool = True,
    ) -> None:
        super().__init__(max_items=500, timeout_seconds=timeout_seconds, user_agent=DEFAULT_USER_AGENT)
        self.request_interval_seconds = max(1.0, request_interval_seconds)
        self.max_pages = max(1, max_pages)
        self.enable_ocr = enable_ocr
        self.session = requests.Session()
        self._session_initialized = False
        self._last_request_at = 0.0
        self._ocr_engine: Any | None = None
        self.last_first_page_html = ""

    @property
    def index_url(self) -> str:
        return f"{SEARCH_INDEX_URL}?{urllib.parse.urlencode({'areaCode': SEARCH_AREA_CODE, 'content': SEARCH_KEYWORD})}"

    def build_request_params(self, page: int = 1) -> dict[str, str]:
        return {
            "content": SEARCH_KEYWORD,
            # The official form submits an empty page value for the first AJAX
            # request. Pagination callbacks submit 2, 3, ... afterwards.
            "page": "" if page <= 1 else str(page),
            "type": "",
            "areaCode": SEARCH_AREA_CODE,
            "fieldType": "0",
            "orderType": "2",
            "startTime": "",
            "endTime": "",
        }

    def request_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Referer": self.index_url,
            "X-Requested-With": "XMLHttpRequest",
        }

    def _ensure_search_session(self) -> None:
        if self._session_initialized:
            return
        self._wait_for_rate_limit()
        response = self.session.get(
            self.index_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=self.timeout_seconds,
        )
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        self._session_initialized = True

    def fetch_search_page(self, page: int = 1) -> PlanningSearchPage:
        params = self.build_request_params(page)
        try:
            # The browser opens the search page before its AJAX list request.
            # Keep that session cookie in memory only; never log or persist it.
            self._ensure_search_session()
            self._wait_for_rate_limit()
            response = self.session.get(
                SEARCH_API_URL,
                params=params,
                headers=self.request_headers(),
                timeout=self.timeout_seconds,
            )
            self._last_request_at = time.monotonic()
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
            return parse_search_page(response.text, page=page)
        except requests.RequestException as exc:
            self.errors.append(f"列表请求失败 page={page} url={SEARCH_API_URL}: {exc}")
            return PlanningSearchPage(page=page, total_count=0, page_size=SERVER_PAGE_SIZE)

    def collect_all_search_items(self) -> tuple[int, int, list[PlanningSearchItem]]:
        first = self.fetch_search_page(1)
        self.last_first_page_html = first.raw_html
        if first.total_count <= 0:
            return 0, 0, []
        pages = min(self.max_pages, max(1, math.ceil(first.total_count / max(1, first.page_size))))
        items = list(first.items)
        for page_number in range(2, pages + 1):
            page = self.fetch_search_page(page_number)
            items.extend(page.items)
        unique: dict[str, PlanningSearchItem] = {}
        for item in items:
            unique[item.detail_url] = item
        return first.total_count, len(first.items), list(unique.values())

    def collect_import_records(
        self,
    ) -> tuple[dict[str, Any], list[PlanningConstructionPermitRecord]]:
        raw_total, current_page_count, items = self.collect_all_search_items()
        valid_items, haimen_confirmed_count, filtered_reasons = filter_planning_construction_items(items)
        records = [self.fetch_detail(item, use_ocr=True) for item in valid_items]
        current_day = date.today()
        recent_90 = [item for item in valid_items if _within_days(item.publish_date, 90, current_day)]
        recent_30 = [item for item in valid_items if _within_days(item.publish_date, 30, current_day)]
        return (
            {
                "source_total_count": raw_total,
                "current_page_count": current_page_count,
                "parsed_list_count": len(items),
                "valid_count": len(valid_items),
                "haimen_confirmed_count": haimen_confirmed_count,
                "recent_90_days_count": len(recent_90),
                "recent_30_days_count": len(recent_30),
                "latest_date": valid_items[0].publish_date if valid_items else UNKNOWN,
                "filtered_out_count": sum(filtered_reasons.values()),
                "filtered_out_reasons": filtered_reasons,
                "all_pages_loaded": raw_total > 0 and len(items) == raw_total,
                "collection_method": "requests_api",
                "errors": self.errors,
            },
            records,
        )

    def fetch_detail(self, item: PlanningSearchItem, use_ocr: bool = True) -> PlanningConstructionPermitRecord:
        company_name, project_name = parse_title_entities(item.title)
        record = PlanningConstructionPermitRecord(
            title=item.title,
            publish_date=item.publish_date,
            publisher=item.publisher,
            detail_url=item.detail_url,
            company_name=company_name,
            construction_unit=company_name,
            project_name=project_name,
            source_url=item.detail_url,
            category=item.category,
        )
        self._wait_for_rate_limit()
        try:
            response = self.session.get(
                item.detail_url,
                headers={"User-Agent": self.user_agent, "Referer": self.index_url},
                timeout=self.timeout_seconds,
            )
            self._last_request_at = time.monotonic()
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
        except requests.RequestException as exc:
            self.errors.append(f"详情请求失败 url={item.detail_url}: {exc}")
            confirmed, confidence, reason = confirm_haimen(item, SEARCH_AREA_CODE)
            record.haimen_confidence = confidence if confirmed else 0
            record.haimen_reason = reason
            return record

        parser = _DetailPageParser(item.detail_url)
        parser.feed(response.text)
        record.detail_loaded = True
        record.image_urls = parser.image_urls
        record.publish_date = parse_date(parser.meta.get("pubdate", "")) or item.publish_date
        source_match = re.search(r"来源\s*[：:]\s*([^\s<]+)", html_to_text(response.text))
        if source_match:
            record.publisher = normalize_space(source_match.group(1))

        if use_ocr and self.enable_ocr and record.image_urls:
            ocr_text = self._ocr_image(record.image_urls[0], item.detail_url)
            if ocr_text:
                record.ocr_used = True
                fields = parse_ocr_fields(ocr_text)
                ocr_unit = fields.get("construction_unit", "")
                if plausible_organization(ocr_unit) and record.company_name == UNKNOWN:
                    record.construction_unit = ocr_unit
                    record.company_name = ocr_unit
                elif record.company_name != UNKNOWN:
                    record.construction_unit = record.company_name
                ocr_address = fields.get("project_address", "")
                if plausible_address(ocr_address):
                    record.project_address = ocr_address
                record.permit_number = normalize_permit_number(fields.get("permit_number", ""))
                issue_date = parse_date(fields.get("issue_date", ""))
                if issue_date:
                    record.issue_date = issue_date
                ocr_authority = fields.get("issuing_authority", "")
                if plausible_issuing_authority(ocr_authority):
                    record.issuing_authority = ocr_authority
                record.raw["ocr_text"] = ocr_text

        confirmed, confidence, reason = confirm_haimen(
            item,
            SEARCH_AREA_CODE,
            project_address=record.project_address,
            issuing_authority=record.issuing_authority,
        )
        record.haimen_confidence = confidence if confirmed else 0
        record.haimen_reason = reason
        record.raw["detail_meta"] = parser.meta
        return record

    def validate(self, detail_limit: int = 10, today: date | None = None) -> dict[str, Any]:
        raw_total, current_page_count, items = self.collect_all_search_items()
        valid_items, haimen_confirmed_count, filtered_reasons = filter_planning_construction_items(items)
        current_day = today or date.today()
        recent_90 = [item for item in valid_items if _within_days(item.publish_date, 90, current_day)]
        recent_30 = [item for item in valid_items if _within_days(item.publish_date, 30, current_day)]

        detail_items = valid_items[: max(10, detail_limit)]
        detail_records = [self.fetch_detail(item, use_ocr=True) for item in detail_items]
        detail_success_count = sum(record.detail_loaded for record in detail_records)

        return {
            "request_url": SEARCH_API_URL,
            "request_method": "GET",
            "request_params": self.build_request_params(1),
            "request_page_size": "服务器固定10条，请求中无pageSize参数",
            "cookie_required": True,
            "cookie_handling": "检索页初始化后仅保存在进程内存，不落盘、不输出",
            "response_encoding": "UTF-8",
            "raw_total_count": raw_total,
            "current_page_count": current_page_count,
            "parsed_list_count": len(items),
            "detail_attempted_count": len(detail_records),
            "detail_success_count": detail_success_count,
            "haimen_confirmed_count": haimen_confirmed_count,
            "planning_construction_count": len(valid_items),
            "recent_90_days_count": len(recent_90),
            "recent_30_days_count": len(recent_30),
            "latest_date": valid_items[0].publish_date if valid_items else UNKNOWN,
            "filtered_out_count": sum(filtered_reasons.values()),
            "filtered_out_reasons": filtered_reasons,
            "inserted_count": 0,
            "deepseek_called": False,
            "baseline_matches": {
                "平谦现代产业园": any("平谦现代产业园" in item.title and item.publish_date == "2026-07-21" for item in valid_items),
                "冬泽特医食品生产基地": any("冬泽特医食品生产基地" in item.title and item.publish_date == "2026-07-17" for item in valid_items),
                "立新小区九期": any("立新小区九期" in item.title and item.publish_date == "2026-07-15" for item in valid_items),
            },
            "examples": [record.to_dict() for record in detail_records[:10]],
            "recent_30_days_results": [
                {
                    "标题": item.title,
                    "发布日期": item.publish_date,
                    "发布部门": item.publisher,
                    "详情页链接": item.detail_url,
                    "areaCode": SEARCH_AREA_CODE,
                    "海门认定原因": "搜索请求areaCode=320684，接口结果已限定海门",
                }
                for item in recent_30
            ],
            "errors": self.errors,
        }

    def _ocr_image(self, image_url: str, referer: str) -> str:
        self._wait_for_rate_limit()
        try:
            response = self.session.get(
                image_url,
                headers={"User-Agent": self.user_agent, "Referer": referer},
                timeout=self.timeout_seconds,
            )
            self._last_request_at = time.monotonic()
            response.raise_for_status()
        except requests.RequestException as exc:
            self.errors.append(f"详情图片请求失败 url={image_url}: {exc}")
            return ""
        try:
            if self._ocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR

                self._ocr_engine = RapidOCR()
            rows, _ = self._ocr_engine(response.content)
            return "\n".join(str(row[1]) for row in (rows or []))
        except Exception as exc:
            # Third-party image decoders can reject exceptionally large
            # government scans. Keep Pillow's safety limit and skip OCR for
            # that one record instead of aborting the complete import.
            self.errors.append(
                f"本地OCR失败 url={image_url}: {type(exc).__name__}: {exc}"
            )
            return ""

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = self.request_interval_seconds - elapsed
        if self._last_request_at and wait_seconds > 0:
            time.sleep(wait_seconds)


def _within_days(value: str, max_days: int, today: date) -> bool:
    event_day = parse_date_object(value)
    if not event_day:
        return False
    age = (today - event_day).days
    return 0 <= age <= max_days
