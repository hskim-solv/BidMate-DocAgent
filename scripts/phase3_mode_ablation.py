#!/usr/bin/env python3
"""Phase 3 retrieval-eval — mode ablation on real100 (n=221).

Runs 4 retrieval-mode variants against the same ``data/index/real100``
index (no reindexing) and computes paired bootstrap CI deltas vs the
``dense`` baseline per category:

* ``dense``              — ADR 0001 baseline retrieval path
* ``hybrid_bm25_k30``    — RRF over (dense, BM25), k=30 (more top-rank weight)
* ``hybrid_bm25_k60``    — RRF over (dense, BM25), k=60 (ADR 0010 default)
* ``hybrid_bm25_k100``   — RRF over (dense, BM25), k=100 (smoother)

m3 (FlagEmbedding, separate index) and k=10 are out of scope for
Phase 3 — deferred to Phase 3.5 with rationale in the REPORT.md Notes.

Output lives under ``reports/retrieval/phase3_mode_<TIMESTAMP>/``:

* ``mode_specs.json``  — variant metadata
* ``raw_results.json`` — per-case scores for all 4 variants
* ``deltas.json``      — paired CI vs dense per (variant, metric, category)
* ``REPORT.md``        — <=200 line markdown with per-category winner or
  ``유의하지 않음`` (CI crosses 0) per absolute rule #5

Reuses (no new abstraction — absolute rule #3):

* ``rag_retrieval.retrieve_candidates`` (planner bypass — full query as
  the only sub-query, identity expansion, no rerank, ``metadata_first=False``)
* ``rag_indexing.load_index``
* ``eval.scorers.chunk_metrics.{derive_gold_chunk_ids, chunk_recall_at_k,
  chunk_mrr, chunk_ndcg_at_k}``
* ``scripts._ablation_common`` — paired CI aggregation + report formatting
  helpers extracted in PR-C (issue #953)

BM25 is built lazily on the first hybrid call via
``rag_retrieval.get_or_build_bm25`` and cached on the index dict, so
``hybrid_bm25_k30`` pays the BM25 build cost once and ``k60`` / ``k100``
are cache hits.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.scorers.chunk_metrics import (  # noqa: E402
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
    derive_gold_chunk_ids,
)
from rag_indexing import load_index  # noqa: E402
from rag_retrieval import apply_fusion_and_reranking, retrieve_candidates  # noqa: E402
from rag_text_processing import tokenize  # noqa: E402
from scripts._ablation_common import (  # noqa: E402
    _fmt_ci,
    _fmt_mean,
    anon_qid,
    categories_from_case,
    compute_deltas,
)


@dataclass(frozen=True)
class VariantSpec:
    name: str
    retrieval_backend: str  # "dense" | "hybrid"
    rrf_k: int | None       # None for dense
    index_dir: Path         # all 4 variants share the same dir


def _plan_for_variant(spec: VariantSpec, top_k: int) -> dict[str, Any]:
    """Build a plan dict that exercises exactly the variant's retrieval
    mode — everything else (expansion, rerank, metadata-first) is held
    flat across variants to isolate the mode effect.
    """
    plan: dict[str, Any] = {
        "retrieval_backend": spec.retrieval_backend,
        "metadata_filters": {},
        "metadata_first": False,
        "rerank": False,
        "query_expansion": "identity",
        "bm25_stopword_profile": "shared",
        "bm25_tokenizer": "regex",
        "top_k": top_k,
    }
    if spec.rrf_k is not None:
        plan["rrf_k"] = spec.rrf_k
    return plan


def _analysis_stub(query: str) -> dict[str, Any]:
    return {
        "query_type": "single_doc",
        "tokens": list(tokenize(query)),
        "topics": [],
        "entities": [],
        "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
    }


def run_single_case(
    index: dict[str, Any], case: dict[str, Any], spec: VariantSpec, top_k: int
) -> tuple[list[str], float]:
    query = str(case.get("query") or "")
    analysis = _analysis_stub(query)
    plan = _plan_for_variant(spec, top_k)
    t0 = time.perf_counter()
    # ``retrieve_candidates`` is the candidate-generation stage only; for
    # the hybrid backend it returns ``score=0.0`` placeholders with the
    # raw per-channel signals living in ``score_parts``. The RRF fusion +
    # final top-k truncation live in ``apply_fusion_and_reranking`` —
    # without this second call hybrid ranks degenerate to chunk_id
    # alphabetic order (every score equal so Python's stable sort falls
    # back to insertion order). The original PR #956 commit omitted the
    # fusion call, which is why all 3 ``hybrid_bm25_k{30,60,100}``
    # variants looked byte-identical in the first run — the chunk_id
    # insertion order was the same for every k. Phase 3.5 PR #966 fixed
    # the same omission in its runner; issue #983 backports the fix
    # here.
    candidates = retrieve_candidates(index, query, analysis, plan)
    final = apply_fusion_and_reranking(candidates, index, query, analysis, plan)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return [str(c["chunk_id"]) for c in final[:top_k]], latency_ms


def measure_variant(
    spec: VariantSpec,
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    top_k: int,
    ks: list[int],
    warmup_n: int,
) -> dict[str, Any]:
    """Run ``cases`` through ``index`` for ``spec`` and return per-case +
    aggregate scores. Per-case rows preserve list order so paired CI in
    ``compute_deltas`` aligns across variants.
    """
    print(f"[measure] {spec.name}: {len(cases)} cases (warmup {warmup_n})", flush=True)
    for case in cases[:warmup_n]:
        run_single_case(index, case, spec, top_k)

    per_case_rows: list[dict[str, Any]] = []
    latency_vals: list[float] = []
    for idx, case in enumerate(cases, 1):
        qid = case.get("id") or case.get("qid") or f"?#{idx}"
        qt = case.get("query_type") or "unknown"
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        retrieved_chunk_ids, latency_ms = run_single_case(index, case, spec, top_k)
        latency_vals.append(latency_ms)
        row: dict[str, Any] = {
            "qid": anon_qid(qid),
            "query_type": qt,
            "categories": categories_from_case(case),
            "gold_chunk_n": len(gold_chunk_ids),
            "latency_ms": round(latency_ms, 3),
        }
        for k in ks:
            row[f"chunk_recall@{k}"] = chunk_recall_at_k(
                retrieved_chunk_ids, gold_chunk_ids, k
            )
        row["mrr"] = chunk_mrr(retrieved_chunk_ids, gold_chunk_ids)
        row["ndcg@10"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_chunk_ids, 10)
        per_case_rows.append(row)
        if idx % 50 == 0:
            print(f"[measure] {spec.name}: {idx}/{len(cases)}", flush=True)

    return {
        "variant": spec.name,
        "per_case": per_case_rows,
        "latency_ms": {
            "p50": round(statistics.median(latency_vals), 3) if latency_vals else None,
            "p95": (
                round(statistics.quantiles(latency_vals, n=20)[-1], 3)
                if len(latency_vals) > 1
                else (round(latency_vals[0], 3) if latency_vals else None)
            ),
            "mean": round(statistics.mean(latency_vals), 3) if latency_vals else None,
            "n": len(latency_vals),
        },
    }


def render_report(
    out_dir: Path,
    specs: list[dict[str, Any]],
    measurements: dict[str, dict[str, Any]],
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]],
    config: dict[str, Any],
) -> None:
    """Write REPORT.md (<=200 lines). ``deltas`` shape:
    ``{other_name: {metric: {category: ci}}}``.
    """
    baseline = config["baseline"]
    lines: list[str] = []
    lines.append(
        f"# Phase 3 retrieval-eval — 검색 모드(mode) ablation (real100 n={config['num_cases']})"
    )
    lines.append("")
    lines.append(
        f"Run: `{config['run_id']}` · commit `{config['git_commit'][:10]}` · "
        f"index_dir=`{config['index_dir']}` · "
        f"eval_config=`{config['eval_config']}` · "
        f"seeds={config['seeds']} · top_k={config['top_k']} · ks={config['ks']}"
    )
    lines.append("")
    lines.append("## 변형(variants)")
    lines.append("")
    lines.append("| 변형 | backend | RRF k | 문서 | 청크 |")
    lines.append("|---|---|---|---|---|")
    for spec in specs:
        rrf = spec.get("rrf_k")
        rrf_str = str(rrf) if rrf is not None else "—"
        lines.append(
            f"| `{spec['name']}` | {spec['retrieval_backend']} | {rrf_str} | "
            f"{spec['num_documents']} | {spec['num_chunks']} |"
        )
    lines.append("")
    lines.append("## 지연시간(latency, ms)")
    lines.append("")
    lines.append("| 변형 | p50 | p95 | mean | n |")
    lines.append("|---|---|---|---|---|")
    for variant_name in [s["name"] for s in specs]:
        lat = measurements[variant_name]["latency_ms"]
        lines.append(
            f"| `{variant_name}` | {lat['p50']} | {lat['p95']} | {lat['mean']} | {lat['n']} |"
        )
    lines.append("")

    metrics_to_report = ["chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10"]
    categories = [
        "overall",
        "multi_hop",
        "distractor_heavy",
        "long_context",
        "no_answer",
        "ambiguous_query",
        "uncategorized",
    ]

    for metric in metrics_to_report:
        lines.append(f"## {metric}")
        lines.append("")
        header_cols = ["카테고리"] + [f"`{s['name']}`" for s in specs]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                cat_arg = None if category == "overall" else category
                cells.append(
                    _fmt_mean(measurements[spec["name"]]["per_case"], metric, cat_arg)
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines.append(f"### {metric} — `{baseline}` 대비 paired CI delta (seed 평균)")
        lines.append("")
        header_cols = ["카테고리"] + [
            f"`{s['name']}`" for s in specs if s["name"] != baseline
        ]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                if spec["name"] == baseline:
                    continue
                ci = deltas.get(spec["name"], {}).get(metric, {}).get(category)
                cells.append(_fmt_ci(ci))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## 카테고리별 winner")
    lines.append("")
    lines.append(
        f"winner = `chunk_recall@10` 평균이 가장 높으면서 `{baseline}` 대비 paired CI "
        f"가 완전히 0 위인 변형. \"유의하지 않음\" = 어떤 변형의 CI 도 0 을 넘지 못함 "
        f"(절대 규칙 #5)."
    )
    lines.append("")
    lines.append("| 카테고리 | winner | 평균 recall@10 | " + f"`{baseline}` 대비 delta CI |")
    lines.append("|---|---|---|---|")
    for category in categories:
        winner = "유의하지 않음"
        winner_mean: float | None = None
        winner_ci: dict[str, Any] | None = None
        for spec in specs:
            if spec["name"] == baseline:
                continue
            ci = deltas.get(spec["name"], {}).get("chunk_recall@10", {}).get(category)
            if ci is None:
                continue
            if ci["ci_lo"] > 0 and (winner_mean is None or ci["mean_other"] > winner_mean):
                winner = spec["name"]
                winner_mean = ci["mean_other"]
                winner_ci = ci
        mean_str = f"{winner_mean:.3f}" if winner_mean is not None else "—"
        ci_str = _fmt_ci(winner_ci) if winner_ci is not None else "—"
        lines.append(f"| {category} | `{winner}` | {mean_str} | {ci_str} |")
    lines.append("")
    lines.append("## 비고(notes)")
    lines.append("")
    lines.append(
        "* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, "
        "rerank 없음, `metadata_first=False` — 검색 모드 효과를 expansion / rerank / "
        "metadata-filter 효과로부터 격리한다."
    )
    lines.append(
        "* 4 변형 모두 `data/index/real100` 을 공유한다; `plan['retrieval_backend']` "
        "와 `plan['rrf_k']` 만 다르다. BM25 는 첫 hybrid 호출 시 "
        "`rag_retrieval.get_or_build_bm25` 로 lazy-build 되어 index dict 에 캐시되므로 "
        "`hybrid_bm25_k30` 가 BM25 build 비용을 1회 지불하고 `k60`/`k100` 은 캐시 hit 이다."
    )
    lines.append(
        "* `chunk_recall@k` 는 `expected_terms` / `expected_doc_ids` 가 없는 케이스"
        "(예: abstention(보류))에서 None 이다 — 변형 간 케이스 정렬을 보존하기 위해 "
        "pairwise 에서 제외된다."
    )
    lines.append(
        "* Seed 는 bootstrap RNG 만 구동한다; retrieval 자체는 동일 "
        "query+index+backend+rrf_k 에 대해 결정적(deterministic)이다 (dense + BM25 모두)."
    )
    lines.append(
        "* 카테고리 버킷팅은 `hardcase_categories`(의미 난이도 태그)를 쓴다. 멀티태그 "
        "케이스는 여러 버킷에 나타나므로 카테고리별 카운트는 겹치고 paired CI 가 "
        "케이스를 공유한다."
    )
    lines.append(
        f"* `{baseline}` 이 delta baseline 인 이유: ADR 0010 의 `hybrid` 채택 근거가 "
        "질문을 \"hybrid 가 실제로 dense 보다 나은가?\" 로 프레이밍했기 때문이다. "
        "0 위 delta 는 hybrid 변형에, 0 아래는 dense 에 유리하다."
    )
    lines.append(
        "* m3 (FlagEmbedding 3-channel RRF)는 Phase 3 **범위 외**다 — 별도 인덱스 "
        "빌드(`build_m3_index`)가 필요하므로 Phase 3.5 로 미뤄 Phase 3 측정을 좁게 "
        "유지한다 (mode ↔ index 분리)."
    )
    lines.append(
        "* k=10 / k=200 은 Phase 3 **범위 외**다 — k∈{30,60,100} 이 변형 수를 부풀리지 "
        "않으면서 ADR 0010 의 k=60 default 를 감싼다. k=30 vs k=100 이 깔끔한 gradient "
        "를 보이면 후속에서 더 좁은/넓은 k 를 추가할 수 있다."
    )
    if config.get("reaggregate_source"):
        lines.append(
            "* 이 리포트는 `--reaggregate` 로 "
            f"`{config['reaggregate_source']}` 로부터 재생성됨 — 카테고리는 "
            "`hardcase_categories` 에서 재유도; `raw_results.json` 의 retrieval "
            "점수는 주입된 `categories` 필드를 제외하면 byte-for-byte 불변."
        )

    report_path = out_dir / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {report_path} ({len(lines)} lines)", flush=True)


def _git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        )
        return commit, dirty
    except Exception:
        return "unknown", True


def _resolve_specs(args: argparse.Namespace) -> list[VariantSpec]:
    index_dir = Path(args.index_dir)
    return [
        VariantSpec(name="dense", retrieval_backend="dense", rrf_k=None, index_dir=index_dir),
        VariantSpec(name="hybrid_bm25_k30", retrieval_backend="hybrid", rrf_k=30, index_dir=index_dir),
        VariantSpec(name="hybrid_bm25_k60", retrieval_backend="hybrid", rrf_k=60, index_dir=index_dir),
        VariantSpec(name="hybrid_bm25_k100", retrieval_backend="hybrid", rrf_k=100, index_dir=index_dir),
    ]


def _spec_meta(
    spec: VariantSpec, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": spec.name,
        "retrieval_backend": spec.retrieval_backend,
        "rrf_k": spec.rrf_k,
        "index_dir": str(spec.index_dir),
        "num_documents": len(payload.get("documents", [])),
        "num_chunks": len(payload.get("chunks", [])),
    }


def _run_reaggregate(
    args: argparse.Namespace,
    out_dir: Path,
    seeds: list[int],
    ks: list[int],
) -> int:
    """Re-derive ``row['categories']`` from ``hardcase_categories`` and
    regenerate deltas + REPORT.md without re-running retrieval. Useful
    when the categorization schema changes between runs but raw scores
    are still trustworthy.
    """
    raw_path = Path(args.reaggregate)
    if not raw_path.exists():
        print(f"[ERROR] --reaggregate path not found: {raw_path}", file=sys.stderr)
        return 2
    print(f"[reaggregate] loading {raw_path}", flush=True)
    measurements = json.loads(raw_path.read_text(encoding="utf-8"))

    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    cases_by_qid = {}
    for _c in cases:
        _cid = str(_c.get("id"))
        # Tolerant join: committed real-eval artifacts carry anonymized
        # qids (anon_qid maps Hangul ids -> real_<hash>); synthetic /
        # legacy files carry the raw id. Map both so re-aggregation
        # works regardless of which the persisted row used.
        cases_by_qid[_cid] = _c
        cases_by_qid[anon_qid(_cid)] = _c

    for variant_name, m in measurements.items():
        rows = m.get("per_case", []) or []
        untagged = 0
        for row in rows:
            case = cases_by_qid.get(str(row.get("qid")))
            tags = categories_from_case(case or {})
            row["categories"] = tags
            if tags == ["uncategorized"]:
                untagged += 1
        print(
            f"[reaggregate] {variant_name}: {len(rows)} rows, {untagged} uncategorized",
            flush=True,
        )

    specs_path = raw_path.parent / "mode_specs.json"
    if not specs_path.exists():
        print(
            f"[ERROR] mode_specs.json not found beside raw: {specs_path}",
            file=sys.stderr,
        )
        return 2
    spec_metas = json.loads(specs_path.read_text(encoding="utf-8"))
    (out_dir / "mode_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "raw_results.json").write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[phase] deltas (reaggregate)", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    baseline = args.baseline
    baseline_rows = measurements[baseline]["per_case"]
    for variant_name in measurements:
        if variant_name == baseline:
            continue
        deltas[variant_name] = {
            metric: compute_deltas(
                baseline_rows, measurements[variant_name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        + "-phase3-mode-reaggregate"
    )
    baseline_spec = next(
        (s for s in spec_metas if s.get("name") == baseline),
        {"index_dir": "unknown"},
    )
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir": baseline_spec.get("index_dir", "unknown"),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(baseline_rows),
        "baseline": baseline,
        "reaggregate_source": str(raw_path),
    }
    print("[phase] render (reaggregate)", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index_dir",
        default="data/index/real100",
        help="Shared index for all 4 variants (default: data/index/real100).",
    )
    parser.add_argument("--eval_config", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument(
        "--reaggregate",
        default=None,
        help=(
            "Path to an existing raw_results.json. Skips measurement, "
            "re-derives row['categories'] from hardcase_categories in --eval_config, "
            "and regenerates deltas + REPORT.md into --output_dir. "
            "Companion mode_specs.json must sit beside raw_results.json."
        ),
    )
    parser.add_argument("--seeds", default="17,23,29")
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--ks", default="5,10")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument(
        "--cases_subset_n",
        type=int,
        default=None,
        help="Truncate to first N cases (for pre-flight dry-runs).",
    )
    parser.add_argument(
        "--baseline",
        default="dense",
        choices=["dense", "hybrid_bm25_k30", "hybrid_bm25_k60", "hybrid_bm25_k100"],
        help="Baseline variant for paired CI deltas (default: dense).",
    )
    args = parser.parse_args(argv)

    seeds = [int(x) for x in args.seeds.split(",")]
    ks = [int(x) for x in args.ks.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.reaggregate:
        return _run_reaggregate(args, out_dir, seeds, ks)

    specs = _resolve_specs(args)

    print("[phase] measure", flush=True)
    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    if args.cases_subset_n is not None:
        cases = cases[: args.cases_subset_n]
        print(f"[measure] truncated to first {len(cases)} cases", flush=True)
    print(f"[measure] {len(cases)} cases", flush=True)

    # All variants share the same index; load once and reuse so the
    # BM25 cache populated by the first hybrid variant is hit by the
    # remaining ones.
    print(f"[measure] loading shared index from {args.index_dir}", flush=True)
    index = load_index(Path(args.index_dir))
    spec_metas = [_spec_meta(spec, index) for spec in specs]
    (out_dir / "mode_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    measurements: dict[str, dict[str, Any]] = {}
    for spec in specs:
        measurements[spec.name] = measure_variant(
            spec, index, cases, args.top_k, ks, args.warmup
        )

    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[measure] wrote {raw_path}", flush=True)

    print("[phase] deltas", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    baseline = args.baseline
    baseline_rows = measurements[baseline]["per_case"]
    for spec in specs:
        if spec.name == baseline:
            continue
        deltas[spec.name] = {
            metric: compute_deltas(
                baseline_rows, measurements[spec.name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-phase3-mode"
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir": str(specs[0].index_dir),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(cases),
        "baseline": baseline,
    }

    print("[phase] render", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
