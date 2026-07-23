from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from data_source.planning_construction_permit import (
    SEARCH_AREA_CODE,
    SEARCH_INDEX_URL,
    SEARCH_KEYWORD,
    SERVER_PAGE_SIZE,
    PlanningSearchItem,
    parse_search_page,
)


COLLECTION_METHOD = "playwright_browser"
BLOCKED_PAGE_MARKERS = (
    "请输入验证码",
    "验证码",
    "请登录",
    "访问受限",
    "拒绝访问",
)


@dataclass
class BrowserCollectionResult:
    browser_started: bool = False
    search_submitted: bool = False
    raw_total_count: int = 0
    pages_collected: int = 0
    records: list[PlanningSearchItem] = field(default_factory=list)
    sample_html: str = ""
    collection_method: str = COLLECTION_METHOD
    errors: list[str] = field(default_factory=list)


def parse_display_total(text: str) -> int:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else 0


class PlanningConstructionPermitBrowserCrawler:
    def __init__(
        self,
        *,
        headless: bool,
        max_pages: int,
        timeout_seconds: int = 30,
        interval_seconds: float = 1.5,
        browser_channel: str = "msedge",
    ) -> None:
        self.headless = headless
        self.max_pages = max(1, max_pages)
        self.timeout_ms = max(10, timeout_seconds) * 1000
        self.interval_ms = int(min(2.0, max(1.0, interval_seconds)) * 1000)
        self.browser_channel = browser_channel

    @property
    def index_url(self) -> str:
        return f"{SEARCH_INDEX_URL}?areaCode={SEARCH_AREA_CODE}"

    def collect(self, sample_path: Path | None = None) -> BrowserCollectionResult:
        result = BrowserCollectionResult()
        browser = None
        context = None
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            result.errors.append(f"Playwright未安装：{exc}")
            return result

        try:
            with sync_playwright() as playwright:
                browser = self._launch_browser(playwright)
                result.browser_started = True
                context = browser.new_context(locale="zh-CN")
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())
                page.goto(self.index_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.locator("#searchValue").wait_for(state="visible", timeout=self.timeout_ms)

                area_code = page.locator("#areaCode").input_value()
                if area_code != SEARCH_AREA_CODE:
                    result.errors.append(f"页面未正确选择海门：areaCode={area_code!r}")
                    return result

                page.locator("#searchValue").fill(SEARCH_KEYWORD)
                page.locator("#searchbt").click()
                result.search_submitted = True
                self._wait_for_results(page, PlaywrightTimeoutError)
                page.wait_for_timeout(self.interval_ms)

                body_text = page.locator("body").inner_text()
                blocked_marker = next((marker for marker in BLOCKED_PAGE_MARKERS if marker in body_text), "")
                if blocked_marker:
                    result.errors.append(f"页面出现访问控制提示：{blocked_marker}")
                    return result

                total_text = page.locator("#totalSize").inner_text()
                result.raw_total_count = parse_display_total(total_text)
                first_sample_html = page.content()
                result.sample_html = first_sample_html

                total_pages = max(
                    1,
                    math.ceil(result.raw_total_count / SERVER_PAGE_SIZE),
                )
                page_limit = min(self.max_pages, total_pages)
                unique: dict[str, PlanningSearchItem] = {}

                for page_number in range(1, page_limit + 1):
                    panel = page.locator("#listPanel")
                    page_html = panel.inner_html()
                    parsed = parse_search_page(page_html, page=page_number)
                    for item in parsed.items:
                        unique[item.detail_url] = item
                    result.pages_collected += 1

                    if page_number >= page_limit:
                        break
                    previous_url = parsed.items[0].detail_url if parsed.items else ""
                    page.wait_for_timeout(self.interval_ms)
                    next_button = panel.get_by_text("下一页", exact=True)
                    if next_button.count() == 0:
                        result.errors.append(f"第{page_number}页未找到“下一页”按钮")
                        break
                    next_button.last.click()
                    if previous_url:
                        page.wait_for_function(
                            """
                            previous => {
                                const link = document.querySelector('#listPanel ul.item li a');
                                return Boolean(link && link.href && link.href !== previous);
                            }
                            """,
                            arg=previous_url,
                            timeout=self.timeout_ms,
                        )
                    else:
                        self._wait_for_results(page, PlaywrightTimeoutError)
                    page.wait_for_timeout(self.interval_ms)

                result.records = list(unique.values())
                if (
                    sample_path is not None
                    and result.raw_total_count > 50
                    and result.records
                ):
                    sample_path.parent.mkdir(parents=True, exist_ok=True)
                    sample_path.write_text(first_sample_html, encoding="utf-8")
        except Exception as exc:
            result.errors.append(f"Playwright浏览器采集失败：{type(exc).__name__}: {exc}")
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
        return result

    def _launch_browser(self, playwright):
        try:
            return playwright.chromium.launch(
                channel=self.browser_channel,
                headless=self.headless,
                slow_mo=80 if not self.headless else 0,
            )
        except Exception as channel_error:
            try:
                return playwright.chromium.launch(headless=self.headless)
            except Exception as bundled_error:
                raise RuntimeError(
                    f"无法启动Edge Chromium（{channel_error}）；"
                    f"也未找到Playwright Chromium（{bundled_error}）"
                ) from bundled_error

    def _wait_for_results(self, page, timeout_error_type) -> None:
        try:
            page.wait_for_function(
                """
                () => {
                    const panel = document.querySelector('#listPanel');
                    const total = document.querySelector('#totalSize');
                    return Boolean(
                        panel &&
                        total &&
                        (
                            panel.querySelector('ul.item li') ||
                            Number((total.textContent || '').trim()) === 0
                        )
                    );
                }
                """,
                timeout=self.timeout_ms,
            )
        except timeout_error_type as exc:
            raise RuntimeError("等待官网搜索结果超时") from exc
