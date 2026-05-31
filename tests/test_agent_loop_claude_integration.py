from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "claude-hooks" / "stop-agent-loop.sh"
COMMAND_DIR = ROOT / ".claude" / "commands"


def _copy_agent_loop_hook_repo(tmp_path: Path) -> Path:
    repo = tmp_path
    (repo / "scripts" / "claude-hooks").mkdir(parents=True)
    shutil.copy2(HOOK, repo / "scripts" / "claude-hooks" / HOOK.name)
    shutil.copy2(ROOT / "scripts" / "agent_loop.py", repo / "scripts" / "agent_loop.py")
    shutil.copy2(ROOT / "scripts" / "_governance.py", repo / "scripts" / "_governance.py")
    # agent_loop.py imports strip_ship_secret_env at module top (ADR 0090 env-isolation);
    # the fixture must carry the leaf module or the hook's agent_loop invocation ImportErrors.
    shutil.copy2(ROOT / "scripts" / "_ship_env.py", repo / "scripts" / "_ship_env.py")
    return repo


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


def test_stop_agent_loop_no_watch_is_noop(tmp_path: Path) -> None:
    repo = _copy_agent_loop_hook_repo(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/claude-hooks/stop-agent-loop.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert not (repo / "reports" / "agent_loop").exists()


def test_stop_agent_loop_watch_refreshes_status_reports_and_telemetry(tmp_path: Path) -> None:
    repo = _copy_agent_loop_hook_repo(tmp_path)
    _git("init", "-q", "-b", "main", cwd=repo)
    (repo / ".gitignore").write_text(".claude/\nreports/\n", encoding="utf-8")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git("add", ".gitignore", "README.md", cwd=repo)
    _git("commit", "-qm", "init", cwd=repo)
    (repo / ".claude").mkdir()
    (repo / ".claude" / ".agent-loop-watch").write_text("1\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/claude-hooks/stop-agent-loop.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    report_dir = repo / "reports" / "agent_loop"
    assert (report_dir / "gate_status.md").exists()
    assert (report_dir / "loop_state.json").exists()
    assert (report_dir / "auto_pass.md").exists()
    assert not (report_dir / "auto_ship_prepare.md").exists()
    assert not (report_dir / "auto_ship_plan.md").exists()
    fires = (repo / ".claude" / ".hook-fires.log").read_text(encoding="utf-8")
    assert "|pipeline_end|agent-loop|stop-report|reports/agent_loop/loop_state.json" in fires


def test_agent_loop_commands_are_tracked_and_safe() -> None:
    commands = sorted(COMMAND_DIR.glob("agent-loop-*.md"))
    assert {path.name for path in commands} == {
        "agent-loop-auto-ship.md",
        "agent-loop-auto-pass.md",
        "agent-loop-preflight.md",
        "agent-loop-review.md",
        "agent-loop-status.md",
        "agent-loop-watch.md",
    }

    forbidden_in_bash = re.compile(
        r"\b(?:git\s+push|gh\s+pr\s+(?:create|merge|close)|git\s+branch\s+-D|force-push)\b",
        re.IGNORECASE,
    )
    for path in commands:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-v", "--", path.as_posix()],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{path} should have an explicit gitignore rule"
        assert ":!" in result.stdout, f"{path} should be allowlisted, not ignored"

        text = path.read_text(encoding="utf-8")
        assert "allowed-tools:" in text
        assert "scripts/agent_loop.py" in text or path.name == "agent-loop-watch.md"
        for block in re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL):
            assert not forbidden_in_bash.search(block), path.name


def test_settings_registers_stop_agent_loop_hook_after_stop_ship() -> None:
    settings = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "bash scripts/claude-hooks/stop-ship.sh" in settings
    assert "bash scripts/claude-hooks/stop-agent-loop.sh" in settings
    assert settings.index("stop-ship.sh") < settings.index("stop-agent-loop.sh")


def test_agent_loop_artifacts_workflow_is_informational_and_uploads_reports() -> None:
    workflow = (ROOT / ".github" / "workflows" / "agent-loop-artifacts.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "reports/agent_loop/" in workflow
    assert "dashboard" in workflow
    forbidden = re.compile(r"\b(?:git\s+push|gh\s+pr\s+(?:create|merge|close)|git\s+branch\s+-D|force-push)\b")
    assert not forbidden.search(workflow)
