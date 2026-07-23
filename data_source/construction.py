from __future__ import annotations

from io import BytesIO
from typing import Any

from app.parsers.html_links import extract_links
from data_source.base import (
    BaseCrawler,
    OpportunityRecord,
    UNKNOWN,
    clean_value,
    dedupe_records,
    extract_enterprise_name,
    extract_location,
    first_match,
    infer_industry,
    parse_date,
)


class ConstructionPermitCrawler(BaseCrawler):
    """住建施工许可证信息数据源."""

    source_name = "住建施工许可证信息"
    source_type = "施工许可"
    default_stage = "施工许可/开工阶段"
    detail_page_limit = 5
    keywords = [
        "施工许可证",
        "建筑工程施工许可证",
        "行政许可事项公示清单",
    ]
    match_keywords = keywords
    start_urls = [
        "http://www.haimen.gov.cn/hmszjj/xzxk/xzxk.html",
    ]

    def crawl(self) -> list[OpportunityRecord]:
        records: list[OpportunityRecord] = []
        for candidate in self.collect_candidates()[: self.detail_page_limit]:
            records.extend(self.records_from_candidate(candidate))
            if len(records) >= self.max_items:
                break
        return dedupe_records([record.enrich() for record in records])[: self.max_items]

    def records_from_candidate(self, candidate) -> list[OpportunityRecord]:
        detail = self.safe_fetch_text(candidate.url)
        if not detail.ok or not detail.text:
            return [self.fallback_record(candidate)]

        records: list[OpportunityRecord] = []
        attachment_links = [
            item
            for item in extract_links(detail.text, detail.url)
            if item.get("url", "").lower().endswith((".xls", ".xlsx"))
        ]
        for attachment in attachment_links:
            attachment_result = self.safe_fetch_bytes(attachment["url"])
            if not attachment_result.ok or not attachment_result.body:
                continue
            records.extend(
                self.records_from_excel(
                    body=attachment_result.body,
                    attachment_url=attachment_result.url,
                    attachment_title=attachment.get("title", ""),
                    source_url=candidate.url,
                    source_title=candidate.title,
                    fallback_date=candidate.date,
                )
            )
        if records:
            return records
        return [self.fallback_record(candidate)]

    def record_from_candidate(self, candidate):
        record = super().record_from_candidate(candidate)
        if not record:
            return None
        record.approval_type = "施工许可证"
        record.stage = "施工许可/开工阶段"
        combined = f"{candidate.title} {record.source_title} {record.project_name}"
        construction_company = first_match(
            combined,
            [r"施工单位\s*[:：]\s*([^，。；;\n\r]{2,80})", r"施工单位[:：]?([^，。；;\n\r]{2,80})"],
        )
        owner = first_match(
            combined,
            [r"建设单位\s*[:：]\s*([^，。；;\n\r]{2,80})", r"建设单位[:：]?([^，。；;\n\r]{2,80})"],
        )
        if owner != "未披露":
            record.enterprise_name = owner
        elif record.enterprise_name == "未披露":
            record.enterprise_name = extract_enterprise_name(combined)
        record.raw["施工单位"] = construction_company
        record.raw["建设单位"] = owner
        return record

    def fallback_record(self, candidate) -> OpportunityRecord:
        return OpportunityRecord(
            enterprise_name=UNKNOWN,
            project_name=candidate.title,
            source=self.source_name,
            event_time=candidate.date or UNKNOWN,
            amount=UNKNOWN,
            industry="制造业",
            region="南通市海门区",
            approval_type="施工许可证",
            stage="施工许可/开工阶段",
            source_url=candidate.url,
            source_title=candidate.title,
            publish_time=candidate.date or UNKNOWN,
            update_time=candidate.date or UNKNOWN,
            raw={
                "crawler": self.__class__.__name__,
                "source_type": self.source_type,
                "fallback_reason": "施工许可附件暂未成功解析，保留清单页线索",
            },
        )

    def records_from_excel(
        self,
        body: bytes,
        attachment_url: str,
        attachment_title: str,
        source_url: str,
        source_title: str,
        fallback_date: str,
    ) -> list[OpportunityRecord]:
        try:
            import pandas as pd
        except ImportError:
            self.errors.append("住建施工许可证信息 缺少 pandas，无法读取行政许可 Excel 附件")
            return []

        try:
            workbook = pd.read_excel(BytesIO(body), sheet_name=None, header=None, dtype=str)
        except Exception as exc:  # pragma: no cover - depends on remote Excel format
            self.errors.append(f"住建施工许可证信息 Excel 解析失败: {attachment_url}; {exc}")
            return []

        records: list[OpportunityRecord] = []
        for sheet_name, frame in workbook.items():
            rows = frame.fillna("").astype(str).values.tolist()
            header_index = find_header_index(rows)
            if header_index is None:
                continue
            headers = [clean_value(value) for value in rows[header_index]]
            for row in rows[header_index + 1 :]:
                values = {headers[index]: clean_value(value) for index, value in enumerate(row) if index < len(headers)}
                row_text = " ".join(value for value in values.values() if value)
                if not row_text:
                    continue
                if not any(keyword in row_text for keyword in ["施工许可证", "建筑工程施工许可证", "施工许可"]):
                    continue
                enterprise = pick_value(values, ["建设单位", "行政相对人名称", "申请单位", "单位名称", "法人"])
                project = pick_value(values, ["项目名称", "工程名称", "许可内容", "行政许可决定文书名称", "事项名称"])
                event_time = parse_date(row_text) or fallback_date or UNKNOWN
                if enterprise == UNKNOWN and project == UNKNOWN:
                    continue
                records.append(
                    OpportunityRecord(
                        enterprise_name=enterprise if enterprise != UNKNOWN else extract_enterprise_name(row_text),
                        project_name=project if project != UNKNOWN else source_title,
                        source=self.source_name,
                        event_time=event_time,
                        amount=UNKNOWN,
                        industry=infer_industry(row_text, "制造业"),
                        region="南通市海门区",
                        approval_type="施工许可证",
                        stage="施工许可/开工阶段",
                        source_url=source_url,
                        source_title=source_title,
                        publish_time=event_time,
                        update_time=event_time,
                        construction_location=extract_location(row_text),
                        raw={
                            "crawler": self.__class__.__name__,
                            "source_type": self.source_type,
                            "attachment_url": attachment_url,
                            "attachment_title": attachment_title,
                            "sheet_name": str(sheet_name),
                            "row": values,
                        },
                    )
                )
        return records


def find_header_index(rows: list[list[Any]]) -> int | None:
    header_markers = ["建设单位", "行政相对人", "项目名称", "工程名称", "许可内容", "文书名称"]
    for index, row in enumerate(rows[:15]):
        row_text = " ".join(str(value) for value in row)
        if sum(1 for marker in header_markers if marker in row_text) >= 2:
            return index
    return None


def pick_value(values: dict[str, str], headers: list[str]) -> str:
    for target in headers:
        for header, value in values.items():
            if target in header and value:
                return value
    return UNKNOWN
