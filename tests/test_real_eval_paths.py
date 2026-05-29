from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.real_eval_paths import (
    DEFAULT_REAL100_V2_INDEX_DIR,
    PREFERRED_MINILM_MODEL,
    missing_required,
    resolve_entries,
)


def _args(**overrides: str | None) -> argparse.Namespace:
    defaults = {
        "root": None,
        "config": None,
        "data_list": None,
        "data_dir": None,
        "kordoc_data_dir": None,
        "cache_dir": None,
        "index_dir": None,
        "report_dir": None,
        "baseline_summary": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _entry(entries: list, name: str):
    return next(e for e in entries if e.name == name)


def test_resolver_precedence_cli_env_config_default_and_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    private = tmp_path / "private"
    (private / "eval").mkdir(parents=True)
    (private / "eval" / "real_config.local.yaml").write_text(
        """
real_eval:
  data_list: config/data_list.csv
""".strip(),
        encoding="utf-8",
    )

    env = {
        "REAL_EVAL_ROOT": str(private),
        "REAL_EVAL_DATA_LIST": "env/data_list.csv",
    }
    entries = resolve_entries(
        _args(data_list="cli/data_list.csv"),
        environ=env,
        repo_root=repo,
    )
    assert _entry(entries, "data_list").path == str(private / "cli/data_list.csv")
    assert _entry(entries, "data_list").source == "cli"

    entries = resolve_entries(_args(), environ=env, repo_root=repo)
    assert _entry(entries, "data_list").path == str(private / "env/data_list.csv")
    assert _entry(entries, "data_list").source == "env:REAL_EVAL_DATA_LIST"

    entries = resolve_entries(
        _args(),
        environ={"REAL_EVAL_ROOT": str(private)},
        repo_root=repo,
    )
    assert _entry(entries, "data_list").path == str(private / "config/data_list.csv")
    assert _entry(entries, "data_list").source == "config:data_list"

    (private / "eval" / "real_config.local.yaml").write_text("real_eval: {}\n", encoding="utf-8")
    entries = resolve_entries(
        _args(),
        environ={"REAL_EVAL_ROOT": str(private)},
        repo_root=repo,
    )
    assert _entry(entries, "data_list").path == str(private / "data" / "data_list.csv")
    assert _entry(entries, "data_list").source == "default"


def test_missing_required_inputs_are_explicit(tmp_path: Path) -> None:
    entries = resolve_entries(_args(), environ={}, repo_root=tmp_path)
    missing = {e.name for e in missing_required(entries)}
    assert {"config", "data_list", "data_dir"}.issubset(missing)
    assert "cache_dir" not in missing
    assert "index_dir" not in missing
    assert "report_dir" not in missing
    assert "eval_summary" not in missing


def test_cache_index_and_report_are_not_required_inputs(tmp_path: Path) -> None:
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "real_config.local.yaml").write_text("cases: []\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data_list.csv").write_text("파일명\n", encoding="utf-8")
    (tmp_path / "data" / "files").mkdir()

    entries = resolve_entries(_args(), environ={}, repo_root=tmp_path)
    assert missing_required(entries) == []
    assert _entry(entries, "cache_dir").status == "regenerable-missing"
    assert _entry(entries, "index_dir").status == "regenerable-missing"
    assert _entry(entries, "report_dir").status == "creatable"
    assert _entry(entries, "eval_summary").status == "creatable"


def test_default_index_dir_is_checkpoint_minilm_pageaware(tmp_path: Path) -> None:
    entries = resolve_entries(_args(), environ={}, repo_root=tmp_path)
    index = _entry(entries, "index_dir")
    report = _entry(entries, "report_dir")
    baseline = _entry(entries, "baseline_summary")

    assert index.path == str(tmp_path / DEFAULT_REAL100_V2_INDEX_DIR)
    assert index.source == "default"
    assert report.path == str(tmp_path / "reports" / "real100_v2")
    assert baseline.path == str(tmp_path / "reports" / "real100_v2" / "baseline.aggregate.json")


def test_output_eval_summary_is_not_required_before_run(tmp_path: Path) -> None:
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "real_config.local.yaml").write_text("cases: []\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "data_list.csv").write_text("파일명\n", encoding="utf-8")
    (tmp_path / "data" / "files").mkdir()

    entries = resolve_entries(_args(report_dir="reports/custom"), environ={}, repo_root=tmp_path)
    summary = _entry(entries, "eval_summary")
    assert summary.path == str(tmp_path / "reports" / "custom" / "eval_summary.json")
    assert summary.required_before_run is False
    assert summary.status == "creatable"


def test_kordoc_data_dir_override_is_separate_from_source_data_dir(tmp_path: Path) -> None:
    env = {
        "REAL_EVAL_DATA_DIR": "data/private-files",
        "REAL_EVAL_KORDOC_DATA_DIR": "cache/kordoc-md",
    }
    entries = resolve_entries(_args(), environ=env, repo_root=tmp_path)
    assert _entry(entries, "data_dir").path == str(tmp_path / "data" / "private-files")
    kordoc = _entry(entries, "kordoc_data_dir")
    assert kordoc.path == str(tmp_path / "cache" / "kordoc-md")
    assert kordoc.required_before_run is False
    assert kordoc.can_regenerate is True


def test_existing_low_chunk_private_index_is_flagged_but_not_required(tmp_path: Path) -> None:
    index_dir = tmp_path / "data" / "index" / "real100_m3"
    index_dir.mkdir(parents=True)
    (index_dir / "index.json").write_text(
        json.dumps({"build": {"num_documents": 100, "num_chunks": 898}}),
        encoding="utf-8",
    )

    entries = resolve_entries(_args(index_dir=str(index_dir)), environ={}, repo_root=tmp_path)
    index = _entry(entries, "index_dir")
    assert index.status == "invalid"
    assert "low-chunk index" in index.message
    assert index.required_before_run is False


def _private_index_payload(*, backend: str, model: str, with_page_metadata: bool) -> dict:
    chunk = {
        "chunk_id": "redacted::chunk-001",
        "doc_id": "redacted",
        "text": "redacted",
    }
    if with_page_metadata:
        chunk["page_span"] = [1, 1]
    return {
        "schema_version": 2,
        "embedding": {"backend": backend, "model": model, "dimension": 384},
        "build": {"num_documents": 100, "num_chunks": 21800},
        "documents": [{"doc_id": "redacted"} for _ in range(100)],
        "chunks": [chunk],
    }


def test_private_real_eval_index_rejects_hashing_even_with_page_metadata(tmp_path: Path) -> None:
    index_dir = tmp_path / "data" / "index" / "real100_v2"
    index_dir.mkdir(parents=True)
    (index_dir / "index.json").write_text(
        json.dumps(
            _private_index_payload(
                backend="hashing",
                model="local-hashing-bow",
                with_page_metadata=True,
            )
        ),
        encoding="utf-8",
    )

    entries = resolve_entries(_args(index_dir=str(index_dir)), environ={}, repo_root=tmp_path)
    index = _entry(entries, "index_dir")
    assert index.status == "invalid"
    assert "hashing embeddings are forbidden" in index.message


def test_private_real_eval_index_rejects_zero_page_metadata_coverage(tmp_path: Path) -> None:
    index_dir = tmp_path / "data" / "index" / "real100_v2"
    index_dir.mkdir(parents=True)
    (index_dir / "index.json").write_text(
        json.dumps(
            _private_index_payload(
                backend="sentence-transformers",
                model=PREFERRED_MINILM_MODEL,
                with_page_metadata=False,
            )
        ),
        encoding="utf-8",
    )

    entries = resolve_entries(_args(index_dir=str(index_dir)), environ={}, repo_root=tmp_path)
    index = _entry(entries, "index_dir")
    assert index.status == "invalid"
    assert "chunk page metadata coverage is 0.0" in index.message


def test_private_real_eval_index_accepts_minilm_page_aware_index(tmp_path: Path) -> None:
    index_dir = tmp_path / "data" / "index" / "real100_v2"
    index_dir.mkdir(parents=True)
    (index_dir / "index.json").write_text(
        json.dumps(
            _private_index_payload(
                backend="sentence-transformers",
                model=PREFERRED_MINILM_MODEL,
                with_page_metadata=True,
            )
        ),
        encoding="utf-8",
    )

    entries = resolve_entries(_args(index_dir=str(index_dir)), environ={}, repo_root=tmp_path)
    index = _entry(entries, "index_dir")
    assert index.status == "ok"
