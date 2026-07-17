from __future__ import annotations

import re


UNKNOWN = "未识别"


APPROVAL_KEYWORDS = [
    "建设用地规划许可证",
    "建设工程规划许可证",
    "企业投资项目备案",
    "项目备案",
    "备案",
    "施工许可证",
    "环评审批",
    "审批",
    "批复",
    "许可",
    "公示",
]


def extract_announcement_fields(title: str, text: str, url: str, fallback_date: str = "") -> dict[str, str]:
    combined = f"{title}\n{text}"
    return {
        "company_name": extract_company_name(combined),
        "project_name": extract_project_name(title, combined),
        "approval_item": extract_approval_item(combined),
        "date": parse_date(combined) or fallback_date or UNKNOWN,
        "url": url,
    }


def extract_company_name(text: str) -> str:
    patterns = [
        r"(?:建设单位|项目单位|申报单位|建设主体|企业名称|建设单位名称)\s*[:：]\s*([^，。,；;\n\r]{2,80})",
        r"关于\s*([^，。,；;\n\r]{2,80}(?:股份有限公司|集团有限公司|有限公司|公司|工厂|厂|合作社))",
        r"建设单位为\s*([^，。,；;\n\r]{2,80})",
        r"由\s*([^，。,；;\n\r]{2,80}(?:有限公司|股份有限公司|集团有限公司|公司|厂|合作社|中心))\s*(?:建设|投资|实施)",
        r"([^，。,；;\s]{2,80}(?:股份有限公司|集团有限公司|有限公司|公司|工厂|厂|合作社))",
    ]
    return _first_match(text, patterns)


def extract_project_name(title: str, text: str) -> str:
    patterns = [
        r"(?:项目名称|项目名)\s*[:：]\s*([^，。,；;\n\r]{2,120})",
        r"[《“\"]([^》”\"]{2,120}?项目[^》”\"]*)[》”\"]",
        r"关于([^，。,；;\n\r]{2,120}?项目)(?:备案|审批|核准|批复|公示|许可)",
    ]
    matched = _first_match(text, patterns)
    if matched != UNKNOWN:
        return matched
    cleaned_title = _clean_value(title)
    return cleaned_title or UNKNOWN


def extract_approval_item(text: str) -> str:
    for keyword in APPROVAL_KEYWORDS:
        if keyword in text:
            return keyword
    return "建设项目公告"


def parse_date(text: str) -> str:
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


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_value(match.group(1))
            if value:
                return value
    return UNKNOWN


def _clean_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ：:，。,；;、\t\r\n")
    if "关于" in value and re.search(r"(股份有限公司|集团有限公司|有限公司|公司|工厂|厂|合作社)$", value):
        value = value.split("关于")[-1]
    value = re.split(
        r"\s+(?:项目名称|项目名|审批事项|发布时间|发布日期|日期|建设地点|项目地址|链接)\s*[:：]",
        value,
        maxsplit=1,
    )[0]
    value = re.sub(r"(以下简称.*)$", "", value).strip()
    return value[:120]
