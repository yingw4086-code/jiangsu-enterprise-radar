from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.storage import load_public_planning_construction_permits


DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "cloud" / "planning_construction_permits.json"
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
    "province",
    "city",
    "region_key",
    "area_code",
    "source_url",
    "source_name",
    "source_region",
    "source_time",
    "fresh_score",
    "first_seen_at",
    "last_seen_at",
    "owner_name",
    "owner_category",
    "ownership_type",
    "ownership_confidence",
    "ownership_basis",
    "marketing_eligible",
    "marketing_priority",
    "exclusion_reason",
    "manual_review_required",
    "classification_updated_at",
    "project_type",
    "classification_confidence",
    "ai_opportunity_level",
    "financing_need",
    "recommended_products",
    "marketing_summary",
    "visit_suggestion",
    "reasoning_summary",
    "confidence",
    "risk_notice",
)


def export_cloud_data(db_path: Path, output_path: Path) -> dict[str, Any]:
    rows = load_public_planning_construction_permits(db_path, region_key=None)
    if not rows:
        return {
            "export_count": 0,
            "output_path": str(output_path),
            "written": False,
            "error": "construction_permits中没有建设工程规划许可证，未创建或覆盖JSON",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出Streamlit Cloud公开许可证数据")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite数据库路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="公开JSON输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = export_cloud_data(Path(args.db_path), Path(args.output))
    print(f"export_count={result['export_count']}")
    print(f"output_path={result['output_path']}")
    print(f"written={result['written']}")
    if result["error"]:
        print(f"error={result['error']}")
    return 0 if result["written"] and result["export_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
