from __future__ import annotations

from data_source.base import BaseCrawler, OpportunityRecord, extract_amount, extract_location, parse_date


class InvestmentProjectCrawler(BaseCrawler):
    """江苏/南通/海门发改投资项目备案信息数据源."""

    source_name = "发改投资项目备案信息"
    source_type = "投资备案"
    default_stage = "投资备案阶段"
    detail_fetch_enabled = False
    keywords = [
        "备案",
        "项目备案",
        "投资项目",
        "企业投资项目",
        "重大项目",
        "工业项目",
        "厂房",
        "生产项目",
        "项目开工",
        "项目建设",
        "签约",
        "投运",
    ]
    match_keywords = keywords
    start_urls = [
        "https://www.haimen.gov.cn/hmsrmzf/pzfw/pzfw.html",
        "https://www.haimen.gov.cn/hmsrmzf/xmjz/xmjz.html",
    ]

    def record_from_candidate(self, candidate):
        record = super().record_from_candidate(candidate)
        if not record:
            return None
        text = f"{candidate.title} {record.project_name} {record.source_title}"
        record.approval_type = "企业投资项目备案" if "备案" in text else record.approval_type
        record.stage = "投资备案阶段"
        record.event_time = parse_date(text) or record.event_time
        record.amount = extract_amount(text) if extract_amount(text) != "未披露" else record.amount
        record.construction_location = (
            extract_location(text) if extract_location(text) != "未披露" else record.construction_location
        )
        return record
