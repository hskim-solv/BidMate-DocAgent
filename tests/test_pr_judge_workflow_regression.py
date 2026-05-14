"""Regression tests for `.github/workflows/pr-judge.yml` (ADR 0043).

These guard the policy invariants codified in ADR 0043:

- Trigger is `pull_request` `labeled` only (no `synchronize`/`push`/`opened`).
- The `live-judge-please` label gate is enforced in the job `if:` expression.
- The fork-repo guard (`head.repo.full_name == github.repository`) is present.
- The live backend env var is hard-coded to `openai_compatible`.
- The three judge secrets are wired through to `env`.
- The aggregate JSON is uploaded as an artifact (no `git push` of per-case data).

The companion comment-renderer (`scripts/render_judge_comment.py`) is exercised
end-to-end against a minimal fixture so the workflow's `python scripts/...`
step has a unit-test floor that fires before CI does.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-judge.yml"
PR_TEMPLATE_PATH = REPO_ROOT / ".github" / "pull_request_template.md"
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_judge_comment.py"


def _load_workflow() -> dict:
    with WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class WorkflowStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = _load_workflow()

    def test_workflow_parses(self) -> None:
        self.assertIsInstance(self.workflow, dict)
        self.assertEqual(self.workflow["name"], "PR Live LLM-Judge")

    def test_trigger_is_labeled_only(self) -> None:
        # PyYAML maps the bareword `on` to True; accept either form.
        on_block = self.workflow.get("on") or self.workflow.get(True)
        self.assertIsNotNone(
            on_block,
            "workflow `on:` block missing — ADR 0043 trigger contract broken",
        )
        self.assertIn("pull_request", on_block)
        types = on_block["pull_request"]["types"]
        self.assertEqual(
            list(types),
            ["labeled"],
            "ADR 0043 Goodhart guard: workflow must fire on `labeled` only, "
            "not on `synchronize`/`push`/`opened`.  See pr-judge.yml comment.",
        )

    def test_job_has_label_gate(self) -> None:
        job = self.workflow["jobs"]["live-judge"]
        condition = job["if"]
        # The label-name check is the primary gate.
        self.assertIn("github.event.label.name == 'live-judge-please'", condition)

    def test_job_has_fork_guard(self) -> None:
        condition = self.workflow["jobs"]["live-judge"]["if"]
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            condition,
            "ADR 0043 § Fork PR consideration: fork PRs must be excluded so "
            "BIDMATE_JUDGE_API_KEY cannot leak via untrusted code paths.",
        )

    def test_env_pins_openai_compatible_backend(self) -> None:
        env = self.workflow["jobs"]["live-judge"]["env"]
        self.assertEqual(env["BIDMATE_SYNTHETIC_JUDGE_BACKEND"], "openai_compatible")

    def test_env_references_three_judge_secrets(self) -> None:
        env = self.workflow["jobs"]["live-judge"]["env"]
        for key in ("BIDMATE_JUDGE_API_KEY", "BIDMATE_JUDGE_MODEL", "BIDMATE_JUDGE_BASE_URL"):
            self.assertIn(key, env, f"{key} env var missing from pr-judge.yml")
            self.assertIn("secrets.", env[key], f"{key} must come from repo secrets")

    def test_concurrency_groups_per_pr(self) -> None:
        concurrency = self.workflow["concurrency"]
        self.assertIn("pull_request.number", concurrency["group"])
        self.assertTrue(concurrency.get("cancel-in-progress"))

    def test_permissions_minimal(self) -> None:
        perms = self.workflow["permissions"]
        # Read source + comment on PR.  Nothing else (no `contents: write`,
        # no `actions:`, no `id-token:`) — ADR 0005 commit boundary.
        self.assertEqual(perms.get("contents"), "read")
        self.assertEqual(perms.get("pull-requests"), "write")

    def test_artifact_upload_step_present(self) -> None:
        steps = self.workflow["jobs"]["live-judge"]["steps"]
        upload_steps = [
            s for s in steps
            if isinstance(s, dict) and s.get("uses", "").startswith("actions/upload-artifact")
        ]
        self.assertTrue(
            upload_steps,
            "ADR 0043 § Output: workflow must upload aggregate as artifact",
        )
        # Confirm the artifact path is the aggregate JSON, not the local
        # per-case file (which would violate ADR 0005 commit boundary).
        paths = [s["with"].get("path", "") for s in upload_steps]
        self.assertTrue(
            any("synthetic_judge.aggregate.json" in p for p in paths),
            f"upload-artifact paths {paths} do not include the aggregate JSON",
        )
        self.assertFalse(
            any("synthetic_judge.local.json" in p for p in paths),
            "Per-case local JSON must not be uploaded (ADR 0005 boundary)",
        )

    def test_no_pull_request_target(self) -> None:
        # `pull_request_target` runs on the *base* repo with secrets exposed,
        # which would let fork PRs exfiltrate BIDMATE_JUDGE_API_KEY.  ADR 0043
        # explicitly forbids it.
        on_block = self.workflow.get("on") or self.workflow.get(True)
        self.assertNotIn("pull_request_target", on_block)

    def test_workflow_does_not_commit_artifacts(self) -> None:
        # Sanity: no shell step pushes back to the repo.  A `git push` here
        # would silently violate the ADR 0005 boundary the policy ADR
        # promises to preserve.
        steps = self.workflow["jobs"]["live-judge"]["steps"]
        for step in steps:
            run_block = step.get("run", "") if isinstance(step, dict) else ""
            self.assertNotIn("git push", run_block)
            self.assertNotIn("git commit", run_block)


class PrTemplateMentionsLabelTest(unittest.TestCase):
    """PR template should hint at the label trigger so authors discover it."""

    def test_template_mentions_label(self) -> None:
        body = PR_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn("live-judge-please", body)
        self.assertIn("ADR 0043", body)


class RenderCommentSmokeTest(unittest.TestCase):
    """End-to-end smoke for scripts/render_judge_comment.py.

    The workflow runs ``python scripts/render_judge_comment.py ...``; a broken
    render would silently produce an empty PR comment, which is worse than a
    failed CI run.  This test catches missing keys + format breakage.
    """

    FIXTURE = {
        "schema_version": 1,
        "generated_at": "2026-05-14T00:00:00Z",
        "backend": "openai_compatible",
        "model": "claude-sonnet-4-5",
        "n": 42,
        "faithfulness_mean": 0.81,
        "answer_relevance_mean": 0.78,
        "grounded_rate": 0.88,
        "agreement_with_verifier": 0.86,
        "status_distribution": {"supported": 36, "insufficient": 6},
        "by_query_type": {
            "abstention": {
                "n": 9,
                "faithfulness_mean": 0.70,
                "answer_relevance_mean": 0.72,
                "grounded_rate": 0.78,
                "agreement_with_verifier": 0.89,
            },
            "comparison": {
                "n": 10,
                "faithfulness_mean": 0.85,
                "answer_relevance_mean": 0.80,
                "grounded_rate": 0.90,
                "agreement_with_verifier": 0.80,
            },
        },
    }

    def test_render_emits_marker_and_table(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            agg = tmp_path / "agg.json"
            agg.write_text(json.dumps(self.FIXTURE), encoding="utf-8")
            out = tmp_path / "comment.md"
            result = subprocess.run(
                [sys.executable, str(RENDER_SCRIPT),
                 "--aggregate", str(agg), "--output", str(out)],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = out.read_text(encoding="utf-8")

        # Marker is required for the workflow's upsert step to work.
        self.assertIn("<!-- pr-judge-bot -->", rendered)
        # Headline metrics surfaced.
        self.assertIn("faithfulness", rendered)
        self.assertIn("answer_relevance", rendered)
        self.assertIn("agreement_w/_verifier", rendered)
        # Per-query-type slice rendered.
        self.assertIn("abstention", rendered)
        self.assertIn("comparison", rendered)
        # Goodhart footnote rendered.
        self.assertIn("Re-attach the label", rendered)
        # Backend + model surfaced (so reviewers see live vs stub at a glance).
        self.assertIn("openai_compatible", rendered)
        self.assertIn("claude-sonnet-4-5", rendered)

    def test_render_handles_missing_optional_blocks(self) -> None:
        import tempfile

        minimal = {
            "schema_version": 1,
            "generated_at": "2026-05-14T00:00:00Z",
            "backend": "stub",
            "model": "stub",
            "n": 0,
            "faithfulness_mean": None,
            "answer_relevance_mean": None,
            "grounded_rate": None,
            "agreement_with_verifier": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            agg = tmp_path / "agg.json"
            agg.write_text(json.dumps(minimal), encoding="utf-8")
            out = tmp_path / "comment.md"
            subprocess.run(
                [sys.executable, str(RENDER_SCRIPT),
                 "--aggregate", str(agg), "--output", str(out)],
                check=True, capture_output=True, text=True,
            )
            rendered = out.read_text(encoding="utf-8")
        self.assertIn("<!-- pr-judge-bot -->", rendered)
        # None values render as em-dash, not "None".
        self.assertNotIn("None", rendered)


if __name__ == "__main__":
    unittest.main()
