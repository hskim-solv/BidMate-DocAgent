#!/usr/bin/env python3
"""Validate the parser element micro-eval surface.

This gate is intentionally narrower than a benchmark. It verifies that the
current 12-doc parser element retrieval smoke is suitable as a reviewer-facing
wiring regression artifact: fixed query-set hash, textless aggregate,
source/type coverage, and deterministic pass metrics. It does not make the
surface a parser-quality benchmark or canonical ingestion gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_parser_element_stream_retrieval_smoke import validate_smoke_queries  # noqa: E402

SURFACE_NAME = "parser_element_micro_eval_v0"
EXPECTED_QUERY_SET_HASH = "72acf426e277165258395b6c2934a13893013159c7d96c097eb4e0fe86d756c5"
EXPECTED_ELEMENT_STREAM_MARKER = "parser-element-stream-12doc-routing-v2-20260605T092518Z/element_stream.json"
KNOWN_TOP1_SAME_HIT_EXCEPTIONS = {"text_row48_compliance_table"}
MIN_SAME_HIT_MRR = 0.875
DEFAULT_QUERIES_JSON = "data/private/real100_v2/parser_element_micro_eval/parser-element-12doc-expected-facts.json"
DEFAULT_AGGREGATE_JSON = (
    "reports/parser_candidate_eval/"
    "parser-element-micro-eval-12doc-routing-v2-samehit-20260607T090346Z/"
    "retrieval_smoke.aggregate.json"
)
REQUIRED_SOURCES = {"metadata_fact", "ocr_text", "table", "text_layer"}
REQUIRED_EXPECTED_ELEMENT_TYPES = {"metadata_fact", "ocr_text", "table", "text_layer"}
FORBIDDEN_AGGREGATE_KEYS = {"query", "text", "chunk_text", "raw_text", "content"}


def normalize_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_query_hash(queries: list[dict[str, Any]]) -> str:
    canonical = json.dumps(queries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_forbidden_keys(value: Any, *, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_AGGREGATE_KEYS:
                hits.append(child_path)
            hits.extend(find_forbidden_keys(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(find_forbidden_keys(child, path=f"{path}[{index}]"))
    return hits


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_surface(
    *,
    queries: list[dict[str, Any]],
    aggregate: dict[str, Any],
    expected_query_set_hash: str = EXPECTED_QUERY_SET_HASH,
    expected_element_stream_marker: str = EXPECTED_ELEMENT_STREAM_MARKER,
) -> dict[str, Any]:
    queries = validate_smoke_queries(queries)
    query_set_hash = canonical_query_hash(queries)
    require(
        query_set_hash == expected_query_set_hash,
        f"query set hash mismatch: {query_set_hash} != {expected_query_set_hash}",
    )

    forbidden_keys = find_forbidden_keys(aggregate)
    require(
        not forbidden_keys,
        f"aggregate contains raw/text-like keys: {', '.join(forbidden_keys[:10])}",
    )

    require(aggregate.get("schema_version") == 1, "aggregate schema_version must be 1")
    require(
        aggregate.get("mode") == "parser_element_stream_retrieval_smoke",
        "aggregate mode must be parser_element_stream_retrieval_smoke",
    )
    run = aggregate.get("run") if isinstance(aggregate.get("run"), dict) else {}
    require(run.get("embedding_backend") == "hashing", "embedding_backend must be hashing")
    require(run.get("chunking_strategy") == "section", "chunking_strategy must be section")
    require(int(run.get("top_k") or 0) == 6, "top_k must be 6")
    require(
        run.get("query_set_hash") == expected_query_set_hash,
        f"aggregate query_set_hash mismatch: {run.get('query_set_hash')} != {expected_query_set_hash}",
    )
    element_stream = str(run.get("element_stream") or "")
    require(
        expected_element_stream_marker in element_stream,
        f"unexpected element_stream: {element_stream}",
    )

    summary = aggregate.get("summary") if isinstance(aggregate.get("summary"), dict) else {}
    query_count = len(queries)
    query_names = {str(item.get("name")) for item in queries}
    require(int(summary.get("documents") or 0) == 12, "documents must be 12")
    require(int(summary.get("queries") or 0) == query_count, "summary query count mismatch")
    require(int(summary.get("passed") or 0) == query_count, "all queries must pass")
    require(int(summary.get("top1_row_hits") or 0) == query_count, "all queries must be top-1 row hits")
    min_top1_same_hits = query_count - len(KNOWN_TOP1_SAME_HIT_EXCEPTIONS & query_names)
    require(
        int(summary.get("top1_hits") or 0) >= min_top1_same_hits,
        f"top1 same-hit matches must be >= {min_top1_same_hits}",
    )
    require(
        float(summary.get("mrr") or 0.0) >= MIN_SAME_HIT_MRR,
        f"same-hit MRR must be >= {MIN_SAME_HIT_MRR}",
    )

    by_source = summary.get("by_source") if isinstance(summary.get("by_source"), dict) else {}
    require(
        REQUIRED_SOURCES.issubset(set(by_source)),
        f"missing source coverage: {sorted(REQUIRED_SOURCES - set(by_source))}",
    )
    by_expected_type = (
        summary.get("by_expected_element_type")
        if isinstance(summary.get("by_expected_element_type"), dict)
        else {}
    )
    require(
        REQUIRED_EXPECTED_ELEMENT_TYPES.issubset(set(by_expected_type)),
        f"missing expected element type coverage: {sorted(REQUIRED_EXPECTED_ELEMENT_TYPES - set(by_expected_type))}",
    )

    results = aggregate.get("queries") if isinstance(aggregate.get("queries"), list) else []
    require(len(results) == query_count, "aggregate query result count mismatch")
    result_by_name = {str(item.get("name")): item for item in results if isinstance(item, dict)}
    require(query_names == set(result_by_name), "aggregate query names do not match query config")
    for item in queries:
        name = str(item.get("name"))
        result = result_by_name[name]
        require("query_hash" in result and "query" not in result, f"{name} must use query_hash only")
        require(result.get("passed") is True, f"{name} did not pass")
        require(result.get("same_hit") is True, f"{name} row/type did not match the same hit")
        require(result.get("first_expected_hit_rank"), f"{name} must report first_expected_hit_rank")
        require(result.get("top1_row_hit") is True, f"{name} is not a top-1 row hit")
        require(
            bool(result.get("allow_source_sha256_alias")) == bool(item.get("allow_source_sha256_alias", False)),
            f"{name} alias flag mismatch",
        )
        if item.get("allow_source_sha256_alias", False):
            require(isinstance(result.get("alias_rows"), list), f"{name} must report alias_rows")
    top1_same_hit_misses = {
        name
        for name, result in result_by_name.items()
        if result.get("top1_hit") is not True
    }
    unexpected_misses = top1_same_hit_misses - KNOWN_TOP1_SAME_HIT_EXCEPTIONS
    require(
        not unexpected_misses,
        f"unexpected top1 same-hit misses: {sorted(unexpected_misses)}",
    )

    return {
        "surface": SURFACE_NAME,
        "status": "valid",
        "query_set_hash": query_set_hash,
        "queries": query_count,
        "passed": summary.get("passed"),
        "top1_row_hits": summary.get("top1_row_hits"),
        "top1_hits": summary.get("top1_hits"),
        "mrr": summary.get("mrr"),
        "aggregate_mode": aggregate.get("mode"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate parser element micro-eval surface.")
    parser.add_argument("--queries-json", default=DEFAULT_QUERIES_JSON)
    parser.add_argument("--aggregate-json", default=DEFAULT_AGGREGATE_JSON)
    parser.add_argument("--expected-query-set-hash", default=EXPECTED_QUERY_SET_HASH)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        result = validate_surface(
            queries=read_json(normalize_path(args.queries_json)),
            aggregate=read_json(normalize_path(args.aggregate_json)),
            expected_query_set_hash=str(args.expected_query_set_hash),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
