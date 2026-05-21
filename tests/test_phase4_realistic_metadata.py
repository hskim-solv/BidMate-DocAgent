"""Unit + smoke tests for scripts/phase4_realistic_metadata_ablation.py.

These exercise the realistic query-time extractor wiring WITHOUT loading a
real index or running retrieval (default CI tier): synthetic corpus
catalogs, synthetic per-case rows, and a file-based --reaggregate round
trip. The retrieval path itself is covered by the oracle runner's tests +
the existing rag_retrieval regression suite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from rag_indexing import metadata_targets
from scripts.phase4_realistic_metadata_ablation import (
    EXTRACTOR_HIT_TAG,
    EXTRACTOR_MISS_TAG,
    FOLLOW_UP_TAG,
    _categories_for_row,
    _extracted_agency_project,
    _extraction_quality,
    _plan_for_variant,
    _prepare_case,
    _resolve_specs,
    main,
)


def _catalog() -> list[dict]:
    index = {
        "documents": [
            {
                "doc_id": "d1",
                "agency": "한국전자통신연구원",
                "project": "차세대 통신 시스템 구축 사업",
            },
            {
                "doc_id": "d2",
                "agency": "한국교육학술정보원",
                "project": "대학재정정보시스템 고도화",
            },
        ]
    }
    return metadata_targets(index)


def test_variant_spec_resolution_four_variants() -> None:
    specs = _resolve_specs(argparse.Namespace(index_dir="data/index/real100_kordoc"))
    assert [s.name for s in specs] == [
        "no_metadata",
        "extractor_soft_agency",
        "extractor_prefilter_agency",
        "extractor_prefilter_project",
    ]
    assert [s.prefilter for s in specs] == ["none", "none", "agency", "project"]
    assert [s.inject_entities for s in specs] == [False, True, False, False]
    # All four share one index dir (no reindexing).
    assert len({str(s.index_dir) for s in specs}) == 1


def test_extracted_agency_from_query_text_only() -> None:
    targets = _catalog()
    agency, project = _extracted_agency_project(
        "한국전자통신연구원의 사업 예산은 얼마인가?", targets
    )
    assert agency == "한국전자통신연구원"
    # Project of the matched doc may also surface; agency is the assertion.
    agency2, _ = _extracted_agency_project("점심 메뉴 추천해줘", targets)
    assert agency2 is None  # no catalog signal in an unrelated query


def test_plan_uses_extraction_not_gold() -> None:
    """The retrieval plan must depend ONLY on the extracted agency/project,
    never on gold (expected_doc_ids). Two cases with an identical query but
    different gold docs must yield identical plans.
    """
    targets = _catalog()
    doc_meta = {
        "d1": {"doc_id": "d1", "agency": "한국전자통신연구원", "project": "차세대 통신 시스템 구축 사업"},
        "d2": {"doc_id": "d2", "agency": "한국교육학술정보원", "project": "대학재정정보시스템 고도화"},
    }
    query = "한국전자통신연구원의 사업 예산은?"
    case_a = {"id": "a", "query": query, "expected_doc_ids": ["d1"]}
    case_b = {"id": "b", "query": query, "expected_doc_ids": ["d2"]}
    prep_a = _prepare_case(case_a, targets, doc_meta)
    prep_b = _prepare_case(case_b, targets, doc_meta)

    # Extraction is query-only, so identical across the two cases.
    assert prep_a["_ext_agency"] == prep_b["_ext_agency"] == "한국전자통신연구원"
    # Gold differs (it comes from expected_doc_ids).
    assert prep_a["_gold_agency"] != prep_b["_gold_agency"]

    spec = _resolve_specs(argparse.Namespace(index_dir="x"))[2]  # prefilter_agency
    plan_a = _plan_for_variant(spec, prep_a["_ext_agency"], prep_a["_ext_project"], 20)
    plan_b = _plan_for_variant(spec, prep_b["_ext_agency"], prep_b["_ext_project"], 20)
    assert plan_a == plan_b
    assert plan_a["metadata_filters"] == {"agencies": ["한국전자통신연구원"]}


def test_categories_followup_and_extractor_cohorts() -> None:
    base = {"hardcase_categories": ["multi_hop"], "query_type": "single_doc"}
    hit = _categories_for_row(base, gold_agency="A기관", agency_match=True)
    miss = _categories_for_row(base, gold_agency="A기관", agency_match=False)
    assert EXTRACTOR_HIT_TAG in hit and EXTRACTOR_MISS_TAG not in hit
    assert EXTRACTOR_MISS_TAG in miss and EXTRACTOR_HIT_TAG not in miss
    assert "multi_hop" in hit

    fu = _categories_for_row(
        {"hardcase_categories": [], "query_type": "follow_up"},
        gold_agency=None,
        agency_match=False,
    )
    assert FOLLOW_UP_TAG in fu
    # No gold → no extractor cohort tag.
    assert EXTRACTOR_HIT_TAG not in fu and EXTRACTOR_MISS_TAG not in fu


def test_extraction_quality_hand_calc() -> None:
    rows = [
        # agency: 3 answerable, 2 extracted, 1 correct
        {"gold_agency": "A", "extracted_agency": "A", "agency_match": True,
         "gold_project": None, "extracted_project": None, "project_match": False,
         "query_type": "single_doc"},
        {"gold_agency": "B", "extracted_agency": "X", "agency_match": False,
         "gold_project": "P", "extracted_project": "P", "project_match": True,
         "query_type": "single_doc"},
        {"gold_agency": "C", "extracted_agency": None, "agency_match": False,
         "gold_project": None, "extracted_project": None, "project_match": False,
         "query_type": "follow_up"},
    ]
    q = _extraction_quality(rows)
    assert q["n_answerable_agency"] == 3
    assert q["agency_extracted_n"] == 2
    assert q["agency_correct_n"] == 1
    assert q["agency_recall"] == round(1 / 3, 3)
    assert q["agency_precision"] == round(1 / 2, 3)
    assert q["n_answerable_project"] == 1
    assert q["project_recall"] == 1.0
    assert q["project_precision"] == 1.0
    assert q["follow_up_n"] == 1
    assert q["follow_up_agency_correct_n"] == 0


def test_reaggregate_byte_identical_scores(tmp_path: Path) -> None:
    """--reaggregate must regenerate REPORT.md + re-derive categories WITHOUT
    altering the persisted retrieval scores (determinism guarantee).
    """
    measurements = {
        "no_metadata": {
            "variant": "no_metadata",
            "per_case": [
                {"qid": "a", "query_type": "single_doc", "categories": ["stale"],
                 "gold_agency": "한국전자통신연구원", "gold_project": None,
                 "extracted_agency": "한국전자통신연구원", "extracted_project": None,
                 "agency_match": True, "project_match": False,
                 "chunk_recall@5": 0.0, "chunk_recall@10": 0.5, "mrr": 0.25, "ndcg@10": 0.3,
                 "latency_ms": 10.0},
                {"qid": "b", "query_type": "abstention", "categories": ["stale"],
                 "gold_agency": None, "gold_project": None,
                 "extracted_agency": None, "extracted_project": None,
                 "agency_match": False, "project_match": False,
                 "chunk_recall@5": None, "chunk_recall@10": None, "mrr": None, "ndcg@10": None,
                 "latency_ms": 9.0},
            ],
            "latency_ms": {"p50": 9.5, "p95": 10.0, "mean": 9.5, "n": 2},
        },
        "extractor_prefilter_agency": {
            "variant": "extractor_prefilter_agency",
            "per_case": [
                {"qid": "a", "query_type": "single_doc", "categories": ["stale"],
                 "gold_agency": "한국전자통신연구원", "gold_project": None,
                 "extracted_agency": "한국전자통신연구원", "extracted_project": None,
                 "agency_match": True, "project_match": False,
                 "chunk_recall@5": 0.5, "chunk_recall@10": 1.0, "mrr": 0.5, "ndcg@10": 0.6,
                 "latency_ms": 2.0},
                {"qid": "b", "query_type": "abstention", "categories": ["stale"],
                 "gold_agency": None, "gold_project": None,
                 "extracted_agency": None, "extracted_project": None,
                 "agency_match": False, "project_match": False,
                 "chunk_recall@5": None, "chunk_recall@10": None, "mrr": None, "ndcg@10": None,
                 "latency_ms": 9.0},
            ],
            "latency_ms": {"p50": 5.5, "p95": 9.0, "mean": 5.5, "n": 2},
        },
    }
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    raw = src_dir / "raw_results.json"
    raw.write_text(json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
    specs = [
        {"name": "no_metadata", "metadata_first": False, "prefilter": "none",
         "inject_entities": False, "index_dir": "data/index/real100_kordoc",
         "num_documents": 100, "num_chunks": 26376},
        {"name": "extractor_prefilter_agency", "metadata_first": False, "prefilter": "agency",
         "inject_entities": False, "index_dir": "data/index/real100_kordoc",
         "num_documents": 100, "num_chunks": 26376},
    ]
    (src_dir / "metadata_specs.json").write_text(
        json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cfg = {"cases": [
        {"id": "a", "query": "q", "query_type": "single_doc",
         "hardcase_categories": ["multi_hop"]},
        {"id": "b", "query": "q2", "query_type": "abstention",
         "hardcase_categories": ["no_answer"]},
    ]}
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    out_dir = tmp_path / "out"
    rc = main([
        "--reaggregate", str(raw),
        "--eval_config", str(cfg_path),
        "--output_dir", str(out_dir),
        "--seeds", "17,23,29",
        "--ks", "5,10",
    ])
    assert rc == 0

    report = (out_dir / "REPORT.md").read_text(encoding="utf-8")
    assert report.count("\n") <= 200
    assert "추출 품질" in report
    for section in ("chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10"):
        assert section in report

    out_raw = json.loads((out_dir / "raw_results.json").read_text(encoding="utf-8"))
    # Retrieval scores byte-identical; categories re-derived (stale -> real).
    row_a = out_raw["no_metadata"]["per_case"][0]
    assert row_a["chunk_recall@10"] == 0.5
    assert "stale" not in row_a["categories"]
    assert "multi_hop" in row_a["categories"]
    assert EXTRACTOR_HIT_TAG in row_a["categories"]  # agency_match True + gold present
