"""Schema + contract guards for the real-eval hardcase generator (issue #935).

The generator (``scripts/generate_real_cases.py``) is consumer-zero at
land time (PR-A): no eval config wired to it yet. These tests are the
forward contract — they pin

  (a) the stub backend is deterministic enough to test schema/abstention
      contracts without an Anthropic SDK call, and
  (b) the generated YAML drops straight into ``eval/run_eval.py``'s
      case-loader without schema drift,

so when ADR 0052 + baseline regen lands in PR-B and the local workflow
appends generator output to ``eval/real_config.local.yaml``, a loader
change can't silently invalidate the generator's output.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

# Add project root to sys.path so we can import the script as a module.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import generate_real_cases  # noqa: E402
from eval.run_eval import load_config  # noqa: E402


SAMPLE_DOC = {
    "doc_id": "rfp-test-sample",
    "title": "테스트 기관 X 시범 사업 RFP",
    "agency": "기관 X",
    "project": "시범 사업",
    "sections": [
        {"heading": "사업 개요", "text": "본 사업은 테스트 목적이다."},
        {"heading": "거버넌스", "text": "운영 위원회 정족수 미달 시 차회로 이월한다."},
    ],
}


class StubBackendSchemaTest(unittest.TestCase):
    """Stub backend generates loader-compatible YAML deterministically."""

    def test_generated_yaml_loads_via_run_eval_case_loader(self) -> None:
        cases = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=5, backend="stub", seed=17
        )
        # Wrap into a minimal but loader-valid eval config (mode + index_dir +
        # ablation_runs + answer_policy). The loader's case-side validation
        # is what we're testing.
        config_payload = {
            "mode": "rag",
            "index_dir": "data/index/real100",
            "answer_policy": {
                "answerable_status": "supported",
                "unanswerable_status": "insufficient",
                "min_claims_answerable": 1,
                "require_claim_citations": True,
            },
            "ablation_runs": [{"name": "full"}],
            "cases": cases,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.safe_dump(config_payload, tmp, allow_unicode=True, sort_keys=False)
            tmp_path = Path(tmp.name)
        try:
            loaded = load_config(tmp_path)
        finally:
            tmp_path.unlink()
        self.assertEqual(len(loaded["cases"]), 5)
        for case in loaded["cases"]:
            self.assertIn(
                case["query_type"], generate_real_cases.VALID_QUERY_TYPES
            )

    def test_every_case_carries_a_recognized_hardcase_enum(self) -> None:
        cases = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=5, backend="stub", seed=17
        )
        for case in cases:
            categories = case.get("hardcase_categories") or []
            recognized = [c for c in categories if c in generate_real_cases.HARDCASE_ENUMS]
            self.assertTrue(
                recognized,
                f"case {case.get('id')!r} has no recognized hardcase enum "
                f"(got {categories!r}; expected ⊆ {generate_real_cases.HARDCASE_ENUMS})",
            )

    def test_unanswerable_case_strips_expected_terms(self) -> None:
        """``answerable=false`` is the abstention contract — no positive
        evidence assertions allowed, even if the LLM hallucinated some."""
        # Inject a malicious LLM-style case with answerable=false but
        # nonempty expected_terms; normalization must scrub them.
        normalized = generate_real_cases._normalize_case(
            {
                "id": "real_x_no_answer_bad",
                "query_type": "abstention",
                "query": "doc 에 없는 질문",
                "expected_doc_ids": ["something"],
                "expected_terms": ["should be stripped"],
                "expected_citation_terms": ["also stripped"],
                "answerable": False,
                "hardcase_categories": ["no_answer"],
            },
            SAMPLE_DOC,
        )
        self.assertFalse(normalized["answerable"])
        self.assertEqual([], normalized["expected_terms"])
        self.assertEqual([], normalized["expected_citation_terms"])

    def test_case_ids_carry_real_prefix(self) -> None:
        cases = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=3, backend="stub", seed=17
        )
        for case in cases:
            self.assertTrue(
                case["id"].startswith("real_"),
                f"case id {case['id']!r} missing real_ prefix",
            )

    def test_stub_backend_is_deterministic_for_same_seed(self) -> None:
        a = generate_real_cases.generate_cases(SAMPLE_DOC, k=5, backend="stub", seed=17)
        b = generate_real_cases.generate_cases(SAMPLE_DOC, k=5, backend="stub", seed=17)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class CLIContractTest(unittest.TestCase):
    """CLI surface — help text + main() exit code + file output."""

    def test_help_lists_all_five_hardcase_enums(self) -> None:
        # argparse calls sys.exit on --help; capture and inspect.
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with self.assertRaises(SystemExit):
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                generate_real_cases.parse_args(["--help"])
        help_text = buf_out.getvalue()
        for enum_value in generate_real_cases.HARDCASE_ENUMS:
            self.assertIn(enum_value, help_text, f"--help missing enum {enum_value!r}")

    def test_main_writes_yaml_when_output_path_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "raw"
            raw_dir.mkdir()
            (raw_dir / "rfp-test-sample.json").write_text(
                json.dumps(SAMPLE_DOC, ensure_ascii=False), encoding="utf-8"
            )
            out_path = Path(tmpdir) / "out.yaml"
            with mock.patch.dict("os.environ", {"BIDMATE_HARDCASE_BACKEND": "stub"}):
                rc = generate_real_cases.main(
                    [
                        "--doc-id", "rfp-test-sample",
                        "--k", "3",
                        "--raw-dir", str(raw_dir),
                        "--output", str(out_path),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            self.assertIn("cases", loaded)
            self.assertEqual(3, len(loaded["cases"]))

    def test_main_errors_without_doc_id_or_batch(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = generate_real_cases.main([])
        self.assertEqual(2, rc)
        self.assertIn("--doc-id", buf.getvalue())

    def test_anthropic_backend_falls_back_to_clear_error_without_api_key(
        self,
    ) -> None:
        """Without API key, anthropic backend must raise an actionable error
        pointing operators to the env vars or the stub fallback."""
        # Ensure no API key in env.
        env_patch = {
            k: v
            for k, v in {"BIDMATE_HARDCASE_API_KEY": None}.items()
            if v is not None
        }
        with mock.patch.dict("os.environ", env_patch, clear=False):
            # Pop the var if present.
            import os as _os
            _os.environ.pop("BIDMATE_HARDCASE_API_KEY", None)
            # Skip if the anthropic SDK isn't even installed — then the
            # import-time RuntimeError fires first, which is still the
            # right behavior (caller gets actionable guidance either way).
            try:
                import anthropic  # noqa: F401
            except Exception:
                self.skipTest("anthropic SDK not installed; import-time error path covered.")
            with self.assertRaises(RuntimeError) as ctx:
                generate_real_cases._anthropic_backend(SAMPLE_DOC, k=2, seed=17)
            self.assertIn("BIDMATE_HARDCASE_API_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
