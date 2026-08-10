from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


ENTERPRISE = "enterprise"
GOVERNMENT = "government"
UNKNOWN = "unknown"
PROJECT_TYPES = frozenset({ENTERPRISE, GOVERNMENT, UNKNOWN})
HIGH = "high"
MEDIUM = "medium"
LOW = "low"
CLASSIFICATION_CONFIDENCES = frozenset({HIGH, MEDIUM, LOW})

ENTERPRISE_KEYWORDS = (
    "有限公司",
    "股份有限公司",
    "科技有限公司",
    "制造有限公司",
    "集团",
    "产业有限公司",
    "实业有限公司",
    "新能源",
    "智能装备",
    "电子科技",
    "材料科技",
)

GOVERNMENT_KEYWORDS = (
    "政府",
    "财政",
    "交通局",
    "住建局",
    "自然资源局",
    "市政",
    "道路",
    "桥梁",
    "公园",
    "公共服务",
    "学校",
    "医院",
    "保障房",
)

ENTERPRISE_PROJECT_SIGNALS = (
    "年产",
    "生产基地",
    "产业化",
    "扩建",
    "技改",
    "设备升级",
)


@dataclass(frozen=True)
class ProjectClassification:
    project_type: str
    confidence: str


def classify_project(
    *,
    company_name: Any,
    construction_unit: Any = "",
    project_name: Any = "",
) -> ProjectClassification:
    """Classify a project and report the strength of the matching evidence."""

    company_text = _normalize(company_name)
    construction_text = _normalize(construction_unit)
    project_text = _normalize(project_name)
    subject_text = " ".join((company_text, construction_text))

    if any(keyword in subject_text for keyword in ENTERPRISE_KEYWORDS):
        return ProjectClassification(ENTERPRISE, HIGH)

    government_in_subject = any(
        keyword in subject_text for keyword in GOVERNMENT_KEYWORDS
    )
    government_in_project = any(
        keyword in project_text for keyword in GOVERNMENT_KEYWORDS
    )
    if government_in_subject or government_in_project:
        confidence = HIGH if government_in_subject else MEDIUM
        return ProjectClassification(GOVERNMENT, confidence)

    if any(keyword in project_text for keyword in ENTERPRISE_PROJECT_SIGNALS):
        return ProjectClassification(ENTERPRISE, MEDIUM)

    return ProjectClassification(UNKNOWN, LOW)


def classify_project_type(
    *,
    company_name: Any,
    construction_unit: Any = "",
    project_name: Any = "",
) -> str:
    return classify_project(
        company_name=company_name,
        construction_unit=construction_unit,
        project_name=project_name,
    ).project_type


def classify_project_confidence(
    *,
    company_name: Any,
    construction_unit: Any = "",
    project_name: Any = "",
) -> str:
    return classify_project(
        company_name=company_name,
        construction_unit=construction_unit,
        project_name=project_name,
    ).confidence


def classify_project_record(record: Mapping[str, Any]) -> str:
    return classify_project_type(
        company_name=record.get("company_name"),
        construction_unit=record.get("construction_unit"),
        project_name=record.get("project_name"),
    )


def classify_project_record_result(
    record: Mapping[str, Any],
) -> ProjectClassification:
    return classify_project(
        company_name=record.get("company_name"),
        construction_unit=record.get("construction_unit"),
        project_name=record.get("project_name"),
    )


def _normalize(value: Any) -> str:
    return str(value or "").strip()
