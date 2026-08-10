from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Generic, Iterable, Protocol, TypeVar


_IGNORED_PUNCTUATION = str.maketrans("", "", "·•.,，。'\"“”‘’")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class CompanyNamedRecord(Protocol):
    company_name: str


RecordT = TypeVar("RecordT", bound=CompanyNamedRecord)


@dataclass(frozen=True)
class CompanyMatchResult(Generic[RecordT]):
    query_name: str
    normalized_name: str
    status: str
    match_method: str
    record: RecordT | None
    candidate_names: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return self.record is not None


def normalize_company_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = _WHITESPACE_PATTERN.sub("", text)
    return text.translate(_IGNORED_PUNCTUATION).casefold()


class CompanyRegistryMatcher(Generic[RecordT]):
    """Conservative matcher: exact name first, then normalized exact name."""

    def __init__(self, records: Iterable[RecordT]):
        self._exact: dict[str, list[RecordT]] = {}
        self._normalized: dict[str, list[RecordT]] = {}
        for record in records:
            exact_name = str(record.company_name or "").strip()
            normalized_name = normalize_company_name(exact_name)
            if not exact_name or not normalized_name:
                continue
            self._exact.setdefault(exact_name, []).append(record)
            self._normalized.setdefault(normalized_name, []).append(record)

    def match(self, company_name: object) -> CompanyMatchResult[RecordT]:
        query_name = str(company_name or "").strip()
        normalized_name = normalize_company_name(query_name)
        if not normalized_name:
            return CompanyMatchResult(
                query_name=query_name,
                normalized_name=normalized_name,
                status="not_found",
                match_method="none",
                record=None,
            )

        exact_candidates = self._exact.get(query_name, [])
        if len(exact_candidates) == 1:
            return CompanyMatchResult(
                query_name=query_name,
                normalized_name=normalized_name,
                status="matched",
                match_method="exact",
                record=exact_candidates[0],
            )
        normalized_candidates = self._normalized.get(normalized_name, [])
        if len(normalized_candidates) == 1:
            return CompanyMatchResult(
                query_name=query_name,
                normalized_name=normalized_name,
                status="matched",
                match_method="normalized_exact",
                record=normalized_candidates[0],
            )
        if normalized_candidates:
            return CompanyMatchResult(
                query_name=query_name,
                normalized_name=normalized_name,
                status="ambiguous",
                match_method="normalized_exact",
                record=None,
                candidate_names=tuple(
                    sorted({record.company_name for record in normalized_candidates})
                ),
            )
        return CompanyMatchResult(
            query_name=query_name,
            normalized_name=normalized_name,
            status="not_found",
            match_method="none",
            record=None,
        )
