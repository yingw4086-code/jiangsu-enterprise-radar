from __future__ import annotations

from data_source.base import BaseCrawler, extract_amount, first_match


class TenderCrawler(BaseCrawler):
    """公共资源交易和中标公告数据源."""

    source_name = "公共资源交易信息"
    source_type = "公共资源交易"
    default_stage = "招投标/中标阶段"
    detail_fetch_enabled = False
    keywords = [
        "中标",
        "成交",
        "公共资源交易",
        "招标",
        "采购",
        "采购公告",
        "项目金额",
        "中标金额",
        "工程",
    ]
    match_keywords = keywords
    start_urls = [
        "https://www.haimen.gov.cn/hmsrmzf/fscg/fscg.html",
        "https://www.haimen.gov.cn/hmsgtj/zfcg/zfcg.html",
    ]

    def record_from_candidate(self, candidate):
        record = super().record_from_candidate(candidate)
        if not record:
            return None
        record.approval_type = "中标公告" if any(key in candidate.title for key in ["中标", "成交"]) else "公共资源交易"
        record.stage = "招投标/中标阶段"
        combined = f"{candidate.title} {record.source_title} {record.project_name}"
        winner = first_match(
            combined,
            [
                r"(?:中标企业|中标人|成交供应商|成交单位|供应商名称)\s*[:：]\s*([^，。；;\n\r]{2,80})",
                r"([^，。；;\s]{2,80}(?:股份有限公司|集团有限公司|有限公司|公司|厂|合作社|中心))",
            ],
        )
        amount = extract_amount(combined)
        if winner != "未披露":
            record.enterprise_name = winner
        if amount != "未披露":
            record.amount = amount
        record.raw["中标企业"] = winner
        return record
