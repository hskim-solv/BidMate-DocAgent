"""Pipeline-level regression tests for the case proposer (ADR 0029, PR2).

Covers the end-to-end shape of ``propose_cases_from_files`` (CSV
reader + index reader + stub generation), the deterministic YAML
writer, the review walk's branching logic, and the promote step's
idempotency + meta-stripping. PR1 invariants (Protocol, backend
dispatch, ADR 0001 import surface guard) stay in
``tests/test_case_proposer_stub.py``.
"""
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import yaml

from eval.case_proposer import (
    CSV_COLUMN_AGENCY,
    CSV_COLUMN_FILE_FORMAT,
    CSV_COLUMN_FILE_NAME,
    CSV_COLUMN_NOTICE_ID,
    CSV_COLUMN_PROJECT,
    CSV_COLUMN_TEXT,
    CaseProposerInputError,
    REQUIRED_CSV_COLUMNS,
    propose_cases,
    propose_cases_from_files,
    write_proposed_yaml,
)
from scripts.case_proposer_promote import (
    PROPOSER_META_FIELDS,
    promote_cases,
)
from scripts.case_proposer_review import (
    read_proposed_yaml,
    walk_review_session,
    write_reviewed_yaml,
)

NOW_FIXED = "2026-05-13T08:00:00Z"


def _make_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REQUIRED_CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_index(path: Path, doc_ids: list[str]) -> None:
    payload = {
        "schema_version": 2,
        "build": {
            "documents": [{"doc_id": d} for d in doc_ids],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _sample_row(
    notice_id: str = "K2026-001",
    agency: str = "A기관",
    project: str = "사업A",
) -> dict[str, str]:
    return {
        CSV_COLUMN_NOTICE_ID: notice_id,
        CSV_COLUMN_PROJECT: project,
        CSV_COLUMN_AGENCY: agency,
        CSV_COLUMN_FILE_FORMAT: "pdf",
        CSV_COLUMN_FILE_NAME: f"{notice_id}.pdf",
        CSV_COLUMN_TEXT: "본문 텍스트",
    }


class StubBackendGenerationTest(unittest.TestCase):
    def test_two_templates_per_row_with_doc_id(self) -> None:
        rows = [{"doc_id": "doc-001", CSV_COLUMN_AGENCY: "기관A", CSV_COLUMN_PROJECT: "사업A"}]
        cases = propose_cases(rows, backend="stub", now_iso=NOW_FIXED)
        self.assertEqual(len(cases), 2)
        single_doc, abstention = cases
        self.assertEqual(single_doc["query_type"], "single_doc")
        self.assertEqual(single_doc["expected_doc_ids"], ["doc-001"])
        self.assertTrue(single_doc["answerable"])
        self.assertEqual(abstention["query_type"], "abstention")
        self.assertEqual(abstention["expected_doc_ids"], [])
        self.assertFalse(abstention["answerable"])

    def test_skip_rows_without_doc_id(self) -> None:
        rows = [
            {"doc_id": "", CSV_COLUMN_AGENCY: "기관A", CSV_COLUMN_PROJECT: "사업A"},
            {"doc_id": "doc-001", CSV_COLUMN_AGENCY: "기관B", CSV_COLUMN_PROJECT: "사업B"},
        ]
        cases = propose_cases(rows, backend="stub", now_iso=NOW_FIXED)
        # Only the row with a doc_id produces cases (2 templates).
        self.assertEqual(len(cases), 2)
        for case in cases:
            self.assertEqual(case["proposer_meta"]["seed_doc_id"], "doc-001")

    def test_proposed_id_uses_iso_date_prefix(self) -> None:
        rows = [{"doc_id": "doc-001"}]
        cases = propose_cases(rows, backend="stub", now_iso="2026-05-13T12:34:56Z")
        self.assertEqual(cases[0]["id"], "proposed_20260513_001")
        self.assertEqual(cases[1]["id"], "proposed_20260513_002")

    def test_required_csv_columns_match_ingestion_module(self) -> None:
        """Drift guard: case_proposer hard-codes the column names to
        stay free of rag_core-transitive imports. This test confirms
        the duplicated list still matches ``ingestion.REQUIRED_COLUMNS``.
        """
        from ingestion import REQUIRED_COLUMNS as INGESTION_REQUIRED

        self.assertEqual(set(REQUIRED_CSV_COLUMNS), set(INGESTION_REQUIRED))


class ProposeCasesFromFilesTest(unittest.TestCase):
    def test_end_to_end_yields_deterministic_cases(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path = td_path / "data_list.csv"
            index_dir = td_path / "index"
            index_dir.mkdir()
            _make_csv(csv_path, [
                _sample_row("K2026-001", "기관A", "사업A"),
                _sample_row("K2026-002", "기관B", "사업B"),
            ])
            _make_index(index_dir / "index.json", ["K2026-001", "K2026-002"])

            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=10,
                backend="stub",
                now_iso=NOW_FIXED,
            )
            self.assertEqual(len(cases), 4)
            # Re-run produces byte-equal cases.
            cases2 = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=10,
                backend="stub",
                now_iso=NOW_FIXED,
            )
            self.assertEqual(cases, cases2)

    def test_raises_when_no_csv_row_matches_index(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path = td_path / "data_list.csv"
            index_dir = td_path / "index"
            index_dir.mkdir()
            _make_csv(csv_path, [_sample_row("K2026-001")])
            _make_index(index_dir / "index.json", ["does-not-match"])

            with self.assertRaises(CaseProposerInputError):
                propose_cases_from_files(
                    metadata_csv=csv_path,
                    index_dir=index_dir,
                    n_seed_docs=10,
                    backend="stub",
                    now_iso=NOW_FIXED,
                )

    def test_n_seed_docs_caps_selection(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path = td_path / "data_list.csv"
            index_dir = td_path / "index"
            index_dir.mkdir()
            _make_csv(csv_path, [
                _sample_row(f"K2026-{i:03d}", f"기관{i}", f"사업{i}")
                for i in range(1, 6)
            ])
            _make_index(
                index_dir / "index.json",
                [f"K2026-{i:03d}" for i in range(1, 6)],
            )
            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=2,
                backend="stub",
                now_iso=NOW_FIXED,
            )
            self.assertEqual(len(cases), 4)  # 2 docs * 2 templates


class YamlWriterTest(unittest.TestCase):
    def test_write_proposed_yaml_is_byte_equal_across_runs(self) -> None:
        rows = [{"doc_id": "doc-001", CSV_COLUMN_AGENCY: "기관A", CSV_COLUMN_PROJECT: "사업A"}]
        cases = propose_cases(rows, backend="stub", now_iso=NOW_FIXED)
        with TemporaryDirectory() as td:
            path_a = Path(td) / "a.yaml"
            path_b = Path(td) / "b.yaml"
            write_proposed_yaml(cases, path_a)
            write_proposed_yaml(cases, path_b)
            self.assertEqual(
                path_a.read_text(encoding="utf-8"),
                path_b.read_text(encoding="utf-8"),
            )

    def test_write_proposed_yaml_round_trips_via_pyyaml(self) -> None:
        rows = [{"doc_id": "doc-001", CSV_COLUMN_AGENCY: "기관A", CSV_COLUMN_PROJECT: "사업A"}]
        cases = propose_cases(rows, backend="stub", now_iso=NOW_FIXED)
        with TemporaryDirectory() as td:
            path = Path(td) / "proposed.yaml"
            write_proposed_yaml(cases, path)
            read_back = read_proposed_yaml(path)
            self.assertEqual(len(read_back), len(cases))
            self.assertEqual(read_back[0]["id"], cases[0]["id"])
            self.assertEqual(read_back[0]["query_type"], "single_doc")
            self.assertEqual(read_back[0]["expected_doc_ids"], ["doc-001"])

    def test_write_proposed_yaml_empty_list(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "empty.yaml"
            write_proposed_yaml([], path)
            content = path.read_text(encoding="utf-8")
            self.assertIn("proposed_cases: []", content)
            self.assertEqual(read_proposed_yaml(path), [])


class ReviewWalkSessionTest(unittest.TestCase):
    def _sample_proposed(self) -> list[dict[str, Any]]:
        rows = [{"doc_id": "doc-001", CSV_COLUMN_AGENCY: "기관A", CSV_COLUMN_PROJECT: "사업A"}]
        return propose_cases(rows, backend="stub", now_iso=NOW_FIXED)

    def test_accept_path_records_approved_true(self) -> None:
        proposed = self._sample_proposed()
        choices = iter(["a", "a"])  # accept both
        reviewed = walk_review_session(
            proposed,
            prompt_fn=lambda _p: next(choices),
            edit_fn=lambda c: c,
            now_iso_fn=lambda: NOW_FIXED,
            write_fn=lambda _m: None,
        )
        self.assertEqual(len(reviewed), 2)
        for case in reviewed:
            self.assertTrue(case["approved"])
            self.assertFalse(case["review_meta"]["edited"])

    def test_reject_path_records_approved_false(self) -> None:
        proposed = self._sample_proposed()
        choices = iter(["r", "r"])
        reviewed = walk_review_session(
            proposed,
            prompt_fn=lambda _p: next(choices),
            edit_fn=lambda c: c,
            now_iso_fn=lambda: NOW_FIXED,
            write_fn=lambda _m: None,
        )
        self.assertEqual(len(reviewed), 2)
        for case in reviewed:
            self.assertFalse(case["approved"])

    def test_edit_path_replaces_case_body_and_flags_edited(self) -> None:
        proposed = self._sample_proposed()
        choices = iter(["e", "a"])

        def fake_edit(case: dict[str, Any]) -> dict[str, Any]:
            return {**case, "query": "edited query"}

        reviewed = walk_review_session(
            proposed,
            prompt_fn=lambda _p: next(choices),
            edit_fn=fake_edit,
            now_iso_fn=lambda: NOW_FIXED,
            write_fn=lambda _m: None,
        )
        self.assertEqual(len(reviewed), 2)
        self.assertTrue(reviewed[0]["approved"])
        self.assertTrue(reviewed[0]["review_meta"]["edited"])
        self.assertEqual(reviewed[0]["query"], "edited query")

    def test_skip_path_omits_case_from_output(self) -> None:
        proposed = self._sample_proposed()
        choices = iter(["s", "a"])
        reviewed = walk_review_session(
            proposed,
            prompt_fn=lambda _p: next(choices),
            edit_fn=lambda c: c,
            now_iso_fn=lambda: NOW_FIXED,
            write_fn=lambda _m: None,
        )
        # First case skipped → only second case in output.
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0]["id"], proposed[1]["id"])

    def test_quit_path_stops_walk(self) -> None:
        proposed = self._sample_proposed()
        choices = iter(["a", "q"])
        reviewed = walk_review_session(
            proposed,
            prompt_fn=lambda _p: next(choices),
            edit_fn=lambda c: c,
            now_iso_fn=lambda: NOW_FIXED,
            write_fn=lambda _m: None,
        )
        self.assertEqual(len(reviewed), 1)
        self.assertTrue(reviewed[0]["approved"])

    def test_help_path_re_prompts(self) -> None:
        proposed = self._sample_proposed()[:1]
        choices = iter(["?", "a"])
        messages: list[str] = []
        reviewed = walk_review_session(
            proposed,
            prompt_fn=lambda _p: next(choices),
            edit_fn=lambda c: c,
            now_iso_fn=lambda: NOW_FIXED,
            write_fn=messages.append,
        )
        self.assertEqual(len(reviewed), 1)
        self.assertTrue(any("help" in m.lower() or "accept" in m.lower() for m in messages))


class PromoteIdempotencyTest(unittest.TestCase):
    def _approved_reviewed(self, ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": case_id,
                "source": "proposed-then-reviewed",
                "proposer_meta": {
                    "backend": "stub",
                    "model": "stub",
                    "seed_doc_id": case_id,
                    "generated_at": NOW_FIXED,
                    "proposer_version": 1,
                },
                "query_type": "single_doc",
                "query": f"query for {case_id}",
                "expected_doc_ids": [case_id],
                "expected_terms": [],
                "expected_citation_terms": [],
                "expected_claim_targets": [],
                "answerable": True,
                "approved": True,
                "review_meta": {"reviewed_at": NOW_FIXED, "edited": False},
            }
            for case_id in ids
        ]

    def _empty_real_config(self) -> dict[str, Any]:
        return {"mode": "rag", "cases": []}

    def test_appends_only_approved_cases(self) -> None:
        reviewed = self._approved_reviewed(["a", "b"])
        reviewed[1]["approved"] = False  # b is rejected
        config, n_appended, n_skipped = promote_cases(
            reviewed, self._empty_real_config()
        )
        self.assertEqual(n_appended, 1)
        self.assertEqual(n_skipped, 1)
        self.assertEqual([c["id"] for c in config["cases"]], ["a"])

    def test_strips_proposer_and_review_meta(self) -> None:
        reviewed = self._approved_reviewed(["a"])
        config, _, _ = promote_cases(reviewed, self._empty_real_config())
        promoted = config["cases"][0]
        for forbidden in PROPOSER_META_FIELDS:
            self.assertNotIn(forbidden, promoted)
        # Schema-fields preserved.
        self.assertEqual(promoted["id"], "a")
        self.assertEqual(promoted["query_type"], "single_doc")
        self.assertEqual(promoted["expected_doc_ids"], ["a"])

    def test_second_promote_is_idempotent(self) -> None:
        reviewed = self._approved_reviewed(["a", "b"])
        config, n1, _ = promote_cases(reviewed, self._empty_real_config())
        self.assertEqual(n1, 2)
        config_after, n2, n_skipped2 = promote_cases(reviewed, config)
        self.assertEqual(n2, 0)
        self.assertEqual(n_skipped2, 2)
        self.assertEqual(
            [c["id"] for c in config_after["cases"]],
            ["a", "b"],
        )

    def test_preexisting_cases_block_appended_duplicate(self) -> None:
        reviewed = self._approved_reviewed(["a"])
        config = {
            "mode": "rag",
            "cases": [{"id": "a", "query": "preexisting"}],
        }
        new_config, n_appended, n_skipped = promote_cases(reviewed, config)
        self.assertEqual(n_appended, 0)
        self.assertEqual(n_skipped, 1)
        # Original case preserved untouched.
        self.assertEqual(new_config["cases"][0]["query"], "preexisting")


if __name__ == "__main__":
    unittest.main()
