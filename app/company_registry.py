from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from app.company_data_provider import CompanyDataProvider
from app.company_matcher import CompanyRegistryMatcher, normalize_company_name


UNKNOWN = "未披露"
REGISTRY_REQUIRED_FIELDS = (
    "company_name",
    "unified_social_credit_code",
    "legal_person",
    "registered_capital",
    "establish_date",
    "company_address",
    "business_scope",
    "company_status",
    "industry",
)
COMPANY_REGISTRY_COLUMNS = (
    "id",
    *REGISTRY_REQUIRED_FIELDS,
    "data_source",
    "source_url",
    "verified_at",
    "created_at",
    "updated_at",
)
_CREDIT_CODE_PATTERN = re.compile(r"^[0-9A-Z]{18}$")
REGISTRY_COMPLETENESS_FIELDS = (
    "unified_social_credit_code",
    "legal_person",
    "registered_capital",
    "establish_date",
    "company_address",
    "business_scope",
    "company_status",
    "industry",
)
REGISTRY_COMPLETENESS_LABELS = {
    "A": "A 完整",
    "B": "B 较完整",
    "C": "C 基础",
    "D": "D 待补充",
}
INVALID_COMPANY_NAME_KEYS = {
    normalize_company_name(value)
    for value in ("未披露", "未知", "建设单位暂未披露", "None", "null")
}


class CompanyRegistryValidationError(ValueError):
    """Raised when registry input is incomplete or malformed."""


CompanyRegistryProvider = CompanyDataProvider


@dataclass(frozen=True)
class CompanyRegistryRecord:
    company_name: str
    unified_social_credit_code: str = ""
    legal_person: str = ""
    registered_capital: str = ""
    establish_date: str = ""
    company_address: str = ""
    business_scope: str = ""
    company_status: str = ""
    industry: str = ""
    data_source: str = ""
    source_url: str = ""
    verified_at: str = ""
    id: int | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_fields(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegistryCompletenessAssessment:
    percentage: int
    level: str
    label: str
    filled_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]

    def to_fields(self) -> dict[str, Any]:
        return {
            "registry_completeness_percentage": self.percentage,
            "registry_completeness_level": self.level,
            "registry_completeness_label": self.label,
            "registry_completeness_filled_fields": list(self.filled_fields),
            "registry_completeness_missing_fields": list(self.missing_fields),
        }


@dataclass(frozen=True)
class CompanyExcelImportResult:
    total_count: int
    inserted_count: int
    updated_count: int
    matched_existing_count: int
    history_count: int = 0


@dataclass(frozen=True)
class PreparedCompanyExcelImport:
    records: tuple[CompanyRegistryRecord, ...]
    inserted_count: int
    updated_count: int
    matched_existing_count: int

    @property
    def total_count(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class RegistryCoverageSummary:
    total_project_count: int
    matched_project_count: int
    matched_company_count: int
    coverage_percentage: float


def summarize_registry_coverage(
    items: list[Mapping[str, Any]],
) -> RegistryCoverageSummary:
    matched_items = [item for item in items if item.get("registry_data_available")]
    matched_company_names = {
        normalize_company_name(_company_name(item))
        for item in matched_items
        if _company_name(item)
    }
    total_project_count = len(items)
    coverage_percentage = (
        round(len(matched_items) * 100 / total_project_count, 1)
        if total_project_count
        else 0.0
    )
    return RegistryCoverageSummary(
        total_project_count=total_project_count,
        matched_project_count=len(matched_items),
        matched_company_count=len(matched_company_names),
        coverage_percentage=coverage_percentage,
    )


def ensure_company_registry_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL UNIQUE,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            legal_person TEXT NOT NULL DEFAULT '',
            registered_capital TEXT NOT NULL DEFAULT '',
            establish_date TEXT NOT NULL DEFAULT '',
            company_address TEXT NOT NULL DEFAULT '',
            business_scope TEXT NOT NULL DEFAULT '',
            company_status TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            data_source TEXT NOT NULL DEFAULT 'manual',
            source_url TEXT NOT NULL DEFAULT '',
            verified_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_company_registry_credit_code
        ON company_registry(unified_social_credit_code)
        WHERE unified_social_credit_code <> ''
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_registry_status
        ON company_registry(company_status)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_registry_industry
        ON company_registry(industry)
        """
    )


def upsert_company_registry_record(
    db_path: Path,
    record: CompanyRegistryRecord,
) -> CompanyRegistryRecord:
    normalized = _validated_record(record)
    now = datetime.now().isoformat(timespec="seconds")
    connection = _connect(db_path)
    try:
        with connection:
            ensure_company_registry_table(connection)
            _upsert_company_registry_record(connection, normalized, now=now)
        stored = get_company_registry_record(db_path, normalized.company_name)
        if stored is None:
            raise RuntimeError("工商基础信息写入后无法读取")
        return stored
    finally:
        connection.close()


def _upsert_company_registry_record(
    connection: sqlite3.Connection,
    record: CompanyRegistryRecord,
    *,
    now: str,
) -> None:
    existing_source_row = connection.execute(
        "SELECT data_source FROM company_registry WHERE company_name = ?",
        (record.company_name,),
    ).fetchone()
    data_source = record.data_source or (
        str(existing_source_row[0]) if existing_source_row else "manual"
    )
    connection.execute(
        """
        INSERT INTO company_registry(
            company_name,
            unified_social_credit_code,
            legal_person,
            registered_capital,
            establish_date,
            company_address,
            business_scope,
            company_status,
            industry,
            data_source,
            source_url,
            verified_at,
            created_at,
            updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_name) DO UPDATE SET
            unified_social_credit_code=COALESCE(
                NULLIF(excluded.unified_social_credit_code, ''),
                company_registry.unified_social_credit_code
            ),
            legal_person=COALESCE(
                NULLIF(excluded.legal_person, ''),
                company_registry.legal_person
            ),
            registered_capital=COALESCE(
                NULLIF(excluded.registered_capital, ''),
                company_registry.registered_capital
            ),
            establish_date=COALESCE(
                NULLIF(excluded.establish_date, ''),
                company_registry.establish_date
            ),
            company_address=COALESCE(
                NULLIF(excluded.company_address, ''),
                company_registry.company_address
            ),
            business_scope=COALESCE(
                NULLIF(excluded.business_scope, ''),
                company_registry.business_scope
            ),
            company_status=COALESCE(
                NULLIF(excluded.company_status, ''),
                company_registry.company_status
            ),
            industry=COALESCE(
                NULLIF(excluded.industry, ''),
                company_registry.industry
            ),
            data_source=COALESCE(
                NULLIF(excluded.data_source, ''),
                company_registry.data_source
            ),
            source_url=COALESCE(
                NULLIF(excluded.source_url, ''),
                company_registry.source_url
            ),
            verified_at=COALESCE(
                NULLIF(excluded.verified_at, ''),
                company_registry.verified_at
            ),
            updated_at=excluded.updated_at
        """,
        (
            record.company_name,
            record.unified_social_credit_code,
            record.legal_person,
            record.registered_capital,
            record.establish_date,
            record.company_address,
            record.business_scope,
            record.company_status,
            record.industry,
            data_source,
            record.source_url,
            record.verified_at,
            now,
            now,
        ),
    )


def validate_company_registry_record(
    record: CompanyRegistryRecord,
) -> CompanyRegistryRecord:
    return _validated_record(record)


def get_company_registry_record(
    db_path: Path,
    company_name: str,
) -> CompanyRegistryRecord | None:
    normalized_name = _required_text(company_name, "company_name")
    connection = _connect(db_path)
    try:
        with connection:
            ensure_company_registry_table(connection)
        row = connection.execute(
            """
            SELECT id, company_name, unified_social_credit_code, legal_person,
                   registered_capital, establish_date, company_address,
                   business_scope, company_status, industry, data_source,
                   source_url, verified_at, created_at, updated_at
            FROM company_registry
            WHERE company_name = ?
            """,
            (normalized_name,),
        ).fetchone()
        return _record_from_row(row) if row is not None else None
    finally:
        connection.close()


def list_company_registry_records(db_path: Path) -> list[CompanyRegistryRecord]:
    connection = _connect(db_path)
    try:
        with connection:
            ensure_company_registry_table(connection)
        rows = connection.execute(
            """
            SELECT id, company_name, unified_social_credit_code, legal_person,
                   registered_capital, establish_date, company_address,
                   business_scope, company_status, industry, data_source,
                   source_url, verified_at, created_at, updated_at
            FROM company_registry
            ORDER BY company_name
            """
        ).fetchall()
        return [_record_from_row(row) for row in rows]
    finally:
        connection.close()


def enrich_items_with_company_registry(
    items: list[dict[str, Any]],
    db_path: Path,
) -> list[dict[str, Any]]:
    matcher = CompanyRegistryMatcher(list_company_registry_records(db_path))
    enriched_items = []
    for item in items:
        match = matcher.match(_company_name(item))
        enriched = enrich_item_with_company_registry(item, match.record)
        enriched["company_match_status"] = match.status
        enriched["company_match_method"] = match.match_method
        enriched["matched_registry_company_name"] = (
            match.record.company_name if match.record else ""
        )
        enriched_items.append(enriched)
    return enriched_items


def enrich_item_with_company_registry(
    item: Mapping[str, Any],
    record: CompanyRegistryRecord | None,
) -> dict[str, Any]:
    enriched = dict(item)
    if record is None:
        enriched["registry_data_available"] = False
        enriched["registry_data_source"] = ""
        enriched["registry_disclosed_fields"] = []
        return enriched
    registry_disclosed_fields = []
    for field in REGISTRY_REQUIRED_FIELDS:
        value = getattr(record, field)
        if value:
            enriched[field] = value
            if field in REGISTRY_COMPLETENESS_FIELDS:
                registry_disclosed_fields.append(field)
    enriched["registry_data_available"] = True
    enriched["registry_data_source"] = record.data_source
    enriched["registry_disclosed_fields"] = registry_disclosed_fields
    enriched["registry_source_url"] = record.source_url
    enriched["registry_verified_at"] = record.verified_at
    return enriched


def lookup_and_store_company_registry(
    db_path: Path,
    company_name: str,
    provider: CompanyRegistryProvider,
) -> CompanyRegistryRecord | None:
    """Use an injected provider; this module does not call any API by itself."""

    normalized_name = _required_text(company_name, "company_name")
    record = provider.lookup(normalized_name)
    if record is None:
        return None
    if record.company_name != normalized_name:
        record = CompanyRegistryRecord(
            **(
                record.to_fields()
                | {
                    "id": None,
                    "company_name": normalized_name,
                    "data_source": record.data_source or provider.provider_name,
                    "created_at": "",
                    "updated_at": "",
                }
            )
        )
    elif not record.data_source:
        record = CompanyRegistryRecord(
            **(record.to_fields() | {"data_source": provider.provider_name})
        )
    return upsert_company_registry_record(db_path, record)


def import_company_registry_excel(
    db_path: Path,
    source: bytes | bytearray | Path | BinaryIO,
    *,
    import_file_name: str = "",
    file_sha256: str = "",
    change_source: str = "excel_import",
) -> CompanyExcelImportResult:
    from app.company_registry_history import (
        ensure_company_registry_history_table,
        record_company_registry_changes,
    )

    prepared_import = prepare_company_registry_excel_import(db_path, source)
    connection = _connect(db_path)
    history_count = 0
    try:
        with connection:
            ensure_company_registry_table(connection)
            ensure_company_registry_history_table(connection)
            now = datetime.now().isoformat(timespec="seconds")
            for record in prepared_import.records:
                existing = connection.execute(
                    """
                    SELECT unified_social_credit_code, legal_person,
                           registered_capital, establish_date, company_address,
                           business_scope, company_status, industry
                    FROM company_registry
                    WHERE company_name = ?
                    """,
                    (record.company_name,),
                ).fetchone()
                old_values = (
                    dict(existing) if existing is not None else {}
                )
                new_values = {
                    field: str(getattr(record, field) or "").strip()
                    for field in REGISTRY_COMPLETENESS_FIELDS
                }
                _upsert_company_registry_record(connection, record, now=now)
                history_count += record_company_registry_changes(
                    connection,
                    company_name=record.company_name,
                    old_values=old_values,
                    new_values=new_values,
                    changed_at=now,
                    change_source=change_source,
                    import_file_name=import_file_name,
                    file_sha256=file_sha256,
                )
    finally:
        connection.close()
    return CompanyExcelImportResult(
        total_count=prepared_import.total_count,
        inserted_count=prepared_import.inserted_count,
        updated_count=prepared_import.updated_count,
        matched_existing_count=prepared_import.matched_existing_count,
        history_count=history_count,
    )


def prepare_company_registry_excel_import(
    db_path: Path,
    source: bytes | bytearray | Path | BinaryIO,
) -> PreparedCompanyExcelImport:
    from app.company_data_provider import ExcelCompanyDataProvider

    incoming = ExcelCompanyDataProvider(source).load_records()
    existing_records = list_company_registry_records(db_path)
    matcher = CompanyRegistryMatcher(existing_records)
    existing_credit_codes = {
        record.unified_social_credit_code: record.company_name
        for record in existing_records
        if record.unified_social_credit_code
    }
    prepared: list[CompanyRegistryRecord] = []
    matched_existing_count = 0
    for incoming_item in incoming:
        record = incoming_item.record
        match = matcher.match(record.company_name)
        if match.status == "ambiguous":
            raise CompanyRegistryValidationError(
                f"第 {incoming_item.row_number} 行企业名称匹配不唯一："
                + "、".join(match.candidate_names)
            )
        if match.record is not None:
            matched_existing_count += 1
            record = replace(record, company_name=match.record.company_name)
        normalized = validate_company_registry_record(record)
        credit_owner = existing_credit_codes.get(
            normalized.unified_social_credit_code
        )
        if (
            normalized.unified_social_credit_code
            and credit_owner
            and normalize_company_name(credit_owner)
            != normalize_company_name(normalized.company_name)
        ):
            raise CompanyRegistryValidationError(
                f"第 {incoming_item.row_number} 行统一社会信用代码已属于 {credit_owner}"
            )
        prepared.append(normalized)

    existing_names = {
        normalize_company_name(record.company_name) for record in existing_records
    }
    inserted_count = sum(
        normalize_company_name(record.company_name) not in existing_names
        for record in prepared
    )
    return PreparedCompanyExcelImport(
        records=tuple(prepared),
        inserted_count=inserted_count,
        updated_count=len(prepared) - inserted_count,
        matched_existing_count=matched_existing_count,
    )


def assess_registry_completeness(
    item: Mapping[str, Any],
) -> RegistryCompletenessAssessment:
    disclosed_fields = item.get("registry_disclosed_fields")
    if isinstance(disclosed_fields, (list, tuple, set)):
        disclosed_field_names = {str(field) for field in disclosed_fields}
        filled = tuple(
            field
            for field in REGISTRY_COMPLETENESS_FIELDS
            if field in disclosed_field_names and _disclosed(item.get(field))
        )
    elif item.get("registry_data_available") is False:
        filled: tuple[str, ...] = ()
    else:
        filled = tuple(
            field
            for field in REGISTRY_COMPLETENESS_FIELDS
            if _disclosed(item.get(field))
        )
    missing = tuple(
        field for field in REGISTRY_COMPLETENESS_FIELDS if field not in filled
    )
    percentage = round(len(filled) * 100 / len(REGISTRY_COMPLETENESS_FIELDS))
    if percentage >= 90:
        level = "A"
    elif percentage >= 70:
        level = "B"
    elif percentage >= 50:
        level = "C"
    else:
        level = "D"
    return RegistryCompletenessAssessment(
        percentage=percentage,
        level=level,
        label=REGISTRY_COMPLETENESS_LABELS[level],
        filled_fields=filled,
        missing_fields=missing,
    )


def enrich_registry_completeness(item: Mapping[str, Any]) -> dict[str, Any]:
    return dict(item) | assess_registry_completeness(item).to_fields()


def _validated_record(record: CompanyRegistryRecord) -> CompanyRegistryRecord:
    company_name = _required_text(record.company_name, "company_name")
    if normalize_company_name(company_name) in INVALID_COMPANY_NAME_KEYS:
        raise CompanyRegistryValidationError(
            f"company_name 不能使用占位值：{company_name}"
        )
    credit_code = str(record.unified_social_credit_code or "").strip().upper()
    if credit_code and not _CREDIT_CODE_PATTERN.fullmatch(credit_code):
        raise CompanyRegistryValidationError(
            "unified_social_credit_code 必须为空或18位大写字母数字"
        )
    establish_date = str(record.establish_date or "").strip()
    if establish_date:
        try:
            establish_date = datetime.strptime(
                establish_date[:10], "%Y-%m-%d"
            ).date().isoformat()
        except ValueError as exc:
            raise CompanyRegistryValidationError(
                "establish_date 必须为 YYYY-MM-DD"
            ) from exc
    return CompanyRegistryRecord(
        company_name=company_name,
        unified_social_credit_code=credit_code,
        legal_person=str(record.legal_person or "").strip(),
        registered_capital=str(record.registered_capital or "").strip(),
        establish_date=establish_date,
        company_address=str(record.company_address or "").strip(),
        business_scope=str(record.business_scope or "").strip(),
        company_status=str(record.company_status or "").strip(),
        industry=str(record.industry or "").strip(),
        data_source=str(record.data_source or "").strip(),
        source_url=str(record.source_url or "").strip(),
        verified_at=str(record.verified_at or "").strip(),
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _record_from_row(row: sqlite3.Row) -> CompanyRegistryRecord:
    return CompanyRegistryRecord(
        id=int(row["id"]),
        company_name=str(row["company_name"]),
        unified_social_credit_code=str(row["unified_social_credit_code"]),
        legal_person=str(row["legal_person"]),
        registered_capital=str(row["registered_capital"]),
        establish_date=str(row["establish_date"]),
        company_address=str(row["company_address"]),
        business_scope=str(row["business_scope"]),
        company_status=str(row["company_status"]),
        industry=str(row["industry"]),
        data_source=str(row["data_source"]),
        source_url=str(row["source_url"]),
        verified_at=str(row["verified_at"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _company_name(item: Mapping[str, Any]) -> str:
    return str(
        item.get("company_name")
        or item.get("construction_unit")
        or item.get("owner_name")
        or ""
    ).strip()


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CompanyRegistryValidationError(f"{field_name} 不能为空")
    return text


def _disclosed(value: Any) -> bool:
    return str(value or "").strip() not in {
        "",
        "未披露",
        "未知",
        "None",
        "null",
    }
