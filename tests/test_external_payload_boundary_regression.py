"""Regression tests for the external-payload data-boundary guard.

ADR 0061 ③ restricts external egress to public fixture surfaces and
keeps private RFP bodies off the wire (ADR 0005). Before issue #1154
that was policy-only — the anthropic / openai backends in
``rag_metadata_extraction`` and ``rag_synthesis`` sent the full document /
evidence text to the vendor with no surface check.

These tests lock the *fail_closed* contract on three surfaces:

* the central guard (``bidmate_data_boundary``) — only an explicit
  public fixture attestation permits egress; unset / private / unknown
  values raise ``ExternalPayloadBlocked``;
* the four external backend entry points fail closed *before* any SDK
  import or network call (so the guard, not the SDK, is the blocker);
* the public dispatch wrappers (``extract_rfp_metadata`` /
  ``synthesize_answer``) keep their deterministic offline result when the
  guard blocks — the pipeline never breaks.

A final test proves the guard does not *over*-block: with a public
attestation the backend proceeds to its own key check (forced
network-free by clearing the API key).
"""
from __future__ import annotations

import contextlib
import os
import unittest
from typing import Any

import rag_embedding
import rag_query_expansion
import rag_rerank
import rag_synthesis
from bidmate_data_boundary import (
    DATA_SURFACE_ENV,
    EGRESS_PROFILE_ENV,
    ExternalPayloadBlocked,
    assert_external_payload_allowed,
    external_egress_allowed,
    is_public_surface,
    resolve_data_surface,
    resolve_egress_profile,
)
from rag_metadata_extraction import (
    _anthropic_tool_use_backend,
    _openai_function_call_backend,
    _regex_backend,
    extract_rfp_metadata,
)
from rag_planner import LLMPlanner, StaticPlanner


@contextlib.contextmanager
def _surface(value: str | None):
    """Set (or unset, when ``value is None``) BIDMATE_DATA_SURFACE.

    Restores the prior value on exit so tests do not leak the env var into
    each other or the ambient process.
    """
    saved = os.environ.get(DATA_SURFACE_ENV)
    if value is None:
        os.environ.pop(DATA_SURFACE_ENV, None)
    else:
        os.environ[DATA_SURFACE_ENV] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(DATA_SURFACE_ENV, None)
        else:
            os.environ[DATA_SURFACE_ENV] = saved


@contextlib.contextmanager
def _cleared(*names: str):
    """Temporarily clear env vars (restore on exit).

    Used by the over-block tests to force the backend's own API-key check
    to fail *without* a network round-trip, so the test proves the guard
    is not the blocker regardless of whether the SDK is installed.
    """
    saved = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextlib.contextmanager
def _set_env(**values: str):
    saved = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextlib.contextmanager
def _egress_profile(value: str | None):
    saved = os.environ.get(EGRESS_PROFILE_ENV)
    if value is None:
        os.environ.pop(EGRESS_PROFILE_ENV, None)
    else:
        os.environ[EGRESS_PROFILE_ENV] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(EGRESS_PROFILE_ENV, None)
        else:
            os.environ[EGRESS_PROFILE_ENV] = saved


SAMPLE_DOCUMENT: dict[str, Any] = {
    "doc_id": "sample-rfp",
    "agency": "기관 A",
    "project": "AI 챗봇 구축 사업",
    "metadata": {"agency": "기관 A", "budget": 150_000_000},
    "sections": [{"text": "본 사업은 AI 챗봇 구축 사업이다. 문의: rfp@example.com"}],
}


def _make_answer() -> dict[str, Any]:
    return {
        "status": "supported",
        "summary": "기관 A는 보안 통제 매뉴얼이 필요하다.",
        "claims": [
            {
                "target": "기관 A",
                "claim": "보안 통제 매뉴얼을 구축한다",
                "citations": [{"doc_id": "rfp-a", "chunk_id": "rfp-a::chunk-001"}],
            }
        ],
        "insufficiency": None,
    }


def _make_evidence() -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": "rfp-a::chunk-001",
            "doc_id": "rfp-a",
            "agency": "기관 A",
            "text": "제안사는 보안 통제 매뉴얼을 구축해야 한다.",
        }
    ]


class GuardSurfaceTest(unittest.TestCase):
    """The central guard is fail_closed: only public fixture surfaces pass."""

    def test_fail_closed_when_surface_unset(self) -> None:
        with _surface(None):
            with self.assertRaises(ExternalPayloadBlocked):
                assert_external_payload_allowed(channel="test:unset")

    def test_fail_closed_on_private_local(self) -> None:
        for value in ("private", "local", "private_local"):
            with self.subTest(value=value), _surface(value):
                with self.assertRaises(ExternalPayloadBlocked):
                    assert_external_payload_allowed(channel="test:private")

    def test_fail_closed_on_unrecognized_value(self) -> None:
        # An unknown token must NOT fail open — the allowlist is strict.
        with _surface("prod"), self.assertRaises(ExternalPayloadBlocked):
            assert_external_payload_allowed(channel="test:unknown")

    def test_allows_attested_public_surfaces(self) -> None:
        for value in ("public", "public_fixture", "public-fixture"):
            with self.subTest(value=value), _surface(value):
                # Must not raise.
                assert_external_payload_allowed(channel="test:public")
                self.assertTrue(is_public_surface())

    def test_allows_approved_private_external_egress_profiles(self) -> None:
        for value in ("approved_external_api", "customer_managed_cloud"):
            with self.subTest(value=value), _surface("private_local"), _egress_profile(value):
                assert_external_payload_allowed(channel="test:approved")
                self.assertEqual(value, resolve_egress_profile())
                self.assertTrue(external_egress_allowed())

    def test_approved_private_egress_profile_is_channel_wide(self) -> None:
        channels = (
            "metadata_extraction:anthropic_tool_use",
            "synthesis:openai_compatible",
            "embedding:openai",
            "rerank:cohere",
            "query_expansion:anthropic_hyde",
            "planner:anthropic",
        )
        with _surface("private_local"), _egress_profile("approved_external_api"):
            for channel in channels:
                with self.subTest(channel=channel):
                    assert_external_payload_allowed(channel=channel)

    def test_resolve_normalizes_case_and_whitespace(self) -> None:
        with _surface("  Public_Fixture  "):
            self.assertEqual(resolve_data_surface(), "public_fixture")
            self.assertTrue(is_public_surface())

    def test_blocked_message_names_channel_and_env(self) -> None:
        with _surface(None):
            with self.assertRaises(ExternalPayloadBlocked) as ctx:
                assert_external_payload_allowed(channel="metadata_extraction:anthropic_tool_use")
        message = str(ctx.exception)
        self.assertIn("metadata_extraction:anthropic_tool_use", message)
        self.assertIn(DATA_SURFACE_ENV, message)

    def test_external_payload_blocked_is_runtimeerror(self) -> None:
        # Subclassing RuntimeError is load-bearing: the backends' existing
        # ``except Exception`` fallbacks must catch the guard so it fails
        # closed without breaking the pipeline.
        self.assertTrue(issubclass(ExternalPayloadBlocked, RuntimeError))


class BackendEntryFailClosedTest(unittest.TestCase):
    """Each external entry point raises before any SDK import / network."""

    def test_metadata_anthropic_backend_fail_closed(self) -> None:
        with _surface("private_local"):
            with self.assertRaises(ExternalPayloadBlocked):
                _anthropic_tool_use_backend(SAMPLE_DOCUMENT)

    def test_metadata_openai_backend_fail_closed(self) -> None:
        with _surface(None):
            with self.assertRaises(ExternalPayloadBlocked):
                _openai_function_call_backend(SAMPLE_DOCUMENT)

    def test_synthesis_anthropic_backend_fail_closed(self) -> None:
        with _surface("private_local"):
            with self.assertRaises(ExternalPayloadBlocked):
                rag_synthesis._anthropic_backend(
                    query="q",
                    analysis={},
                    answer=_make_answer(),
                    evidence=_make_evidence(),
                )

    def test_synthesis_openai_backend_fail_closed(self) -> None:
        with _surface(None):
            with self.assertRaises(ExternalPayloadBlocked):
                rag_synthesis._openai_compatible_backend(
                    query="q",
                    analysis={},
                    answer=_make_answer(),
                    evidence=_make_evidence(),
                )

    def test_synthesis_local_openai_rejects_non_loopback_base_url(self) -> None:
        with _surface("private_local"), _set_env(
            BIDMATE_SYNTHESIS_BASE_URL="https://api.example.com/v1",
            BIDMATE_SYNTHESIS_API_KEY="test",
            BIDMATE_SYNTHESIS_MODEL="local-small",
        ):
            with self.assertRaises(ExternalPayloadBlocked):
                rag_synthesis._local_openai_compatible_backend(
                    query="q",
                    analysis={},
                    answer=_make_answer(),
                    evidence=_make_evidence(),
                )

    def test_synthesis_local_openai_loopback_reaches_key_check(self) -> None:
        with _surface("private_local"), _set_env(
            BIDMATE_SYNTHESIS_BASE_URL="http://127.0.0.1:11434/v1"
        ), _cleared("BIDMATE_SYNTHESIS_API_KEY", "BIDMATE_SYNTHESIS_MODEL"):
            with self.assertRaises(RuntimeError) as ctx:
                rag_synthesis._local_openai_compatible_backend(
                    query="q",
                    analysis={},
                    answer=_make_answer(),
                    evidence=_make_evidence(),
                )
        self.assertIn("BIDMATE_SYNTHESIS_API_KEY", str(ctx.exception))


class DispatchFallbackTest(unittest.TestCase):
    """Public wrappers keep the deterministic offline result when blocked."""

    def test_extract_rfp_metadata_falls_back_to_regex(self) -> None:
        with _surface(None):
            blocked = extract_rfp_metadata(
                SAMPLE_DOCUMENT, backend="anthropic_tool_use"
            )
        # Identical to the regex baseline — no partial, no raise propagated.
        self.assertEqual(blocked.as_dict(), _regex_backend(SAMPLE_DOCUMENT).as_dict())
        self.assertEqual(blocked.agency, "기관 A")

    def test_synthesize_answer_falls_back_with_guard_reason(self) -> None:
        with _surface("private_local"):
            updated, meta = rag_synthesis.synthesize_answer(
                query="기관 A의 보안 통제 요구사항은?",
                analysis={"query_type": "single_doc", "entities": ["기관 A"]},
                answer=_make_answer(),
                evidence=_make_evidence(),
                backend="anthropic",
            )
        self.assertIsNone(updated)
        self.assertTrue(meta["fell_back"])
        self.assertIn("ExternalPayloadBlocked", meta["fallback_reason"])


class GuardDoesNotOverBlockTest(unittest.TestCase):
    """A public attestation lets the backend reach its own key check.

    Forcing the API key empty keeps this network-free regardless of whether
    the SDK is installed: the backend raises a *different* RuntimeError
    (missing SDK or missing key), proving the guard is not the blocker.
    """

    def test_public_surface_passes_guard_then_key_check(self) -> None:
        with _surface("public_fixture"):
            saved = os.environ.get("ANTHROPIC_API_KEY")
            os.environ["ANTHROPIC_API_KEY"] = ""
            try:
                with self.assertRaises(RuntimeError) as ctx:
                    _anthropic_tool_use_backend(SAMPLE_DOCUMENT)
            finally:
                if saved is None:
                    os.environ.pop("ANTHROPIC_API_KEY", None)
                else:
                    os.environ["ANTHROPIC_API_KEY"] = saved
        # Guard passed — the failure is the backend's own SDK/key check.
        self.assertNotIsInstance(ctx.exception, ExternalPayloadBlocked)
        message = str(ctx.exception)
        self.assertTrue(
            "ANTHROPIC_API_KEY" in message or "anthropic SDK" in message,
            f"unexpected error after guard: {message!r}",
        )


_CANDIDATES: list[dict[str, Any]] = [
    {
        "chunk_id": "rfp-a::chunk-001",
        "doc_id": "rfp-a",
        "text": "제안사는 보안 통제 매뉴얼을 구축해야 한다.",
    },
    {
        "chunk_id": "rfp-a::chunk-002",
        "doc_id": "rfp-a",
        "text": "사업비는 1억 5천만원으로 한다.",
    },
]


class RerankBackendFailClosedTest(unittest.TestCase):
    """rag_rerank cohere backend fails closed; rerank() keeps input order.

    issue #1195 — extends the ADR 0061 ③ guard to the candidate-text
    egress in ``rag_rerank._cohere_backend``.
    """

    def test_cohere_backend_entry_fail_closed(self) -> None:
        for value in (None, "private", "local"):
            with self.subTest(value=value), _surface(value):
                with self.assertRaises(ExternalPayloadBlocked):
                    rag_rerank._cohere_backend(
                        query="q", candidates=list(_CANDIDATES), model=None
                    )

    def test_rerank_dispatch_falls_back_unchanged(self) -> None:
        # never-raise wrapper: blocked surface returns the input candidates
        # in their original order with fell_back set.
        with _surface(None):
            reordered, meta = rag_rerank.rerank(
                "q", list(_CANDIDATES), backend="cohere"
            )
        self.assertEqual(
            [c["chunk_id"] for c in reordered],
            [c["chunk_id"] for c in _CANDIDATES],
        )
        self.assertTrue(meta["fell_back"])
        self.assertIn("ExternalPayloadBlocked", meta["fallback_reason"])

    def test_stub_backend_never_invokes_guard(self) -> None:
        # ADR 0001 invariant: the default stub backend is guard-free and
        # passes through even on an unset (blocked) surface.
        with _surface(None):
            reordered, meta = rag_rerank.rerank(
                "q", list(_CANDIDATES), backend="stub"
            )
        self.assertFalse(meta["fell_back"])
        self.assertEqual(
            [c["chunk_id"] for c in reordered],
            [c["chunk_id"] for c in _CANDIDATES],
        )

    def test_public_surface_passes_guard_then_sdk_or_key_check(self) -> None:
        with _surface("public_fixture"), _cleared(
            "BIDMATE_COHERE_API_KEY", "COHERE_API_KEY"
        ):
            with self.assertRaises(RuntimeError) as ctx:
                rag_rerank._cohere_backend(
                    query="q", candidates=list(_CANDIDATES), model=None
                )
        # Guard passed — the failure is the backend's own SDK/key check.
        self.assertNotIsInstance(ctx.exception, ExternalPayloadBlocked)


class EmbeddingBackendFailClosedTest(unittest.TestCase):
    """rag_embedding openai backend fails closed by RAISING.

    issue #1195 — unlike the never-raise backends, the openai embedding
    path has no offline wrapper, so a blocked surface fails closed by
    raising ExternalPayloadBlocked rather than degrading to hashing.
    """

    def test_embed_with_openai_entry_fail_closed(self) -> None:
        for value in (None, "private", "local"):
            with self.subTest(value=value), _surface(value):
                with self.assertRaises(ExternalPayloadBlocked):
                    rag_embedding._embed_with_openai(
                        ["문서 본문 텍스트"], model_name="text-embedding-3-small"
                    )

    def test_embed_texts_openai_raises_not_silent(self) -> None:
        # Asymmetry vs rerank / hyde / planner: no never-raise wrapper, so
        # the block surfaces as an exception out of the public entry point.
        with _surface(None):
            with self.assertRaises(ExternalPayloadBlocked):
                rag_embedding.embed_texts(["문서 본문 텍스트"], backend="openai")

    def test_default_backend_never_invokes_guard(self) -> None:
        # ADR 0001 invariant: the default offline path is not gated. The
        # hashing backend produces vectors even on an unset (blocked) surface.
        with _surface(None):
            result = rag_embedding.embed_texts(["문서 본문 텍스트"], backend="hashing")
        self.assertEqual(result.backend, "hashing")
        self.assertEqual(result.vectors.shape[0], 1)

    def test_public_surface_passes_guard_then_sdk_or_key_check(self) -> None:
        with _surface("public_fixture"), _cleared(
            "BIDMATE_OPENAI_API_KEY", "OPENAI_API_KEY"
        ):
            with self.assertRaises(RuntimeError) as ctx:
                rag_embedding._embed_with_openai(
                    ["문서 본문 텍스트"], model_name="text-embedding-3-small"
                )
        self.assertNotIsInstance(ctx.exception, ExternalPayloadBlocked)


class QueryExpansionBackendFailClosedTest(unittest.TestCase):
    """rag_query_expansion HyDE backend fails closed; expand() keeps raw query.

    issue #1195 — extends the ADR 0061 ③ guard to the query-text egress in
    ``rag_query_expansion._call_anthropic_hyde``.
    """

    QUERY = "기관 A의 보안 통제 요구사항은?"

    def test_call_anthropic_hyde_entry_fail_closed(self) -> None:
        for value in (None, "private", "local"):
            with self.subTest(value=value), _surface(value):
                with self.assertRaises(ExternalPayloadBlocked):
                    rag_query_expansion._call_anthropic_hyde(
                        query=self.QUERY,
                        model="claude-haiku-4-5-20251001",
                        max_tokens=256,
                    )

    def test_hyde_expander_falls_back_to_raw_query(self) -> None:
        with _surface("private_local"):
            expanded, meta = rag_query_expansion.HyDEExpander().expand(
                self.QUERY, plan={}
            )
        self.assertEqual(expanded, self.QUERY)
        self.assertTrue(meta["fell_back"])
        self.assertIn("ExternalPayloadBlocked", meta["fallback_reason"])

    def test_identity_expander_never_invokes_guard(self) -> None:
        # ADR 0001 invariant: the default identity expander is guard-free.
        with _surface(None):
            expanded, meta = rag_query_expansion.IdentityExpander().expand(
                self.QUERY, plan={}
            )
        self.assertEqual(expanded, self.QUERY)
        self.assertFalse(meta["fell_back"])

    def test_public_surface_passes_guard_then_sdk_or_key_check(self) -> None:
        with _surface("public_fixture"), _cleared("ANTHROPIC_API_KEY"):
            with self.assertRaises(RuntimeError) as ctx:
                rag_query_expansion._call_anthropic_hyde(
                    query=self.QUERY,
                    model="claude-haiku-4-5-20251001",
                    max_tokens=256,
                )
        self.assertNotIsInstance(ctx.exception, ExternalPayloadBlocked)


class PlannerBackendFailClosedTest(unittest.TestCase):
    """rag_planner LLMPlanner falls back to StaticPlanner when blocked.

    issue #1195 — the guard sits inside plan_next's try block, so a blocked
    surface is caught by the existing except and routed to StaticPlanner;
    the never-raise contract (always a valid action) is preserved.
    """

    @staticmethod
    def _analysis() -> dict[str, Any]:
        return {"query_type": "single_doc", "entities": ["기관 A"]}

    def test_llm_planner_falls_back_to_static(self) -> None:
        with _surface("private_local"):
            action, meta = LLMPlanner().plan_next(
                analysis=self._analysis(), history=[], budget={}
            )
        self.assertTrue(meta["fell_back"])
        self.assertEqual(meta["backend"], "anthropic_fallback")
        self.assertIn("ExternalPayloadBlocked", meta["fallback_reason"])
        self.assertIn(action["tool"], {"retrieve_evidence", "abstain"})

    def test_static_planner_never_invokes_guard(self) -> None:
        # ADR 0001 invariant: the default static planner is guard-free.
        with _surface(None):
            _, meta = StaticPlanner().plan_next(
                analysis=self._analysis(), history=[], budget={}
            )
        self.assertFalse(meta["fell_back"])
        self.assertEqual(meta["backend"], "static")

    def test_public_surface_does_not_block_planner_channel(self) -> None:
        # The guard's allow/block decision is channel-independent, so an
        # attested public surface must not block the planner channel. Asserted
        # directly (network-free) since plan_next swallows backend errors.
        with _surface("public_fixture"):
            assert_external_payload_allowed(channel="planner:anthropic")


if __name__ == "__main__":
    unittest.main()
