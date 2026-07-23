from __future__ import annotations

import re

from data_source.base import BaseCrawler, OpportunityRecord, UNKNOWN, clean_value, first_match


class EnvironmentApprovalCrawler(BaseCrawler):
    """生态环境审批公开信息数据源."""

    source_name = "生态环境审批公开信息"
    source_type = "生态环境"
    default_stage = "环评审批阶段"
    detail_fetch_enabled = False
    keywords = [
        "环评",
        "环境影响评价",
        "拟批准",
        "受理公示",
    ]
    match_keywords = keywords
    start_urls = [
        "https://www.haimen.gov.cn/hmsrmzf/npzgs/npzgs.html",
    ]

    def record_from_candidate(self, candidate):
        record = super().record_from_candidate(candidate)
        if not record:
            return None
        record.approval_type = "环境影响评价"
        record.stage = "环评审批阶段"
        record.raw["建设内容"] = extract_construction_content(record.source_title)
        return record


def extract_construction_content(text: str) -> str:
    content = first_match(
        text,
        [
            r"(?:建设内容|项目内容|建设规模)\s*[:：]\s*([^。；;\n\r]{2,180})",
            r"(?:建设|新建|扩建|技改)([^。；;\n\r]{2,180})",
        ],
    )
    if content != UNKNOWN:
        return clean_value(content)
    match = re.search(r"([^。；;\n\r]{2,180}?项目)", text)
    return clean_value(match.group(1)) if match else UNKNOWN
