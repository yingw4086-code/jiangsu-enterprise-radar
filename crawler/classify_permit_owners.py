from __future__ import annotations

import argparse
from pathlib import Path

from database.permit_ownership import classify_and_update_permit_owners


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_OVERRIDES_PATH = (
    PROJECT_ROOT / "data" / "reference" / "enterprise_ownership_overrides.csv"
)
DEFAULT_REPORT_PATH = (
    PROJECT_ROOT / "data" / "reports" / "ownership_classification_report.csv"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建设工程规划许可证项目主体性质分类")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite数据库路径")
    parser.add_argument(
        "--overrides",
        default=str(DEFAULT_OVERRIDES_PATH),
        help="人工分类覆盖表路径",
    )
    parser.add_argument(
        "--report",
        default=str(DEFAULT_REPORT_PATH),
        help="分类报告输出路径",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = classify_and_update_permit_owners(
        Path(args.db_path),
        Path(args.overrides),
        Path(args.report),
    )
    for key, value in summary.as_dict().items():
        print(f"{key}={value}")
    print(f"report_path={args.report}")
    print("deepseek_called=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
