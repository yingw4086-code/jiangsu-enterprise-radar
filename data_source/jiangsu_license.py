from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests
from app.parsers.html_links import html_to_text, normalize_space
from data_source.base import (
    BaseCrawler,
    FetchResult,
    LinkCandidate,
    OpportunityRecord,
    UNKNOWN,
    calculate_fresh_score,
    extract_amount,
    extract_location,
    infer_industry,
    parse_amount_to_yuan,
    parse_date,
    parse_date_object,
)


PERMIT_TYPES = [
    "建设工程施工许可证",
    "建设工程规划许可证",
    "建设用地规划许可证",
]

LICENSE_FIELD_ALIASES = {
    "company_name": ["行政相对人名称", "建设单位名称", "建设单位", "项目单位", "企业名称", "单位名称"],
    "project_name": ["建设项目名称", "项目名称", "工程名称", "标题"],
    "project_address": ["项目地址", "建设地址", "建设地点", "建设位置", "项目地点"],
    "construction_unit": ["建设单位名称", "建设单位", "行政相对人名称", "项目单位"],
    "permit_type": ["许可证书名称", "许可事项名称", "许可事项", "事项名称", "分类"],
    "permit_date": ["许可决定日期", "发证日期", "决定日期", "许可日期", "颁发日期"],
    "permit_number": ["许可证书编号", "许可证编号", "许可编号", "证书编号", "行政许可决定文书号", "文号"],
    "investment_amount": ["项目总投资", "计划总投资", "总投资", "投资金额"],
    "project_scale": ["项目规模", "建设规模", "许可面积", "用地面积", "建筑面积"],
    "update_time": ["发布时间", "更新时间", "发布日期"],
}

STAGE_BY_PERMIT_TYPE = {
    "建设用地规划许可证": "拿地规划",
    "建设工程规划许可证": "建设审批",
    "建设工程施工许可证": "开工建设",
}

SCORE_BY_PERMIT_TYPE = {
    "建设用地规划许可证": 25,
    "建设工程规划许可证": 30,
    "建设工程施工许可证": 40,
}


@dataclass
class LicenseInterfaceResult:
    keyword: str
    request_method: str
    interface_url: str
    request_params: dict[str, str]
    status_code: int | None = None
    content_type: str = ""
    response_encoding: str = ""
    final_url: str = ""
    response_format: str = "UNKNOWN"
    result_count: int = 0
    parsed_count: int = 0
    candidates: list[LinkCandidate] = field(default_factory=list)
    all_candidates: list[LinkCandidate] = field(default_factory=list, repr=False)
    raw_html: str = field(default="", repr=False)
    sample_data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "关键词": self.keyword,
            "请求方式": self.request_method,
            "接口": self.interface_url,
            "请求参数": self.request_params,
            "返回状态码": self.status_code,
            "返回格式": self.response_format,
            "Content-Type": self.content_type,
            "response.encoding": self.response_encoding,
            "最终URL": self.final_url,
            "HTML字符数": len(self.raw_html),
            "返回数据数量": self.result_count,
            "成功解析数量": self.parsed_count,
            "示例数据": self.sample_data,
            "错误": self.error,
        }


@dataclass
class ConstructionPermitRecord:
    permit_type: str = UNKNOWN
    company_name: str = UNKNOWN
    project_name: str = UNKNOWN
    project_address: str = UNKNOWN
    construction_unit: str = UNKNOWN
    permit_date: str = UNKNOWN
    permit_number: str = UNKNOWN
    project_scale: str = UNKNOWN
    investment_amount: str = UNKNOWN
    industry: str = UNKNOWN
    source_url: str = ""
    update_time: str = UNKNOWN
    project_stage: str = UNKNOWN
    loan_opportunity_score: int = 0
    customer_level: str = "C"
    fresh_score: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def enrich(self) -> "ConstructionPermitRecord":
        event_time = self.permit_date if self.permit_date != UNKNOWN else self.update_time
        self.fresh_score = calculate_fresh_score(event_time)
        self.project_stage = stage_for_permit(self.permit_type)
        self.loan_opportunity_score = calculate_loan_opportunity_score(
            permit_type=self.permit_type,
            investment_amount=self.investment_amount,
            publish_time=self.permit_date or self.update_time,
        )
        self.customer_level = level_from_license_score(self.loan_opportunity_score)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "许可证类型": self.permit_type,
            "企业名称": self.company_name,
            "项目名称": self.project_name,
            "项目地址": self.project_address,
            "建设单位": self.construction_unit,
            "发证日期": self.permit_date,
            "许可证编号": self.permit_number,
            "项目规模": self.project_scale,
            "投资金额": self.investment_amount,
            "所属行业": self.industry,
            "来源网址": self.source_url,
            "更新时间": self.update_time,
            "项目阶段": self.project_stage,
            "loan_opportunity_score": self.loan_opportunity_score,
            "客户机会等级": self.customer_level,
            "fresh_score": self.fresh_score,
            "raw": self.raw,
        }

    def to_unified_dict(self) -> dict[str, Any]:
        return {
            "企业名称": self.company_name,
            "项目名称": self.project_name,
            "许可证类型": self.permit_type,
            "日期": self.permit_date if self.permit_date != UNKNOWN else self.update_time,
            "地址": self.project_address,
            "来源网址": self.source_url,
            "fresh_score": self.fresh_score,
        }

    def to_opportunity_record(self) -> OpportunityRecord:
        record = OpportunityRecord(
            enterprise_name=self.company_name,
            project_name=self.project_name,
            source="江苏自然资源建设项目许可证",
            event_time=self.permit_date if self.permit_date != UNKNOWN else self.update_time,
            amount=self.investment_amount,
            industry=self.industry,
            region="南通市海门区",
            opportunity_level=self.customer_level,
            recommended_loan_product=recommended_products_for_license(self),
            approval_type=self.permit_type,
            stage=self.project_stage,
            source_url=self.source_url,
            source_title=self.raw.get("source_title", ""),
            publish_time=self.permit_date,
            update_time=self.update_time,
            fresh_score=self.fresh_score,
            opportunity_score=float(self.loan_opportunity_score),
            land_area=self.project_scale,
            construction_location=self.project_address,
            manager_view={
                "是否值得拜访": "是" if self.customer_level in {"A", "B"} else "建议观察",
                "预计融资需求": estimate_license_financing_need(self),
                "推荐银行产品": recommended_products_for_license(self).split("、"),
                "拜访话术": build_license_marketing_script(self),
                "原因": f"{self.permit_type}阶段，贷款机会评分{self.loan_opportunity_score}分。",
            },
            raw={**self.raw, "license_record": self.to_dict()},
        )
        return record


class JiangsuLicenseCrawler(BaseCrawler):
    """建设项目许可证专项采集器."""

    source_name = "江苏自然资源建设项目许可证"
    source_type = "建设项目许可证"
    homepage_url = "https://zrzy.jiangsu.gov.cn/"
    search_page_url = "https://zrzy.jiangsu.gov.cn/gtxxgk/nrglIndex.action?classID=8a908254409a391f01409a4b28500008"
    search_url = "https://zrzy.jiangsu.gov.cn/gtxxgk/nrglIndex.action"
    search_catalog_id = "2c90825471c8dd7a0171c90aec380001"
    form_encoding = "gb18030"
    permit_keywords = PERMIT_TYPES
    browser_user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )

    def __init__(
        self,
        max_items: int = 80,
        timeout_seconds: int = 12,
        verify_ssl: bool = False,
        enable_provincial_search: bool = True,
        max_age_days: int = 30,
        request_interval_seconds: float = 1.2,
        max_pages: int = 3,
    ):
        super().__init__(max_items=max_items, timeout_seconds=timeout_seconds, verify_ssl=verify_ssl)
        self.enable_provincial_search = enable_provincial_search
        self.max_age_days = max_age_days
        self.request_interval_seconds = max(1.0, min(float(request_interval_seconds), 2.0)) if request_interval_seconds else 0.0
        self.max_pages = max(1, min(int(max_pages), 5))
        self.last_interface_results: list[LicenseInterfaceResult] = []
        self._last_response_content_type = ""
        self._last_response_encoding = ""
        self._search_session_ready = False
        self._search_session_attempted = False
        self._last_request_started_at = 0.0
        self.session = requests.Session()
        self.session.trust_env = False

    def crawl_licenses(self) -> list[ConstructionPermitRecord]:
        candidates = self.collect_license_candidates()
        records: list[ConstructionPermitRecord] = []
        for candidate in candidates:
            record = self.record_from_license_candidate(candidate)
            if not record:
                continue
            record.enrich()
            if not is_haimen_license_record(record):
                continue
            if not is_recent_license_record(record, max_age_days=self.max_age_days):
                continue
            records.append(record)
            if len(records) >= self.max_items:
                break
        return dedupe_license_records(records)

    def crawl(self) -> list[OpportunityRecord]:
        return [record.to_opportunity_record() for record in self.crawl_licenses()]

    def collect_license_candidates(self) -> list[LinkCandidate]:
        candidates: list[LinkCandidate] = []
        if self.enable_provincial_search:
            for keyword in self.permit_keywords:
                search_result = self.search_keyword(keyword)
                self.last_interface_results.append(search_result)
                candidates.extend(search_result.candidates)

        return self.filter_license_candidates(candidates)

    def search_keyword(self, keyword: str) -> LicenseInterfaceResult:
        self.ensure_search_session()
        params = self.build_search_params(keyword)
        query_url = f"{self.search_url}?{urllib.parse.urlencode(params)}"
        fetch_result = self.requests_fetch_text(
            query_url,
            method="GET",
            headers={"Referer": self.homepage_url},
            timeout_seconds=20,
        )
        content_type = self._last_response_content_type
        response_format = infer_response_format(fetch_result.text, content_type)
        all_candidates = self.extract_candidates(fetch_result.text, fetch_result.url) if fetch_result.ok else []
        candidates = parse_license_search_results(fetch_result.text, fetch_result.url) if fetch_result.ok else []
        filtered = self.filter_search_result_candidates(candidates, keyword)
        return LicenseInterfaceResult(
            keyword=keyword,
            request_method="GET",
            interface_url=self.search_url,
            request_params=params,
            status_code=fetch_result.status,
            content_type=content_type,
            response_encoding=self._last_response_encoding,
            final_url=fetch_result.url,
            response_format=response_format,
            result_count=len(filtered),
            candidates=filtered,
            all_candidates=all_candidates,
            raw_html=fetch_result.text,
            error=fetch_result.error,
        )

    def build_search_params(self, keyword: str) -> dict[str, str]:
        return {
            "catalogID": self.search_catalog_id,
            "type": "1",
            "title": keyword,
        }

    def build_request_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        request_headers = {
            "User-Agent": self.browser_user_agent,
            "Referer": self.homepage_url,
            "Accept": "text/html,application/xhtml+xml,application/xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if headers:
            request_headers.update(headers)
        return request_headers

    def ensure_search_session(self) -> bool:
        if self._search_session_attempted:
            return self._search_session_ready
        self._search_session_attempted = True
        try:
            self.wait_for_request_slot()
            response = self.session.get(
                self.homepage_url,
                headers=self.build_request_headers(),
                timeout=20,
                verify=self.verify_ssl,
            )
            self._search_session_ready = 200 <= response.status_code < 400
            if not self._search_session_ready:
                message = f"{self.source_name} 首页预访问 HTTP {response.status_code}: {self.homepage_url}"
                self.errors.append(message)
                if response.status_code == 403:
                    self.print_403_debug(response)
        except requests.RequestException as exc:
            self._search_session_ready = False
            self.errors.append(f"{self.source_name} 首页预访问失败: {self.homepage_url}; {exc}")
        return self._search_session_ready

    def wait_for_request_slot(self) -> None:
        if self.request_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_started_at
        remaining = self.request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_started_at = time.monotonic()

    def requests_fetch_text(
        self,
        url: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> FetchResult:
        request_headers = self.build_request_headers(headers)
        try:
            self.wait_for_request_slot()
            if data is not None:
                body = urllib.parse.urlencode(data, encoding=self.form_encoding).encode(self.form_encoding)
                request_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=GB18030"
            else:
                body = None
            if method.upper() == "POST":
                response = self.session.post(
                    url,
                    data=body,
                    headers=request_headers,
                    timeout=timeout_seconds or 20,
                    verify=self.verify_ssl,
                )
            else:
                response = self.session.get(
                    url,
                    headers=request_headers,
                    timeout=timeout_seconds or self.timeout_seconds,
                    verify=self.verify_ssl,
                )
            content_type = response.headers.get("Content-Type", "")
            self._last_response_content_type = content_type
            declared_encoding = response.encoding
            if not declared_encoding or declared_encoding.lower() in {"iso-8859-1", "ascii"}:
                response.encoding = response.apparent_encoding or "gb18030"
            self._last_response_encoding = response.encoding or ""
            ok = 200 <= response.status_code < 400
            error = "" if ok else f"{self.source_name} HTTP {response.status_code}: {response.url or url}"
            if error:
                self.errors.append(error)
            if response.status_code == 403:
                self.print_403_debug(response)
            return FetchResult(
                ok=ok,
                url=response.url or url,
                status=response.status_code,
                text=response.text,
                error=error,
            )
        except requests.RequestException as exc:
            self._last_response_content_type = ""
            self._last_response_encoding = ""
            message = f"{self.source_name} requests访问失败: {url}; {exc}"
            self.errors.append(message)
            return FetchResult(ok=False, url=url, error=message)

    @staticmethod
    def print_403_debug(response: requests.Response) -> None:
        print("HTTP 403 response.headers:")
        print(dict(response.headers))
        print("HTTP 403 response.text[:500]:")
        print((response.text or "")[:500])

    @staticmethod
    def save_debug_html(result: LicenseInterfaceResult, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.raw_html, encoding="gb18030", errors="replace")
        return output_path

    @staticmethod
    def diagnose_search_page(result: LicenseInterfaceResult) -> dict[str, Any]:
        html = result.raw_html or ""
        text = html_to_text(html)
        title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        page_title = normalize_space(title_match.group(1)) if title_match else ""
        total_match = re.search(r"共\s*(?:<[^>]+>\s*)*(\d+)\s*(?:<[^>]+>\s*)*条", html)
        no_data = any(marker in text for marker in ["暂无数据", "暂无相关数据", "没有找到", "无相关信息"])
        has_pagination = bool(
            re.search(r"(?i)pageform|pageNo|currentPage|下一页|末页|总页数", html)
        )
        lowered_title = page_title.lower()
        final_url = (result.final_url or "").lower()
        page_kind = "搜索结果页"
        if "登录" in page_title or "login" in final_url:
            page_kind = "登录页"
        elif result.status_code and result.status_code >= 400 or any(
            marker in lowered_title for marker in ["error", "forbidden", "not found"]
        ):
            page_kind = "错误页"
        elif "classid=" in final_url and "catalogid=" not in final_url:
            page_kind = "搜索首页"
        return {
            "关键词": result.keyword,
            "HTTP状态码": result.status_code,
            "response.encoding": result.response_encoding,
            "HTML字符数": len(html),
            "页面标题": page_title,
            "页面是否包含关键词": result.keyword in text,
            "页面是否包含暂无数据": no_data,
            "页面是否包含共X条": bool(total_match),
            "共X条": int(total_match.group(1)) if total_match else None,
            "是否存在结果列表": bool(result.candidates),
            "原始链接数量": len(result.all_candidates),
            "结果链接数量": len(result.candidates),
            "是否存在分页": has_pagination,
            "页面类型": page_kind,
            "最终URL": result.final_url,
        }

    def filter_search_result_candidates(self, candidates: list[LinkCandidate], keyword: str) -> list[LinkCandidate]:
        result: list[LinkCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            title = normalize_space(candidate.title)
            url = candidate.url.strip()
            if not title or not url or url in seen:
                continue
            combined = f"{title} {url}"
            if keyword not in combined and not any(permit_type in combined for permit_type in PERMIT_TYPES):
                continue
            seen.add(url)
            result.append(
                LinkCandidate(
                    title=title,
                    url=url,
                    date=candidate.date,
                    source_list_url=candidate.source_list_url,
                )
            )
        return sorted(result, key=lambda item: parse_date_object(item.date) or date.min, reverse=True)

    def build_parsing_test_report(
        self,
        min_items: int = 5,
    ) -> tuple[list[dict[str, Any]], list[ConstructionPermitRecord]]:
        reports: list[dict[str, Any]] = []
        records: list[ConstructionPermitRecord] = []
        seen_candidates: set[str] = set()
        for keyword in self.permit_keywords:
            result = self.search_keyword(keyword)
            keyword_records: list[ConstructionPermitRecord] = []
            for candidate in result.candidates:
                if candidate.url in seen_candidates:
                    continue
                seen_candidates.add(candidate.url)
                record = self.record_from_license_candidate(candidate)
                if not record:
                    continue
                record.enrich()
                keyword_records.append(record)
                records.append(record)
                if len(records) >= max(min_items * 2, min_items):
                    break
            result.parsed_count = len(keyword_records)
            if keyword_records:
                result.sample_data = keyword_records[0].to_unified_dict()
            elif result.candidates:
                candidate = result.candidates[0]
                result.sample_data = {
                    "标题": candidate.title,
                    "链接": candidate.url,
                    "日期": candidate.date,
                }
            reports.append(result.to_report_dict())
        return reports, dedupe_license_records(records)[: self.max_items]

    def build_interface_test_report(self) -> list[dict[str, Any]]:
        reports, _ = self.build_parsing_test_report(min_items=1)
        return reports

    def filter_license_candidates(self, candidates: list[LinkCandidate]) -> list[LinkCandidate]:
        result: list[LinkCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            title = normalize_space(candidate.title)
            if not title or candidate.url in seen:
                continue
            if not is_haimen_license_candidate(title, candidate.url):
                continue
            seen.add(candidate.url)
            result.append(
                LinkCandidate(
                    title=title,
                    url=candidate.url,
                    date=candidate.date,
                    source_list_url=candidate.source_list_url,
                )
            )
        return sorted(result, key=lambda item: parse_date_object(item.date) or date.min, reverse=True)

    def record_from_license_candidate(self, candidate: LinkCandidate) -> ConstructionPermitRecord | None:
        detail = self.requests_fetch_text(candidate.url)
        record = parse_license_detail_html(
            html=detail.text if detail.ok else "",
            title=candidate.title,
            source_url=candidate.url,
            candidate_date=candidate.date,
            raw={
                "source_title": candidate.title,
                "source_list_url": candidate.source_list_url,
                "detail_fetched": detail.ok,
                "detail_url": detail.url,
                "detail_error": detail.error,
            },
        )
        if detail.ok and not record:
            self.errors.append(
                f"解析阶段=详情页; URL={candidate.url}; HTTP={detail.status}; 未提取到目标许可证字段"
            )
        return record


class _LicenseDetailParser(HTMLParser):
    """Collect label/value pairs while preserving HTML table cell boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.definition_pairs: list[tuple[str, str]] = []
        self._row_cells: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._definition_tag = ""
        self._definition_parts: list[str] = []
        self._pending_definition_label = ""
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "tr":
            self._row_cells = []
        elif lowered in {"th", "td"}:
            self._cell_parts = []
        elif lowered in {"dt", "dd"}:
            self._definition_tag = lowered
            self._definition_parts = []
        elif lowered == "br":
            if self._cell_parts is not None:
                self._cell_parts.append(" ")
            if self._definition_tag:
                self._definition_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._definition_tag:
            self._definition_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if lowered in {"th", "td"} and self._cell_parts is not None:
            value = normalize_space(" ".join(self._cell_parts))
            if self._row_cells is None:
                self._row_cells = []
            self._row_cells.append(value)
            self._cell_parts = None
        elif lowered == "tr" and self._row_cells is not None:
            cells = [cell for cell in self._row_cells if cell]
            if cells:
                self.rows.append(cells)
            self._row_cells = None
        elif lowered == self._definition_tag:
            value = normalize_space(" ".join(self._definition_parts))
            if lowered == "dt":
                self._pending_definition_label = value
            elif lowered == "dd" and self._pending_definition_label and value:
                self.definition_pairs.append((self._pending_definition_label, value))
                self._pending_definition_label = ""
            self._definition_tag = ""
            self._definition_parts = []


class _LicenseSearchResultParser(HTMLParser):
    """Parse the real Jiangsu result row: td.nlist > a + span."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.items: list[LinkCandidate] = []
        self._in_result_cell = False
        self._in_anchor = False
        self._in_date = False
        self._href = ""
        self._title_attr = ""
        self._title_parts: list[str] = []
        self._date_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if lowered == "td" and "nlist" in attr_map.get("class", "").split():
            self._in_result_cell = True
            self._href = ""
            self._title_attr = ""
            self._title_parts = []
            self._date_parts = []
        elif self._in_result_cell and lowered == "a":
            self._in_anchor = True
            self._href = re.sub(r"\s+", "", attr_map.get("href", ""))
            self._title_attr = normalize_space(attr_map.get("title", ""))
        elif self._in_result_cell and lowered == "span":
            self._in_date = True

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._title_parts.append(data)
        elif self._in_date:
            self._date_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a":
            self._in_anchor = False
        elif lowered == "span":
            self._in_date = False
        elif lowered == "td" and self._in_result_cell:
            title = self._title_attr or normalize_space(" ".join(self._title_parts))
            event_date = parse_date(" ".join(self._date_parts))
            if title and self._href and "messageID=" in self._href:
                self.items.append(
                    LinkCandidate(
                        title=title,
                        url=urllib.parse.urljoin(self.base_url, self._href),
                        date=event_date,
                        source_list_url=self.base_url,
                    )
                )
            self._in_result_cell = False


def parse_license_search_results(html: str, base_url: str) -> list[LinkCandidate]:
    parser = _LicenseSearchResultParser(base_url)
    parser.feed(html or "")
    return parser.items


def extract_license_html_fields(html: str) -> dict[str, str]:
    if not html:
        return {}
    parser = _LicenseDetailParser()
    parser.feed(html)
    pairs = list(parser.definition_pairs)
    known_labels = [alias for aliases in LICENSE_FIELD_ALIASES.values() for alias in aliases]
    known_labels.sort(key=len, reverse=True)
    for row in parser.rows:
        for index, cell in enumerate(row[:-1]):
            label = normalize_license_label(cell)
            if any(label == known or known in label for known in known_labels):
                pairs.append((cell, row[index + 1]))
        for index in range(0, len(row) - 1, 2):
            pairs.append((row[index], row[index + 1]))
        for cell in row:
            inline = re.match(r"^\s*([^:：]{2,30})\s*[:：]\s*(.+?)\s*$", cell)
            if inline:
                pairs.append((inline.group(1), inline.group(2)))

    fields: dict[str, str] = {}
    for raw_label, raw_value in pairs:
        label = normalize_license_label(raw_label)
        value = clean_license_value(raw_value)
        if not label or not value:
            continue
        matched_label = next(
            (known for known in known_labels if label == known or known in label),
            "",
        )
        if matched_label and matched_label not in fields:
            fields[matched_label] = value
    return fields


def normalize_license_label(value: str) -> str:
    normalized = normalize_space(value)
    normalized = re.sub(r"[\s:：*＊]+", "", normalized)
    return normalized.strip("（）()[]【】")


def lookup_license_field(fields: dict[str, str], field_name: str, text: str = "") -> str:
    aliases = LICENSE_FIELD_ALIASES[field_name]
    for alias in aliases:
        value = fields.get(alias)
        if value:
            return value
    return extract_labeled_value(text, aliases)


def parse_license_detail_html(
    html: str,
    title: str,
    source_url: str,
    candidate_date: str = "",
    raw: dict[str, Any] | None = None,
) -> ConstructionPermitRecord | None:
    detail_text = html_to_text(html) if html else ""
    combined = f"{title}\n{detail_text}"
    fields = extract_license_html_fields(html)

    permit_name = lookup_license_field(fields, "permit_type", combined)
    permit_type = extract_permit_type(f"{permit_name} {combined}")
    if permit_type == UNKNOWN or not is_haimen_region(combined, source_url):
        return None

    update_value = lookup_license_field(fields, "update_time", combined)
    update_time = parse_date(update_value) or parse_date(candidate_date) or extract_update_time(combined) or UNKNOWN
    permit_value = lookup_license_field(fields, "permit_date", combined)
    permit_date = parse_date(permit_value) or parse_date(candidate_date) or parse_date(combined) or UNKNOWN

    company_name = lookup_license_field(fields, "company_name", combined)
    construction_unit = lookup_license_field(fields, "construction_unit", combined)
    if company_name == UNKNOWN and construction_unit != UNKNOWN:
        company_name = construction_unit
    if construction_unit == UNKNOWN and company_name != UNKNOWN:
        construction_unit = company_name

    project_name = lookup_license_field(fields, "project_name", combined)
    if project_name == UNKNOWN:
        project_name = extract_project_name_from_license(title, combined, company_name)

    project_address = lookup_license_field(fields, "project_address", combined)
    if project_address == UNKNOWN:
        project_address = extract_location(combined)

    project_scale = lookup_license_field(fields, "project_scale", combined)
    permit_number = lookup_license_field(fields, "permit_number", combined)
    investment = lookup_license_field(fields, "investment_amount", combined)
    if investment == UNKNOWN:
        investment = extract_amount(combined)

    return ConstructionPermitRecord(
        permit_type=permit_type,
        company_name=company_name,
        project_name=project_name,
        project_address=project_address,
        construction_unit=construction_unit,
        permit_date=permit_date,
        permit_number=permit_number,
        project_scale=project_scale,
        investment_amount=investment,
        industry=infer_industry(combined, UNKNOWN),
        source_url=source_url,
        update_time=update_time,
        raw={**(raw or {}), "html_fields": fields},
    )


def extract_permit_type(text: str) -> str:
    normalized = normalize_space(text)
    for permit_type in PERMIT_TYPES:
        if permit_type in normalized:
            return permit_type
    return UNKNOWN


def extract_labeled_value(text: str, labels: list[str]) -> str:
    normalized = normalize_space(text)
    next_labels = [
        "行政相对人名称",
        "行政相对人类别",
        "统一社会信用代码",
        "建设单位",
        "项目单位",
        "企业名称",
        "许可证书名称",
        "许可事项名称",
        "许可事项",
        "许可证编号",
        "许可证书编号",
        "许可编号",
        "证书编号",
        "行政许可决定文书号",
        "项目名称",
        "项目地址",
        "建设地址",
        "建设地点",
        "建设位置",
        "许可内容",
        "许可面积",
        "用地面积",
        "建筑面积",
        "项目规模",
        "建设规模",
        "项目总投资",
        "计划总投资",
        "总投资",
        "投资金额",
        "许可决定日期",
        "发证日期",
        "有效期",
        "许可机关",
        "数据来源",
        "发布时间",
        "更新时间",
    ]
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]?\s*(.+?)(?=\s+(?:{'|'.join(map(re.escape, next_labels))})\s*[:：]?|$)"
        match = re.search(pattern, normalized)
        if match:
            value = clean_license_value(match.group(1))
            if value:
                return value
    return UNKNOWN


def extract_update_time(text: str) -> str:
    value = extract_labeled_value(text, ["发布时间", "更新时间", "发布日期"])
    if value != UNKNOWN:
        return parse_date(value) or value
    return parse_date(text) or UNKNOWN


def extract_project_name_from_license(title: str, text: str, company_name: str) -> str:
    value = extract_labeled_value(text, ["项目名称", "工程名称"])
    if value != UNKNOWN:
        return value
    title_text = normalize_space(title)
    title_text = re.sub(r"^关于(?:同意|核发|准予|批准)?", "", title_text)
    title_text = re.sub(r"的行政许可.*$", "", title_text)
    if company_name != UNKNOWN:
        title_text = title_text.replace(company_name, "")
    title_text = clean_license_value(title_text)
    return title_text if title_text else UNKNOWN


def calculate_loan_opportunity_score(permit_type: str, investment_amount: str, publish_time: str) -> int:
    score = SCORE_BY_PERMIT_TYPE.get(permit_type, 0)
    amount = parse_amount_to_yuan(investment_amount)
    if amount > 100_000_000:
        score += 20
    elif 50_000_000 <= amount <= 100_000_000:
        score += 10

    publish_day = parse_date_object(publish_time)
    if publish_day:
        days = (date.today() - publish_day).days
        if days <= 30:
            score += 20
        elif days <= 90:
            score += 10
    return score


def level_from_license_score(score: int) -> str:
    if score >= 70:
        return "A"
    if score >= 45:
        return "B"
    return "C"


def stage_for_permit(permit_type: str) -> str:
    return STAGE_BY_PERMIT_TYPE.get(permit_type, UNKNOWN)


def recommended_products_for_license(record: ConstructionPermitRecord) -> str:
    products = ["项目贷款", "固定资产贷款"]
    if record.permit_type == "建设工程施工许可证":
        products.append("工程进度款融资")
    if parse_amount_to_yuan(record.investment_amount) >= 50_000_000:
        products.append("设备融资")
    products.append("开户结算")
    return "、".join(dict.fromkeys(products))


def estimate_license_financing_need(record: ConstructionPermitRecord) -> str:
    if record.permit_type == "建设工程施工许可证":
        return "项目进入开工建设阶段，预计存在工程款、设备采购和流动资金需求"
    if record.permit_type == "建设工程规划许可证":
        return "项目进入建设审批阶段，适合提前对接固定资产贷款方案"
    if record.permit_type == "建设用地规划许可证":
        return "项目处于拿地规划阶段，适合提前建立授信和结算关系"
    return "需进一步核实融资需求"


def build_license_marketing_script(record: ConstructionPermitRecord) -> str:
    company = record.company_name if record.company_name != UNKNOWN else "该建设单位"
    return (
        f"建议联系{company}，围绕{record.permit_type}后的项目资金安排，"
        "了解资本金到位、施工计划、设备采购和结算账户安排。"
    )


def infer_response_format(text: str, content_type: str = "") -> str:
    lowered = (content_type or "").lower()
    stripped = (text or "").lstrip()
    if "json" in lowered:
        return "JSON"
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return "JSON"
        except json.JSONDecodeError:
            pass
    if "<html" in stripped.lower() or "<!doctype" in stripped.lower():
        return "HTML"
    if "<" in stripped and ">" in stripped:
        return "HTML"
    return "TEXT"


def is_haimen_license_candidate(title: str, url: str) -> bool:
    combined = f"{title} {url}"
    return any(keyword in combined for keyword in PERMIT_TYPES)


def is_haimen_region(text: str, url: str = "") -> bool:
    combined = f"{text} {url}"
    if "hmsgtj" in combined or "haimen.gov.cn" in combined:
        return True
    return ("南通" in combined or "南通市" in combined) and "海门" in combined


def is_haimen_license_record(record: ConstructionPermitRecord) -> bool:
    combined = " ".join(
        [
            record.company_name,
            record.construction_unit,
            record.project_name,
            record.project_address,
            str(record.raw.get("source_title", "")),
        ]
    )
    return is_haimen_region(combined, record.source_url)


def dedupe_license_records(records: list[ConstructionPermitRecord]) -> list[ConstructionPermitRecord]:
    result: list[ConstructionPermitRecord] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        company = normalize_dedupe_value(record.company_name)
        permit_number = normalize_dedupe_value(record.permit_number)
        if company and permit_number:
            key = ("company_permit", company, permit_number)
        else:
            key = (
                "fallback",
                normalize_dedupe_value(record.source_url),
                company,
                normalize_dedupe_value(record.project_name),
                normalize_dedupe_value(record.permit_type),
            )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return sorted(
        result,
        key=lambda item: (
            item.loan_opportunity_score,
            parse_date_object(item.permit_date) or date.min,
            item.company_name,
        ),
        reverse=True,
    )


def normalize_dedupe_value(value: str) -> str:
    normalized = normalize_space(str(value or "")).lower()
    return "" if normalized in {"", UNKNOWN.lower()} else normalized


def is_recent_license_record(
    record: ConstructionPermitRecord,
    max_age_days: int = 30,
    today: date | None = None,
) -> bool:
    event_time = record.permit_date if record.permit_date != UNKNOWN else record.update_time
    event_day = parse_date_object(event_time)
    if not event_day:
        return False
    days = ((today or date.today()) - event_day).days
    return 0 <= days <= max_age_days


def clean_license_value(value: str) -> str:
    cleaned = normalize_space(value)
    cleaned = cleaned.strip(" ：:，,。；;、\t\r\n")
    cleaned = re.sub(r"^(?:关于|同意|批准|准予|核准)", "", cleaned).strip(" ：:，,。；;、\t\r\n")
    cleaned = re.split(r"\s+(?:字体|来源|发布时间|累计次数|返回)$", cleaned, maxsplit=1)[0]
    return cleaned[:240]
