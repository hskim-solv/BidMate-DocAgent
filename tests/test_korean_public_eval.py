"""Contract tests for the Korean public RAG bench surface (ADR 0018).

Locks the determinism of the KorQuAD sampler and the metric shape of
the runner. We do NOT run against the real KorQuAD download here —
network access is forbidden in CI and 93 MB downloads would dwarf
the rest of the test suite. Instead we use a tiny fixture that
mirrors the upstream shape (article → context → qas list).
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from eval.korean_public import fetch_korquad, run as kp_run  # noqa: E402


def _tiny_korquad_raw() -> dict:
    """Mini KorQuAD-shaped payload: 2 articles, 4 scoreable QAs."""
    article_a = {
        "title": "기관_A",
        "context": (
            "<html><body><p>기관 A는 보안 통제 매뉴얼과 로그 추적 시스템을 "
            "구축한다. 운영자 교육 자료도 필수 산출물이다.</p></body></html>"
        ),
        "qas": [
            {
                "id": "tiny_a_1",
                "question": "기관 A의 필수 산출물은?",
                "answer": {"text": "운영자 교육 자료", "answer_start": 0},
            },
            {
                "id": "tiny_a_2",
                "question": "기관 A는 무엇을 추적하나요?",
                "answer": {"text": "로그", "answer_start": 0},
            },
        ],
    }
    article_b = {
        "title": "기관_B",
        "context": (
            "기관 B는 데이터 표준 사전과 MLOps 운영 가이드를 갖춘다. "
            "프로젝트는 3개월 안에 마쳐야 한다."
        ),
        "qas": [
            {
                "id": "tiny_b_1",
                "question": "기관 B 프로젝트 기간은?",
                "answer": {"text": "3개월", "answer_start": 0},
            },
            {
                "id": "tiny_b_2",
                "question": "기관 B의 운영 가이드 이름은?",
                "answer": {"text": "MLOps 운영 가이드", "answer_start": 0},
            },
        ],
    }
    return {"version": "tiny", "data": [article_a, article_b]}


def test_sample_korquad_strips_html_and_dedupes_articles() -> None:
    payload = fetch_korquad.sample_korquad(_tiny_korquad_raw(), sample_size=4, seed=17)
    titles = {a["title"] for a in payload["articles"]}
    # Both articles should be referenced by at least one question.
    assert titles == {"기관_A", "기관_B"}
    # HTML must be stripped from the article that had it.
    article_a = next(a for a in payload["articles"] if a["title"] == "기관_A")
    assert "<html>" not in article_a["context"]
    assert "<p>" not in article_a["context"]
    # The plain-text answer must still be present (round-trip survives).
    assert "운영자 교육 자료" in article_a["context"]


def test_sample_korquad_is_deterministic() -> None:
    a = fetch_korquad.sample_korquad(_tiny_korquad_raw(), sample_size=3, seed=17)
    b = fetch_korquad.sample_korquad(_tiny_korquad_raw(), sample_size=3, seed=17)
    assert fetch_korquad.sample_sha256(a) == fetch_korquad.sample_sha256(b)


def test_sample_korquad_rejects_overlarge_request() -> None:
    with pytest.raises(SystemExit):
        fetch_korquad.sample_korquad(_tiny_korquad_raw(), sample_size=999, seed=17)


def test_read_zip_or_path_handles_zip(tmp_path: Path) -> None:
    raw = _tiny_korquad_raw()
    zpath = tmp_path / "tiny.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("KorQuAD_tiny.json", json.dumps(raw, ensure_ascii=False))
    parsed = fetch_korquad._read_json_from_zip_or_path(zpath)
    assert parsed["version"] == "tiny"
    assert len(parsed["data"]) == 2


def test_evaluate_returns_expected_metric_shape() -> None:
    sample = fetch_korquad.sample_korquad(_tiny_korquad_raw(), sample_size=4, seed=17)
    summary = kp_run.evaluate(sample, pipeline="naive_baseline", top_k=2)
    assert summary["schema_version"] == 1
    assert summary["num_predictions"] == 4
    metrics = summary["metrics"]
    for key in (
        "retrieval_recall_at_top_k",
        "answer_substring_match",
        "citation_doc_precision",
        "citation_coverage",
        "latency",
    ):
        assert key in metrics, f"missing metric {key}"
    # Per-case rows preserved for downstream debugging.
    assert len(summary["cases"]) == 4
    for case in summary["cases"]:
        for field in ("gold_doc_id", "gold_answer", "retrieval_hit_top_k", "substring_hit"):
            assert field in case, f"case missing {field}"


def test_doc_id_handles_korean_titles() -> None:
    # The fetcher / runner must round-trip a Korean title with spaces
    # and underscores so the gold-doc-id mapping is stable across both.
    doc_id = kp_run._to_doc_id("기관 A 사업")
    assert doc_id.startswith("korquad::")
    assert "기관" in doc_id
    assert " " not in doc_id  # spaces collapsed
