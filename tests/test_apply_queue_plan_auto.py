from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_queue_plan_auto.py"


def _seed_repo(tmp_path: Path, *, queue_text: str | None = None, plan_text: str | None = None) -> None:
    (tmp_path / "tasks").mkdir(parents=True)
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "reports" / "agent_loop").mkdir(parents=True)
    (tmp_path / "tasks" / "queue.md").write_text("# Queue\n", encoding="utf-8")
    (tmp_path / "reports" / "agent_loop" / "queue_entry_draft.md").write_text(
        queue_text
        or """## T-2026-9999 — Auto apply draft\n\n- ID: T-2026-9999\n- Status: backlog\n""",
        encoding="utf-8",
    )
    (tmp_path / "reports" / "agent_loop" / "plan_draft.md").write_text(
        plan_text
        or """# Plan: T-2026-9999 Auto apply draft\n\n- Suggested final path: `docs/plans/T-2026-9999-auto-apply-draft.md`\n\n## Validation\n\n```bash\ngit diff --check\n```\n""",
        encoding="utf-8",
    )


def test_apply_queue_plan_auto_applies_local_drafts_without_confirm_flag(tmp_path: Path) -> None:
    _seed_repo(tmp_path)

    result = subprocess.run(
        ["python3", str(SCRIPT), "--repo-root", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "without approval flag" in result.stdout
    assert "T-2026-9999" in (tmp_path / "tasks" / "queue.md").read_text(encoding="utf-8")
    assert (tmp_path / "docs" / "plans" / "T-2026-9999-auto-apply-draft.md").exists()
    report = (tmp_path / "reports" / "agent_loop" / "apply_queue_plan.md").read_text(encoding="utf-8")
    assert "- Result: `applied`" in report
    assert "push, create/merge/close PRs" in report


def test_apply_queue_plan_auto_preserves_privacy_block(tmp_path: Path) -> None:
    _seed_repo(
        tmp_path,
        queue_text="""## T-2026-9999 — Bad draft\n\n- ID: T-2026-9999\n- raw question: should not be applied\n""",
    )

    result = subprocess.run(
        ["python3", str(SCRIPT), "--repo-root", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "private raw values" in result.stderr
    assert (tmp_path / "tasks" / "queue.md").read_text(encoding="utf-8") == "# Queue\n"
    assert not (tmp_path / "docs" / "plans" / "T-2026-9999-auto-apply-draft.md").exists()
