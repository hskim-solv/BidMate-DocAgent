"""Regression: PR-gate workflows must fire on EVERY PR base, not just main.

Issue #1159 — ``branch-and-issue-check.yml`` was triggered by
``pull_request: branches: [main]``. A change opened as a stacked PR
(base≠main — a CLAUDE.md-blessed 1-day-decomposition pattern) therefore never
ran the branch/issue + ceiling-ratchet gates on that workflow. ``pr-eval.yml``
carried the same ``branches: [main]`` filter, so its eval-delta / pytest gates
were also exempt on stacked PRs. (The original incident also covered the §5b
hard-gate, which was later deprecated in ADR 0084.)

These tests pin "PR-correctness gates fire on all bases" so that re-adding a
``branches:`` filter — which would re-exempt stacked PRs — fails CI before it
can merge.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Workflows that gate PR correctness. Each MUST run on every PR base (no
# ``branches:`` restriction) so stacked PRs (base≠main) are never exempt.
PR_GATE_WORKFLOWS = (
    "branch-and-issue-check.yml",
    "pr-eval.yml",
)


def _load(name: str) -> dict:
    with (WORKFLOWS / name).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _on_block(wf: dict) -> dict:
    # PyYAML maps the bareword key ``on`` to the boolean True; accept either.
    block = wf.get("on")
    if block is None:
        block = wf.get(True)
    assert block is not None, "workflow has no `on:` trigger block"
    return block


class PrGateBaseAgnosticTest(unittest.TestCase):
    def test_each_gate_has_pull_request_trigger(self) -> None:
        for name in PR_GATE_WORKFLOWS:
            with self.subTest(workflow=name):
                on_block = _on_block(_load(name))
                self.assertIsNotNone(on_block, f"{name}: `on:` block missing")
                self.assertIn(
                    "pull_request",
                    on_block,
                    f"{name}: must be pull_request-triggered to gate PRs",
                )

    def test_no_gate_restricts_branches_to_main(self) -> None:
        for name in PR_GATE_WORKFLOWS:
            with self.subTest(workflow=name):
                pr = _on_block(_load(name))["pull_request"]
                # ``pull_request:`` with no body parses to None (no filter);
                # a dict carries a ``branches`` key only if a filter is set.
                branches = (pr or {}).get("branches")
                self.assertIsNone(
                    branches,
                    f"{name}: `pull_request.branches` is {branches!r}, but PR "
                    f"gates must fire on EVERY base. A `branches: [main]` "
                    f"filter exempts stacked PRs (base≠main) from the gate "
                    f"(issue #1159).",
                )


class PrEvalChangeScopeWiringTest(unittest.TestCase):
    """The balanced CI policy must stay in tested code, not inline regex."""

    def test_pr_eval_uses_tested_change_scope_helper(self) -> None:
        text = (WORKFLOWS / "pr-eval.yml").read_text(encoding="utf-8")

        self.assertIn("scripts/pr_eval_change_scope.py", text)
        self.assertIn("pytest: ${{ steps.scope.outputs.pytest }}", text)
        self.assertIn("if: needs.changes.outputs.pytest == 'true'", text)
        self.assertIn("if: needs.changes.outputs.runtime == 'true'", text)


if __name__ == "__main__":
    unittest.main()
