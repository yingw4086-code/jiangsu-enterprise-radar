from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.parsers.html_links import extract_links, html_to_text, normalize_space


UNKNOWN = "未披露"
DEFAULT_REGION = "南通市海门区"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class FetchResult:
    ok: bool
    url: str
    status: int | None = None
    text: str = ""
    body: bytes = b""
    error: str = ""


@dataclass
class LinkCandidate:
    title: str
    url: str
    date: str = ""
    source_list_url: str = ""


@dataclass
class OpportunityRecord:
    enterprise_name: str = UNKNOWN
    project_name: str = UNKNOWN
    source: str = UNKNOWN
    event_time: str = UNKNOWN
    amount: str = UNKNOWN
    industry: str = UNKNOWN
    region: str = DEFAULT_REGION
    opportunity_level: str = "C"
    recommended_loan_product: str = UNKNOWN
    approval_type: str = UNKNOWN
    stage: str = UNKNOWN
    source_url: str = ""
    source_title: str = ""
    publish_time: str = UNKNOWN
    update_time: str = UNKNOWN
    fresh_score: int = 0
    opportunity_score: float = 0.0
    land_area: str = UNKNOWN
    construction_location: str = UNKNOWN
    manager_view: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def enrich(self) -> "OpportunityRecord":
        self.publish_time = self.publish_time if self.publish_time != UNKNOWN else self.event_time
        self.update_time = self.update_time if self.update_time != UNKNOWN else self.event_time
        self.fresh_score = calculate_fresh_score(self.event_time)
        self.opportunity_score = calculate_opportunity_score(
            amount_text=self.amount,
            event_time=self.event_time,
            stage=self.stage,
            industry=self.industry,
        )
        self.opportunity_level = level_from_score(self.opportunity_score)
        self.recommended_loan_product = recommended_products_for(
            stage=self.stage,
            industry=self.industry,
            amount_text=self.amount,
            source=self.source,
        )
        self.manager_view = build_manager_view(self)
        return self

    def to_unified_dict(self) -> dict[str, Any]:
        return {
            "企业名称": self.enterprise_name,
            "项目名称": self.project_name,
            "来源": self.source,
            "时间": self.event_time,
            "金额": self.amount,
            "行业": self.industry,
            "地区": self.region,
            "机会等级": self.opportunity_level,
            "推荐贷款产品": self.recommended_loan_product,
            "publish_time": self.publish_time,
            "update_time": self.update_time,
            "fresh_score": self.fresh_score,
            "opportunity_score": round(self.opportunity_score, 2),
            "审批类型": self.approval_type,
            "项目阶段": self.stage,
            "土地面积": self.land_area,
            "建设地点": self.construction_location,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "客户经理视角": self.manager_view,
            "raw": self.raw,
        }

    def to_dashboard_item(self, index: int) -> dict[str, Any]:
        products = split_products(self.recommended_loan_product)
        has_need = self.opportunity_level in {"A", "B"}
        return {
            "index": index,
            "enterprise_name": self.enterprise_name,
            "project_name": self.project_name,
            "industry": self.industry,
            "investment_amount": self.amount,
            "project_address": self.construction_location
            if self.construction_location != UNKNOWN
            else self.region,
            "date": self.event_time,
            "data_source": self.source,
            "approval_item": self.approval_type if self.approval_type != UNKNOWN else self.stage,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "publish_time": self.publish_time,
            "update_time": self.update_time,
            "fresh_score": self.fresh_score,
            "opportunity_score": round(self.opportunity_score, 2),
            "ai_analysis": {
                "has_financing_need": has_need,
                "expected_loan_types": products,
                "customer_value_level": self.opportunity_level,
                "marketing_advice": self.manager_view.get("拜访话术", UNKNOWN),
                "reason": self.manager_view.get("原因", build_reason(self)),
                "confidence": round(max(0.35, min(0.95, self.opportunity_score / 100)), 2),
                "是否值得拜访": self.manager_view.get("是否值得拜访", UNKNOWN),
                "预计融资需求": self.manager_view.get("预计融资需求", UNKNOWN),
                "推荐银行产品": products,
                "拜访话术": self.manager_view.get("拜访话术", UNKNOWN),
            },
        }


class BaseCrawler:
    source_name = "未命名数据源"
    source_type = "通用"
    keywords: list[str] = []
    match_keywords: list[str] = []
    start_urls: list[str] = []
    default_stage = UNKNOWN
    default_industry = UNKNOWN
    default_region = DEFAULT_REGION
    form_encoding = "utf-8"
    detail_fetch_enabled = True

    def __init__(
        self,
        max_items: int = 80,
        timeout_seconds: int = 20,
        verify_ssl: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.max_items = max_items
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent
        self.errors: list[str] = []

    def crawl(self) -> list[OpportunityRecord]:
        records = []
        for candidate in self.collect_candidates():
            record = self.record_from_candidate(candidate)
            if record:
                records.append(record.enrich())
            if len(records) >= self.max_items:
                break
        return dedupe_records(records)

    def collect_candidates(self) -> list[LinkCandidate]:
        candidates: list[LinkCandidate] = []
        for url in self.start_urls:
            result = self.safe_fetch_text(url)
            if not result.ok:
                continue
            candidates.extend(self.extract_candidates(result.text, url))
        return self.filter_candidates(candidates)

    def record_from_candidate(self, candidate: LinkCandidate) -> OpportunityRecord | None:
        if not self.detail_fetch_enabled:
            return self.record_from_text(candidate, candidate.title)
        detail = self.safe_fetch_text(candidate.url)
        detail_text = html_to_text(detail.text) if detail.ok and detail.text else candidate.title
        combined = f"{candidate.title}\n{detail_text}"
        return self.record_from_text(candidate, combined)

    def record_from_text(self, candidate: LinkCandidate, combined: str) -> OpportunityRecord | None:
        if not is_haimen_related(combined) and not is_haimen_related(candidate.url):
            return None
        event_time = parse_date(combined) or candidate.date or UNKNOWN
        amount = extract_amount(combined)
        stage = infer_stage(combined, self.default_stage)
        industry = infer_industry(combined, self.default_industry)
        return OpportunityRecord(
            enterprise_name=extract_enterprise_name(combined),
            project_name=extract_project_name(candidate.title, combined),
            source=self.source_name,
            event_time=event_time,
            amount=amount,
            industry=industry,
            region=extract_region(combined, self.default_region),
            approval_type=extract_approval_type(combined, self.default_stage),
            stage=stage,
            source_url=candidate.url,
            source_title=candidate.title,
            publish_time=event_time,
            update_time=event_time,
            land_area=extract_land_area(combined),
            construction_location=extract_location(combined),
            raw={
                "crawler": self.__class__.__name__,
                "source_type": self.source_type,
                "source_list_url": candidate.source_list_url,
            },
        )

    def extract_candidates(self, html: str, base_url: str) -> list[LinkCandidate]:
        return [
            LinkCandidate(
                title=item.get("title", ""),
                url=item.get("url", ""),
                date=item.get("date", ""),
                source_list_url=base_url,
            )
            for item in extract_links(html, base_url)
        ]

    def filter_candidates(self, candidates: list[LinkCandidate]) -> list[LinkCandidate]:
        result: list[LinkCandidate] = []
        seen: set[str] = set()
        for item in candidates:
            title = normalize_space(item.title)
            url = item.url.strip()
            if not title or not url or url in seen:
                continue
            combined = f"{title} {url}"
            active_keywords = self.match_keywords or self.keywords
            if active_keywords and not any(keyword in combined for keyword in active_keywords):
                continue
            if not is_haimen_related(combined):
                continue
            seen.add(url)
            result.append(LinkCandidate(title=title, url=url, date=item.date, source_list_url=item.source_list_url))
        return sort_candidates(result)[: self.max_items * 3]

    def safe_fetch_text(
        self,
        url: str,
        data: dict[str, str] | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        try:
            return self.fetch_text(url=url, data=data, method=method, headers=headers)
        except urllib.error.HTTPError as exc:
            message = f"{self.source_name} HTTP {exc.code}: {url}"
            self.errors.append(message)
            return FetchResult(ok=False, url=url, status=exc.code, error=message)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            message = f"{self.source_name} 访问失败: {url}; {exc}"
            self.errors.append(message)
            return FetchResult(ok=False, url=url, error=message)

    def safe_fetch_bytes(self, url: str, headers: dict[str, str] | None = None) -> FetchResult:
        try:
            return self.fetch_bytes(url=url, headers=headers)
        except urllib.error.HTTPError as exc:
            message = f"{self.source_name} HTTP {exc.code}: {url}"
            self.errors.append(message)
            return FetchResult(ok=False, url=url, status=exc.code, error=message)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            message = f"{self.source_name} 附件下载失败: {url}; {exc}"
            self.errors.append(message)
            return FetchResult(ok=False, url=url, error=message)

    def fetch_text(
        self,
        url: str,
        data: dict[str, str] | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        encoded_data = None
        request_method = method or "GET"
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if headers:
            request_headers.update(headers)
        if data is not None:
            encoded_data = urllib.parse.urlencode(data, encoding=self.form_encoding).encode(self.form_encoding)
            request_method = method or "POST"
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        request = urllib.request.Request(
            url,
            data=encoded_data,
            headers=request_headers,
            method=request_method,
        )
        context = None if self.verify_ssl else ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
            body = response.read()
            charset = response.headers.get_content_charset()
            final_url = response.geturl()
            status = getattr(response, "status", None)
        return FetchResult(ok=True, url=final_url or url, status=status, text=decode_bytes(body, charset))

    def fetch_bytes(self, url: str, headers: dict[str, str] | None = None) -> FetchResult:
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, headers=request_headers, method="GET")
        context = None if self.verify_ssl else ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
            body = response.read()
            final_url = response.geturl()
            status = getattr(response, "status", None)
        return FetchResult(ok=True, url=final_url or url, status=status, body=body)


def decode_bytes(body: bytes, charset: str | None = None) -> str:
    encodings: list[str | None] = []
    if charset and "," in charset:
        encodings.extend(part.strip() for part in charset.split(",") if part.strip())
    else:
        encodings.append(charset)
    encodings.extend(["utf-8-sig", "utf-8", "gb18030", "gbk"])
    for encoding in encodings:
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def is_haimen_related(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in ["海门", "haimen", "南通市海门区", "南通海门"])


def sort_candidates(candidates: list[LinkCandidate]) -> list[LinkCandidate]:
    return sorted(candidates, key=lambda item: parse_date_object(item.date) or date.min, reverse=True)


def dedupe_records(records: list[OpportunityRecord]) -> list[OpportunityRecord]:
    result: list[OpportunityRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (
            record.source_url.strip() or record.source_title.strip(),
            normalize_key(record.enterprise_name),
            normalize_key(record.project_name),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return sorted(
        result,
        key=lambda item: (
            item.opportunity_score,
            parse_date_object(item.event_time) or date.min,
            parse_amount_to_yuan(item.amount),
        ),
        reverse=True,
    )


def parse_date(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def parse_date_object(value: str) -> date | None:
    parsed = parse_date(value) or value
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(parsed[:19], fmt).date()
        except ValueError:
            continue
    return None


def calculate_fresh_score(event_time: str, today: date | None = None) -> int:
    event_day = parse_date_object(event_time)
    if not event_day:
        return 0
    days = ((today or date.today()) - event_day).days
    if days < 0:
        return 80
    if days <= 7:
        return 100
    if days <= 30:
        return 80
    if days <= 90:
        return 60
    if days <= 180:
        return 40
    return 20


def calculate_opportunity_score(amount_text: str, event_time: str, stage: str, industry: str) -> float:
    return (
        amount_score(amount_text) * 0.30
        + calculate_fresh_score(event_time) * 0.25
        + stage_score(stage) * 0.25
        + industry_score(industry) * 0.20
    )


def amount_score(amount_text: str) -> int:
    amount = parse_amount_to_yuan(amount_text)
    if amount <= 0:
        return 35
    if amount >= 500_000_000:
        return 100
    if amount >= 100_000_000:
        return 85
    if amount >= 50_000_000:
        return 70
    if amount >= 10_000_000:
        return 50
    return 30


def stage_score(stage: str) -> int:
    text = stage or ""
    if any(keyword in text for keyword in ["施工许可证", "开工", "设备采购", "建设工程"]):
        return 100
    if any(keyword in text for keyword in ["土地", "规划许可证", "用地审批", "环评", "环境影响"]):
        return 80
    if any(keyword in text for keyword in ["投资备案", "项目备案", "项目规划", "备案"]):
        return 60
    if any(keyword in text for keyword in ["中标", "招标", "公共资源交易"]):
        return 70
    return 45


def industry_score(industry: str) -> int:
    text = industry or ""
    high_value = ["新能源", "电子", "半导体", "智能制造", "高端装备", "新材料", "生物医药"]
    medium_value = ["制造", "设备制造", "装备制造", "电气", "纺织", "机械", "汽车零部件"]
    if any(keyword in text for keyword in high_value):
        return 100
    if any(keyword in text for keyword in medium_value):
        return 80
    if text and text != UNKNOWN:
        return 60
    return 45


def level_from_score(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    return "C"


def parse_amount_to_yuan(value: str) -> float:
    if not value or value == UNKNOWN:
        return 0.0
    text = str(value).replace(",", "").replace("，", "")
    amounts: list[float] = []
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(亿元|亿|万元|万|元)", text):
        amount = float(number)
        if unit in {"亿元", "亿"}:
            amount *= 100_000_000
        elif unit in {"万元", "万"}:
            amount *= 10_000
        amounts.append(amount)
    return max(amounts) if amounts else 0.0


def format_amount_yuan(value: float) -> str:
    if value <= 0:
        return UNKNOWN
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿元"
    if value >= 10_000:
        return f"{value / 10_000:.0f}万元"
    return f"{value:.0f}元"


def extract_amount(text: str) -> str:
    if not text:
        return UNKNOWN
    amounts = []
    patterns = [
        r"(?:总投资|项目投资|投资金额|项目金额|中标金额|合同估算价|成交金额|投资额)\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:亿元|亿|万元|万|元))",
        r"(\d+(?:\.\d+)?\s*(?:亿元|亿|万元|万|元))",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            amount = parse_amount_to_yuan(match)
            if amount:
                amounts.append(amount)
    return format_amount_yuan(max(amounts)) if amounts else UNKNOWN


def extract_enterprise_name(text: str) -> str:
    patterns = [
        r"(?:企业名称|建设单位|项目单位|申报单位|建设主体|中标企业|中标人|施工单位|招标人)\s*[:：]\s*([^，。；;\n\r]{2,80})",
        r"关于\s*([^，。；;\n\r]{2,80}(?:股份有限公司|集团有限公司|有限公司|公司|厂|合作社|中心))",
        r"由\s*([^，。；;\n\r]{2,80}(?:股份有限公司|集团有限公司|有限公司|公司|厂|合作社|中心))\s*(?:建设|投资|实施|中标)",
        r"([^，。；;\s]{2,80}(?:股份有限公司|集团有限公司|有限公司|公司|厂|合作社|中心))",
    ]
    return first_match(text, patterns)


def extract_project_name(title: str, text: str) -> str:
    patterns = [
        r"(?:项目名称|工程名称|标段名称)\s*[:：]\s*([^，。；;\n\r]{2,160})",
        r"[《“\"]([^》”\"]{2,160}?项目[^》”\"]*)[》”\"]",
        r"关于([^，。；;\n\r]{2,160}?项目)(?:备案|审批|核准|批复|公示|许可|中标|招标)",
    ]
    matched = first_match(text, patterns)
    if matched != UNKNOWN:
        return matched
    cleaned = clean_value(title)
    return cleaned or UNKNOWN


def extract_approval_type(text: str, default: str = UNKNOWN) -> str:
    keywords = [
        "建设用地规划许可证",
        "建设工程规划许可证",
        "施工许可证",
        "企业投资项目备案",
        "项目备案",
        "投资备案",
        "环评审批",
        "环境影响评价",
        "中标公告",
        "招标公告",
        "土地出让",
        "审批",
        "批复",
        "许可",
        "公示",
    ]
    for keyword in keywords:
        if keyword in text:
            return keyword
    return default


def infer_stage(text: str, default: str = UNKNOWN) -> str:
    rules = [
        ("施工许可/开工阶段", ["施工许可证", "开工", "施工单位", "建设工程"]),
        ("土地/规划审批阶段", ["土地出让", "建设用地规划许可证", "建设工程规划许可证", "用地审批", "规划许可"]),
        ("环评审批阶段", ["环评", "环境影响评价", "拟批准", "受理公示"]),
        ("投资备案阶段", ["投资备案", "项目备案", "备案"]),
        ("招投标/中标阶段", ["中标", "招标", "公共资源交易"]),
    ]
    for stage, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return stage
    return default


def infer_industry(text: str, default: str = UNKNOWN) -> str:
    rules = [
        ("新能源", ["新能源", "电池", "光伏", "储能", "风电", "氢能"]),
        ("电子", ["电子", "芯片", "半导体", "集成电路", "传感器"]),
        ("设备制造", ["设备", "装备", "机械", "电气", "零部件", "高压", "生产线"]),
        ("新材料", ["材料", "纤维", "复合", "高性能"]),
        ("纺织服装", ["纺织", "家纺", "面料", "服装", "纤维丝"]),
        ("生物医药", ["医药", "生物", "药品", "医疗器械"]),
        ("制造业", ["制造", "生产", "厂房", "加工"]),
    ]
    for industry, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return industry
    return default


def extract_region(text: str, default: str = DEFAULT_REGION) -> str:
    if "南通市海门区" in text:
        return "南通市海门区"
    if "海门区" in text:
        return "海门区"
    if "海门" in text:
        return "海门"
    return default


def extract_land_area(text: str) -> str:
    patterns = [
        r"(?:土地面积|用地面积|宗地面积|占地面积)\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:平方米|㎡|亩|公顷))",
        r"(\d+(?:\.\d+)?\s*(?:平方米|㎡|亩|公顷))",
    ]
    return first_match(text, patterns)


def extract_location(text: str) -> str:
    patterns = [
        r"(?:建设地点|项目地址|建设地址|工程地址|建设位置|项目地点)\s*[:：]\s*([^，。；;\n\r]{2,120})",
        r"(海门区[^，。；;\n\r]{2,80})",
    ]
    return first_match(text, patterns)


def first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = clean_value(match.group(1))
            if value:
                return value
    return UNKNOWN


def clean_value(value: str) -> str:
    cleaned = normalize_space(value)
    cleaned = cleaned.strip(" ：:，,。；;、\t\r\n")
    cleaned = re.sub(r"^(?:关于|同意|批准|准予|核准)", "", cleaned).strip(" ：:，,。；;、\t\r\n")
    cleaned = re.split(
        r"\s+(?:项目名称|审批事项|发布时间|发布日期|日期|建设地点|项目地址|链接)\s*[:：]",
        cleaned,
        maxsplit=1,
    )[0]
    cleaned = re.sub(r"(以下简称.*)$", "", cleaned).strip()
    return cleaned[:180]


def recommended_products_for(stage: str, industry: str, amount_text: str, source: str = "") -> str:
    products: list[str] = []
    text = f"{stage} {industry} {source}"
    if any(keyword in text for keyword in ["施工", "开工", "建设工程", "土地", "规划", "备案"]):
        products.extend(["固定资产贷款", "项目贷款"])
    if any(keyword in text for keyword in ["设备", "装备", "电子", "新能源", "制造"]):
        products.append("设备融资")
    if any(keyword in text for keyword in ["中标", "招标", "公共资源"]):
        products.extend(["流动资金贷款", "保函"])
    if any(keyword in text for keyword in ["环评", "新能源", "新材料"]):
        products.append("绿色金融")
    if parse_amount_to_yuan(amount_text) >= 100_000_000:
        products.append("银团贷款")
    products.append("开户结算")
    return "、".join(dict.fromkeys(products))


def split_products(value: str) -> list[str]:
    if not value or value == UNKNOWN:
        return ["暂未明确贷款需求"]
    return [part.strip() for part in re.split(r"[、,，/]+", value) if part.strip()]


def build_manager_view(record: OpportunityRecord) -> dict[str, Any]:
    worth_visit = "是" if record.opportunity_level in {"A", "B"} else "建议观察"
    financing_need = estimate_financing_need(record)
    reason = build_reason(record)
    enterprise = record.enterprise_name if record.enterprise_name != UNKNOWN else "该企业"
    script = (
        f"建议以“项目建设资金安排和授信方案预沟通”为切入点联系{enterprise}，"
        f"重点了解项目进度、设备采购计划、资本金到位情况和结算账户安排。"
    )
    return {
        "是否值得拜访": worth_visit,
        "预计融资需求": financing_need,
        "推荐银行产品": split_products(record.recommended_loan_product),
        "拜访话术": script,
        "原因": reason,
    }


def estimate_financing_need(record: OpportunityRecord) -> str:
    amount = parse_amount_to_yuan(record.amount)
    if amount >= 100_000_000:
        return "预计存在较大固定资产或项目贷款需求"
    if amount >= 10_000_000:
        return "预计存在项目建设和流动资金需求"
    if record.stage in {"施工许可/开工阶段", "土地/规划审批阶段", "投资备案阶段"}:
        return "预计存在阶段性建设资金需求"
    return "需进一步核实融资需求"


def build_reason(record: OpportunityRecord) -> str:
    return (
        f"评分{record.opportunity_score:.1f}，"
        f"时间新鲜度{record.fresh_score}分，"
        f"阶段为{record.stage}，行业为{record.industry}，金额为{record.amount}。"
    )


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()
