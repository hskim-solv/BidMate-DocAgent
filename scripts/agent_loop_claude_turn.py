"""Read-only Claude lane adapter for the active-loop `agent-turn` (issue #1590).

Invokes `claude -p` in plan permission mode with a read-only tool allowlist and a
write/ship denylist, asking for output that conforms to
`schemas/review_artifact.schema.json`. Parses the `--output-format json` wrapper
into the shared review-artifact core (verdict / summary / findings / next_steps).
No writes, no patches, no ship.

The agent-turn caller (scripts/agent_loop.py) owns privacy scrubbing, artifact
persistence, Work Unit accounting, and the session heartbeat. This module never
raises on tool failure — it returns a ``verdict="error"`` core so the caller can
record a deterministic non-pass heartbeat. The subprocess call is injectable via
``runner`` so tests never shell out to the real `claude` binary.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Sequence

# Read-only lane: plan mode already blocks mutation; the denylist is belt-and-suspenders.
DEFAULT_ALLOWED_TOOLS = (
    "Read",
    "Grep",
    "Glob",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git status:*)",
)
DEFAULT_DISALLOWED_TOOLS = (
    "Edit",
    "Write",
    "NotebookEdit",
    "Bash(git push:*)",
    "Bash(git commit:*)",
    "Bash(git merge:*)",
    "Bash(gh:*)",
    "Bash(make:*)",
)
_VERDICTS = {"approved", "clear", "needs-attention", "blocked", "error"}
_SEVERITIES = {"blocker", "warning", "info"}

# runner(cmd) -> CompletedProcess; injectable for tests.
ClaudeRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def build_command(
    *,
    prompt: str,
    schema_path: Path,
    allowed_tools: Sequence[str] = DEFAULT_ALLOWED_TOOLS,
    disallowed_tools: Sequence[str] = DEFAULT_DISALLOWED_TOOLS,
) -> list[str]:
    return [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        str(schema_path),
        "--permission-mode",
        "plan",
        "--allowedTools",
        " ".join(allowed_tools),
        "--disallowedTools",
        " ".join(disallowed_tools),
    ]


def _default_runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def run_turn(
    *,
    prompt: str,
    schema_path: Path,
    allowed_tools: Sequence[str] = DEFAULT_ALLOWED_TOOLS,
    disallowed_tools: Sequence[str] = DEFAULT_DISALLOWED_TOOLS,
    runner: ClaudeRunner | None = None,
) -> dict[str, object]:
    """Return the core review-artifact fields from a read-only Claude turn."""
    run = runner or _default_runner
    cmd = build_command(
        prompt=prompt,
        schema_path=schema_path,
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )
    try:
        proc = run(cmd)
    except OSError as exc:
        return _error(f"claude invocation failed: {exc}")
    if proc.returncode != 0:
        tail = next((line for line in reversed((proc.stderr or "").splitlines()) if line.strip()), "")
        return _error(f"claude rc={proc.returncode}: {tail}".strip())
    core = _extract_core(proc.stdout or "")
    return core if core is not None else _error("claude emitted unparseable output")


def _extract_core(stdout: str) -> dict[str, object] | None:
    try:
        outer = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    candidate: object = outer
    if isinstance(outer, dict) and "result" in outer:
        candidate = outer["result"]
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(candidate, dict):
        return None
    return _normalize_core(candidate)


def _normalize_core(obj: dict[str, object]) -> dict[str, object]:
    verdict = str(obj.get("verdict") or "needs-attention")
    if verdict not in _VERDICTS:
        verdict = "needs-attention"
    summary = str(obj.get("summary") or "").strip() or "Claude review complete."
    raw_findings = obj.get("findings")
    findings = [
        _normalize_finding(item)
        for item in (raw_findings if isinstance(raw_findings, list) else [])
        if isinstance(item, dict)
    ]
    raw_steps = obj.get("next_steps")
    next_steps = [str(step) for step in (raw_steps if isinstance(raw_steps, list) else []) if isinstance(step, str)]
    return {"verdict": verdict, "summary": summary, "findings": findings, "next_steps": next_steps}


def _normalize_finding(finding: dict[str, object]) -> dict[str, object]:
    severity = str(finding.get("severity") or "info")
    if severity not in _SEVERITIES:
        severity = "info"
    out: dict[str, object] = {"severity": severity, "title": str(finding.get("title") or "(untitled)")}
    body = str(finding.get("body") or "").strip()
    if body:
        out["body"] = body
    recommendation = str(finding.get("recommendation") or "").strip()
    if recommendation:
        out["recommendation"] = recommendation
    return out


def _error(message: str) -> dict[str, object]:
    return {"verdict": "error", "summary": message, "findings": [], "next_steps": []}
