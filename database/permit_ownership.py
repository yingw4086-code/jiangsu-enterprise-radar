from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.permit_ownership import (
    FOREIGN_ENTERPRISE,
    GOVERNMENT_AGENCY,
    MIXED_OWNERSHIP,
    PRIVATE_ENTERPRISE,
    PUBLIC_INSTITUTION,
    STATE_OWNED_COMMERCIAL,
    UNKNOWN,
    UNKNOWN_OWNERSHIP,
    classify_permit_owner,
    load_ownership_overrides,
    owner_category_label,
)
from database.storage import (
    PLANNING_CONSTRUCTION_PERMIT_TYPE,
    db_connection,
    init_db,
)


@dataclass(frozen=True)
class OwnershipClassificationSummary:
    total_records: int
    private_count: int
    state_owned_count: int
    government_count: int
    public_institution_count: int
    mixed_count: int
    foreign_count: int
    unknown_count: int
    marketing_eligible_count: int
    manual_review_count: int
    updated_count: int
    unchanged_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total_records": self.total_records,
            "private_count": self.private_count,
            "state_owned_count": self.state_owned_count,
            "government_count": self.government_count,
            "public_institution_count": self.public_institution_count,
            "mixed_count": self.mixed_count,
            "foreign_count": self.foreign_count,
            "unknown_count": self.unknown_count,
            "marketing_eligible_count": self.marketing_eligible_count,
            "manual_review_count": self.manual_review_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
        }


def classify_and_update_permit_owners(
    db_path: Path,
    overrides_path: Path,
    report_path: Path,
) -> OwnershipClassificationSummary:
    init_db(db_path)
    overrides = load_ownership_overrides(overrides_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts = {
        PRIVATE_ENTERPRISE: 0,
        STATE_OWNED_COMMERCIAL: 0,
        GOVERNMENT_AGENCY: 0,
        PUBLIC_INSTITUTION: 0,
        MIXED_OWNERSHIP: 0,
        FOREIGN_ENTERPRISE: 0,
        UNKNOWN_OWNERSHIP: 0,
    }
    marketing_eligible_count = 0
    manual_review_count = 0
    updated_count = 0
    unchanged_count = 0
    report_rows: list[dict[str, Any]] = []

    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                company_name,
                project_name,
                permit_date,
                publish_date,
                source_url,
                owner_name,
                owner_category,
                ownership_type,
                ownership_confidence,
                ownership_basis,
                marketing_eligible,
                marketing_priority,
                exclusion_reason,
                manual_review_required
            FROM construction_permits
            WHERE permit_type = ?
            ORDER BY id
            """,
            (PLANNING_CONSTRUCTION_PERMIT_TYPE,),
        ).fetchall()

        for row in rows:
            classification = classify_permit_owner(row["company_name"], overrides)
            values = classification.as_dict()
            comparable = {
                "owner_name": str(row["owner_name"] or ""),
                "owner_category": str(row["owner_category"] or ""),
                "ownership_type": str(row["ownership_type"] or ""),
                "ownership_confidence": int(row["ownership_confidence"] or 0),
                "ownership_basis": str(row["ownership_basis"] or ""),
                "marketing_eligible": bool(row["marketing_eligible"]),
                "marketing_priority": str(row["marketing_priority"] or ""),
                "exclusion_reason": str(row["exclusion_reason"] or ""),
                "manual_review_required": bool(row["manual_review_required"]),
            }
            if comparable != values:
                conn.execute(
                    """
                    UPDATE construction_permits SET
                        owner_name = ?,
                        owner_category = ?,
                        ownership_type = ?,
                        ownership_confidence = ?,
                        ownership_basis = ?,
                        marketing_eligible = ?,
                        marketing_priority = ?,
                        exclusion_reason = ?,
                        manual_review_required = ?,
                        classification_updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        values["owner_name"],
                        values["owner_category"],
                        values["ownership_type"],
                        values["ownership_confidence"],
                        values["ownership_basis"],
                        int(values["marketing_eligible"]),
                        values["marketing_priority"],
                        values["exclusion_reason"],
                        int(values["manual_review_required"]),
                        now,
                        row["id"],
                    ),
                )
                updated_count += 1
            else:
                unchanged_count += 1

            category = classification.owner_category
            counts[category] = counts.get(category, 0) + 1
            marketing_eligible_count += int(classification.marketing_eligible)
            manual_review_count += int(classification.manual_review_required)
            report_rows.append(
                {
                    "建设单位": classification.owner_name,
                    "项目名称": row["project_name"] or UNKNOWN,
                    "许可证日期": _effective_date(row["permit_date"], row["publish_date"]),
                    "分类结果": owner_category_label(category),
                    "所有制类型": classification.ownership_type,
                    "营销优先级": classification.marketing_priority,
                    "判断依据": classification.ownership_basis,
                    "置信度": classification.ownership_confidence,
                    "是否可营销": "是" if classification.marketing_eligible else "否",
                    "是否需要人工核验": "是" if classification.manual_review_required else "否",
                    "排除原因": classification.exclusion_reason,
                    "官方来源链接": row["source_url"] or "",
                }
            )

    _write_report(report_path, report_rows)
    return OwnershipClassificationSummary(
        total_records=len(report_rows),
        private_count=counts[PRIVATE_ENTERPRISE],
        state_owned_count=counts[STATE_OWNED_COMMERCIAL],
        government_count=counts[GOVERNMENT_AGENCY],
        public_institution_count=counts[PUBLIC_INSTITUTION],
        mixed_count=counts[MIXED_OWNERSHIP],
        foreign_count=counts[FOREIGN_ENTERPRISE],
        unknown_count=counts[UNKNOWN_OWNERSHIP],
        marketing_eligible_count=marketing_eligible_count,
        manual_review_count=manual_review_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
    )


def _write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "建设单位",
        "项目名称",
        "许可证日期",
        "分类结果",
        "所有制类型",
        "营销优先级",
        "判断依据",
        "置信度",
        "是否可营销",
        "是否需要人工核验",
        "排除原因",
        "官方来源链接",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _effective_date(permit_date: Any, publish_date: Any) -> str:
    permit_text = str(permit_date or "").strip()
    if permit_text and permit_text != UNKNOWN:
        return permit_text
    return str(publish_date or UNKNOWN).strip() or UNKNOWN
