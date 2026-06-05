"""Shape snapshot guard for the ADR 0003 answer contract (issue #322, parent #284).

ADR 0003 commits `run_rag_query` to a structured answer + citation
contract identified by `schema_version: 2`. Drift in that surface
(renaming `status` to `state`, dropping `status_reason.verified`,
turning `citations` into a flat string, ...) silently breaks every
downstream consumer — eval scoring, FastAPI demo, and aggregate summaries.

This test extracts the **contract surface only** (intentionally
excluding `analysis` / `plan` / `diagnostics` / `trace` /
`conversation_state` — those are additive observability per ADR 0013
and other extension ADRs, free to evolve without bumping the answer
contract) and asserts its shape signature matches
`tests/data/answer_contract_shape.json`.

If a future PR legitimately changes the contract: regenerate the
golden inside that PR, bump `ANSWER_SCHEMA_VERSION` in `rag_core.py`,
and update ADR 0003 (or write a superseding ADR). Doing all three
together is the entire point of the contract-bump mechanism.

To regenerate the golden:
    python3 -c "from tests.test_answer_contract_snapshot import \\
        _build_contract_shape, GOLDEN_PATH; import json; \\
        GOLDEN_PATH.write_text(json.dumps(_build_contract_shape(), \\
        indent=2, ensure_ascii=False, sort_keys=True) + chr(10))"
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from rag_core import build_index_payload, run_rag_query


ROOT_DIR = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT_DIR / "tests" / "data" / "answer_contract_shape.json"
SMOKE_FIXTURE_RAW = ROOT_DIR / "eval" / "fixtures" / "smoke_rfp" / "raw"

# Fixed query chosen because the naive_baseline pipeline yields
# status=supported with claims and evidence both non-empty, so the
# golden captures the full inner shape (citations[*], evidence[*]).
SNAPSHOT_QUERY = "기관A의 보안 통제 요구사항은?"


def _shape(value: Any) -> Any:
    """Reduce a JSON-serializable value to a structural signature.

    Scalars become their type name; dicts become {key: shape(value)}
    recursively (keys sorted on serialization); lists become
    [shape(first_element)] under the assumption of homogeneity.
    Empty lists stay empty (no inner shape can be inferred).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [_shape(value[0])]
    return type(value).__name__


def _extract_contract_subset(result: dict[str, Any]) -> dict[str, Any]:
    """Pull only the ADR 0003 contract surface from `run_rag_query` output.

    Everything outside this subset (diagnostics, plan, trace, analysis,
    conversation_state, mode) is intentionally additive observability
    that can evolve without forcing a schema_version bump.
    """
    answer = result.get("answer") or {}
    return {
        "answer": {
            "schema_version": answer.get("schema_version"),
            "status": answer.get("status"),
            "status_reason": answer.get("status_reason"),
            "query_type": answer.get("query_type"),
            "claims": answer.get("claims"),
            "summary": answer.get("summary"),
            "insufficiency": answer.get("insufficiency"),
        },
        "evidence": result.get("evidence"),
        "answer_text": result.get("answer_text"),
    }


def _build_contract_shape() -> dict[str, Any]:
    """Run the deterministic pipeline and return the shape signature.

    Used both by the test (compared to the committed golden) and by
    the regenerate-golden helper documented in this module's docstring.
    """
    index = build_index_payload(
        SMOKE_FIXTURE_RAW,
        embedding_backend="hashing",
        chunking_strategy="fixed",
    )
    result = run_rag_query(index, SNAPSHOT_QUERY, pipeline="naive_baseline")
    return _shape(_extract_contract_subset(result))


class AnswerContractShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = _build_contract_shape()
        cls.golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    def test_shape_classifies_json_scalars_deterministically(self) -> None:
        self.assertEqual(
            _shape(
                {
                    "none": None,
                    "truthy": True,
                    "integer": 7,
                    "decimal": 1.5,
                    "text": "요약",
                }
            ),
            {
                "none": "null",
                "truthy": "bool",
                "integer": "int",
                "decimal": "float",
                "text": "str",
            },
        )

    def test_shape_classifies_containers_recursively(self) -> None:
        self.assertEqual(
            _shape(
                {
                    "empty_items": [],
                    "items": [{"status": "supported", "score": 1}],
                    "metadata": {
                        "flags": [True],
                    },
                }
            ),
            {
                "empty_items": [],
                "items": [{"status": "str", "score": "int"}],
                "metadata": {
                    "flags": ["bool"],
                },
            },
        )

    def test_contract_subset_keeps_answer_shape_when_answer_missing(self) -> None:
        subset = _extract_contract_subset({
            "evidence": [{"chunk_id": "doc-1"}],
            "answer_text": "근거만 있음",
        })

        self.assertEqual(
            subset,
            {
                "answer": {
                    "schema_version": None,
                    "status": None,
                    "status_reason": None,
                    "query_type": None,
                    "claims": None,
                    "summary": None,
                    "insufficiency": None,
                },
                "evidence": [{"chunk_id": "doc-1"}],
                "answer_text": "근거만 있음",
            },
        )

    def test_contract_subset_keeps_keys_when_result_empty(self) -> None:
        subset = _extract_contract_subset({})

        self.assertEqual(
            subset,
            {
                "answer": {
                    "schema_version": None,
                    "status": None,
                    "status_reason": None,
                    "query_type": None,
                    "claims": None,
                    "summary": None,
                    "insufficiency": None,
                },
                "evidence": None,
                "answer_text": None,
            },
        )

    def test_contract_subset_excludes_additive_observability_fields(self) -> None:
        subset = _extract_contract_subset({
            "answer": {
                "schema_version": 2,
                "status": "supported",
                "status_reason": {"code": "verified"},
                "query_type": "single_doc",
                "claims": [],
                "summary": "요약",
                "insufficiency": None,
                "analysis": {"debug": "answer-local"},
            },
            "evidence": [],
            "answer_text": "요약",
            "analysis": {"debug": "top-level"},
            "plan": {"steps": []},
            "diagnostics": {"latency_ms": 1},
            "trace": ["event"],
            "conversation_state": {"turn": 1},
            "mode": "agentic_full",
        })

        self.assertEqual(
            set(subset),
            {"answer", "evidence", "answer_text"},
        )
        self.assertNotIn("analysis", subset["answer"])
        for observability_key in (
            "analysis",
            "plan",
            "diagnostics",
            "trace",
            "conversation_state",
            "mode",
        ):
            self.assertNotIn(observability_key, subset)

    def test_schema_version_is_pinned_to_two(self) -> None:
        # The literal value is not in the shape signature (shape only
        # captures the type "int"), so we re-read the answer dict
        # directly to ensure the version constant matches ADR 0003.
        index = build_index_payload(
            SMOKE_FIXTURE_RAW,
            embedding_backend="hashing",
            chunking_strategy="fixed",
        )
        result = run_rag_query(index, SNAPSHOT_QUERY, pipeline="naive_baseline")
        version = (result.get("answer") or {}).get("schema_version")
        self.assertEqual(
            version,
            2,
            f"ADR 0003 pins `schema_version` to 2; observed {version!r}. "
            f"If the contract has legitimately evolved, bump "
            f"`ANSWER_SCHEMA_VERSION` in rag_core.py, regenerate "
            f"{GOLDEN_PATH.name}, and update ADR 0003 (or write a "
            f"superseding ADR).",
        )

    def test_contract_shape_matches_golden(self) -> None:
        self.assertEqual(
            self.golden,
            self.observed,
            "ADR 0003 answer-contract shape drifted from "
            f"{GOLDEN_PATH.name}.\n\n"
            "The diff above lists every contract-surface field whose "
            "type or nesting changed. The contract is the "
            "`run_rag_query` return dict subset documented in "
            "docs/adr/0003-structured-answer-citation-contract.md — "
            "specifically `answer.{schema_version, status, "
            "status_reason, query_type, claims, summary, "
            "insufficiency}`, top-level `evidence`, and "
            "`answer_text`.\n\n"
            "If this drift is intentional:\n"
            "  1. Bump `ANSWER_SCHEMA_VERSION` in rag_core.py.\n"
            f"  2. Regenerate {GOLDEN_PATH.name} (see this module's "
            "docstring for the one-liner).\n"
            "  3. Update ADR 0003 — or write a superseding ADR "
            "explaining why the contract changed.\n\n"
            "If this drift is *not* intentional, restore the contract "
            "surface to what `tests/data/answer_contract_shape.json` "
            "describes before merging."
        )


if __name__ == "__main__":
    unittest.main()
