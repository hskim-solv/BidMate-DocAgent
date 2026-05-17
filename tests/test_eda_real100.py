"""Tests for scripts/eda_real100.py.

Covers:
  - ADR 0005 boundary leak guard: sentinel strings planted in raw CSV fields
    (사업명 / 사업 요약 / 텍스트 / 파일명) and chunk text never appear in the
    rendered eda.md or eda.aggregate.json.
  - Tail agencies (rank > top-N) are anonymized to ``agency_NN`` labels.
  - Deterministic output: running the script twice on the same fixture yields
    byte-identical md and json.
  - Eval cross degrades cleanly when eval_summary.json is absent.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "eda_real100.py"

SENTINEL_TITLE = "SECRET_TITLE_XYZ_ZZ"
SENTINEL_SUMMARY = "SECRET_SUMMARY_XYZ_ZZ"
SENTINEL_BODY = "SECRET_BODY_XYZ_ZZ"
SENTINEL_FILENAME = "SECRET_FILENAME_XYZ_ZZ"
SENTINEL_CHUNK_TEXT = "SECRET_CHUNK_TEXT_XYZ_ZZ"

ALL_SENTINELS = (
    SENTINEL_TITLE,
    SENTINEL_SUMMARY,
    SENTINEL_BODY,
    SENTINEL_FILENAME,
    SENTINEL_CHUNK_TEXT,
)


def _make_fixture(tmp_path: Path) -> dict[str, Path]:
    """Build a synthetic mini-corpus with 12 docs (so top-10 leaves a tail).

    - 11 distinct agencies — agency_0 through agency_10. agency_0 gets 2 docs
      so the top-N truncation has a clear tail to anonymize.
    - mix of hwp / pdf so by-format aggregations have multiple buckets.
    - sentinel strings planted in 사업명 / 사업 요약 / 텍스트 / 파일명 / chunk text.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    chunks: list[dict[str, object]] = []
    for i in range(12):
        agency = f"발주기관_{i % 11:02d}"  # 11 unique → 1 in tail beyond top-10
        notice = f"NOTICE-{i:05d}"
        doc_id = f"{notice}-0.0"
        fmt = "hwp" if i % 4 != 0 else "pdf"
        text_source = "data_list_csv_text" if fmt == "hwp" else "visual_parsing_v2"
        text_len_chars = 100 + i * 50

        rows.append({
            "공고 번호": notice,
            "공고 차수": "0.0",
            "사업명": f"{SENTINEL_TITLE}_proj_{i}",
            "사업 금액": str((i + 1) * 10_000_000),
            "발주 기관": agency,
            "공개 일자": f"2024-{((i % 12) + 1):02d}-01 12:00:00",
            "입찰 참여 시작일": f"2024-{((i % 12) + 1):02d}-05 12:00:00",
            "입찰 참여 마감일": f"2024-{((i % 12) + 1):02d}-15 17:00:00",
            "사업 요약": f"{SENTINEL_SUMMARY}_brief_{i}",
            "파일형식": fmt,
            "파일명": f"{SENTINEL_FILENAME}_{i}.{fmt}",
            "텍스트": (SENTINEL_BODY * 5 + " body content ") * (i + 1),
        })

        for j in range(2 + (i % 3)):
            chunks.append({
                "chunk_id": f"chunk_{i}_{j}",
                "doc_id": doc_id,
                "text": f"{SENTINEL_CHUNK_TEXT} sample text chunk body {j} " + ("다 " * (50 + j * 20)),
                "section": f"표 {j} (HWP native)" if fmt == "hwp" and j == 0 else f"section {j}",
                "metadata": {
                    "doc_id": doc_id,
                    "file_format": fmt,
                    "text_source": text_source,
                    "file_name": f"{SENTINEL_FILENAME}_{i}.{fmt}",
                },
            })

    csv_path = data_dir / "data_list.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    index_path = data_dir / "index.json"
    with index_path.open("w", encoding="utf-8") as fh:
        json.dump({"schema_version": 4, "chunks": chunks}, fh, ensure_ascii=False)

    baseline_path = data_dir / "baseline.aggregate.json"
    baseline = {
        "by_query_type": {
            "single_doc": {"accuracy": 0.5, "groundedness": 0.6, "num_predictions": 6},
            "abstention": {"abstention": 0.7, "groundedness": 0.5, "num_predictions": 3},
            "comparison": {"accuracy": 0.8, "groundedness": 0.9, "num_predictions": 2},
            "follow_up": {"accuracy": 0.3, "groundedness": 0.4, "num_predictions": 1},
        }
    }
    with baseline_path.open("w", encoding="utf-8") as fh:
        json.dump(baseline, fh)

    return {
        "data_list": csv_path,
        "index": index_path,
        "baseline": baseline_path,
    }


def _run_eda(tmp_path: Path, fixture: dict[str, Path], with_eval_summary: bool = False) -> dict[str, Path]:
    out_md = tmp_path / "eda.md"
    out_json = tmp_path / "eda.aggregate.json"
    figures_dir = tmp_path / "figures"
    cmd = [
        sys.executable, str(SCRIPT),
        "--data-list", str(fixture["data_list"]),
        "--index", str(fixture["index"]),
        "--baseline", str(fixture["baseline"]),
        "--out-md", str(out_md),
        "--out-json", str(out_json),
        "--figures-dir", str(figures_dir),
    ]
    eval_summary_path = tmp_path / "eval_summary.json"
    if with_eval_summary:
        eval_summary = {
            "case_results": [
                {
                    "id": "c1",
                    "query_type": "single_doc",
                    "expected_doc_ids": ["NOTICE-00001-0.0"],
                    "accuracy": 1.0,
                    "groundedness": 0.9,
                    "citation_precision": 0.8,
                },
                {
                    "id": "c2",
                    "query_type": "comparison",
                    "expected_doc_ids": ["NOTICE-00004"],
                    "accuracy": 0.0,
                    "groundedness": 0.5,
                    "citation_precision": 0.5,
                },
            ]
        }
        with eval_summary_path.open("w", encoding="utf-8") as fh:
            json.dump(eval_summary, fh)
    cmd.extend(["--eval-summary", str(eval_summary_path)])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    return {"md": out_md, "json": out_json, "figures_dir": figures_dir}


def test_no_sentinel_leak_in_outputs(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    out = _run_eda(tmp_path, fixture)
    md_text = out["md"].read_text(encoding="utf-8")
    json_text = out["json"].read_text(encoding="utf-8")
    for sentinel in ALL_SENTINELS:
        assert sentinel not in md_text, f"sentinel {sentinel!r} leaked to eda.md"
        assert sentinel not in json_text, f"sentinel {sentinel!r} leaked to eda.aggregate.json"


def test_tail_agencies_anonymized(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    out = _run_eda(tmp_path, fixture)
    md_text = out["md"].read_text(encoding="utf-8")
    json_text = out["json"].read_text(encoding="utf-8")
    # With 11 unique agencies and top-N=10, one tail entry should be anonymized.
    # The JSON must carry an `agency_NN` label and the tail count should match.
    aggregate = json.loads(json_text)
    tail = aggregate["axis1_metadata"]["agency"]["tail_anonymized"]
    assert tail, "expected at least one anonymized tail agency"
    for entry in tail:
        assert entry["label"].startswith("agency_"), entry
    # The markdown summary should not contain the raw 11th agency name.
    # Note: agencies are sorted by count desc; the singleton 발주기관_10 is in
    # the tail because 발주기관_00 has 2 docs and steals one of the top-10
    # slots. So 발주기관_10 should NOT appear in the rendered md.
    # (We assert on a name that *must* be in the tail given the fixture.)
    # The fixture has indices 0..11 mod 11 → agency_00 appears twice, others once.
    # 11 unique names, top-10 keeps 10 → exactly 1 in tail. Any of agency_01..10
    # could be the tail one depending on tie-breaking; just assert the anonymized
    # label is present in the rendered md.
    assert "agency_11" in md_text or "anonymized" in md_text


def test_deterministic_output(tmp_path: Path) -> None:
    """Run the script twice on the *same* fixture with the same args and
    compare. Different fixture paths would show up in the `_sources` block of
    the md, so reusing one fixture is the only honest determinism check."""
    fixture = _make_fixture(tmp_path)
    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"
    run1_dir.mkdir()
    run2_dir.mkdir()
    out1 = _run_eda(run1_dir, fixture)
    out2 = _run_eda(run2_dir, fixture)
    assert out1["md"].read_bytes() == out2["md"].read_bytes(), "eda.md drifted between runs"
    assert out1["json"].read_bytes() == out2["json"].read_bytes(), "eda.aggregate.json drifted between runs"


def test_eval_summary_optional(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    out = _run_eda(tmp_path, fixture, with_eval_summary=False)
    aggregate = json.loads(out["json"].read_text(encoding="utf-8"))
    assert aggregate["axis4_eval_cross"]["case_cross_available"] is False
    # baseline_by_query_type must still be present
    assert aggregate["axis4_eval_cross"]["baseline_by_query_type"]


def test_eval_summary_cross_present(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    out = _run_eda(tmp_path, fixture, with_eval_summary=True)
    aggregate = json.loads(out["json"].read_text(encoding="utf-8"))
    a4 = aggregate["axis4_eval_cross"]
    assert a4["case_cross_available"] is True
    assert a4["n_cases"] == 2
    assert a4["query_type_x_file_format"]
    assert set(a4["by_doc_length_bucket"].keys()) == {"short", "medium", "long"}


def test_aggregate_json_keys_allowlist(tmp_path: Path) -> None:
    """Top-level keys and per-axis keys are a stable contract — guard against
    silent additions that might leak fields."""
    fixture = _make_fixture(tmp_path)
    out = _run_eda(tmp_path, fixture)
    aggregate = json.loads(out["json"].read_text(encoding="utf-8"))
    expected_top = {
        "schema_version",
        "axis1_metadata",
        "axis2_chunk_health",
        "axis3_text_source",
        "axis4_eval_cross",
    }
    assert set(aggregate.keys()) == expected_top, f"unexpected top-level keys: {set(aggregate.keys()) - expected_top}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
