"""Env-isolation regression tests for the agent loop (ADR 0090, P2.0→D-minus).

Covers the env-inheritance boundary (the shared ``_ship_env.strip_ship_secret_env`` helper +
the omc lane allowlist) so runner children — write AND read lanes — can never read/spoof the
ship-lane secrets, plus the ``시작-ship`` recipe's defence-in-depth secret strip. The ship
manifest EMISSION seam is DEFERRED to P2.2 (it belongs with the real ship), so this module no
longer exercises it. No network/GitHub is touched.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
# Repo root first so the `scripts.<module>` package form resolves (namespace
# package — no __init__.py), then scripts/ for the bare sibling imports below.
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import agent_loop  # noqa: E402
import agent_loop_claude_turn as claude_turn  # noqa: E402
import agent_loop_codex_turn as codex_turn  # noqa: E402
from _ship_env import SHIP_SECRET_ENV_PREFIX, strip_ship_secret_env  # noqa: E402


# --- _ship_env.strip_ship_secret_env (single source of truth; US-3.1/3.2) ----

def test_strip_ship_secret_env_removes_only_ship_prefix_keeps_path_home():
    env = {
        "BIDMATE_SHIP_MERGE_TOKEN": "t",
        "BIDMATE_SHIP_PROTECTION_VERIFIED": "1",
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "ANTHROPIC_API_KEY": "k",
    }
    result = strip_ship_secret_env(env)
    # No BIDMATE_SHIP_* survives.
    assert not any(k.startswith(SHIP_SECRET_ENV_PREFIX) for k in result)
    # Non-secret shell basics preserved (not over-tight).
    assert result["PATH"] == "/usr/bin"
    assert result["HOME"] == "/home/x"
    # ANTHROPIC_API_KEY is out of scope for THIS helper (popped at the claude lane).


def test_strip_ship_secret_env_no_ship_var_unchanged():
    env = {"PATH": "/usr/bin", "HOME": "/home/x"}
    assert strip_ship_secret_env(env) == env
    # Empty env round-trips unchanged too.
    assert strip_ship_secret_env({}) == {}


def test_ship_secret_env_prefix_literal():
    # Single-source prefix literal lives in _ship_env only.
    assert SHIP_SECRET_ENV_PREFIX == "BIDMATE_SHIP_"


# --- omc lane coverage (US-3.3) ----------------------------------------------

def test_omc_allowlist_excludes_ship_secrets():
    assert "BIDMATE_SHIP_MERGE_TOKEN" not in agent_loop._OMC_ENV_ALLOWLIST
    assert "BIDMATE_SHIP_PROTECTION_VERIFIED" not in agent_loop._OMC_ENV_ALLOWLIST


# --- Makefile 시작-ship env-strip dry-run (ADR 0090, Fix 1) -------------------

def test_makefile_sijak_ship_strips_inherited_ship_secrets():
    import subprocess as _sp

    result = _sp.run(
        ["make", "-n", "시작-ship"],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        check=True,
    )
    out = result.stdout
    # The loop sub-make must be launched with EVERY inherited BIDMATE_SHIP_* var
    # explicitly unset via a PREFIX-strip loop (not a fixed allowlist) so a
    # future/unknown BIDMATE_SHIP_FUTURE_SECRET can never enter the workspace-write
    # loop process. The prefix-strip sed pattern + the `unset` loop must be present.
    assert "BIDMATE_SHIP_[A-Za-z0-9_]*" in out, "expected prefix-strip sed pattern in 시작-ship recipe"
    assert "unset" in out, "expected an `unset` loop over the matched BIDMATE_SHIP_* vars"
    # The kill-switch is a CONTROL signal, NOT a secret: it must NOT be stripped, and
    # the lane must honor it BEFORE the loop phase (a pre-check, not a post-step-only
    # guard). So the recipe pre-checks the kill-switch and aborts before `make 시작`.
    # In the strip loop, BIDMATE_SHIP_KILL_SWITCH is the kept var (the `continue` case).
    assert "BIDMATE_SHIP_KILL_SWITCH" in out, "kill-switch must be referenced (kept) in the strip loop"
    assert "continue" in out, "kill-switch must be the `continue`/kept var in the strip loop"
    assert "kill-switch engaged" in out, "expected a kill-switch pre-check before the loop phase"
    # The manifest EMISSION seam is DEFERRED to P2.2: the loop sub-make must receive NO
    # ship signal at all, so BIDMATE_SHIP_MANIFEST_DIR must NOT be injected into it.
    # (The post-step _staging_ship.py invocation passes --manifest-dir; that is not an
    # injection into the loop sub-make, so we check the loop-side variable assignment.)
    assert "BIDMATE_SHIP_MANIFEST_DIR=" not in out, "manifest emission is deferred to P2.2; no MANIFEST_DIR in the loop"
    # The prefix-strip loop precedes the loop sub-make invocation (`make 시작`). The
    # make binary path is non-deterministic, so anchor on the trailing ` 시작` token.
    strip_idx = out.index("BIDMATE_SHIP_[A-Za-z0-9_]*")
    submake_idx = out.index("make 시작", strip_idx) if "make 시작" in out[strip_idx:] else out.index(" 시작", strip_idx)
    assert strip_idx < submake_idx
    # The kill-switch pre-check fires BEFORE the strip/sub-make line.
    assert out.index("kill-switch engaged") < strip_idx


# --- turn-module import robustness (bare + package context; ADR 0090) --------

def test_turn_modules_import_in_package_context():
    # Package form (`scripts.<module>`, run from repo root) must resolve even
    # though `_ship_env` is a bare sibling — the ImportError fallback proves it.
    pkg_codex = importlib.import_module("scripts.agent_loop_codex_turn")
    pkg_claude = importlib.import_module("scripts.agent_loop_claude_turn")
    assert callable(pkg_codex.strip_ship_secret_env)
    assert callable(pkg_claude.strip_ship_secret_env)


# --- read-lane default-runner coverage (the missed leaks; ADR 0090) ----------

class _CapturedRun:
    """Stand-in for subprocess.run that captures the env kwarg and returns a stub proc."""

    def __init__(self, stdout: str = "{}"):
        self.captured_env: dict[str, str] | None = None
        self._stdout = stdout

    def __call__(self, *args, **kwargs):  # noqa: D401 - simple capture
        self.captured_env = kwargs.get("env")

        class _Proc:
            returncode = 0
            stdout = self._stdout  # type: ignore[assignment]
            stderr = ""

        proc = _Proc()
        proc.stdout = self._stdout
        return proc


def test_codex_read_lane_default_runner_strips_ship_secret_keeps_path(monkeypatch, tmp_path):
    monkeypatch.setenv("BIDMATE_SHIP_MERGE_TOKEN", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    cap = _CapturedRun()
    monkeypatch.setattr(codex_turn.subprocess, "run", cap)
    companion = tmp_path / "codex-companion.mjs"
    companion.write_text("// stub\n", encoding="utf-8")
    codex_turn._default_runner(companion, "origin/main", "branch", "", "")
    assert cap.captured_env is not None
    assert not any(k.startswith(SHIP_SECRET_ENV_PREFIX) for k in cap.captured_env)
    assert cap.captured_env["PATH"] == "/usr/bin"
    assert cap.captured_env["HOME"] == str(tmp_path)


def test_codex_auth_probe_strips_ship_secret_keeps_path(monkeypatch, tmp_path):
    # The pre-runner `codex login status` auth probe is runner-adjacent — it must
    # build an env with no BIDMATE_SHIP_* (ADR 0090 env-isolation), matching the
    # write/read lane strips. Capture the env via the injectable runner.
    monkeypatch.setenv("BIDMATE_SHIP_MERGE_TOKEN", "secret")
    monkeypatch.setenv("BIDMATE_SHIP_MANIFEST_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    cap = _CapturedRun(stdout="Logged in using ChatGPT")
    agent_loop._active_codex_auth_check(
        auth_mode="chatgpt",
        codex_executable="codex",
        execute=True,
        runner=cap,
    )
    assert cap.captured_env is not None
    assert not any(k.startswith(SHIP_SECRET_ENV_PREFIX) for k in cap.captured_env)
    assert cap.captured_env["PATH"] == "/usr/bin"
    assert cap.captured_env["HOME"] == str(tmp_path)


def test_claude_read_lane_default_runner_strips_ship_secret_keeps_path(monkeypatch, tmp_path):
    monkeypatch.setenv("BIDMATE_SHIP_MERGE_TOKEN", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    cap = _CapturedRun(stdout='{"verdict": "approved"}')
    monkeypatch.setattr(claude_turn.subprocess, "run", cap)
    claude_turn._default_runner(["claude", "-p", "x"], timeout=None)
    assert cap.captured_env is not None
    assert not any(k.startswith(SHIP_SECRET_ENV_PREFIX) for k in cap.captured_env)
    assert cap.captured_env["PATH"] == "/usr/bin"
    assert cap.captured_env["HOME"] == str(tmp_path)
    # ANTHROPIC_API_KEY is also dropped on this lane (subscription-OAuth path, ADR 0082).
    assert "ANTHROPIC_API_KEY" not in cap.captured_env


def test_claude_version_probe_strips_ship_secret_keeps_path(monkeypatch, tmp_path):
    # The pre-runner `claude --version` capability probe is runner-adjacent — it must
    # build a subprocess env with no BIDMATE_SHIP_* (ADR 0090 env-isolation), matching
    # the write/read lane strips. Capture the env via a monkeypatched subprocess.run.
    monkeypatch.setenv("BIDMATE_SHIP_MERGE_TOKEN", "secret")
    monkeypatch.setenv("BIDMATE_SHIP_MANIFEST_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    cap = _CapturedRun(stdout="2.1.150 (Claude Code)")
    monkeypatch.setattr(agent_loop.subprocess, "run", cap)
    # The probe memoizes via a mutable-default cache list — reset it so this call
    # actually exercises the subprocess path rather than returning a cached verdict.
    monkeypatch.setattr(
        agent_loop._claude_cli_supports_effort, "__defaults__", ([],)
    )
    agent_loop._claude_cli_supports_effort()
    assert cap.captured_env is not None
    assert not any(k.startswith(SHIP_SECRET_ENV_PREFIX) for k in cap.captured_env)
    assert cap.captured_env["PATH"] == "/usr/bin"
    assert cap.captured_env["HOME"] == str(tmp_path)
