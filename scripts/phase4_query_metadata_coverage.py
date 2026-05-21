#!/usr/bin/env python3
"""Phase 4 query ↔ metadata coverage analysis.

The Phase 4 metadata ablation measured an oracle ceiling (recall@10
+0.22 over no-metadata) by pre-filtering on the *gold* agency / project
of each answerable case. But the oracle used metadata for ALL queries,
including ones whose text never mentions an agency or project. Production
retrieval only has the query text — this script measures how much of the
oracle's signal is actually query-derivable, i.e. the realistic ceiling.

It classifies the answerable cases into three semantic buckets:

* **metadata-identifiable** — the gold agency or project shares a
  character 4-gram with the query (whitespace-ignored, so Korean compound
  nouns like "대학재정정보시스템" match even when token-split misses them).
  Metadata routing can plausibly fire here.
* **content-query** — no agency/project signal in the query, but gold
  chunks exist (the query asks about content *inside* a project —
  features, specs, requirements). Content matching reaches these; metadata
  routing has nothing to filter on.
* **underspecified** — no metadata signal AND no derivable gold (the
  query is context-dependent or too vague for any retrieval to resolve).

Why this matters for the ADR: the oracle ceiling is a counterfactual
("if the query had stated the metadata"), not the realistic potential of
metadata routing. The realistic ceiling is bounded by the
metadata-identifiable fraction.

Reuses ``eval.scorers.chunk_metrics.derive_gold_chunk_ids`` — no new deps
(stdlib json/yaml/re/statistics only). Deterministic: same index +
eval_config → byte-identical output.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.scorers.chunk_metrics import derive_gold_chunk_ids  # noqa: E402
from rag_indexing import load_index  # noqa: E402


def _char_ngrams(text: str, n: int = 4) -> set[str]:
    """Whitespace-ignored character n-grams. Korean compound nouns are
    not whitespace-delimited, so token overlap under-counts; char n-grams
    catch substring matches like query "대학재정정보시스템" ↔ project
    "...대학재정정보시스템 고도화"."""
    squashed = re.sub(r"\s+", "", text)
    if len(squashed) < n:
        return set()
    return {squashed[i : i + n] for i in range(len(squashed) - n + 1)}


def _metadata_signal(query: str, agency: str, project: str) -> bool:
    """True if the gold agency or project shares a char-4gram with the
    query — i.e. the query carries a metadata signal a router could use."""
    q = _char_ngrams(query)
    if not q:
        return False
    if agency and (q & _char_ngrams(agency)):
        return True
    if project and (q & _char_ngrams(project)):
        return True
    return False


def analyze_coverage(
    cases: list[dict[str, Any]], index: dict[str, Any]
) -> dict[str, Any]:
    """Classify answerable cases into metadata-identifiable / content-query
    / underspecified and return aggregate stats + per-bucket counts."""
    doc_meta = {str(d.get("doc_id")): d for d in index.get("documents", [])}
    answerable = [
        c
        for c in cases
        if c.get("answerable")
        and (c.get("expected_doc_ids") or [""])[0] in doc_meta
    ]

    buckets: dict[str, list[dict[str, Any]]] = {
        "metadata_identifiable": [],
        "content_query": [],
        "underspecified": [],
    }
    gold_sizes: dict[str, list[int]] = {k: [] for k in buckets}
    query_type_by_bucket: dict[str, Counter] = {k: Counter() for k in buckets}

    for case in answerable:
        query = str(case.get("query") or "")
        doc = doc_meta[str(case["expected_doc_ids"][0])]
        agency = str(doc.get("agency") or "").strip()
        project = str(doc.get("project") or "").strip()
        gold = derive_gold_chunk_ids(case, index)
        qt = str(case.get("query_type") or "unknown")

        if _metadata_signal(query, agency, project):
            bucket = "metadata_identifiable"
        elif gold:
            bucket = "content_query"
        else:
            bucket = "underspecified"
        buckets[bucket].append(case)
        gold_sizes[bucket].append(len(gold))
        query_type_by_bucket[bucket][qt] += 1

    n = len(answerable)

    def _bucket_stats(name: str) -> dict[str, Any]:
        cases_b = buckets[name]
        sizes = gold_sizes[name]
        nonzero = [s for s in sizes if s > 0]
        return {
            "n": len(cases_b),
            "pct": round(100.0 * len(cases_b) / n, 1) if n else 0.0,
            "gold_present": sum(1 for s in sizes if s > 0),
            "gold_size_median": statistics.median(nonzero) if nonzero else 0,
            "gold_size_mean": round(statistics.mean(nonzero), 1) if nonzero else 0.0,
            "query_types": dict(query_type_by_bucket[name]),
            "sample_queries": [
                str(c.get("query") or "")[:70] for c in cases_b[:5]
            ],
        }

    return {
        "n_answerable": n,
        "buckets": {name: _bucket_stats(name) for name in buckets},
        "query_type_overall": dict(Counter(str(c.get("query_type")) for c in answerable)),
    }


def render_markdown(stats: dict[str, Any], config: dict[str, Any]) -> str:
    n = stats["n_answerable"]
    b = stats["buckets"]
    lines: list[str] = []
    lines.append("# Phase 4 — query ↔ metadata coverage 분석")
    lines.append("")
    lines.append(
        f"index_dir=`{config['index_dir']}` · eval_config=`{config['eval_config']}` · "
        f"commit `{config['git_commit'][:10]}` · n_answerable={n}"
    )
    lines.append("")
    lines.append(
        "Phase 4 oracle ceiling(모든 query 에 gold 메타데이터)과 현실 ceiling"
        "(query 에서 도출 가능한 메타데이터만) 사이의 격차를 정량화한다. 버킷은 "
        "상호 배타적이며, 우선순위는 metadata-identifiable → content-query → "
        "underspecified 이다."
    )
    lines.append("")
    lines.append("## query 의미 분류(semantic classes)")
    lines.append("")
    lines.append("| 분류 | n | % | gold 존재 | \\|gold\\| 중앙값 | \\|gold\\| 평균 |")
    lines.append("|---|---|---|---|---|---|")
    labels = {
        "metadata_identifiable": "metadata-identifiable",
        "content_query": "content-query",
        "underspecified": "underspecified",
    }
    for key, label in labels.items():
        s = b[key]
        lines.append(
            f"| {label} | {s['n']} | {s['pct']}% | "
            f"{s['gold_present']}/{s['n']} | {s['gold_size_median']} | {s['gold_size_mean']} |"
        )
    lines.append("")
    lines.append("## 해석(interpretation)")
    lines.append("")
    mi = b["metadata_identifiable"]
    cq = b["content_query"]
    us = b["underspecified"]
    lines.append(
        f"* **metadata-identifiable ({mi['pct']}%)**: gold agency/project 가 query "
        "와 char-4gram 을 공유한다. 메타데이터 routing 이 현실적으로 작동할 수 있는 "
        "cohort 이며 — 메타데이터 routing 의 현실 ceiling 은 oracle 의 전체 coverage "
        "가 아니라 이 비율로 bound 된다."
    )
    lines.append(
        f"* **content-query ({cq['pct']}%)**: agency/project 신호는 없지만 gold "
        f"청크가 존재한다 ({cq['gold_present']}/{cq['n']} 에 gold 있음). 프로젝트 "
        "*내부* 콘텐츠(기능/스펙/요구사항)를 묻는다. content matching 은 이들에 "
        "도달하나, 메타데이터 routing 은 필터링할 대상이 없다. 여기서 gold 집합이 "
        f"오히려 *더 크다*(중앙값 {cq['gold_size_median']} vs metadata-identifiable "
        f"{mi['gold_size_median']}) — 콘텐츠 답변이 더 많은 청크에 걸친다."
    )
    lines.append(
        f"* **underspecified ({us['pct']}%)**: 메타데이터 신호도 없고 도출 가능한 "
        "gold 도 없다 — context-dependent(follow_up)이거나 어떤 retrieval 로도 "
        "해결 못 할 만큼 모호하다. 미미하므로 숨은 retrieval-불가 ceiling 은 없다."
    )
    lines.append("")
    lines.append(
        "**Headline**: oracle ceiling(+0.22 recall@10)은 counterfactual 이다 — "
        "메타데이터를 전혀 언급하지 않는 "
        f"{cq['pct']}% 의 query 에도 gold 메타데이터를 썼다. 메타데이터 routing 은 "
        f"~{mi['pct']}% metadata-identifiable cohort 로 bound 된 좁은 add-on 이며; "
        "주된 retrieval lever 는 여전히 content matching(Phase 2 chunking + "
        "Phase 3 ranking mode)이다."
    )
    lines.append("")
    lines.append("## 방법(method)")
    lines.append("")
    lines.append(
        "* 메타데이터 신호에 **char-4gram overlap**(공백 무시)을 쓴다. 한국어 "
        "복합명사는 공백으로 구분되지 않아 토큰 overlap 이 과소 계산하기 때문이다"
        "(예: \"대학재정정보시스템\")."
    )
    lines.append(
        "* **gold** = `eval.scorers.chunk_metrics.derive_gold_chunk_ids` "
        "(doc_id ∈ expected_doc_ids 이고 청크 텍스트가 expected_term 을 포함)."
    )
    lines.append(
        "* 결정적(deterministic): 동일 index + eval_config → byte-identical 출력. "
        "run 헤더의 1줄 CLI 로 재현."
    )
    return "\n".join(lines) + "\n"


def _git_commit() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    import yaml

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index_dir", default="data/index/real100_kordoc")
    parser.add_argument("--eval_config", required=True)
    parser.add_argument(
        "--output_dir",
        required=True,
        help="Writes coverage.json + COVERAGE.md here.",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[coverage] loading index {args.index_dir}", flush=True)
    index = load_index(Path(args.index_dir))
    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []

    print(f"[coverage] analyzing {len(cases)} cases", flush=True)
    stats = analyze_coverage(cases, index)

    config = {
        "index_dir": args.index_dir,
        "eval_config": args.eval_config,
        "git_commit": _git_commit(),
    }
    (out_dir / "coverage.json").write_text(
        json.dumps({"config": config, "stats": stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = render_markdown(stats, config)
    (out_dir / "COVERAGE.md").write_text(md, encoding="utf-8")
    print(f"[coverage] wrote {out_dir}/coverage.json + COVERAGE.md", flush=True)
    print("", flush=True)
    print(md, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
