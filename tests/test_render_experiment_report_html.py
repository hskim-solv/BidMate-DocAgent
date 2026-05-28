"""Tests for scripts/render_experiment_report_html.py (issue #1661).

Covers:
  1. Normal aggregate.json → HTML with HTML-escape of hostile values.
  2. raw_results.json filename → denied.
  3. data_list*.csv filename → denied.
  4. stale_pairs() detects missing OR older paired HTML.
  5. --auto-scan walks reports/ and renders every stale candidate.
  6. top-level forbidden key (chunk_text) → denied even outside private globs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import render_experiment_report_html as r  # noqa: E402


@pytest.fixture
def reports_root(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    root.mkdir()
    return root


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_renders_aggregate_and_escapes_html(reports_root: Path) -> None:
    src = _write_json(
        reports_root / "real100_v2" / "metric_suite.aggregate.json",
        {
            "ablation_full": {
                "accuracy": 0.42,
                "ci": {
                    "accuracy": {"mean": 0.42, "ci_lo": 0.35, "ci_hi": 0.49, "n": 100},
                },
            },
            "evil_key_<script>alert(1)</script>": "value_<img src=x>",
        },
    )
    rc = r.main(["--input", str(src), "--quiet"])
    assert rc == r.EXIT_OK
    dst = src.with_name("metric_suite.aggregate.html")
    assert dst.exists()
    html = dst.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x&gt;" in html


def test_raw_results_filename_is_denied(reports_root: Path) -> None:
    src = _write_json(
        reports_root / "retrieval" / "phase4_x" / "raw_results.json",
        {"ablation_full": {"accuracy": 0.5}},
    )
    rc = r.main(["--input", str(src), "--quiet"])
    assert rc == r.EXIT_DENIED
    assert not src.with_suffix(".html").exists()


def test_data_list_prefix_is_denied(tmp_path: Path) -> None:
    src = tmp_path / "data_list.csv"
    src.write_text("qid,gold_agency\n", encoding="utf-8")
    rc = r.main(["--input", str(src), "--quiet"])
    assert rc == r.EXIT_DENIED


def test_stale_pairs_detects_missing_and_older(reports_root: Path) -> None:
    a = _write_json(reports_root / "a.aggregate.json", {"x": 1})
    b = _write_json(reports_root / "b.aggregate.json", {"x": 2})
    # Render a → HTML, leave b unrendered.
    rc = r.main(["--input", str(a), "--quiet"])
    assert rc == r.EXIT_OK
    stale = r.stale_pairs(reports_root)
    assert b in stale
    assert a not in stale
    # Touch a so its mtime jumps past the rendered HTML.
    time.sleep(0.01)
    os.utime(a, None)
    stale = r.stale_pairs(reports_root)
    assert a in stale and b in stale


def test_auto_scan_renders_every_stale(reports_root: Path) -> None:
    _write_json(reports_root / "x" / "one.aggregate.json", {"m": 0.1})
    _write_json(reports_root / "y" / "two.aggregate.json", {"m": 0.2})
    (reports_root / "retrieval" / "phase2_x").mkdir(parents=True)
    (reports_root / "retrieval" / "phase2_x" / "REPORT.md").write_text(
        "# Phase 2 chunking\n\nbody\n", encoding="utf-8"
    )
    rc = r.main(["--auto-scan", "--quiet", "--reports-root", str(reports_root)])
    assert rc == r.EXIT_OK
    assert (reports_root / "x" / "one.aggregate.html").exists()
    assert (reports_root / "y" / "two.aggregate.html").exists()
    assert (reports_root / "retrieval" / "phase2_x" / "REPORT.html").exists()
    # Idempotent: second pass renders nothing new.
    assert r.stale_pairs(reports_root) == []


def test_top_level_chunk_text_key_is_denied(reports_root: Path) -> None:
    src = _write_json(
        reports_root / "rogue.aggregate.json",
        {"chunk_text": "supposed raw RFP content"},
    )
    rc = r.main(["--input", str(src), "--quiet"])
    assert rc == r.EXIT_DENIED
    assert not src.with_suffix(".html").exists()
