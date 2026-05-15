"""Tests for scripts/rag_pipeline_eda.py.

Covers:
  - ADR 0005 boundary leak guard: sentinel strings planted in case.id, query,
    answer, evidence text, retrieved_chunk_ids never appear in the rendered
    rag_pipeline.md or rag_pipeline.aggregate.json.
  - Deterministic output: running the script twice on the same fixture yields
    byte-identical md and json.
  - eval_summary.json required: script exits non-zero when missing.
  - Degenerate input (1 case): all 7 axis keys still present.
  - Top-level JSON keys allowlist.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag_pipeline_eda.py"

SENTINEL_CASE_ID = "SECRET_CASE_ID_XYZ_ZZ"
SENTINEL_QUERY = "SECRET_QUERY_XYZ_ZZ"
SENTINEL_ANSWER = "SECRET_ANSWER_XYZ_ZZ"
SENTINEL_EVIDENCE_TEXT = "SECRET_EVIDENCE_TEXT_XYZ_ZZ"
SENTINEL_CHUNK = "SECRET_CHUNK_XYZ_ZZ"
# Regression: real-100 retry reasons embed doc-id + agency after the enum prefix
# (e.g. "missing_comparison_doc:<doc_id>,<agency>"). The script must strip the
# suffix before counting — otherwise the dynamic context leaks into outputs.
SENTINEL_RETRY_DOC = "SECRET_RETRY_DOC_XYZ_ZZ"
SENTINEL_RETRY_AGENCY = "SECRET_RETRY_AGENCY_XYZ_ZZ"

ALL_SENTINELS = (
    SENTINEL_CASE_ID,
    SENTINEL_QUERY,
    SENTINEL_ANSWER,
    SENTINEL_EVIDENCE_TEXT,
    SENTINEL_CHUNK,
    SENTINEL_RETRY_DOC,
    SENTINEL_RETRY_AGENCY,
)


def _build_case(
    i: int,
    *,
    query_type: str,
    cold_start: bool = False,
    retry_count: int = 0,
    retry_reasons: list[str] | None = None,
    has_rerank: bool = False,
    confidence: float | None = None,
    abstained: bool = False,
    answer_status: str = "supported",
    chunk_recall_at_10: float = 0.5,
    citation_precision: float = 0.5,
    groundedness: float = 0.5,
    rerank_delta_mrr: float | None = None,
) -> dict:
    case = {
        # Sentinel-bearing fields (must never leak into outputs):
        "id": f"{SENTINEL_CASE_ID}_{i}",
        "query": f"{SENTINEL_QUERY}_{i}",
        "answer": f"{SENTINEL_ANSWER}_{i}",
        "resolved_query": f"{SENTINEL_QUERY}_resolved_{i}",
        "evidence": [
            {
                "text": SENTINEL_EVIDENCE_TEXT + f"_{i}",
                "doc_id": f"doc_{i}",
                "chunk_id": f"{SENTINEL_CHUNK}_{i}",
            }
        ],
        "retrieved_chunk_ids": [f"{SENTINEL_CHUNK}_{i}_a", f"{SENTINEL_CHUNK}_{i}_b"],
        "gold_chunk_ids": [f"{SENTINEL_CHUNK}_{i}_a"],
        "evidence_doc_ids": [f"doc_{i}"],
        "expected_doc_ids": [f"doc_{i}"],
        "metadata_selected_doc_ids": [f"doc_{i}"],
        # Numeric / safe fields:
        "query_type": query_type,
        "chunk_recall_at_5": chunk_recall_at_10,
        "chunk_recall_at_10": chunk_recall_at_10,
        "chunk_recall_at_20": chunk_recall_at_10,
        "chunk_mrr": chunk_recall_at_10,
        "chunk_ndcg_at_10": chunk_recall_at_10,
        "chunk_ndcg_at_20": chunk_recall_at_10,
        "rerank_delta_mrr": rerank_delta_mrr if has_rerank else None,
        "rerank_delta_ndcg_at_10": (rerank_delta_mrr if has_rerank else None),
        "last_attempt_verified": True,
        "retry_count": retry_count,
        "retry_trigger_reasons": retry_reasons or [],
        "selected_top_k": 4,
        "metadata_candidate_count": 3,
        "stage_latency": {
            "query_analysis_ms": 1.0,
            "context_resolution_ms": 0.5,
            "retrieve_ms": 10.0,
            "verify_ms": 5.0,
            "answer_generation_ms": 2.0,
        },
        "latency_ms": 18.5,
        "confidence": confidence,
        "abstained": abstained,
        "answer_status": answer_status,
        "answer_format_compliance": 1.0,
        "citation_precision": citation_precision,
        "groundedness": groundedness,
        "cold_start": cold_start,
    }
    return case


def _make_fixture(tmp_path: Path) -> Path:
    cases: list[dict] = []
    # 6 single_doc (mix of rerank, retry, cold/warm)
    for i in range(6):
        cases.append(
            _build_case(
                i,
                query_type="single_doc",
                cold_start=(i == 0),
                retry_count=(i % 3),
                retry_reasons=["topic_not_grounded"] if i % 2 else [],
                has_rerank=(i % 2 == 0),
                rerank_delta_mrr=(0.1 if i % 4 == 0 else -0.05),
                confidence=0.7,
                chunk_recall_at_10=0.8,
                citation_precision=0.7,
                groundedness=0.8,
            )
        )
    # 2 comparison
    for i in range(6, 8):
        cases.append(
            _build_case(
                i,
                query_type="comparison",
                cold_start=(i == 6),
                has_rerank=True,
                rerank_delta_mrr=0.0,
                confidence=0.5,
                chunk_recall_at_10=0.4,
                citation_precision=0.4,
                groundedness=0.5,
            )
        )
    # 2 follow_up — one carries a dynamic retry reason of the
    # ``missing_comparison_doc:<doc_id>,<agency>`` shape that real-100 actually
    # emits; the script must strip the suffix before counting.
    for i in range(8, 10):
        cases.append(
            _build_case(
                i,
                query_type="follow_up",
                retry_count=1,
                retry_reasons=(
                    [
                        f"missing_comparison_doc:{SENTINEL_RETRY_DOC}_{i},{SENTINEL_RETRY_AGENCY}_{i}",
                        f"missing_comparison_entity:{SENTINEL_RETRY_AGENCY}_{i}",
                    ]
                    if i == 8
                    else ["insufficient_evidence"]
                ),
                confidence=0.3,
                chunk_recall_at_10=0.2,
                citation_precision=0.2,
                groundedness=0.3,
            )
        )
    # 2 abstention
    for i in range(10, 12):
        cases.append(
            _build_case(
                i,
                query_type="abstention",
                abstained=True,
                answer_status="insufficient",
                confidence=None,
                chunk_recall_at_10=0.0,
                citation_precision=0.0,
                groundedness=0.0,
            )
        )

    eval_summary = {"case_results": cases}
    path = tmp_path / "eval_summary.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(eval_summary, fh, ensure_ascii=False)
    return path


def _run(tmp_path: Path, eval_path: Path, *, baseline: Path | None = None) -> dict[str, Path]:
    out_md = tmp_path / "rag_pipeline.md"
    out_json = tmp_path / "rag_pipeline.aggregate.json"
    figures_dir = tmp_path / "figures"
    cmd = [
        sys.executable, str(SCRIPT),
        "--eval-summary", str(eval_path),
        "--out-md", str(out_md),
        "--out-json", str(out_json),
        "--figures-dir", str(figures_dir),
        "--seed", "0",
    ]
    if baseline is not None:
        cmd.extend(["--baseline", str(baseline)])
    else:
        cmd.extend(["--baseline", str(tmp_path / "_nonexistent_baseline.json")])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    return {"md": out_md, "json": out_json, "figures_dir": figures_dir}


def test_no_sentinel_leak_in_outputs(tmp_path: Path) -> None:
    eval_path = _make_fixture(tmp_path)
    out = _run(tmp_path, eval_path)
    md_text = out["md"].read_text(encoding="utf-8")
    json_text = out["json"].read_text(encoding="utf-8")
    for sentinel in ALL_SENTINELS:
        assert sentinel not in md_text, f"sentinel {sentinel!r} leaked to rag_pipeline.md"
        assert sentinel not in json_text, f"sentinel {sentinel!r} leaked to rag_pipeline.aggregate.json"


def test_deterministic_output(tmp_path: Path) -> None:
    eval_path = _make_fixture(tmp_path)
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    run1.mkdir()
    run2.mkdir()
    out1 = _run(run1, eval_path)
    out2 = _run(run2, eval_path)
    assert out1["md"].read_bytes() == out2["md"].read_bytes(), "rag_pipeline.md drifted between runs"
    assert out1["json"].read_bytes() == out2["json"].read_bytes(), "rag_pipeline.aggregate.json drifted between runs"


def test_eval_summary_required_exits_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    out_md = tmp_path / "rag_pipeline.md"
    out_json = tmp_path / "rag_pipeline.aggregate.json"
    cmd = [
        sys.executable, str(SCRIPT),
        "--eval-summary", str(missing),
        "--out-md", str(out_md),
        "--out-json", str(out_json),
        "--figures-dir", str(tmp_path / "figures"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode != 0, "script should exit non-zero when eval_summary is missing"
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower(), result.stderr


def test_degenerate_input_all_axes_present(tmp_path: Path) -> None:
    single = _build_case(0, query_type="single_doc", cold_start=False, confidence=0.5)
    eval_path = tmp_path / "eval_summary.json"
    with eval_path.open("w", encoding="utf-8") as fh:
        json.dump({"case_results": [single]}, fh)
    out = _run(tmp_path, eval_path)
    aggregate = json.loads(out["json"].read_text(encoding="utf-8"))
    expected_axes = {
        "axis1_retrieval_efficiency",
        "axis2_reranker_contribution",
        "axis3_verification_retry",
        "axis4_stage_latency",
        "axis5_answer_synthesis",
        "axis6_evidence_quality",
        "axis7_cold_start",
    }
    missing = expected_axes - set(aggregate.keys())
    assert not missing, f"axes missing on degenerate input: {missing}"


def test_aggregate_json_keys_allowlist(tmp_path: Path) -> None:
    eval_path = _make_fixture(tmp_path)
    out = _run(tmp_path, eval_path)
    aggregate = json.loads(out["json"].read_text(encoding="utf-8"))
    expected_top = {
        "schema_version",
        "axis1_retrieval_efficiency",
        "axis2_reranker_contribution",
        "axis3_verification_retry",
        "axis4_stage_latency",
        "axis5_answer_synthesis",
        "axis6_evidence_quality",
        "axis7_cold_start",
    }
    assert set(aggregate.keys()) == expected_top, (
        f"unexpected top-level keys: {set(aggregate.keys()) ^ expected_top}"
    )


def test_figures_optional(tmp_path: Path, monkeypatch) -> None:
    """When matplotlib import fails, md/json still write, figures dir untouched."""
    eval_path = _make_fixture(tmp_path)
    out_md = tmp_path / "rag_pipeline.md"
    out_json = tmp_path / "rag_pipeline.aggregate.json"
    figures_dir = tmp_path / "figures_blocked"
    # Block matplotlib by injecting an import-poisoning path
    env = {
        "PYTHONPATH": str(tmp_path / "shim_path"),
        "PATH": "/usr/bin:/bin",
    }
    shim = tmp_path / "shim_path"
    shim.mkdir()
    # Write a shim matplotlib module that raises ImportError on use
    (shim / "matplotlib.py").write_text("raise ImportError('blocked')\n", encoding="utf-8")
    cmd = [
        sys.executable, str(SCRIPT),
        "--eval-summary", str(eval_path),
        "--out-md", str(out_md),
        "--out-json", str(out_json),
        "--figures-dir", str(figures_dir),
        "--baseline", str(tmp_path / "_nonexistent.json"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env={**env}, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out_md.exists()
    assert out_json.exists()
    # figures dir should be empty (or non-existent) when matplotlib is blocked
    assert not figures_dir.exists() or not any(figures_dir.iterdir()), (
        "figures should be skipped when matplotlib unavailable"
    )
