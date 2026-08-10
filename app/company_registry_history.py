from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


COMPANY_REGISTRY_HISTORY_COLUMNS = (
    "id",
    "company_name",
    "field_name",
    "old_value",
    "new_value",
    "change_type",
    "changed_at",
    "change_source",
    "import_file_name",
    "file_sha256",
)


@dataclass(frozen=True)
class CompanyRegistryHistoryRecord:
    id: int
    company_name: str
    field_name: str
    old_value: str
    new_value: str
    change_type: str
    changed_at: str
    change_source: str
    import_file_name: str
    file_sha256: str


def ensure_company_registry_history_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_registry_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT NOT NULL DEFAULT '',
            new_value TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            change_source TEXT NOT NULL DEFAULT 'excel_import',
            import_file_name TEXT NOT NULL DEFAULT '',
            file_sha256 TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_registry_history_company
        ON company_registry_history(company_name)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_registry_history_changed_at
        ON company_registry_history(changed_at)
        """
    )


def record_company_registry_changes(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    old_values: dict[str, str],
    new_values: dict[str, str],
    changed_at: str,
    change_source: str,
    import_file_name: str,
    file_sha256: str,
) -> int:
    """Record only non-blank incoming values that actually changed."""

    ensure_company_registry_history_table(connection)
    rows = []
    for field_name, incoming_value in new_values.items():
        new_value = str(incoming_value or "").strip()
        if not new_value:
            continue
        old_value = str(old_values.get(field_name) or "").strip()
        if old_value == new_value:
            continue
        rows.append(
            (
                company_name,
                field_name,
                old_value,
                new_value,
                "update" if old_value else "insert",
                changed_at,
                str(change_source or "excel_import").strip(),
                str(import_file_name or "").strip(),
                str(file_sha256 or "").strip().upper(),
            )
        )
    connection.executemany(
        """
        INSERT INTO company_registry_history(
            company_name, field_name, old_value, new_value, change_type,
            changed_at, change_source, import_file_name, file_sha256
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def list_company_registry_history(
    db_path: Path,
    *,
    company_name: str = "",
    limit: int = 100,
) -> list[CompanyRegistryHistoryRecord]:
    selected_limit = max(1, min(int(limit), 1000))
    connection = sqlite3.connect(Path(db_path), timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        ensure_company_registry_history_table(connection)
        if company_name:
            rows = connection.execute(
                """
                SELECT id, company_name, field_name, old_value, new_value,
                       change_type, changed_at, change_source,
                       import_file_name, file_sha256
                FROM company_registry_history
                WHERE company_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (company_name, selected_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, company_name, field_name, old_value, new_value,
                       change_type, changed_at, change_source,
                       import_file_name, file_sha256
                FROM company_registry_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (selected_limit,),
            ).fetchall()
        return [CompanyRegistryHistoryRecord(**dict(row)) for row in rows]
    finally:
        connection.close()
