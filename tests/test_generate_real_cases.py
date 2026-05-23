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


SAMPLE_DOC_SAME_AGENCY = {
    "doc_id": "rfp-test-sample-2",
    "title": "테스트 기관 X 후속 사업 RFP",
    "agency": "기관 X",
    "project": "후속 사업",
    "sections": [
        {"heading": "추진 배경", "text": "후속 사업의 배경을 기술한다."},
        {"heading": "검수 기준", "text": "산출물 검수 위원회를 운영한다."},
    ],
}


class IdCollisionTest(unittest.TestCase):
    """F1 — case ids must embed doc_id so same-agency docs don't collide."""

    def test_stub_ids_embed_slugified_doc_id(self) -> None:
        doc_slug = generate_real_cases._slugify(SAMPLE_DOC["doc_id"])
        cases = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=5, backend="stub", seed=17
        )
        self.assertTrue(cases)
        for case in cases:
            self.assertIn(
                doc_slug,
                case["id"],
                f"case id {case['id']!r} missing doc slug {doc_slug!r}",
            )

    def test_same_agency_distinct_docs_produce_no_duplicate_ids(self) -> None:
        # Pre-fix, both docs (same agency "기관 X") emitted
        # real_x_<category>_<i> with no doc_id — guaranteed collision.
        cases_a = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=5, backend="stub", seed=17
        )
        cases_b = generate_real_cases.generate_cases(
            SAMPLE_DOC_SAME_AGENCY, k=5, backend="stub", seed=17
        )
        self.assertEqual(
            [], generate_real_cases.find_duplicate_ids(cases_a + cases_b)
        )

    def test_find_duplicate_ids_flags_collisions(self) -> None:
        cases = [
            {"id": "real_x_a_1"},
            {"id": "real_x_a_1"},
            {"id": "real_x_b_2"},
        ]
        self.assertEqual(
            ["real_x_a_1"], generate_real_cases.find_duplicate_ids(cases)
        )

    def test_main_fails_before_write_on_duplicate_ids(self) -> None:
        colliding = {
            "id": "real_dup_collision_1",
            "query_type": "single_doc",
            "query": "q",
            "expected_doc_ids": [],
            "expected_terms": [],
            "expected_citation_terms": [],
            "answerable": False,
            "hardcase_categories": ["no_answer"],
            "generation_notes": "",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "raw"
            raw_dir.mkdir()
            for stem, doc in (
                ("d1", SAMPLE_DOC),
                ("d2", SAMPLE_DOC_SAME_AGENCY),
            ):
                (raw_dir / f"{stem}.json").write_text(
                    json.dumps(doc, ensure_ascii=False), encoding="utf-8"
                )
            out_path = Path(tmpdir) / "out.yaml"
            buf = io.StringIO()
            with mock.patch.object(
                generate_real_cases, "generate_cases", return_value=[dict(colliding)]
            ), redirect_stderr(buf):
                rc = generate_real_cases.main(
                    [
                        "--batch", "2",
                        "--raw-dir", str(raw_dir),
                        "--output", str(out_path),
                    ]
                )
            self.assertEqual(2, rc)
            self.assertIn("duplicate case ids", buf.getvalue())
            self.assertFalse(
                out_path.exists(), "must refuse to write when ids collide"
            )


class StrictValidationTest(unittest.TestCase):
    """F2 — _normalize_case rejects malformed output instead of coercing."""

    def test_string_false_answerable_is_rejected(self) -> None:
        with self.assertRaises(generate_real_cases.CaseValidationError):
            generate_real_cases._normalize_case(
                {
                    "id": "real_x_no_answer_1",
                    "query_type": "abstention",
                    "query": "q",
                    "answerable": "false",  # truthy string — must not pass as True
                    "hardcase_categories": ["no_answer"],
                },
                SAMPLE_DOC,
            )

    def test_empty_hardcase_categories_is_rejected(self) -> None:
        with self.assertRaises(generate_real_cases.CaseValidationError):
            generate_real_cases._normalize_case(
                {
                    "id": "real_x_1",
                    "query_type": "single_doc",
                    "query": "q",
                    "answerable": True,
                    "hardcase_categories": [],
                },
                SAMPLE_DOC,
            )

    def test_unknown_hardcase_category_is_rejected(self) -> None:
        with self.assertRaises(generate_real_cases.CaseValidationError):
            generate_real_cases._normalize_case(
                {
                    "id": "real_x_1",
                    "query_type": "single_doc",
                    "query": "q",
                    "answerable": True,
                    "hardcase_categories": ["totally_made_up"],
                },
                SAMPLE_DOC,
            )

    def test_unknown_query_type_is_rejected_not_rewritten(self) -> None:
        with self.assertRaises(generate_real_cases.CaseValidationError):
            generate_real_cases._normalize_case(
                {
                    "id": "real_x_1",
                    "query_type": "freeform_chat",
                    "query": "q",
                    "answerable": True,
                    "hardcase_categories": ["multi_hop"],
                },
                SAMPLE_DOC,
            )

    def test_generate_cases_drops_invalid_and_reports(self) -> None:
        fake_backend = lambda *_: [  # noqa: E731
            {
                "id": "real_x_good_1",
                "query_type": "single_doc",
                "query": "q",
                "answerable": True,
                "expected_terms": ["거버넌스"],
                "expected_citation_terms": ["거버넌스"],
                "hardcase_categories": ["multi_hop"],
            },
            {  # malformed: string answerable
                "id": "real_x_bad_2",
                "query_type": "single_doc",
                "query": "q",
                "answerable": "false",
                "hardcase_categories": ["multi_hop"],
            },
        ]
        buf = io.StringIO()
        with mock.patch.dict(
            generate_real_cases._BACKENDS, {"fake": fake_backend}, clear=False
        ), redirect_stderr(buf):
            cases = generate_real_cases.generate_cases(
                SAMPLE_DOC, k=2, backend="fake", seed=17
            )
        self.assertEqual(1, len(cases))
        self.assertEqual("real_rfp_test_sample_x_good_1", cases[0]["id"])
        self.assertIn("drop (invalid", buf.getvalue())


class GroundingTest(unittest.TestCase):
    """F3/F4 — answerable gold terms must exist in the source document."""

    def test_stub_answerable_terms_are_grounded_in_doc(self) -> None:
        doc_text = generate_real_cases._doc_text(SAMPLE_DOC).lower()
        cases = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=5, backend="stub", seed=17
        )
        answerable = [c for c in cases if c["answerable"]]
        self.assertTrue(answerable)
        for case in answerable:
            for term in case["expected_terms"]:
                self.assertIn(
                    term.lower(),
                    doc_text,
                    f"stub emitted off-document term {term!r} for {case['id']!r}",
                )

    def test_stub_does_not_emit_fixed_offdoc_template_terms(self) -> None:
        # SAMPLE_DOC contains neither "약칭" nor "부속서"; the pre-fix stub
        # would have emitted them verbatim from its fixed templates.
        cases = generate_real_cases.generate_cases(
            SAMPLE_DOC, k=5, backend="stub", seed=17
        )
        emitted = {t for c in cases for t in c["expected_terms"]}
        self.assertNotIn("약칭", emitted)
        self.assertNotIn("부속서", emitted)

    def test_generate_cases_drops_ungrounded_answerable_case(self) -> None:
        fake_backend = lambda *_: [  # noqa: E731
            {
                "id": "real_x_hallucinated_1",
                "query_type": "single_doc",
                "query": "q",
                "answerable": True,
                "expected_terms": ["우주선 추진계"],  # absent from SAMPLE_DOC
                "expected_citation_terms": [],
                "hardcase_categories": ["long_context"],
            }
        ]
        buf = io.StringIO()
        with mock.patch.dict(
            generate_real_cases._BACKENDS, {"fake": fake_backend}, clear=False
        ), redirect_stderr(buf):
            cases = generate_real_cases.generate_cases(
                SAMPLE_DOC, k=1, backend="fake", seed=17
            )
        self.assertEqual([], cases)
        self.assertIn("drop (ungrounded", buf.getvalue())

    def test_build_section_summary_covers_tail_sections(self) -> None:
        big_doc = {
            "doc_id": "rfp-big",
            "agency": "기관 Z",
            "title": "대형 RFP",
            "sections": [
                {"heading": f"섹션 {i}", "text": f"본문 {i}"} for i in range(40)
            ],
        }
        summary = generate_real_cases._build_section_summary(big_doc)
        # Pre-fix the prompt truncated to sections[:15]; the appendix-style
        # tail heading must now reach the model.
        self.assertIn("섹션 39", summary)


if __name__ == "__main__":
    unittest.main()
