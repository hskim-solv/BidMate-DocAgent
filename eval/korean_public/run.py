#!/usr/bin/env python3
"""Run the BidMate pipeline against the KorQuAD 2.x dev subset.

Wires the sample produced by ``fetch_korquad.py`` into the existing
``rag_core.run_rag_query`` pipeline so we can measure Korean-language
generalization on a publicly verifiable, out-of-domain corpus. See
[ADR 0018](../docs/adr/0018-korean-public-rag-bench.md) for the
surface boundary (this never replaces the synthetic CI or private
real-data surfaces — it is supplementary by construction).

Metrics:

* ``retrieval_recall_at_5`` — for each question, did the gold article
  appear as the ``doc_id`` of any chunk in the top-5 retrieved
  evidence? Tests retrieval alone, independent of answer rendering.
* ``answer_substring_match`` — does ``answer_text`` contain the gold
  answer string? Tests end-to-end extract → cite → render.
* ``citation_doc_precision`` — over the *answered* cases, what fraction
  of claim citations point to the gold article's ``doc_id``? Tests
  citation grounding accuracy.

Aggregates are reported with bootstrap 95% CI bands using
``eval/bootstrap.py`` (seed=17, 1000 resamples). The same seed used
by the synthetic surface so the public-CI reproducibility recipe
extends to this surface.

Usage:
  python eval/korean_public/run.py
  python eval/korean_public/run.py --pipeline agentic_full
  python eval/korean_public/run.py --sample /custom/path.json --output reports/korean_public/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.bootstrap import bootstrap_ci  # noqa: E402
from rag_core import build_index_payload_from_documents, run_rag_query  # noqa: E402

DEFAULT_SAMPLE = "data/korean_public/korquad_dev_sample.json"
DEFAULT_OUTPUT_DIR = "reports/korean_public"
DEFAULT_PIPELINE = "naive_baseline"
DEFAULT_TOP_K = 5
DEFAULT_SEED = 17
BOOTSTRAP_RESAMPLES = 1000

# KorQuAD's "title" → our "doc_id". Slugify defensively so any title
# (with spaces, parentheses, etc.) survives as a single token. We
# preserve Hangul characters; only spaces / non-word ASCII get
# normalized.
def _to_doc_id(title: str) -> str:
    cleaned = title.strip().replace(" ", "_")
    return f"korquad::{cleaned}"


def _build_documents(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap KorQuAD articles into the document schema rag_core expects."""
    documents = []
    for article in articles:
        title = str(article["title"])
        context = str(article["context"])
        doc_id = _to_doc_id(title)
        documents.append(
            {
                "doc_id": doc_id,
                "title": title,
                "agency": "",
                "project": "",
                "text": context,
                "source_path": f"data/korean_public/korquad/{doc_id}.txt",
                "metadata": {
                    "language": "ko",
                    "source": "korquad-2.1",
                },
            }
        )
    return documents


def _evidence_doc_ids(result: dict[str, Any], top_k: int) -> set[str]:
    evidence = result.get("evidence") or []
    return {str(item.get("doc_id") or "") for item in evidence[:top_k] if item.get("doc_id")}


def _citation_doc_ids(result: dict[str, Any]) -> set[str]:
    answer = result.get("answer") or {}
    doc_ids: set[str] = set()
    for claim in answer.get("claims") or []:
        for citation in claim.get("citations") or []:
            doc_id = citation.get("doc_id")
            if doc_id:
                doc_ids.add(str(doc_id))
    return doc_ids


def _normalize(text: str) -> str:
    """Whitespace + casefold normalization for answer-string comparison."""
    return " ".join(str(text or "").casefold().split())


def evaluate(
    sample: dict[str, Any],
    *,
    pipeline: str,
    top_k: int,
    embedding_backend: str = "hashing",
) -> dict[str, Any]:
    documents = _build_documents(sample["articles"])
    index = build_index_payload_from_documents(
        documents,
        source_dir="data/korean_public/korquad",
        embedding_backend=embedding_backend,
    )

    cases: list[dict[str, Any]] = []
    started_total = time.perf_counter()
    for q in sample["questions"]:
        gold_doc_id = _to_doc_id(q["title"])
        gold_answer = str(q["answer_text"])
        query = str(q["question"])

        started = time.perf_counter()
        result = run_rag_query(index, query, pipeline=pipeline, top_k=top_k)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

        retrieved = _evidence_doc_ids(result, top_k)
        cited = _citation_doc_ids(result)
        answer_text = str(result.get("answer_text") or "")

        retrieval_hit = gold_doc_id in retrieved
        substring_hit = bool(gold_answer) and _normalize(gold_answer) in _normalize(answer_text)
        # Citation precision is only defined when the model returned a
        # citation. Untouched cases (no citation) contribute None,
        # which the aggregator skips.
        citation_precision: float | None = None
        if cited:
            citation_precision = sum(1 for d in cited if d == gold_doc_id) / len(cited)

        cases.append(
            {
                "id": str(q["id"]),
                "gold_doc_id": gold_doc_id,
                "gold_answer": gold_answer,
                "retrieval_hit_top_k": retrieval_hit,
                "substring_hit": substring_hit,
                "citation_precision": citation_precision,
                "latency_ms": elapsed_ms,
                "status": (result.get("answer") or {}).get("status"),
            }
        )
    total_latency_ms = round((time.perf_counter() - started_total) * 1000, 2)

    return _aggregate(cases, total_latency_ms=total_latency_ms, pipeline=pipeline, top_k=top_k)


def _aggregate(
    cases: list[dict[str, Any]],
    *,
    total_latency_ms: float,
    pipeline: str,
    top_k: int,
) -> dict[str, Any]:
    n = len(cases)
    if not n:
        raise SystemExit("no cases evaluated")

    retrieval = [1.0 if c["retrieval_hit_top_k"] else 0.0 for c in cases]
    substring = [1.0 if c["substring_hit"] else 0.0 for c in cases]
    citation_values = [c["citation_precision"] for c in cases if c["citation_precision"] is not None]
    latencies = [c["latency_ms"] for c in cases]

    return {
        "schema_version": 1,
        "source": "KorQuAD_2.1_dev_sample",
        "pipeline": pipeline,
        "top_k": top_k,
        "num_predictions": n,
        "metrics": {
            "retrieval_recall_at_top_k": _ci_block(retrieval),
            "answer_substring_match": _ci_block(substring),
            "citation_doc_precision": _ci_block(citation_values) if citation_values else None,
            "citation_coverage": round(len(citation_values) / n, 4),
            "latency": {
                "mean_ms": round(sum(latencies) / n, 2),
                "p50_ms": round(sorted(latencies)[n // 2], 2),
                "p95_ms": round(sorted(latencies)[max(0, int(n * 0.95) - 1)], 2),
                "total_ms": total_latency_ms,
            },
        },
        "cases": cases,
    }


def _ci_block(values: list[float]) -> dict[str, Any] | None:
    band = bootstrap_ci(values, num_resamples=BOOTSTRAP_RESAMPLES, seed=DEFAULT_SEED)
    if band is None:
        return None
    return {
        "mean": round(band["mean"], 4),
        "ci_low": round(band["ci_lo"], 4),
        "ci_high": round(band["ci_hi"], 4),
        "n": int(band["n"]),
        "num_resamples": int(band["num_resamples"]),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, default=Path(DEFAULT_SAMPLE))
    ap.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT_DIR))
    ap.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    ap.add_argument(
        "--embedding-backend",
        default=os.environ.get("EMBEDDING_BACKEND", "hashing"),
        help="hashing (default, deterministic) or sentence-transformers",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.sample.exists():
        raise SystemExit(
            f"Sample not found: {args.sample}. "
            "Run `python eval/korean_public/fetch_korquad.py` first."
        )

    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    summary = evaluate(
        sample,
        pipeline=args.pipeline,
        top_k=args.top_k,
        embedding_backend=args.embedding_backend,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "eval_summary.json"
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[korean-public-eval] wrote {out_path}", file=sys.stderr)
    metrics = summary["metrics"]
    print(
        "[korean-public-eval] "
        f"retrieval_recall@{summary['top_k']}={metrics['retrieval_recall_at_top_k']['mean']:.3f} "
        f"answer_substring={metrics['answer_substring_match']['mean']:.3f} "
        f"latency_p95_ms={metrics['latency']['p95_ms']:.1f} "
        f"pipeline={summary['pipeline']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
