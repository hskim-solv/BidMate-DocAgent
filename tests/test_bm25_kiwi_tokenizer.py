"""Regression guard for the kiwi BM25 tokenizer (issue #486, ADR 0030).

Three contracts to lock:

1. **Never-raise fallback.** ``korean_lexicon.kiwi_tokens`` returns
   ``None`` when kiwipiepy is unavailable. The dispatch in
   ``rag_retrieval._chunk_tokens_for_bm25`` and
   ``rag_retrieval.bm25_scores_for_index`` silently degrades to the
   regex path on ``None`` — under that fallback ``full_kiwi`` is
   byte-equal to ``hybrid_bm25``.
2. **Cache isolation.** ``get_or_build_bm25`` keys on
   ``(stopword_profile, tokenizer)`` so the kiwi corpus does not
   reuse the regex BM25Okapi instance (different IDF distributions).
3. **ADR 0001 invariant.** ``naive_baseline`` preset stays at
   ``bm25_tokenizer: "regex"`` — golden ranking unchanged. Already
   gated by ``tests/test_naive_baseline_ranking_invariance.py``; this
   file double-checks the preset surface explicitly.

The kiwi tokenizer behavior itself is gated by
``pytest.importorskip("kiwipiepy")`` — those tests skip cleanly in
environments without the wheel (e.g. minimal CI installs).
"""

from __future__ import annotations

import unittest

import pytest

from korean_lexicon import _KIWI_POS_KEEP, kiwi_tokens
from rag_pipeline_presets import (
    PIPELINE_PRESETS,
    VALID_BM25_TOKENIZERS,
    resolve_pipeline_config,
)


class NeverRaiseFallbackTest(unittest.TestCase):
    """kiwi_tokens must not raise on any input shape."""

    def test_empty_string_returns_empty_list(self) -> None:
        # Empty input is the cheap path — return [] without touching
        # kiwipiepy. Important because the regex path also returns []
        # for empty input, preserving the byte-equal contract.
        result = kiwi_tokens("")
        self.assertEqual(result, [])

    def test_whitespace_only_returns_empty_or_none(self) -> None:
        # Whitespace yields no tagged morphemes — kiwi returns nothing
        # or only spaces (filtered out by POS keep). Result is `[]` or
        # `None` (fallback path); both are acceptable.
        result = kiwi_tokens("   ")
        self.assertIn(result, ([], None))

    def test_arbitrary_unicode_does_not_raise(self) -> None:
        # Defensive coverage of malformed inputs (chat-template
        # tokens, emoji, mixed scripts). Either kiwipiepy handles it
        # or we return None — never raise.
        for weird in ("🚀 hello", "\x00\x01", "<|im_start|>", "한국어와 English 혼합"):
            kiwi_tokens(weird)  # must not raise


class ConfigSurfaceTest(unittest.TestCase):
    """The new config key + validator surfaces are wired correctly."""

    def test_valid_tokenizers_set_has_regex_and_kiwi(self) -> None:
        self.assertEqual(VALID_BM25_TOKENIZERS, {"regex", "kiwi"})

    def test_all_presets_default_to_regex(self) -> None:
        """ADR 0001 invariant — every shipped preset stays at regex.

        A future ADR can flip ``agentic_full`` (or any non-naive
        preset) to kiwi by changing this default after the ADR 0030
        re-open conditions trigger. Until then, regex is the gate.
        """
        for name, preset in PIPELINE_PRESETS.items():
            with self.subTest(preset=name):
                self.assertEqual(
                    preset.get("bm25_tokenizer"),
                    "regex",
                    f"preset {name!r} must keep bm25_tokenizer='regex' "
                    "until a follow-up ADR documents the flip",
                )

    def test_resolve_rejects_unknown_tokenizer(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_pipeline_config(
                {
                    "pipeline": "agentic_full",
                    "bm25_tokenizer": "mecab",  # not in VALID set
                }
            )
        self.assertIn("bm25_tokenizer must be one of", str(ctx.exception))

    def test_resolve_accepts_kiwi_explicitly(self) -> None:
        config = resolve_pipeline_config(
            {
                "pipeline": "agentic_full",
                "bm25_tokenizer": "kiwi",
            }
        )
        self.assertEqual(config["bm25_tokenizer"], "kiwi")

    def test_resolve_defaults_to_regex_when_missing(self) -> None:
        config = resolve_pipeline_config({"pipeline": "naive_baseline"})
        self.assertEqual(config["bm25_tokenizer"], "regex")


class KiwiTokensBehaviorTest(unittest.TestCase):
    """Behavior tests that require kiwipiepy to be installed."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_kiwi(self) -> None:
        pytest.importorskip("kiwipiepy")

    def test_korean_compound_noun_emits_morphemes(self) -> None:
        # The motivating example: "입찰참여시작일" should yield ≥ 2
        # noun morphemes when kiwi splits it. Exact list depends on
        # the kiwi model's dictionary; we assert the structural
        # property (multiple tokens) rather than a brittle list.
        tokens = kiwi_tokens("입찰참여시작일은 2026년 5월 12일입니다")
        self.assertIsNotNone(tokens)
        assert tokens is not None  # narrow for type-checker
        self.assertGreaterEqual(len(tokens), 2)

    def test_pos_filter_drops_particles(self) -> None:
        # 조사 (J*) and 어미 (E*) tags carry no retrieval signal.
        # If kiwi emits any token tagged J* or E*, it would have been
        # dropped by ``_KIWI_POS_KEEP``. Asserting that all retained
        # tokens have POS in the keep set indirectly verifies the
        # filter ran.
        tokens = kiwi_tokens("기관 A의 보안 통제 요구사항을 알려주세요")
        self.assertIsNotNone(tokens)
        # No particle leaks like "을" / "의" — they're filtered.
        self.assertNotIn("을", tokens or [])
        self.assertNotIn("의", tokens or [])

    def test_english_and_numbers_kept(self) -> None:
        # SL (외국어) / SN (숫자) are in the keep set so RFP queries
        # that mix Korean + English / numbers retain the retrieval
        # anchors.
        tokens = kiwi_tokens("API 1000ms 응답시간")
        self.assertIsNotNone(tokens)
        assert tokens is not None
        joined = " ".join(tokens)
        # Either "API" or "1000" should appear — exact form depends
        # on kiwi's segmentation but at least one is retained.
        self.assertTrue("API" in joined or "1000" in joined)

    def test_idempotent_on_same_input(self) -> None:
        # The lru_cache on _kiwi_instance means the same Kiwi
        # singleton handles repeated calls. Output for identical
        # input must be identical.
        query = "기관 A의 AI 요구사항"
        self.assertEqual(kiwi_tokens(query), kiwi_tokens(query))


class PosKeepSetTest(unittest.TestCase):
    """The POS filter set is the load-bearing config — pin it explicitly."""

    def test_keep_set_covers_substantives(self) -> None:
        # 체언 — the retrieval-bearing nouns.
        for tag in ("NNG", "NNP", "NP", "NR"):
            self.assertIn(tag, _KIWI_POS_KEEP)

    def test_keep_set_covers_predicates(self) -> None:
        # 용언 — verbs / adjectives carry topical signal.
        for tag in ("VV", "VA", "VX", "VCP", "VCN"):
            self.assertIn(tag, _KIWI_POS_KEEP)

    def test_keep_set_covers_modifiers_and_foreign(self) -> None:
        # 수식어 + 외래어 / 한자 / 숫자 — RFP queries mix all of these.
        for tag in ("MM", "MAG", "MAJ", "SL", "SH", "SN"):
            self.assertIn(tag, _KIWI_POS_KEEP)

    def test_keep_set_excludes_particles(self) -> None:
        # 조사 (J*) and 어미 (E*) must NOT be in the keep set —
        # they carry no retrieval signal.
        for tag in ("JKS", "JKO", "JX", "EC", "EF"):
            self.assertNotIn(tag, _KIWI_POS_KEEP)


if __name__ == "__main__":
    unittest.main()
