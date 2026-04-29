#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import load_index, percentile, rate, run_rag_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local RAG evaluation over configured cases.")
    parser.add_argument("--input_dir", default="outputs", help="Kept for CLI compatibility; not required.")
    parser.add_argument("--index_dir", default="data/index", help="Directory containing built index.json.")
    parser.add_argument("--output_dir", default="reports", help="Directory to save eval summary.")
    parser.add_argument("--query", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--config", required=True, help="Path to eval config YAML file.")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Eval config must be a mapping: {path}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Eval config must include non-empty cases list")
    return data


def contains_all_terms(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return all(str(term).lower() in lowered for term in terms)


def score_case(case: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    answerable = bool(case.get("answerable", True))
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or []]
    evidence = prediction.get("evidence") or []
    evidence_doc_ids = {item.get("doc_id") for item in evidence}
    answer = str(prediction.get("answer") or "")
    evidence_text = " ".join(str(item.get("text") or "") for item in evidence)
    combined_text = " ".join([answer, evidence_text])
    abstained = bool((prediction.get("diagnostics") or {}).get("abstained"))

    if answerable:
        doc_match = expected_doc_ids.issubset(evidence_doc_ids)
        term_match = contains_all_terms(combined_text, expected_terms)
        accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
        groundedness = 1.0 if term_match and evidence and not abstained else 0.0
        if evidence:
            citation_precision = len(evidence_doc_ids & expected_doc_ids) / len(evidence_doc_ids)
        else:
            citation_precision = 0.0
        abstention = None
    else:
        accuracy = None
        groundedness = 1.0 if abstained and not evidence else 0.0
        citation_precision = 1.0 if abstained and not evidence else 0.0
        abstention = 1.0 if abstained else 0.0

    return {
        "id": case.get("id"),
        "query": case.get("query"),
        "answerable": answerable,
        "expected_doc_ids": sorted(expected_doc_ids),
        "evidence_doc_ids": sorted(doc_id for doc_id in evidence_doc_ids if doc_id),
        "accuracy": accuracy,
        "groundedness": groundedness,
        "citation_precision": citation_precision,
        "abstention": abstention,
        "latency_ms": (prediction.get("diagnostics") or {}).get("latency_ms"),
        "retry_count": (prediction.get("diagnostics") or {}).get("retry_count", 0),
        "abstained": abstained,
        "answer": answer,
    }


def main() -> int:
    try:
        args = parse_args()
        config_path = Path(args.config)
        if not config_path.exists():
            raise ValueError(f"--config does not exist: {config_path}")
        config = load_config(config_path)
        index = load_index(Path(args.index_dir))
    except Exception as exc:
        print(f"[ERROR] Eval setup failed: {exc}", file=sys.stderr)
        return 2

    case_results = []
    try:
        for case in config["cases"]:
            prediction = run_rag_query(
                index,
                str(case["query"]),
                context_entities=case.get("context_entities") or [],
            )
            case_results.append(score_case(case, prediction))
    except Exception as exc:
        print(f"[ERROR] Eval execution failed: {exc}", file=sys.stderr)
        return 2

    accuracy_scores = [r["accuracy"] for r in case_results if r["accuracy"] is not None]
    groundedness_scores = [r["groundedness"] for r in case_results if r["groundedness"] is not None]
    citation_scores = [r["citation_precision"] for r in case_results if r["citation_precision"] is not None]
    abstention_scores = [r["abstention"] for r in case_results if r["abstention"] is not None]
    latencies = [float(r["latency_ms"]) for r in case_results if r["latency_ms"] is not None]
    retries = [float(r["retry_count"] > 0) for r in case_results]

    summary = {
        "mode": "rag",
        "config": args.config,
        "index_dir": args.index_dir,
        "num_predictions": len(case_results),
        "accuracy": rate(accuracy_scores),
        "groundedness": rate(groundedness_scores),
        "citation_precision": rate(citation_scores),
        "abstention": rate(abstention_scores),
        "latency": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "retry": rate(retries),
        "case_results": case_results,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eval_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Eval summary written: {out_path}")

    if args.query:
        print("[INFO] --query is accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
