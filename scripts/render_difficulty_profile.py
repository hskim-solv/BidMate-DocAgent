#!/usr/bin/env python3
"""Render an aggregate-only private real-eval difficulty profile.

The renderer reads local-only private eval diagnostics and index chunk text to
derive difficulty buckets in memory. Outputs intentionally contain only counts,
closed enum buckets, means, and safe provenance. No raw question text, answer
text, evidence text, document IDs, chunk IDs, filenames, paths, or per-case rows
cross the ADR 0005 boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_INDEX = ROOT / "data" / "index" / "real100" / "index.json"
DEFAULT_BASELINE = ROOT / "reports" / "real100" / "baseline.aggregate.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100" / "difficulty_profile.aggregate.json"
DEFAULT_OUT_MD = ROOT / "reports" / "real100" / "difficulty_profile.md"

SCHEMA_VERSION = 1
METRIC_KEYS = (
    "accuracy",
    "recall_at_5",
    "recall_at_10",
    "mrr_at_5",
    "ndcg_at_5",
    "citation_precision",
    "abstention",
)
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "question",
        "query",
        "resolved_query",
        "answer",
        "answer_text",
        "generated_answer",
        "expected_answer",
        "gold_evidence",
        "retrieved_chunks",
        "retrieved_chunk_ids",
        "gold_chunk_ids",
        "evidence",
        "text",
        "text_preview",
        "section",
        "section_path",
        "title",
        "doc_id",
        "chunk_id",
        "id",
        "question_id",
        "qid",
        "filename",
        "file_name",
        "file",
        "path",
        "absolute_path",
        "index_dir",
        "output_dir",
        "trace_path",
    }
)
ABSOLUTE_PATH_RE = re.compile(r"(^|[\s'\"])(?:/Users/|/private/|/home/|/Volumes/|[A-Za-z]:[\\/])")
TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")
TABLE_RE = re.compile(r"(<table\b|</t[dh]>|rowspan=|colspan=|\|[^\n]+\||\t)", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4}\s*[.\-/년]\s*\d{1,2}|마감|기한|기간|일정|deadline|date)", re.IGNORECASE)
AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|원|천원|만원|억원|예산|금액|사업비|budget|amount|cost)", re.IGNORECASE)
SCORE_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:점|%)|배점|평가점수|score|points?)", re.IGNORECASE)
SAFE_FAILURE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON input not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return payload


def _source_provenance(path: Path) -> dict[str, Any]:
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        location = str(resolved_path.relative_to(resolved_root))
        redacted = False
    except ValueError:
        location = f"external_private/{path.name}"
        redacted = True
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return {
        "location": location,
        "location_redacted": redacted,
        "basename": path.name,
        "sha256_12": digest,
    }


def _case_results(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw = summary.get("case_results")
    if not isinstance(raw, list):
        raise ValueError("eval_summary.json::case_results missing or not a list")
    return [case for case in raw if isinstance(case, dict)]


def _is_naive_summary(summary: dict[str, Any]) -> bool:
    candidates: list[str] = []
    for value in (summary.get("primary_run"), summary.get("pipeline")):
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            candidates.extend(str(value.get(key) or "") for key in ("name", "pipeline"))
    return any(value == "naive_baseline" for value in candidates)


def _chunk_text_index(index_payload: dict[str, Any]) -> dict[str, str]:
    chunks = index_payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("index.json must contain a non-empty chunks list")
    out: dict[str, str] = {}
    for item in chunks:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "")
        text = str(item.get("text") or "")
        if chunk_id:
            out[chunk_id] = text
    if not out:
        raise ValueError("index.json chunks contain no usable chunk_id values")
    return out


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _gold_chunk_ids(case: dict[str, Any]) -> list[str]:
    explicit = _unique_strings(case.get("gold_chunk_ids"))
    evidence_ids: list[str] = []
    for item in case.get("gold_evidence") or []:
        if isinstance(item, dict) and item.get("chunk_id"):
            evidence_ids.append(str(item["chunk_id"]))
    return _unique_strings([*explicit, *evidence_ids])


def _gold_doc_count(case: dict[str, Any]) -> int | None:
    doc_ids: list[str] = []
    for item in case.get("gold_evidence") or []:
        if isinstance(item, dict) and item.get("doc_id"):
            doc_ids.append(str(item["doc_id"]))
    if not doc_ids:
        doc_ids = _unique_strings(case.get("expected_doc_ids"))
    if not doc_ids:
        return None
    return len(set(doc_ids))


def _bucket_count(count: int | None, *, missing_label: str = "missing") -> str:
    if count is None:
        return missing_label
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 3:
        return "2_3"
    return "4_plus"


def _expected_terms_bucket(case: dict[str, Any]) -> str:
    if "expected_terms" not in case:
        return "missing"
    terms = case.get("expected_terms")
    if not isinstance(terms, list):
        return "missing"
    return _bucket_count(len([term for term in terms if str(term).strip()]))


def _gold_doc_bucket(count: int | None) -> str:
    if count == 1:
        return "single_doc"
    if count is not None and count >= 2:
        return "multi_doc"
    return "unknown"


def _gold_chunk_bucket(count: int) -> str:
    if count == 0:
        return "none"
    if count == 1:
        return "single_chunk"
    return "multi_chunk"


def _length_bucket(length: int | None) -> str:
    if length is None:
        return "missing"
    if length <= 500:
        return "0_500"
    if length <= 1200:
        return "501_1200"
    if length <= 2500:
        return "1201_2500"
    return "2501_plus"


def _overlap_bucket(score: float | None) -> str:
    if score is None:
        return "missing"
    if score <= 0.0:
        return "none"
    if score < 0.10:
        return "low"
    if score < 0.30:
        return "medium"
    return "high"


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 2}


def _lexical_overlap(question: str, evidence_text: str) -> float | None:
    q_tokens = _tokens(question)
    e_tokens = _tokens(evidence_text)
    if not q_tokens or not e_tokens:
        return None
    return len(q_tokens & e_tokens) / len(q_tokens)


def _safe_metric(case: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = case.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    return None


def _case_metrics(case: dict[str, Any]) -> dict[str, float | None]:
    return {
        "accuracy": _safe_metric(case, "accuracy"),
        "recall_at_5": _safe_metric(case, "chunk_recall_at_5"),
        "recall_at_10": _safe_metric(case, "chunk_recall_at_10"),
        "mrr_at_5": _safe_metric(case, "chunk_mrr_at_5", "chunk_mrr"),
        "ndcg_at_5": _safe_metric(case, "chunk_ndcg_at_5"),
        "citation_precision": _safe_metric(case, "citation_precision", "citation_accuracy"),
        "abstention": _safe_metric(case, "abstention"),
    }


def _mean(values: list[float | None]) -> dict[str, Any]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return {
        "mean": (sum(numeric) / len(numeric)) if numeric else None,
        "n": len(numeric),
        "missing": len(values) - len(numeric),
    }


def _safe_failure_category(value: Any) -> str:
    if value is None or value == "":
        return "no_failure"
    text = str(value).split(":", 1)[0].strip()
    return text if SAFE_FAILURE_RE.fullmatch(text) else "other"


def _metric_block(cases: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [_case_metrics(case) for case in cases]
    failures = Counter(_safe_failure_category(case.get("failure_category")) for case in cases)
    failed = sum(count for key, count in failures.items() if key != "no_failure")
    return {
        "n": len(cases),
        "failed_count": failed,
        "failure_rate": (failed / len(cases)) if cases else None,
        "metrics": {
            key: _mean([row[key] for row in metrics])
            for key in METRIC_KEYS
        },
        "failure_category_distribution": dict(sorted(failures.items())),
    }


def _question_flags(question: str) -> dict[str, bool]:
    return {
        "date_like": bool(DATE_RE.search(question)),
        "amount_like": bool(AMOUNT_RE.search(question)),
        "score_like": bool(SCORE_RE.search(question)),
    }


def _similar_clause_proxy(case: dict[str, Any]) -> bool:
    failure = str(case.get("failure_category") or "").lower()
    if "similar_clause" in failure or "wrong_similar_clause" in failure:
        return True
    tags = [str(tag).lower() for tag in case.get("hardcase_categories") or []]
    return any(
        ("distractor" in tag or "similar" in tag or "clause" in tag or "near_duplicate" in tag)
        for tag in tags
    )


def _case_features(
    case: dict[str, Any],
    chunk_texts: dict[str, str],
) -> tuple[dict[str, str], dict[str, int]]:
    gold_ids = _gold_chunk_ids(case)
    gold_texts = [chunk_texts[chunk_id] for chunk_id in gold_ids if chunk_id in chunk_texts]
    missing_refs = max(len(gold_ids) - len(gold_texts), 0)
    gold_lengths = [len(text) for text in gold_texts]
    mean_gold_length = int(sum(gold_lengths) / len(gold_lengths)) if gold_lengths else None
    evidence_text = " ".join(gold_texts)
    question = str(case.get("query") or case.get("question") or "")
    flags = _question_flags(question)
    gold_evidence_count = (
        len(case.get("gold_evidence"))
        if isinstance(case.get("gold_evidence"), list)
        else len(gold_ids)
    )
    buckets = {
        "answerability": "answerable" if bool(case.get("answerable", True)) else "unanswerable",
        "gold_doc_cardinality": _gold_doc_bucket(_gold_doc_count(case)),
        "gold_chunk_cardinality": _gold_chunk_bucket(len(gold_ids)),
        "expected_terms_count": _expected_terms_bucket(case),
        "date_like_question": str(flags["date_like"]).lower(),
        "amount_like_question": str(flags["amount_like"]).lower(),
        "score_like_question": str(flags["score_like"]).lower(),
        "table_like_evidence": str(any(TABLE_RE.search(text) for text in gold_texts)).lower(),
        "similar_clause_distractor_proxy": str(_similar_clause_proxy(case)).lower(),
        "gold_evidence_count": _bucket_count(gold_evidence_count),
        "gold_chunk_length": _length_bucket(mean_gold_length),
        "lexical_overlap": _overlap_bucket(_lexical_overlap(question, evidence_text)),
    }
    validity = {
        "answerable_missing_gold_count": int(bool(case.get("answerable", True)) and not gold_ids),
        "missing_index_gold_reference_count": missing_refs,
    }
    return buckets, validity


def _slice_axes(
    cases: list[dict[str, Any]],
    chunk_texts: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    axis_cases: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    validity = Counter()
    easy_cases: list[dict[str, Any]] = []
    failure_dominance: Counter[str] = Counter()

    for case in cases:
        buckets, case_validity = _case_features(case, chunk_texts)
        validity.update(case_validity)
        for axis, bucket in buckets.items():
            axis_cases[axis][bucket].append(case)
            if case.get("failure_category"):
                failure_dominance[f"{axis}__{bucket}"] += 1
        if (
            bool(case.get("answerable", True))
            and buckets["gold_doc_cardinality"] == "single_doc"
            and buckets["gold_chunk_cardinality"] == "single_chunk"
        ):
            easy_cases.append(case)

    axes = {
        axis: {
            bucket: _metric_block(bucket_cases)
            for bucket, bucket_cases in sorted(buckets.items())
        }
        for axis, buckets in sorted(axis_cases.items())
    }
    special = {
        "easy_single_doc_single_chunk_answerable": _metric_block(easy_cases),
    }
    dominance = {
        "top_failure_slices": [
            {
                "axis": key.split("__", 1)[0],
                "bucket": key.split("__", 1)[1],
                "failed_count": count,
                "share_of_all_failures": count / max(1, sum(failure_dominance.values())),
            }
            for key, count in failure_dominance.most_common(8)
        ]
    }
    return axes, special, {"validity_counters": dict(validity), **dominance}


def _abstention_outcomes(summary: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, int]:
    raw = summary.get("abstention_outcomes")
    if isinstance(raw, dict):
        return {
            key: int(raw.get(key) or 0)
            for key in ("correct_refusal", "boundary_partial", "incorrect_answer")
        }
    outcomes = {"correct_refusal": 0, "boundary_partial": 0, "incorrect_answer": 0}
    for case in cases:
        if bool(case.get("answerable", True)):
            continue
        abstention = _safe_metric(case, "abstention")
        if abstention == 1.0:
            outcomes["correct_refusal"] += 1
        elif abstention == 0.0:
            outcomes["incorrect_answer"] += 1
    return outcomes


def _choose_next_improvement(axes: dict[str, dict[str, Any]], special: dict[str, Any], overall: dict[str, Any]) -> dict[str, Any]:
    failure_counts = Counter(overall["failure_category_distribution"])
    retrieval_failures = sum(
        count for key, count in failure_counts.items() if key.startswith("retrieval")
    )
    verifier_failures = failure_counts.get("verifier_false_negative", 0)
    abstention_failures = failure_counts.get("abstention_failure", 0)
    multi_chunk_failures = axes.get("gold_chunk_cardinality", {}).get("multi_chunk", {}).get("failed_count", 0)
    low_overlap_failures = axes.get("lexical_overlap", {}).get("low", {}).get("failed_count", 0)
    no_overlap_failures = axes.get("lexical_overlap", {}).get("none", {}).get("failed_count", 0)
    table_failures = axes.get("table_like_evidence", {}).get("true", {}).get("failed_count", 0)
    easy_recall = (
        special["easy_single_doc_single_chunk_answerable"]["metrics"]["recall_at_10"]["mean"]
    )
    rerank_signal = 0
    for bucket in axes.get("gold_chunk_cardinality", {}).values():
        r5 = bucket["metrics"]["recall_at_5"]["mean"]
        r10 = bucket["metrics"]["recall_at_10"]["mean"]
        n = bucket["metrics"]["recall_at_10"]["n"]
        if r5 is not None and r10 is not None and r10 > r5:
            rerank_signal += n

    scores = {
        "hybrid_sweep": retrieval_failures + low_overlap_failures + no_overlap_failures,
        "reranker": rerank_signal,
        "page_metadata_recovery": table_failures + failure_counts.get("parse_or_metadata_issue", 0),
        "multi_chunk_expansion": multi_chunk_failures,
        "abstention_verifier_tuning": verifier_failures + abstention_failures,
    }
    if easy_recall is not None and easy_recall < 0.30:
        scores["hybrid_sweep"] += special["easy_single_doc_single_chunk_answerable"]["n"]
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {
        "recommended_next": ranked[0][0] if ranked else "hybrid_sweep",
        "ranked_signals": [{"lever": key, "signal_count": int(value)} for key, value in ranked],
    }


def _conclusions(
    cases: list[dict[str, Any]],
    axes: dict[str, dict[str, Any]],
    special: dict[str, Any],
    diagnostics: dict[str, Any],
    overall: dict[str, Any],
) -> dict[str, Any]:
    answerable_n = sum(1 for case in cases if bool(case.get("answerable", True)))
    invalid_count = sum(diagnostics.get("validity_counters", {}).values())
    invalid_rate = invalid_count / max(1, answerable_n)
    recall10 = overall["metrics"]["recall_at_10"]["mean"]
    easy = special["easy_single_doc_single_chunk_answerable"]
    easy_recall10 = easy["metrics"]["recall_at_10"]["mean"]
    easy_citation = easy["metrics"]["citation_precision"]["mean"]
    next_step = _choose_next_improvement(axes, special, overall)
    hard_benchmark = (recall10 is not None and recall10 < 0.30) or overall["failure_rate"] > 0.50
    invalid = invalid_rate > 0.10
    easy_solvable = (
        easy["n"] > 0
        and easy_recall10 is not None
        and easy_recall10 >= max(0.25, (recall10 or 0.0))
    )
    should_split = bool(
        easy["n"] > 0
        and (
            axes.get("gold_chunk_cardinality", {}).get("multi_chunk", {}).get("n", 0) > 0
            or axes.get("lexical_overlap", {}).get("low", {}).get("n", 0) > 0
            or axes.get("table_like_evidence", {}).get("true", {}).get("n", 0) > 0
        )
    )
    return {
        "benchmark_validity": "invalid_benchmark_risk" if invalid else "hard_benchmark_not_invalid",
        "is_eval_too_hard_overall": bool(hard_benchmark),
        "easy_single_doc_single_chunk_solvable": bool(easy_solvable),
        "dominant_failure_slices": diagnostics.get("top_failure_slices", []),
        "split_benchmark_recommended": should_split,
        "split_recommendation": {
            "easy_sanity_subset": "answerable single_doc single_chunk high_or_medium lexical_overlap",
            "standard_real_subset": "answerable single_doc or moderate multi_chunk non-table cases",
            "hard_stress_subset": "multi_doc multi_chunk low_overlap table_like or similar_clause_proxy cases",
        },
        "next_improvement": next_step,
        "interpretation": (
            "Low aggregate scores indicate a hard benchmark, not an invalid benchmark, unless "
            "validity counters dominate the answerable population."
        ),
        "easy_subset_recall_at_10": easy_recall10,
        "easy_subset_citation_precision": easy_citation,
        "overall_recall_at_10": recall10,
        "invalid_signal_rate": invalid_rate,
    }


def assert_public_safe(payload: dict[str, Any]) -> None:
    violations: list[str] = []

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                next_trail = f"{trail}.{key_text}".strip(".")
                if key_text.lower() in FORBIDDEN_OUTPUT_KEYS:
                    violations.append(next_trail)
                if ABSOLUTE_PATH_RE.search(key_text):
                    violations.append(next_trail)
                walk(value, next_trail)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{trail}[{idx}]")
        elif isinstance(node, str) and ABSOLUTE_PATH_RE.search(node):
            violations.append(trail)

    walk(payload, "")
    if violations:
        raise ValueError("difficulty profile contains forbidden private fields: " + ", ".join(violations[:10]))


def build_aggregate(
    summary: dict[str, Any],
    index_payload: dict[str, Any],
    *,
    summary_source: dict[str, Any] | None = None,
    index_source: dict[str, Any] | None = None,
    baseline_source: dict[str, Any] | None = None,
    allow_non_naive: bool = False,
) -> dict[str, Any]:
    if not allow_non_naive and not _is_naive_summary(summary):
        raise ValueError("difficulty profile requires primary_run or pipeline to be naive_baseline")
    cases = _case_results(summary)
    chunk_texts = _chunk_text_index(index_payload)
    axes, special, diagnostics = _slice_axes(cases, chunk_texts)
    overall = _metric_block(cases)
    aggregate = {
        "schema_version": SCHEMA_VERSION,
        "profile_type": "private_real_eval_difficulty_profile",
        "source": {
            "summary": summary_source or {"location": "in_memory", "location_redacted": True},
            "index_source": index_source or {"location": "in_memory", "location_redacted": True},
            "baseline": baseline_source,
        },
        "run": {
            "primary_run": str(summary.get("primary_run") or ""),
            "pipeline": str(summary.get("pipeline") or ""),
            "is_naive_primary": _is_naive_summary(summary),
            "num_predictions": int(summary.get("num_predictions") or len(cases)),
        },
        "population": {
            "num_cases": len(cases),
            "answerable_count": sum(1 for case in cases if bool(case.get("answerable", True))),
            "unanswerable_count": sum(1 for case in cases if not bool(case.get("answerable", True))),
        },
        "overall_outcomes": {
            **overall,
            "abstention_outcomes": _abstention_outcomes(summary, cases),
        },
        "difficulty_axes": axes,
        "special_slices": special,
        "diagnostics": diagnostics,
    }
    aggregate["conclusions"] = _conclusions(cases, axes, special, diagnostics, overall)
    assert_public_safe(aggregate)
    return aggregate


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _metric_mean(block: dict[str, Any], metric: str) -> Any:
    return ((block.get("metrics") or {}).get(metric) or {}).get("mean")


def render_markdown(aggregate: dict[str, Any]) -> str:
    conclusions = aggregate["conclusions"]
    overall = aggregate["overall_outcomes"]
    easy = aggregate["special_slices"]["easy_single_doc_single_chunk_answerable"]
    next_step = conclusions["next_improvement"]
    lines = [
        f"# Real100 difficulty profile (aggregate-only, n={aggregate['population']['num_cases']})",
        "",
        "This report is aggregate-only. It distinguishes a hard benchmark from an invalid benchmark; raw questions, answers, evidence text, IDs, filenames, paths, and case rows are intentionally excluded.",
        "",
        "## Required conclusions",
        "",
        f"1. Overall status: `{conclusions['benchmark_validity']}`; too hard overall: `{str(conclusions['is_eval_too_hard_overall']).lower()}`.",
        f"2. Easy single-doc/single-chunk answerable cases solvable: `{str(conclusions['easy_single_doc_single_chunk_solvable']).lower()}` (n={easy['n']}, recall@10={_fmt_pct(_metric_mean(easy, 'recall_at_10'))}, citation_precision={_fmt_pct(_metric_mean(easy, 'citation_precision'))}).",
        "3. Failure-dominant slices: "
        + ", ".join(
            f"{item['axis']}={item['bucket']} ({item['failed_count']})"
            for item in conclusions["dominant_failure_slices"][:5]
        ),
        f"4. Split benchmark recommended: `{str(conclusions['split_benchmark_recommended']).lower()}` into easy sanity, standard real, and hard stress subsets.",
        f"5. Next improvement justified: `{next_step['recommended_next']}`.",
        "",
        "## Overall outcomes",
        "",
        "| metric | mean | n | missing |",
        "|---|---:|---:|---:|",
    ]
    for key in METRIC_KEYS:
        metric = overall["metrics"][key]
        lines.append(f"| `{key}` | {_fmt_pct(metric['mean'])} | {metric['n']} | {metric['missing']} |")
    lines.extend(
        [
            "",
            "## Difficulty axes",
            "",
            "| axis | bucket | n | failure_rate | recall@10 | citation_precision |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for axis, buckets in aggregate["difficulty_axes"].items():
        for bucket, block in buckets.items():
            lines.append(
                f"| `{axis}` | `{bucket}` | {block['n']} | {_fmt_pct(block['failure_rate'])} | "
                f"{_fmt_pct(_metric_mean(block, 'recall_at_10'))} | "
                f"{_fmt_pct(_metric_mean(block, 'citation_precision'))} |"
            )
    lines.extend(["", "## Next-improvement signals", "", "| lever | signal_count |", "|---|---:|"])
    for row in next_step["ranked_signals"]:
        lines.append(f"| `{row['lever']}` | {row['signal_count']} |")
    lines.extend(
        [
            "",
            "## Privacy boundary",
            "",
            "The profiler may compute lexical overlap from private text locally, but only bucket counts and aggregate means are rendered. Hard benchmark does not mean invalid benchmark; invalidity is reserved for missing gold/index references or unobservable metrics dominating the population.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--allow-non-naive", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = _load_json(args.summary)
        index_payload = _load_json(args.index)
        baseline_source = _source_provenance(args.baseline) if args.baseline.is_file() else None
        aggregate = build_aggregate(
            summary,
            index_payload,
            summary_source=_source_provenance(args.summary),
            index_source=_source_provenance(args.index),
            baseline_source=baseline_source,
            allow_non_naive=bool(args.allow_non_naive),
        )
        markdown = render_markdown(aggregate)
        rendered = json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        assert_public_safe(aggregate)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(rendered, encoding="utf-8")
        args.out_md.write_text(markdown, encoding="utf-8")
    except Exception as exc:
        print(f"[ERROR] difficulty profile failed: {exc}", file=sys.stderr)
        return 1
    print(f"[OK] Wrote {args.out_json} and {args.out_md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
