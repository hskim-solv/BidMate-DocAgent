from __future__ import annotations

import pytest

from scripts.component_eval.gold_annotation_survey import survey_case


@pytest.mark.parametrize(
    ("case", "yaml_terms", "cid_to_text", "expected"),
    [
        ({"id": "q1", "gold_chunk_ids": []}, {"q1": ["alpha"]}, {}, "no_gold"),
        (
            {"id": "q1", "gold_chunk_ids": ["missing"]},
            {"q1": ["alpha"]},
            {"chunk-1": "alpha beta"},
            "gold_not_in_index",
        ),
        ({"id": "q1", "gold_chunk_ids": ["chunk-1"]}, {}, {"chunk-1": "alpha beta"}, "gold_no_terms"),
        (
            {"id": "q1", "gold_chunk_ids": ["chunk-1", "chunk-2"]},
            {"q1": ["alpha", "gamma"]},
            {"chunk-1": "alpha beta", "chunk-2": "gamma delta"},
            "gold_valid",
        ),
        (
            {"id": "q1", "gold_chunk_ids": ["chunk-1"]},
            {"q1": ["alpha", "missing-term"]},
            {"chunk-1": "alpha beta"},
            "gold_drift",
        ),
    ],
)
def test_survey_case_classifies_gold_annotation_health(case, yaml_terms, cid_to_text, expected) -> None:
    assert survey_case(case, yaml_terms, cid_to_text) == expected
