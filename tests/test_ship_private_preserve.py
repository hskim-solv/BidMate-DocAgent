from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "claude-hooks" / "_ship_private_preserve.py"
SPEC = importlib.util.spec_from_file_location("_ship_private_preserve", HELPER)
assert SPEC is not None and SPEC.loader is not None
preserve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preserve)


def test_preserve_moves_untracked_private_report_to_canonical_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "worktree"
    canonical = tmp_path / "main-checkout"
    source = repo / "reports" / "real100" / "strategy.aggregate.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"ok": true}\n', encoding="utf-8")
    canonical.mkdir()

    message = preserve.preserve_one(
        repo_root=repo,
        preserve_root=canonical,
        status="??",
        relpath="reports/real100/strategy.aggregate.json",
    )

    assert message.startswith("moved reports/real100/strategy.aggregate.json")
    assert not source.exists()
    assert (canonical / "reports" / "real100" / "strategy.aggregate.json").read_text(
        encoding="utf-8"
    ) == '{"ok": true}\n'


def test_preserve_dedupes_identical_existing_file(tmp_path: Path) -> None:
    repo = tmp_path / "worktree"
    canonical = tmp_path / "main-checkout"
    source = repo / "reports" / "real100" / "same.aggregate.json"
    dest = canonical / "reports" / "real100" / "same.aggregate.json"
    source.parent.mkdir(parents=True)
    dest.parent.mkdir(parents=True)
    source.write_text('{"same": true}\n', encoding="utf-8")
    dest.write_text('{"same": true}\n', encoding="utf-8")

    message = preserve.preserve_one(
        repo_root=repo,
        preserve_root=canonical,
        status="??",
        relpath="reports/real100/same.aggregate.json",
    )

    assert message == "dedupe reports/real100/same.aggregate.json"
    assert not source.exists()
    assert dest.read_text(encoding="utf-8") == '{"same": true}\n'


def test_preserve_uses_conflict_name_when_destination_differs(tmp_path: Path) -> None:
    repo = tmp_path / "worktree"
    canonical = tmp_path / "main-checkout"
    source = repo / "reports" / "real100" / "conflict.aggregate.json"
    dest = canonical / "reports" / "real100" / "conflict.aggregate.json"
    source.parent.mkdir(parents=True)
    dest.parent.mkdir(parents=True)
    source.write_text('{"new": true}\n', encoding="utf-8")
    dest.write_text('{"old": true}\n', encoding="utf-8")

    message = preserve.preserve_one(
        repo_root=repo,
        preserve_root=canonical,
        status="??",
        relpath="reports/real100/conflict.aggregate.json",
    )

    assert message.startswith("moved reports/real100/conflict.aggregate.json")
    assert not source.exists()
    assert dest.read_text(encoding="utf-8") == '{"old": true}\n'
    conflicts = list(dest.parent.glob("conflict.aggregate.json.ship-preserved-*"))
    assert len(conflicts) == 1
    assert conflicts[0].read_text(encoding="utf-8") == '{"new": true}\n'


def test_preserve_does_not_move_tracked_private_modification(tmp_path: Path) -> None:
    repo = tmp_path / "worktree"
    canonical = tmp_path / "main-checkout"
    source = repo / "reports" / "real100" / "tracked.aggregate.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"tracked": true}\n', encoding="utf-8")
    canonical.mkdir()

    message = preserve.preserve_one(
        repo_root=repo,
        preserve_root=canonical,
        status=" M",
        relpath="reports/real100/tracked.aggregate.json",
    )

    assert message == "skip tracked-status  M reports/real100/tracked.aggregate.json"
    assert source.exists()
    assert not (canonical / "reports" / "real100" / "tracked.aggregate.json").exists()


def test_preserve_rejects_unsafe_relative_path(tmp_path: Path) -> None:
    try:
        preserve.preserve_one(
            repo_root=tmp_path / "repo",
            preserve_root=tmp_path / "main",
            status="??",
            relpath="../secret.txt",
        )
    except ValueError as exc:
        assert "unsafe relative path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unsafe relative path to fail")


def test_cli_without_preserve_root_skips_safely(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SHIP_PRIVATE_PRESERVE_ROOT", raising=False)
    monkeypatch.delenv("BIDMATE_PRIVATE_PRESERVE_ROOT", raising=False)
    repo = tmp_path / "worktree"
    source = repo / "reports" / "real100" / "skip.aggregate.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"skip": true}\n', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--repo-root",
            str(repo),
        ],
        input="??\treports/real100/skip.aggregate.json\n",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "SHIP_PRIVATE_PRESERVE_ROOT is not set" in result.stderr
    assert source.exists()
