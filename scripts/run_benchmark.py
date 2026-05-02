#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import DEFAULT_CLI_PIPELINE_NAME, load_index, resolve_pipeline_config


def load_eval_module() -> Any:
    module_path = ROOT_DIR / "eval" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("bidmate_eval_run_eval", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load eval module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVAL = load_eval_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a benchmark suite and write local artifacts.")
    parser.add_argument("--suite", required=True, help="Path to benchmarks/suites/*.yaml")
    parser.add_argument("--ablations", required=True, help="Path to benchmarks/ablations/*.yaml")
    parser.add_argument("--run_id", default=None, help="Optional stable run id.")
    parser.add_argument("--artifact_root", default=None, help="Override artifact root directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing run artifact directory.")
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


def json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def run_logged_command(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
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
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {rel_path(log_path)}")


def normalize_run(run: dict[str, Any]) -> dict[str, Any]:
    name = str(run.get("name") or "").strip()
    if not name:
        raise ValueError("Each ablation run must include a name")
    config = resolve_pipeline_config(run, default_pipeline=DEFAULT_CLI_PIPELINE_NAME)
    return {
        "name": name,
        "pipeline": config["pipeline"],
        "pipeline_alias": config.get("pipeline_alias"),
        "top_k": config.get("top_k"),
        "metadata_first": bool(config.get("metadata_first")),
        "rerank": bool(config.get("rerank")),
        "verifier_retry": bool(config.get("verifier_retry")),
        "retrieval_mode": str(config.get("retrieval_mode", "flat")),
        "prompt_profile": str(config.get("prompt_profile")),
    }


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "case"


def metric_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "num_predictions",
        "accuracy",
        "groundedness",
        "citation_precision",
        "answer_format_compliance",
        "abstention",
        "retry",
        "latency",
        "retry_cost",
        "retry_reason_counts",
        "by_query_type",
    ]
    return {key: summary.get(key) for key in keys if key in summary}


def run_flags(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "pipeline": str(run.get("pipeline") or ""),
        "top_k": run.get("top_k"),
        "metadata_first": bool(run.get("metadata_first", True)),
        "rerank": bool(run.get("rerank", True)),
        "verifier_retry": bool(run.get("verifier_retry", True)),
        "retrieval_mode": str(run.get("retrieval_mode", "flat")),
        "prompt_profile": str(run.get("prompt_profile") or ""),
    }


def case_has_error(score: dict[str, Any]) -> bool:
    for key in (
        "accuracy",
        "groundedness",
        "citation_precision",
        "answer_format_compliance",
        "abstention",
    ):
        value = score.get(key)
        if isinstance(value, (int, float)) and value < 1.0:
            return True
    return str(score.get("answer_status") or "") == "partial"


def evaluate_run_with_artifacts(
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    run_config: dict[str, Any],
    answer_policy: dict[str, Any],
    predictions_file: Any,
    latency_file: Any,
    error_examples_file: Any,
    trace_dir: Path,
) -> list[dict[str, Any]]:
    case_results = []
    run_name = str(run_config["name"])
    run_trace_dir = trace_dir / run_name
    run_trace_dir.mkdir(parents=True, exist_ok=True)

    for case in cases:
        conversation_state: dict[str, Any] = {}
        for turn in case.get("prior_turns") or []:
            prior_prediction = EVAL.run_rag_query(
                index,
                str(turn["query"]),
                pipeline=str(run_config.get("pipeline") or DEFAULT_CLI_PIPELINE_NAME),
                top_k=run_config.get("top_k"),
                context_entities=turn.get("context_entities") or [],
                metadata_first=bool(run_config.get("metadata_first", True)),
                rerank=bool(run_config.get("rerank", True)),
                verifier_retry=bool(run_config.get("verifier_retry", True)),
                retrieval_mode=str(run_config.get("retrieval_mode", "flat")),
                prompt_profile=str(run_config.get("prompt_profile") or ""),
                conversation_state=conversation_state,
            )
            conversation_state = prior_prediction.get("conversation_state") or conversation_state

        prediction = EVAL.run_rag_query(
            index,
            str(case["query"]),
            pipeline=str(run_config.get("pipeline") or DEFAULT_CLI_PIPELINE_NAME),
            top_k=run_config.get("top_k"),
            context_entities=case.get("context_entities") or [],
            metadata_first=bool(run_config.get("metadata_first", True)),
            rerank=bool(run_config.get("rerank", True)),
            verifier_retry=bool(run_config.get("verifier_retry", True)),
            retrieval_mode=str(run_config.get("retrieval_mode", "flat")),
            prompt_profile=str(run_config.get("prompt_profile") or ""),
            conversation_state=conversation_state,
        )
        score = EVAL.score_case(case, prediction, answer_policy)
        case_results.append(score)

        record = {
            "run": run_name,
            "case_id": case.get("id"),
            "query_type": case.get("query_type"),
            "prediction": prediction,
            "score": score,
        }
        predictions_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        if case_has_error(score):
            error_examples_file.write(json.dumps(record, ensure_ascii=False) + "\n")

        diagnostics = prediction.get("diagnostics") or {}
        latency_file.write(
            json.dumps(
                {
                    "run": run_name,
                    "case_id": case.get("id"),
                    "query_type": case.get("query_type"),
                    "pipeline": diagnostics.get("pipeline"),
                    "top_k": (prediction.get("plan") or {}).get("top_k"),
                    "latency_ms": diagnostics.get("latency_ms"),
                    "retry_count": diagnostics.get("retry_count", 0),
                    "retrieval_mode": diagnostics.get("retrieval_mode"),
                    "prompt_profile": diagnostics.get("prompt_profile"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )

        trace = {
            "run": run_name,
            "case_id": case.get("id"),
            "plan": prediction.get("plan"),
            "diagnostics": diagnostics,
            "evidence_refs": [
                {
                    "doc_id": item.get("doc_id"),
                    "chunk_id": item.get("chunk_id"),
                    "section": item.get("section"),
                    "score": item.get("score"),
                }
                for item in prediction.get("evidence") or []
            ],
        }
        write_json(run_trace_dir / f"{safe_name(str(case.get('id') or 'case'))}.json", trace)

    return case_results


def build_summary(
    run_summaries: list[dict[str, Any]],
    primary_run: str,
    config_path: str,
    index_dir: str,
) -> dict[str, Any]:
    primary_summary = next((run for run in run_summaries if run["name"] == primary_run), None)
    if primary_summary is None:
        primary_summary = run_summaries[0]

    return {
        "mode": "rag",
        "config": config_path,
        "index_dir": index_dir,
        "primary_run": primary_summary["name"],
        "pipeline": primary_summary.get("pipeline"),
        "prompt_profile": primary_summary.get("prompt_profile"),
        "top_k": primary_summary.get("top_k"),
        "num_predictions": primary_summary["num_predictions"],
        "accuracy": primary_summary["accuracy"],
        "groundedness": primary_summary["groundedness"],
        "citation_precision": primary_summary["citation_precision"],
        "abstention": primary_summary["abstention"],
        "answer_format_compliance": primary_summary["answer_format_compliance"],
        "latency": primary_summary["latency"],
        "retry": primary_summary["retry"],
        "by_query_type": primary_summary["by_query_type"],
        "retry_cost": primary_summary["retry_cost"],
        "retry_reason_counts": primary_summary["retry_reason_counts"],
        "ablation": {"runs": run_summaries},
        "case_results": primary_summary.get("case_results", []),
    }


def main() -> int:
    args = parse_args()
    suite_path = repo_path(args.suite)
    ablations_path = repo_path(args.ablations)
    suite = load_yaml(suite_path)
    ablations = load_yaml(ablations_path)
    suite_id = str(suite.get("id") or suite_path.stem)
    run_id = args.run_id or f"{suite_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    artifact_root = repo_path(
        args.artifact_root or suite.get("artifacts", {}).get("root") or "artifacts/benchmarks"
    )
    run_dir = artifact_root / run_id
    if run_dir.exists():
        if not args.force:
            raise SystemExit(f"[ERROR] Artifact directory already exists: {rel_path(run_dir)}")
        shutil.rmtree(run_dir)

    run_dir.mkdir(parents=True, exist_ok=True)

    traces_dir = run_dir / "traces"
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = run_dir / "predictions.jsonl"
    latency_path = run_dir / "latency_samples.jsonl"
    error_examples_path = run_dir / "error_examples.jsonl"
    eval_summary_path = run_dir / "eval_summary.json"
    manifest_path = run_dir / "run_manifest.json"

    command = suite.get("index", {}).get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise SystemExit("[ERROR] suite.index.command must be a list of command tokens")
    run_logged_command(command, logs_dir / "index.log")

    eval_config_path = repo_path(suite.get("eval", {}).get("config") or "eval/config.yaml")
    eval_config = EVAL.load_config(eval_config_path)
    normalized_runs = [normalize_run(run) for run in ablations.get("runs") or []]
    if not normalized_runs:
        raise SystemExit("[ERROR] Ablation file must include non-empty runs")
    eval_config["ablation_runs"] = normalized_runs

    index_dir = repo_path(suite.get("index", {}).get("output_dir") or suite.get("eval", {}).get("index_dir") or "data/index")
    index = load_index(index_dir)
    answer_policy = eval_config.get("answer_policy") if isinstance(eval_config.get("answer_policy"), dict) else {}
    primary_run = str(ablations.get("primary_run") or "full")
    baseline_run = str(ablations.get("baseline_run") or normalized_runs[-1]["name"])

    run_summaries = []
    with predictions_path.open("w", encoding="utf-8") as predictions_file, latency_path.open(
        "w", encoding="utf-8"
    ) as latency_file, error_examples_path.open("w", encoding="utf-8") as error_examples_file:
        for run_config in normalized_runs:
            case_results = evaluate_run_with_artifacts(
                index,
                eval_config["cases"],
                run_config,
                answer_policy,
                predictions_file,
                latency_file,
                error_examples_file,
                traces_dir,
            )
            run_summary = EVAL.summarize_run(
                run_config["name"],
                run_config,
                case_results,
                include_cases=run_config["name"] == primary_run,
            )
            run_summaries.append(run_summary)

    summary = build_summary(run_summaries, primary_run, rel_path(eval_config_path), rel_path(index_dir))
    write_json(eval_summary_path, summary)

    runs_by_name = {run["name"]: metric_snapshot(run) for run in run_summaries}
    artifact_paths = {
        "run_dir": rel_path(run_dir),
        "run_manifest": rel_path(manifest_path),
        "eval_summary": rel_path(eval_summary_path),
        "predictions": rel_path(predictions_path),
        "latency_samples": rel_path(latency_path),
        "error_examples": rel_path(error_examples_path),
        "traces": rel_path(traces_dir),
        "logs": rel_path(logs_dir),
    }
    config_snapshot = {
        "suite": suite,
        "ablations": ablations,
        "eval": eval_config,
    }
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git_commit": git_output(["rev-parse", "HEAD"]),
        "git_dirty": git_dirty(),
        "config_hash": json_hash(config_snapshot),
        "config_snapshot": config_snapshot,
        "suite": {
            "id": suite_id,
            "path": rel_path(suite_path),
            "dataset": suite.get("dataset") or {},
            "eval_config": rel_path(eval_config_path),
            "index_dir": rel_path(index_dir),
        },
        "ablation_suite": {
            "id": str(ablations.get("id") or ablations_path.stem),
            "path": rel_path(ablations_path),
            "baseline_run": baseline_run,
            "primary_run": primary_run,
        },
        "ablation_flags": {run["name"]: run_flags(run) for run in normalized_runs},
        "model_config": index.get("embedding", {}),
        "retriever_config": {
            "index_dir": rel_path(index_dir),
            "retrieval_modes": sorted({run["retrieval_mode"] for run in normalized_runs}),
            "pipeline_by_run": {
                run["name"]: str(run.get("pipeline") or "") for run in normalized_runs
            },
            "top_k_by_run": {run["name"]: run.get("top_k") for run in normalized_runs},
            "metadata_first_runs": {
                run["name"]: bool(run.get("metadata_first", True)) for run in normalized_runs
            },
            "prompt_profile_by_run": {
                run["name"]: str(run.get("prompt_profile") or "") for run in normalized_runs
            },
        },
        "reranker_config": {
            "enabled_by_run": {run["name"]: bool(run.get("rerank", True)) for run in normalized_runs}
        },
        "verifier_config": {
            "retry_enabled_by_run": {
                run["name"]: bool(run.get("verifier_retry", True)) for run in normalized_runs
            }
        },
        "metrics": {
            "baseline_run": baseline_run,
            "primary_run": primary_run,
            "baseline": runs_by_name.get(baseline_run),
            "primary": runs_by_name.get(primary_run),
            "runs": runs_by_name,
        },
        "latency": {
            "baseline": (runs_by_name.get(baseline_run) or {}).get("latency"),
            "primary": (runs_by_name.get(primary_run) or {}).get("latency"),
            "runs": {name: metrics.get("latency") for name, metrics in runs_by_name.items()},
        },
        "artifacts": artifact_paths,
    }
    write_json(manifest_path, manifest)

    print(f"[OK] Benchmark artifacts written: {rel_path(run_dir)}")
    print(f"[OK] Run manifest: {rel_path(manifest_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
