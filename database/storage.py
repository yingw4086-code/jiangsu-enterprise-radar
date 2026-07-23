from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from data_source.base import OpportunityRecord, UNKNOWN


SCHEMA_VERSION = 4
PLANNING_CONSTRUCTION_PERMIT_TYPE = "建设工程规划许可证"


@dataclass(frozen=True)
class UpsertSummary:
    fetched_count: int
    inserted_count: int
    updated_count: int
    total_count: int
    skipped_count: int = 0


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_connection(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS enterprise_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_hash TEXT NOT NULL UNIQUE,
                enterprise_name TEXT NOT NULL,
                project_name TEXT NOT NULL,
                source TEXT NOT NULL,
                event_time TEXT NOT NULL,
                amount TEXT NOT NULL,
                industry TEXT NOT NULL,
                region TEXT NOT NULL,
                opportunity_level TEXT NOT NULL,
                recommended_loan_product TEXT NOT NULL,
                approval_type TEXT NOT NULL,
                stage TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_title TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                update_time TEXT NOT NULL,
                fresh_score INTEGER NOT NULL,
                opportunity_score REAL NOT NULL,
                land_area TEXT NOT NULL,
                construction_location TEXT NOT NULL,
                manager_view_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawler_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_started_at TEXT NOT NULL,
                run_finished_at TEXT NOT NULL,
                source TEXT NOT NULL,
                fetched_count INTEGER NOT NULL,
                inserted_count INTEGER NOT NULL,
                updated_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS construction_permits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_hash TEXT NOT NULL UNIQUE,
                company_name TEXT NOT NULL,
                project_name TEXT NOT NULL,
                permit_type TEXT NOT NULL,
                permit_date TEXT NOT NULL,
                address TEXT NOT NULL,
                investment TEXT NOT NULL,
                score INTEGER NOT NULL,
                source TEXT NOT NULL,
                construction_unit TEXT NOT NULL,
                permit_number TEXT NOT NULL,
                project_scale TEXT NOT NULL,
                industry TEXT NOT NULL,
                update_time TEXT NOT NULL,
                project_stage TEXT NOT NULL,
                customer_level TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS permit_ai_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                permit_id INTEGER NOT NULL UNIQUE,
                input_hash TEXT NOT NULL,
                ai_opportunity_level TEXT NOT NULL,
                financing_need TEXT NOT NULL,
                recommended_products_json TEXT NOT NULL,
                marketing_summary TEXT NOT NULL,
                visit_suggestion TEXT NOT NULL,
                reasoning_summary TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                risk_notice TEXT NOT NULL,
                api_model TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(permit_id) REFERENCES construction_permits(id) ON DELETE CASCADE
            )
            """
        )
        _ensure_columns(
            conn,
            "construction_permits",
            {
                "publish_date": "TEXT NOT NULL DEFAULT '未披露'",
                "issuing_authority": "TEXT NOT NULL DEFAULT '未披露'",
                "district": "TEXT NOT NULL DEFAULT '未披露'",
                "district_code": "TEXT NOT NULL DEFAULT '未披露'",
                "source_url": "TEXT NOT NULL DEFAULT ''",
                "source_name": "TEXT NOT NULL DEFAULT '未披露'",
                "fresh_score": "INTEGER NOT NULL DEFAULT 0",
                "first_seen_at": "TEXT NOT NULL DEFAULT ''",
                "last_seen_at": "TEXT NOT NULL DEFAULT ''",
                "owner_name": "TEXT NOT NULL DEFAULT '未披露'",
                "owner_category": "TEXT NOT NULL DEFAULT 'unknown'",
                "ownership_type": "TEXT NOT NULL DEFAULT 'unknown'",
                "ownership_confidence": "INTEGER NOT NULL DEFAULT 0",
                "ownership_basis": "TEXT NOT NULL DEFAULT '建设单位信息不足，无法判断所有制'",
                "marketing_eligible": "INTEGER NOT NULL DEFAULT 0",
                "marketing_priority": "TEXT NOT NULL DEFAULT '待核验'",
                "exclusion_reason": "TEXT NOT NULL DEFAULT ''",
                "manual_review_required": "INTEGER NOT NULL DEFAULT 1",
                "classification_updated_at": "TEXT NOT NULL DEFAULT ''",
            },
        )
        conn.execute(
            "UPDATE construction_permits SET source_url = source WHERE source_url = '' AND source <> ''"
        )
        conn.execute(
            "UPDATE construction_permits SET first_seen_at = created_at WHERE first_seen_at = ''"
        )
        conn.execute(
            "UPDATE construction_permits SET last_seen_at = updated_at WHERE last_seen_at = ''"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO schema_meta(key, value)
            VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_time ON enterprise_opportunities(event_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_level ON enterprise_opportunities(opportunity_level)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_source ON enterprise_opportunities(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_date ON construction_permits(permit_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_type ON construction_permits(permit_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_score ON construction_permits(score)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_number ON construction_permits(permit_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_source_url ON construction_permits(source_url)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_owner_category ON construction_permits(owner_category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_marketing_eligible ON construction_permits(marketing_eligible)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_ai_level ON permit_ai_analyses(ai_opportunity_level)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_permit_ai_input_hash ON permit_ai_analyses(input_hash)")


def _ensure_columns(
    conn: sqlite3.Connection,
    table_name: str,
    columns: dict[str, str],
) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column_name, definition in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_opportunities(db_path: Path, records: Iterable[OpportunityRecord]) -> UpsertSummary:
    records = list(records)
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hashes = [record_hash(record) for record in records]
    with db_connection(db_path) as conn:
        existing = set()
        if hashes:
            placeholders = ",".join("?" for _ in hashes)
            rows = conn.execute(
                f"SELECT record_hash FROM enterprise_opportunities WHERE record_hash IN ({placeholders})",
                hashes,
            ).fetchall()
            existing = {row["record_hash"] for row in rows}

        for record in records:
            item_hash = record_hash(record)
            conn.execute(
                """
                INSERT INTO enterprise_opportunities (
                    record_hash, enterprise_name, project_name, source, event_time, amount,
                    industry, region, opportunity_level, recommended_loan_product,
                    approval_type, stage, source_url, source_title, publish_time, update_time,
                    fresh_score, opportunity_score, land_area, construction_location,
                    manager_view_json, raw_json, created_at, updated_at
                )
                VALUES (
                    :record_hash, :enterprise_name, :project_name, :source, :event_time, :amount,
                    :industry, :region, :opportunity_level, :recommended_loan_product,
                    :approval_type, :stage, :source_url, :source_title, :publish_time, :update_time,
                    :fresh_score, :opportunity_score, :land_area, :construction_location,
                    :manager_view_json, :raw_json, :created_at, :updated_at
                )
                ON CONFLICT(record_hash) DO UPDATE SET
                    enterprise_name=excluded.enterprise_name,
                    project_name=excluded.project_name,
                    source=excluded.source,
                    event_time=excluded.event_time,
                    amount=excluded.amount,
                    industry=excluded.industry,
                    region=excluded.region,
                    opportunity_level=excluded.opportunity_level,
                    recommended_loan_product=excluded.recommended_loan_product,
                    approval_type=excluded.approval_type,
                    stage=excluded.stage,
                    source_url=excluded.source_url,
                    source_title=excluded.source_title,
                    publish_time=excluded.publish_time,
                    update_time=excluded.update_time,
                    fresh_score=excluded.fresh_score,
                    opportunity_score=excluded.opportunity_score,
                    land_area=excluded.land_area,
                    construction_location=excluded.construction_location,
                    manager_view_json=excluded.manager_view_json,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                record_to_params(record, item_hash, now),
            )

        total = conn.execute("SELECT COUNT(*) AS count FROM enterprise_opportunities").fetchone()["count"]

    inserted = sum(1 for item in hashes if item not in existing)
    updated = len(records) - inserted
    return UpsertSummary(
        fetched_count=len(records),
        inserted_count=inserted,
        updated_count=updated,
        total_count=total,
    )


def upsert_construction_permits(db_path: Path, records: Iterable[Any]) -> UpsertSummary:
    records = list(records)
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hashes = [construction_permit_hash(record) for record in records]
    with db_connection(db_path) as conn:
        existing = set()
        if hashes:
            placeholders = ",".join("?" for _ in hashes)
            rows = conn.execute(
                f"SELECT record_hash FROM construction_permits WHERE record_hash IN ({placeholders})",
                hashes,
            ).fetchall()
            existing = {row["record_hash"] for row in rows}

        for record in records:
            item_hash = construction_permit_hash(record)
            conn.execute(
                """
                INSERT INTO construction_permits (
                    record_hash, company_name, project_name, permit_type, permit_date,
                    address, investment, score, source, construction_unit, permit_number,
                    project_scale, industry, update_time, project_stage, customer_level,
                    raw_json, created_at, updated_at
                )
                VALUES (
                    :record_hash, :company_name, :project_name, :permit_type, :permit_date,
                    :address, :investment, :score, :source, :construction_unit, :permit_number,
                    :project_scale, :industry, :update_time, :project_stage, :customer_level,
                    :raw_json, :created_at, :updated_at
                )
                ON CONFLICT(record_hash) DO UPDATE SET
                    company_name=excluded.company_name,
                    project_name=excluded.project_name,
                    permit_type=excluded.permit_type,
                    permit_date=excluded.permit_date,
                    address=excluded.address,
                    investment=excluded.investment,
                    score=excluded.score,
                    source=excluded.source,
                    construction_unit=excluded.construction_unit,
                    permit_number=excluded.permit_number,
                    project_scale=excluded.project_scale,
                    industry=excluded.industry,
                    update_time=excluded.update_time,
                    project_stage=excluded.project_stage,
                    customer_level=excluded.customer_level,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                construction_permit_to_params(record, item_hash, now),
            )

        total = conn.execute("SELECT COUNT(*) AS count FROM construction_permits").fetchone()["count"]

    inserted = sum(1 for item in hashes if item not in existing)
    updated = len(records) - inserted
    return UpsertSummary(
        fetched_count=len(records),
        inserted_count=inserted,
        updated_count=updated,
        total_count=total,
    )


def upsert_planning_construction_permits(db_path: Path, records: Iterable[Any]) -> UpsertSummary:
    records = list(records)
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    updated = 0
    skipped = 0
    seen_keys: set[str] = set()

    with db_connection(db_path) as conn:
        for record in records:
            item_hash = construction_permit_hash(record)
            if item_hash in seen_keys:
                skipped += 1
                continue
            seen_keys.add(item_hash)
            params = planning_construction_permit_to_params(record, item_hash, now)
            existing = _find_existing_planning_permit(conn, params)
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO construction_permits (
                        record_hash, company_name, project_name, permit_type, permit_date,
                        address, investment, score, source, construction_unit, permit_number,
                        project_scale, industry, update_time, project_stage, customer_level,
                        raw_json, created_at, updated_at, publish_date, issuing_authority,
                        district, district_code, source_url, source_name, fresh_score,
                        first_seen_at, last_seen_at
                    ) VALUES (
                        :record_hash, :company_name, :project_name, :permit_type, :permit_date,
                        :address, :investment, :score, :source, :construction_unit, :permit_number,
                        :project_scale, :industry, :update_time, :project_stage, :customer_level,
                        :raw_json, :created_at, :updated_at, :publish_date, :issuing_authority,
                        :district, :district_code, :source_url, :source_name, :fresh_score,
                        :first_seen_at, :last_seen_at
                    )
                    """,
                    params,
                )
                inserted += 1
                continue

            changed = any(
                str(existing[column] or "") != str(params[column] or "")
                for column in _PLANNING_COMPARE_COLUMNS
            )
            params["existing_id"] = existing["id"]
            params["first_seen_at"] = existing["first_seen_at"] or existing["created_at"] or now
            if changed:
                conn.execute(
                    """
                    UPDATE construction_permits SET
                        company_name=:company_name,
                        project_name=:project_name,
                        permit_type=:permit_type,
                        permit_date=:permit_date,
                        address=:address,
                        source=:source,
                        construction_unit=:construction_unit,
                        permit_number=:permit_number,
                        update_time=:update_time,
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
                        last_seen_at=:last_seen_at
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
            (PLANNING_CONSTRUCTION_PERMIT_TYPE,),
        ).fetchone()["count"]

    return UpsertSummary(
        fetched_count=len(records),
        inserted_count=inserted,
        updated_count=updated,
        total_count=int(total),
        skipped_count=skipped,
    )


_PLANNING_COMPARE_COLUMNS = (
    "company_name",
    "project_name",
    "permit_type",
    "permit_date",
    "publish_date",
    "address",
    "issuing_authority",
    "district",
    "district_code",
    "source_url",
    "source_name",
    "permit_number",
)


def _find_existing_planning_permit(
    conn: sqlite3.Connection,
    params: dict[str, Any],
) -> sqlite3.Row | None:
    permit_number = params["permit_number"]
    if _is_known(permit_number):
        row = conn.execute(
            "SELECT * FROM construction_permits WHERE permit_number = ? ORDER BY id LIMIT 1",
            (permit_number,),
        ).fetchone()
        if row is not None:
            return row
    source_url = params["source_url"]
    if source_url:
        row = conn.execute(
            "SELECT * FROM construction_permits WHERE source_url = ? OR source = ? ORDER BY id LIMIT 1",
            (source_url, source_url),
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


def save_crawler_run(
    db_path: Path,
    run_started_at: str,
    run_finished_at: str,
    source: str,
    summary: UpsertSummary,
    status: str,
    error_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    init_db(db_path)
    with db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crawler_runs (
                run_started_at, run_finished_at, source, fetched_count, inserted_count,
                updated_count, total_count, status, error_message, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_started_at,
                run_finished_at,
                source,
                summary.fetched_count,
                summary.inserted_count,
                summary.updated_count,
                summary.total_count,
                status,
                error_message,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )


def load_opportunities(db_path: Path, limit: int | None = None) -> list[OpportunityRecord]:
    init_db(db_path)
    sql = """
        SELECT * FROM enterprise_opportunities
        ORDER BY opportunity_score DESC, event_time DESC, id DESC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with db_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_to_record(row) for row in rows]


def count_opportunities(db_path: Path) -> int:
    init_db(db_path)
    with db_connection(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) AS count FROM enterprise_opportunities").fetchone()["count"])


def count_construction_permits(db_path: Path, permit_type: str | None = None) -> int:
    init_db(db_path)
    with db_connection(db_path) as conn:
        if permit_type:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM construction_permits WHERE permit_type = ?",
                (permit_type,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS count FROM construction_permits").fetchone()
        return int(row["count"])


def load_recent_planning_permit_analysis_candidates(
    db_path: Path,
    days: int,
    limit: int,
    today: datetime | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    current_day = (today or datetime.now()).date()
    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                permits.id AS permit_id,
                permits.company_name,
                permits.project_name,
                permits.permit_type,
                permits.permit_number,
                permits.permit_date,
                permits.publish_date,
                permits.address AS project_address,
                permits.issuing_authority,
                permits.district,
                permits.district_code,
                permits.source_url,
                permits.source_name,
                analyses.input_hash AS analysis_input_hash,
                analyses.ai_opportunity_level,
                analyses.financing_need,
                analyses.recommended_products_json,
                analyses.marketing_summary,
                analyses.visit_suggestion,
                analyses.reasoning_summary,
                analyses.confidence,
                analyses.risk_notice,
                analyses.api_model,
                analyses.analyzed_at
            FROM construction_permits AS permits
            LEFT JOIN permit_ai_analyses AS analyses ON analyses.permit_id = permits.id
            WHERE permits.permit_type = ?
            ORDER BY
                CASE WHEN permits.permit_date <> ? THEN permits.permit_date ELSE permits.publish_date END DESC,
                permits.id DESC
            """,
            (PLANNING_CONSTRUCTION_PERMIT_TYPE, UNKNOWN),
        ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        effective_date = _parse_date_value(
            item["permit_date"] if _is_known(item["permit_date"]) else item["publish_date"]
        )
        if effective_date is None:
            continue
        age = (current_day - effective_date).days
        if 0 <= age <= max(0, days):
            item["recommended_products"] = _json_string_list(item.pop("recommended_products_json", ""))
            candidates.append(item)
            if len(candidates) >= max(0, limit):
                break
    return candidates


def save_permit_ai_analysis(
    db_path: Path,
    permit_id: int,
    input_hash: str,
    analysis: dict[str, Any],
    api_model: str,
) -> None:
    init_db(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO permit_ai_analyses (
                permit_id,
                input_hash,
                ai_opportunity_level,
                financing_need,
                recommended_products_json,
                marketing_summary,
                visit_suggestion,
                reasoning_summary,
                confidence,
                risk_notice,
                api_model,
                analyzed_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(permit_id) DO UPDATE SET
                input_hash=excluded.input_hash,
                ai_opportunity_level=excluded.ai_opportunity_level,
                financing_need=excluded.financing_need,
                recommended_products_json=excluded.recommended_products_json,
                marketing_summary=excluded.marketing_summary,
                visit_suggestion=excluded.visit_suggestion,
                reasoning_summary=excluded.reasoning_summary,
                confidence=excluded.confidence,
                risk_notice=excluded.risk_notice,
                api_model=excluded.api_model,
                analyzed_at=excluded.analyzed_at,
                updated_at=excluded.updated_at
            """,
            (
                permit_id,
                input_hash,
                analysis["ai_opportunity_level"],
                analysis["financing_need"],
                json.dumps(analysis["recommended_products"], ensure_ascii=False),
                analysis["marketing_summary"],
                analysis["visit_suggestion"],
                analysis["reasoning_summary"],
                int(analysis["confidence"]),
                analysis["risk_notice"],
                api_model,
                now,
                now,
            ),
        )


def load_public_planning_construction_permits(db_path: Path) -> list[dict[str, Any]]:
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
                owner_name,
                owner_category,
                ownership_type,
                ownership_confidence,
                ownership_basis,
                marketing_eligible,
                marketing_priority,
                exclusion_reason,
                manual_review_required,
                classification_updated_at,
                analyses.ai_opportunity_level,
                analyses.financing_need,
                analyses.recommended_products_json,
                analyses.marketing_summary,
                analyses.visit_suggestion,
                analyses.reasoning_summary,
                analyses.confidence,
                analyses.risk_notice
            FROM construction_permits AS permits
            LEFT JOIN permit_ai_analyses AS analyses ON analyses.permit_id = permits.id
            WHERE permits.permit_type = ?
            ORDER BY
                CASE WHEN permits.permit_date <> ? THEN permits.permit_date ELSE permits.publish_date END DESC,
                permits.id DESC
            """,
            (PLANNING_CONSTRUCTION_PERMIT_TYPE, UNKNOWN),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["recommended_products"] = _json_string_list(item.pop("recommended_products_json", ""))
        result.append(item)
    return result


def _json_string_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _parse_date_value(value: Any):
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def record_hash(record: OpportunityRecord) -> str:
    key = "|".join(
        [
            normalize_key(record.source_url),
            normalize_key(record.enterprise_name),
            normalize_key(record.project_name),
            normalize_key(record.source),
            normalize_key(record.event_time),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def construction_permit_hash(record: Any) -> str:
    permit_number = normalize_key(getattr(record, "permit_number", ""))
    source_url = normalize_key(getattr(record, "source_url", ""))
    if _is_known(permit_number):
        key = "|".join(["permit_number", permit_number])
    elif source_url:
        key = "|".join(["source_url", source_url])
    else:
        key = "|".join(
            [
                "project_permit_date",
                normalize_key(getattr(record, "project_name", "")),
                normalize_key(getattr(record, "permit_type", "")),
                normalize_key(getattr(record, "permit_date", "")),
            ]
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def planning_construction_permit_to_params(
    record: Any,
    item_hash: str,
    now: str,
) -> dict[str, Any]:
    source_url = getattr(record, "source_url", "") or getattr(record, "detail_url", "") or ""
    permit_date = getattr(record, "permit_date", UNKNOWN) or UNKNOWN
    publish_date = getattr(record, "publish_date", UNKNOWN) or UNKNOWN
    return {
        "record_hash": item_hash,
        "company_name": getattr(record, "company_name", UNKNOWN) or UNKNOWN,
        "project_name": getattr(record, "project_name", UNKNOWN) or UNKNOWN,
        "permit_type": PLANNING_CONSTRUCTION_PERMIT_TYPE,
        "permit_date": permit_date,
        "address": getattr(record, "project_address", UNKNOWN) or UNKNOWN,
        "investment": UNKNOWN,
        "score": 0,
        "source": source_url,
        "construction_unit": getattr(record, "construction_unit", UNKNOWN) or UNKNOWN,
        "permit_number": getattr(record, "permit_number", UNKNOWN) or UNKNOWN,
        "project_scale": UNKNOWN,
        "industry": UNKNOWN,
        "update_time": publish_date if publish_date != UNKNOWN else permit_date,
        "project_stage": "建设审批",
        "customer_level": "C",
        "raw_json": json.dumps(getattr(record, "raw", {}) or {}, ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
        "publish_date": publish_date,
        "issuing_authority": getattr(record, "issuing_authority", UNKNOWN) or UNKNOWN,
        "district": "海门区",
        "district_code": "320684",
        "source_url": source_url,
        "source_name": getattr(record, "source_name", UNKNOWN) or UNKNOWN,
        "fresh_score": int(getattr(record, "fresh_score", 0) or 0),
        "first_seen_at": now,
        "last_seen_at": now,
    }


def construction_permit_to_params(record: Any, item_hash: str, now: str) -> dict[str, Any]:
    return {
        "record_hash": item_hash,
        "company_name": getattr(record, "company_name", UNKNOWN) or UNKNOWN,
        "project_name": getattr(record, "project_name", UNKNOWN) or UNKNOWN,
        "permit_type": getattr(record, "permit_type", UNKNOWN) or UNKNOWN,
        "permit_date": getattr(record, "permit_date", UNKNOWN) or UNKNOWN,
        "address": getattr(record, "project_address", UNKNOWN) or UNKNOWN,
        "investment": getattr(record, "investment_amount", UNKNOWN) or UNKNOWN,
        "score": int(getattr(record, "loan_opportunity_score", 0) or 0),
        "source": getattr(record, "source_url", "") or "",
        "construction_unit": getattr(record, "construction_unit", UNKNOWN) or UNKNOWN,
        "permit_number": getattr(record, "permit_number", UNKNOWN) or UNKNOWN,
        "project_scale": getattr(record, "project_scale", UNKNOWN) or UNKNOWN,
        "industry": getattr(record, "industry", UNKNOWN) or UNKNOWN,
        "update_time": getattr(record, "update_time", UNKNOWN) or UNKNOWN,
        "project_stage": getattr(record, "project_stage", UNKNOWN) or UNKNOWN,
        "customer_level": getattr(record, "customer_level", "C") or "C",
        "raw_json": json.dumps(getattr(record, "raw", {}) or {}, ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    }


def record_to_params(record: OpportunityRecord, item_hash: str, now: str) -> dict[str, Any]:
    return {
        "record_hash": item_hash,
        "enterprise_name": record.enterprise_name or UNKNOWN,
        "project_name": record.project_name or UNKNOWN,
        "source": record.source or UNKNOWN,
        "event_time": record.event_time or UNKNOWN,
        "amount": record.amount or UNKNOWN,
        "industry": record.industry or UNKNOWN,
        "region": record.region or UNKNOWN,
        "opportunity_level": record.opportunity_level or "C",
        "recommended_loan_product": record.recommended_loan_product or UNKNOWN,
        "approval_type": record.approval_type or UNKNOWN,
        "stage": record.stage or UNKNOWN,
        "source_url": record.source_url or "",
        "source_title": record.source_title or "",
        "publish_time": record.publish_time or UNKNOWN,
        "update_time": record.update_time or UNKNOWN,
        "fresh_score": int(record.fresh_score or 0),
        "opportunity_score": float(record.opportunity_score or 0.0),
        "land_area": record.land_area or UNKNOWN,
        "construction_location": record.construction_location or UNKNOWN,
        "manager_view_json": json.dumps(record.manager_view or {}, ensure_ascii=False),
        "raw_json": json.dumps(record.raw or {}, ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    }


def row_to_record(row: sqlite3.Row) -> OpportunityRecord:
    return OpportunityRecord(
        enterprise_name=row["enterprise_name"],
        project_name=row["project_name"],
        source=row["source"],
        event_time=row["event_time"],
        amount=row["amount"],
        industry=row["industry"],
        region=row["region"],
        opportunity_level=row["opportunity_level"],
        recommended_loan_product=row["recommended_loan_product"],
        approval_type=row["approval_type"],
        stage=row["stage"],
        source_url=row["source_url"],
        source_title=row["source_title"],
        publish_time=row["publish_time"],
        update_time=row["update_time"],
        fresh_score=int(row["fresh_score"]),
        opportunity_score=float(row["opportunity_score"]),
        land_area=row["land_area"],
        construction_location=row["construction_location"],
        manager_view=json.loads(row["manager_view_json"] or "{}"),
        raw=json.loads(row["raw_json"] or "{}"),
    )


def normalize_key(value: str) -> str:
    return " ".join(str(value or "").split()).lower()


def _is_known(value: str) -> bool:
    return normalize_key(value) not in {"", normalize_key(UNKNOWN)}
