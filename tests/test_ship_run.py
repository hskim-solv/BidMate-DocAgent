"""Tests for the Codex-runnable auto-ship entrypoint."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIP_RUN_PATH = REPO_ROOT / "scripts" / "claude-hooks" / "_ship_run.py"


def _load_ship_run():
    spec = importlib.util.spec_from_file_location("_ship_run_mod", SHIP_RUN_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _args(**overrides):
    values = {
        "ttl": "30m",
        "real_eval": "skip",
        "draft": "true",
        "dry_run": "1",
        "cross_owner": "ack",
        "stacked": "ack",
        "use_existing_arm": "0",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_run_ship_arms_then_invokes_dispatcher(tmp_path, monkeypatch):
    ship_run = _load_ship_run()
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\n")
        return subprocess.CompletedProcess(cmd, 0)

    assert ship_run.run_ship(_args(), runner=fake_run) == 0
    assert len(calls) == 3
    assert calls[0][0][:3] == ["git", "rev-parse", "--show-toplevel"]
    assert calls[1][0][1].endswith("_ship_arm.py")
    assert "--real-eval" in calls[1][0]
    assert "skip" in calls[1][0]
    assert calls[1][1] == {"check": False, "cwd": tmp_path}
    assert calls[2][0][0] == "bash"
    assert calls[2][0][1].endswith("stop-ship.sh")
    assert calls[2][1]["input"] == ""
    assert calls[2][1]["text"] is True
    assert calls[2][1]["check"] is False
    assert calls[2][1]["cwd"] == tmp_path


def test_run_ship_refuses_existing_arm_without_reuse(tmp_path, monkeypatch, capsys):
    ship_run = _load_ship_run()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".ship-armed").write_text("{}\n")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\n")
        return subprocess.CompletedProcess(cmd, 0)

    assert ship_run.run_ship(_args(), runner=fake_run) == 1
    assert len(calls) == 1
    assert calls[0][0][:3] == ["git", "rev-parse", "--show-toplevel"]
    assert "already exists" in capsys.readouterr().err


def test_run_ship_reuses_existing_arm(tmp_path, monkeypatch):
    ship_run = _load_ship_run()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".ship-armed").write_text("{}\n")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\n")
        return subprocess.CompletedProcess(cmd, 0)

    assert ship_run.run_ship(_args(use_existing_arm="1"), runner=fake_run) == 0
    assert len(calls) == 2
    assert calls[0][0][:3] == ["git", "rev-parse", "--show-toplevel"]
    assert calls[1][0][0] == "bash"
    assert calls[1][0][1].endswith("stop-ship.sh")


def test_run_ship_returns_arm_failure(tmp_path, monkeypatch):
    ship_run = _load_ship_run()
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\n")
        return subprocess.CompletedProcess(cmd, 7)

    assert ship_run.run_ship(_args(), runner=fake_run) == 7
    assert len(calls) == 2
    assert calls[1][0][1].endswith("_ship_arm.py")
