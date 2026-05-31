"""Regression tests for the isolated staging self-ship lane (ADR 0088).

Covers the constitutional-invariant guards (force-push / staging boundary /
kill-switch / ship-arm exclusion), the breaker counters (T1 bounded, T4 cap with
self-immutable store), and the lane (CI-green gate, fail-closed external
enforcement). git/gh is injected as a fake so no network/GitHub is touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import _staging_ship as ss  # noqa: E402
from _ship_payload_guard import RawPayloadViolation  # noqa: E402


# --- guards -------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["main", "master", "HEAD", "", "develop", "Main"])
def test_staging_target_rejects_protected(bad):
    with pytest.raises(ss.StagingBoundaryViolation):
        ss.assert_staging_target(bad)


@pytest.mark.parametrize("ok", ["autopilot/integration", "autopilot/feature-x"])
def test_staging_target_accepts_staging(ok):
    ss.assert_staging_target(ok)  # no raise


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push", "--force", "origin", "br"],
        ["git", "push", "-f", "origin", "br"],
        ["git", "push", "--force-with-lease", "origin", "br"],
        ["git", "filter-branch", "--tree-filter", "x"],
        ["git", "push", "origin", "+main"],
        "git push --mirror origin",
    ],
)
def test_force_push_forbidden(argv):
    with pytest.raises(ss.ForcePushForbidden):
        ss.assert_no_force_push(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push", "origin", "autopilot/integration"],
        ["git", "commit", "-m", "msg"],
        "git push origin HEAD:autopilot/integration",
    ],
)
def test_normal_git_allowed(argv):
    ss.assert_no_force_push(argv)  # no raise


def test_kill_switch_file(tmp_path):
    assert ss.kill_switch_active(tmp_path) is False
    (tmp_path / "KILL").write_text("stop")
    assert ss.kill_switch_active(tmp_path) is True


def test_kill_switch_env(tmp_path):
    assert ss.kill_switch_active(tmp_path, env={"BIDMATE_SHIP_KILL_SWITCH": "1"}) is True


def test_ship_arm_exclusion(tmp_path):
    ss.assert_ship_arm_not_active(tmp_path)  # no .ship-armed -> ok
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".ship-armed").write_text("")
    with pytest.raises(ss.ShipArmConflict):
        ss.assert_ship_arm_not_active(tmp_path)


# --- breaker counters ---------------------------------------------------------

def test_bounded_failure_counter():
    c = ss.BoundedFailureCounter(limit=3)
    c.record_failure(); c.record_failure()
    assert c.should_halt() is False
    c.record_failure()
    assert c.should_halt() is True
    c.record_success()
    assert c.should_halt() is False


class _FakeStore:
    def __init__(self, loop_writable: bool):
        self.loop_writable = loop_writable
        self._counts: dict[str, int] = {}

    def get(self, day: str) -> int:
        return self._counts.get(day, 0)

    def increment(self, day: str) -> None:
        self._counts[day] = self._counts.get(day, 0) + 1


def test_daily_cap_rejects_loop_writable_store():
    with pytest.raises(ss.EnforcementNotVerified):
        ss.DailyMergeCapCounter(store=_FakeStore(loop_writable=True), cap=5)


def test_daily_cap_counts_with_immutable_store():
    cap = ss.DailyMergeCapCounter(store=_FakeStore(loop_writable=False), cap=2)
    assert cap.would_exceed("2026-05-31") is False
    cap.record_merge("2026-05-31")
    cap.record_merge("2026-05-31")
    assert cap.would_exceed("2026-05-31") is True


# --- lane ---------------------------------------------------------------------

class _FakeGitOps:
    def __init__(self, *, protection=True, checks_green=True):
        self._protection = protection
        self._checks_green = checks_green
        self.opened: list[dict] = []
        self.merged: list[str] = []

    def protection_verified(self, branch: str) -> bool:
        return self._protection

    def open_pr(self, *, source, base, title, body) -> str:
        self.opened.append({"source": source, "base": base, "title": title, "body": body})
        return "PR-1"

    def required_checks_all_success(self, pr_id: str) -> bool:
        return self._checks_green

    def merge(self, pr_id: str) -> None:
        self.merged.append(pr_id)


def _lane(ops, tmp_path, **kw):
    return ss.StagingShipLane(
        ops=ops,
        repo_root=tmp_path,
        state_dir=tmp_path,
        merge_cap=ss.DailyMergeCapCounter(store=_FakeStore(loop_writable=False), cap=5),
        **kw,
    )


def test_lane_happy_path_ships(tmp_path):
    ops = _FakeGitOps(protection=True, checks_green=True)
    lane = _lane(ops, tmp_path)
    res = lane.ship(source="autopilot/work", title="chore: 3 tasks", body="5 PRs merged, revert 0", day="d1")
    assert res.decision == "shipped"
    assert ops.merged == ["PR-1"]


def test_lane_blocks_on_unverified_enforcement(tmp_path):
    ops = _FakeGitOps(protection=False, checks_green=True)
    lane = _lane(ops, tmp_path)
    res = lane.ship(source="autopilot/work", title="x", body="ok 1", day="d1")
    assert res.decision == "blocked-on-user"
    assert ops.merged == []  # never opened/merged


def test_lane_blocks_when_ci_not_green(tmp_path):
    ops = _FakeGitOps(protection=True, checks_green=False)
    lane = _lane(ops, tmp_path)
    res = lane.ship(source="autopilot/work", title="x", body="ok 1", day="d1")
    assert res.decision == "blocked-ci"
    assert ops.merged == []  # opened but NOT merged
    assert len(ops.opened) == 1


def test_lane_halts_on_kill_switch(tmp_path):
    (tmp_path / "KILL").write_text("stop")
    ops = _FakeGitOps()
    lane = _lane(ops, tmp_path)
    res = lane.ship(source="autopilot/work", title="x", body="ok 1", day="d1")
    assert res.decision == "halted-kill-switch"
    assert ops.opened == []


def test_lane_blocks_on_cap(tmp_path):
    ops = _FakeGitOps()
    lane = ss.StagingShipLane(
        ops=ops, repo_root=tmp_path, state_dir=tmp_path,
        merge_cap=ss.DailyMergeCapCounter(store=_FakeStore(loop_writable=False), cap=1),
    )
    assert lane.ship(source="autopilot/w", title="x", body="ok 1", day="d1").decision == "shipped"
    assert lane.ship(source="autopilot/w", title="x", body="ok 1", day="d1").decision == "blocked-cap"


def test_lane_ship_arm_conflict(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".ship-armed").write_text("")
    lane = _lane(_FakeGitOps(), tmp_path)
    with pytest.raises(ss.ShipArmConflict):
        lane.ship(source="autopilot/w", title="x", body="ok 1", day="d1")


def test_lane_rejects_main_target(tmp_path):
    lane = _lane(_FakeGitOps(), tmp_path, target_branch="main")
    with pytest.raises(ss.StagingBoundaryViolation):
        lane.ship(source="autopilot/w", title="x", body="ok 1", day="d1")


def test_lane_rejects_raw_payload_in_body(tmp_path):
    lane = _lane(_FakeGitOps(), tmp_path)
    with pytest.raises(RawPayloadViolation):
        lane.ship(
            source="autopilot/w",
            title="x",
            body="질문: 사업기간은? 답변: 12개월 근거: 본 사업의 계약기간은 착수일로부터",
            day="d1",
        )


def test_cli_blocks_on_user_without_enforcement(monkeypatch, capsys):
    monkeypatch.delenv("BIDMATE_SHIP_PROTECTION_VERIFIED", raising=False)
    monkeypatch.delenv("BIDMATE_SHIP_TOKEN_SEPARATED", raising=False)
    rc = ss.main(["--source", "autopilot/work", "--title", "x", "--body", "ok 1", "--day", "d1"])
    assert rc == 2
    assert "blocked-on-user" in capsys.readouterr().err
