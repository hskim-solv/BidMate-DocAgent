"""Regression: PR-gate workflows must fire on EVERY PR base, not just main.

Issue #1159 — the §5b real-data-delta hard-gate (``--check-5b``) lives only in
``branch-and-issue-check.yml``, which was triggered by
``pull_request: branches: [main]``. A load-bearing change opened as a stacked
PR (base≠main — a CLAUDE.md-blessed 1-day-decomposition pattern) therefore
never ran ``--check-5b``: the PR #69 hard-gate was silently bypassable on the
stacked path. ``pr-eval.yml`` carried the same ``branches: [main]`` filter, so
its eval-delta / pytest gates were also exempt on stacked PRs.

These tests pin "PR-correctness gates fire on all bases" so that re-adding a
``branches:`` filter — which reintroduces the §5b bypass — fails CI before it
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
                    f"filter exempts stacked PRs (base≠main) from the gate and "
                    f"reintroduces the §5b bypass (issue #1159).",
                )


class FiveBGateStillWiredTest(unittest.TestCase):
    """The trigger fix is moot if the §5b step itself is dropped."""

    def test_check_5b_step_present(self) -> None:
        text = (WORKFLOWS / "branch-and-issue-check.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "--check-5b",
            text,
            "branch-and-issue-check.yml must still invoke "
            "`check_branch_and_issue.py --check-5b` (PR #69 hard-gate).",
        )


if __name__ == "__main__":
    unittest.main()
