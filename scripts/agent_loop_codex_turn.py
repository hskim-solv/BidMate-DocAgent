"""Read-only Codex lane adapter for the active-loop `agent-turn` (issue #1590).

Runs the Codex companion `adversarial-review` (ADR 0066) in read-only mode and
maps its JSON output into the shared review-artifact core
(`schemas/review_artifact.schema.json`): verdict / summary / findings / next_steps.
No writes, no patches, no ship — review only. The companion path is resolved by
glob over the plugin cache (the ADR 0066 "symlink/glob follow-up"), not the
version-pinned literal the CI workflow uses.

The agent-turn caller (scripts/agent_loop.py) owns privacy scrubbing, artifact
persistence, Work Unit accounting, and the session heartbeat. This module only
produces the core review fields and never raises on tool failure — it returns a
``verdict="error"`` core instead, so the caller can record a deterministic
non-pass heartbeat.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

try:
    from scripts._ship_env import strip_ship_secret_env
except ImportError:  # bare sibling import (run from scripts/ dir)
    from _ship_env import strip_ship_secret_env

HOME = Path(os.path.expanduser("~"))
COMPANION_GLOB = ".claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs"

# Codex adversarial-review severity -> review_artifact severity (plan collapse).
_SEVERITY_COLLAPSE = {
    "critical": "blocker",
    "high": "blocker",
    "medium": "warning",
    "low": "info",
}
# Codex verdict -> review_artifact verdict.
_VERDICT_MAP = {
    "approve": "approved",
    "needs-attention": "needs-attention",
}

# runner(companion, base, scope, focus, model) -> CompletedProcess; injectable for tests.
# ADR 0082: model is explicit per-role; `adversarial-review` supports `--model` (companion 1.0.4
# line 684 valueOptions: ["base", "scope", "model", "cwd"]). `--effort` is NOT supported by the
# adversarial-review subcommand — env BIDMATE_CODEX_LANE_EFFORT is defined upstream but not
# injected here; companion-side support is a separate follow-up.
CodexRunner = Callable[[Path, str, str, str, str], "subprocess.CompletedProcess[str]"]


def resolve_companion(explicit: str | None = None, *, home: Path = HOME) -> Path | None:
    """Resolve codex-companion.mjs: explicit arg > $CODEX_COMPANION > newest glob match."""
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_file() else None
    env = os.environ.get("CODEX_COMPANION")
    if env and Path(env).is_file():
        return Path(env)
    matches = sorted(glob.glob(str(home / COMPANION_GLOB)))
    return Path(matches[-1]) if matches else None


def _default_runner(
    companion: Path, base: str, scope: str, focus: str, model: str
) -> "subprocess.CompletedProcess[str]":
    cmd = ["node", str(companion), "adversarial-review", "--json", "--base", base, "--scope", scope]
    if model:
        cmd += ["--model", model]
    if focus:
        cmd.append(focus)
    # ADR 0090 env-isolation: the read-only review child must never inherit ship-lane
    # secrets (BIDMATE_SHIP_*). Shared single-source strip; PATH/HOME/auth preserved.
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=strip_ship_secret_env(dict(os.environ)),
    )


def run_turn(
    *,
    base: str = "origin/main",
    scope: str = "branch",
    focus: str = "",
    model: str = "",
    companion_path: str | None = None,
    runner: CodexRunner | None = None,
    home: Path = HOME,
) -> dict[str, object]:
    """Return the core review-artifact fields from a read-only Codex review."""
    companion = resolve_companion(companion_path, home=home)
    if companion is None:
        return _error("codex companion not found (plugin cache glob miss)")
    run = runner or _default_runner
    try:
        proc = run(companion, base, scope, focus, model)
    except OSError as exc:
        return _error(f"codex companion invocation failed: {exc}")
    if proc.returncode != 0:
        tail = next((line for line in reversed((proc.stderr or "").splitlines()) if line.strip()), "")
        return _error(f"codex companion rc={proc.returncode}: {tail}".strip())
    try:
        payload = json.loads(proc.stdout or "")
    except (json.JSONDecodeError, TypeError):
        return _error("codex companion emitted non-JSON output")
    if not isinstance(payload, dict):
        return _error("codex companion output is not a JSON object")
    if payload.get("parseError"):
        return _error(f"codex structured-output rejected: {payload.get('parseError')}")
    raw_result = payload.get("result")
    result: dict[str, object] = raw_result if isinstance(raw_result, dict) else {}
    verdict = _VERDICT_MAP.get(str(result.get("verdict") or ""), "needs-attention")
    summary = str(result.get("summary") or "").strip() or "Codex adversarial review complete."
    raw_findings = result.get("findings")
    findings = [
        _collapse_finding(f)
        for f in (raw_findings if isinstance(raw_findings, list) else [])
        if isinstance(f, dict)
    ]
    raw_steps = result.get("next_steps")
    next_steps = [
        str(step) for step in (raw_steps if isinstance(raw_steps, list) else []) if isinstance(step, str)
    ]
    return {
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "next_steps": next_steps,
    }


def _collapse_finding(finding: dict[str, object]) -> dict[str, object]:
    severity = _SEVERITY_COLLAPSE.get(str(finding.get("severity") or "low"), "info")
    out: dict[str, object] = {"severity": severity, "title": str(finding.get("title") or "(untitled)")}
    body = str(finding.get("body") or "").strip()
    file = str(finding.get("file") or "").strip()
    if file:
        location = file
        line_start, line_end = finding.get("line_start"), finding.get("line_end")
        if isinstance(line_start, int):
            location += f":{line_start}" + (f"-{line_end}" if isinstance(line_end, int) else "")
        body = f"[{location}] {body}".strip()
    if body:
        out["body"] = body
    recommendation = str(finding.get("recommendation") or "").strip()
    if recommendation:
        out["recommendation"] = recommendation
    return out


def _error(message: str) -> dict[str, object]:
    return {"verdict": "error", "summary": message, "findings": [], "next_steps": []}
