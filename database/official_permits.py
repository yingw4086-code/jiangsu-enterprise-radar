from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from data_source.base import UNKNOWN
from data_source.official_permit_record import OfficialPermitRecord
from data_source.project_classification import classify_project
from database.storage import (
    UpsertSummary,
    construction_permit_hash,
    db_connection,
    init_db,
)


PUBLIC_FIELDS = (
    "company_name",
    "project_name",
    "permit_type",
    "permit_number",
    "permit_date",
    "publish_date",
    "project_address",
    "issuing_authority",
    "district",
    "district_code",
    "source_url",
    "source_name",
    "fresh_score",
    "first_seen_at",
    "last_seen_at",
    "project_type",
    "classification_confidence",
)

COMPARE_COLUMNS = (
    "company_name",
    "project_name",
    "permit_type",
    "permit_number",
    "permit_date",
    "publish_date",
    "address",
    "issuing_authority",
    "district",
    "district_code",
    "source_url",
    "source_name",
    "project_type",
    "classification_confidence",
)


def upsert_official_permits(
    db_path: Path,
    records: Iterable[OfficialPermitRecord],
    *,
    permit_type: str,
) -> UpsertSummary:
    records = list(records)
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    updated = 0
    skipped = 0
    seen: set[str] = set()

    with db_connection(db_path) as conn:
        for record in records:
            if record.permit_type != permit_type:
                skipped += 1
                continue
            item_hash = construction_permit_hash(record)
            if item_hash in seen:
                skipped += 1
                continue
            seen.add(item_hash)
            params = _record_to_params(record, item_hash, now)
            existing = _find_existing(conn, params)
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO construction_permits (
                        record_hash, company_name, project_name, permit_type, permit_date,
                        address, investment, score, source, construction_unit, permit_number,
                        project_scale, industry, update_time, project_stage, customer_level,
                        raw_json, created_at, updated_at, publish_date, issuing_authority,
                        district, district_code, source_url, source_name, fresh_score,
                        first_seen_at, last_seen_at, project_type,
                        classification_confidence
                    ) VALUES (
                        :record_hash, :company_name, :project_name, :permit_type, :permit_date,
                        :address, :investment, :score, :source, :construction_unit, :permit_number,
                        :project_scale, :industry, :update_time, :project_stage, :customer_level,
                        :raw_json, :created_at, :updated_at, :publish_date, :issuing_authority,
                        :district, :district_code, :source_url, :source_name, :fresh_score,
                        :first_seen_at, :last_seen_at, :project_type,
                        :classification_confidence
                    )
                    """,
                    params,
                )
                inserted += 1
                continue

            changed = any(
                str(existing[column] or "") != str(params[column] or "")
                for column in COMPARE_COLUMNS
            )
            params["existing_id"] = existing["id"]
            params["first_seen_at"] = existing["first_seen_at"] or existing["created_at"] or now
            if changed:
                conn.execute(
                    """
                    UPDATE construction_permits SET
                        record_hash=:record_hash,
                        company_name=:company_name,
                        project_name=:project_name,
                        permit_type=:permit_type,
                        permit_date=:permit_date,
                        address=:address,
                        investment=:investment,
                        score=:score,
                        source=:source,
                        construction_unit=:construction_unit,
                        permit_number=:permit_number,
                        project_scale=:project_scale,
                        industry=:industry,
                        update_time=:update_time,
                        project_stage=:project_stage,
                        customer_level=:customer_level,
                        raw_json=:raw_json,
                        updated_at=:updated_at,
                        publish_date=:publish_date,
                        issuing_authority=:issuing_authority,
                        district=:district,
                        district_code=:district_code,
                        source_url=:source_url,
                        source_name=:source_name,
                        fresh_score=:fresh_score,
                        first_seen_at=:first_seen_at,
                        last_seen_at=:last_seen_at,
                        project_type=:project_type,
                        classification_confidence=:classification_confidence
                    WHERE id=:existing_id
                    """,
                    params,
                )
                updated += 1
            else:
                conn.execute(
                    """
                    UPDATE construction_permits
                    SET last_seen_at=:last_seen_at, updated_at=:updated_at, fresh_score=:fresh_score
                    WHERE id=:existing_id
                    """,
                    params,
                )
                skipped += 1

        total = conn.execute(
            "SELECT COUNT(*) AS count FROM construction_permits WHERE permit_type = ?",
            (permit_type,),
        ).fetchone()["count"]

    return UpsertSummary(
        fetched_count=len(records),
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        total_count=int(total),
    )


def load_public_official_permits(
    db_path: Path,
    *,
    permit_type: str,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                company_name,
                project_name,
                permit_type,
                permit_number,
                permit_date,
                publish_date,
                address AS project_address,
                issuing_authority,
                district,
                district_code,
                source_url,
                source_name,
                fresh_score,
                first_seen_at,
                last_seen_at,
                project_type,
                classification_confidence
            FROM construction_permits
            WHERE permit_type = ? AND district_code = '320684'
            ORDER BY
                CASE WHEN permit_date <> ? THEN permit_date ELSE publish_date END DESC,
                id DESC
            """,
            (permit_type, UNKNOWN),
        ).fetchall()
    return [dict(row) for row in rows]


def export_public_official_permits(
    db_path: Path,
    output_path: Path,
    *,
    permit_type: str,
) -> dict[str, Any]:
    rows = load_public_official_permits(db_path, permit_type=permit_type)
    if not rows:
        return {
            "export_count": 0,
            "output_path": str(output_path),
            "written": False,
            "error": f"数据库中没有已确认的{permit_type}，未创建或覆盖JSON",
        }
    public_rows = [{field: row.get(field) for field in PUBLIC_FIELDS} for row in rows]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(public_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "export_count": len(public_rows),
        "output_path": str(output_path),
        "written": True,
        "error": "",
    }


def _record_to_params(
    record: OfficialPermitRecord,
    item_hash: str,
    now: str,
) -> dict[str, Any]:
    company_name = record.company_name or UNKNOWN
    construction_unit = record.construction_unit or UNKNOWN
    project_name = record.project_name or UNKNOWN
    classification = classify_project(
        company_name=company_name,
        construction_unit=construction_unit,
        project_name=project_name,
    )
    return {
        "record_hash": item_hash,
        "company_name": company_name,
        "project_name": project_name,
        "permit_type": record.permit_type or UNKNOWN,
        "permit_date": record.permit_date or UNKNOWN,
        "address": record.project_address or UNKNOWN,
        "investment": record.investment_amount or UNKNOWN,
        "score": record.loan_opportunity_score,
        "source": record.source_url,
        "construction_unit": construction_unit,
        "permit_number": record.permit_number or UNKNOWN,
        "project_scale": record.project_scale or UNKNOWN,
        "industry": record.industry or UNKNOWN,
        "update_time": record.update_time or UNKNOWN,
        "project_stage": record.project_stage or UNKNOWN,
        "customer_level": record.customer_level,
        "raw_json": json.dumps(record.raw, ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
        "publish_date": record.publish_date or UNKNOWN,
        "issuing_authority": record.issuing_authority or UNKNOWN,
        "district": record.district or UNKNOWN,
        "district_code": record.district_code or UNKNOWN,
        "source_url": record.source_url,
        "source_name": record.source_name or UNKNOWN,
        "fresh_score": record.fresh_score,
        "first_seen_at": now,
        "last_seen_at": now,
        "project_type": classification.project_type,
        "classification_confidence": classification.confidence,
    }


def _find_existing(
    conn: sqlite3.Connection,
    params: dict[str, Any],
) -> sqlite3.Row | None:
    permit_number = str(params["permit_number"])
    if permit_number and permit_number != UNKNOWN:
        row = conn.execute(
            """
            SELECT * FROM construction_permits
            WHERE permit_number = ? AND permit_type = ?
            ORDER BY id LIMIT 1
            """,
            (permit_number, params["permit_type"]),
        ).fetchone()
        if row is not None:
            return row
    source_url = str(params["source_url"])
    if source_url:
        row = conn.execute(
            """
            SELECT * FROM construction_permits
            WHERE (source_url = ? OR source = ?) AND permit_type = ?
            ORDER BY id LIMIT 1
            """,
            (source_url, source_url, params["permit_type"]),
        ).fetchone()
        if row is not None:
            return row
    return conn.execute(
        """
        SELECT * FROM construction_permits
        WHERE project_name = ? AND permit_type = ? AND permit_date = ?
        ORDER BY id LIMIT 1
        """,
        (params["project_name"], params["permit_type"], params["permit_date"]),
    ).fetchone()
