"""Read-only Claude lane adapter for the active-loop `agent-turn` (issue #1590, ADR 0082).

Invokes ``claude -p`` (Claude Code CLI subprocess) with the unified diff embedded in the
prompt, an inline ``--json-schema``, a read-only tool allowlist, and a write/ship denylist.
The diff is embedded rather than fetched via claude's own tools because headless ``-p``
tool use crashes the API ("tool_use ids must be unique", issue #1598 F4); plan mode is
likewise dropped.

ADR 0082: claude lane stays on the **subscription-OAuth path** (Pro/Max quota), never on
Anthropic Messages API direct calls — this preserves the user's "subscription only" policy
(memory: project_claude_sdk_credit_policy) and inherits the same trust contract as the
codex lane (ADR 0066: user CLI install + auth = explicit egress consent). The CLI also
exposes ``--model`` and ``--effort`` (claude-code 2.1+ — verified 2.1.153) so the per-role
model × effort matrix in ``scripts/agent_loop.py`` can drive the lane without resorting
to the Messages API. ``--effort`` accepts ``low | medium | high | xhigh | max``;
``xhigh`` is Opus-4-7-only and the caller normalizes that via ``_validate_effort_for_model``.

The agent-turn caller (scripts/agent_loop.py) owns privacy scrubbing, artifact persistence,
Work Unit accounting, and the session heartbeat. This module never raises on tool failure —
it returns a ``verdict="error"`` core so the caller can record a deterministic non-pass
heartbeat. The subprocess call is injectable via ``runner`` so tests never shell out to the
real ``claude`` binary.
"""
from __future__ import annotations

import json
import os
import re
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
    model: str = "",
    effort: str = "",
    allowed_tools: Sequence[str] = DEFAULT_ALLOWED_TOOLS,
    disallowed_tools: Sequence[str] = DEFAULT_DISALLOWED_TOOLS,
) -> list[str]:
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    # ADR 0082: per-role model + effort (Sonnet medium / Opus xhigh / etc.). Empty strings
    # mean "use the user's claude settings default" — the agent-turn caller resolves the
    # role profile before calling here so empty fall-throughs only happen in unit tests.
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    # `--json-schema` expects the schema JSON *inline*, not a file path — passing a path
    # crashes the claude binary (issue #1598 F2). Inline the file content; omit the flag if
    # the schema is unreadable so the lane still runs (the prompt carries the required shape).
    try:
        schema_text = schema_path.read_text(encoding="utf-8").strip()
    except OSError:
        schema_text = ""
    if schema_text:
        cmd += ["--json-schema", schema_text]
    # No --permission-mode plan: in headless `-p`, plan mode + tool use crashes the API with
    # "tool_use ids must be unique" (issue #1598 F4). The diff is embedded in the prompt so
    # the lane needs no tools; the read-only allowlist + mutation denylist stay as defense.
    if allowed_tools:
        cmd += ["--allowedTools", " ".join(allowed_tools)]
    if disallowed_tools:
        cmd += ["--disallowedTools", " ".join(disallowed_tools)]
    return cmd


def _default_runner(
    cmd: list[str], *, timeout: float | None = None
) -> "subprocess.CompletedProcess[str]":
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, env=env, timeout=timeout
    )


def _invoke_runner(
    run: "ClaudeRunner", cmd: list[str], timeout: float | None
) -> "subprocess.CompletedProcess[str]":
    """Call ``run(cmd, timeout=...)``, falling back to ``run(cmd)`` for legacy 1-arg runners.

    The injected ``runner`` contract historically took only ``cmd``; the timeout kwarg is
    additive (ADR 0085). Test runners that accept just ``cmd`` keep working — the timeout is
    then enforced only on the real ``_default_runner`` path.
    """
    try:
        return run(cmd, timeout=timeout)  # type: ignore[call-arg]
    except TypeError:
        return run(cmd)


def run_turn(
    *,
    prompt: str,
    schema_path: Path,
    model: str = "",
    effort: str = "",
    allowed_tools: Sequence[str] = DEFAULT_ALLOWED_TOOLS,
    disallowed_tools: Sequence[str] = DEFAULT_DISALLOWED_TOOLS,
    runner: ClaudeRunner | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, object]:
    """Return the core review-artifact fields from a read-only Claude turn.

    ``timeout_seconds`` (ADR 0085) bounds the subprocess so a hung Claude session cannot
    stall the caller. Semantics mirror the unlimited-by-default policy: ``0`` / ``None`` /
    any non-positive value means *no* timeout (unlimited), and a positive value (the
    wall-clock-derived budget the caller threads when one is set) bounds the call to that
    many seconds. On ``subprocess.TimeoutExpired`` the lane collapses to ``verdict="error"``
    — the same deterministic non-pass contract the adapter already honors for tool/parse
    failures — and the timed-out subprocess is killed so it does not leak.
    """
    run = runner or _default_runner
    effective_timeout = (
        timeout_seconds if isinstance(timeout_seconds, int) and timeout_seconds > 0 else None
    )
    cmd = build_command(
        prompt=prompt,
        schema_path=schema_path,
        model=model,
        effort=effort,
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )
    try:
        # ``subprocess.run(..., timeout=...)`` kills the child and reaps it before re-raising
        # TimeoutExpired, so the timed-out subprocess does not leak on the real runner path.
        proc = _invoke_runner(run, cmd, effective_timeout)
    except subprocess.TimeoutExpired as exc:
        return _error(f"claude timed out after {exc.timeout}s")
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
            candidate = json.loads(_strip_code_fences(candidate))
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(candidate, dict):
        return None
    return _normalize_core(candidate)


def _strip_code_fences(text: str) -> str:
    """Strip a leading/trailing markdown code fence (claude 2.1.3 wraps result JSON; F3)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z0-9_-]*\s*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


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
