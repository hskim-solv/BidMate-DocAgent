from __future__ import annotations

import json
from pathlib import Path

from scripts.render_real100_v2_latency_budget import build_budget, main, render_markdown


def _baseline() -> dict[str, object]:
    return {
        "num_predictions": 3,
        "pipeline": "agentic_full",
        "primary_run": "full",
        "prompt_profile": "structured_grounded_claims",
        "latency": {"mean": 100.4, "p50": 90.2, "p95": 200.1},
        "stage_latency": {
            "query_analysis_ms": {"mean": 10.0, "p50": 9.0, "p95": 20.1},
            "context_resolution_ms": {"mean": 1.0, "p50": 1.0, "p95": 2.0},
            "retrieve_ms": {"mean": 50.0, "p50": 45.0, "p95": 80.1},
            "verify_ms": {"mean": 5.0, "p50": 4.0, "p95": 10.0},
            "answer_generation_ms": {"mean": 2.0, "p50": 1.0, "p95": 4.0},
        },
    }


def test_build_budget_sets_latency_thresholds_and_cost_status() -> None:
    report = build_budget(_baseline(), source={"input_artifact": "reports/real100_v2/baseline.aggregate.json"})

    assert report["profile_type"] == "private_real100_v2_latency_cost_budget"
    assert report["baseline_latency"]["p50_ms"] == 90.2
    assert report["baseline_latency"]["p95_ms"] == 200.1
    assert report["baseline_latency"]["p99_status"] == "not_observed_in_source_aggregate"
    assert report["baseline_latency"]["soft_ceiling_ms"] == 251.0
    assert report["baseline_latency"]["hard_ceiling_ms"] == 301.0
    assert report["stage_latency"]["retrieve_ms"]["hard_ceiling_ms"] == 121.0
    assert report["cost_envelope"]["status"] == "not_observable_from_committed_aggregate"
    assert report["downstream_use"]["applies_to"][0] == "T-2026-0032 reranker candidate-budget experiment"
    assert report["privacy"]["aggregate_only"] is True
    assert report["non_claims"]["performance_improvement_claim"] is False


def test_rendered_output_has_no_private_fields() -> None:
    payload = _baseline()
    payload["query"] = "PRIVATE QUERY"
    payload["doc_id"] = "SECRET_DOC_ID"
    payload["chunk_id"] = "SECRET_CHUNK_ID"
    report = build_budget(payload, source={"input_artifact": "external_private/real100_v2_baseline_aggregate"})
    rendered = json.dumps(report, ensure_ascii=False) + render_markdown(report)

    for forbidden in (
        "PRIVATE QUERY",
        "SECRET_DOC_ID",
        "SECRET_CHUNK_ID",
        "/Users/",
    ):
        assert forbidden not in rendered
    assert "p99 is named but not observed" in rendered
    assert "Legacy `real100`/v1/221/kordoc" in rendered


def test_cli_writes_outputs_and_rejects_legacy_input(tmp_path: Path) -> None:
    v2_dir = tmp_path / "reports" / "real100_v2"
    v2_dir.mkdir(parents=True)
    summary = v2_dir / "baseline.aggregate.json"
    out_json = tmp_path / "budget.aggregate.json"
    out_md = tmp_path / "budget.md"
    summary.write_text(json.dumps(_baseline()), encoding="utf-8")

    assert main(["--summary", str(summary), "--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    written = json.loads(out_json.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert written["source"]["input_location_redacted"] is True
    assert "`T-2026-0030`" in out_md.read_text(encoding="utf-8")

    legacy_dir = tmp_path / "reports" / "real100"
    legacy_dir.mkdir(parents=True)
    legacy_summary = legacy_dir / "baseline.aggregate.json"
    legacy_summary.write_text(json.dumps(_baseline()), encoding="utf-8")

    assert main(["--summary", str(legacy_summary), "--out-json", str(out_json), "--out-md", str(out_md)]) == 1
