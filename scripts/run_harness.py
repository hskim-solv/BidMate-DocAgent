#!/usr/bin/env python3
"""Reproducible local harness.

Three modes:

  python3 scripts/run_harness.py --config harness/smoke.yaml
    Single-run: index → query → eval. Writes artifacts/runs/<run_id>/.

  python3 scripts/run_harness.py --matrix harness/ablation.yaml
    Matrix: deep-merge base + each cell override, run each cell, aggregate to
    artifacts/matrices/<matrix_id>/matrix_summary.json + optional compare.md.

  python3 scripts/run_harness.py --compare --run-a <dir> --run-b <dir>
    Compare two run dirs (or eval_summary.json files) — markdown delta table.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _utils import (  # noqa: E402
    append_jsonl,
    git_dirty,
    git_output,
    json_hash,
    load_yaml,
    rel_path,
    repo_path,
    utc_now,
    write_json,
)
from harness_compare import render_matrix_compare, render_pair, resolve_summary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible local harness.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--config", help="Path to harness/*.yaml (single-run mode)")
    mode.add_argument("--matrix", help="Path to matrix YAML (matrix mode)")
    mode.add_argument("--compare", action="store_true", help="Compare two runs")
    parser.add_argument("--run_id", default=None, help="Optional stable run id (single-run only).")
    parser.add_argument("--artifact_root", default=None, help="Override artifact root directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing run directory.")
    parser.add_argument("--run-a", default=None, help="Run dir or eval_summary.json (compare mode)")
    parser.add_argument("--run-b", default=None, help="Run dir or eval_summary.json (compare mode)")
    parser.add_argument("--out", default=None, help="Write compare markdown to this file")
    return parser.parse_args()


def run_logged_command(command: list[str], log_path: Path) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started_at = utc_now()
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write("$ " + " ".join(command) + "\n\n")
        log_file.flush()
        result = subprocess.run(
            command,
            cwd=ROOT_DIR,
            env=env,
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    ended_at = utc_now()
    return {
        "command": command,
        "log": rel_path(log_path),
        "started_at": started_at,
        "ended_at": ended_at,
        "returncode": result.returncode,
        "status": "passed" if result.returncode == 0 else "failed",
    }


def require_mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Config must include mapping: {key}")
    return value


def command_failed(step: dict[str, Any]) -> bool:
    return int(step.get("returncode", 1)) != 0


def build_commands(config: dict[str, Any], run_dir: Path) -> dict[str, list[str]]:
    dataset = require_mapping(config, "dataset")
    index_config = require_mapping(config, "index")
    query_config = require_mapping(config, "query")
    eval_config = require_mapping(config, "eval")

    input_dir = str(dataset.get("input_dir") or "data/raw")
    index_dir = run_dir / "index"
    output_dir = run_dir / "outputs"
    metrics_dir = run_dir / "metrics"
    eval_config_path = str(eval_config.get("config") or "harness/smoke_eval.yaml")

    index_command = [
        "python3",
        "scripts/build_index.py",
        "--input_dir",
        input_dir,
        "--output_dir",
        rel_path(index_dir),
        "--embedding_backend",
        str(index_config.get("embedding_backend") or "hashing"),
    ]
    chunking_strategy = index_config.get("chunking_strategy")
    if chunking_strategy:
        index_command.extend(["--chunking_strategy", str(chunking_strategy)])

    query_command = [
        "python3",
        "app.py",
        "--input_dir",
        rel_path(index_dir),
        "--output_dir",
        rel_path(output_dir),
        "--query",
        str(query_config.get("text") or ""),
        "--pipeline",
        str(query_config.get("pipeline") or "naive_baseline"),
    ]

    eval_command = [
        "python3",
        "eval/run_eval.py",
        "--index_dir",
        rel_path(index_dir),
        "--output_dir",
        rel_path(metrics_dir),
        "--config",
        eval_config_path,
    ]

    return {
        "index": index_command,
        "query": query_command,
        "eval": eval_command,
    }


def metric_snapshot(metrics_path: Path) -> dict[str, Any]:
    if not metrics_path.exists():
        return {}
    summary = json.loads(metrics_path.read_text(encoding="utf-8"))
    keys = [
        "num_predictions",
        "accuracy",
        "groundedness",
        "citation_precision",
        "answer_format_compliance",
        "abstention",
        "retry",
        "latency",
    ]
    return {key: summary.get(key) for key in keys if key in summary}


def write_predictions(answer_path: Path, predictions_path: Path, query: str) -> None:
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    if not answer_path.exists():
        predictions_path.touch()
        return
    answer = json.loads(answer_path.read_text(encoding="utf-8"))
    record = {
        "source": "sample_query",
        "query": query,
        "prediction": answer,
    }
    predictions_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def _execute_pipeline(
    config: dict[str, Any],
    run_id: str,
    run_dir: Path,
    *,
    source_paths: dict[str, str],
    eval_config_path: Path,
) -> dict[str, Any]:
    """Run index → query → eval against a pre-resolved run_dir.

    Writes config_snapshot.json, run_manifest.json, summary.json,
    predictions.jsonl, errors.jsonl, metrics/, logs/, outputs/answer.json.
    Returns the manifest dict.

    The caller owns run_dir creation/wiping so matrix mode can write a
    cell_config.yaml alongside before invoking.
    """
    started_at = utc_now()
    logs_dir = run_dir / "logs"
    metrics_path = run_dir / "metrics" / "eval_summary.json"
    answer_path = run_dir / "outputs" / "answer.json"
    predictions_path = run_dir / "predictions.jsonl"
    errors_path = run_dir / "errors.jsonl"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    config_snapshot_path = run_dir / "config_snapshot.json"

    eval_config = load_yaml(eval_config_path)
    config_snapshot = {
        "harness": config,
        "eval": eval_config,
        "source_paths": source_paths,
    }
    write_json(config_snapshot_path, config_snapshot)
    errors_path.touch()

    commands = build_commands(config, run_dir)
    steps: list[dict[str, Any]] = []
    status = "passed"
    failure: dict[str, Any] | None = None

    for name in ("index", "query", "eval"):
        step = {"name": name, **run_logged_command(commands[name], logs_dir / f"{name}.log")}
        steps.append(step)
        if command_failed(step):
            status = "failed"
            failure = {
                "step": name,
                "returncode": step["returncode"],
                "log": step["log"],
                "command": step["command"],
            }
            append_jsonl(errors_path, failure)
            break

    write_predictions(
        answer_path,
        predictions_path,
        str(require_mapping(config, "query").get("text") or ""),
    )
    metrics = metric_snapshot(metrics_path)
    ended_at = utc_now()
    artifact_paths = {
        "run_dir": rel_path(run_dir),
        "run_manifest": rel_path(manifest_path),
        "config_snapshot": rel_path(config_snapshot_path),
        "summary": rel_path(summary_path),
        "predictions": rel_path(predictions_path),
        "metrics": rel_path(metrics_path),
        "errors": rel_path(errors_path),
        "logs": rel_path(logs_dir),
        "index": rel_path(run_dir / "index" / "index.json"),
        "answer": rel_path(answer_path),
    }

    summary = {
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "steps": steps,
        "artifact_dir": rel_path(run_dir),
        "metrics_path": rel_path(metrics_path),
        "errors_path": rel_path(errors_path),
    }
    write_json(summary_path, summary)

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": ended_at,
        "git_commit": git_output(["rev-parse", "HEAD"]),
        "git_dirty": git_dirty(),
        "config_hash": json_hash(config_snapshot),
        "config_snapshot_path": rel_path(config_snapshot_path),
        "artifacts": artifact_paths,
        "commands": commands,
        "status": status,
        "metrics": metrics,
    }
    if failure:
        manifest["failure"] = failure
    write_json(manifest_path, manifest)

    print(f"[OK] Harness run written: {rel_path(run_dir)}")
    print(f"[OK] Run manifest: {rel_path(manifest_path)}")
    return manifest


def execute_single(
    config_path: Path,
    *,
    run_id: str | None,
    artifact_root: Path | None,
    force: bool,
) -> int:
    config = load_yaml(config_path)
    config_id = str(config.get("id") or config_path.stem)
    effective_run_id = run_id or f"{config_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    effective_root = artifact_root or repo_path(config.get("artifact_root") or "artifacts/runs")
    run_dir = effective_root / effective_run_id

    if run_dir.exists():
        if not force:
            raise SystemExit(f"[ERROR] Artifact directory already exists: {rel_path(run_dir)}")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    eval_config_path = repo_path(require_mapping(config, "eval").get("config") or "harness/smoke_eval.yaml")
    source_paths = {
        "harness": rel_path(config_path),
        "eval": rel_path(eval_config_path),
    }
    manifest = _execute_pipeline(
        config,
        effective_run_id,
        run_dir,
        source_paths=source_paths,
        eval_config_path=eval_config_path,
    )
    return 0 if manifest["status"] == "passed" else 2


# ---------------------------------------------------------------------------
# Matrix mode
# ---------------------------------------------------------------------------

_MERGE_KEYS = ("dataset", "index", "query", "eval")
_FORBIDDEN_OVERRIDE_KEYS = ("id", "description", "artifact_root", "matrix", "compare", "base")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Nested-merge override into a deep copy of base, restricted to _MERGE_KEYS.

    Leaf values (scalars / lists) in override replace base wholesale — no list
    concatenation, no auto-flattening. Keeps config_hash deterministic.
    """
    for forbidden in _FORBIDDEN_OVERRIDE_KEYS:
        if forbidden in override:
            raise ValueError(
                f"override may not set top-level key '{forbidden}' "
                f"(reserved for matrix metadata)"
            )
    merged = copy.deepcopy(base)
    for section in _MERGE_KEYS:
        if section not in override:
            continue
        section_override = override[section]
        if not isinstance(section_override, dict):
            merged[section] = section_override
            continue
        base_section = merged.get(section)
        if not isinstance(base_section, dict):
            merged[section] = copy.deepcopy(section_override)
            continue
        for key, value in section_override.items():
            base_section[key] = copy.deepcopy(value)
    return merged


def _validate_matrix(matrix: dict[str, Any]) -> None:
    for required in ("id", "base", "matrix"):
        if required not in matrix:
            raise SystemExit(f"[ERROR] Matrix YAML missing required key: {required}")
    if not isinstance(matrix["base"], dict):
        raise SystemExit("[ERROR] Matrix 'base' must be a mapping")
    cells = matrix["matrix"]
    if not isinstance(cells, list) or len(cells) == 0:
        raise SystemExit("[ERROR] Matrix must declare ≥1 cell under 'matrix:'")
    seen_names: set[str] = set()
    for idx, cell in enumerate(cells):
        if not isinstance(cell, dict) or "name" not in cell:
            raise SystemExit(f"[ERROR] Matrix cell[{idx}] must be a mapping with 'name'")
        name = cell["name"]
        if name in seen_names:
            raise SystemExit(f"[ERROR] Duplicate cell name: {name}")
        seen_names.add(name)

    # ADR 0001 — naive_baseline must remain runnable in every matrix.
    base_pipeline = (matrix["base"].get("query") or {}).get("pipeline")
    has_naive = False
    for cell in cells:
        override = cell.get("override") or {}
        cell_pipeline = (override.get("query") or {}).get("pipeline", base_pipeline)
        if cell["name"] == "naive_baseline" and cell_pipeline == "naive_baseline":
            has_naive = True
            break
    if not has_naive:
        raise SystemExit(
            "[ERROR] Matrix must include a cell named 'naive_baseline' running the "
            "naive_baseline pipeline (ADR 0001 — preserve naive baseline). "
            "Add an empty-override cell or set query.pipeline=naive_baseline."
        )

    compare = matrix.get("compare")
    if compare is not None:
        if not isinstance(compare, dict) or "base" not in compare:
            raise SystemExit("[ERROR] Matrix 'compare' must have a 'base' key")
        if compare["base"] not in seen_names:
            raise SystemExit(
                f"[ERROR] compare.base '{compare['base']}' not in cell names: "
                f"{sorted(seen_names)}"
            )

    on_failure = matrix.get("on_cell_failure", "continue")
    if on_failure not in ("continue", "abort"):
        raise SystemExit(
            f"[ERROR] on_cell_failure must be 'continue' or 'abort', got: {on_failure}"
        )


def execute_matrix(matrix_path: Path, *, force: bool) -> int:
    matrix = load_yaml(matrix_path)
    _validate_matrix(matrix)

    matrix_id = str(matrix["id"])
    artifact_root = repo_path(matrix.get("artifact_root") or "artifacts/matrices")
    matrix_dir = artifact_root / matrix_id

    if matrix_dir.exists():
        if not force:
            raise SystemExit(f"[ERROR] Matrix directory already exists: {rel_path(matrix_dir)}")
        shutil.rmtree(matrix_dir)
    matrix_dir.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    matrix_errors_path = matrix_dir / "errors.jsonl"
    matrix_errors_path.touch()
    on_failure = matrix.get("on_cell_failure", "continue")
    base = matrix["base"]

    cell_results: list[dict[str, Any]] = []
    cells_passed = 0
    cells_failed = 0

    for cell in matrix["matrix"]:
        cell_name = cell["name"]
        override = cell.get("override") or {}
        try:
            merged = _deep_merge(base, override)
        except ValueError as exc:
            raise SystemExit(f"[ERROR] cell '{cell_name}': {exc}") from exc
        merged["id"] = f"{matrix_id}__{cell_name}"
        merged.setdefault(
            "description",
            f"Matrix cell {cell_name} of {matrix_id}",
        )

        cell_run_dir = matrix_dir / "cells" / cell_name
        cell_run_dir.mkdir(parents=True, exist_ok=True)
        cell_config_path = cell_run_dir / "cell_config.yaml"
        cell_config_path.write_text(
            yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        try:
            eval_config_path = repo_path(
                require_mapping(merged, "eval").get("config") or "harness/smoke_eval.yaml"
            )
        except ValueError as exc:
            raise SystemExit(f"[ERROR] cell '{cell_name}': {exc}") from exc

        source_paths = {
            "harness": rel_path(cell_config_path),
            "eval": rel_path(eval_config_path),
        }
        print(f"[matrix] running cell {cell_name} → {rel_path(cell_run_dir)}")
        manifest = _execute_pipeline(
            merged,
            f"{matrix_id}__{cell_name}",
            cell_run_dir,
            source_paths=source_paths,
            eval_config_path=eval_config_path,
        )

        cell_summary_path = cell_run_dir / "metrics" / "eval_summary.json"
        eval_summary = (
            json.loads(cell_summary_path.read_text(encoding="utf-8"))
            if cell_summary_path.exists()
            else {}
        )
        cell_result = {
            "name": cell_name,
            "run_id": manifest["run_id"],
            "status": manifest["status"],
            "config_hash": manifest["config_hash"],
            "run_manifest_path": manifest["artifacts"]["run_manifest"],
            "metrics_snapshot": manifest["metrics"],
            "failure": manifest.get("failure"),
            "eval_summary": eval_summary,
        }
        cell_results.append(cell_result)

        if manifest["status"] == "passed":
            cells_passed += 1
        else:
            cells_failed += 1
            append_jsonl(
                matrix_errors_path,
                {"cell": cell_name, **(manifest.get("failure") or {})},
            )
            if on_failure == "abort":
                print(f"[matrix] cell {cell_name} failed; on_cell_failure=abort → stopping")
                break

    compare_md_path: str | None = None
    compare_cfg = matrix.get("compare")
    if compare_cfg and cell_results:
        try:
            markdown = render_matrix_compare(
                cell_results,
                compare_cfg["base"],
                matrix_id=matrix_id,
            )
        except ValueError as exc:
            raise SystemExit(f"[ERROR] compare render: {exc}") from exc
        compare_path = matrix_dir / "compare.md"
        compare_path.write_text(markdown, encoding="utf-8")
        compare_md_path = rel_path(compare_path)

    ended_at = utc_now()
    overall_status = "passed" if cells_failed == 0 else "failed"

    matrix_summary = {
        "schema_version": 1,
        "matrix_id": matrix_id,
        "matrix_config_hash": json_hash(matrix),
        "generated_at": ended_at,
        "started_at": started_at,
        "git_commit": git_output(["rev-parse", "HEAD"]),
        "git_dirty": git_dirty(),
        "matrix_config_path": rel_path(matrix_path),
        "matrix_dir": rel_path(matrix_dir),
        "on_cell_failure": on_failure,
        "cells": [
            {k: v for k, v in c.items() if k != "eval_summary"} for c in cell_results
        ],
        "compare": (
            {"base_cell": compare_cfg["base"], "compare_md_path": compare_md_path}
            if compare_cfg
            else None
        ),
        "status": overall_status,
        "cells_passed": cells_passed,
        "cells_failed": cells_failed,
    }
    write_json(matrix_dir / "matrix_summary.json", matrix_summary)
    print(f"[OK] Matrix summary: {rel_path(matrix_dir / 'matrix_summary.json')}")
    if compare_md_path:
        print(f"[OK] Compare table: {compare_md_path}")
    return 0 if overall_status == "passed" else 2


# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------


def execute_compare(run_a: str, run_b: str, out: str | None) -> int:
    a_path = resolve_summary(Path(run_a))
    b_path = resolve_summary(Path(run_b))
    a = json.loads(a_path.read_text(encoding="utf-8"))
    b = json.loads(b_path.read_text(encoding="utf-8"))
    markdown = render_pair(a, b, title="Harness compare")
    print(markdown, end="")
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    if args.compare:
        if not args.run_a or not args.run_b:
            raise SystemExit("[ERROR] --compare requires --run-a and --run-b")
        return execute_compare(args.run_a, args.run_b, args.out)
    if args.matrix:
        return execute_matrix(repo_path(args.matrix), force=args.force)
    return execute_single(
        repo_path(args.config),
        run_id=args.run_id,
        artifact_root=repo_path(args.artifact_root) if args.artifact_root else None,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
