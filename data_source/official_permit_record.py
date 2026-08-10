from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_source.base import UNKNOWN, calculate_fresh_score
from data_source.permit_validation import PermitValidationRecord


@dataclass
class OfficialPermitRecord:
    company_name: str
    construction_unit: str
    project_name: str
    permit_type: str
    permit_number: str
    permit_date: str
    publish_date: str
    project_address: str
    issuing_authority: str
    district: str
    district_code: str
    source_url: str
    source_name: str
    project_scale: str = UNKNOWN
    investment_amount: str = UNKNOWN
    industry: str = UNKNOWN
    project_stage: str = UNKNOWN
    source_title: str = ""
    haimen_match_reason: str = ""
    haimen_match_confidence: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def event_date(self) -> str:
        if self.permit_date and self.permit_date != UNKNOWN:
            return self.permit_date
        return self.publish_date

    @property
    def fresh_score(self) -> int:
        return calculate_fresh_score(self.event_date)

    @property
    def update_time(self) -> str:
        return self.publish_date if self.publish_date != UNKNOWN else self.permit_date

    @property
    def loan_opportunity_score(self) -> int:
        return 0

    @property
    def customer_level(self) -> str:
        return "C"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "company_name": self.company_name,
            "project_name": self.project_name,
            "permit_type": self.permit_type,
            "permit_number": self.permit_number,
            "permit_date": self.permit_date,
            "publish_date": self.publish_date,
            "project_address": self.project_address,
            "issuing_authority": self.issuing_authority,
            "district": self.district,
            "district_code": self.district_code,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "fresh_score": self.fresh_score,
        }


def from_validation_record(
    record: PermitValidationRecord,
    *,
    project_stage: str,
) -> OfficialPermitRecord:
    raw = dict(record.raw)
    raw["source_title"] = record.source_title
    raw["haimen_match_reason"] = record.haimen_match_reason
    raw["haimen_match_confidence"] = record.haimen_match_confidence
    return OfficialPermitRecord(
        company_name=record.company_name,
        construction_unit=record.construction_unit,
        project_name=record.project_name,
        permit_type=record.permit_type,
        permit_number=record.permit_number,
        permit_date=record.permit_date,
        publish_date=record.publish_date,
        project_address=(
            record.project_address
            if record.project_address != UNKNOWN
            else record.construction_location
        ),
        issuing_authority=record.issuing_authority,
        district="海门区",
        district_code="320684",
        source_url=record.source_url,
        source_name=record.source_name,
        project_scale=record.project_scale,
        investment_amount=record.investment_amount,
        project_stage=project_stage,
        source_title=record.source_title,
        haimen_match_reason=record.haimen_match_reason,
        haimen_match_confidence=record.haimen_match_confidence,
        raw=raw,
    )
