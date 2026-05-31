"""Regression tests for the isolated staging self-ship lane (ADR 0088/0090).

Covers the constitutional-invariant guards (force-push / staging boundary /
kill-switch / ship-arm exclusion), the breaker counters (T1 bounded, T4 cap with
self-immutable store), the lane (CI-green gate, fail-closed external enforcement),
the P2.0 ship-manifest contract, and the *live* read-only ``protection_verified``.
git/gh is injected as a fake so no network/GitHub is touched.

D1 scope: the autonomous merge orchestration (open_pr/merge LIVE impls, daily-cap
transactionality, single-instance lock, source-SHA binding, bounded-poll) is deferred
to P2.2; ``_RealGitOps.open_pr``/``merge`` are honest stubs and ``main()`` is a
verify-and-refuse harness that always returns rc 2. Those P2.2 behaviours are NOT
tested here.
"""
from __future__ import annotations

import subprocess
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
        # issue #1697 Fix 4a: the `+src:dst` refspec form is also a force update.
        ["git", "push", "origin", "+main:autopilot/integration"],
        # issue #1697 Fix 4b: `--force*=value` forms (prefix match, not exact).
        ["git", "push", "--force-with-lease=main", "origin", "b"],
        ["git", "push", "--force-if-includes", "origin", "b"],
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
        # issue #1697 Fix 4: a normal `src:dst` refspec (no leading '+') is a
        # fast-forward, NOT a force update — must still be allowed.
        ["git", "push", "origin", "main:autopilot/integration"],
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


# --- P2.0 ship-manifest contract (US-1) --------------------------------------

def test_manifest_round_trips_all_schema_fields(tmp_path):
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="chore: staging self-ship",
        body="5 PRs merged, revert 0",
        day="2026-05-31",
    )
    data = ss.read_ship_manifest(tmp_path)
    assert data is not None
    assert data["schema_version"] == ss.SHIP_MANIFEST_SCHEMA_VERSION
    assert data["source_branch"] == "autopilot/work"
    assert data["source_sha"] == "0123456789abcdef0123456789abcdef01234567"
    assert data["title"] == "chore: staging self-ship"
    assert data["body"] == "5 PRs merged, revert 0"
    assert data["day"] == "2026-05-31"


def test_manifest_read_is_idempotent_not_consumed(tmp_path):
    # G1: read no longer consumes — the manifest stays in place and re-reads return
    # the same dict (resumability for blocked/interrupted runs).
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="t",
        body="ok 1",
        day="d1",
    )
    manifest_path = tmp_path / ss.SHIP_MANIFEST_FILENAME
    consumed_path = tmp_path / ss.SHIP_MANIFEST_CONSUMED
    assert manifest_path.exists()
    first = ss.read_ship_manifest(tmp_path)
    assert first is not None
    # Read did NOT rename: source still present, no consumed file yet.
    assert manifest_path.exists()
    assert not consumed_path.exists()
    # A second read returns the SAME manifest (idempotent / re-readable).
    second = ss.read_ship_manifest(tmp_path)
    assert second == first


def test_archive_ship_manifest_consumes(tmp_path):
    # G1: explicit archive renames ship_manifest.json -> .consumed.json and is a
    # no-op when already gone (idempotent).
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="t",
        body="ok 1",
        day="d1",
    )
    manifest_path = tmp_path / ss.SHIP_MANIFEST_FILENAME
    consumed_path = tmp_path / ss.SHIP_MANIFEST_CONSUMED
    ss.archive_ship_manifest(tmp_path)
    assert not manifest_path.exists()
    assert consumed_path.exists()
    # After consumption a read returns None and a second archive is a no-op.
    assert ss.read_ship_manifest(tmp_path) is None
    ss.archive_ship_manifest(tmp_path)  # no raise


def test_manifest_read_empty_dir_returns_none(tmp_path):
    assert ss.read_ship_manifest(tmp_path) is None


def test_manifest_missing_required_key_raises(tmp_path):
    import json

    # Hand-write a manifest missing the required "day" key.
    payload = {
        "schema_version": ss.SHIP_MANIFEST_SCHEMA_VERSION,
        "source_branch": "autopilot/work",
        "title": "t",
        "body": "ok 1",
    }
    (tmp_path / ss.SHIP_MANIFEST_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        ss.read_ship_manifest(tmp_path)


def test_manifest_missing_source_sha_key_raises(tmp_path):
    import json

    # source_sha is part of the D1 required-keys contract (merge-binding for P2.2).
    payload = {
        "schema_version": ss.SHIP_MANIFEST_SCHEMA_VERSION,
        "source_branch": "autopilot/work",
        "title": "t",
        "body": "ok 1",
        "day": "d1",
    }
    (tmp_path / ss.SHIP_MANIFEST_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        ss.read_ship_manifest(tmp_path)


@pytest.mark.parametrize("bad_sha", ["", "notahex", "abc123", "0123456789ABCDEF" * 2 + "01234567"])
def test_manifest_malformed_source_sha_raises(tmp_path, bad_sha):
    import json

    # A present-but-malformed source_sha (empty / non-hex / too short / uppercase) must
    # fail closed — the SHA binds the deferred P2.2 merge to the exact gated commit.
    payload = {
        "schema_version": ss.SHIP_MANIFEST_SCHEMA_VERSION,
        "source_branch": "autopilot/work",
        "source_sha": bad_sha,
        "title": "t",
        "body": "ok 1",
        "day": "d1",
    }
    (tmp_path / ss.SHIP_MANIFEST_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        ss.read_ship_manifest(tmp_path)


def test_manifest_valid_40_hex_source_sha_ok(tmp_path):
    import json

    sha = "0123456789abcdef0123456789abcdef01234567"
    payload = {
        "schema_version": ss.SHIP_MANIFEST_SCHEMA_VERSION,
        "source_branch": "autopilot/work",
        "source_sha": sha,
        "title": "t",
        "body": "ok 1",
        "day": "d1",
    }
    (tmp_path / ss.SHIP_MANIFEST_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    data = ss.read_ship_manifest(tmp_path)
    assert data is not None
    assert data["source_sha"] == sha


def test_manifest_wrong_schema_version_raises(tmp_path):
    import json

    payload = {
        "schema_version": 999,
        "source_branch": "autopilot/work",
        "source_sha": "0123456789abcdef0123456789abcdef01234567",
        "title": "t",
        "body": "ok 1",
        "day": "d1",
    }
    (tmp_path / ss.SHIP_MANIFEST_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        ss.read_ship_manifest(tmp_path)


# --- P2.0 D1 _RealGitOps.protection_verified with injected fake runner (US-2) -

class _FakeProc:
    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class _FakeRunner:
    """Canned-response runner keyed by the leading argv tokens.

    Each call records (argv, kwargs); responses are looked up by an argv-prefix
    match so tests can assert the exact argv passed to ``self._run``.
    """

    def __init__(self, responses: list[tuple[list[str], _FakeProc]]):
        self._responses = responses
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})
        for prefix, proc in self._responses:
            if list(argv)[: len(prefix)] == prefix:
                return proc
        return _FakeProc(returncode=1, stdout="")


_REPO_VIEW_OK = (
    ["gh", "repo", "view"],
    _FakeProc(0, '{"owner": {"login": "o"}, "name": "r"}'),
)


_FORCE_ABSENT = object()  # sentinel: omit allow_force_pushes entirely
_ADMINS_ABSENT = object()  # sentinel: omit enforce_admins entirely
_STRICT_ABSENT = object()  # sentinel: omit required_status_checks.strict entirely


def _protection_proc(
    *,
    contexts=None,
    checks=None,
    force_enabled=False,
    admins_enabled=True,
    strict=True,
    rc=0,
):
    body = {"required_status_checks": {}}
    # required_status_checks.strict: explicit True by default (require branches
    # up-to-date, issue #1697 Fix 1); sentinel omits the key entirely.
    if strict is not _STRICT_ABSENT:
        body["required_status_checks"]["strict"] = strict
    # allow_force_pushes: explicit dict by default; sentinel omits the key entirely.
    if force_enabled is not _FORCE_ABSENT:
        body["allow_force_pushes"] = {"enabled": force_enabled}
    # enforce_admins: explicit dict by default; sentinel omits the key entirely.
    if admins_enabled is not _ADMINS_ABSENT:
        body["enforce_admins"] = {"enabled": admins_enabled}
    if contexts is not None:
        body["required_status_checks"]["contexts"] = contexts
    if checks is not None:
        body["required_status_checks"]["checks"] = checks
    import json

    return (["gh", "api"], _FakeProc(rc, json.dumps(body)))


def test_real_protection_verified_true_when_all_conditions_met():
    # The ADR 0088 authority check must be present (via contexts) + force-push denied.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is True


def test_real_protection_verified_true_via_checks_context_shape():
    # Same authority check, but expressed through the `checks[].context` shape.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            checks=[{"context": ss._REQUIRED_STAGING_CHECK}],
            force_enabled=False,
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is True


def test_real_protection_verified_false_when_only_other_check_present():
    # A required check exists, but it is NOT the staging-self-ship-guard authority.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=["ci/build"], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_protection_api_404():
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        (["gh", "api"], _FakeProc(returncode=1, stdout="")),  # absent / 404
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_force_push_enabled():
    # Authority check present, but force-push allowed => still False (force path).
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=True),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_required_checks_empty():
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[], checks=[], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_repo_view_fails():
    # gh repo view failure => cannot derive owner/repo => fail closed False.
    runner = _FakeRunner([
        (["gh", "repo", "view"], _FakeProc(returncode=1, stdout="")),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


# --- BLOCKING fix: gh subprocess environmental failure must fail CLOSED -------
# (issue #1697) gh missing / timeout / invalid cwd must return False, NEVER raise
# out of protection_verified (which would crash main()).


class _RaisingRunner:
    """A runner whose every invocation raises *exc* (records calls first)."""

    def __init__(self, exc: BaseException):
        self._exc = exc
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})
        raise self._exc


def test_real_protection_verified_false_when_gh_missing_no_raise():
    # gh binary absent: subprocess.run raises FileNotFoundError (an OSError) =>
    # verification failure, NOT a traceback out of the verifier.
    runner = _RaisingRunner(FileNotFoundError("gh: command not found"))
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False
    assert runner.calls, "expected the gh repo view call to be attempted"


def test_real_protection_verified_false_when_gh_times_out_no_raise():
    # A hung gh: subprocess.run raises TimeoutExpired => fail closed False.
    runner = _RaisingRunner(subprocess.TimeoutExpired(cmd="gh", timeout=ss._GH_TIMEOUT_SEC))
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_cwd_invalid_no_raise():
    # An invalid repo_root (cwd) raises NotADirectoryError (an OSError) => fail closed.
    runner = _RaisingRunner(NotADirectoryError("invalid cwd"))
    ops = ss._RealGitOps(run=runner, repo_root="/no/such/dir")
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_passes_bounded_timeout_to_runner():
    # The gh subprocess call carries the bounded _GH_TIMEOUT_SEC so a hung gh cannot
    # wedge the verifier.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner)
    ops.protection_verified("autopilot/integration")
    assert runner.calls
    for call in runner.calls:
        assert call["kwargs"].get("timeout") == ss._GH_TIMEOUT_SEC


# --- Fix 1: protection_verified binds gh invocation to repo_root (cwd) ---------

def test_real_protection_verified_binds_gh_to_repo_root_cwd():
    # codex Fix 1: gh must resolve THIS repo regardless of process cwd, so every
    # injected runner call must carry cwd=repo_root (not the process working dir).
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner, repo_root="/some/repo/root")
    ops.protection_verified("autopilot/integration")
    assert runner.calls, "expected at least the gh repo view call"
    for call in runner.calls:
        assert call["kwargs"].get("cwd") == "/some/repo/root"


# --- Fix 3: the read-only verify must not inherit ambient gh repo/creds --------

def test_real_protection_verified_strips_ambient_gh_env(monkeypatch):
    # issue #1697 Fix 3: GH_REPO could misdirect the protection read at the wrong
    # repo; GH_TOKEN / GITHUB_TOKEN / GH_ENTERPRISE_TOKEN would over-privilege a
    # read-only verify. None may reach the gh subprocess env.
    monkeypatch.setenv("GH_REPO", "evil/other-repo")
    monkeypatch.setenv("GH_TOKEN", "ghp_mutation")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_mutation")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "ghe_mutation")
    monkeypatch.setenv("PATH_KEEPME", "kept")  # a harmless var must survive
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner)
    ops.protection_verified("autopilot/integration")
    assert runner.calls, "expected at least the gh repo view call"
    for call in runner.calls:
        env = call["kwargs"].get("env")
        assert env is not None
        assert "GH_REPO" not in env
        assert "GH_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env
        assert "GH_ENTERPRISE_TOKEN" not in env
        # Non-sensitive ambient vars are preserved (operator's default gh auth env).
        assert env.get("PATH_KEEPME") == "kept"


# --- Fix 2: protection fails CLOSED on incomplete state (no fail-open) ---------

def test_real_protection_verified_false_when_force_push_key_absent():
    # codex Fix 2a: an ABSENT allow_force_pushes key is NOT proof of denial.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=_FORCE_ABSENT
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_force_push_enabled_true():
    # codex Fix 2b: allow_force_pushes.enabled=true => fail closed.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=True),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_enforce_admins_absent():
    # codex Fix 2c: enforce_admins absent => admins could bypass => fail closed.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            contexts=[ss._REQUIRED_STAGING_CHECK],
            force_enabled=False,
            admins_enabled=_ADMINS_ABSENT,
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_enforce_admins_disabled():
    # codex Fix 2c: enforce_admins.enabled=false => admin bypass => fail closed.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            contexts=[ss._REQUIRED_STAGING_CHECK],
            force_enabled=False,
            admins_enabled=False,
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_true_with_full_valid_protection():
    # codex Fix 2d: guard check present + force-push explicitly denied +
    # enforce_admins explicitly enabled + required_status_checks.strict True
    # (issue #1697 Fix 1) => the ONLY True path.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            contexts=[ss._REQUIRED_STAGING_CHECK],
            force_enabled=False,
            admins_enabled=True,
            strict=True,
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is True


# --- Fix 1: required_status_checks.strict must be explicitly True --------------

def test_real_protection_verified_false_when_strict_absent():
    # issue #1697 Fix 1: an ABSENT required_status_checks.strict is NOT proof that
    # branches must be up-to-date => fail closed (a stale source could be merged).
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            contexts=[ss._REQUIRED_STAGING_CHECK],
            force_enabled=False,
            admins_enabled=True,
            strict=_STRICT_ABSENT,
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


def test_real_protection_verified_false_when_strict_false():
    # issue #1697 Fix 1: strict=false (branches NOT required up-to-date) => fail closed.
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(
            contexts=[ss._REQUIRED_STAGING_CHECK],
            force_enabled=False,
            admins_enabled=True,
            strict=False,
        ),
    ])
    ops = ss._RealGitOps(run=runner)
    assert ops.protection_verified("autopilot/integration") is False


# --- G4 protection_verified URL-encodes the slashed branch in the gh api path -

def test_real_protection_verified_url_encodes_slashed_branch():
    runner = _FakeRunner([
        _REPO_VIEW_OK,
        _protection_proc(contexts=[ss._REQUIRED_STAGING_CHECK], force_enabled=False),
    ])
    ops = ss._RealGitOps(run=runner)
    ops.protection_verified("autopilot/integration")
    api_call = next(c for c in runner.calls if c["argv"][:2] == ["gh", "api"])
    # The slash in the branch must be percent-encoded so the gh api path is valid.
    assert "autopilot%2Fintegration" in api_call["argv"][2]
    assert "autopilot/integration" not in api_call["argv"][2]


# --- D1: merge orchestration is a deferred-to-P2.2 stub -----------------------

def test_real_open_pr_is_deferred_stub():
    # D1 does not auto-merge: open_pr refuses rather than fakes.
    ops = ss._RealGitOps(run=_FakeRunner([]))
    with pytest.raises(ss.EnforcementNotVerified):
        ops.open_pr(source="autopilot/work", base="autopilot/integration", title="t", body="ok 1")


def test_real_merge_is_deferred_stub():
    ops = ss._RealGitOps(run=_FakeRunner([]))
    with pytest.raises(ss.EnforcementNotVerified):
        ops.merge("7")


def test_real_required_checks_is_deferred_stub_returns_false():
    ops = ss._RealGitOps(run=_FakeRunner([]))
    assert ops.required_checks_all_success("7") is False


# --- D1 main() verify-and-refuse harness (NEVER merges) -----------------------

def test_cli_blocks_on_user_with_no_manifest_and_no_source(monkeypatch, tmp_path, capsys):
    # No manifest AND no --source => still rc 2 with the "no ship manifest" message.
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _FakeProc(1, ""))
    rc = ss.main(["--title", "x", "--body", "ok 1", "--day", "d1", "--manifest-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "blocked-on-user: no ship manifest" in err


def test_cli_no_manifest_no_source_still_runs_live_protection_check(monkeypatch, tmp_path, capsys):
    # issue #1697 Fix 2: the headline D-minus value (the LIVE branch-protection
    # verifier) must run + be reported even on the default `make 시작-ship` path
    # (no manifest, no --source) BEFORE the rc 2 refusal. Spy the gh subprocess to
    # prove protection_verified was actually exercised.
    calls: list[list[str]] = []

    def spy_run(argv, **kwargs):
        calls.append(list(argv))
        return _FakeProc(1, "")  # fail closed (gh unreachable) — verify still RAN

    monkeypatch.setattr(ss.subprocess, "run", spy_run)
    rc = ss.main(["--manifest-dir", str(tmp_path)])
    assert rc == 2
    # protection_verified WAS invoked: it shelled out to `gh repo view`.
    assert any(c[:3] == ["gh", "repo", "view"] for c in calls), (
        "expected the live protection pre-flight to invoke gh repo view"
    )
    err = capsys.readouterr().err
    # The live check was reported (NOT verified, since gh was unreachable) AND the
    # default path still refuses with the "no ship manifest" message.
    assert "NOT verified" in err
    assert "blocked-on-user: no ship manifest" in err


def test_cli_blocks_on_user_with_manifest_present_defers_to_p2_2(monkeypatch, tmp_path, capsys):
    # With a manifest present (cap store / merge token NOT required in D1), main()
    # LIVE-verifies protection (False via injected fake runner) then refuses, citing
    # P2.2. It must NEVER merge.
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="chore: t",
        body="ok 1",
        day="2026-05-31",
    )

    # protection_verified resolves False without touching the network: repo view ok,
    # protection api returns a required check that is NOT staging-self-ship-guard.
    class _FakeProcLocal:
        def __init__(self, rc, out=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    def fake_run(argv, **kwargs):
        if list(argv)[:3] == ["gh", "repo", "view"]:
            return _FakeProcLocal(0, '{"owner": {"login": "o"}, "name": "r"}')
        if list(argv)[:2] == ["gh", "api"]:
            return _FakeProcLocal(
                0,
                '{"required_status_checks": {"contexts": ["ci/build"]}, '
                '"allow_force_pushes": {"enabled": false}}',
            )
        return _FakeProcLocal(1, "")

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    rc = ss.main(["--manifest-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "blocked-on-user" in err
    assert "P2.2" in err
    assert "does not yet auto-merge" in err


def test_cli_reports_enforcement_verified_then_still_refuses(monkeypatch, tmp_path, capsys):
    # Even when protection IS verified live (True via injected fake runner), D1 STILL
    # refuses to merge (rc 2) and cites P2.2 — it only verifies read-only.
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="chore: t",
        body="ok 1",
        day="2026-05-31",
    )

    class _FakeProcLocal:
        def __init__(self, rc, out=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    def fake_run(argv, **kwargs):
        if list(argv)[:3] == ["gh", "repo", "view"]:
            return _FakeProcLocal(0, '{"owner": {"login": "o"}, "name": "r"}')
        if list(argv)[:2] == ["gh", "api"]:
            # Full valid protection: guard check + strict (branches up-to-date,
            # issue #1697 Fix 1) + explicit force-push-deny + enforce_admins enabled
            # (codex Fix 2 — the only True path).
            return _FakeProcLocal(
                0,
                '{"required_status_checks": {"contexts": ["staging-self-ship-guard"], '
                '"strict": true}, '
                '"allow_force_pushes": {"enabled": false}, '
                '"enforce_admins": {"enabled": true}}',
            )
        return _FakeProcLocal(1, "")

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    rc = ss.main(["--manifest-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "is VERIFIED" in err
    assert "P2.2" in err
    assert "does not yet auto-merge" in err


def test_cli_does_not_consume_manifest(monkeypatch, tmp_path, capsys):
    # D1 never ships, so it must leave the manifest in place (no archive).
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="chore: t",
        body="ok 1",
        day="2026-05-31",
    )

    class _FakeProcLocal:
        def __init__(self, rc, out=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _FakeProcLocal(1, ""))
    ss.main(["--manifest-dir", str(tmp_path)])
    assert (tmp_path / ss.SHIP_MANIFEST_FILENAME).exists()
    assert not (tmp_path / ss.SHIP_MANIFEST_CONSUMED).exists()


def test_cli_returns_2_no_traceback_when_gh_unavailable(monkeypatch, tmp_path, capsys):
    # BLOCKING fix (issue #1697): when gh is unavailable the subprocess raises, but
    # main() must still return rc 2 cleanly (fail closed) — no traceback escapes.
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="chore: t",
        body="ok 1",
        day="2026-05-31",
    )

    def raising_run(argv, **kwargs):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(ss.subprocess, "run", raising_run)
    rc = ss.main(["--manifest-dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "NOT verified" in err
    assert "P2.2" in err


def test_cli_blocks_on_kill_switch(monkeypatch, tmp_path, capsys):
    # Local guard: kill-switch engaged => fail closed rc 2 before any gh call.
    ss.write_ship_manifest(
        tmp_path,
        source_branch="autopilot/work",
        source_sha="0123456789abcdef0123456789abcdef01234567",
        title="chore: t",
        body="ok 1",
        day="2026-05-31",
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "KILL").write_text("stop")
    rc = ss.main(["--manifest-dir", str(tmp_path), "--state-dir", str(state_dir)])
    assert rc == 2
    assert "kill-switch" in capsys.readouterr().err
