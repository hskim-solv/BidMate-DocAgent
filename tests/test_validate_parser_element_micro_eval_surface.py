from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_parser_element_micro_eval_surface.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("parser_element_surface_validator", VALIDATOR_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_queries() -> list[dict]:
    return [
        {
            "name": "metadata_case",
            "source": "metadata_fact",
            "query": "alpha project metadata",
            "expected_rows": [1],
            "expected_element_types": ["metadata_fact"],
        },
        {
            "name": "ocr_case",
            "source": "ocr_text",
            "query": "cover OCR kangaroo",
            "expected_rows": [1],
            "expected_element_types": ["ocr_text"],
        },
        {
            "name": "table_case",
            "source": "table",
            "query": "project table zebra",
            "expected_rows": [2],
            "expected_element_types": ["table"],
            "allow_source_sha256_alias": True,
        },
        {
            "name": "text_case",
            "source": "text_layer",
            "query": "project compliance checklist",
            "expected_rows": [3],
            "expected_element_types": ["text_layer"],
        },
    ]


def valid_aggregate() -> dict:
    validator = load_validator_module()
    queries = valid_queries()
    query_results = []
    for query in queries:
        query_results.append(
            {
                "name": query["name"],
                "source": query["source"],
                "query_hash": "a" * 12,
                "declared_expected_rows": query["expected_rows"],
                "expected_rows": query["expected_rows"],
                "allow_source_sha256_alias": bool(query.get("allow_source_sha256_alias", False)),
                "alias_rows": [22] if query.get("allow_source_sha256_alias") else [],
                "expected_element_types": query["expected_element_types"],
                "passed": True,
                "row_hit": True,
                "type_hit": True,
                "same_hit": True,
                "top1_row_hit": True,
                "top1_hit": True,
                "first_expected_row_rank": 1,
                "first_expected_type_rank": 1,
                "first_expected_hit_rank": 1,
                "reciprocal_rank": 1.0,
                "top_rows": query["expected_rows"],
                "top_element_types": query["expected_element_types"],
                "hits": [
                    {
                        "rank": 1,
                        "csv_row": query["expected_rows"][0],
                        "element_type": query["expected_element_types"][0],
                    }
                ],
            }
        )
    return {
        "schema_version": 1,
        "mode": "parser_element_stream_retrieval_smoke",
        "generated_at_utc": "20260605T000000Z",
        "run": {
            "run_id": "unit",
            "element_stream": "parser-element-stream-12doc-routing-v2-20260605T092518Z/element_stream.json",
            "embedding_backend": "hashing",
            "chunking_strategy": "section",
            "top_k": 6,
            "query_set_hash": validator.canonical_query_hash(queries),
        },
        "summary": {
            "documents": 12,
            "chunks": 4,
            "queries": 4,
            "passed": 4,
            "top1_row_hits": 4,
            "top1_hits": 4,
            "mrr": 1.0,
            "by_source": {
                "metadata_fact": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
                "ocr_text": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
                "table": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
                "text_layer": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
            },
            "by_expected_element_type": {
                "metadata_fact": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
                "ocr_text": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
                "table": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
                "text_layer": {"total": 1, "passed": 1, "top1_row_hits": 1, "top1_hits": 1},
            },
        },
        "queries": query_results,
    }


class ParserElementMicroEvalSurfaceValidatorTest(unittest.TestCase):
    def test_valid_candidate_surface(self) -> None:
        validator = load_validator_module()
        queries = valid_queries()
        result = validator.validate_surface(
            queries=queries,
            aggregate=valid_aggregate(),
            expected_query_set_hash=validator.canonical_query_hash(queries),
        )
        self.assertEqual("valid", result["status"])
        self.assertEqual("parser_element_micro_eval_v0", result["surface"])
        self.assertEqual(4, result["queries"])
        self.assertEqual(4, result["top1_hits"])
        self.assertEqual(1.0, result["mrr"])

    def test_rejects_raw_text_or_query_keys_in_aggregate(self) -> None:
        validator = load_validator_module()
        queries = valid_queries()
        aggregate = valid_aggregate()
        aggregate["queries"][0]["query"] = "raw private query"
        with self.assertRaisesRegex(ValueError, "raw/text-like keys"):
            validator.validate_surface(
                queries=queries,
                aggregate=aggregate,
                expected_query_set_hash=validator.canonical_query_hash(queries),
            )

    def test_rejects_query_set_hash_drift(self) -> None:
        validator = load_validator_module()
        with self.assertRaisesRegex(ValueError, "query set hash mismatch"):
            validator.validate_surface(
                queries=valid_queries(),
                aggregate=valid_aggregate(),
                expected_query_set_hash="0" * 64,
            )

    def test_rejects_split_row_and_type_hit(self) -> None:
        validator = load_validator_module()
        queries = valid_queries()
        aggregate = valid_aggregate()
        aggregate["queries"][0]["same_hit"] = False
        with self.assertRaisesRegex(ValueError, "row/type did not match the same hit"):
            validator.validate_surface(
                queries=queries,
                aggregate=aggregate,
                expected_query_set_hash=validator.canonical_query_hash(queries),
            )

    def test_rejects_unexpected_top1_same_hit_miss(self) -> None:
        validator = load_validator_module()
        queries = valid_queries()
        aggregate = valid_aggregate()
        aggregate["queries"][0]["top1_hit"] = False
        with self.assertRaisesRegex(ValueError, "unexpected top1 same-hit misses"):
            validator.validate_surface(
                queries=queries,
                aggregate=aggregate,
                expected_query_set_hash=validator.canonical_query_hash(queries),
            )


if __name__ == "__main__":
    unittest.main()
