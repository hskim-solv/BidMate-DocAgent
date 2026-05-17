"""Tests for the CSV-metadata case proposer backend (ADR 0048 / issue #880).

This is a sibling of ``test_case_proposer_stub.py`` (which pins the stub
backend's deterministic 2-templates-per-row contract). The CSV-metadata
backend bridges ``data/data_list.csv`` directly to ADR 0048's
``by_metadata_field`` aggregate without an LLM pass:

- emits up to 4 ``single_doc`` cases per row (one per metadata_field)
- ``expected_terms`` populated verbatim from the CSV cell
- each case carries the ADR 0048 ``metadata_field`` tag
- skips fields whose cell is empty (no fabricated gold)
- byte-equal across runs (deterministic, same guarantee as stub)
"""
from __future__ import annotations

import unittest

from eval.case_proposer import (
    CSV_COLUMN_AGENCY,
    CSV_COLUMN_BUDGET,
    CSV_COLUMN_DEADLINE,
    CSV_COLUMN_PROJECT,
    CSV_METADATA_FIELD_SOURCES,
    propose_cases,
    resolve_backend,
    write_proposed_yaml,
)
from eval.scorers._shared import METADATA_FIELD_KEYS


def _seed_row(
    *,
    doc_id: str = "doc-001",
    agency: str = "A기관",
    project: str = "사업A",
    budget: str = "1,234,567,890",
    deadline: str = "2026-06-30T17:00:00",
) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        CSV_COLUMN_AGENCY: agency,
        CSV_COLUMN_PROJECT: project,
        CSV_COLUMN_BUDGET: budget,
        CSV_COLUMN_DEADLINE: deadline,
    }


class CsvMetadataBackendBasicsTest(unittest.TestCase):
    def test_resolves_via_explicit_arg(self) -> None:
        name, _ = resolve_backend("csv_metadata")
        self.assertEqual(name, "csv_metadata")

    def test_resolves_via_env_var(self) -> None:
        import os

        prev = os.environ.get("BIDMATE_CASE_PROPOSER_BACKEND")
        os.environ["BIDMATE_CASE_PROPOSER_BACKEND"] = "csv_metadata"
        try:
            name, _ = resolve_backend()
            self.assertEqual(name, "csv_metadata")
        finally:
            if prev is None:
                os.environ.pop("BIDMATE_CASE_PROPOSER_BACKEND", None)
            else:
                os.environ["BIDMATE_CASE_PROPOSER_BACKEND"] = prev

    def test_empty_rows_emits_no_cases(self) -> None:
        out = propose_cases([], backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        self.assertEqual(out, [])

    def test_row_without_doc_id_skipped(self) -> None:
        row = _seed_row()
        row["doc_id"] = ""
        out = propose_cases(
            [row], backend="csv_metadata", now_iso="2026-05-15T00:00:00Z"
        )
        self.assertEqual(out, [])


class CsvMetadataBackendOutputShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now_iso = "2026-05-15T00:00:00Z"
        self.cases = propose_cases(
            [_seed_row()], backend="csv_metadata", now_iso=self.now_iso
        )

    def test_full_row_emits_4_cases_one_per_field(self) -> None:
        self.assertEqual(len(self.cases), 4)
        emitted_fields = [c["metadata_field"] for c in self.cases]
        self.assertEqual(emitted_fields, ["agency", "project", "budget", "deadline"])

    def test_all_cases_are_single_doc_answerable(self) -> None:
        for case in self.cases:
            self.assertEqual(case["query_type"], "single_doc")
            self.assertTrue(case["answerable"])
            self.assertEqual(case["expected_doc_ids"], ["doc-001"])

    def test_metadata_field_tag_uses_adr_0048_enum(self) -> None:
        for case in self.cases:
            self.assertIn(case["metadata_field"], METADATA_FIELD_KEYS)

    def test_expected_terms_are_csv_cell_verbatim(self) -> None:
        # Map each metadata_field back to the cell value the backend
        # claimed it pulled in.
        seen = {c["metadata_field"]: c["expected_terms"] for c in self.cases}
        self.assertEqual(seen["agency"], ["A기관"])
        self.assertEqual(seen["project"], ["사업A"])
        self.assertEqual(seen["budget"], ["1,234,567,890"])
        self.assertEqual(seen["deadline"], ["2026-06-30T17:00:00"])

    def test_expected_citation_terms_and_claim_targets_mirror_terms(self) -> None:
        for case in self.cases:
            self.assertEqual(
                case["expected_citation_terms"], case["expected_terms"]
            )
            self.assertEqual(
                case["expected_claim_targets"], case["expected_terms"]
            )

    def test_proposer_meta_marks_backend(self) -> None:
        for case in self.cases:
            self.assertEqual(case["proposer_meta"]["backend"], "csv_metadata")
            self.assertEqual(case["proposer_meta"]["seed_doc_id"], "doc-001")
            self.assertEqual(case["proposer_meta"]["generated_at"], self.now_iso)


class CsvMetadataBackendDeterminismTest(unittest.TestCase):
    def test_byte_equal_across_runs(self) -> None:
        rows = [_seed_row(doc_id=f"doc-{i:03d}") for i in range(3)]
        runs = [
            propose_cases(rows, backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
            for _ in range(5)
        ]
        for run in runs[1:]:
            self.assertEqual(run, runs[0])

    def test_iteration_order_follows_field_sources_declaration(self) -> None:
        rows = [_seed_row()]
        out = propose_cases(rows, backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        expected_order = [field_key for field_key, _, _ in CSV_METADATA_FIELD_SOURCES]
        self.assertEqual([c["metadata_field"] for c in out], expected_order)

    def test_counter_increments_across_rows_and_fields(self) -> None:
        rows = [
            _seed_row(doc_id="doc-001"),
            _seed_row(doc_id="doc-002"),
        ]
        out = propose_cases(rows, backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        ids = [c["id"] for c in out]
        # 2 rows * 4 fields = 8 cases, ids should be sequential
        self.assertEqual(len(ids), 8)
        suffixes = [int(case_id.split("_")[-1]) for case_id in ids]
        self.assertEqual(suffixes, list(range(1, 9)))


class CsvMetadataBackendEmptyCellSkipTest(unittest.TestCase):
    def test_empty_deadline_emits_3_cases(self) -> None:
        row = _seed_row(deadline="")
        out = propose_cases([row], backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        self.assertEqual(len(out), 3)
        self.assertEqual(
            [c["metadata_field"] for c in out],
            ["agency", "project", "budget"],
        )

    def test_empty_budget_and_deadline_emits_2_cases(self) -> None:
        row = _seed_row(budget="", deadline="")
        out = propose_cases([row], backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        self.assertEqual(len(out), 2)
        self.assertEqual(
            [c["metadata_field"] for c in out],
            ["agency", "project"],
        )

    def test_all_empty_cells_emits_no_cases(self) -> None:
        row = _seed_row(agency="", project="", budget="", deadline="")
        out = propose_cases([row], backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        self.assertEqual(out, [])

    def test_missing_optional_column_treated_as_empty(self) -> None:
        # data_list.csv at 92% deadline fill rate — some rows simply
        # don't have the column populated. Backend must skip silently
        # rather than emit a case with empty expected_terms.
        row = _seed_row()
        row.pop(CSV_COLUMN_DEADLINE)
        out = propose_cases([row], backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        self.assertEqual(len(out), 3)
        self.assertNotIn("deadline", [c["metadata_field"] for c in out])


class CsvMetadataBackendYamlRoundTripTest(unittest.TestCase):
    """The yaml writer was extended to emit ``metadata_field`` when
    present. This must round-trip through yaml.safe_load — the field
    is what `load_config` in eval/run_eval.py reads when validating
    against METADATA_FIELD_KEYS."""

    def test_yaml_writer_emits_metadata_field_tag(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        import yaml

        rows = [_seed_row()]
        cases = propose_cases(rows, backend="csv_metadata", now_iso="2026-05-15T00:00:00Z")
        with TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "proposed.yaml"
            write_proposed_yaml(cases, out_path)
            loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        self.assertIn("proposed_cases", loaded)
        loaded_cases = loaded["proposed_cases"]
        self.assertEqual(len(loaded_cases), 4)
        for case in loaded_cases:
            self.assertIn("metadata_field", case)
            self.assertIn(case["metadata_field"], METADATA_FIELD_KEYS)

    def test_yaml_writer_omits_metadata_field_for_stub_backend(self) -> None:
        """The stub backend produces cases without `metadata_field` keys.
        The writer's emission must stay absent (not ``null``) for those
        cases, so the historical stub byte-output is preserved."""
        from pathlib import Path
        from tempfile import TemporaryDirectory

        stub_cases = propose_cases(
            [{"doc_id": "doc-001", CSV_COLUMN_AGENCY: "A기관", CSV_COLUMN_PROJECT: "사업A"}],
            backend="stub",
            now_iso="2026-05-15T00:00:00Z",
        )
        with TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "stub.yaml"
            write_proposed_yaml(stub_cases, out_path)
            text = out_path.read_text(encoding="utf-8")
        self.assertNotIn("metadata_field", text)


if __name__ == "__main__":
    unittest.main()
