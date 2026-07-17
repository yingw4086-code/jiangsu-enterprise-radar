from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from app.models import ProjectAnnouncement
from app.parsers.field_extractor import extract_announcement_fields
from app.parsers.html_links import extract_links, html_to_text
from app.sources.base import SiteConfig


class GenericGovernmentSite:
    """Generic adapter for static government announcement pages."""

    def __init__(self, config: SiteConfig):
        self.config = config

    def collect(self) -> list[ProjectAnnouncement]:
        candidates = []
        for list_url in self.config.list_urls:
            html = self._safe_fetch_text(list_url)
            if not html:
                print(f"采集警告：列表页访问失败，已跳过：{list_url}")
                continue
            candidates.extend(extract_links(html, list_url))

        filtered = self._filter_candidates(candidates)
        announcements: list[ProjectAnnouncement] = []
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for item in filtered[: self.config.max_items]:
            detail_html = self._safe_fetch_text(item["url"])
            detail_text = html_to_text(detail_html) if detail_html else item["title"]
            fields = extract_announcement_fields(
                title=item["title"],
                text=detail_text,
                url=item["url"],
                fallback_date=item.get("date", ""),
            )
            announcements.append(
                ProjectAnnouncement(
                    company_name=fields["company_name"],
                    project_name=fields["project_name"],
                    approval_item=fields["approval_item"],
                    date=fields["date"],
                    link=item["url"],
                    source_name=self.config.name,
                    title=item["title"],
                    fetched_at=fetched_at,
                )
            )
        return announcements

    def _filter_candidates(self, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        keywords = [keyword.strip() for keyword in self.config.keywords if keyword.strip()]
        for item in candidates:
            title = item["title"].strip()
            url = item["url"].strip()
            if not title or not url or url in seen:
                continue
            combined = f"{title} {url}"
            if keywords and not any(keyword in combined for keyword in keywords):
                continue
            seen.add(url)
            result.append(item)
        return result

    def _safe_fetch_text(self, url: str) -> str:
        try:
            return self._fetch_text(url)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            print(f"采集警告：访问失败：{url}；原因：{exc}")
            return ""

    def _fetch_text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": self.config.user_agent})
        context = None if self.config.verify_ssl else ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds, context=context) as response:
            body = response.read()
            charset = response.headers.get_content_charset()
        return _decode_bytes(body, charset)


def load_site_configs(path: Path) -> list[SiteConfig]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    configs: list[SiteConfig] = []
    for item in data:
        configs.append(
            SiteConfig(
                name=item["name"],
                base_url=item["base_url"],
                list_urls=item["list_urls"],
                keywords=item.get("keywords", []),
                max_items=int(item.get("max_items", 50)),
                enabled=bool(item.get("enabled", True)),
                verify_ssl=bool(item.get("verify_ssl", True)),
                timeout_seconds=int(item.get("timeout_seconds", 20)),
                user_agent=item.get(
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ProjectRadar/0.1",
                ),
            )
        )
    return configs


def _decode_bytes(body: bytes, charset: str | None) -> str:
    encodings = [charset, "utf-8", "gb18030"]
    for encoding in encodings:
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")
