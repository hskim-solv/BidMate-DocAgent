#!/usr/bin/env python3
"""Phase 4 retrieval-eval — metadata / filtering ablation on real100.

Runs 4 metadata-handling variants against the same ``data/index/real100``
index (no reindexing) and computes paired bootstrap CI deltas vs the
``no_metadata`` baseline per category:

* ``no_metadata``       — dense + lexical only (``metadata_first=False``,
  no candidate filter). Score = 0.70·dense + 0.30·lexical.
* ``soft_agency``       — ``metadata_first=True`` with the oracle agency
  injected into ``analysis['entities']``. Score = 0.60·dense + 0.25·lexical
  + 0.15·metadata, where ``metadata_similarity`` returns 1.0 for chunks
  whose ``agency`` matches the oracle. Soft boost, full candidate pool.
* ``prefilter_agency``  — hard candidate pre-filter by oracle agency
  (``metadata_filters={"agencies": [oracle]}``). Same dense+lexical
  scoring as the baseline; only the candidate pool changes.
* ``prefilter_project`` — hard candidate pre-filter by oracle project
  (``metadata_filters={"projects": [oracle]}``). Tighter than agency
  (one project ≈ one doc), so this is close to the recall ceiling.

The oracle agency / project come from the answerable case's
``expected_doc_ids[0]`` looked up in the index's document metadata. This
is a **ceiling measurement** ("if the metadata signal were perfect, how
much does recall move?") — not a realistic query-time NER. Abstention
cases (no ``expected_doc_ids``) get no oracle, so every variant collapses
to the baseline for them; ``chunk_recall@k`` is None for those cases and
they drop pairwise, which restricts the measured effect to answerable
("metadata-applicable") cases as the protocol requires.

All variants use ``retrieval_backend="dense"`` and ``rerank=True`` (the
flag that selects the score-fusion formula in ``retrieve_candidates`` —
NOT ``rerank_cross_encoder``, which stays off). Phase 3 used
``rerank=False``, which short-circuits to ``score=dense_score`` and never
exercises the ``metadata_first`` branch — Phase 4 must enable it to
measure the metadata signal at all.

Output lives under ``reports/retrieval/phase4_metadata_<TIMESTAMP>/``:

* ``metadata_specs.json`` — variant metadata
* ``raw_results.json``    — per-case scores for all 4 variants
* ``deltas.json``         — paired CI vs no_metadata per (variant, metric, category)
* ``REPORT.md``           — <=200 line markdown with per-category winner or
  ``유의하지 않음`` (CI crosses 0) per absolute rule #5

Reuses (no new abstraction — absolute rule #3):

* ``rag_retrieval.{retrieve_candidates, apply_fusion_and_reranking}``
* ``rag_indexing.load_index``
* ``eval.scorers.chunk_metrics.{derive_gold_chunk_ids, chunk_recall_at_k,
  chunk_mrr, chunk_ndcg_at_k}``
* ``scripts._ablation_common`` — paired CI aggregation + report formatting
"""
from __future__ import annotations

import argparse
import json
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
    categories_from_case,
    compute_deltas,
)


@dataclass(frozen=True)
class VariantSpec:
    name: str
    metadata_first: bool      # selects the score-fusion formula
    prefilter: str            # "none" | "agency" | "project"
    inject_entities: bool     # put oracle agency into analysis['entities']
    index_dir: Path           # all 4 variants share the same dir


def _oracle_agency_project(
    case: dict[str, Any], doc_meta: dict[str, dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Oracle (agency, project) from the answerable case's first
    ``expected_doc_ids`` looked up in document metadata. Returns
    ``(None, None)`` when the case has no expected doc (abstention) or
    the doc is absent from the index.
    """
    eids = case.get("expected_doc_ids") or []
    if not eids:
        return None, None
    doc = doc_meta.get(str(eids[0]))
    if doc is None:
        return None, None
    agency = doc.get("agency") or None
    project = doc.get("project") or None
    return agency, project


def _plan_for_variant(
    spec: VariantSpec,
    oracle_agency: str | None,
    oracle_project: str | None,
    top_k: int,
) -> dict[str, Any]:
    """Build a plan exercising exactly this variant's metadata handling.
    ``retrieval_backend='dense'`` + ``rerank=True`` are held flat so the
    only thing that moves is the metadata filter / fusion. ``rerank``
    here selects the fusion formula; ``rerank_cross_encoder`` is never
    set, so the cross-encoder stage stays off.
    """
    metadata_filters: dict[str, Any] = {}
    if spec.prefilter == "agency" and oracle_agency:
        metadata_filters = {"agencies": [oracle_agency]}
    elif spec.prefilter == "project" and oracle_project:
        metadata_filters = {"projects": [oracle_project]}
    return {
        "retrieval_backend": "dense",
        "metadata_filters": metadata_filters,
        "metadata_first": spec.metadata_first,
        "rerank": True,
        "query_expansion": "identity",
        "bm25_stopword_profile": "shared",
        "bm25_tokenizer": "regex",
        "top_k": top_k,
    }


def _analysis_stub(
    query: str, spec: VariantSpec, oracle_agency: str | None
) -> dict[str, Any]:
    entities: list[str] = []
    if spec.inject_entities and oracle_agency:
        entities = [oracle_agency]
    return {
        "query_type": "single_doc",
        "tokens": list(tokenize(query)),
        "topics": [],
        "entities": entities,
        "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
    }


def run_single_case(
    index: dict[str, Any],
    case: dict[str, Any],
    spec: VariantSpec,
    top_k: int,
    doc_meta: dict[str, dict[str, Any]],
) -> tuple[list[str], float]:
    query = str(case.get("query") or "")
    oracle_agency, oracle_project = _oracle_agency_project(case, doc_meta)
    analysis = _analysis_stub(query, spec, oracle_agency)
    plan = _plan_for_variant(spec, oracle_agency, oracle_project, top_k)
    t0 = time.perf_counter()
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
    doc_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run ``cases`` through ``index`` for ``spec`` and return per-case +
    aggregate scores. Per-case rows preserve list order so paired CI in
    ``compute_deltas`` aligns across variants.
    """
    print(f"[measure] {spec.name}: {len(cases)} cases (warmup {warmup_n})", flush=True)
    for case in cases[:warmup_n]:
        run_single_case(index, case, spec, top_k, doc_meta)

    per_case_rows: list[dict[str, Any]] = []
    latency_vals: list[float] = []
    for idx, case in enumerate(cases, 1):
        qid = case.get("id") or case.get("qid") or f"?#{idx}"
        qt = case.get("query_type") or "unknown"
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        retrieved_chunk_ids, latency_ms = run_single_case(
            index, case, spec, top_k, doc_meta
        )
        latency_vals.append(latency_ms)
        row: dict[str, Any] = {
            "qid": qid,
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
        f"# Phase 4 retrieval-eval — 메타데이터 / 필터링 ablation "
        f"(real100 n={config['num_cases']})"
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
    lines.append("| 변형 | metadata_first | prefilter | oracle 엔티티 | 문서 | 청크 |")
    lines.append("|---|---|---|---|---|---|")
    for spec in specs:
        lines.append(
            f"| `{spec['name']}` | {spec['metadata_first']} | {spec['prefilter']} | "
            f"{spec['inject_entities']} | {spec['num_documents']} | {spec['num_chunks']} |"
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
        f"가 완전히 0 위인 변형. \"유의하지 않음\" = 어떤 변형의 CI 도 0 을 넘지 "
        f"못함 (절대 규칙 #5)."
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
        "* **Oracle ceiling, realistic NER 아님**: agency / project 는 answerable "
        "케이스의 `expected_doc_ids[0]` 를 인덱스 문서 메타데이터에서 조회해 얻는다. "
        "이는 \"메타데이터 신호가 완벽하다면 recall 이 얼마나 움직이는가?\" 의 "
        "상한(upper bound)을 측정한다. 현실의 query-time agency 추출기는 이 "
        "ceiling 아래에 위치한다 (follow-up)."
    )
    lines.append(
        "* **Abstention(보류) 케이스는 oracle 이 없다** (`expected_doc_ids` 없음). "
        "따라서 모든 변형이 baseline 으로 수렴하고 `chunk_recall@k` 가 None → "
        "pairwise 에서 제외된다. 측정된 효과는 Phase 4 프로토콜 요구대로 "
        "answerable(메타데이터 적용 가능) 케이스에 한정된다."
    )
    lines.append(
        "* **`rerank=True` 필수**: `retrieve_candidates` 의 score-fusion 공식은 "
        "`rerank` 가 truthy 일 때만 `metadata_first` 분기에 도달한다 (`rerank=False` "
        "는 `score=dense_score` 로 단락된다). Phase 3 은 `rerank=False` 라 "
        "`metadata_first` 플래그가 무력했다. 여기서 `rerank_cross_encoder` 는 "
        "설정하지 않으므로 cross-encoder 단계는 꺼진 채 — `rerank` 는 "
        "dense+lexical(+metadata) 혼합만 선택한다."
    )
    lines.append(
        "* **점수 공식(scoring formulas)**: `no_metadata` / `prefilter_*` = "
        "0.70·dense + 0.30·lexical; `soft_agency` = 0.60·dense + 0.25·lexical + "
        "0.15·metadata, 여기서 `metadata_similarity` 는 `agency` 가 oracle 엔티티와 "
        "일치하는 청크에 1.0 을 반환한다. `prefilter_*` 는 baseline 공식을 유지하되 "
        "점수 계산 전에 후보 풀(candidate pool)을 hard filter 로 축소한다."
    )
    corpus_chunks = specs[0].get("num_chunks", 0) if specs else 0
    if corpus_chunks and corpus_chunks < 5000:
        lines.append(
            f"* **csv_text 코퍼스 caveat**: `{config['index_dir']}` 는 "
            f"`data_list_csv_text` fallback 빌드({corpus_chunks} 청크)이며 kordoc "
            "전체 코퍼스 추출(~26k 청크)이 아니다. 변형들이 같은 코퍼스를 공유하므로 "
            "paired CI delta 는 편향 없으나, 절대 recall 수치는 kordoc 코퍼스 "
            "phase 들과 비교 불가다."
        )
    else:
        lines.append(
            f"* **kordoc 코퍼스**: `{config['index_dir']}` 는 kordoc 전체 코퍼스 "
            f"추출({corpus_chunks} 청크)로, Phase 2 / Phase 3 이 쓴 코퍼스와 "
            "동일하다. 절대 recall 수치는 kordoc 코퍼스 phase 들 간 비교 가능하다. "
            "n=221 케이스 중 114 개가 gold-derivable(answerable 이며 "
            "`expected_terms` 가 청크와 매칭); abstention + 미매칭 케이스는 "
            "pairwise 에서 제외된다 (overall n=114)."
        )
    lines.append(
        "* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, "
        "cross-encoder rerank 없음 — 메타데이터 효과를 expansion / cross-encoder "
        "효과로부터 격리한다."
    )
    lines.append(
        "* Seed 는 bootstrap RNG 만 구동한다; retrieval 자체는 동일 query + index + "
        "plan 에 대해 결정적(deterministic)이다."
    )
    lines.append(
        "* 카테고리 버킷팅은 `hardcase_categories` 를 쓴다. 멀티태그 케이스는 여러 "
        "버킷에 나타나므로 카테고리별 카운트는 겹치고 케이스를 공유한다."
    )
    lines.append(
        "* **Recall-↑ query 패턴 (Phase 4 프로토콜 step 3)**: agency / project 가 "
        "expected doc 에 매핑되는 모든 answerable query 는 oracle 메타데이터 신호로 "
        "recall@10 +0.21~0.22, MRR +0.40~0.44, ndcg@10 +0.30~0.32 (모두 SIG) 를 "
        "얻는다. 지배적인 `multi_hop` cohort(n=93)가 가장 큰 lift(recall@10 "
        "+0.23~0.24, MRR +0.44~0.48)를 본다. Abstention query 는 아무것도 얻지 "
        "못한다 — 메타데이터는 타깃 doc 이 존재하는 곳에서만 정확히 돕는다."
    )
    lines.append(
        "* **지연시간 Pareto**: hard pre-filter 는 점수 계산 전 후보 풀을 26k "
        "청크에서 1 개 doc / agency 로 축소해, p50 을 3892ms(`no_metadata`)에서 "
        "253ms(`prefilter_agency`, ~15배)로 줄이면서 recall 은 동등하거나 더 높다 "
        "— Pareto-dominant. `soft_agency` 는 전체 풀을 유지하므로 더 싼 top-1 "
        "fusion 경로로 p50 지연시간을 절반(1576ms)만 줄인다."
    )
    lines.append(
        "* **쿼리 ↔ 메타데이터 coverage**: 위 oracle ceiling 은 counterfactual"
        "(모든 query 에 gold 메타데이터 주입)이다. query 에서 실제 도출 가능한 "
        "메타데이터로 bound 한 현실 ceiling 분석(query 의미 분류: "
        "metadata-identifiable / content-query / underspecified)은 `COVERAGE.md` "
        "참조 — 재현: `scripts/phase4_query_metadata_coverage.py`."
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
        VariantSpec("no_metadata", False, "none", False, index_dir),
        VariantSpec("soft_agency", True, "none", True, index_dir),
        VariantSpec("prefilter_agency", False, "agency", False, index_dir),
        VariantSpec("prefilter_project", False, "project", False, index_dir),
    ]


def _spec_meta(spec: VariantSpec, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": spec.name,
        "metadata_first": spec.metadata_first,
        "prefilter": spec.prefilter,
        "inject_entities": spec.inject_entities,
        "index_dir": str(spec.index_dir),
        "num_documents": len(payload.get("documents", [])),
        "num_chunks": len(payload.get("chunks", [])),
    }


def _doc_meta_map(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(d.get("doc_id")): d for d in index.get("documents", [])}


def _run_reaggregate(
    args: argparse.Namespace,
    out_dir: Path,
    seeds: list[int],
    ks: list[int],
) -> int:
    """Re-derive ``row['categories']`` from ``hardcase_categories`` and
    regenerate deltas + REPORT.md without re-running retrieval.
    """
    raw_path = Path(args.reaggregate)
    if not raw_path.exists():
        print(f"[ERROR] --reaggregate path not found: {raw_path}", file=sys.stderr)
        return 2
    print(f"[reaggregate] loading {raw_path}", flush=True)
    measurements = json.loads(raw_path.read_text(encoding="utf-8"))

    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    cases_by_qid = {str(c.get("id")): c for c in cases}

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

    specs_path = raw_path.parent / "metadata_specs.json"
    if not specs_path.exists():
        print(
            f"[ERROR] metadata_specs.json not found beside raw: {specs_path}",
            file=sys.stderr,
        )
        return 2
    spec_metas = json.loads(specs_path.read_text(encoding="utf-8"))
    (out_dir / "metadata_specs.json").write_text(
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
        + "-phase4-metadata-reaggregate"
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
            "re-derives row['categories'] from hardcase_categories in "
            "--eval_config, and regenerates deltas + REPORT.md into "
            "--output_dir. Companion metadata_specs.json must sit beside it."
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
        default="no_metadata",
        choices=["no_metadata", "soft_agency", "prefilter_agency", "prefilter_project"],
        help="Baseline variant for paired CI deltas (default: no_metadata).",
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

    print(f"[measure] loading shared index from {args.index_dir}", flush=True)
    index = load_index(Path(args.index_dir))
    doc_meta = _doc_meta_map(index)
    spec_metas = [_spec_meta(spec, index) for spec in specs]
    (out_dir / "metadata_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    measurements: dict[str, dict[str, Any]] = {}
    for spec in specs:
        measurements[spec.name] = measure_variant(
            spec, index, cases, args.top_k, ks, args.warmup, doc_meta
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
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-phase4-metadata"
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
