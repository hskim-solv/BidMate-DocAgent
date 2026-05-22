"""Tests for trace schema v2 (issue #967, ADR 0001 invariant preserved).

Covers:
- ``TRACE_SCHEMA_VERSION = 2`` baked into ``build_result_trace`` output
- ``synthesis_llm_call = None`` when ``synthesis_meta`` is absent or env=off
- ``synthesis_llm_call`` populated when ``synthesis_meta`` carries
  ``user_prompt_text`` + ``completion_text`` (env=on simulated by passing them)
- Two calls with identical inputs produce byte-identical traces (ADR 0001
  run-to-run determinism — schema bump is deterministic per-config, not
  per-config-version)

These tests do NOT exercise the real anthropic/openai backends — they
operate on ``build_result_trace`` directly with synthetic inputs, which is
the surgical scope of issue #967 (the LLM call sites only *populate* the
synthesis_meta dict; ``build_result_trace`` is the consumer).
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rag_synthesis  # noqa: E402
from rag_synthesis import synthesize_answer  # noqa: E402
from rag_tracing import (  # noqa: E402
    REDACTED_LIST_PLACEHOLDER,
    TRACE_SCHEMA_VERSION,
    build_result_trace,
    redact_trace,
)


def _minimal_trace_args(answer_status: str = "ok") -> dict:
    """Build the minimum positional kwargs for build_result_trace."""
    return dict(
        original_query="기관 A 의 사업기간은?",
        resolved_query="기관 A 의 사업기간은?",
        analysis={"query_type": "single_doc"},
        plan={"top_k": 4, "pipeline": "agentic_full"},
        metadata_resolution={"active_doc_ids": ["doc_1"]},
        context_resolution={"rewritten": False},
        stage_sequence=["base"],
        stage_attempts=[
            {"stage": "base", "verification_reasons": [], "metadata_filters": {}}
        ],
        answer={
            "schema_version": 2,
            "status": answer_status,
            "status_reason": {},
            "query_type": "single_doc",
            "claims": [{"text": "사업기간은 12개월", "citations": [{"chunk_id": "c1"}]}],
        },
    )


class TestSchemaVersionBumped(unittest.TestCase):
    def test_schema_version_constant_is_2(self):
        self.assertEqual(TRACE_SCHEMA_VERSION, 2)

    def test_trace_carries_schema_version_2(self):
        trace = build_result_trace(**_minimal_trace_args())
        self.assertEqual(trace["schema_version"], 2)


class TestSynthesisLlmCallEnvOff(unittest.TestCase):
    def test_no_synthesis_meta_yields_null_llm_call(self):
        trace = build_result_trace(**_minimal_trace_args())
        self.assertIn("synthesis_llm_call", trace)
        self.assertIsNone(trace["synthesis_llm_call"])

    def test_synthesis_meta_without_prompt_text_yields_null(self):
        # Simulates env=off: synthesis ran, captured tokens, but did NOT
        # capture full prompt/completion. Trace v2 surfaces None — the
        # presence of tokens alone does not promote the case to "llm_call
        # captured".
        meta_without_full_io = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
        }
        trace = build_result_trace(
            **_minimal_trace_args(),
            synthesis_meta=meta_without_full_io,
        )
        self.assertIsNone(trace["synthesis_llm_call"])

    def test_non_dict_synthesis_meta_is_safe(self):
        trace = build_result_trace(
            **_minimal_trace_args(),
            synthesis_meta="not-a-dict",  # type: ignore[arg-type]
        )
        self.assertIsNone(trace["synthesis_llm_call"])


class TestSynthesisLlmCallEnvOn(unittest.TestCase):
    def test_synthesis_meta_with_prompt_text_yields_payload(self):
        # Simulates env=on: synthesis backend captured prompt + completion
        # in the returned dict, top-level synthesize_summary copied them to
        # meta. build_result_trace surfaces them as synthesis_llm_call.
        meta_with_full_io = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
            "user_prompt_text": "Query: 기관 A 사업기간\n\nEvidence: ...",
            "completion_text": '{"summary": "12개월", "used_chunk_ids": ["c1"]}',
        }
        trace = build_result_trace(
            **_minimal_trace_args(),
            synthesis_meta=meta_with_full_io,
        )
        llm_call = trace["synthesis_llm_call"]
        self.assertIsNotNone(llm_call)
        self.assertEqual(llm_call["backend"], "anthropic")
        self.assertEqual(llm_call["model"], "claude-sonnet-4-6")
        self.assertEqual(llm_call["tokens_in"], 1200)
        self.assertEqual(llm_call["tokens_out"], 350)
        self.assertEqual(llm_call["user_prompt_text"], "Query: 기관 A 사업기간\n\nEvidence: ...")
        self.assertEqual(llm_call["completion_text"], '{"summary": "12개월", "used_chunk_ids": ["c1"]}')


class TestRunToRunDeterminism(unittest.TestCase):
    """ADR 0001 invariant — two runs of build_result_trace with identical
    inputs produce byte-identical JSON output. Schema bump 1→2 does NOT
    break this; it only shifts the absolute value of schema_version."""

    def test_byte_identical_traces(self):
        args = _minimal_trace_args()
        meta = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
            "user_prompt_text": "same prompt",
            "completion_text": "same completion",
        }
        t1 = build_result_trace(**args, synthesis_meta=meta)
        t2 = build_result_trace(**args, synthesis_meta=meta)
        self.assertEqual(
            json.dumps(t1, sort_keys=True, ensure_ascii=False),
            json.dumps(t2, sort_keys=True, ensure_ascii=False),
        )


_PRIVATE_DOC_ID = "doc_private_42"
_PRIVATE_AGENCY = "비밀조달청"


def _trace_with_synthesis_io() -> dict:
    """A trace whose synthesis_llm_call carries a private doc_id + agency in
    the freeform prompt/completion text (GAP 1, issue #1352)."""
    meta = {
        "backend": "anthropic",
        "model": "claude-sonnet-4-6",
        "tokens_in": 1200,
        "tokens_out": 350,
        "user_prompt_text": (
            f"Query: 사업기간\n\n[{_PRIVATE_DOC_ID}#c1] "
            f"doc={_PRIVATE_DOC_ID} agency={_PRIVATE_AGENCY}\n근거 본문 텍스트"
        ),
        "completion_text": (
            f'{{"summary": "12개월", "used_chunk_ids": ["{_PRIVATE_DOC_ID}#c1"]}}'
        ),
    }
    return build_result_trace(**_minimal_trace_args(), synthesis_meta=meta)


class TestRedactSynthesisLlmCall(unittest.TestCase):
    """GAP 1 — redact_trace must mask synthesis_llm_call full I/O, the same
    ADR 0005 boundary class as the #1144 leak."""

    def test_redact_all_strips_private_doc_id_and_agency(self):
        trace = _trace_with_synthesis_io()
        # sanity: unredacted trace leaks the private values
        self.assertIn(_PRIVATE_DOC_ID, json.dumps(trace, ensure_ascii=False))

        redacted = redact_trace(
            trace, include_doc_ids=False, include_entities=False
        )
        blob = json.dumps(redacted, ensure_ascii=False)
        self.assertNotIn(_PRIVATE_DOC_ID, blob)
        self.assertNotIn(_PRIVATE_AGENCY, blob)
        self.assertNotIn("근거 본문 텍스트", blob)
        # structural metadata is preserved for reviewers
        call = redacted["synthesis_llm_call"]
        self.assertEqual(call["backend"], "anthropic")
        self.assertEqual(call["model"], "claude-sonnet-4-6")
        self.assertEqual(call["tokens_in"], 1200)
        self.assertEqual(call["user_prompt_text"], REDACTED_LIST_PLACEHOLDER)
        self.assertEqual(call["completion_text"], REDACTED_LIST_PLACEHOLDER)

    def test_doc_ids_only_redaction_still_masks_io(self):
        # prompt embeds doc IDs verbatim, so masking doc IDs alone must drop
        # the freeform text (it cannot be selectively scrubbed)
        redacted = redact_trace(
            _trace_with_synthesis_io(),
            include_doc_ids=False,
            include_entities=True,
        )
        blob = json.dumps(redacted, ensure_ascii=False)
        self.assertNotIn(_PRIVATE_DOC_ID, blob)

    def test_entities_only_redaction_still_masks_io(self):
        redacted = redact_trace(
            _trace_with_synthesis_io(),
            include_doc_ids=True,
            include_entities=False,
        )
        blob = json.dumps(redacted, ensure_ascii=False)
        self.assertNotIn(_PRIVATE_AGENCY, blob)

    def test_no_redaction_preserves_io(self):
        redacted = redact_trace(
            _trace_with_synthesis_io(),
            include_doc_ids=True,
            include_entities=True,
        )
        call = redacted["synthesis_llm_call"]
        self.assertIn(_PRIVATE_DOC_ID, call["user_prompt_text"])
        self.assertNotEqual(call["completion_text"], REDACTED_LIST_PLACEHOLDER)

    def test_null_synthesis_llm_call_is_safe(self):
        trace = build_result_trace(**_minimal_trace_args())
        self.assertIsNone(trace["synthesis_llm_call"])
        redacted = redact_trace(
            trace, include_doc_ids=False, include_entities=False
        )
        self.assertIsNone(redacted["synthesis_llm_call"])


_FALLBACK_PROMPT = "Query: 사업기간\n\n[c1] doc=doc_1 agency=조달청\n근거"
_FALLBACK_COMPLETION = '{"summary": "x", "used_chunk_ids": ["ghost_chunk"]}'


def _full_io_payload(*, summary: str, used_chunk_ids: list[str]) -> dict:
    return {
        "summary": summary,
        "used_chunk_ids": used_chunk_ids,
        "model": "fake",
        "tokens_in": 10,
        "tokens_out": 5,
        "user_prompt_text": _FALLBACK_PROMPT,
        "completion_text": _FALLBACK_COMPLETION,
    }


class TestSynthesisIoCapturedOnFailurePaths(unittest.TestCase):
    """GAP 2 (issue #1352) — full I/O must survive the validation
    early-returns so the diagnostically richest cases (rejected/empty LLM
    responses) are still auditable, not silently dropped to None."""

    def setUp(self):
        self._prev_env = os.environ.get("BIDMATE_TRACE_FULL")
        os.environ["BIDMATE_TRACE_FULL"] = "1"
        self._added = []

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("BIDMATE_TRACE_FULL", None)
        else:
            os.environ["BIDMATE_TRACE_FULL"] = self._prev_env
        for name in self._added:
            rag_synthesis._BACKENDS.pop(name, None)

    def _register(self, name: str, payload: dict):
        rag_synthesis._BACKENDS[name] = lambda **_kw: payload
        self._added.append(name)

    def _answer(self):
        return {
            "schema_version": 2,
            "status": "ok",
            "summary": "원본 요약",
            "claims": [{"target": "doc_1", "claim": "사업기간 12개월",
                        "citations": [{"chunk_id": "c1"}]}],
        }

    def test_unauthorized_chunk_ids_still_captures_io(self):
        # used_chunk_ids references a chunk not in evidence -> fallback
        self._register(
            "fake_unauthorized",
            _full_io_payload(summary="요약", used_chunk_ids=["ghost_chunk"]),
        )
        updated, meta = synthesize_answer(
            query="q", analysis={}, answer=self._answer(),
            evidence=[{"chunk_id": "c1"}], backend="fake_unauthorized",
        )
        self.assertIsNone(updated)  # validation rejected the response
        self.assertTrue(meta["fell_back"])
        self.assertTrue(meta["fallback_reason"].startswith("unauthorized_chunk_ids"))
        # ...yet the I/O the model actually produced is still recorded
        self.assertEqual(meta["user_prompt_text"], _FALLBACK_PROMPT)
        self.assertEqual(meta["completion_text"], _FALLBACK_COMPLETION)

    def test_empty_summary_still_captures_io(self):
        self._register(
            "fake_empty",
            _full_io_payload(summary="   ", used_chunk_ids=["c1"]),
        )
        updated, meta = synthesize_answer(
            query="q", analysis={}, answer=self._answer(),
            evidence=[{"chunk_id": "c1"}], backend="fake_empty",
        )
        self.assertIsNone(updated)
        self.assertEqual(meta["fallback_reason"], "empty_summary")
        self.assertEqual(meta["user_prompt_text"], _FALLBACK_PROMPT)

    def test_fallback_io_surfaces_in_trace_and_is_redactable(self):
        # end-to-end: fallback meta -> build_result_trace -> redact_trace all
        self._register(
            "fake_unauthorized2",
            _full_io_payload(summary="요약", used_chunk_ids=["ghost_chunk"]),
        )
        _updated, meta = synthesize_answer(
            query="q", analysis={}, answer=self._answer(),
            evidence=[{"chunk_id": "c1"}], backend="fake_unauthorized2",
        )
        trace = build_result_trace(**_minimal_trace_args(), synthesis_meta=meta)
        self.assertIsNotNone(trace["synthesis_llm_call"])
        self.assertEqual(
            trace["synthesis_llm_call"]["completion_text"], _FALLBACK_COMPLETION
        )
        redacted = redact_trace(
            trace, include_doc_ids=False, include_entities=False
        )
        self.assertEqual(
            redacted["synthesis_llm_call"]["completion_text"],
            REDACTED_LIST_PLACEHOLDER,
        )

    def test_env_off_does_not_capture_on_failure(self):
        os.environ.pop("BIDMATE_TRACE_FULL", None)
        self._register(
            "fake_off",
            _full_io_payload(summary="요약", used_chunk_ids=["ghost_chunk"]),
        )
        _updated, meta = synthesize_answer(
            query="q", analysis={}, answer=self._answer(),
            evidence=[{"chunk_id": "c1"}], backend="fake_off",
        )
        self.assertNotIn("user_prompt_text", meta)


if __name__ == "__main__":
    unittest.main()
