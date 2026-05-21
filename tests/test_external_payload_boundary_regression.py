"""Regression tests for the external-payload data-boundary guard.

ADR 0061 ③ restricts external egress to public/synthetic surfaces and
keeps private RFP bodies off the wire (ADR 0005/0012). Before issue #1154
that was policy-only — the anthropic / openai backends in
``rag_metadata_extraction`` and ``rag_synthesis`` sent the full document /
evidence text to the vendor with no surface check.

These tests lock the *fail_closed* contract on three surfaces:

* the central guard (``bidmate_data_boundary``) — only an explicit
  public/synthetic attestation permits egress; unset / private / unknown
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

import rag_synthesis
from bidmate_data_boundary import (
    DATA_SURFACE_ENV,
    ExternalPayloadBlocked,
    assert_external_payload_allowed,
    is_public_surface,
    resolve_data_surface,
)
from rag_metadata_extraction import (
    _anthropic_tool_use_backend,
    _openai_function_call_backend,
    _regex_backend,
    extract_rfp_metadata,
)


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
    """The central guard is fail_closed: only public/synthetic passes."""

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
        for value in ("public", "synthetic", "public_synthetic", "public-synthetic"):
            with self.subTest(value=value), _surface(value):
                # Must not raise.
                assert_external_payload_allowed(channel="test:public")
                self.assertTrue(is_public_surface())

    def test_resolve_normalizes_case_and_whitespace(self) -> None:
        with _surface("  Public_Synthetic  "):
            self.assertEqual(resolve_data_surface(), "public_synthetic")
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
        with _surface("public_synthetic"):
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


if __name__ == "__main__":
    unittest.main()
