from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from app.ai.financing_analyzer import FinancingAnalyzer
from app.ai.provider import LLMConfigError, LLMRequestError, OpenAICompatibleClient, config_from_env
from app.exporters.excel_writer import write_xlsx
from app.exporters.json_writer import write_json
from app.models import ProjectAnnouncement
from app.sources.generic_government import GenericGovernmentSite, load_site_configs
from app.storage.state_store import SeenLinkStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sites.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "excel"
DEFAULT_AI_OUTPUT_DIR = PROJECT_ROOT / "data" / "ai"
DEFAULT_STATE_PATH = PROJECT_ROOT / "data" / "state" / "seen_links.json"


HEADERS = ["企业名称", "项目名称", "审批事项", "日期", "链接", "来源", "原始标题", "抓取时间"]


def collect_announcements(config_path: Path, state_path: Path, include_seen: bool) -> list[ProjectAnnouncement]:
    configs = load_site_configs(config_path)
    seen_store = SeenLinkStore(state_path)
    all_rows: list[ProjectAnnouncement] = []

    for config in configs:
        if not config.enabled:
            continue
        site = GenericGovernmentSite(config)
        rows = site.collect()
        for row in rows:
            if include_seen or not seen_store.has_seen(row.link):
                all_rows.append(row)

    deduped = _dedupe_by_link(all_rows)
    if not include_seen:
        seen_store.mark_many([row.link for row in deduped])
    return deduped


def run_once(args: argparse.Namespace) -> Path:
    config_path = Path(args.config).resolve()
    output_dir = Path(args.output_dir).resolve()
    state_path = Path(args.state_path).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = collect_announcements(config_path, state_path, args.include_seen)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = output_dir / f"project_announcements_{timestamp}.xlsx"
    write_xlsx(output_path, HEADERS, [row.to_excel_row() for row in rows])

    print(f"采集完成：{len(rows)} 条新增公告")
    print(f"Excel 文件：{output_path}")
    if getattr(args, "with_ai", False):
        ai_output_path = run_ai_analysis(rows, args, timestamp)
        print(f"AI 分析 JSON：{ai_output_path}")
    return output_path


def run_ai_analysis(rows: list[ProjectAnnouncement], args: argparse.Namespace, timestamp: str) -> Path:
    ai_output_dir = Path(args.ai_output_dir).resolve()
    ai_output_path = ai_output_dir / f"financing_analysis_{timestamp}.json"
    if not rows:
        write_json(
            ai_output_path,
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "model": "not_called_no_new_items",
                "items": [],
            },
        )
        return ai_output_path

    try:
        llm_config = config_from_env(
            api_key_env=args.llm_api_key_env,
            base_url=args.llm_base_url,
            model=args.llm_model,
            timeout_seconds=args.llm_timeout,
            verify_ssl=args.llm_verify_ssl,
            response_format=args.llm_response_format,
        )
        client = OpenAICompatibleClient(llm_config)
        analyzer = FinancingAnalyzer(client=client, model_name=llm_config.model)
        result = analyzer.analyze_many(rows)
    except (LLMConfigError, LLMRequestError) as exc:
        raise SystemExit(f"AI 分析失败：{exc}") from exc

    write_json(ai_output_path, result)
    return ai_output_path


def watch_daily(args: argparse.Namespace) -> None:
    target_time = args.time
    print(f"每日采集已启动，计划时间：{target_time}")
    print("保持此窗口打开；如需后台稳定运行，建议使用 Windows 任务计划程序。")
    last_run_date: str | None = None

    while True:
        now = datetime.now()
        current_day = now.date().isoformat()
        if now.strftime("%H:%M") >= target_time and last_run_date != current_day:
            run_once(args)
            last_run_date = current_day
        time.sleep(60)


def _dedupe_by_link(rows: list[ProjectAnnouncement]) -> list[ProjectAnnouncement]:
    seen: set[str] = set()
    result: list[ProjectAnnouncement] = []
    for row in rows:
        key = row.link.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(row)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="区域企业项目雷达采集模块")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("run-once", "watch"):
        cmd = subparsers.add_parser(command)
        cmd.add_argument("--config", default=str(DEFAULT_CONFIG), help="网站配置文件")
        cmd.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Excel 输出目录")
        cmd.add_argument("--state-path", default=str(DEFAULT_STATE_PATH), help="去重状态文件")
        cmd.add_argument("--include-seen", action="store_true", help="包含已经抓取过的链接")
        cmd.add_argument("--with-ai", action="store_true", help="调用大语言模型 API 生成融资分析 JSON")
        cmd.add_argument("--ai-output-dir", default=str(DEFAULT_AI_OUTPUT_DIR), help="AI 分析 JSON 输出目录")
        cmd.add_argument("--llm-api-key-env", default="PROJECT_RADAR_LLM_API_KEY", help="保存 API Key 的环境变量名")
        cmd.add_argument("--llm-base-url", default=None, help="OpenAI 兼容接口地址，例如 https://api.openai.com/v1")
        cmd.add_argument("--llm-model", default=None, help="模型名称；也可用 PROJECT_RADAR_LLM_MODEL 设置")
        cmd.add_argument("--llm-timeout", type=int, default=60, help="LLM API 超时时间，单位秒")
        cmd.add_argument(
            "--llm-response-format",
            choices=["json_object", "none"],
            default="json_object",
            help="是否请求模型按 JSON object 返回；部分兼容接口不支持时可设为 none",
        )
        cmd.add_argument("--llm-no-verify-ssl", dest="llm_verify_ssl", action="store_false", help="关闭 LLM API SSL 校验")
        cmd.set_defaults(llm_verify_ssl=True)

    subparsers.choices["watch"].add_argument("--time", default="08:30", help="每日运行时间，格式 HH:MM")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-once":
        run_once(args)
        return 0
    if args.command == "watch":
        watch_daily(args)
        return 0
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
