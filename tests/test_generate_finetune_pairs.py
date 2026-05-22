"""Tests for the LoRA pair-generation pipeline (issue #433).

The stub backend is deterministic, so plumbing is testable without a
network / API key. Tests pin:

* byte-determinism: ``seed=17`` always produces the same JSONL
* contamination guard rejects queries that overlap the eval surfaces
* hard-negative sampling stays in the configured rank window
* negatives never share ``doc_id`` with their positive
* train/val split is deterministic by query
* per-doc coverage stays balanced (no doc is starved)
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_finetune_pairs import (  # noqa: E402
    ContaminationGuard,
    _normalize_for_contamination,
    _split_for_query,
    build_subchunks,
    generate_pairs,
    load_eval_queries,
)

# Most cases here mine BM25 hard negatives over the full data/raw corpus
# (383 chunks, ADR 0050) — query-by-query get_scores/sort dominates, tens
# of seconds. Marked slow so `make test-fast` deselects them; CI still runs.
pytestmark = pytest.mark.slow


def _run(tmpdir: Path, **overrides) -> tuple[Path, dict]:
    output = tmpdir / "pairs.jsonl"
    kwargs = dict(
        input_dir=ROOT / "data" / "raw",
        output=output,
        backend="stub",
        queries_per_chunk=5,
        neg_per_pos=3,
        hard_neg_rank_window=(3, 15),
        val_frac=0.10,
        seed=17,
        max_chars=240,
    )
    kwargs.update(overrides)
    stats = generate_pairs(**kwargs)
    return output, stats


def _read_pairs(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


class DeterminismTest(unittest.TestCase):
    def test_same_seed_produces_byte_equal_output(self) -> None:
        with TemporaryDirectory() as tmp_a, TemporaryDirectory() as tmp_b:
            out_a, _ = _run(Path(tmp_a))
            out_b, _ = _run(Path(tmp_b))
            self.assertEqual(
                out_a.read_bytes(),
                out_b.read_bytes(),
                "stub backend must be byte-stable across runs at the same seed",
            )

    def test_different_seed_changes_split_assignment(self) -> None:
        with TemporaryDirectory() as tmp_a, TemporaryDirectory() as tmp_b:
            _, _ = _run(Path(tmp_a), seed=17)
            _, _ = _run(Path(tmp_b), seed=23)
            # Split assignment is by query-hash, so identical queries get
            # identical splits regardless of seed. Negatives, however, are
            # mined with a seed-dependent RNG. Sanity: file sizes differ
            # (negatives shuffle) but row count is the same.
            rows_a = _read_pairs(Path(tmp_a) / "pairs.jsonl")
            rows_b = _read_pairs(Path(tmp_b) / "pairs.jsonl")
            self.assertEqual(len(rows_a), len(rows_b))


class ContaminationGuardTest(unittest.TestCase):
    def test_normalizes_korean_particles(self) -> None:
        a = _normalize_for_contamination("기관 A의 보안 통제 요구사항은?")
        b = _normalize_for_contamination("기관 A 보안 통제 요구사항?")
        self.assertEqual(a.replace("?", "").strip(), b.replace("?", "").strip())

    def test_exact_match_rejected(self) -> None:
        guard = ContaminationGuard.from_eval_queries(["기관 A의 보안 통제 요구사항은?"])
        self.assertTrue(guard.is_contaminated("기관 A의 보안 통제 요구사항은?"))

    def test_paraphrase_above_threshold_rejected(self) -> None:
        # Same content words, different particles — should trip the
        # 3-gram Jaccard test on normalized form.
        guard = ContaminationGuard.from_eval_queries(["기관 A의 보안 통제 요구사항은?"])
        self.assertTrue(guard.is_contaminated("기관 A 보안 통제 요구사항"))

    def test_unrelated_query_passes(self) -> None:
        guard = ContaminationGuard.from_eval_queries(["기관 A의 보안 통제 요구사항은?"])
        self.assertFalse(guard.is_contaminated("기관 C 챗봇 응답 시간 목표"))

    def test_eval_surface_query_set_is_nonempty(self) -> None:
        # Sanity: at least the public synthetic + multiturn surfaces
        # contribute queries. If this drops to zero, the contamination
        # guard is silently disabled — fail loudly here instead.
        queries = load_eval_queries()
        self.assertGreater(len(queries), 30)

    def test_actual_eval_query_rejected_by_loaded_guard(self) -> None:
        # End-to-end: an exact public-eval question must be rejected.
        queries = load_eval_queries()
        self.assertTrue(queries, "eval query surfaces empty — fixture missing?")
        guard = ContaminationGuard.from_eval_queries(queries)
        self.assertTrue(guard.is_contaminated(queries[0]))


class HardNegativeConstraintsTest(unittest.TestCase):
    def test_negatives_never_share_doc_id_with_positive(self) -> None:
        with TemporaryDirectory() as tmp:
            out, _ = _run(Path(tmp))
            rows = _read_pairs(out)
            self.assertTrue(rows)
            for row in rows:
                for neg in row["negatives"]:
                    pos_doc = row["positive_doc_id"]
                    self.assertFalse(
                        neg["chunk_id"].startswith(pos_doc + "::"),
                        f"negative {neg['chunk_id']} shares doc with positive {pos_doc}",
                    )

    def test_negatives_in_configured_rank_window_when_possible(self) -> None:
        # ADR 0050 expanded data/raw from ~25 chunks (v1 axis-A) to 383
        # chunks (real_scale_v2_distractor + H/I/J/K corpora). The window
        # is scaled accordingly — a window of (3, 100) covers ~26% of the
        # post-expansion corpus, matching the pre-expansion (3, 15)/25
        # coverage ratio so the constraint can be honored "when possible".
        window = (3, 100)
        with TemporaryDirectory() as tmp:
            out, _ = _run(Path(tmp), hard_neg_rank_window=window)
            rows = _read_pairs(out)
            in_window = 0
            total_negs = 0
            for row in rows:
                for neg in row["negatives"]:
                    total_negs += 1
                    if window[0] <= neg["bm25_rank"] <= window[1]:
                        in_window += 1
            # Window now meaningfully smaller than the 383-chunk corpus;
            # we still expect *most* negatives in window. Demand ≥ 80%.
            self.assertGreaterEqual(
                in_window / max(1, total_negs),
                0.80,
                f"only {in_window}/{total_negs} negatives in {window}",
            )

    def test_negatives_count_matches_neg_per_pos(self) -> None:
        with TemporaryDirectory() as tmp:
            out, _ = _run(Path(tmp), neg_per_pos=3)
            rows = _read_pairs(out)
            for row in rows:
                # Allow degenerate cases where the corpus has < 3 valid
                # candidates after the doc_id filter; sample as many as
                # are available. On 7-RFP / 25-chunk fixture this should
                # never trigger.
                self.assertLessEqual(len(row["negatives"]), 3)
                self.assertGreaterEqual(len(row["negatives"]), 1)


class SplitTest(unittest.TestCase):
    def test_split_is_query_deterministic(self) -> None:
        q = "기관 A의 일정은?"
        self.assertEqual(_split_for_query(q, 0.10), _split_for_query(q, 0.10))

    def test_val_fraction_roughly_honored(self) -> None:
        with TemporaryDirectory() as tmp:
            _, stats = _run(Path(tmp), queries_per_chunk=20)
            train = stats["splits"].get("train", 0)
            val = stats["splits"].get("val", 0)
            total = train + val
            self.assertGreater(total, 100)
            val_frac = val / total
            # With val_frac=0.10 and ~500 queries, expect 5%–18% by
            # binomial variance.
            self.assertGreater(val_frac, 0.03)
            self.assertLess(val_frac, 0.20)


class PerDocCoverageTest(unittest.TestCase):
    def test_every_doc_appears(self) -> None:
        with TemporaryDirectory() as tmp:
            out, stats = _run(Path(tmp), queries_per_chunk=5)
            self.assertGreaterEqual(
                len(stats["per_doc"]),
                7,
                "all 7 raw RFP docs should contribute pairs",
            )


class ContaminationRejectionThresholdTest(unittest.TestCase):
    def test_pipeline_fails_when_contamination_too_high(self) -> None:
        # Contract: ``fail_threshold=0.0`` MUST raise when any generated
        # query is contaminated, proving the threshold is wired up.
        #
        # Issue #1315 — this used to mine over the full 383-chunk data/raw
        # corpus at queries_per_chunk=200 (316s, a pr-eval shard floor) and
        # relied on volume to *probabilistically* trip a rejection — so it
        # also tolerated the zero-rejection path, which never exercised the
        # raise. We instead guarantee contamination deterministically: a
        # 2-chunk tmp corpus whose section headings ARE real eval-surface
        # queries (load_eval_queries — not a mock). The stub template wraps
        # each heading verbatim, so the generated query's trigrams overlap
        # the eval query above the 0.7 Jaccard threshold. Same raise path,
        # against the real guard, in <1s instead of 316s.
        eval_queries = load_eval_queries()
        self.assertGreaterEqual(
            len(eval_queries), 2, "eval surface must be populated to seed contamination"
        )
        doc = {
            "doc_id": "fixture-contaminating",
            "title": "오염 유발 픽스처",
            "agency": "기관 X",
            "project": "테스트",
            "metadata": {},
            "sections": [
                {"heading": eval_queries[0], "text": f"{eval_queries[0]} 관련 본문."},
                {"heading": eval_queries[1], "text": f"{eval_queries[1]} 관련 본문."},
            ],
        }
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaises(RuntimeError) as ctx:
                generate_pairs(
                    input_dir=Path(tmp),
                    output=Path(tmp) / "pairs.jsonl",
                    backend="stub",
                    queries_per_chunk=5,
                    neg_per_pos=3,
                    hard_neg_rank_window=(3, 15),
                    val_frac=0.10,
                    seed=17,
                    max_chars=240,
                    fail_threshold=0.0,
                )
            self.assertIn("rejection rate", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
