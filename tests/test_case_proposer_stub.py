"""Tests for the real-data case proposer skeleton (ADR 0029, PR1).

The stub backend ships empty in PR1 — these tests pin the skeleton's
shape (Protocol, backend dispatch, error surface) and the
ADR 0001 byte-identity guard: loading ``eval.case_proposer`` must not
pull in ``rag_core``, because the proposer is upstream of
``run_rag_query`` and any accidental dependency would risk a
side-effect on the naive baseline golden.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest

from eval.case_proposer import (
    BACKEND_ENV_VAR,
    DEFAULT_AGGREGATE_PATH,
    DEFAULT_PROPOSED_PATH,
    PROPOSER_VERSION,
    propose_cases,
    resolve_backend,
)


class CaseProposerStubTest(unittest.TestCase):
    def test_stub_returns_empty_list_in_pr1(self) -> None:
        """PR1 invariant: skeleton stub emits no candidates."""
        out = propose_cases([{"doc_id": "doc-001"}], backend="stub")
        self.assertEqual(out, [])

    def test_stub_deterministic_across_calls(self) -> None:
        """Stub must be byte-equal across runs (ADR 0011 stub-default contract)."""
        rows = [
            {"doc_id": "doc-001", "사업명": "사업A"},
            {"doc_id": "doc-002", "사업명": "사업B"},
        ]
        calls = [propose_cases(rows, backend="stub") for _ in range(5)]
        for result in calls[1:]:
            self.assertEqual(result, calls[0])

    def test_resolve_backend_default_is_stub(self) -> None:
        name, fn = resolve_backend()
        self.assertEqual(name, "stub")
        self.assertEqual(fn([], model="stub"), [])

    def test_resolve_backend_explicit_arg_wins_over_env(self) -> None:
        """Explicit ``name`` argument overrides $BIDMATE_CASE_PROPOSER_BACKEND."""
        import os

        prior = os.environ.get(BACKEND_ENV_VAR)
        os.environ[BACKEND_ENV_VAR] = "openai_compatible"
        try:
            name, _ = resolve_backend("stub")
            self.assertEqual(name, "stub")
        finally:
            if prior is None:
                os.environ.pop(BACKEND_ENV_VAR, None)
            else:
                os.environ[BACKEND_ENV_VAR] = prior

    def test_resolve_backend_env_var_overrides_default(self) -> None:
        import os

        prior = os.environ.get(BACKEND_ENV_VAR)
        os.environ[BACKEND_ENV_VAR] = "openai_compatible"
        try:
            name, _ = resolve_backend()
            self.assertEqual(name, "openai_compatible")
        finally:
            if prior is None:
                os.environ.pop(BACKEND_ENV_VAR, None)
            else:
                os.environ[BACKEND_ENV_VAR] = prior

    def test_resolve_backend_unknown_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_backend("does-not-exist")
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_openai_compatible_backend_raises_not_implemented_in_pr1(self) -> None:
        """Live backend lands in PR3 — callers must fail loudly, not silently fall back."""
        with self.assertRaises(NotImplementedError):
            propose_cases(
                [{"doc_id": "doc-001"}],
                backend="openai_compatible",
                model="claude-sonnet-4-6",
            )

    def test_default_paths_under_reports_proposed(self) -> None:
        """ADR 0005 commit-boundary intent: proposed/reviewed yaml stays under reports/proposed/."""
        for path in (DEFAULT_PROPOSED_PATH, DEFAULT_AGGREGATE_PATH):
            parts = path.parts
            self.assertIn("reports", parts)
            self.assertIn("proposed", parts)

    def test_proposer_version_is_int(self) -> None:
        self.assertIsInstance(PROPOSER_VERSION, int)
        self.assertGreaterEqual(PROPOSER_VERSION, 1)


class CaseProposerImportSurfaceTest(unittest.TestCase):
    """ADR 0001 byte-identity guard.

    The naive-baseline golden (``tests/data/naive_baseline_top_k.json``)
    is produced by ``rag_core``'s retrieval path. ``eval.case_proposer``
    is strictly upstream of ``run_rag_query`` — it produces eval
    inputs, not answer outputs — so importing it must NOT trigger any
    ``rag_core`` import. A subprocess check is used so the parent
    pytest process (which has already imported ``rag_core`` via other
    test modules) cannot mask a regression here.
    """

    def test_importing_case_proposer_does_not_import_rag_core(self) -> None:
        script = textwrap.dedent(
            """
            import sys
            import eval.case_proposer  # noqa: F401
            forbidden = [m for m in sys.modules if m == "rag_core" or m.startswith("rag_core.")]
            if forbidden:
                print(f"FAIL: {forbidden}", file=sys.stderr)
                sys.exit(1)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"eval.case_proposer pulled in rag_core (regression). "
            f"stderr: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
