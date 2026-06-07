#!/usr/bin/env python3
"""Build an eval-only RAG index from parser element stream and run retrieval smoke.

This is a harness, not canonical ingestion. It consumes the private element
stream emitted by `scripts/build_parser_element_stream.py`, maps each element to
one citation-bearing section, builds a deterministic hashing index with the
existing RAG indexer, and writes a textless retrieval aggregate.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_core import retrieve  # noqa: E402
from rag_indexing import build_index_payload_from_documents, load_index, metadata_targets, write_index  # noqa: E402
from rag_query import analyze_query, make_plan  # noqa: E402
from scripts.run_parser_candidate_eval import utc_now, write_json  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_ELEMENT_STREAM = (
    "data/private/real100_v2/parser_element_stream/"
    "parser-element-stream-12doc-routing-v2-20260605T092518Z/element_stream.json"
)
DEFAULT_TOP_K = 6
DEFAULT_CHUNK_MAX_CHARS = 4000


def normalize_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def page_label(page_span: list[int] | None) -> str:
    if not page_span:
        return "metadata"
    if len(page_span) == 2 and page_span[0] == page_span[1]:
        return f"p{int(page_span[0]):04d}"
    return f"p{int(page_span[0]):04d}-p{int(page_span[1]):04d}"


def metadata_value(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def element_to_section(element: dict[str, Any], ordinal: int) -> dict[str, Any] | None:
    text = str(element.get("text") or "").strip()
    if not text:
        return None
    element_type = str(element.get("element_type") or "unknown")
    source_role = str(element.get("source_role") or "unknown")
    page_span = element.get("page_span") if isinstance(element.get("page_span"), list) else None
    section_path = ["parser_element_stream", element_type, source_role, page_label(page_span)]
    section = {
        "heading": " / ".join(section_path),
        "section_path": section_path,
        "text": text,
    }
    if page_span:
        section["page_span"] = [int(page_span[0]), int(page_span[1])]
    bbox = element.get("bbox")
    if bbox and page_span:
        section["regions"] = [{"page_number": int(page_span[0]), "bbox": bbox}]
    # Keep element provenance in the textless chunk metadata via section path,
    # not by changing canonical chunk schema.
    section["element_id"] = element.get("element_id") or f"element-{ordinal:04d}"
    return section


def element_stream_to_documents(stream: dict[str, Any]) -> list[dict[str, Any]]:
    documents = []
    run_id = (stream.get("run") or {}).get("run_id")
    for raw_doc in stream.get("documents") or []:
        if not isinstance(raw_doc, dict):
            continue
        csv_metadata = ((raw_doc.get("metadata") or {}).get("csv") or {}) if isinstance(raw_doc.get("metadata"), dict) else {}
        csv_row = int(raw_doc.get("csv_row") or 0)
        sections = []
        for ordinal, element in enumerate(raw_doc.get("elements") or [], start=1):
            if not isinstance(element, dict):
                continue
            section = element_to_section(element, ordinal)
            if section is not None:
                sections.append(section)
        if not sections:
            continue
        source_file = str(raw_doc.get("source_file") or f"row-{csv_row:04d}")
        title = metadata_value(csv_metadata, "공고명", "사업명", "용역명") or source_file
        agency = metadata_value(csv_metadata, "수요기관", "발주기관", "기관명", "주관기관")
        project = metadata_value(csv_metadata, "사업명", "공고명", "용역명") or title
        metadata = {
            "csv_row": csv_row,
            "source_file": source_file,
            "path_pdf": raw_doc.get("path_pdf"),
            "source_sha256": raw_doc.get("source_sha256"),
            "parser_element_stream_run_id": run_id,
            **{str(key): value for key, value in csv_metadata.items()},
        }
        documents.append(
            {
                "doc_id": str(raw_doc.get("doc_id") or f"parser-element-stream-row-{csv_row:04d}"),
                "title": title,
                "agency": agency,
                "project": project,
                "metadata": metadata,
                "sections": sections,
                "source_path": str(raw_doc.get("path_pdf") or source_file),
            }
        )
    if not documents:
        raise ValueError("element stream produced no indexable documents")
    return documents


def default_smoke_queries() -> list[dict[str, Any]]:
    return [
        {
            "name": "metadata_row16_project",
            "query": "건설통합시스템 CMS 고도화",
            "expected_rows": [16],
            "expected_element_types": ["metadata_fact", "ocr_text"],
        },
        {
            "name": "ocr_row16_cover",
            "query": "Kwater 기술기획처 과업지시서",
            "expected_rows": [16],
            "expected_element_types": ["ocr_text"],
        },
        {
            "name": "table_medical_device_project",
            "query": "의료기기산업 종합정보시스템 정보관리기관 기능개선 사업 주관기관 한국보건산업진흥원",
            "expected_rows": [23, 48],
            "expected_element_types": ["table", "text_layer"],
        },
    ]


def validate_smoke_queries(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries JSON must be a non-empty list")
    seen_names: set[str] = set()
    for index, item in enumerate(queries, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"query item {index} must be an object")
        name = str(item.get("name") or "").strip()
        if name:
            if name in seen_names:
                raise ValueError(f"duplicate query name: {name}")
            seen_names.add(name)
        if not str(item.get("query") or "").strip():
            raise ValueError(f"query item {name or index} has no query")
        expected_rows = item.get("expected_rows")
        if not isinstance(expected_rows, list) or not expected_rows:
            raise ValueError(f"query item {name or index} must declare expected_rows")
        try:
            rows = [int(row) for row in expected_rows]
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"query item {name or index} has non-integer expected_rows") from exc
        if any(row <= 0 for row in rows):
            raise ValueError(f"query item {name or index} has non-positive expected_rows")
        expected_types = item.get("expected_element_types")
        if not isinstance(expected_types, list) or not expected_types:
            raise ValueError(f"query item {name or index} must declare expected_element_types")
        if any(not str(kind).strip() for kind in expected_types):
            raise ValueError(f"query item {name or index} has blank expected_element_types")
        alias_flag = item.get("allow_source_sha256_alias", False)
        if not isinstance(alias_flag, bool):
            raise ValueError(f"query item {name or index} allow_source_sha256_alias must be boolean")
    return queries


def query_set_hash(queries: list[dict[str, Any]]) -> str:
    import hashlib

    canonical = json.dumps(queries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_smoke_queries(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return validate_smoke_queries(default_smoke_queries())
    data = read_json(path)
    return validate_smoke_queries(data)


def row_from_hit(hit: dict[str, Any]) -> int | None:
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    try:
        return int(metadata.get("csv_row"))
    except Exception:  # noqa: BLE001
        return None


def element_type_from_hit(hit: dict[str, Any]) -> str:
    section_path = hit.get("section_path") or []
    if isinstance(section_path, list) and len(section_path) >= 2:
        return str(section_path[1])
    return "unknown"


def source_role_from_hit(hit: dict[str, Any]) -> str:
    section_path = hit.get("section_path") or []
    if isinstance(section_path, list) and len(section_path) >= 3:
        return str(section_path[2])
    return "unknown"


def source_sha_rows(index: dict[str, Any]) -> dict[str, set[int]]:
    rows_by_sha: dict[str, set[int]] = {}
    for doc in index.get("documents") or []:
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        source_sha = str(metadata.get("source_sha256") or "").strip()
        if not source_sha:
            continue
        try:
            csv_row = int(metadata.get("csv_row"))
        except Exception:  # noqa: BLE001
            continue
        rows_by_sha.setdefault(source_sha, set()).add(csv_row)
    return rows_by_sha


def row_source_sha(index: dict[str, Any]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for doc in index.get("documents") or []:
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        try:
            csv_row = int(metadata.get("csv_row"))
        except Exception:  # noqa: BLE001
            continue
        mapping[csv_row] = str(metadata.get("source_sha256") or "").strip()
    return mapping


def expand_expected_rows(
    expected_rows: set[int],
    *,
    index: dict[str, Any],
    allow_source_sha256_alias: bool,
) -> tuple[set[int], set[int]]:
    if not allow_source_sha256_alias or not expected_rows:
        return set(expected_rows), set()
    rows_by_sha = source_sha_rows(index)
    sha_by_row = row_source_sha(index)
    effective_rows = set(expected_rows)
    alias_rows: set[int] = set()
    for row in expected_rows:
        source_sha = sha_by_row.get(row)
        if not source_sha:
            continue
        for alias_row in rows_by_sha.get(source_sha, set()):
            effective_rows.add(alias_row)
            if alias_row not in expected_rows:
                alias_rows.add(alias_row)
    return effective_rows, alias_rows


def expected_hit_matches(hit: dict[str, Any], expected_rows: set[int], expected_types: set[str]) -> bool:
    row_matches = not expected_rows or hit.get("csv_row") in expected_rows
    type_matches = not expected_types or hit.get("element_type") in expected_types
    return bool(row_matches and type_matches)


def first_matching_hit_rank(
    hits: list[dict[str, Any]],
    expected_rows: set[int],
    expected_types: set[str],
) -> int | None:
    return next(
        (
            rank
            for rank, hit in enumerate(hits, start=1)
            if expected_hit_matches(hit, expected_rows, expected_types)
        ),
        None,
    )


def run_query_smoke(index: dict[str, Any], queries: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    targets = metadata_targets(index)
    results = []
    for item in queries:
        query = str(item.get("query") or "").strip()
        if not query:
            raise ValueError(f"query item has no query: {item!r}")
        declared_expected_rows = {int(row) for row in item.get("expected_rows") or []}
        allow_source_sha256_alias = bool(item.get("allow_source_sha256_alias", False))
        expected_rows, alias_rows = expand_expected_rows(
            declared_expected_rows,
            index=index,
            allow_source_sha256_alias=allow_source_sha256_alias,
        )
        expected_types = {str(kind) for kind in item.get("expected_element_types") or []}
        analysis = analyze_query(query, targets)
        plan = make_plan(
            analysis,
            top_k=top_k,
            metadata_first=True,
            rerank=True,
            retrieval_backend="hybrid",
            retrieval_mode="flat",
            bm25_stopword_profile="shared",
            bm25_tokenizer="regex",
            bm25_backend="okapi",
        )
        hits = retrieve(index, query, analysis, plan)[:top_k]
        compact_hits = []
        for rank, hit in enumerate(hits, start=1):
            compact_hits.append(
                {
                    "rank": rank,
                    "csv_row": row_from_hit(hit),
                    "doc_id": hit.get("doc_id"),
                    "chunk_id": hit.get("chunk_id"),
                    "element_type": element_type_from_hit(hit),
                    "source_role": source_role_from_hit(hit),
                    "section_path": hit.get("section_path"),
                    "score": hit.get("score"),
                    "score_parts": hit.get("score_parts"),
                }
            )
        top_rows = [hit["csv_row"] for hit in compact_hits if hit.get("csv_row") is not None]
        top_types = [hit["element_type"] for hit in compact_hits]
        first_expected_row_rank = next(
            (idx for idx, row in enumerate(top_rows, start=1) if row in expected_rows),
            None,
        )
        first_expected_type_rank = next(
            (idx for idx, kind in enumerate(top_types, start=1) if kind in expected_types),
            None,
        )
        row_hit = not expected_rows or any(row in expected_rows for row in top_rows)
        type_hit = not expected_types or any(kind in expected_types for kind in top_types)
        first_expected_hit_rank = first_matching_hit_rank(compact_hits, expected_rows, expected_types)
        top1_hit = bool(compact_hits and expected_hit_matches(compact_hits[0], expected_rows, expected_types))
        results.append(
            {
                "name": item.get("name") or query[:40],
                "source": item.get("source") or None,
                "query_hash": hash_query(query),
                "declared_expected_rows": sorted(declared_expected_rows),
                "expected_rows": sorted(expected_rows),
                "allow_source_sha256_alias": allow_source_sha256_alias,
                "alias_rows": sorted(alias_rows),
                "expected_element_types": sorted(expected_types),
                "passed": bool(first_expected_hit_rank),
                "row_hit": bool(row_hit),
                "type_hit": bool(type_hit),
                "same_hit": bool(first_expected_hit_rank),
                "top1_row_hit": bool(top_rows and (not expected_rows or top_rows[0] in expected_rows)),
                "top1_hit": top1_hit,
                "first_expected_row_rank": first_expected_row_rank,
                "first_expected_type_rank": first_expected_type_rank,
                "first_expected_hit_rank": first_expected_hit_rank,
                "reciprocal_rank": round(1.0 / first_expected_hit_rank, 4) if first_expected_hit_rank else 0.0,
                "top_rows": top_rows,
                "top_element_types": top_types,
                "hits": compact_hits,
            }
        )
    return results


def aggregate_query_metrics(query_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(query_results)
    if not total:
        return {
            "top1_row_hits": 0,
            "top1_hits": 0,
            "mrr": 0.0,
            "by_expected_element_type": {},
            "by_source": {},
        }
    by_type: dict[str, Counter] = {}
    by_source: dict[str, Counter] = {}
    top1_row_hits = 0
    top1_hits = 0
    reciprocal_rank_sum = 0.0
    for result in query_results:
        if result.get("top1_row_hit"):
            top1_row_hits += 1
        if result.get("top1_hit"):
            top1_hits += 1
        reciprocal_rank_sum += float(result.get("reciprocal_rank") or 0.0)
        expected_types = result.get("expected_element_types") or ["unspecified"]
        for element_type in expected_types:
            bucket = by_type.setdefault(str(element_type), Counter())
            bucket["total"] += 1
            if result.get("passed"):
                bucket["passed"] += 1
            if result.get("top1_row_hit"):
                bucket["top1_row_hits"] += 1
            if result.get("top1_hit"):
                bucket["top1_hits"] += 1
        source = str(result.get("source") or "unspecified")
        source_bucket = by_source.setdefault(source, Counter())
        source_bucket["total"] += 1
        if result.get("passed"):
            source_bucket["passed"] += 1
        if result.get("top1_row_hit"):
            source_bucket["top1_row_hits"] += 1
        if result.get("top1_hit"):
            source_bucket["top1_hits"] += 1
    return {
        "top1_row_hits": top1_row_hits,
        "top1_hits": top1_hits,
        "mrr": round(reciprocal_rank_sum / total, 4),
        "by_expected_element_type": {
            key: dict(value)
            for key, value in sorted(by_type.items())
        },
        "by_source": {
            key: dict(value)
            for key, value in sorted(by_source.items())
        },
    }


def hash_query(query: str) -> str:
    import hashlib

    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def aggregate_chunks(index: dict[str, Any]) -> dict[str, Any]:
    element_type_counts = Counter()
    source_role_counts = Counter()
    row_counts = Counter()
    for chunk in index.get("chunks") or []:
        section_path = chunk.get("section_path") or []
        if isinstance(section_path, list) and len(section_path) >= 2:
            element_type_counts[str(section_path[1])] += 1
        if isinstance(section_path, list) and len(section_path) >= 3:
            source_role_counts[str(section_path[2])] += 1
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        if metadata.get("csv_row") is not None:
            row_counts[str(metadata.get("csv_row"))] += 1
    return {
        "element_type_counts": dict(sorted(element_type_counts.items())),
        "source_role_counts": dict(sorted(source_role_counts.items())),
        "chunk_counts_by_row": dict(sorted(row_counts.items(), key=lambda pair: int(pair[0]))),
    }


def write_markdown_summary(path: Path, report: dict[str, Any]) -> None:
    summary = report.get("summary") or {}
    lines = ["# Parser Element Stream Retrieval Smoke", ""]
    lines.append(f"- Run ID: `{(report.get('run') or {}).get('run_id')}`")
    lines.append(f"- Generated: `{report.get('generated_at_utc')}`")
    lines.append(f"- Documents: `{summary.get('documents')}`")
    lines.append(f"- Chunks: `{summary.get('chunks')}`")
    lines.append(f"- Smoke queries: `{summary.get('queries')}`")
    lines.append(f"- Query set hash: `{((report.get('run') or {}).get('query_set_hash'))}`")
    lines.append(f"- Passed: `{summary.get('passed')}/{summary.get('queries')}`")
    lines.append(f"- Top-1 same-hit matches: `{summary.get('top1_hits')}/{summary.get('queries')}`")
    lines.append(f"- Top-1 row hits: `{summary.get('top1_row_hits')}/{summary.get('queries')}`")
    lines.append(f"- MRR: `{summary.get('mrr')}`")
    lines.append(f"- Element type chunks: `{summary.get('element_type_counts')}`")
    lines.append(f"- By expected type: `{summary.get('by_expected_element_type')}`")
    lines.append("")
    lines.append("This report intentionally omits raw chunk text and query text; use query hashes for audit linkage.")
    lines.append("")
    lines.append(
        "| query | source | passed | same hit | top1 hit | hit rank | row rank | type rank | declared rows | effective rows | alias rows | expected types | top rows | top types |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|")
    for result in report.get("queries") or []:
        lines.append(
            f"| `{result.get('name')}` (`{result.get('query_hash')}`) | "
            f"`{result.get('source') or ''}` | {result.get('passed')} | {result.get('same_hit')} | "
            f"{result.get('top1_hit')} | {result.get('first_expected_hit_rank')} | "
            f"{result.get('first_expected_row_rank')} | {result.get('first_expected_type_rank')} | "
            f"`{result.get('declared_expected_rows')}` | `{result.get('expected_rows')}` | "
            f"`{result.get('alias_rows')}` | `{result.get('expected_element_types')}` | "
            f"`{result.get('top_rows')}` | `{result.get('top_element_types')}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def out_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "data/private/real100_v2/parser_element_retrieval_smoke" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports/parser_candidate_eval" / run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run eval-only retrieval smoke over parser element stream.")
    parser.add_argument("--element-stream", default=DEFAULT_ELEMENT_STREAM)
    parser.add_argument("--queries-json", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--report-dir", default=None)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--chunk-max-chars", type=int, default=DEFAULT_CHUNK_MAX_CHARS)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        run_id = args.run_id or f"parser-element-retrieval-smoke-{utc_now()}"
        element_stream_path = normalize_path(args.element_stream)
        queries_path = normalize_path(args.queries_json) if args.queries_json else None
        out_dir = Path(args.out_dir) if args.out_dir else out_dir_default(run_id)
        report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(run_id)
        index_dir = out_dir / "index"
        documents = element_stream_to_documents(read_json(element_stream_path))
        payload = build_index_payload_from_documents(
            documents,
            source_dir=str(element_stream_path),
            model_name="hashing",
            embedding_backend="hashing",
            chunking_strategy="section",
            chunk_max_chars=int(args.chunk_max_chars),
            chunk_overlap_sentences=0,
            message="Eval-only parser element stream retrieval smoke index.",
        )
        write_index(payload, index_dir)
        index = load_index(index_dir)
        queries = load_smoke_queries(queries_path)
        queries_hash = query_set_hash(queries)
        query_results = run_query_smoke(index, queries, top_k=int(args.top_k))
        chunk_summary = aggregate_chunks(index)
        passed = sum(1 for result in query_results if result.get("passed"))
        query_metrics = aggregate_query_metrics(query_results)
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": "parser_element_stream_retrieval_smoke",
            "generated_at_utc": utc_now(),
            "run": {
                "run_id": run_id,
                "element_stream": str(element_stream_path),
                "queries_json": str(queries_path) if queries_path else None,
                "out_dir": str(out_dir),
                "report_dir": str(report_dir),
                "index_dir": str(index_dir),
                "embedding_backend": "hashing",
                "chunking_strategy": "section",
                "chunk_max_chars": int(args.chunk_max_chars),
                "top_k": int(args.top_k),
                "query_set_hash": queries_hash,
            },
            "summary": {
                "documents": index.get("build", {}).get("num_documents"),
                "chunks": index.get("build", {}).get("num_chunks"),
                "queries": len(query_results),
                "passed": passed,
                **query_metrics,
                **chunk_summary,
            },
            "queries": query_results,
        }
        write_json(report_dir / "retrieval_smoke.aggregate.json", report)
        write_markdown_summary(report_dir / "retrieval_smoke.md", report)
        # Private companion records the same textless smoke plus index pointer;
        # raw chunk text lives in index/index.json under data/private.
        write_json(out_dir / "retrieval_smoke.json", report)
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "index_dir": str(index_dir),
                    "report_dir": str(report_dir),
                    "documents": report["summary"]["documents"],
                    "chunks": report["summary"]["chunks"],
                    "queries": report["summary"]["queries"],
                    "passed": report["summary"]["passed"],
                },
                ensure_ascii=False,
            )
        )
        return 0 if passed == len(query_results) else 3
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
