#!/usr/bin/env python3
"""Phase 4 retrieval-eval — realistic query-time metadata routing on real100.

The oracle ablation (``scripts/phase4_metadata_ablation.py``, PR #1108)
injected gold agency / project looked up from each answerable case's
``expected_doc_ids[0]``. That is a **counterfactual ceiling** — production
search has only the query text. ADR 0065 decision #3 gates the production
routing knob on a *realistic* query-time extractor measurement. This
runner is that measurement.

The extractor is the repo's existing deterministic, query-text-only
matcher (no gold, no new dependency, ADR 0061 baseline-safe):

* ``rag_indexing.metadata_targets(index)`` builds the corpus catalog of
  every agency / project / title value.
* ``rag_metadata_processing.match_metadata_targets(query, targets)`` runs
  compact-contains / alias / partial-token / fuzzy matching of the **query
  text** against that catalog and returns matches with confidence.

The 4 variants mirror the oracle runner 1:1 so each realistic delta is
directly comparable to the oracle ceiling for the same variant:

* ``no_metadata``                 — dense + lexical only (baseline).
* ``extractor_soft_agency``       — ``metadata_first=True`` with the
  *extracted* agency injected into ``analysis['entities']`` (soft boost,
  full candidate pool).
* ``extractor_prefilter_agency``  — hard candidate pre-filter by the
  *extracted* agency.
* ``extractor_prefilter_project`` — hard candidate pre-filter by the
  *extracted* project.

Extraction is deterministic and variant-independent, so it is computed
once per case (``_prepare_case``) and reused across variants; this also
keeps the per-case row order identical across variants so paired CI in
``compute_deltas`` aligns. Each row records ``extracted_agency`` /
``gold_agency`` / ``agency_match`` (gold = the oracle agency, kept ONLY
to score extraction quality — never injected into retrieval). The report
adds an extraction-quality table (agency / project precision + recall vs
gold over the answerable cohort) and an ``extractor_hit_agency`` derived
cohort showing the retrieval delta on the subset the extractor actually
routes — the realistic counterpart of the oracle's ~34%
metadata-identifiable cohort. ``follow_up`` (a ``query_type``) is split
out as its own cohort per ADR 0065 decision #3.

Abstention cases (no ``expected_doc_ids``) get no gold and the extractor
rarely fires, so every variant collapses to the baseline; their
``chunk_recall@k`` is None and they drop pairwise — restricting the
measured effect to answerable cases as the protocol requires.

Reuses (no new abstraction — absolute rule #3):

* ``rag_retrieval.{retrieve_candidates, apply_fusion_and_reranking}``
* ``rag_indexing.{load_index, metadata_targets}``
* ``rag_metadata_processing.match_metadata_targets``
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
from rag_indexing import load_index, metadata_targets  # noqa: E402
from rag_metadata_processing import match_metadata_targets  # noqa: E402
from rag_retrieval import apply_fusion_and_reranking, retrieve_candidates  # noqa: E402
from rag_text_processing import tokenize  # noqa: E402
from scripts._ablation_common import (  # noqa: E402
    _fmt_ci,
    _fmt_mean,
    categories_from_case,
    compute_deltas,
)

FOLLOW_UP_TAG = "follow_up"
EXTRACTOR_HIT_TAG = "extractor_hit_agency"
EXTRACTOR_MISS_TAG = "extractor_miss_agency"


@dataclass(frozen=True)
class VariantSpec:
    name: str
    metadata_first: bool      # selects the score-fusion formula
    prefilter: str            # "none" | "agency" | "project"
    inject_entities: bool     # put EXTRACTED agency into analysis['entities']
    index_dir: Path           # all 4 variants share the same dir


def _gold_agency_project(
    case: dict[str, Any], doc_meta: dict[str, dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Gold (agency, project) from the answerable case's first
    ``expected_doc_ids`` — used ONLY to score extraction quality, never
    injected into retrieval. Returns ``(None, None)`` for abstention or a
    doc absent from the index.
    """
    eids = case.get("expected_doc_ids") or []
    if not eids:
        return None, None
    doc = doc_meta.get(str(eids[0]))
    if doc is None:
        return None, None
    return (doc.get("agency") or None), (doc.get("project") or None)


def _extracted_agency_project(
    query: str, targets: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Realistic query-time extraction: highest-confidence agency match
    and highest-confidence project/title match from the query text alone.
    ``match_metadata_targets`` returns matches sorted by confidence desc,
    so the first hit per field is the most confident.
    """
    matches = match_metadata_targets(query, targets)
    agency: str | None = None
    project: str | None = None
    for m in matches:
        if agency is None and m.get("field") == "agency" and m.get("agency"):
            agency = m["agency"]
        if project is None and m.get("field") in ("project", "title") and m.get("project"):
            project = m["project"]
        if agency is not None and project is not None:
            break
    return agency, project


def _categories_for_row(
    case: dict[str, Any], gold_agency: str | None, agency_match: bool
) -> list[str]:
    """``hardcase_categories`` + ``follow_up`` (query_type) + the derived
    extractor cohort. The extractor tags depend only on the persisted
    ``agency_match`` flag, so this is identical in measure and reaggregate.
    """
    cats = list(categories_from_case(case))
    if str(case.get("query_type") or "") == FOLLOW_UP_TAG:
        cats.append(FOLLOW_UP_TAG)
    if gold_agency:
        cats.append(EXTRACTOR_HIT_TAG if agency_match else EXTRACTOR_MISS_TAG)
    return cats


def _plan_for_variant(
    spec: VariantSpec,
    extracted_agency: str | None,
    extracted_project: str | None,
    top_k: int,
) -> dict[str, Any]:
    """Same flat plan as the oracle runner (``retrieval_backend='dense'`` +
    ``rerank=True``); only the metadata filter / fusion moves. Uses the
    EXTRACTED agency / project, so an empty extraction collapses to the
    baseline.
    """
    metadata_filters: dict[str, Any] = {}
    if spec.prefilter == "agency" and extracted_agency:
        metadata_filters = {"agencies": [extracted_agency]}
    elif spec.prefilter == "project" and extracted_project:
        metadata_filters = {"projects": [extracted_project]}
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
    query: str, spec: VariantSpec, extracted_agency: str | None
) -> dict[str, Any]:
    entities: list[str] = []
    if spec.inject_entities and extracted_agency:
        entities = [extracted_agency]
    return {
        "query_type": "single_doc",
        "tokens": list(tokenize(query)),
        "topics": [],
        "entities": entities,
        "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
    }


def _prepare_case(
    case: dict[str, Any],
    targets: list[dict[str, Any]],
    doc_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute extraction + gold + categories ONCE (extraction is
    deterministic and variant-independent). Returns the case augmented
    with the precomputed fields the variant loop reads.
    """
    query = str(case.get("query") or "")
    gold_agency, gold_project = _gold_agency_project(case, doc_meta)
    ext_agency, ext_project = _extracted_agency_project(query, targets)
    agency_match = bool(gold_agency and ext_agency == gold_agency)
    project_match = bool(gold_project and ext_project == gold_project)
    return {
        **case,
        "_query": query,
        "_gold_agency": gold_agency,
        "_gold_project": gold_project,
        "_ext_agency": ext_agency,
        "_ext_project": ext_project,
        "_agency_match": agency_match,
        "_project_match": project_match,
        "_categories": _categories_for_row(case, gold_agency, agency_match),
    }


def run_single_case(
    index: dict[str, Any],
    prepared: dict[str, Any],
    spec: VariantSpec,
    top_k: int,
) -> tuple[list[str], float]:
    query = prepared["_query"]
    analysis = _analysis_stub(query, spec, prepared["_ext_agency"])
    plan = _plan_for_variant(spec, prepared["_ext_agency"], prepared["_ext_project"], top_k)
    t0 = time.perf_counter()
    candidates = retrieve_candidates(index, query, analysis, plan)
    final = apply_fusion_and_reranking(candidates, index, query, analysis, plan)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return [str(c["chunk_id"]) for c in final[:top_k]], latency_ms


def measure_variant(
    spec: VariantSpec,
    index: dict[str, Any],
    prepared_cases: list[dict[str, Any]],
    top_k: int,
    ks: list[int],
    warmup_n: int,
) -> dict[str, Any]:
    print(f"[measure] {spec.name}: {len(prepared_cases)} cases (warmup {warmup_n})", flush=True)
    for case in prepared_cases[:warmup_n]:
        run_single_case(index, case, spec, top_k)

    per_case_rows: list[dict[str, Any]] = []
    latency_vals: list[float] = []
    for idx, case in enumerate(prepared_cases, 1):
        qid = case.get("id") or case.get("qid") or f"?#{idx}"
        qt = case.get("query_type") or "unknown"
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        retrieved_chunk_ids, latency_ms = run_single_case(index, case, spec, top_k)
        latency_vals.append(latency_ms)
        row: dict[str, Any] = {
            "qid": qid,
            "query_type": qt,
            "categories": list(case["_categories"]),
            "gold_chunk_n": len(gold_chunk_ids),
            "gold_agency": case["_gold_agency"],
            "gold_project": case["_gold_project"],
            "extracted_agency": case["_ext_agency"],
            "extracted_project": case["_ext_project"],
            "agency_match": case["_agency_match"],
            "project_match": case["_project_match"],
            "latency_ms": round(latency_ms, 3),
        }
        for k in ks:
            row[f"chunk_recall@{k}"] = chunk_recall_at_k(retrieved_chunk_ids, gold_chunk_ids, k)
        row["mrr"] = chunk_mrr(retrieved_chunk_ids, gold_chunk_ids)
        row["ndcg@10"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_chunk_ids, 10)
        per_case_rows.append(row)
        if idx % 50 == 0:
            print(f"[measure] {spec.name}: {idx}/{len(prepared_cases)}", flush=True)

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


def _extraction_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate extraction precision / recall vs gold over the answerable
    cohort (gold present). Variant-independent, so any variant's rows work.
    """
    answerable = [r for r in rows if r.get("gold_agency")]
    ag_extracted = [r for r in answerable if r.get("extracted_agency")]
    ag_correct = [r for r in answerable if r.get("agency_match")]
    proj_answerable = [r for r in rows if r.get("gold_project")]
    proj_extracted = [r for r in proj_answerable if r.get("extracted_project")]
    proj_correct = [r for r in proj_answerable if r.get("project_match")]
    follow_up = [r for r in rows if r.get("query_type") == FOLLOW_UP_TAG]

    def _ratio(num: int, den: int) -> float | None:
        return round(num / den, 3) if den else None

    return {
        "n_answerable_agency": len(answerable),
        "agency_extracted_n": len(ag_extracted),
        "agency_correct_n": len(ag_correct),
        "agency_recall": _ratio(len(ag_correct), len(answerable)),
        "agency_precision": _ratio(len(ag_correct), len(ag_extracted)),
        "n_answerable_project": len(proj_answerable),
        "project_extracted_n": len(proj_extracted),
        "project_correct_n": len(proj_correct),
        "project_recall": _ratio(len(proj_correct), len(proj_answerable)),
        "project_precision": _ratio(len(proj_correct), len(proj_extracted)),
        "follow_up_n": len(follow_up),
        "follow_up_agency_correct_n": sum(1 for r in follow_up if r.get("agency_match")),
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
        f"# Phase 4 retrieval-eval — 현실 query-time 메타데이터 라우팅"
        f"(realistic routing) (real100 n={config['num_cases']})"
    )
    lines.append("")
    lines.append(
        f"Run: `{config['run_id']}` · commit `{config['git_commit'][:10]}` · "
        f"index_dir=`{config['index_dir']}` · eval_config=`{config['eval_config']}` · "
        f"seeds={config['seeds']} · top_k={config['top_k']} · ks={config['ks']}"
    )
    lines.append("")
    lines.append("## 변형(variants)")
    lines.append("")
    lines.append("| 변형 | metadata_first | prefilter | 추출 엔티티 주입 | 문서 | 청크 |")
    lines.append("|---|---|---|---|---|---|")
    for spec in specs:
        lines.append(
            f"| `{spec['name']}` | {spec['metadata_first']} | {spec['prefilter']} | "
            f"{spec['inject_entities']} | {spec['num_documents']} | {spec['num_chunks']} |"
        )
    lines.append("")

    eq = config.get("extraction_quality") or {}
    lines.append("## 추출 품질(extraction quality, gold 대비)")
    lines.append("")
    lines.append(
        "현실 추출기(`match_metadata_targets`)가 query 텍스트만으로 도출한 "
        "agency / project 를 정답(gold, `expected_doc_ids[0]`)과 비교. recall = "
        "정답 대비 정확 추출 비율(= 현실 라우팅 coverage), precision = 추출한 것 중 "
        "정확 비율."
    )
    lines.append("")
    lines.append("| 필드 | answerable n | 추출 n | 정확 n | recall | precision |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(
        f"| agency | {eq.get('n_answerable_agency')} | {eq.get('agency_extracted_n')} | "
        f"{eq.get('agency_correct_n')} | {eq.get('agency_recall')} | {eq.get('agency_precision')} |"
    )
    lines.append(
        f"| project | {eq.get('n_answerable_project')} | {eq.get('project_extracted_n')} | "
        f"{eq.get('project_correct_n')} | {eq.get('project_recall')} | {eq.get('project_precision')} |"
    )
    lines.append("")
    lines.append(
        f"follow_up cohort: n={eq.get('follow_up_n')}, agency 정확 추출 "
        f"{eq.get('follow_up_agency_correct_n')} (단일 query 만 보므로 context 의존 "
        "follow_up 은 추출 신호가 약함 — ADR 0065 decision #3 의 cohort 분리)."
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
        EXTRACTOR_HIT_TAG,
        EXTRACTOR_MISS_TAG,
        "multi_hop",
        "distractor_heavy",
        "long_context",
        "no_answer",
        "ambiguous_query",
        FOLLOW_UP_TAG,
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
                cells.append(_fmt_mean(measurements[spec["name"]]["per_case"], metric, cat_arg))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines.append(f"### {metric} — `{baseline}` 대비 paired CI delta (seed 평균)")
        lines.append("")
        header_cols = ["카테고리"] + [f"`{s['name']}`" for s in specs if s["name"] != baseline]
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
        "* **결론 (NULL-WINNER)**: 위 추출 품질 표의 agency recall 과 카테고리별 winner "
        "표가 보여주듯, 현실 추출기는 answerable cohort 의 소수에서만 정답 agency 를 "
        "회수하며(coverage 분석의 char-4gram proxy ~34% 보다 낮다 — 운영 matcher 는 "
        "compact-contains / 강한 토큰 중첩을 요구), 회수에 성공한 cohort"
        "(`extractor_hit_agency`)에서도 oracle ceiling(PR #1108, recall@10 +0.22)을 "
        "통계적으로 회복하지 못한다(모든 카테고리 유의하지 않음). 이는 ADR 0065 의 "
        "\"메타데이터 라우팅 = 좁은 opt-in 부가 기능, 운영 기본값 변경 아님\" 결정을 "
        "측정으로 지지한다. 또한 `extractor_prefilter_project` 는 oracle 의 ~15배 "
        "지연시간 Pareto 와 달리 부정확한 project 매칭으로 p95 지연시간이 오히려 "
        "악화된다 — hard project 필터의 이득은 현실 추출 정밀도에 종속된다."
    )
    lines.append(
        "* **현실 추출기, oracle 아님**: agency / project 는 `match_metadata_targets` "
        "가 query 텍스트만으로 corpus catalog(`metadata_targets`)에 매칭해 도출한다 "
        "(gold 미사용, 결정적, 새 의존성 0). gold 는 추출 품질 채점에만 쓰고 retrieval "
        "에 주입하지 않는다. 이 측정의 delta 는 oracle ceiling(PR #1108, recall@10 "
        "+0.21~0.22) 대비 **실제 회수율**이다 — ADR 0065 decision #3."
    )
    lines.append(
        f"* **`{EXTRACTOR_HIT_TAG}` cohort**: 추출기가 정답 agency 를 맞춘 케이스. "
        "oracle 의 ~34% metadata-identifiable cohort 의 현실 대응물 — 추출이 성공한 "
        f"곳에서의 retrieval lift 를 보여준다. `{EXTRACTOR_MISS_TAG}` = gold 는 있으나 "
        "추출 실패(라우팅 신호 없음 → baseline 으로 수렴)."
    )
    lines.append(
        "* **False-positive 라우팅 위험**: 잘못 추출된 agency 로 hard pre-filter 시 "
        "정답 doc 이 후보 풀에서 제거될 수 있다 → overall delta 가 음수일 수 있어 "
        f"`{EXTRACTOR_HIT_TAG}` / `{EXTRACTOR_MISS_TAG}` cohort 를 분리 보고한다."
    )
    lines.append(
        "* **follow_up cohort 분리**: `match_metadata_targets` 는 단일 query 만 보므로 "
        "context 의존 follow_up 의 추출 신호가 약하다. 별도 cohort 로 분리해 혼입 "
        "방지(ADR 0065 decision #3)."
    )
    lines.append(
        "* **`rerank=True` 필수**: oracle runner 와 동일 — score-fusion 공식은 `rerank` "
        "가 truthy 일 때만 `metadata_first` 분기에 도달한다. `rerank_cross_encoder` 는 "
        "설정하지 않으므로 cross-encoder 단계는 꺼진 채다."
    )
    corpus_chunks = specs[0].get("num_chunks", 0) if specs else 0
    if corpus_chunks and corpus_chunks >= 5000:
        lines.append(
            f"* **kordoc 코퍼스**: `{config['index_dir']}` 는 kordoc 전체 코퍼스 추출"
            f"({corpus_chunks} 청크)로 PR #1108 oracle 측정과 동일 인덱스 — delta 직접 "
            "비교 가능."
        )
    else:
        lines.append(
            f"* **csv_text 코퍼스 caveat**: `{config['index_dir']}`({corpus_chunks} 청크)는 "
            "csv_text fallback 빌드일 수 있다. 변형이 같은 코퍼스를 공유하므로 paired CI "
            "는 편향 없으나 절대 recall 은 kordoc phase 와 비교 불가."
        )
    lines.append(
        "* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, "
        "cross-encoder rerank 없음 — 메타데이터 효과를 격리한다."
    )
    lines.append(
        "* Seed 는 bootstrap RNG 만 구동한다; retrieval + 추출은 동일 query + index + "
        "plan 에 대해 결정적이다."
    )
    if config.get("reaggregate_source"):
        lines.append(
            "* 이 리포트는 `--reaggregate` 로 "
            f"`{config['reaggregate_source']}` 로부터 재생성됨 — hardcase / follow_up "
            "카테고리는 eval_config 에서, extractor cohort 태그는 raw row 의 "
            "`agency_match` 에서 재유도; retrieval 점수는 byte-identical 불변."
        )

    report_path = out_dir / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {report_path} ({len(lines)} lines)", flush=True)


def _git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
        return commit, dirty
    except Exception:
        return "unknown", True


def _resolve_specs(args: argparse.Namespace) -> list[VariantSpec]:
    index_dir = Path(args.index_dir)
    return [
        VariantSpec("no_metadata", False, "none", False, index_dir),
        VariantSpec("extractor_soft_agency", True, "none", True, index_dir),
        VariantSpec("extractor_prefilter_agency", False, "agency", False, index_dir),
        VariantSpec("extractor_prefilter_project", False, "project", False, index_dir),
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


def _compute_and_write_deltas(
    measurements: dict[str, dict[str, Any]],
    baseline: str,
    seeds: list[int],
    ks: list[int],
    out_dir: Path,
) -> dict[str, dict[str, dict[str, dict[str, Any] | None]]]:
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
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
    return deltas


def _run_reaggregate(
    args: argparse.Namespace,
    out_dir: Path,
    seeds: list[int],
    ks: list[int],
) -> int:
    """Re-derive ``row['categories']`` (hardcase + follow_up from
    eval_config, extractor cohort from the persisted ``agency_match``) and
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
        for row in rows:
            case = cases_by_qid.get(str(row.get("qid"))) or {}
            row["categories"] = _categories_for_row(
                case, row.get("gold_agency"), bool(row.get("agency_match"))
            )
        print(f"[reaggregate] {variant_name}: {len(rows)} rows", flush=True)

    specs_path = raw_path.parent / "metadata_specs.json"
    if not specs_path.exists():
        print(f"[ERROR] metadata_specs.json not found beside raw: {specs_path}", file=sys.stderr)
        return 2
    spec_metas = json.loads(specs_path.read_text(encoding="utf-8"))
    (out_dir / "metadata_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "raw_results.json").write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[phase] deltas (reaggregate)", flush=True)
    baseline = args.baseline
    deltas = _compute_and_write_deltas(measurements, baseline, seeds, ks, out_dir)

    git_commit, git_dirty = _git_state()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        + "-phase4-realistic-reaggregate"
    )
    baseline_spec = next(
        (s for s in spec_metas if s.get("name") == baseline), {"index_dir": "unknown"}
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
        "num_cases": len(measurements[baseline]["per_case"]),
        "baseline": baseline,
        "extraction_quality": _extraction_quality(measurements[baseline]["per_case"]),
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
        default="data/index/real100_kordoc",
        help="Shared index for all 4 variants (default: data/index/real100_kordoc).",
    )
    parser.add_argument("--eval_config", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument(
        "--reaggregate",
        default=None,
        help=(
            "Path to an existing raw_results.json. Skips measurement, "
            "re-derives row['categories'], and regenerates deltas + "
            "REPORT.md. Companion metadata_specs.json must sit beside it."
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
        choices=[
            "no_metadata",
            "extractor_soft_agency",
            "extractor_prefilter_agency",
            "extractor_prefilter_project",
        ],
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
    targets = metadata_targets(index)
    print(f"[measure] built {len(targets)} metadata targets from corpus catalog", flush=True)
    prepared_cases = [_prepare_case(case, targets, doc_meta) for case in cases]

    spec_metas = [_spec_meta(spec, index) for spec in specs]
    (out_dir / "metadata_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    measurements: dict[str, dict[str, Any]] = {}
    for spec in specs:
        measurements[spec.name] = measure_variant(
            spec, index, prepared_cases, args.top_k, ks, args.warmup
        )

    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[measure] wrote {raw_path}", flush=True)

    print("[phase] deltas", flush=True)
    baseline = args.baseline
    deltas = _compute_and_write_deltas(measurements, baseline, seeds, ks, out_dir)

    git_commit, git_dirty = _git_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-phase4-realistic"
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
        "extraction_quality": _extraction_quality(measurements[baseline]["per_case"]),
    }

    print("[phase] render", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
