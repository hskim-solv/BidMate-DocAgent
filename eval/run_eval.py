#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import load_index, percentile, rate, run_rag_query


QUERY_TYPES = ("single_doc", "multi_doc", "follow_up", "abstention")
DEFAULT_ABLATION_RUNS = [
    {
        "name": "full",
        "metadata_first": True,
        "rerank": True,
        "verifier_retry": True,
    }
]


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
    for case in cases:
        query_type = case.get("query_type")
        if query_type not in QUERY_TYPES:
            raise ValueError(f"Eval case must include query_type in {QUERY_TYPES}: {case.get('id')}")
        prior_turns = case.get("prior_turns") or []
        if not isinstance(prior_turns, list):
            raise ValueError(f"Eval case prior_turns must be a list: {case.get('id')}")
        for turn in prior_turns:
            if not isinstance(turn, dict) or not str(turn.get("query") or "").strip():
                raise ValueError(f"Each prior turn must include a query: {case.get('id')}")

    runs = data.get("ablation_runs", DEFAULT_ABLATION_RUNS)
    if not isinstance(runs, list) or not runs:
        raise ValueError("Eval config ablation_runs must be a non-empty list when provided")
    seen_names: set[str] = set()
    for run in runs:
        if not isinstance(run, dict) or not run.get("name"):
            raise ValueError("Each ablation run must be a mapping with a name")
        if run["name"] in seen_names:
            raise ValueError(f"Duplicate ablation run name: {run['name']}")
        seen_names.add(run["name"])
    return data


def contains_all_terms(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return all(str(term).lower() in lowered for term in terms)


def retry_trigger_reasons(prediction: dict[str, Any]) -> list[str]:
    diagnostics = prediction.get("diagnostics") or {}
    reasons: list[str] = []
    for attempt in diagnostics.get("filter_stage_attempts") or []:
        if attempt.get("verified"):
            continue
        reasons.extend(str(reason) for reason in attempt.get("verification_reasons") or [])
    return reasons


def score_case(case: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    answerable = bool(case.get("answerable", True))
    query_type = str(case.get("query_type"))
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or []]
    expected_citation_terms = [
        str(term) for term in case.get("expected_citation_terms") or expected_terms
    ]
    evidence = prediction.get("evidence") or []
    evidence_doc_ids = {item.get("doc_id") for item in evidence}
    answer = str(prediction.get("answer") or "")
    evidence_text = " ".join(str(item.get("text") or "") for item in evidence)
    combined_text = " ".join([answer, evidence_text])
    diagnostics = prediction.get("diagnostics") or {}
    abstained = bool(diagnostics.get("abstained"))
    context_resolution = diagnostics.get("context_resolution") or {}

    citation_doc_precision = 0.0
    if evidence_doc_ids:
        citation_doc_precision = len(evidence_doc_ids & expected_doc_ids) / len(evidence_doc_ids)
    citation_term_match = (
        contains_all_terms(evidence_text, expected_citation_terms)
        if expected_citation_terms
        else bool(evidence)
    )

    if answerable:
        doc_match = expected_doc_ids.issubset(evidence_doc_ids)
        term_match = contains_all_terms(combined_text, expected_terms)
        accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
        groundedness = 1.0 if term_match and evidence and not abstained else 0.0
        citation_precision = citation_doc_precision if citation_term_match else 0.0
        abstention = None
    else:
        doc_match = not evidence
        term_match = abstained
        accuracy = None
        groundedness = 1.0 if abstained and not evidence else 0.0
        citation_precision = 1.0 if abstained and not evidence else 0.0
        abstention = 1.0 if abstained else 0.0

    return {
        "id": case.get("id"),
        "query_type": query_type,
        "query": case.get("query"),
        "answerable": answerable,
        "expected_doc_ids": sorted(expected_doc_ids),
        "evidence_doc_ids": sorted(doc_id for doc_id in evidence_doc_ids if doc_id),
        "doc_match": doc_match,
        "term_match": term_match,
        "citation_term_match": citation_term_match,
        "citation_doc_precision": citation_doc_precision,
        "accuracy": accuracy,
        "groundedness": groundedness,
        "citation_precision": citation_precision,
        "abstention": abstention,
        "latency_ms": diagnostics.get("latency_ms"),
        "retry_count": diagnostics.get("retry_count", 0),
        "retry_trigger_reasons": retry_trigger_reasons(prediction),
        "context_resolution_status": context_resolution.get("status"),
        "context_resolution_source": context_resolution.get("source"),
        "context_resolution_confidence": context_resolution.get("confidence"),
        "context_resolution_reason": context_resolution.get("reason"),
        "resolved_query": prediction.get("resolved_query"),
        "abstained": abstained,
        "answer": answer,
    }


def metric_block(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    accuracy_scores = [r["accuracy"] for r in case_results if r["accuracy"] is not None]
    groundedness_scores = [
        r["groundedness"] for r in case_results if r["groundedness"] is not None
    ]
    citation_scores = [
        r["citation_precision"] for r in case_results if r["citation_precision"] is not None
    ]
    abstention_scores = [r["abstention"] for r in case_results if r["abstention"] is not None]
    latencies = [float(r["latency_ms"]) for r in case_results if r["latency_ms"] is not None]
    retry_counts = [int(r.get("retry_count") or 0) for r in case_results]
    retries = [float(count > 0) for count in retry_counts]
    retry_reason_counts = Counter(
        reason for result in case_results for reason in result.get("retry_trigger_reasons") or []
    )

    return {
        "num_predictions": len(case_results),
        "accuracy": rate(accuracy_scores),
        "groundedness": rate(groundedness_scores),
        "citation_precision": rate(citation_scores),
        "abstention": rate(abstention_scores),
        "latency": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "mean": rate(latencies),
        },
        "retry": rate(retries),
        "retry_cost": {
            "total_retries": sum(retry_counts),
            "mean_retry_count": rate([float(count) for count in retry_counts]),
            "max_retry_count": max(retry_counts) if retry_counts else 0,
            "cases_with_retry": sum(1 for count in retry_counts if count > 0),
        },
        "retry_reason_counts": dict(sorted(retry_reason_counts.items())),
    }


def summarize_run(
    name: str,
    run_config: dict[str, Any],
    case_results: list[dict[str, Any]],
    include_cases: bool = False,
) -> dict[str, Any]:
    summary = {
        "name": name,
        "metadata_first": bool(run_config.get("metadata_first", True)),
        "rerank": bool(run_config.get("rerank", True)),
        "verifier_retry": bool(run_config.get("verifier_retry", True)),
        **metric_block(case_results),
        "by_query_type": {},
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        grouped[str(result["query_type"])].append(result)
    for query_type in QUERY_TYPES:
        if query_type in grouped:
            summary["by_query_type"][query_type] = metric_block(grouped[query_type])
    if include_cases:
        summary["case_results"] = case_results
    return summary


def evaluate_run(
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    run_config: dict[str, Any],
) -> list[dict[str, Any]]:
    case_results = []
    for case in cases:
        conversation_state: dict[str, Any] = {}
        for turn in case.get("prior_turns") or []:
            prior_prediction = run_rag_query(
                index,
                str(turn["query"]),
                context_entities=turn.get("context_entities") or [],
                metadata_first=bool(run_config.get("metadata_first", True)),
                rerank=bool(run_config.get("rerank", True)),
                verifier_retry=bool(run_config.get("verifier_retry", True)),
                conversation_state=conversation_state,
            )
            conversation_state = prior_prediction.get("conversation_state") or conversation_state

        prediction = run_rag_query(
            index,
            str(case["query"]),
            context_entities=case.get("context_entities") or [],
            metadata_first=bool(run_config.get("metadata_first", True)),
            rerank=bool(run_config.get("rerank", True)),
            verifier_retry=bool(run_config.get("verifier_retry", True)),
            conversation_state=conversation_state,
        )
        case_results.append(score_case(case, prediction))
    return case_results


def ablation_runs(config: dict[str, Any]) -> list[dict[str, Any]]:
    runs = config.get("ablation_runs") or DEFAULT_ABLATION_RUNS
    normalized = []
    for run in runs:
        normalized.append(
            {
                "name": str(run["name"]),
                "metadata_first": bool(run.get("metadata_first", True)),
                "rerank": bool(run.get("rerank", True)),
                "verifier_retry": bool(run.get("verifier_retry", True)),
            }
        )
    return normalized


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

    run_summaries = []
    full_summary = None
    try:
        for run_config in ablation_runs(config):
            case_results = evaluate_run(index, config["cases"], run_config)
            is_full = run_config["name"] == "full"
            run_summary = summarize_run(
                run_config["name"],
                run_config,
                case_results,
                include_cases=is_full,
            )
            run_summaries.append(run_summary)
            if is_full:
                full_summary = run_summary
    except Exception as exc:
        print(f"[ERROR] Eval execution failed: {exc}", file=sys.stderr)
        return 2

    if full_summary is None:
        full_summary = run_summaries[0]

    summary = {
        "mode": "rag",
        "config": args.config,
        "index_dir": args.index_dir,
        "num_predictions": full_summary["num_predictions"],
        "accuracy": full_summary["accuracy"],
        "groundedness": full_summary["groundedness"],
        "citation_precision": full_summary["citation_precision"],
        "abstention": full_summary["abstention"],
        "latency": full_summary["latency"],
        "retry": full_summary["retry"],
        "by_query_type": full_summary["by_query_type"],
        "retry_cost": full_summary["retry_cost"],
        "retry_reason_counts": full_summary["retry_reason_counts"],
        "ablation": {"runs": run_summaries},
        "case_results": full_summary.get("case_results", []),
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
