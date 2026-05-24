#!/usr/bin/env python3
"""Run and package the current naive RAG baseline evaluation.

This is an eval wrapper only. It filters an existing eval config down to the
ADR 0001 naive_baseline row, delegates execution to eval/run_eval.py, then
exports the requested experiment artifacts without changing retrieval,
chunking, prompting, verifier, or answer behavior.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
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
DEFAULT_REPORT_PATH = ROOT_DIR / "docs" / "evaluation" / "naive_rag_baseline_report.md"

RETRIEVAL_LABELS = {
    "Recall@5": "chunk_recall_at_5",
    "Recall@10": "chunk_recall_at_10",
    "MRR@5": "chunk_mrr_at_5",
    "nDCG@5": "chunk_ndcg_at_5",
}
ANSWER_LABELS = {
    "Faithfulness": "groundedness",
    "Answer relevancy": "accuracy",
    "Citation accuracy": "citation_precision",
}
REQUIRED_FAILURE_BUCKETS = {
    "retrieval_failures": (
        "gold evidence not in top-k",
        "gold evidence ranked too low",
        "wrong similar clause",
        "chunk boundary split",
        "query wording mismatch",
        "multi-chunk evidence missing",
    ),
    "parsing_failures": (
        "table content lost",
        "figure content ignored",
        "page metadata missing",
        "header/footer noise",
        "Korean/English mixed text issue",
    ),
    "citation_failures": (
        "correct answer but wrong citation",
        "insufficient citation",
        "missing page number",
        "citation does not support claim",
        "vague citation for multiple claims",
    ),
    "answer_failures": (
        "hallucinated requirement",
        "partial answer",
        "overconfident weak evidence",
        "wrong synthesis",
        "failed to abstain",
    ),
    "evaluation_failures": (
        "missing gold evidence",
        "metric missing",
        "failure case not saved",
        "schema mismatch",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run eval/config.yaml's naive_baseline row and export baseline artifacts."
    )
    parser.add_argument("--config", default="eval/config.yaml", help="Source eval config YAML.")
    parser.add_argument("--index_dir", default="data/index", help="Existing index directory.")
    parser.add_argument(
        "--output_root",
        default="experiments/runs",
        help="Directory under which <run_id>/ artifacts are written.",
    )
    parser.add_argument("--run_id", default=None, help="Optional stable run id.")
    parser.add_argument(
        "--report_path",
        default=str(DEFAULT_REPORT_PATH.relative_to(ROOT_DIR)),
        help="Markdown baseline report to create/update.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing run dir.")
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def rel_path(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT_DIR.resolve()))
    except ValueError:
        return str(p)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def default_run_id() -> str:
    return f"naive_baseline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def select_naive_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied config containing only the naive_baseline row."""
    filtered = deepcopy(config)
    runs = filtered.get("ablation_runs")
    if not isinstance(runs, list) or not runs:
        filtered["ablation_runs"] = [{"name": "naive_baseline", "pipeline": "naive_baseline"}]
    else:
        matches = [
            deepcopy(run)
            for run in runs
            if isinstance(run, dict)
            and str(run.get("name") or "") == "naive_baseline"
            and str(run.get("pipeline") or "naive_baseline") == "naive_baseline"
        ]
        if not matches:
            raise ValueError("Source config has no naive_baseline ablation row")
        filtered["ablation_runs"] = [matches[0]]
    filtered["primary_run"] = "naive_baseline"
    return filtered


def build_eval_command(config_path: Path, index_dir: Path, run_dir: Path) -> list[str]:
    return [
        "python3",
        "eval/run_eval.py",
        "--config",
        rel_path(config_path),
        "--index_dir",
        rel_path(index_dir),
        "--output_dir",
        rel_path(run_dir),
    ]


def run_eval_command(command: list[str], log_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    log_path.parent.mkdir(parents=True, exist_ok=True)
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
        raise RuntimeError(f"naive baseline eval failed; see {rel_path(log_path)}")


def dataset_counts(config: dict[str, Any]) -> dict[str, int]:
    cases = config.get("cases") or []
    answerable = sum(1 for case in cases if bool(case.get("answerable", True)))
    unanswerable = sum(1 for case in cases if case.get("answerable") is False)
    explicit_gold = sum(
        1 for case in cases if case.get("gold_evidence") or case.get("gold_chunk_ids")
    )
    expected_gold = sum(
        1
        for case in cases
        if case.get("expected_doc_ids") and case.get("expected_terms")
    )
    return {
        "dataset_size": len(cases),
        "answerable_questions": answerable,
        "unanswerable_questions": unanswerable,
        "explicit_gold_evidence_cases": explicit_gold,
        "derived_gold_evidence_cases": expected_gold,
    }


def _stage_value(summary: dict[str, Any], stage: str, stat: str) -> float | None:
    value = ((summary.get("stage_latency") or {}).get(stage) or {}).get(stat)
    return float(value) if isinstance(value, (int, float)) else None


def _metric(summary: dict[str, Any], key: str) -> float | None:
    value = summary.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _failure_rate(summary: dict[str, Any], key: str) -> float | None:
    total = summary.get("num_predictions")
    count = (summary.get("failure_category_counts") or {}).get(key)
    if not isinstance(total, int) or total <= 0 or not isinstance(count, int):
        return None
    return count / total


def _total_latency_ms(summary: dict[str, Any]) -> float | None:
    values = [
        float(case["latency_ms"])
        for case in summary.get("case_results") or []
        if isinstance(case.get("latency_ms"), (int, float))
    ]
    if values:
        return sum(values)
    latency = summary.get("latency") or {}
    mean = latency.get("mean")
    n = summary.get("num_predictions")
    if isinstance(mean, (int, float)) and isinstance(n, int):
        return float(mean) * n
    return None


def build_metrics_json(
    summary: dict[str, Any],
    config: dict[str, Any],
    *,
    run_id: str,
    command: list[str],
    artifact_paths: dict[str, str],
) -> dict[str, Any]:
    failure_counts = summary.get("failure_category_counts") or {}
    hallucination_count = int(failure_counts.get("generator_hallucination") or 0)
    metrics = {
        "schema_version": 1,
        "run_id": run_id,
        "system": "Naive Dense RAG",
        "evaluation_command": " ".join(command),
        "config": summary.get("config"),
        "index_dir": summary.get("index_dir"),
        "dataset": dataset_counts(config),
        "artifacts": artifact_paths,
        "Retrieval metrics": {
            label: _metric(summary, key) for label, key in RETRIEVAL_LABELS.items()
        },
        "Answer/evidence metrics": {
            "Faithfulness": _metric(summary, "groundedness"),
            "Answer relevancy": _metric(summary, "accuracy"),
            "Citation accuracy": _metric(summary, "citation_precision"),
            "Hallucination rate": _failure_rate(summary, "generator_hallucination"),
            "Hallucination count": hallucination_count,
            "Unanswerable detection rate": _metric(summary, "abstention"),
            "Unanswerable outcomes": summary.get("abstention_outcomes"),
        },
        "Operational metrics": {
            "total latency ms": _total_latency_ms(summary),
            "retrieval latency mean ms": _stage_value(summary, "retrieve_ms", "mean"),
            "retrieval latency p50 ms": _stage_value(summary, "retrieve_ms", "p50"),
            "retrieval latency p95 ms": _stage_value(summary, "retrieve_ms", "p95"),
            "generation latency mean ms": _stage_value(summary, "answer_generation_ms", "mean"),
            "generation latency p50 ms": _stage_value(summary, "answer_generation_ms", "p50"),
            "generation latency p95 ms": _stage_value(summary, "answer_generation_ms", "p95"),
            "P50 latency ms": (summary.get("latency") or {}).get("p50"),
            "P95 latency ms": (summary.get("latency") or {}).get("p95"),
        },
        "raw_eval_summary_keys": {
            "accuracy": summary.get("accuracy"),
            "groundedness": summary.get("groundedness"),
            "citation_precision": summary.get("citation_precision"),
            "claim_citation_alignment": summary.get("claim_citation_alignment"),
            "failure_category_counts": failure_counts,
            "latency": summary.get("latency"),
            "stage_latency": summary.get("stage_latency"),
        },
    }
    validate_metrics(metrics)
    return metrics


def validate_metrics(metrics: dict[str, Any]) -> None:
    required = {
        "Retrieval metrics": ("Recall@5", "Recall@10", "MRR@5", "nDCG@5"),
        "Answer/evidence metrics": (
            "Faithfulness",
            "Answer relevancy",
            "Citation accuracy",
            "Hallucination rate",
            "Unanswerable detection rate",
        ),
        "Operational metrics": (
            "total latency ms",
            "retrieval latency mean ms",
            "generation latency mean ms",
            "P50 latency ms",
            "P95 latency ms",
        ),
    }
    missing: list[str] = []
    for group, keys in required.items():
        block = metrics.get(group)
        if not isinstance(block, dict):
            missing.append(group)
            continue
        for key in keys:
            if key not in block or block[key] is None:
                missing.append(f"{group}.{key}")
    if missing:
        raise ValueError("metrics.json missing required keys: " + ", ".join(sorted(missing)))


def answers_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for case in summary.get("case_results") or []:
        hallucination_flag = case.get("failure_category") == "generator_hallucination"
        unanswerable_flag = (
            bool(case.get("abstained")) if case.get("answerable") is False else None
        )
        rows.append(
            {
                "case_id": case.get("id"),
                "query": case.get("query"),
                "query_type": case.get("query_type"),
                "answerable": case.get("answerable"),
                "expected_answer": case.get("expected_answer") or "; ".join(case.get("expected_terms") or []),
                "answer": case.get("answer"),
                "citations": case.get("citation") or [],
                "metrics": {
                    "faithfulness": case.get("groundedness"),
                    "answer_relevancy": case.get("accuracy"),
                    "citation_accuracy": case.get("citation_precision"),
                    "claim_citation_alignment": case.get("claim_citation_alignment"),
                    "abstention": case.get("abstention"),
                },
                "hallucination_flag": hallucination_flag,
                "unanswerable_detection_flag": unanswerable_flag,
                "failure_category": case.get("failure_category"),
            }
        )
    return rows


def retrieved_chunk_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for case in summary.get("case_results") or []:
        rows.append(
            {
                "case_id": case.get("id"),
                "query": case.get("query"),
                "query_type": case.get("query_type"),
                "answerable": case.get("answerable"),
                "gold_evidence": case.get("gold_evidence") or [],
                "gold_chunk_ids": case.get("gold_chunk_ids") or [],
                "retrieved_chunks": case.get("retrieved_chunks") or [],
                "retrieval_metrics": {
                    "Recall@5": case.get("chunk_recall_at_5"),
                    "Recall@10": case.get("chunk_recall_at_10"),
                    "MRR@5": case.get("chunk_mrr_at_5"),
                    "nDCG@5": case.get("chunk_ndcg_at_5"),
                },
                "failure_category": case.get("failure_category"),
            }
        )
    return rows


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _bucket_template() -> dict[str, Counter[str]]:
    return {group: Counter({name: 0 for name in names}) for group, names in REQUIRED_FAILURE_BUCKETS.items()}


def categorize_failures(
    summary: dict[str, Any],
    *,
    metric_errors: list[str] | None = None,
) -> dict[str, Any]:
    buckets = _bucket_template()
    representative: list[dict[str, Any]] = []
    case_results = summary.get("case_results") or []
    index_coverage = summary.get("index_citation_metadata_coverage") or {}
    if index_coverage.get("coverage_reason") == "index_lacks_page_region_metadata":
        buckets["parsing_failures"]["page metadata missing"] += len(case_results)
        cited_cases = sum(
            1 for case in case_results if case.get("citation") or case.get("evidence_doc_ids")
        )
        buckets["citation_failures"]["missing page number"] += cited_cases

    for case in case_results:
        case_labels: list[str] = []
        answerable = bool(case.get("answerable", True))
        recall5 = case.get("chunk_recall_at_5")
        recall10 = case.get("chunk_recall_at_10")
        accuracy = case.get("accuracy")
        citation = case.get("citation_precision")
        alignment = case.get("claim_citation_alignment")
        failure_category = case.get("failure_category")
        hardcase = set(case.get("hardcase_categories") or [])
        query = str(case.get("query") or "")

        retrieval_gap_counted = False
        if answerable and isinstance(recall5, (int, float)):
            if recall5 == 0.0:
                buckets["retrieval_failures"]["gold evidence not in top-k"] += 1
                case_labels.append("retrieval: gold evidence not in top-k")
                retrieval_gap_counted = True
            elif recall5 < 1.0:
                if isinstance(recall10, (int, float)) and recall10 > recall5:
                    buckets["retrieval_failures"]["gold evidence ranked too low"] += 1
                    case_labels.append("retrieval: gold evidence ranked too low")
                else:
                    buckets["retrieval_failures"]["multi-chunk evidence missing"] += 1
                    case_labels.append("retrieval: multi-chunk evidence missing")
                retrieval_gap_counted = True
            if "chunk_boundary" in hardcase and recall5 < 1.0:
                buckets["retrieval_failures"]["chunk boundary split"] += 1
                case_labels.append("retrieval: chunk boundary split")

        if (
            answerable
            and case.get("query_type") == "comparison"
            and isinstance(case.get("comparison_target_recall"), (int, float))
            and case.get("comparison_target_recall") < 1.0
            and not retrieval_gap_counted
        ):
            buckets["retrieval_failures"]["multi-chunk evidence missing"] += 1
            case_labels.append("retrieval: multi-chunk evidence missing")

        if answerable and any("A" <= ch <= "z" for ch in query) and accuracy != 1.0:
            buckets["parsing_failures"]["Korean/English mixed text issue"] += 1
            case_labels.append("parsing: Korean/English mixed text issue")

        if citation is not None and citation < 1.0:
            if accuracy == 1.0:
                buckets["citation_failures"]["correct answer but wrong citation"] += 1
                case_labels.append("citation: correct answer but wrong citation")
            else:
                buckets["citation_failures"]["insufficient citation"] += 1
                case_labels.append("citation: insufficient citation")
        if isinstance(alignment, (int, float)) and alignment < 1.0:
            buckets["citation_failures"]["citation does not support claim"] += 1
            case_labels.append("citation: citation does not support claim")
        if case.get("query_type") == "comparison" and citation is not None and citation < 1.0:
            buckets["citation_failures"]["vague citation for multiple claims"] += 1
            case_labels.append("citation: vague citation for multiple claims")
        if case.get("citation_page_coverage_reason") in {"no_citations", "no_gold_pages"}:
            buckets["citation_failures"]["missing page number"] += 1

        if answerable and accuracy != 1.0:
            if failure_category == "generator_hallucination":
                buckets["answer_failures"]["hallucinated requirement"] += 1
                case_labels.append("answer: hallucinated requirement")
            elif case.get("groundedness") != 1.0:
                buckets["answer_failures"]["overconfident weak evidence"] += 1
                case_labels.append("answer: overconfident weak evidence")
            elif case.get("term_match") is False:
                buckets["answer_failures"]["partial answer"] += 1
                case_labels.append("answer: partial answer")
            else:
                buckets["answer_failures"]["wrong synthesis"] += 1
                case_labels.append("answer: wrong synthesis")
        if not answerable and case.get("abstention") != 1.0:
            buckets["answer_failures"]["failed to abstain"] += 1
            case_labels.append("answer: failed to abstain")

        if answerable and not case.get("gold_chunk_ids"):
            buckets["evaluation_failures"]["missing gold evidence"] += 1
            case_labels.append("evaluation: missing gold evidence")

        if case_labels:
            representative.append(
                {
                    "case_id": case.get("id"),
                    "query_type": case.get("query_type"),
                    "labels": case_labels,
                    "expected": case.get("expected_answer") or "; ".join(case.get("expected_terms") or []),
                    "answer": case.get("answer"),
                    "failure_category": failure_category,
                }
            )

    for err in metric_errors or []:
        key = "metric missing" if "missing" in err.lower() else "schema mismatch"
        buckets["evaluation_failures"][key] += 1

    compact = {group: dict(counter) for group, counter in buckets.items()}
    totals = {
        group: sum(count for count in counter.values())
        for group, counter in compact.items()
    }
    return {
        "buckets": compact,
        "totals": totals,
        "representative_cases": representative[:5],
    }


def _fmt_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{float(value):.2f} ms"
    return str(value)


def _top_nonzero(buckets: dict[str, dict[str, int]], limit: int = 6) -> list[tuple[str, int]]:
    counts = []
    for group, bucket in buckets.items():
        prefix = group.replace("_", " ").replace("failures", "").strip()
        for name, count in bucket.items():
            if count:
                counts.append((f"{prefix}: {name}", count))
    return sorted(counts, key=lambda item: (-item[1], item[0]))[:limit]


def recommend_issues(analysis: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = analysis["buckets"]
    retrieval_total = analysis["totals"].get("retrieval_failures", 0)
    citation_total = analysis["totals"].get("citation_failures", 0)
    parsing_total = analysis["totals"].get("parsing_failures", 0)
    answer_total = analysis["totals"].get("answer_failures", 0)
    evaluation_total = analysis["totals"].get("evaluation_failures", 0)

    issues: list[dict[str, Any]] = []
    if retrieval_total:
        issues.append(
            {
                "title": "Measure dense retrieval miss patterns before adding reranking",
                "problem": "Naive dense retrieval missed or under-ranked gold chunks on observed fixture cases.",
                "why_it_matters": "Recall is the first bottleneck; answer changes cannot recover evidence that never enters context.",
                "expected_metric_impact": "Recall@5/Recall@10 and MRR@5 diagnostics become actionable for later retrieval experiments.",
                "files_likely_to_change": "eval/config.yaml, docs/evaluation/naive_rag_baseline_report.md, optional scripts/* analysis helper",
                "acceptance_criteria": "A retrieval-only follow-up report separates not-in-top-k, ranked-too-low, boundary, and multi-chunk misses.",
                "parallel_ai_assisted": "Yes",
            }
        )
    if citation_total:
        issues.append(
            {
                "title": "Audit citation support gaps in naive baseline answers",
                "problem": "Observed citations are incomplete, vague, or not aligned with the generated claims.",
                "why_it_matters": "RFP review needs claim-to-evidence traceability even when the textual answer is mostly correct.",
                "expected_metric_impact": "Citation accuracy and claim-citation alignment should become explainable before verifier work starts.",
                "files_likely_to_change": "eval/scorers/citation.py, eval/scorers/alignment.py, docs/evaluation/naive_rag_baseline_report.md",
                "acceptance_criteria": "Each citation failure case has a deterministic reason code and a representative example.",
                "parallel_ai_assisted": "Yes",
            }
        )
    if parsing_total:
        issues.append(
            {
                "title": "Measure page metadata coverage for baseline citations",
                "problem": "The current index/eval output exposes missing or weak page metadata as a baseline limitation.",
                "why_it_matters": "Simple source references require stable page/chunk identifiers before richer grounding can be trusted.",
                "expected_metric_impact": "Citation page coverage and missing-page-number counts become measurable.",
                "files_likely_to_change": "ingestion.py, scripts/build_index.py, eval/scorers/citation.py",
                "acceptance_criteria": "Smoke eval reports page metadata coverage without changing naive retrieval ranking.",
                "parallel_ai_assisted": "Yes",
            }
        )
    if answer_total:
        issues.append(
            {
                "title": "Catalog naive answer failure modes without prompt tuning",
                "problem": "The baseline produced an answer-policy failure on observed cases, including failed abstention when evidence was insufficient.",
                "why_it_matters": "Answer failures must be separated from retrieval misses before prompt or verifier experiments.",
                "expected_metric_impact": "Faithfulness, answer relevancy, hallucination, and abstention error rates get cleaner attribution.",
                "files_likely_to_change": "docs/evaluation/naive_rag_baseline_report.md, eval/scorers/case.py",
                "acceptance_criteria": "Failure cases distinguish partial answer, weak evidence, wrong synthesis, and failed abstention.",
                "parallel_ai_assisted": "Yes",
            }
        )
    if evaluation_total:
        issues.append(
            {
                "title": "Harden gold evidence and metric schema checks",
                "problem": "The baseline run surfaced evaluation contract gaps such as missing gold evidence or missing metrics.",
                "why_it_matters": "Bad or incomplete evaluation artifacts can hide real baseline limitations.",
                "expected_metric_impact": "Metric coverage improves; evaluation failures stop being mixed into RAG failures.",
                "files_likely_to_change": "eval/config.yaml, eval/scorers/chunk_metrics.py, tests/test_run_naive_baseline_eval.py",
                "acceptance_criteria": "Eval fails loud when required metric keys or answerable-case gold evidence are unavailable.",
                "parallel_ai_assisted": "Yes",
            }
        )

    if len(issues) < 3:
        issues.append(
            {
                "title": "Expand public fixture baseline slices with observed weak areas",
                "problem": "The current public fixture is small, so observed gaps need a few targeted cases to avoid overfitting interpretation.",
                "why_it_matters": "A measurable baseline needs enough cases to separate retrieval, citation, answer, and parsing failures.",
                "expected_metric_impact": "Recall@k, citation accuracy, faithfulness, and abstention rates become less brittle.",
                "files_likely_to_change": "eval/config.yaml, eval/fixtures/smoke_rfp/raw/*, docs/evaluation/naive_rag_baseline_report.md",
                "acceptance_criteria": "New cases are public-fixture safe and each maps to one observed failure category.",
                "parallel_ai_assisted": "Yes",
            }
        )
    if len(issues) < 3:
        issues.append(
            {
                "title": "Add a reproducibility check for packaged baseline artifacts",
                "problem": "The wrapper exports multiple files, and schema drift should fail before report numbers are trusted.",
                "why_it_matters": "The baseline report depends on metrics.json, retrieved_chunks.jsonl, answers.jsonl, and failure_cases.jsonl staying aligned.",
                "expected_metric_impact": "No direct quality lift; improves evaluation reliability.",
                "files_likely_to_change": "scripts/run_naive_baseline_eval.py, tests/test_run_naive_baseline_eval.py",
                "acceptance_criteria": "A test fixture verifies all required artifact schemas from a minimal eval_summary.json.",
                "parallel_ai_assisted": "Yes",
            }
        )
    return issues[:6]


def render_summary_md(
    *,
    run_id: str,
    command: list[str],
    metrics: dict[str, Any],
    analysis: dict[str, Any],
) -> str:
    retrieval = metrics["Retrieval metrics"]
    answer = metrics["Answer/evidence metrics"]
    ops = metrics["Operational metrics"]
    top = _top_nonzero(analysis["buckets"])
    lines = [
        f"# Naive RAG Baseline Run: {run_id}",
        "",
        "## Command",
        "",
        "```bash",
        " ".join(command),
        "```",
        "",
        "## Experiment Summary",
        "",
        "| System | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Citation Acc. | Faithfulness | Hallucination | P95 Latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            "| Naive Dense RAG | "
            f"{_fmt_number(retrieval['Recall@5'])} | "
            f"{_fmt_number(retrieval['Recall@10'])} | "
            f"{_fmt_number(retrieval['MRR@5'])} | "
            f"{_fmt_number(retrieval['nDCG@5'])} | "
            f"{_fmt_number(answer['Citation accuracy'])} | "
            f"{_fmt_number(answer['Faithfulness'])} | "
            f"{_fmt_number(answer['Hallucination rate'])} | "
            f"{_fmt_ms(ops['P95 latency ms'])} |"
        ),
        "",
        "## Top Failure Categories",
        "",
    ]
    if top:
        lines.extend(f"- {name}: {count}" for name, count in top)
    else:
        lines.append("- No nonzero failure categories observed.")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_report(
    *,
    run_id: str,
    command: list[str],
    metrics: dict[str, Any],
    analysis: dict[str, Any],
    issues: list[dict[str, Any]],
) -> str:
    counts = metrics["dataset"]
    retrieval = metrics["Retrieval metrics"]
    answer = metrics["Answer/evidence metrics"]
    ops = metrics["Operational metrics"]
    top = _top_nonzero(analysis["buckets"])
    lines = [
        "# Naive RAG Baseline Report",
        "",
        "이 문서는 공개 fixture smoke 계약으로 현재 naive baseline을 측정한 첫 재현 가능 baseline report입니다. 실제 성능 claim은 private/internal eval aggregate에서만 판단합니다.",
        "",
        "## Evaluation Command",
        "",
        "```bash",
        " ".join(command),
        "```",
        "",
        "## Run Metadata",
        "",
        f"- run_id: `{run_id}`",
        f"- dataset size: {counts['dataset_size']}",
        f"- answerable questions: {counts['answerable_questions']}",
        f"- unanswerable questions: {counts['unanswerable_questions']}",
        f"- gold evidence source: {counts['explicit_gold_evidence_cases']} explicit, {counts['derived_gold_evidence_cases']} derived from `expected_doc_ids` + `expected_terms`",
        "",
        "## Metric Summary",
        "",
        "| System | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Citation Acc. | Faithfulness | Hallucination | P95 Latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            "| Naive Dense RAG | "
            f"{_fmt_number(retrieval['Recall@5'])} | "
            f"{_fmt_number(retrieval['Recall@10'])} | "
            f"{_fmt_number(retrieval['MRR@5'])} | "
            f"{_fmt_number(retrieval['nDCG@5'])} | "
            f"{_fmt_number(answer['Citation accuracy'])} | "
            f"{_fmt_number(answer['Faithfulness'])} | "
            f"{_fmt_number(answer['Hallucination rate'])} | "
            f"{_fmt_ms(ops['P95 latency ms'])} |"
        ),
        "",
        "## Failure Categories",
        "",
    ]
    for group, bucket in analysis["buckets"].items():
        title = group.replace("_", " ").title()
        lines.append(f"### {title}")
        for name, count in bucket.items():
            lines.append(f"- {name}: {count}")
        lines.append("")

    lines.append("## Top Failure Categories")
    lines.append("")
    if top:
        lines.extend(f"- {name}: {count}" for name, count in top)
    else:
        lines.append("- No nonzero failure categories observed.")
    lines.append("")

    lines.append("## Representative Failure Cases")
    lines.append("")
    reps = analysis["representative_cases"]
    if reps:
        for case in reps:
            labels = "; ".join(case["labels"])
            answer_text = str(case.get("answer") or "").replace("\n", " ")[:220]
            expected = str(case.get("expected") or "").replace("\n", " ")[:180]
            lines.extend(
                [
                    f"- `{case['case_id']}` ({case['query_type']}): {labels}",
                    f"  - expected: {expected or 'N/A'}",
                    f"  - generated: {answer_text or 'N/A'}",
                ]
            )
    else:
        lines.append("- No representative failure cases were emitted.")
    lines.append("")

    good = []
    if retrieval["Recall@5"] == 1.0:
        good.append("Dense top-k retrieval found all derived gold chunks in the public fixture smoke set.")
    if answer["Unanswerable detection rate"] == 1.0:
        good.append("The unanswerable smoke case was detected as insufficient.")
    if answer["Answer relevancy"] == 1.0 and answer["Faithfulness"] == 1.0:
        good.append("Answerable fixture cases scored as relevant and faithful under the current rule-based scorer.")
    if not good:
        good.append("The run is reproducible and emits separated retrieval, answer/evidence, citation, failure, and latency artifacts.")
    lines.append("## What The Naive Baseline Does Reasonably Well")
    lines.append("")
    lines.extend(f"- {item}" for item in good)
    lines.append("")

    weak = []
    if retrieval["Recall@5"] != 1.0:
        weak.append("Dense-only retrieval has observable recall/ranking gaps before any answer logic is considered.")
    if answer["Citation accuracy"] != 1.0:
        weak.append("Citation accuracy is below perfect, so answers are not always tied to sufficient evidence.")
    if answer["Faithfulness"] != 1.0:
        weak.append("Faithfulness is below perfect, showing unsupported or partial evidence use.")
    if answer["Unanswerable detection rate"] != 1.0:
        weak.append("The baseline failed to abstain on at least one unanswerable case and answered with weak evidence.")
    if analysis["totals"].get("parsing_failures", 0):
        weak.append("Parser/index metadata limitations affect simple source references such as page numbers.")
    if not weak:
        weak.append("This small public fixture is too small to expose all expected naive baseline limitations; private/internal eval remains necessary.")
    lines.append("## What The Naive Baseline Fails At")
    lines.append("")
    lines.extend(f"- {item}" for item in weak)
    lines.append("")

    lines.append("## Recommended Next Experiments")
    lines.append("")
    for issue in issues:
        lines.extend(
            [
                f"### {issue['title']}",
                f"- problem: {issue['problem']}",
                f"- why it matters: {issue['why_it_matters']}",
                f"- expected metric impact: {issue['expected_metric_impact']}",
                f"- files likely to change: `{issue['files_likely_to_change']}`",
                f"- acceptance criteria: {issue['acceptance_criteria']}",
                f"- suitable for parallel AI-assisted coding: {issue['parallel_ai_assisted']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def export_artifacts(
    *,
    run_id: str,
    run_dir: Path,
    command: list[str],
    config: dict[str, Any],
    report_path: Path,
) -> dict[str, Any]:
    summary_path = run_dir / "eval_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"eval_summary.json missing: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    failure_source = run_dir / "failures" / "naive_baseline.jsonl"
    failure_rows = load_jsonl(failure_source)
    failure_cases_path = run_dir / "failure_cases.jsonl"
    write_jsonl(failure_cases_path, failure_rows)

    artifact_paths = {
        "metrics": rel_path(run_dir / "metrics.json"),
        "retrieved_chunks": rel_path(run_dir / "retrieved_chunks.jsonl"),
        "answers": rel_path(run_dir / "answers.jsonl"),
        "failure_cases": rel_path(failure_cases_path),
        "summary": rel_path(run_dir / "summary.md"),
        "eval_summary": rel_path(summary_path),
        "eval_log": rel_path(run_dir / "logs" / "eval.log"),
    }
    metrics = build_metrics_json(
        summary,
        config,
        run_id=run_id,
        command=command,
        artifact_paths=artifact_paths,
    )
    analysis = categorize_failures(summary)
    issues = recommend_issues(analysis, metrics)

    write_json(run_dir / "metrics.json", metrics)
    write_jsonl(run_dir / "retrieved_chunks.jsonl", retrieved_chunk_rows(summary))
    write_jsonl(run_dir / "answers.jsonl", answers_rows(summary))
    (run_dir / "summary.md").write_text(
        render_summary_md(
            run_id=run_id,
            command=command,
            metrics=metrics,
            analysis=analysis,
        ),
        encoding="utf-8",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            run_id=run_id,
            command=command,
            metrics=metrics,
            analysis=analysis,
            issues=issues,
        ),
        encoding="utf-8",
    )
    return {
        "metrics": metrics,
        "analysis": analysis,
        "issues": issues,
        "artifact_paths": artifact_paths,
    }


def main() -> int:
    args = parse_args()
    source_config_path = repo_path(args.config)
    index_dir = repo_path(args.index_dir)
    output_root = repo_path(args.output_root)
    report_path = repo_path(args.report_path)
    run_id = args.run_id or default_run_id()
    run_dir = output_root / run_id

    if run_dir.exists():
        if not args.force:
            print(f"[ERROR] Run directory already exists: {rel_path(run_dir)}", file=sys.stderr)
            return 2
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    source_config = load_yaml(source_config_path)
    naive_config = select_naive_config(source_config)
    run_config_path = run_dir / "config.naive.yaml"
    run_config_path.write_text(
        yaml.safe_dump(naive_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    command = build_eval_command(run_config_path, index_dir, run_dir)
    try:
        run_eval_command(command, run_dir / "logs" / "eval.log")
        result = export_artifacts(
            run_id=run_id,
            run_dir=run_dir,
            command=command,
            config=naive_config,
            report_path=report_path,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print(f"[OK] Naive baseline run written: {rel_path(run_dir)}")
    print(f"[OK] metrics.json: {result['artifact_paths']['metrics']}")
    print(f"[OK] failure_cases.jsonl: {result['artifact_paths']['failure_cases']}")
    print(f"[OK] report: {rel_path(report_path)}")
    print(f"run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
