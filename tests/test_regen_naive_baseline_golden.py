"""Regression guard for the naive_baseline golden regenerator CLI wiring.

Covers the ``--check`` exit codes, the write round-trip, query-set/length
preservation, and the committed serialization style of
``scripts/regen_naive_baseline_golden.py`` WITHOUT building a real index —
``build_golden`` is monkeypatched so these stay fast + deterministic. The real
index-build correctness is covered by
``tests/test_naive_baseline_ranking_invariance.py``, which imports the same
``build_golden``.
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


if __name__ == "__main__":
    unittest.main()
