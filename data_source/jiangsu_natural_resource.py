from __future__ import annotations

from data_source.base import BaseCrawler, LinkCandidate


class JiangsuNaturalResourceCrawler(BaseCrawler):
    """江苏自然资源政务信息检索服务数据源."""

    source_name = "江苏自然资源政务信息检索服务"
    source_type = "自然资源"
    default_stage = "土地/规划审批阶段"
    form_encoding = "gb18030"
    detail_fetch_enabled = False
    enable_search = True
    keywords = [
        "海门",
        "南通海门",
        "土地出让",
        "建设用地规划许可证",
        "建设工程规划许可证",
        "施工许可证",
        "工业项目",
        "厂房建设",
        "项目备案",
    ]
    match_keywords = [
        "土地出让",
        "建设用地规划许可证",
        "建设工程规划许可证",
        "施工许可证",
        "工业项目",
        "厂房建设",
        "项目备案",
        "网挂",
        "工网挂",
        "行政许可",
    ]
    search_url = "https://zrzy.jiangsu.gov.cn/gtxxgk/nrglIndex.action?classID=8a908254409a391f01409a4b28500008"
    start_urls = [
        "https://www.haimen.gov.cn/hmsgtj/xzxk/xzxk.html",
        "https://www.haimen.gov.cn/hmsgtj/gytdsyqcr/gytdsyqcr.html",
    ]

    def collect_candidates(self) -> list[LinkCandidate]:
        candidates = super().collect_candidates()
        if not self.enable_search:
            return self.filter_candidates(candidates)
        for keyword in self.keywords:
            result = self.safe_fetch_text(
                self.search_url,
                data={
                    "queryCatalogID": "40288149189c438401189c61ad130028",
                    "querytype": "2",
                    "area": "0",
                    "searchColumn": "biaoti",
                    "title": keyword,
                },
            )
            if result.ok:
                candidates.extend(self.extract_candidates(result.text, result.url))
        return self.filter_candidates(candidates)
