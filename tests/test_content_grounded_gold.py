"""Contract tests for the content-grounded gold generator (ADR 0070, #1347).

Locks the properties the construct-validity fix depends on, using a synthetic
in-memory index (no private data crosses the ADR 0005 boundary):

* ``expected_terms[0]`` is a verbatim substring of its seed chunk text — so the
  answer is genuinely body-grounded and exact-match scorable.
* The query embeds only a distinctive content anchor, never the project title
  — the leak the initial pilot suffered (project name named the gold doc to the
  retriever).
* Boilerplate / form-section docs (별지서식, 평가배점 …) yield no case.
* Generation is deterministic and respects the ``n`` cap.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_content_grounded_gold import generate_cases  # noqa: E402


def _chunk(doc_id: str, text: str, project: str = "어떤 사업") -> dict:
    return {"doc_id": doc_id, "text": text, "project": project}


# Each "good" doc carries a distinctive multi-token content phrase that occurs
# in exactly one doc; the boilerplate doc carries only form/section tokens.
_CHUNKS = [
    _chunk("good-1", "벤처확인종합관리시스템 기능개선 과업을 수행한다 상세요건"),
    _chunk("good-2", "축산물이력관리시스템 개선 용역을 추진하는 범위 설명"),
    _chunk("boiler-1", "별지서식 양식 배점 공동수급 협정서 첨부 붙임 인감 위임장"),
    _chunk("distract-1", "보안 점검 절차의 일반 설명과 일정 안내 문구"),
]


class GenerateCasesContractTest(unittest.TestCase):
    def test_terms_are_verbatim_substrings_of_seed_text(self) -> None:
        cases, _ = generate_cases(_CHUNKS, n=10)
        self.assertTrue(cases, "fixture must yield at least one content-grounded case")
        text_by_doc = {c["doc_id"]: c["text"] for c in _CHUNKS}
        for case in cases:
            doc = case["expected_doc_ids"][0]
            term = case["expected_terms"][0]
            self.assertIn(
                term, text_by_doc[doc],
                f"expected_terms must be verbatim in body of {doc}",
            )

    def test_query_has_no_project_title_leak(self) -> None:
        cases, _ = generate_cases(_CHUNKS, n=10)
        for case in cases:
            q = case["query"]
            # The project title fixture is "어떤 사업"; it must not appear, and the
            # pilot's bracket form 「…」 must be absent.
            self.assertNotIn("어떤 사업", q)
            self.assertNotIn("「", q)
            self.assertNotIn("」", q)

    def test_case_shape_is_single_doc_content_grounded(self) -> None:
        cases, _ = generate_cases(_CHUNKS, n=10)
        for case in cases:
            self.assertEqual(case["query_type"], "single_doc")
            self.assertEqual(case["expected_doc_ids"].__len__(), 1)
            self.assertEqual(case["hardcase_categories"], ["content_grounded"])

    def test_boilerplate_doc_yields_no_case(self) -> None:
        cases, skipped = generate_cases(_CHUNKS, n=10)
        produced_docs = {c["expected_doc_ids"][0] for c in cases}
        self.assertNotIn("boiler-1", produced_docs)
        self.assertGreaterEqual(skipped, 1, "boilerplate candidate must be skipped")

    def test_duplicated_content_phrase_yields_no_case(self) -> None:
        chunks = [
            _chunk("dup-1", "위험관리플랫폼 통합관제 고도화 요구사항을 설명한다"),
            _chunk("dup-2", "위험관리플랫폼 통합관제 고도화 요구사항을 설명한다"),
        ]

        cases, skipped = generate_cases(chunks, n=10)

        self.assertEqual(cases, [])
        self.assertEqual(skipped, 0)

    def test_deterministic_and_respects_n_cap(self) -> None:
        first, _ = generate_cases(_CHUNKS, n=1)
        second, _ = generate_cases(_CHUNKS, n=1)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 1)


if __name__ == "__main__":
    unittest.main()
