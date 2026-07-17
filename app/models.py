from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectAnnouncement:
    company_name: str
    project_name: str
    approval_item: str
    date: str
    link: str
    source_name: str
    title: str
    fetched_at: str

    def to_excel_row(self) -> list[str]:
        return [
            self.company_name,
            self.project_name,
            self.approval_item,
            self.date,
            self.link,
            self.source_name,
            self.title,
            self.fetched_at,
        ]


@dataclass(frozen=True)
class FinancingAnalysis:
    has_financing_need: bool
    expected_loan_types: list[str]
    customer_value_level: str
    marketing_advice: str
    reason: str
    confidence: float

    def to_json_dict(self) -> dict[str, object]:
        return {
            "has_financing_need": self.has_financing_need,
            "expected_loan_types": self.expected_loan_types,
            "customer_value_level": self.customer_value_level,
            "marketing_advice": self.marketing_advice,
            "reason": self.reason,
            "confidence": self.confidence,
        }
