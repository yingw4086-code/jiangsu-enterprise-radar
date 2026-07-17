from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SiteConfig:
    name: str
    base_url: str
    list_urls: list[str]
    keywords: list[str] = field(default_factory=list)
    max_items: int = 50
    enabled: bool = True
    verify_ssl: bool = True
    timeout_seconds: int = 20
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ProjectRadar/0.1"
