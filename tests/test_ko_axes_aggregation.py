"""Tests for Korean RFP eval-axis detection (issue #126).

Aggregation in :mod:`eval.evaluate_dev_results` is pandas-backed and
not part of the CI test suite; it is covered indirectly via end-to-end
use of the dev evaluator. The detection logic is pandas-free and gets
the bulk of test coverage here.
"""

from __future__ import annotations

import unittest

from eval.ko_axes import (
    KO_AXES,
    KO_AXIS_ABBREVIATION,
    KO_AXIS_CURRENCY,
    KO_AXIS_DATE,
    KO_AXIS_HANJA,
    KO_AXIS_PROJECT_NUMBER,
    detect_ko_axes,
)


class TestDetectKoAxes(unittest.TestCase):
    def test_currency_axis(self) -> None:
        cases = [
            {"gold_answer": "사업금액은 493,763,000원이다.", "must_include": "493,763,000원"},
            {"gold_answer": "총 사업비는 4억 9,376만 3천원이다."},
            {"gold_answer": "", "acceptable_aliases": "일금 일억 오천만원"},
            {"gold_answer": "삼억원의 예산이 책정되어 있다."},
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assertIn(KO_AXIS_CURRENCY, detect_ko_axes(row))

    def test_date_axis(self) -> None:
        cases = [
            {"question": "제출 기한은 2026년 5월 11일까지?"},
            {"gold_answer": "착수일로부터 90일 이내다."},
            {"gold_answer": "2026-05-11"},
            {"must_include": "2026/05/11"},
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assertIn(KO_AXIS_DATE, detect_ko_axes(row))

    def test_hanja_axis(self) -> None:
        row = {"question": "본 사업의 推進 일정은?"}
        self.assertIn(KO_AXIS_HANJA, detect_ko_axes(row))

    def test_project_number_axis(self) -> None:
        # Project-number axis is for explicit ID markers, not project
        # descriptions. Year + project name without a code is NOT a
        # project-number axis match — that's metadata, not an ID.
        cases = [
            {"question": "[사전공개] 학업성취도 종단분석 용역의 추진목표는?"},
            {"question": "[입찰공고] 산학협력단 시스템 운영의 범위는?"},
            {"question": "사업번호 RFP-2024-0142 의 범위는?"},
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assertIn(KO_AXIS_PROJECT_NUMBER, detect_ko_axes(row))

    def test_abbreviation_axis(self) -> None:
        cases = [
            {"question": "버스정보시스템(BIS) 구축 범위는?"},
            {"question": "AI 시스템의 보안 요구사항은?"},
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assertIn(KO_AXIS_ABBREVIATION, detect_ko_axes(row))

    def test_no_axis(self) -> None:
        row = {
            "question": "이 사업의 추진목표는?",
            "gold_answer": "맞춤형 교육 지원 기반 마련이다.",
            "must_include": "맞춤형 교육 지원",
            "acceptable_aliases": "",
        }
        self.assertEqual(detect_ko_axes(row), [])

    def test_multi_axis(self) -> None:
        row = {
            "question": "[사전공개] BIS 구축사업의 사업금액과 제출기한은?",
            "gold_answer": "493,763,000원이고 2026년 5월 11일까지다.",
            "must_include": "493,763,000원|2026년 5월 11일",
            "acceptable_aliases": "",
        }
        axes = detect_ko_axes(row)
        self.assertIn(KO_AXIS_CURRENCY, axes)
        self.assertIn(KO_AXIS_DATE, axes)
        self.assertIn(KO_AXIS_PROJECT_NUMBER, axes)
        self.assertIn(KO_AXIS_ABBREVIATION, axes)

    def test_axes_ordered_by_declaration(self) -> None:
        # Even when multiple axes match, the returned list follows
        # KO_AXES declaration order so downstream consumers can rely on
        # a stable ordering.
        row = {
            "question": "BIS 구축 일정과 사업금액은?",
            "gold_answer": "2026-05-11까지, 10,000,000원이다.",
        }
        axes = detect_ko_axes(row)
        declared = [a for a in KO_AXES if a in axes]
        self.assertEqual(axes, declared)


if __name__ == "__main__":
    unittest.main()
