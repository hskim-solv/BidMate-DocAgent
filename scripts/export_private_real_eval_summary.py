#!/usr/bin/env python3
"""Export an aggregate-only redacted private real-eval summary."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
FORBIDDEN_REDACTED_KEYS = {
    "question",
    "answer",
    "support_text",
    "document_text",
    "raw_text",
    "file_path",
    "absolute_path",
}
ABSOLUTE_PATH_RE = re.compile(r"(^|[\s'\"])/(Users|home|private|var|tmp|Volumes)/[^\s'\"]+")


def _repo_path(value: str | Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT_DIR / path


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return payload


def _forbidden_hits(obj: Any, *, path: str = "$", include_absolute_values: bool = True) -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key)
            if key_text.lower() in FORBIDDEN_REDACTED_KEYS:
                hits.append(f"{path}.{key_text}")
            hits.extend(
                _forbidden_hits(
                    value,
                    path=f"{path}.{key_text}",
                    include_absolute_values=include_absolute_values,
                )
            )
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(
                _forbidden_hits(
                    item,
                    path=f"{path}[{idx}]",
                    include_absolute_values=include_absolute_values,
                )
            )
    elif isinstance(obj, str):
        if include_absolute_values and ABSOLUTE_PATH_RE.search(obj):
            hits.append(f"{path}:absolute_path_value")
    return hits


def _metric_block(metrics: dict[str, Any], key: str) -> Any:
    value = metrics.get(key)
    if isinstance(value, dict):
        return value
    return None


def _redacted_run_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"redacted_{digest}"


def build_redacted_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    dataset = metrics.get("dataset") if isinstance(metrics.get("dataset"), dict) else {}
    retrieval = metrics.get("retrieval_metrics") if isinstance(metrics.get("retrieval_metrics"), dict) else {}
    answer = metrics.get("answer_metrics") if isinstance(metrics.get("answer_metrics"), dict) else {}
    failure_counts = metrics.get("failure_counts") if isinstance(metrics.get("failure_counts"), dict) else {}
    latency = metrics.get("latency_metrics") if isinstance(metrics.get("latency_metrics"), dict) else {}

    return {
        "schema_version": 1,
        "eval_type": "private_real_eval",
        "benchmark_type": "private_real_eval",
        "baseline_system": "naive_rag",
        "run_id": _redacted_run_id(metrics.get("run_id")),
        "run_id_redacted": bool(str(metrics.get("run_id") or "").strip()),
        "document_count": metrics.get("document_count"),
        "chunk_count": metrics.get("chunk_count"),
        "question_count": dataset.get("num_questions"),
        "answerable_count": dataset.get("answerable_count"),
        "unanswerable_count": dataset.get("unanswerable_count"),
        "aggregate_retrieval_metrics": retrieval,
        "aggregate_citation_metrics": {
            "citation_accuracy": _metric_block(answer, "citation_accuracy"),
        },
        "aggregate_answer_control_metrics": {
            "rule_based_groundedness": _metric_block(answer, "faithfulness"),
            "term_coverage_accuracy": _metric_block(answer, "answer_relevancy"),
            "hallucination_flag": _metric_block(answer, "hallucination_flag"),
            "unanswerable_detection_flag": _metric_block(answer, "unanswerable_detection_flag"),
        },
        "aggregate_latency_metrics": latency,
        "failure_type_counts": failure_counts,
        "known_limitations": [
            "No raw document text, questions, generated answers, support_text, filenames, or absolute local paths are included.",
            "rule_based_groundedness and term_coverage_accuracy are deterministic proxy metrics, not semantic judge metrics.",
            "Private real-eval aggregate summaries require manual privacy review before commit.",
        ],
    }


def export_summary(run_dir: Path, out_path: Path) -> dict[str, Any]:
    if not out_path.name.endswith(".redacted.json"):
        raise ValueError("--out must end with .redacted.json")
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.is_file():
        raise FileNotFoundError("run_dir must contain metrics.json")
    metrics = _load_json(metrics_path)
    source_hits = _forbidden_hits(metrics, include_absolute_values=False)
    if source_hits:
        raise ValueError(
            "source metrics.json contains forbidden raw/private keys; refusing export: "
            + ", ".join(source_hits[:5])
        )
    summary = build_redacted_summary(metrics)
    summary_hits = _forbidden_hits(summary)
    if summary_hits:
        raise ValueError(
            "redacted summary contains forbidden raw/private keys: "
            + ", ".join(summary_hits[:5])
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = export_summary(_repo_path(args.run_dir), _repo_path(args.out))
    except Exception as exc:
        print(f"[ERROR] redacted summary export failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Wrote redacted private real-eval summary "
        f"for run_id={summary.get('run_id') or '<unset>'}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
