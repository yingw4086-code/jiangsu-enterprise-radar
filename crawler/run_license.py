from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from database.storage import (
    count_construction_permits,
    load_public_planning_construction_permits,
    upsert_construction_permits,
    upsert_opportunities,
    upsert_planning_construction_permits,
)
from data_source.jiangsu_license import (
    ConstructionPermitRecord,
    JiangsuLicenseCrawler,
    dedupe_license_records,
    is_haimen_license_record,
    is_recent_license_record,
)
from data_source.multi_source_runner import build_dashboard_payload, write_json
from data_source.permit_validation import PermitValidationCrawler
from data_source.planning_construction_permit import (
    SEARCH_KEYWORD,
    PlanningConstructionPermitCrawler,
    PlanningConstructionPermitRecord,
    PlanningSearchItem,
    filter_planning_construction_items,
)
from data_source.planning_construction_permit_browser import (
    PlanningConstructionPermitBrowserCrawler,
)
from data_source.base import UNKNOWN, parse_date_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "enterprise.db"
DEFAULT_AI_OUTPUT_DIR = PROJECT_ROOT / "data" / "ai"
DEFAULT_LICENSE_OUTPUT_DIR = PROJECT_ROOT / "data" / "licenses"
DEFAULT_DEBUG_DIR = PROJECT_ROOT / "debug"
DEFAULT_VALIDATION_CSV = DEFAULT_DEBUG_DIR / "permit_validation.csv"
DEFAULT_VALIDATION_REPORT = DEFAULT_DEBUG_DIR / "permit_validation_report.json"
PLANNING_ABNORMAL_HTML = "planning_construction_abnormal_response.html"
PLANNING_BROWSER_SAMPLE_HTML = "planning_construction_browser_sample.html"

DEBUG_HTML_FILES = {
    "建设工程施工许可证": "license_施工许可证.html",
    "建设工程规划许可证": "license_工程规划许可证.html",
    "建设用地规划许可证": "license_用地规划许可证.html",
}


def run_license(args: argparse.Namespace) -> dict[str, object]:
    crawler = JiangsuLicenseCrawler(
        max_items=args.limit,
        timeout_seconds=args.timeout_seconds,
        enable_provincial_search=True,
    )
    license_records = crawler.crawl_licenses()
    opportunity_records = [record.to_opportunity_record() for record in license_records]

    db_path = Path(args.db_path)
    permit_summary = upsert_construction_permits(db_path, license_records)
    opportunity_summary = upsert_opportunities(db_path, opportunity_records)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    license_json_path = export_license_json(license_records, Path(args.license_output_dir), timestamp, crawler.errors)
    dashboard_json_path = Path(args.ai_output_dir) / f"financing_analysis_license_{timestamp}.json"
    write_json(dashboard_json_path, build_dashboard_payload(opportunity_records))

    print_license_rows(license_records)
    result = {
        "license_count": len(license_records),
        "permit_inserted_count": permit_summary.inserted_count,
        "permit_updated_count": permit_summary.updated_count,
        "opportunity_inserted_count": opportunity_summary.inserted_count,
        "opportunity_updated_count": opportunity_summary.updated_count,
        "db_path": str(db_path),
        "license_json": str(license_json_path),
        "dashboard_json": str(dashboard_json_path),
        "crawler_errors": crawler.errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_interface_test(args: argparse.Namespace) -> dict[str, object]:
    crawler = JiangsuLicenseCrawler(
        max_items=args.limit,
        timeout_seconds=args.timeout_seconds,
        enable_provincial_search=True,
    )
    reports, records = crawler.build_parsing_test_report(min_items=5)
    for report in reports:
        print(f"关键词：{report['关键词']}")
        print(f"接口：{report['接口']}")
        print(f"请求方式：{report['请求方式']}")
        print(f"请求参数：{json.dumps(report['请求参数'], ensure_ascii=False)}")
        print(f"返回格式：{report['返回格式']}")
        print(f"返回数据数量：{report['返回数据数量']}")
        print(f"示例数据：{json.dumps(report['示例数据'], ensure_ascii=False)}")
        if report.get("错误"):
            print(f"错误：{report['错误']}")
        print("")

    parsed_items = [record.to_unified_dict() for record in records[:5]]
    print(f"HTML解析结果（展示{len(parsed_items)}条）：")
    for index, item in enumerate(parsed_items, start=1):
        print(f"{index}. {json.dumps(item, ensure_ascii=False)}")

    result = {
        "interface_test": reports,
        "parsed_count": len(records),
        "parsed_results": parsed_items,
        "crawler_errors": crawler.errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_debug(args: argparse.Namespace) -> dict[str, object]:
    crawler = JiangsuLicenseCrawler(
        max_items=args.limit,
        timeout_seconds=args.timeout_seconds,
        enable_provincial_search=True,
    )
    debug_dir = Path(args.debug_dir)
    broad_result = crawler.search_keyword("许可证")
    broad_path = crawler.save_debug_html(broad_result, debug_dir / "license_许可证.html")
    broad_diagnostics = crawler.diagnose_search_page(broad_result)
    broad_diagnostics["保存文件"] = str(broad_path)
    broad_diagnostics["结果样例"] = [
        {"标题": item.title, "发布日期": item.date, "详情页链接": item.url}
        for item in broad_result.candidates[:10]
    ]
    page_reports = []
    exact_candidates = []
    saved_files = []
    for keyword, filename in DEBUG_HTML_FILES.items():
        result = crawler.search_keyword(keyword)
        exact_candidates.extend(result.candidates)
        output_path = crawler.save_debug_html(result, debug_dir / filename)
        diagnostics = crawler.diagnose_search_page(result)
        diagnostics["保存文件"] = str(output_path)
        page_reports.append(diagnostics)
        saved_files.append(str(output_path))
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))

    unique_candidates = []
    seen_urls = set()
    for candidate in exact_candidates:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        unique_candidates.append(candidate)

    parsed_records = []
    for candidate in unique_candidates[: args.limit]:
        record = crawler.record_from_license_candidate(candidate)
        if record:
            parsed_records.append(record.enrich())
    parsed_records = dedupe_license_records(parsed_records)
    haimen_records = [record for record in parsed_records if is_haimen_license_record(record)]
    recent_records = [record for record in haimen_records if is_recent_license_record(record, max_age_days=30)]

    result = {
        "request_parameters": {
            "实际请求方式": "GET",
            "接口": crawler.search_url,
            "catalogID": crawler.search_catalog_id,
            "type": "1",
            "title": "UTF-8 URL编码",
            "已验证旧参数": {
                "queryCatalogID": "当前页面未使用",
                "querytype": "当前页面未使用",
                "area": "搜索表单存在但search()未提交",
                "searchColumn": "当前页面未使用",
                "classID": "只用于打开信息检索首页",
            },
        },
        "broad_search": broad_diagnostics,
        "pages": page_reports,
        "saved_files": saved_files,
        "stages": {
            "第1次_许可证宽词": {
                "raw_result_count": len(broad_result.candidates),
            },
            "第2次_三个完整名称": {
                "raw_result_count": len(unique_candidates),
                "parsed_result_count": len(parsed_records),
            },
            "第3次_海门过滤": {
                "haimen_filtered_count": len(haimen_records),
            },
            "第4次_最近30天": {
                "recent_30_days_count": len(recent_records),
            },
        },
        "raw_result_count": len(broad_result.candidates),
        "parsed_result_count": len(parsed_records),
        "haimen_filtered_count": len(haimen_records),
        "recent_30_days_count": len(recent_records),
        "inserted_count": 0,
        "parsed_examples": [record.to_unified_dict() for record in parsed_records[:5]],
        "crawler_errors": crawler.errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def export_license_json(
    records: list[ConstructionPermitRecord],
    output_dir: Path,
    timestamp: str,
    crawler_errors: list[str],
) -> Path:
    output_path = output_dir / f"construction_permits_{timestamp}.json"
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "record_count": len(records),
        "crawler_errors": crawler_errors,
        "items": [record.to_unified_dict() for record in records],
    }
    write_json(output_path, payload)
    return output_path


def print_license_rows(records: list[ConstructionPermitRecord]) -> None:
    print("企业名称\t许可证类型\t时间\t贷款机会评分")
    for record in records:
        print(
            f"{record.company_name}\t{record.permit_type}\t{record.permit_date}\t{record.loan_opportunity_score}"
        )


def run_planning_construction_validation(args: argparse.Namespace) -> dict[str, object]:
    crawler = PlanningConstructionPermitCrawler(
        timeout_seconds=args.timeout_seconds,
        request_interval_seconds=1.0,
        max_pages=30,
        enable_ocr=True,
    )
    result = crawler.validate(detail_limit=10)
    diagnostic_keys = [
        "request_url",
        "request_method",
        "request_params",
        "raw_total_count",
        "current_page_count",
        "parsed_list_count",
        "detail_success_count",
        "haimen_confirmed_count",
        "recent_90_days_count",
        "recent_30_days_count",
        "latest_date",
        "filtered_out_count",
        "filtered_out_reasons",
    ]
    print("建设工程规划许可证海门数据源验证（只读，不写数据库，不调用DeepSeek）")
    for key in diagnostic_keys:
        value = result.get(key)
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        print(f"{key}={rendered}")

    print("\n10条真实海门示例：")
    for index, item in enumerate(result.get("examples", [])[:10], start=1):
        print(f"{index}. {json.dumps(item, ensure_ascii=False)}")

    print("\n最近30天结果：")
    for item in result.get("recent_30_days_results", []):
        print(json.dumps(item, ensure_ascii=False))

    print("\n完整诊断JSON：")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _date_is_reasonable(value: str, today: date | None = None) -> bool:
    parsed = parse_date_object(value)
    if parsed is None:
        return False
    current_day = today or date.today()
    return current_day - timedelta(days=365) <= parsed <= current_day + timedelta(days=7)


def _api_result_is_healthy(
    diagnostics: dict[str, object],
) -> bool:
    return bool(
        int(diagnostics.get("source_total_count", 0)) > 50
        and int(diagnostics.get("valid_count", 0)) > 0
        and diagnostics.get("all_pages_loaded")
        and _date_is_reasonable(str(diagnostics.get("latest_date", "")))
    )


def _recent_item_count(items: list[PlanningSearchItem], days: int) -> int:
    cutoff = date.today() - timedelta(days=days)
    return sum(
        1
        for item in items
        if (parsed := parse_date_object(item.publish_date)) is not None
        and cutoff <= parsed <= date.today() + timedelta(days=7)
    )


def _build_search_diagnostics(
    *,
    raw_total_count: int,
    current_page_count: int,
    items: list[PlanningSearchItem],
    collection_method: str,
    errors: list[str],
    pages_collected: int,
) -> tuple[dict[str, object], list[PlanningSearchItem]]:
    valid_items, haimen_confirmed_count, filtered_reasons = filter_planning_construction_items(
        items
    )
    expected_pages = (
        math.ceil(raw_total_count / 10)
        if raw_total_count > 0
        else 0
    )
    baseline_titles = ("平谦现代产业园", "冬泽特医食品生产基地", "立新小区九期")
    diagnostics: dict[str, object] = {
        "source_total_count": raw_total_count,
        "current_page_count": current_page_count,
        "parsed_list_count": len(items),
        "valid_count": len(valid_items),
        "haimen_confirmed_count": haimen_confirmed_count,
        "recent_90_days_count": _recent_item_count(valid_items, 90),
        "recent_30_days_count": _recent_item_count(valid_items, 30),
        "latest_date": valid_items[0].publish_date if valid_items else UNKNOWN,
        "filtered_out_count": sum(filtered_reasons.values()),
        "filtered_out_reasons": filtered_reasons,
        "all_pages_loaded": (
            raw_total_count > 0
            and pages_collected >= expected_pages
            and len(items) == raw_total_count
        ),
        "pages_collected": pages_collected,
        "collection_method": collection_method,
        "baseline_matches": {
            title: any(title in item.title for item in valid_items)
            for title in baseline_titles
        },
        "errors": list(errors),
    }
    return diagnostics, valid_items


def _collect_browser_search_items(
    args: argparse.Namespace,
    *,
    max_pages: int,
    headless: bool,
) -> tuple[dict[str, object], list[PlanningSearchItem]]:
    debug_dir = Path(args.debug_dir)
    browser_crawler = PlanningConstructionPermitBrowserCrawler(
        headless=headless,
        max_pages=max_pages,
        timeout_seconds=max(30, args.timeout_seconds),
        interval_seconds=1.5,
    )
    browser_result = browser_crawler.collect(
        sample_path=debug_dir / PLANNING_BROWSER_SAMPLE_HTML
    )
    diagnostics, valid_items = _build_search_diagnostics(
        raw_total_count=browser_result.raw_total_count,
        current_page_count=min(10, len(browser_result.records)),
        items=browser_result.records,
        collection_method=browser_result.collection_method,
        errors=browser_result.errors,
        pages_collected=browser_result.pages_collected,
    )
    diagnostics["browser_started"] = browser_result.browser_started
    diagnostics["search_submitted"] = browser_result.search_submitted
    return diagnostics, valid_items


def collect_planning_construction_records_with_fallback(
    args: argparse.Namespace,
) -> tuple[dict[str, object], list[PlanningConstructionPermitRecord]]:
    crawler = PlanningConstructionPermitCrawler(
        timeout_seconds=args.timeout_seconds,
        request_interval_seconds=1.0,
        max_pages=100,
        enable_ocr=True,
    )
    raw_total, current_page_count, api_items = crawler.collect_all_search_items()
    api_pages = math.ceil(raw_total / 10) if raw_total > 0 else 0
    diagnostics, valid_items = _build_search_diagnostics(
        raw_total_count=raw_total,
        current_page_count=current_page_count,
        items=api_items,
        collection_method="requests_api",
        errors=crawler.errors,
        pages_collected=api_pages if len(api_items) == raw_total else min(api_pages, crawler.max_pages),
    )
    if not _api_result_is_healthy(diagnostics):
        abnormal_path = Path(args.debug_dir) / PLANNING_ABNORMAL_HTML
        abnormal_path.parent.mkdir(parents=True, exist_ok=True)
        abnormal_path.write_text(
            crawler.last_first_page_html or "<!-- requests接口未返回可保存的HTML -->",
            encoding="utf-8",
        )
        browser_diagnostics, valid_items = _collect_browser_search_items(
            args,
            max_pages=100,
            headless=True,
        )
        browser_diagnostics["requests_api_abnormal"] = {
            "source_total_count": diagnostics.get("source_total_count", 0),
            "valid_count": diagnostics.get("valid_count", 0),
            "latest_date": diagnostics.get("latest_date", UNKNOWN),
            "errors": diagnostics.get("errors", []),
            "saved_response": str(abnormal_path),
        }
        diagnostics = browser_diagnostics

    db_path = Path(args.db_path)
    existing_rows = load_public_planning_construction_permits(db_path)
    existing_urls = {
        str(row.get("source_url") or "")
        for row in existing_rows
        if row.get("source_url")
    }
    new_items = [
        item
        for item in valid_items
        if item.detail_url not in existing_urls
    ]
    detail_crawler = PlanningConstructionPermitCrawler(
        timeout_seconds=args.timeout_seconds,
        request_interval_seconds=1.0,
        max_pages=1,
        enable_ocr=True,
    )
    records = [
        detail_crawler.fetch_detail(item, use_ocr=True)
        for item in new_items
    ]
    diagnostics["existing_record_count"] = len(existing_rows)
    diagnostics["skipped_existing_count"] = len(valid_items) - len(new_items)
    diagnostics["new_detail_count"] = len(new_items)
    diagnostics["errors"] = list(diagnostics.get("errors", [])) + detail_crawler.errors
    return diagnostics, records


def run_planning_construction_browser_validation(args: argparse.Namespace) -> dict[str, object]:
    browser_crawler = PlanningConstructionPermitBrowserCrawler(
        headless=False,
        max_pages=3,
        timeout_seconds=max(30, args.timeout_seconds),
        interval_seconds=1.5,
    )
    browser_result = browser_crawler.collect(
        sample_path=Path(args.debug_dir) / PLANNING_BROWSER_SAMPLE_HTML
    )
    valid_items, _, filtered_reasons = filter_planning_construction_items(
        browser_result.records
    )
    result: dict[str, object] = {
        "browser_started": browser_result.browser_started,
        "search_submitted": browser_result.search_submitted,
        "raw_total_count": browser_result.raw_total_count,
        "pages_collected": browser_result.pages_collected,
        "records_collected": len(browser_result.records),
        "valid_count": len(valid_items),
        "recent_90_days_count": _recent_item_count(valid_items, 90),
        "recent_30_days_count": _recent_item_count(valid_items, 30),
        "latest_date": valid_items[0].publish_date if valid_items else UNKNOWN,
        "collection_method": browser_result.collection_method,
        "filtered_out_reasons": filtered_reasons,
        "database_written": False,
        "deepseek_called": False,
        "errors": browser_result.errors,
        "examples": [
            {
                "标题": item.title,
                "发布日期": item.publish_date,
                "发布部门": item.publisher,
                "详情页链接": item.detail_url,
            }
            for item in valid_items[:10]
        ],
    }
    print("建设工程规划许可证Playwright浏览器验证（只读，不写数据库，不调用DeepSeek）")
    for key in (
        "browser_started",
        "search_submitted",
        "raw_total_count",
        "pages_collected",
        "records_collected",
        "valid_count",
        "recent_90_days_count",
        "recent_30_days_count",
        "latest_date",
        "collection_method",
        "errors",
    ):
        value = result[key]
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        print(f"{key}={rendered}")
    print("\n10条真实样本：")
    for index, item in enumerate(result["examples"], start=1):
        print(f"{index}. {json.dumps(item, ensure_ascii=False)}")
    return result


def run_planning_construction_import(args: argparse.Namespace) -> dict[str, object]:
    diagnostics, records = collect_planning_construction_records_with_fallback(args)
    db_path = Path(args.db_path)
    baseline_matches = dict(diagnostics.get("baseline_matches", {}))
    database_total_before = count_construction_permits(db_path, SEARCH_KEYWORD)
    blocked_reasons: list[str] = []
    if int(diagnostics["source_total_count"]) <= 50:
        blocked_reasons.append(
            "采集总数未达到接口或浏览器健康阈值（必须大于50条）"
        )
    if not diagnostics["all_pages_loaded"]:
        blocked_reasons.append(
            "海门规划许可证分页未完整加载，停止入库："
            f"source_total_count={diagnostics['source_total_count']}, "
            f"parsed_list_count={diagnostics['parsed_list_count']}"
        )
    if not records and database_total_before == 0:
        blocked_reasons.append("未解析到有效建设工程规划许可证")
    if baseline_matches and not all(baseline_matches.values()):
        blocked_reasons.append("近期基准项目未全部识别")

    if blocked_reasons:
        result = {
            "status": "blocked",
            "source_total_count": diagnostics["source_total_count"],
            "valid_count": diagnostics["valid_count"],
            "inserted_count": 0,
            "updated_count": 0,
            "skipped_count": diagnostics["source_total_count"],
            "database_total_count": count_construction_permits(db_path, SEARCH_KEYWORD),
            "recent_90_days_count": diagnostics["recent_90_days_count"],
            "recent_30_days_count": diagnostics["recent_30_days_count"],
            "collection_method": diagnostics.get("collection_method", "unknown"),
            "baseline_matches": baseline_matches,
            "blocked_reasons": blocked_reasons,
            "database_written": False,
            "deepseek_called": False,
        }
        print("海门建设工程规划许可证正式导入已安全停止")
        for key, value in result.items():
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            print(f"{key}={rendered}")
        return result

    summary = upsert_planning_construction_permits(db_path, records)
    filtered_count = max(0, int(diagnostics["source_total_count"]) - int(diagnostics["valid_count"]))
    skipped_existing = int(diagnostics.get("skipped_existing_count", 0))
    result = {
        "source_total_count": diagnostics["source_total_count"],
        "valid_count": diagnostics["valid_count"],
        "inserted_count": summary.inserted_count,
        "updated_count": summary.updated_count,
        "skipped_count": filtered_count + skipped_existing + summary.skipped_count,
        "database_total_count": count_construction_permits(db_path, SEARCH_KEYWORD),
        "recent_90_days_count": diagnostics["recent_90_days_count"],
        "recent_30_days_count": diagnostics["recent_30_days_count"],
        "collection_method": diagnostics["collection_method"],
        "filtered_out_reasons": diagnostics["filtered_out_reasons"],
        "crawler_errors": diagnostics["errors"],
        "database_written": True,
        "deepseek_called": False,
    }
    print("海门建设工程规划许可证正式导入")
    for key, value in result.items():
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        print(f"{key}={rendered}")
    return result


def run_permit_validation(args: argparse.Namespace) -> dict[str, object]:
    crawler = PermitValidationCrawler(
        timeout_seconds=args.timeout_seconds,
        request_interval_seconds=1.0,
        detail_limit=args.validation_detail_limit,
    )
    result = crawler.validate_all(Path(args.validation_csv))
    report_path = Path(args.validation_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result["report_path"] = str(report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("三类许可证准确性验证（只读，不写数据库，不调用DeepSeek）")
    for source in result["sources"]:
        print("\n" + "=" * 72)
        print(f"数据源：{source['source_name']}")
        for key in (
            "permit_type",
            "source_total_count",
            "source_list_page_count",
            "scanned_list_page_count",
            "list_group_request_count",
            "list_scan_complete",
            "list_item_parsed_count",
            "target_candidate_count",
            "detail_attempted_count",
            "detail_page_success_count",
            "parsed_result_count",
            "missing_detail_count",
            "detail_not_attempted_count",
            "detail_request_failed_count",
            "non_target_list_item_count",
            "haimen_confirmed_count",
            "haimen_pending_count",
            "recent_90_days_count",
            "recent_30_days_count",
            "latest_publish_date",
            "latest_permit_date",
            "excluded_detail_reasons",
            "key_field_completeness",
        ):
            value = source.get(key)
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            print(f"{key}={rendered}")
        print("样本：")
        for index, sample in enumerate(source["samples"], start=1):
            print(f"{index}. {json.dumps(sample, ensure_ascii=False)}")

    print("\n" + "=" * 72)
    print(f"人工核验CSV：{result['csv_path']}")
    print(f"诊断报告JSON：{result['report_path']}")
    print(f"CSV记录数：{result['csv_record_count']}")
    print(f"正式数据库写入：{result['database_written']}")
    print(f"DeepSeek调用：{result['deepseek_called']}")
    if result["errors"]:
        print("错误：")
        for error in result["errors"]:
            print(f"- {error}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建设项目许可证专项采集")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite 数据库路径")
    parser.add_argument("--ai-output-dir", default=str(DEFAULT_AI_OUTPUT_DIR), help="Dashboard 兼容 JSON 输出目录")
    parser.add_argument("--license-output-dir", default=str(DEFAULT_LICENSE_OUTPUT_DIR), help="许可证 JSON 输出目录")
    parser.add_argument("--debug-dir", default=str(DEFAULT_DEBUG_DIR), help="原始HTML诊断输出目录")
    parser.add_argument("--validation-csv", default=str(DEFAULT_VALIDATION_CSV), help="许可证人工核验CSV路径")
    parser.add_argument("--validation-report", default=str(DEFAULT_VALIDATION_REPORT), help="许可证诊断JSON报告路径")
    parser.add_argument("--validation-detail-limit", type=int, default=40, help="每个全市栏目最多验证的详情数量")
    parser.add_argument("--limit", type=int, default=80, help="最多采集许可证数量")
    parser.add_argument("--timeout-seconds", type=int, default=12, help="单个网页访问超时秒数")
    parser.add_argument("--test", action="store_true", help="只测试江苏自然资源真实检索接口，不入库、不导出JSON")
    parser.add_argument("--debug", action="store_true", help="保存真实HTML并执行分层诊断，不写数据库")
    parser.add_argument(
        "--validate-planning-construction",
        action="store_true",
        help="只验证海门建设工程规划许可证真实搜索接口，不入库、不调用DeepSeek",
    )
    parser.add_argument(
        "--browser-validate-planning-construction",
        action="store_true",
        help="启动可见Playwright浏览器验证海门建设工程规划许可证前3页，不写数据库",
    )
    parser.add_argument(
        "--import-planning-construction",
        action="store_true",
        help="从areaCode=320684官方搜索接口导入海门建设工程规划许可证",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="验证三类许可证详情、海门归属和字段覆盖率，不入库、不调用DeepSeek",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.import_planning_construction:
        result = run_planning_construction_import(args)
        return 0 if result.get("database_written") and result["database_total_count"] > 0 else 1
    if args.browser_validate_planning_construction:
        result = run_planning_construction_browser_validation(args)
        return 0 if (
            result.get("browser_started")
            and result.get("search_submitted")
            and result.get("raw_total_count", 0) > 50
            and result.get("valid_count", 0) >= 10
        ) else 1
    if args.validate:
        result = run_permit_validation(args)
        sources = result.get("sources", [])
        enough_samples = len(sources) == 3 and all(source.get("sample_count", 0) >= 10 for source in sources)
        live_data = all(source.get("source_total_count", 0) > 0 for source in sources)
        return 0 if enough_samples and live_data else 1
    if args.validate_planning_construction:
        result = run_planning_construction_validation(args)
        baselines_ok = all(result.get("baseline_matches", {}).values())
        counts_ok = (
            result.get("raw_total_count", 0) > 0
            and result.get("parsed_list_count") == result.get("raw_total_count")
            and result.get("detail_success_count", 0) >= 10
        )
        return 0 if baselines_ok and counts_ok else 1
    if args.debug:
        result = run_debug(args)
        return 0 if all(page.get("HTTP状态码") == 200 for page in result["pages"]) else 1
    if args.test:
        result = run_interface_test(args)
        return 0 if result["parsed_count"] >= 5 else 1
    result = run_license(args)
    return 0 if result["license_count"] >= 20 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
