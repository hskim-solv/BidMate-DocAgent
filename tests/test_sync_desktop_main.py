from __future__ import annotations

import os
from pathlib import Path
import subprocess

from scripts.sync_desktop_main import sync_desktop_main


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


def _sha(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def _setup_remote_and_desktop(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    desktop = tmp_path / "desktop"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True, text=True)
    _git(seed, "switch", "-c", "main")
    (seed / "README.md").write_text("one\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "init")
    _git(seed, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", str(origin), str(desktop)], check=True, capture_output=True, text=True)
    _git(desktop, "switch", "main")
    return origin, seed, desktop


def _push_remote_commit(seed: Path, text: str = "two\n") -> str:
    (seed / "README.md").write_text(text, encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "remote update")
    _git(seed, "push", "origin", "main")
    return _sha(seed, "HEAD")


def test_sync_fast_forwards_clean_desktop_main(tmp_path: Path) -> None:
    _origin, seed, desktop = _setup_remote_and_desktop(tmp_path)
    remote_sha = _push_remote_commit(seed)

    result = sync_desktop_main(desktop)

    assert result.exit_code == 0
    assert result.status == "synced"
    assert _sha(desktop, "main") == remote_sha
    assert _sha(desktop, "origin/main") == remote_sha


def test_sync_updates_main_ref_when_desktop_is_on_feature_branch(tmp_path: Path) -> None:
    _origin, seed, desktop = _setup_remote_and_desktop(tmp_path)
    _git(desktop, "switch", "-c", "feature")
    remote_sha = _push_remote_commit(seed)

    result = sync_desktop_main(desktop)

    assert result.exit_code == 0
    assert _git(desktop, "branch", "--show-current").stdout.strip() == "feature"
    assert _sha(desktop, "main") == remote_sha


def test_sync_skips_dirty_desktop_main(tmp_path: Path) -> None:
    _origin, seed, desktop = _setup_remote_and_desktop(tmp_path)
    old_sha = _sha(desktop, "main")
    _push_remote_commit(seed)
    (desktop / "local.txt").write_text("dirty\n", encoding="utf-8")

    result = sync_desktop_main(desktop)

    assert result.exit_code == 2
    assert result.status == "skipped"
    assert "local changes" in result.reason
    assert _sha(desktop, "main") == old_sha


def test_sync_skips_divergent_desktop_main(tmp_path: Path) -> None:
    _origin, seed, desktop = _setup_remote_and_desktop(tmp_path)
    _push_remote_commit(seed, "remote\n")
    (desktop / "README.md").write_text("local\n", encoding="utf-8")
    _git(desktop, "add", "README.md")
    _git(desktop, "commit", "-m", "local update")
    local_sha = _sha(desktop, "main")

    result = sync_desktop_main(desktop)

    assert result.exit_code == 2
    assert result.status == "skipped"
    assert "not an ancestor" in result.reason
    assert _sha(desktop, "main") == local_sha


def test_stop_ship_stage_5_invokes_desktop_sync() -> None:
    text = (REPO_ROOT / "scripts" / "claude-hooks" / "stop-ship.sh").read_text(encoding="utf-8")
    assert "scripts/sync_desktop_main.py" in text
    assert "BIDMATE_DESKTOP_REPO" in text
