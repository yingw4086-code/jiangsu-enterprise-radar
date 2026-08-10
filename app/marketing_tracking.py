from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


MARKETING_STATUSES = (
    "未联系",
    "已电话",
    "已拜访",
    "资料收集中",
    "授信审批中",
    "已放款",
    "暂缓",
)
ALL_STATUS_FILTER = "全部"
DEFAULT_CUSTOMER_MANAGER = "未分配"

MARKETING_RECORD_COLUMNS = (
    "id",
    "enterprise_name",
    "project_name",
    "region",
    "discovery_date",
    "customer_manager",
    "status",
    "follow_date",
    "estimated_credit_amount",
    "notes",
)


class MarketingTrackingValidationError(ValueError):
    """Raised when a marketing tracking input is invalid."""


@dataclass(frozen=True)
class MarketingRecord:
    id: int
    enterprise_name: str
    project_name: str
    region: str
    discovery_date: str
    customer_manager: str
    status: str
    follow_date: str
    estimated_credit_amount: float
    notes: str

    @property
    def latest_follow_time(self) -> str:
        return self.follow_date or "尚未跟进"


def ensure_marketing_records_table(connection: sqlite3.Connection) -> None:
    status_values = ", ".join(f"'{status}'" for status in MARKETING_STATUSES)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS marketing_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enterprise_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            region TEXT NOT NULL,
            discovery_date TEXT NOT NULL,
            customer_manager TEXT NOT NULL DEFAULT '{DEFAULT_CUSTOMER_MANAGER}',
            status TEXT NOT NULL DEFAULT '未联系'
                CHECK(status IN ({status_values})),
            follow_date TEXT NOT NULL DEFAULT '',
            estimated_credit_amount REAL NOT NULL DEFAULT 0
                CHECK(estimated_credit_amount >= 0),
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE(enterprise_name, project_name, region)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketing_status_follow_date
        ON marketing_records(status, follow_date DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketing_manager_follow_date
        ON marketing_records(customer_manager, follow_date DESC)
        """
    )


def add_marketing_record(
    db_path: Path,
    *,
    enterprise_name: str,
    project_name: str,
    region: str,
    discovery_date: str | None = None,
    customer_manager: str = DEFAULT_CUSTOMER_MANAGER,
    status: str = "未联系",
    follow_date: str = "",
    estimated_credit_amount: float = 0,
    notes: str = "",
) -> MarketingRecord:
    normalized = _validated_values(
        enterprise_name=enterprise_name,
        project_name=project_name,
        region=region,
        discovery_date=discovery_date or date.today().isoformat(),
        customer_manager=customer_manager,
        status=status,
        follow_date=follow_date,
        estimated_credit_amount=estimated_credit_amount,
        notes=notes,
    )
    connection = _connect(db_path)
    try:
        with connection:
            ensure_marketing_records_table(connection)
            connection.execute(
                """
                INSERT INTO marketing_records(
                    enterprise_name,
                    project_name,
                    region,
                    discovery_date,
                    customer_manager,
                    status,
                    follow_date,
                    estimated_credit_amount,
                    notes
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(enterprise_name, project_name, region) DO NOTHING
                """,
                normalized,
            )
        row = connection.execute(
            """
            SELECT id, enterprise_name, project_name, region, discovery_date,
                   customer_manager, status, follow_date,
                   estimated_credit_amount, notes
            FROM marketing_records
            WHERE enterprise_name = ? AND project_name = ? AND region = ?
            """,
            normalized[:3],
        ).fetchone()
        if row is None:
            raise RuntimeError("营销跟踪记录写入后无法读取")
        return _record_from_row(row)
    finally:
        connection.close()


def get_marketing_record(
    db_path: Path,
    *,
    enterprise_name: str,
    project_name: str,
    region: str,
) -> MarketingRecord | None:
    identity = (
        _required_text(enterprise_name, "enterprise_name"),
        _required_text(project_name, "project_name"),
        _required_text(region, "region"),
    )
    connection = _connect(db_path)
    try:
        with connection:
            ensure_marketing_records_table(connection)
        row = connection.execute(
            """
            SELECT id, enterprise_name, project_name, region, discovery_date,
                   customer_manager, status, follow_date,
                   estimated_credit_amount, notes
            FROM marketing_records
            WHERE enterprise_name = ? AND project_name = ? AND region = ?
            """,
            identity,
        ).fetchone()
        return _record_from_row(row) if row is not None else None
    finally:
        connection.close()


def list_marketing_records(
    db_path: Path,
    *,
    status: str = ALL_STATUS_FILTER,
    customer_manager: str | None = None,
) -> list[MarketingRecord]:
    if status != ALL_STATUS_FILTER and status not in MARKETING_STATUSES:
        raise MarketingTrackingValidationError(f"无效跟进状态：{status}")

    conditions: list[str] = []
    parameters: list[str] = []
    if status != ALL_STATUS_FILTER:
        conditions.append("status = ?")
        parameters.append(status)
    if customer_manager is not None:
        conditions.append("customer_manager = ?")
        parameters.append(_required_text(customer_manager, "customer_manager"))
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    connection = _connect(db_path)
    try:
        with connection:
            ensure_marketing_records_table(connection)
        rows = connection.execute(
            f"""
            SELECT id, enterprise_name, project_name, region, discovery_date,
                   customer_manager, status, follow_date,
                   estimated_credit_amount, notes
            FROM marketing_records
            {where_clause}
            ORDER BY
                CASE WHEN follow_date = '' THEN 1 ELSE 0 END,
                follow_date DESC,
                discovery_date DESC,
                id DESC
            """,
            parameters,
        ).fetchall()
        return [_record_from_row(row) for row in rows]
    finally:
        connection.close()


def update_marketing_record(
    db_path: Path,
    record_id: int,
    *,
    customer_manager: str,
    status: str,
    follow_date: str,
    estimated_credit_amount: float,
    notes: str,
) -> MarketingRecord:
    normalized_id = _positive_integer(record_id, "record_id")
    manager = _required_text(customer_manager, "customer_manager")
    normalized_status = _status(status)
    normalized_follow_date = _date_text(follow_date, "follow_date", allow_empty=True)
    if normalized_status != "未联系" and not normalized_follow_date:
        normalized_follow_date = date.today().isoformat()
    amount = _nonnegative_amount(estimated_credit_amount)
    normalized_notes = str(notes or "").strip()

    connection = _connect(db_path)
    try:
        with connection:
            ensure_marketing_records_table(connection)
            cursor = connection.execute(
                """
                UPDATE marketing_records
                SET customer_manager = ?,
                    status = ?,
                    follow_date = ?,
                    estimated_credit_amount = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    manager,
                    normalized_status,
                    normalized_follow_date,
                    amount,
                    normalized_notes,
                    normalized_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"营销跟踪记录不存在：{normalized_id}")
        row = connection.execute(
            """
            SELECT id, enterprise_name, project_name, region, discovery_date,
                   customer_manager, status, follow_date,
                   estimated_credit_amount, notes
            FROM marketing_records
            WHERE id = ?
            """,
            (normalized_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"营销跟踪记录不存在：{normalized_id}")
        return _record_from_row(row)
    finally:
        connection.close()


def _validated_values(
    *,
    enterprise_name: str,
    project_name: str,
    region: str,
    discovery_date: str,
    customer_manager: str,
    status: str,
    follow_date: str,
    estimated_credit_amount: float,
    notes: str,
) -> tuple[str, str, str, str, str, str, str, float, str]:
    return (
        _required_text(enterprise_name, "enterprise_name"),
        _required_text(project_name, "project_name"),
        _required_text(region, "region"),
        _date_text(discovery_date, "discovery_date"),
        _required_text(customer_manager, "customer_manager"),
        _status(status),
        _date_text(follow_date, "follow_date", allow_empty=True),
        _nonnegative_amount(estimated_credit_amount),
        str(notes or "").strip(),
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _record_from_row(row: sqlite3.Row) -> MarketingRecord:
    return MarketingRecord(
        id=int(row["id"]),
        enterprise_name=str(row["enterprise_name"]),
        project_name=str(row["project_name"]),
        region=str(row["region"]),
        discovery_date=str(row["discovery_date"]),
        customer_manager=str(row["customer_manager"]),
        status=str(row["status"]),
        follow_date=str(row["follow_date"]),
        estimated_credit_amount=float(row["estimated_credit_amount"] or 0),
        notes=str(row["notes"]),
    )


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MarketingTrackingValidationError(f"{field_name} 不能为空")
    return text


def _status(value: Any) -> str:
    status = str(value or "").strip()
    if status not in MARKETING_STATUSES:
        raise MarketingTrackingValidationError(f"无效跟进状态：{status}")
    return status


def _date_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if allow_empty and not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise MarketingTrackingValidationError(
            f"{field_name} 必须为 YYYY-MM-DD"
        ) from exc


def _nonnegative_amount(value: Any) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise MarketingTrackingValidationError("estimated_credit_amount 必须为数字") from exc
    if amount < 0:
        raise MarketingTrackingValidationError("estimated_credit_amount 不能小于0")
    return amount


def _positive_integer(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise MarketingTrackingValidationError(f"{field_name} 必须为正整数") from exc
    if number <= 0:
        raise MarketingTrackingValidationError(f"{field_name} 必须为正整数")
    return number
