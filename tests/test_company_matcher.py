from __future__ import annotations

import unittest
from dataclasses import dataclass

from app.company_matcher import CompanyRegistryMatcher, normalize_company_name


@dataclass(frozen=True)
class NamedRecord:
    company_name: str


class CompanyMatcherTest(unittest.TestCase):
    def test_normalizes_full_width_spacing_and_punctuation(self):
        self.assertEqual(
            normalize_company_name("海门　智能·装备有限公司"),
            normalize_company_name("海门智能装备有限公司"),
        )

    def test_exact_then_normalized_match_and_not_found(self):
        record = NamedRecord("海门智能装备有限公司")
        matcher = CompanyRegistryMatcher([record])

        exact = matcher.match("海门智能装备有限公司")
        normalized = matcher.match("海门 智能装备有限公司")
        missing = matcher.match("其他企业")

        self.assertEqual(exact.match_method, "exact")
        self.assertIs(exact.record, record)
        self.assertEqual(normalized.match_method, "normalized_exact")
        self.assertIs(normalized.record, record)
        self.assertEqual(missing.status, "not_found")

    def test_ambiguous_normalized_names_are_not_guessed(self):
        matcher = CompanyRegistryMatcher(
            [NamedRecord("甲·公司"), NamedRecord("甲公司")]
        )

        result = matcher.match("甲 公司")

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.record)
        self.assertEqual(set(result.candidate_names), {"甲·公司", "甲公司"})


if __name__ == "__main__":
    unittest.main()
