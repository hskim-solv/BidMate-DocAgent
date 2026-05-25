#!/usr/bin/env python3
"""Private aggregate-only hybrid retrieval parameter sweep.

Compares the ``full_dense`` control path against hybrid BM25+dense RRF
variants while keeping verifier, prompt, chunking, reranker, and answer
generation unchanged. The output is intentionally aggregate-only: no raw
questions, answers, evidence, doc_ids, chunk_ids, filenames, paths, or text
previews are written.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.run_eval import load_config, normalize_run_config  # noqa: E402
from eval.scorers import derive_gold_evidence, score_case  # noqa: E402
from eval.scorers.failure_classifier import classify_failure  # noqa: E402
from rag_core import (  # noqa: E402
    DEFAULT_RAG_PIPELINE_NAME,
    _run_rag_query_with_plan_overrides,
    load_index,
    percentile,
    rate,
)


RRF_K_VALUES = (20, 60, 100)
POOL_VALUES = (20, 50, 100)
TOP_K = 20
FORBIDDEN_KEYS = {
    "question",
    "query",
    "answer",
    "evidence",
    "doc_id",
    "doc_ids",
    "chunk_id",
    "chunk_ids",
    "file",
    "file_name",
    "filename",
    "path",
    "file_path",
    "absolute_path",
    "text",
    "text_preview",
    "raw_text",
    "document_text",
    "retrieved_chunks",
    "retrieved_chunk_ids",
    "gold_evidence",
    "gold_chunk_ids",
}
FORBIDDEN_PATH_FRAGMENTS = (
    "/Users/",
    "Desktop/projects",
    ".codex/worktrees",
)
ABSOLUTE_LOCAL_PATH_RE = re.compile(r"(^|[\s:=`'\"])(?:/(?!/)\S+|[A-Za-z]:[\\/]\S+)")


@dataclass(frozen=True)
class VariantSpec:
    name: str
    retrieval_backend: str
    rrf_k: int | None
    dense_pool: int | None
    bm25_pool: int | None
    top_k: int = TOP_K

    @property
    def plan_overrides(self) -> dict[str, Any]:
        if self.retrieval_backend != "hybrid":
            return {}
        return {
            "rrf_channel_pools": {
                "dense": int(self.dense_pool or 0),
                "bm25": int(self.bm25_pool or 0),
            }
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private/local eval config YAML.")
    parser.add_argument("--index_dir", default="data/index/real100", help="Index directory.")
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Output directory. Defaults to reports/retrieval/hybrid_sweep_<UTC timestamp>.",
    )
    parser.add_argument("--cases_subset_n", type=int, default=None)
    parser.add_argument("--top_k", type=int, default=TOP_K)
    parser.add_argument("--rrf_ks", default="20,60,100")
    parser.add_argument("--dense_pools", default="20,50,100")
    parser.add_argument("--bm25_pools", default="20,50,100")
    return parser.parse_args(argv)


def _csv_ints(value: str) -> tuple[int, ...]:
    out = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not out or any(v < 1 for v in out):
        raise ValueError("sweep integer lists must contain positive values")
    return out


def resolve_specs(
    *,
    top_k: int = TOP_K,
    rrf_ks: tuple[int, ...] = RRF_K_VALUES,
    dense_pools: tuple[int, ...] = POOL_VALUES,
    bm25_pools: tuple[int, ...] = POOL_VALUES,
) -> list[VariantSpec]:
    specs = [
        VariantSpec(
            name=f"full_dense_top{top_k}",
            retrieval_backend="dense",
            rrf_k=None,
            dense_pool=None,
            bm25_pool=None,
            top_k=top_k,
        )
    ]
    for rrf_k in rrf_ks:
        for dense_pool in dense_pools:
            for bm25_pool in bm25_pools:
                specs.append(
                    VariantSpec(
                        name=(
                            "hybrid_bm25_dense_v1"
                            f"_k{rrf_k}_dense{dense_pool}_bm25{bm25_pool}"
                        ),
                        retrieval_backend="hybrid",
                        rrf_k=rrf_k,
                        dense_pool=dense_pool,
                        bm25_pool=bm25_pool,
                        top_k=top_k,
                    )
                )
    return specs


def _base_full_dense_config(config: dict[str, Any]) -> dict[str, Any]:
    for run in config.get("ablation_runs") or []:
        if isinstance(run, dict) and run.get("name") == "full_dense":
            base = normalize_run_config(run)
            break
    else:
        base = normalize_run_config(
            {
                "name": "full_dense",
                "pipeline": DEFAULT_RAG_PIPELINE_NAME,
                "metadata_first": True,
                "rerank": True,
                "verifier_retry": True,
                "retrieval_mode": "flat",
                "retrieval_backend": "dense",
                "query_expansion": "identity",
            }
        )
    base["top_k"] = TOP_K
    base["retrieval_backend"] = "dense"
    return base


def _config_for_variant(base: dict[str, Any], spec: VariantSpec) -> dict[str, Any]:
    run_config = dict(base)
    run_config["name"] = spec.name
    run_config["top_k"] = spec.top_k
    run_config["retrieval_backend"] = spec.retrieval_backend
    if spec.rrf_k is not None:
        run_config["rrf_k"] = spec.rrf_k
    return run_config


def _query_kwargs(
    run_config: dict[str, Any],
    *,
    context_entities: list[str] | None = None,
    conversation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "pipeline": str(run_config.get("pipeline") or DEFAULT_RAG_PIPELINE_NAME),
        "top_k": run_config.get("top_k"),
        "context_entities": context_entities or [],
        "metadata_first": bool(run_config.get("metadata_first", True)),
        "rerank": bool(run_config.get("rerank", True)),
        "rerank_cross_encoder": bool(run_config.get("rerank_cross_encoder", False)),
        "verifier_retry": bool(run_config.get("verifier_retry", True)),
        "retrieval_mode": str(run_config.get("retrieval_mode", "flat")),
        "retrieval_backend": str(run_config.get("retrieval_backend", "dense")),
        "prompt_profile": str(run_config.get("prompt_profile") or ""),
        "conversation_state": conversation_state,
        "rrf_k": int(run_config.get("rrf_k") or 60),
        "bm25_stopword_profile": str(run_config.get("bm25_stopword_profile", "shared")),
        "bm25_tokenizer": str(run_config.get("bm25_tokenizer", "regex")),
        "bm25_backend": str(run_config.get("bm25_backend", "okapi")),
    }


def _run_prediction(
    index: dict[str, Any],
    query: str,
    run_config: dict[str, Any],
    plan_overrides: dict[str, Any],
    *,
    context_entities: list[str] | None = None,
    conversation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kwargs = _query_kwargs(
        run_config,
        context_entities=context_entities,
        conversation_state=conversation_state,
    )
    return _run_rag_query_with_plan_overrides(
        index,
        query,
        plan_overrides=plan_overrides,
        **kwargs,
    )


def evaluate_variant(
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    run_config: dict[str, Any],
    plan_overrides: dict[str, Any],
    answer_policy: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        conversation_state: dict[str, Any] = {}
        for turn in case.get("prior_turns") or []:
            prior_prediction = _run_prediction(
                index,
                str(turn["query"]),
                run_config,
                plan_overrides,
                context_entities=turn.get("context_entities") or [],
                conversation_state=conversation_state,
            )
            conversation_state = prior_prediction.get("conversation_state") or conversation_state
        prediction = _run_prediction(
            index,
            str(case["query"]),
            run_config,
            plan_overrides,
            context_entities=case.get("context_entities") or [],
            conversation_state=conversation_state,
        )
        gold_evidence = derive_gold_evidence(case, index)
        gold_chunk_ids = [
            str(item.get("chunk_id") or "")
            for item in gold_evidence
            if isinstance(item, dict) and item.get("chunk_id")
        ]
        results.append(
            score_case(
                case,
                prediction,
                answer_policy,
                gold_chunk_ids=gold_chunk_ids,
                gold_evidence=gold_evidence,
            )
        )
    return results


def _metric_mean(results: list[dict[str, Any]], key: str) -> float | None:
    return rate([float(row[key]) for row in results if row.get(key) is not None])


def _count_rate(count: int, denominator: int) -> dict[str, Any]:
    return {
        "count": count,
        "rate": (count / denominator) if denominator else None,
        "denominator": denominator,
    }


def _less_than_one(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) < 1.0


def summarize_variant(spec: VariantSpec, results: list[dict[str, Any]]) -> dict[str, Any]:
    failure_categories = [classify_failure(row) for row in results]
    total = len(results)
    recall10_rows = [row for row in results if row.get("chunk_recall_at_10") is not None]
    citation_claim_rows = [row for row in results if row.get("citation_claim_coverage") is not None]
    citation_page_rows = [row for row in results if row.get("citation_page_coverage") is not None]
    citation_region_rows = [row for row in results if row.get("citation_region_coverage") is not None]
    latencies = [
        float(row["latency_ms"])
        for row in results
        if row.get("latency_ms") is not None
    ]
    retrieval_miss_count = sum(1 for category in failure_categories if category == "retrieval_miss")
    citation_issue_count = sum(
        1 for category in failure_categories if category == "citation_or_page_metadata_issue"
    )
    return {
        "name": spec.name,
        "parameters": {
            "retrieval_backend": spec.retrieval_backend,
            "rrf_k": spec.rrf_k,
            "dense_pool": spec.dense_pool,
            "bm25_pool": spec.bm25_pool,
            "top_k": spec.top_k,
        },
        "num_cases": total,
        "metrics": {
            "recall_at_5": _metric_mean(results, "chunk_recall_at_5"),
            "recall_at_10": _metric_mean(results, "chunk_recall_at_10"),
            "mrr_at_5": _metric_mean(results, "chunk_mrr_at_5"),
            "ndcg_at_5": _metric_mean(results, "chunk_ndcg_at_5"),
            "retrieval_miss": _count_rate(retrieval_miss_count, total),
            "citation_chunk_guardrail": {
                "chunk_recall_at_10_zero": _count_rate(
                    sum(float(row.get("chunk_recall_at_10") or 0.0) == 0.0 for row in recall10_rows),
                    len(recall10_rows),
                ),
                "citation_or_page_metadata_issue": _count_rate(citation_issue_count, total),
                "claim_citation_incomplete": _count_rate(
                    sum(_less_than_one(row.get("citation_claim_coverage")) for row in citation_claim_rows),
                    len(citation_claim_rows),
                ),
                "citation_page_metadata_incomplete": _count_rate(
                    sum(_less_than_one(row.get("citation_page_coverage")) for row in citation_page_rows),
                    len(citation_page_rows),
                ),
                "citation_region_metadata_incomplete": _count_rate(
                    sum(_less_than_one(row.get("citation_region_coverage")) for row in citation_region_rows),
                    len(citation_region_rows),
                ),
            },
            "latency_ms": {
                "p50": percentile(latencies, 0.50),
                "p95": percentile(latencies, 0.95),
                "count": len(latencies),
            },
        },
    }


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=ROOT_DIR,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
        dirty = True
    return {"git_commit": commit[:12], "git_dirty": dirty}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_output_path(path: Path) -> str:
    """Return a public-safe display path for operator logs."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.name


def assert_rendered_output_privacy_safe(text: str) -> None:
    hits = [fragment for fragment in FORBIDDEN_PATH_FRAGMENTS if fragment in text]
    if ABSOLUTE_LOCAL_PATH_RE.search(text):
        hits.append("absolute_local_path")
    if hits:
        raise ValueError("rendered output failed privacy guard: " + ", ".join(sorted(set(hits))))


def _index_fingerprint(index: dict[str, Any]) -> str:
    payload = {
        "build": index.get("build") or {},
        "embedding": index.get("embedding") or {},
        "num_documents": len(index.get("documents") or []),
        "num_chunks": len(index.get("chunks") or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def assert_aggregate_privacy_safe(obj: Any) -> None:
    hits: list[str] = []

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                if key_text.lower() in FORBIDDEN_KEYS:
                    hits.append(f"{trail}.{key_text}")
                walk(value, f"{trail}.{key_text}")
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{trail}[{idx}]")
        elif isinstance(node, str):
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                if fragment in node:
                    hits.append(f"{trail}:private_path_fragment")
                    break
            if ABSOLUTE_LOCAL_PATH_RE.search(node):
                hits.append(f"{trail}:absolute_local_path")
            if "/" in node or "\\" in node:
                hits.append(f"{trail}:path_like_value")

    walk(obj, "$")
    if hits:
        raise ValueError("aggregate artifact failed privacy guard: " + ", ".join(hits[:20]))


def build_aggregate(
    *,
    config_path: Path,
    index: dict[str, Any],
    specs: list[VariantSpec],
    variant_summaries: list[dict[str, Any]],
    num_cases: int,
) -> dict[str, Any]:
    aggregate = {
        "schema_version": 1,
        "artifact_type": "private_hybrid_retrieval_sweep_aggregate",
        "privacy_boundary": "aggregate_only_no_raw_questions_answers_evidence_ids_paths_or_filenames",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            **_git_state(),
            "eval_config_sha256": _sha256_file(config_path),
            "index_fingerprint_sha256": _index_fingerprint(index),
        },
        "sweep": {
            "baseline": specs[0].name if specs else "full_dense_top20",
            "candidate": "hybrid_bm25_dense_v1",
            "top_k": specs[0].top_k if specs else TOP_K,
            "rrf_k_values": sorted({spec.rrf_k for spec in specs if spec.rrf_k is not None}),
            "dense_pool_values": sorted({spec.dense_pool for spec in specs if spec.dense_pool is not None}),
            "bm25_pool_values": sorted({spec.bm25_pool for spec in specs if spec.bm25_pool is not None}),
            "num_variants": len(specs),
            "num_cases": num_cases,
        },
        "variants": variant_summaries,
        "known_limits": [
            "This aggregate is private-local measurement output, not a public performance claim.",
            "No weighted fusion variant is included.",
        ],
    }
    assert_aggregate_privacy_safe(aggregate)
    return aggregate


def default_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT_DIR / "reports" / "retrieval" / f"hybrid_sweep_{stamp}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    index_dir = Path(args.index_dir)
    if not index_dir.is_absolute():
        index_dir = ROOT_DIR / index_dir
    out_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    if not out_dir.is_absolute():
        out_dir = ROOT_DIR / out_dir

    config = load_config(config_path)
    cases = list(config["cases"])
    if args.cases_subset_n is not None:
        cases = cases[: args.cases_subset_n]
    index = load_index(index_dir)
    specs = resolve_specs(
        top_k=int(args.top_k),
        rrf_ks=_csv_ints(args.rrf_ks),
        dense_pools=_csv_ints(args.dense_pools),
        bm25_pools=_csv_ints(args.bm25_pools),
    )
    base = _base_full_dense_config(config)
    answer_policy = config.get("answer_policy") if isinstance(config.get("answer_policy"), dict) else {}

    variant_summaries: list[dict[str, Any]] = []
    for idx, spec in enumerate(specs, start=1):
        print(f"[sweep] {idx}/{len(specs)} {spec.name}", flush=True)
        run_config = _config_for_variant(base, spec)
        results = evaluate_variant(index, cases, run_config, spec.plan_overrides, answer_policy)
        variant_summaries.append(summarize_variant(spec, results))

    aggregate = build_aggregate(
        config_path=config_path,
        index=index,
        specs=specs,
        variant_summaries=variant_summaries,
        num_cases=len(cases),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "aggregate.json"
    out_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered_path = render_output_path(out_path)
    message = f"[OK] aggregate written: {rendered_path}"
    assert_rendered_output_privacy_safe(message)
    print(message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
