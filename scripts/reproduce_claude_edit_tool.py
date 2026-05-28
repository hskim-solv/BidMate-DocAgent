#!/usr/bin/env python3
"""Minimal reproduction for the "claude -p Edit-tool is broken" assertion.

Background: `scripts/agent_loop_claude_turn.py:6-9, 68-70` and
`docs/operations/active-agent-loop.md:190-191` claim that headless `claude -p`
Edit-tool is broken in all permission modes. The assertion derives from issue
#1598 F4 ("tool_use ids must be unique") observed once during the read-only
lane bring-up — there is no independent measurement of the Edit-tool path.

This script sweeps a small flag matrix and writes a result table so we can
classify each cell as S1 (tool not invoked) / S2 ("tool_use ids must be unique"
API error) / S3 (timeout) / S4 (edit applied). Per-cell fresh mktemp dir; no
shared /tmp paths (CLAUDE.md "Don't" rule on fixed /tmp targets).

Usage:
    python3 scripts/reproduce_claude_edit_tool.py [--out DIR] [--timeout SEC] [--cells N]

The script is intentionally NOT in tests/ — it shells out to the real `claude`
binary which is not available in CI. Result table is printed to stdout and
written to <out>/matrix.json for PR-description attachment.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


# Strip env vars that would force claude to use a raw Anthropic API key path.
# The goal here is to measure the SUBSCRIPTION (OAuth) surface — same path a
# real BidMate-DocAgent user invokes via `make ship-arm` / agent-loop. Leaving
# ANTHROPIC_API_KEY in the child env makes claude bypass subscription auth.
_API_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def subscription_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _API_ENV_KEYS}
    return env


TARGET_INITIAL = "a\n"
TARGET_EXPECTED = "b\n"
PROMPT_PLAIN = "Edit the file {path} so its only line reads exactly 'b' instead of 'a'. Use the Edit tool. After one successful edit, stop."
PROMPT_EXPLICIT = "Use the Edit tool to replace 'a' with 'b' in {path}. Stop immediately after one edit succeeds."


@dataclass
class Cell:
    label: str
    flags: list[str]
    prompt: str
    note: str = ""


@dataclass
class CellResult:
    label: str
    cmd: list[str]
    exit_code: int | None
    duration_s: float
    stdout_head: str
    stderr_tail: str
    file_after: str
    edited: bool
    symptom: str
    note: str = ""
    stdout_path: str = ""
    stderr_path: str = ""


def build_matrix() -> list[Cell]:
    """Eight primary cells targeting the most plausible fix axes.

    Each cell isolates one variable against an "acceptEdits + json + add-dir"
    baseline so the failing axis is obvious from the matrix.
    """
    return [
        Cell(
            label="01_baseline_acceptEdits_json_addDir",
            flags=[
                "--permission-mode", "acceptEdits",
                "--output-format", "json",
                "--allowedTools", "Edit",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="baseline w/ acceptEdits + json + Edit allowed (no add-dir)",
        ),
        Cell(
            label="02_acceptEdits_json_addDir_explicit",
            flags=[
                "--permission-mode", "acceptEdits",
                "--output-format", "json",
                "--allowedTools", "Edit",
                "--no-session-persistence",
            ],
            prompt=PROMPT_EXPLICIT,
            note="explicit 'Use the Edit tool' prompt variant",
        ),
        Cell(
            label="03_bypassPermissions_json",
            flags=[
                "--permission-mode", "bypassPermissions",
                "--output-format", "json",
                "--allowedTools", "Edit",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="bypassPermissions mode",
        ),
        Cell(
            label="04_dangerously_skip_perms",
            flags=[
                "--dangerously-skip-permissions",
                "--output-format", "json",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="dangerously-skip-permissions (sandbox-style)",
        ),
        Cell(
            label="05_acceptEdits_text_output",
            flags=[
                "--permission-mode", "acceptEdits",
                "--output-format", "text",
                "--allowedTools", "Edit",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="text output instead of json (rules out json wrapper coupling)",
        ),
        Cell(
            label="06_default_mode_no_perm_flag",
            flags=[
                "--output-format", "json",
                "--allowedTools", "Edit",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="omit --permission-mode entirely (default mode)",
        ),
        Cell(
            label="07_acceptEdits_tools_form",
            flags=[
                "--permission-mode", "acceptEdits",
                "--output-format", "json",
                "--tools", "Edit,Read",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="--tools built-in form instead of --allowedTools",
        ),
        Cell(
            label="08_plan_mode_with_edit",
            flags=[
                "--permission-mode", "plan",
                "--output-format", "json",
                "--allowedTools", "Edit",
                "--no-session-persistence",
            ],
            prompt=PROMPT_PLAIN,
            note="plan mode — expected to reproduce #1598 F4 'tool_use ids must be unique'",
        ),
    ]


def run_cell(cell: Cell, *, timeout: float, out_dir: Path) -> CellResult:
    """Run one matrix cell against a fresh mktemp working dir."""
    work = Path(tempfile.mkdtemp(prefix="claude-edit-repro-"))
    target = work / "foo.txt"
    target.write_text(TARGET_INITIAL, encoding="utf-8")
    prompt = cell.prompt.format(path=str(target))

    cmd: list[str] = ["claude", "-p", prompt, *cell.flags, "--add-dir", str(work)]

    stdout_file = out_dir / f"{cell.label}.stdout.txt"
    stderr_file = out_dir / f"{cell.label}.stderr.txt"

    start = time.monotonic()
    exit_code: int | None
    child_env = subscription_env()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=child_env,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    duration = time.monotonic() - start

    stdout_file.write_text(stdout, encoding="utf-8")
    stderr_file.write_text(stderr, encoding="utf-8")

    file_after = target.read_text(encoding="utf-8") if target.exists() else "<missing>"
    edited = file_after == TARGET_EXPECTED
    symptom = classify(exit_code=exit_code, stdout=stdout, stderr=stderr, edited=edited, duration=duration, timeout=timeout)

    shutil.rmtree(work, ignore_errors=True)

    return CellResult(
        label=cell.label,
        cmd=cmd,
        exit_code=exit_code,
        duration_s=round(duration, 2),
        stdout_head=stdout[:400].strip(),
        stderr_tail=stderr.strip().splitlines()[-1] if stderr.strip() else "",
        file_after=file_after,
        edited=edited,
        symptom=symptom,
        note=cell.note,
        stdout_path=str(stdout_file),
        stderr_path=str(stderr_file),
    )


def classify(*, exit_code: int | None, stdout: str, stderr: str, edited: bool, duration: float, timeout: float) -> str:
    if edited:
        return "S4_normal"
    if exit_code is None or duration >= timeout - 0.5:
        return "S3_timeout"
    # The `tool_use ids must be unique` API error is surfaced two ways depending
    # on --output-format: (a) wrapped inside the JSON `result` field with
    # is_error=true, or (b) printed verbatim to stdout when --output-format=text.
    # stderr usually stays empty for this class of failure.
    haystack = f"{stdout}\n{stderr}"
    if "tool_use" in haystack and "unique" in haystack:
        return "S2_tool_use_ids"
    return "S1_no_tool_call"


def render_markdown_table(results: Sequence[CellResult]) -> str:
    lines = [
        "| # | Cell | Symptom | Exit | Edited | Duration (s) | stderr tail | Note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for idx, r in enumerate(results, start=1):
        stderr_cell = r.stderr_tail.replace("|", "\\|")[:80]
        note_cell = r.note.replace("|", "\\|")
        exit_str = "timeout" if r.exit_code is None else str(r.exit_code)
        lines.append(
            f"| {idx} | `{r.label}` | **{r.symptom}** | {exit_str} | {'✓' if r.edited else '✗'} | {r.duration_s} | `{stderr_cell}` | {note_cell} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/agent_loop/claude_edit_repro", help="output dir for matrix.json + per-cell logs")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-cell subprocess timeout (s)")
    parser.add_argument("--cells", type=int, default=0, help="run only first N cells (0 = all)")
    args = parser.parse_args(argv)

    if shutil.which("claude") is None:
        print("ERROR: `claude` binary not found on PATH", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    matrix = build_matrix()
    if args.cells > 0:
        matrix = matrix[: args.cells]

    version = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=False).stdout.strip()
    print(f"# claude version: {version}", flush=True)
    print(f"# cells: {len(matrix)}, timeout: {args.timeout}s\n", flush=True)

    results: list[CellResult] = []
    for idx, cell in enumerate(matrix, start=1):
        print(f"[{idx}/{len(matrix)}] {cell.label} ...", flush=True)
        result = run_cell(cell, timeout=args.timeout, out_dir=out_dir)
        results.append(result)
        print(f"    -> symptom={result.symptom} exit={result.exit_code} edited={result.edited} dur={result.duration_s}s", flush=True)

    matrix_json = {
        "claude_version": version,
        "results": [r.__dict__ for r in results],
    }
    (out_dir / "matrix.json").write_text(json.dumps(matrix_json, indent=2, default=str), encoding="utf-8")

    print("\n" + render_markdown_table(results))
    print(f"\n# matrix written to {out_dir}/matrix.json")

    # Summary
    counts: dict[str, int] = {}
    for r in results:
        counts[r.symptom] = counts.get(r.symptom, 0) + 1
    print(f"# symptom counts: {counts}")

    # Verdict
    s4 = [r for r in results if r.symptom == "S4_normal"]
    if s4:
        print(f"\n# VERDICT: S4 found — winning flag sets = {[r.label for r in s4]}")
        print("# Next: write-lane extension feasible via wrapper; PR-B path.")
        return 0
    print("\n# VERDICT: no S4 cell. escape hatch (D) — upstream repro + footnote.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
