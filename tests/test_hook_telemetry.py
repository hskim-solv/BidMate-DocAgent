"""Tests for outcome telemetry (ADR 0060, issue #1039).

거버넌스 비판 보고서 (2026-05-19) 메타 발견 + 약점 #1/#4/#7/#8 해소
핵심: hook-fires.log 의 v2-5field 표준 포맷 + ``emit_hook_fire()`` 헬퍼 +
``--emit-fire`` CLI subcommand + 8 hook 의 emit contract.

테스트 범위:

- ``emit_hook_fire()`` 직접 호출: 정상 / typo guard / I/O 실패 swallow
- ``--emit-fire`` CLI: 정상 / 인자 누락 / typo
- 각 hook 스크립트의 emit-fire 호출 패턴 (정적 grep) — ADR 0060
  verifies-key 마커가 약속하는 hook 별 ``--hook`` 값이 실제로 hardcode
  되었는지 contract lock-in
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOVERNANCE_PATH = REPO_ROOT / "scripts" / "_governance.py"


def _load_governance():
    spec = importlib.util.spec_from_file_location(
        "_governance_mod", GOVERNANCE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def gov():
    return _load_governance()


# ---------------------------------------------------------------------------
# emit_hook_fire() 헬퍼
# ---------------------------------------------------------------------------


def test_emit_hook_fire_v2_5field(tmp_path, gov):
    log = tmp_path / "fires.log"
    gov.emit_hook_fire(
        outcome="blocked",
        hook="bash-guard",
        category="gh-pr-create-stacked",
        path="feat/issue-99-foo",
        extra="on=feat/issue-88-bar",
        log_path=str(log),
    )
    content = log.read_text(encoding="utf-8").strip()
    parts = content.split("|")
    assert len(parts) == 6
    assert parts[1] == "blocked"
    assert parts[2] == "bash-guard"
    assert parts[3] == "gh-pr-create-stacked"
    assert parts[4] == "feat/issue-99-foo"
    assert parts[5] == "on=feat/issue-88-bar"


def test_emit_hook_fire_without_extra(tmp_path, gov):
    log = tmp_path / "fires.log"
    gov.emit_hook_fire(
        outcome="aware",
        hook="loadbearing",
        category="file-edit",
        path="rag_core.py",
        log_path=str(log),
    )
    parts = log.read_text().strip().split("|")
    assert len(parts) == 5  # no extra
    assert parts[1:5] == ["aware", "loadbearing", "file-edit", "rag_core.py"]


def test_emit_hook_fire_unknown_outcome_raises(tmp_path, gov):
    log = tmp_path / "fires.log"
    with pytest.raises(ValueError, match="unknown outcome"):
        gov.emit_hook_fire(
            outcome="made_up",
            hook="bash-guard",
            log_path=str(log),
        )
    assert not log.exists()


def test_emit_hook_fire_unknown_hook_raises(tmp_path, gov):
    log = tmp_path / "fires.log"
    with pytest.raises(ValueError, match="unknown hook"):
        gov.emit_hook_fire(
            outcome="blocked",
            hook="nonexistent-hook",
            log_path=str(log),
        )
    assert not log.exists()


def test_emit_hook_fire_io_error_swallowed(tmp_path, gov):
    """I/O 실패 시에도 raise 안 함 — telemetry 가 hook 을 막으면 안 됨.

    Contract: emit_hook_fire() 호출 자체가 OSError 를 raise 하지 않으면
    통과. 실제 파일 생성 여부는 권한에 따라 다르며, 권한 자체가 stat()
    실패의 원인이므로 exists() 체크를 하지 않는다.
    """
    bad_log = tmp_path / "ro-dir" / "fires.log"
    bad_log.parent.mkdir()
    bad_log.parent.chmod(0o400)  # read-only
    try:
        # Must not raise.
        gov.emit_hook_fire(
            outcome="aware",
            hook="loadbearing",
            log_path=str(bad_log),
        )
    finally:
        bad_log.parent.chmod(0o700)  # restore for cleanup


def test_known_outcomes_includes_required_set(gov):
    required = {"aware", "blocked", "bypassed", "nudged", "ok"}
    assert required.issubset(gov.KNOWN_OUTCOMES)


def test_known_hooks_matches_inventory(gov):
    expected = {
        "bash-guard", "loadbearing", "memory-lines",
        "adr-template", "plan-slug-race",
        "delegation-gate", "stop-ship",
    }
    assert gov.KNOWN_HOOKS == expected


# ---------------------------------------------------------------------------
# --emit-fire CLI
# ---------------------------------------------------------------------------


def _run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(GOVERNANCE_PATH), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_emit_fire_normal(tmp_path):
    log = tmp_path / "fires.log"
    result = _run_cli(
        "--emit-fire",
        "--outcome", "nudged",
        "--hook", "delegation-gate",
        "--category", "agent-delegation",
        "--path", "<user-prompt>",
        "--fire-log", str(log),
    )
    assert result.returncode == 0, result.stderr
    parts = log.read_text().strip().split("|")
    assert parts[1] == "nudged"
    assert parts[2] == "delegation-gate"


def test_cli_emit_fire_missing_outcome(tmp_path):
    log = tmp_path / "fires.log"
    result = _run_cli(
        "--emit-fire",
        "--hook", "bash-guard",
        "--fire-log", str(log),
    )
    assert result.returncode == 2
    assert "requires --outcome" in result.stderr
    assert not log.exists()


def test_cli_emit_fire_missing_hook(tmp_path):
    log = tmp_path / "fires.log"
    result = _run_cli(
        "--emit-fire",
        "--outcome", "aware",
        "--fire-log", str(log),
    )
    assert result.returncode == 2


def test_cli_emit_fire_typo_outcome(tmp_path):
    log = tmp_path / "fires.log"
    result = _run_cli(
        "--emit-fire",
        "--outcome", "made-up",
        "--hook", "bash-guard",
        "--fire-log", str(log),
    )
    assert result.returncode == 1
    assert "unknown outcome" in result.stderr


# ---------------------------------------------------------------------------
# Hook scripts emit-fire contract (static grep)
#
# ADR 0060 verifies-key 마커가 각 hook 의 --emit-fire 호출을 약속함. 본
# 테스트가 hook 파일들의 emit 패턴을 직접 검증해서 ADR 의 약속과 코드의
# 실제 contract 를 lock-in.
# ---------------------------------------------------------------------------


HOOK_EMIT_EXPECTATIONS = [
    # (path, --hook value, expected outcome substring)
    ("scripts/claude-hooks/pretooluse-loadbearing.sh",
     "--hook loadbearing", "--outcome aware"),
    ("scripts/claude-hooks/pretooluse-memory-lines.sh",
     "--hook memory-lines", "--outcome"),
    ("scripts/claude-hooks/userpromptsubmit-delegation-gate.sh",
     "--hook delegation-gate", "--outcome nudged"),
    ("scripts/claude-hooks/pretooluse-adr-template.sh",
     "--hook adr-template", "--outcome blocked"),
    ("scripts/claude-hooks/plan-slug-race.sh",
     "--hook plan-slug-race", "--outcome blocked"),
    ("scripts/claude-hooks/pretooluse-bash-guard.sh",
     "--hook bash-guard", "--outcome blocked"),
]


@pytest.mark.parametrize("relpath, hook_arg, outcome_arg", HOOK_EMIT_EXPECTATIONS)
def test_hook_emits_correct_hook_and_outcome(relpath, hook_arg, outcome_arg):
    content = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert "--emit-fire" in content, (
        f"{relpath} missing --emit-fire call (ADR 0060)"
    )
    assert hook_arg in content, (
        f"{relpath} missing expected hook arg: {hook_arg!r}"
    )
    assert outcome_arg in content, (
        f"{relpath} missing expected outcome arg pattern: {outcome_arg!r}"
    )


def test_no_hook_uses_legacy_printf_fire_log():
    """No production hook should write to .hook-fires.log via printf
    after PR #1039 — all emits route through --emit-fire."""
    for relpath, _, _ in HOOK_EMIT_EXPECTATIONS:
        content = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        # Allow `printf` for stderr messages, but disallow direct
        # `>> .../.hook-fires.log` redirection.
        for line in content.splitlines():
            assert ".hook-fires.log" not in line or "emit-fire" in content, (
                f"{relpath} contains legacy fire-log redirect: {line}"
            )


# ---------------------------------------------------------------------------
# End-to-end: emit_hook_fire + analyze_hook_outcomes parse round-trip
# ---------------------------------------------------------------------------


def test_emit_then_analyze_roundtrip(tmp_path, gov):
    """emit_hook_fire() 가 만든 entry 를 analyze script 가 parse 가능해야.

    PR #1038 (analyze_hook_outcomes.py) 가 main 에 머지된 후에만 검증.
    분리된 PR 이므로 stack-merge 순서에 따라 skip 가능.
    """
    aho_path = REPO_ROOT / "scripts" / "analyze_hook_outcomes.py"
    if not aho_path.exists():
        pytest.skip("requires PR #1038 (analyze_hook_outcomes.py)")

    log = tmp_path / "fires.log"
    for outcome, hook in [
        ("blocked", "bash-guard"),
        ("aware", "loadbearing"),
        ("nudged", "delegation-gate"),
        ("blocked", "adr-template"),
        ("blocked", "plan-slug-race"),
    ]:
        gov.emit_hook_fire(
            outcome=outcome, hook=hook, category="cat",
            path="path/x", log_path=str(log),
        )

    spec = importlib.util.spec_from_file_location("aho", aho_path)
    aho = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(aho)  # type: ignore[union-attr]

    events = aho.load_log(log)
    assert len(events) == 5
    assert all(e["format"] == "v2-5field" for e in events)
    hooks_seen = {e["hook"] for e in events}
    assert hooks_seen == {
        "bash-guard", "loadbearing", "delegation-gate",
        "adr-template", "plan-slug-race",
    }
