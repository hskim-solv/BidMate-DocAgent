#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible local harness.")
    parser.add_argument("--config", required=True, help="Path to harness/*.yaml")
    parser.add_argument("--run_id", default=None, help="Optional stable run id.")
    parser.add_argument("--artifact_root", default=None, help="Override artifact root directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing run directory.")
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def rel_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT_DIR))
    except ValueError:
        return str(resolved)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML must be a mapping: {path}")
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_output(args: list[str], default: str = "unknown") -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT_DIR,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return default
    return result.stdout.strip() or default


def git_dirty() -> bool:
    status = git_output(["status", "--porcelain", "--untracked-files=no"], default="")
    return bool(status.strip())


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


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    config_path = repo_path(args.config)
    config = load_yaml(config_path)
    config_id = str(config.get("id") or config_path.stem)
    run_id = args.run_id or f"{config_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    artifact_root = repo_path(args.artifact_root or config.get("artifact_root") or "artifacts/runs")
    run_dir = artifact_root / run_id

    if run_dir.exists():
        if not args.force:
            raise SystemExit(f"[ERROR] Artifact directory already exists: {rel_path(run_dir)}")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    logs_dir = run_dir / "logs"
    metrics_path = run_dir / "metrics" / "eval_summary.json"
    answer_path = run_dir / "outputs" / "answer.json"
    predictions_path = run_dir / "predictions.jsonl"
    errors_path = run_dir / "errors.jsonl"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    config_snapshot_path = run_dir / "config_snapshot.json"

    eval_config_path = repo_path(require_mapping(config, "eval").get("config") or "harness/smoke_eval.yaml")
    eval_config = load_yaml(eval_config_path)
    config_snapshot = {
        "harness": config,
        "eval": eval_config,
        "source_paths": {
            "harness": rel_path(config_path),
            "eval": rel_path(eval_config_path),
        },
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
    return 0 if status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
