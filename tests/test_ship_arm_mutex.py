"""Tests for ship-arm ↔ ship-pr mutex (issue #1043).

거버넌스 비판 보고서 (2026-05-19) #6 — `make ship-arm` (Stop-hook 자동 ship)
과 `ship-pr` skill (수동 게이트) 의 mutual exclusivity 가 텍스트 only.
`_ship_arm.py:check_ship_pr_mutex()` 가 marker 검출 시 refuse.

테스트 범위:

- ship-pr-active marker 없을 때 → 0 반환 (정상 진행)
- 신선한 marker 존재 시 → 1 반환 + stderr 메시지 (refuse)
- 6h 이상 stale marker → marker 자동 삭제 + 0 반환 (stale 우회)
- marker 가 stat 불가 (perm error 등) → 0 반환 (fail open)
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIP_ARM_PATH = REPO_ROOT / "scripts" / "claude-hooks" / "_ship_arm.py"


def _load_ship_arm():
    spec = importlib.util.spec_from_file_location(
        "_ship_arm_mod", SHIP_ARM_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture
def ship_arm(tmp_path, monkeypatch):
    """Load _ship_arm.py with the marker path redirected to tmp."""
    mod = _load_ship_arm()
    monkeypatch.setattr(
        mod, "SHIP_PR_ACTIVE_FILE", str(tmp_path / ".ship-pr-active")
    )
    return mod


def test_no_marker_allows_arming(ship_arm):
    """No marker → 0 (safe to arm)."""
    assert ship_arm.check_ship_pr_mutex() == 0


def test_fresh_marker_refuses(ship_arm, capsys):
    """Fresh marker (recent mtime) → 1 (refuse) + stderr message."""
    Path(ship_arm.SHIP_PR_ACTIVE_FILE).write_text("")
    result = ship_arm.check_ship_pr_mutex()
    assert result == 1
    captured = capsys.readouterr()
    assert "refuse" in captured.err
    assert "ship-pr skill currently active" in captured.err


def test_stale_marker_cleared_then_allows(ship_arm, capsys):
    """Marker older than SHIP_PR_ACTIVE_STALE_SECONDS → auto-clear + 0."""
    marker = Path(ship_arm.SHIP_PR_ACTIVE_FILE)
    marker.write_text("")
    # Set mtime to 7 hours ago (> 6h threshold).
    old_ts = time.time() - 7 * 3600
    os.utime(marker, (old_ts, old_ts))
    result = ship_arm.check_ship_pr_mutex()
    assert result == 0
    assert not marker.exists(), "stale marker should be removed"
    captured = capsys.readouterr()
    assert "cleared stale" in captured.err


def test_marker_at_boundary_still_refuses(ship_arm, capsys):
    """Marker exactly at threshold edge - 1s → still refuse (strict)."""
    marker = Path(ship_arm.SHIP_PR_ACTIVE_FILE)
    marker.write_text("")
    # mtime 1s less than threshold = still fresh
    ts = time.time() - (ship_arm.SHIP_PR_ACTIVE_STALE_SECONDS - 1)
    os.utime(marker, (ts, ts))
    result = ship_arm.check_ship_pr_mutex()
    assert result == 1
    assert marker.exists()


def test_marker_stat_failure_fails_open(ship_arm, monkeypatch):
    """os.path.getmtime() raises → check returns 0 (fail open)."""
    Path(ship_arm.SHIP_PR_ACTIVE_FILE).write_text("")

    def _raise(_path):
        raise OSError("simulated stat failure")

    monkeypatch.setattr(os.path, "getmtime", _raise)
    result = ship_arm.check_ship_pr_mutex()
    assert result == 0  # fail open
