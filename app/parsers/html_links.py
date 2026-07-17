from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

from app.parsers.field_extractor import parse_date


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self._pending_link_index: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)
        elif self._pending_link_index is not None:
            date = parse_date(data)
            if date and not self.links[self._pending_link_index].get("date"):
                self.links[self._pending_link_index]["date"] = date

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"li", "tr", "td", "p", "div"}:
            self._pending_link_index = None
        if lowered != "a" or not self._current_href:
            return
        title = normalize_space("".join(self._current_text))
        url = urljoin(self.base_url, self._current_href.strip())
        if title and _is_http_like(url):
            self.links.append({"title": title, "url": url, "date": parse_date(title)})
            self._pending_link_index = len(self.links) - 1
        self._current_href = None
        self._current_text = []


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def extract_links(html: str, base_url: str) -> list[dict[str, str]]:
    parser = _LinkParser(base_url)
    parser.feed(html)
    return parser.links


def html_to_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return normalize_space(" ".join(parser.parts))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _is_http_like(url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith(("javascript:", "mailto:", "#")):
        return False
    return lowered.startswith(("http://", "https://", "file://"))
