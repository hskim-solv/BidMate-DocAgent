"""Regression guard for the naive_baseline golden regenerator CLI wiring.

Covers the ``--check`` exit codes, the write round-trip, query-set/length
preservation, and the committed serialization style of
``scripts/regen_naive_baseline_golden.py`` WITHOUT building a real index —
``build_golden`` is monkeypatched so these stay fast + deterministic. The real
index-build correctness is covered by
``tests/test_naive_baseline_ranking_invariance.py``, which imports the same
``build_golden``.

``RegenGoldenDegradedGuardTest`` instead exercises the REAL ``build_golden`` +
``_validate_rebuild`` (monkeypatching only its ``build_index_payload`` /
``run_rag_query`` deps): a degraded/malformed rebuild must fail BOTH ``--check``
and write, and write must never serialize it — the self-validating-golden trap
(ADR 0001) that would otherwise bless a real regression into the baseline.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts import regen_naive_baseline_golden as regen


_REFERENCE = {
    "q1": [["doc::chunk-1", 0.9], ["doc::chunk-2", 0.8]],
    "q2": [["doc::chunk-3", 0.7]],
}


def _write_golden(tmp: Path, data: dict) -> Path:
    path = tmp / "golden.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class RegenGoldenCliTest(unittest.TestCase):
    def test_check_passes_when_fresh(self) -> None:
        with TemporaryDirectory() as d, mock.patch.object(regen, "build_golden", return_value=_REFERENCE):
            golden = _write_golden(Path(d), _REFERENCE)
            self.assertEqual(0, regen.run(check=True, golden_path=golden))

    def test_check_fails_when_stale(self) -> None:
        stale = {
            "q1": [["doc::chunk-1", 0.9], ["doc::chunk-2", 0.8]],
            "q2": [["doc::chunk-99", 0.1]],
        }
        with TemporaryDirectory() as d, mock.patch.object(regen, "build_golden", return_value=_REFERENCE):
            golden = _write_golden(Path(d), stale)
            self.assertEqual(1, regen.run(check=True, golden_path=golden))

    def test_write_round_trips(self) -> None:
        stale = {"q1": [["x", 0.0], ["y", 0.0]], "q2": [["z", 0.0]]}
        with TemporaryDirectory() as d, mock.patch.object(regen, "build_golden", return_value=_REFERENCE):
            golden = _write_golden(Path(d), stale)
            self.assertEqual(0, regen.run(check=False, golden_path=golden))
            self.assertEqual(_REFERENCE, json.loads(golden.read_text(encoding="utf-8")))

    def test_run_passes_committed_golden_as_reference(self) -> None:
        # run() must hand the committed golden to build_golden so the curated
        # query set + per-query K are preserved on regeneration.
        captured: dict = {}

        def fake_build(reference):
            captured["ref"] = reference
            return _REFERENCE

        with TemporaryDirectory() as d, mock.patch.object(regen, "build_golden", side_effect=fake_build):
            golden = _write_golden(Path(d), _REFERENCE)
            regen.run(check=True, golden_path=golden)
        self.assertEqual(_REFERENCE, captured["ref"])

    def test_serialize_korean_literal_2space_indent_trailing_newline(self) -> None:
        out = regen._serialize({"기관": [["c", 0.5]]})
        self.assertTrue(out.endswith("\n"))
        self.assertIn("기관", out)  # ensure_ascii=False keeps Korean keys literal
        self.assertNotIn("\\u", out)
        self.assertIn('\n  "기관"', out)  # 2-space indent
        self.assertEqual({"기관": [["c", 0.5]]}, json.loads(out))

    def test_main_check_flag_dispatches_to_run(self) -> None:
        with mock.patch.object(regen, "run", return_value=0) as run_mock:
            self.assertEqual(0, regen.main(["--check"]))
        run_mock.assert_called_once_with(check=True)

    def test_main_default_is_write(self) -> None:
        with mock.patch.object(regen, "run", return_value=0) as run_mock:
            self.assertEqual(0, regen.main([]))
        run_mock.assert_called_once_with(check=False)


class RegenGoldenDegradedGuardTest(unittest.TestCase):
    """A degraded/malformed rebuild must fail BOTH modes without being written.

    Exercises the real ``build_golden`` + ``_validate_rebuild`` by stubbing only
    its deps, so a retrieval/schema regression cannot be blessed into the golden
    (ADR 0001). Without the guard the write path would happily serialize a
    short/null rebuild and ``--check`` would later agree with it.
    """

    _HEALTHY_GOLDEN = {"q1": [["c1", 0.9], ["c2", 0.8]]}  # K=2

    def _run(self, results_by_query: dict, *, check: bool, golden_data: dict):
        """Run regen with ``run_rag_query`` stubbed per query (no real index).

        Returns ``(rc, before, after)`` where before/after are the on-disk golden
        text, so callers can assert a failed write left the file untouched.
        """

        def fake_run_rag_query(_index, query, **_kwargs):
            return results_by_query[query]

        with TemporaryDirectory() as d, mock.patch.object(
            regen, "build_index_payload", return_value={}
        ), mock.patch.object(regen, "run_rag_query", side_effect=fake_run_rag_query):
            golden = _write_golden(Path(d), golden_data)
            before = golden.read_text(encoding="utf-8")
            rc = regen.run(check=check, golden_path=golden)
            after = golden.read_text(encoding="utf-8")
        return rc, before, after

    # (a) retrieval returns fewer citations than the committed K.
    def test_fewer_citations_refuses_write(self) -> None:
        results = {"q1": {"citations": [{"chunk_id": "c1", "score": 0.9}]}}  # 1 < K=2
        rc, before, after = self._run(results, check=False, golden_data=self._HEALTHY_GOLDEN)
        self.assertEqual(1, rc)
        self.assertEqual(before, after)  # golden NOT overwritten with the short rebuild

    def test_fewer_citations_fails_check(self) -> None:
        results = {"q1": {"citations": [{"chunk_id": "c1", "score": 0.9}]}}
        rc, _, _ = self._run(results, check=True, golden_data=self._HEALTHY_GOLDEN)
        self.assertEqual(1, rc)

    # (b) retrieval returns no citations at all.
    def test_empty_citations_refuses_write(self) -> None:
        results = {"q1": {"citations": []}}
        rc, before, after = self._run(results, check=False, golden_data=self._HEALTHY_GOLDEN)
        self.assertEqual(1, rc)
        self.assertEqual(before, after)

    def test_empty_citations_fails_check(self) -> None:
        results = {"q1": {"citations": []}}
        rc, _, _ = self._run(results, check=True, golden_data=self._HEALTHY_GOLDEN)
        self.assertEqual(1, rc)

    # (c) schema regression: citations missing chunk_id / score -> None entries.
    def test_missing_chunk_id_or_score_refuses_write(self) -> None:
        results = {"q1": {"citations": [{"score": 0.9}, {"chunk_id": "c2"}]}}
        rc, before, after = self._run(results, check=False, golden_data=self._HEALTHY_GOLDEN)
        self.assertEqual(1, rc)
        self.assertEqual(before, after)

    def test_missing_chunk_id_or_score_fails_check(self) -> None:
        results = {"q1": {"citations": [{"score": 0.9}, {"chunk_id": "c2"}]}}
        rc, _, _ = self._run(results, check=True, golden_data=self._HEALTHY_GOLDEN)
        self.assertEqual(1, rc)

    # Positive control: a full, well-formed rebuild still writes (no false positive).
    def test_healthy_rebuild_still_writes(self) -> None:
        results = {"q1": {"citations": [{"chunk_id": "n1", "score": 0.5}, {"chunk_id": "n2", "score": 0.4}]}}
        stale = {"q1": [["old1", 0.1], ["old2", 0.0]]}
        rc, _, after = self._run(results, check=False, golden_data=stale)
        self.assertEqual(0, rc)
        self.assertEqual({"q1": [["n1", 0.5], ["n2", 0.4]]}, json.loads(after))

    def test_build_golden_raises_on_degraded_rebuild(self) -> None:
        with mock.patch.object(regen, "build_index_payload", return_value={}), mock.patch.object(
            regen, "run_rag_query", return_value={"citations": []}
        ):
            with self.assertRaises(regen.DegradedRebuildError):
                regen.build_golden({"q1": [["c1", 0.9]]})


if __name__ == "__main__":
    unittest.main()
