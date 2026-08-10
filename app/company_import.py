from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from app.company_matcher import normalize_company_name
from app.company_registry import (
    CompanyExcelImportResult,
    CompanyRegistryRecord,
    import_company_registry_excel,
    list_company_registry_records,
    prepare_company_registry_excel_import,
)


COMPANY_IMPORT_LOG_COLUMNS = (
    "id",
    "import_time",
    "file_name",
    "total_count",
    "success_count",
    "failed_count",
    "inserted_count",
    "updated_count",
    "status",
    "error_message",
    "file_sha256",
)


class CompanyImportConfirmationError(ValueError):
    """Raised when the confirmed file differs from the previewed file."""


@dataclass(frozen=True)
class CompanyImportPreviewRow:
    row_number: int
    record: CompanyRegistryRecord
    import_action: str
    permit_match_count: int

    def to_display_row(self) -> dict[str, Any]:
        return {
            "Excel行号": self.row_number,
            "导入动作": self.import_action,
            "企业名称": self.record.company_name,
            "许可证项目匹配数": self.permit_match_count,
            "统一社会信用代码": self.record.unified_social_credit_code,
            "法人": self.record.legal_person,
            "注册资本": self.record.registered_capital,
            "成立日期": self.record.establish_date,
            "注册地址": self.record.company_address,
            "经营范围": self.record.business_scope,
            "企业状态": self.record.company_status,
            "行业": self.record.industry,
        }


@dataclass(frozen=True)
class CompanyImportPreview:
    file_name: str
    file_sha256: str
    total_count: int
    inserted_count: int
    updated_count: int
    permit_matched_company_count: int
    permit_matched_project_count: int
    rows: tuple[CompanyImportPreviewRow, ...]

    def to_display_rows(self) -> list[dict[str, Any]]:
        return [row.to_display_row() for row in self.rows]


@dataclass(frozen=True)
class CompanyImportLog:
    id: int
    import_time: str
    file_name: str
    total_count: int
    success_count: int
    failed_count: int
    inserted_count: int
    updated_count: int
    status: str
    error_message: str
    file_sha256: str

    def to_display_row(self) -> dict[str, Any]:
        return {
            "导入时间": self.import_time,
            "文件名称": self.file_name,
            "成功数量": self.success_count,
            "失败数量": self.failed_count,
            "新增数量": self.inserted_count,
            "更新数量": self.updated_count,
            "状态": "成功" if self.status == "success" else "失败",
            "错误信息": self.error_message,
        }


def ensure_company_import_logs_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_import_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_time TEXT NOT NULL,
            file_name TEXT NOT NULL,
            total_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN ('success', 'failed')),
            error_message TEXT NOT NULL DEFAULT '',
            file_sha256 TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_import_logs_import_time
        ON company_import_logs(import_time DESC)
        """
    )


def preview_company_registry_excel(
    db_path: Path,
    source: bytes | bytearray | Path,
    *,
    file_name: str,
    permit_items: list[Mapping[str, Any]],
) -> CompanyImportPreview:
    raw = _source_bytes(source)
    prepared = prepare_company_registry_excel_import(db_path, raw)
    existing_names = {
        normalize_company_name(record.company_name)
        for record in list_company_registry_records(db_path)
    }
    permit_counts = Counter(
        normalize_company_name(_permit_company_name(item))
        for item in permit_items
        if _permit_company_name(item)
    )
    rows = tuple(
        CompanyImportPreviewRow(
            row_number=index + 2,
            record=record,
            import_action=(
                "更新"
                if normalize_company_name(record.company_name) in existing_names
                else "新增"
            ),
            permit_match_count=permit_counts.get(
                normalize_company_name(record.company_name),
                0,
            ),
        )
        for index, record in enumerate(prepared.records)
    )
    return CompanyImportPreview(
        file_name=_safe_file_name(file_name),
        file_sha256=hashlib.sha256(raw).hexdigest().upper(),
        total_count=prepared.total_count,
        inserted_count=prepared.inserted_count,
        updated_count=prepared.updated_count,
        permit_matched_company_count=sum(row.permit_match_count > 0 for row in rows),
        permit_matched_project_count=sum(row.permit_match_count for row in rows),
        rows=rows,
    )


def execute_company_registry_excel_import(
    db_path: Path,
    source: bytes | bytearray | Path,
    *,
    file_name: str,
    expected_sha256: str,
    expected_total_count: int,
) -> CompanyExcelImportResult:
    raw = _source_bytes(source)
    safe_file_name = _safe_file_name(file_name)
    actual_sha256 = hashlib.sha256(raw).hexdigest().upper()
    if actual_sha256 != str(expected_sha256 or "").strip().upper():
        message = "待导入文件与已确认预览文件不一致，请重新生成预览"
        _record_import_log(
            db_path,
            file_name=safe_file_name,
            total_count=expected_total_count,
            success_count=0,
            failed_count=expected_total_count,
            inserted_count=0,
            updated_count=0,
            status="failed",
            error_message=message,
            file_sha256=actual_sha256,
        )
        raise CompanyImportConfirmationError(message)

    try:
        result = import_company_registry_excel(
            db_path,
            raw,
            import_file_name=safe_file_name,
            file_sha256=actual_sha256,
            change_source="confirmed_excel_import",
        )
    except Exception as exc:
        _record_import_log(
            db_path,
            file_name=safe_file_name,
            total_count=expected_total_count,
            success_count=0,
            failed_count=expected_total_count,
            inserted_count=0,
            updated_count=0,
            status="failed",
            error_message=str(exc),
            file_sha256=actual_sha256,
        )
        raise

    _record_import_log(
        db_path,
        file_name=safe_file_name,
        total_count=result.total_count,
        success_count=result.total_count,
        failed_count=0,
        inserted_count=result.inserted_count,
        updated_count=result.updated_count,
        status="success",
        error_message="",
        file_sha256=actual_sha256,
    )
    return result


def list_company_import_logs(
    db_path: Path,
    *,
    limit: int = 20,
) -> list[CompanyImportLog]:
    selected_limit = max(1, min(int(limit), 100))
    connection = sqlite3.connect(Path(db_path), timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='company_import_logs'
            """
        ).fetchone()
        if table is None:
            return []
        rows = connection.execute(
            """
            SELECT id, import_time, file_name, total_count, success_count,
                   failed_count, inserted_count, updated_count, status,
                   error_message, file_sha256
            FROM company_import_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (selected_limit,),
        ).fetchall()
        return [CompanyImportLog(**dict(row)) for row in rows]
    finally:
        connection.close()


def _record_import_log(
    db_path: Path,
    *,
    file_name: str,
    total_count: int,
    success_count: int,
    failed_count: int,
    inserted_count: int,
    updated_count: int,
    status: str,
    error_message: str,
    file_sha256: str,
) -> None:
    connection = sqlite3.connect(Path(db_path), timeout=10)
    try:
        with connection:
            ensure_company_import_logs_table(connection)
            connection.execute(
                """
                INSERT INTO company_import_logs(
                    import_time, file_name, total_count, success_count,
                    failed_count, inserted_count, updated_count, status,
                    error_message, file_sha256
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    file_name,
                    max(0, int(total_count)),
                    max(0, int(success_count)),
                    max(0, int(failed_count)),
                    max(0, int(inserted_count)),
                    max(0, int(updated_count)),
                    status,
                    str(error_message or "")[:1000],
                    file_sha256,
                ),
            )
    finally:
        connection.close()


def _source_bytes(source: bytes | bytearray | Path) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return Path(source).read_bytes()


def _safe_file_name(file_name: str) -> str:
    name = Path(str(file_name or "")).name.strip()
    if not name:
        raise ValueError("file_name 不能为空")
    return name


def _permit_company_name(item: Mapping[str, Any]) -> str:
    return str(
        item.get("company_name")
        or item.get("construction_unit")
        or item.get("owner_name")
        or ""
    ).strip()
