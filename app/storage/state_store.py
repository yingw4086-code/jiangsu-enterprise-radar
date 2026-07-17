from __future__ import annotations

import json
from pathlib import Path


class SeenLinkStore:
    def __init__(self, path: Path):
        self.path = path
        self._links = self._load()

    def has_seen(self, link: str) -> bool:
        return link in self._links

    def mark_many(self, links: list[str]) -> None:
        self._links.update(link for link in links if link)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(sorted(self._links), ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return set()
        return {str(item) for item in data}

