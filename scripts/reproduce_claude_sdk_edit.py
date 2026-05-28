#!/usr/bin/env python3
"""SDK-side mirror of `reproduce_claude_edit_tool.py`.

The `-p` print mode matrix in the sibling script established that headless
`claude -p` Edit-tool calls fail (#1598 F4 `tool_use ids must be unique`) across
all measured permission modes. The Claude Agent SDK uses the same `claude`
binary but forces a different transport (`_is_streaming = True` in
`claude_agent_sdk/_internal/transport/subprocess_cli.py` — i.e.
`--input-format stream-json --output-format stream-json --verbose`).

This script sweeps the SDK's `PermissionMode` literal (default, acceptEdits,
plan, bypassPermissions, dontAsk, auto — same six in SDK 0.2.87) with a
trivial edit task to confirm the SDK transport bypasses the bug.

Usage:
    .venv/bin/python scripts/reproduce_claude_sdk_edit.py [--out DIR] [--timeout SEC] [--cells N]

Subscription OAuth is forced by stripping ANTHROPIC_API_KEY / BASE_URL /
AUTH_TOKEN before importing the SDK.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(_k, None)


from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)


TARGET_INITIAL = "a\n"
TARGET_EXPECTED = "b\n"
PROMPT_TPL = (
    "Edit the file {path} so its only line reads exactly 'b' instead of 'a'. "
    "Use the Edit tool. After one successful edit, stop."
)
SDK_PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")


@dataclass
class CellResult:
    label: str
    permission_mode: str
    exit_code: int | None
    duration_s: float
    tool_use_count: int
    tool_result_count: int
    edited: bool
    symptom: str
    result_subtype: str | None
    result_is_error: bool | None
    result_text: str
    exception: str | None
    stdout_log: str


def classify(*, edited: bool, exception: str | None, result_subtype: str | None,
             result_is_error: bool | None, result_text: str, duration: float, timeout: float,
             tool_use_count: int) -> str:
    if edited:
        return "S4_normal"
    if duration >= timeout - 0.5:
        return "S3_timeout"
    if exception:
        if "tool_use" in exception and "unique" in exception:
            return "S2_tool_use_ids"
        return "S2_or_other_exception"
    if result_subtype == "success" and not result_is_error and tool_use_count >= 1:
        return "S4_success_without_target_match"
    haystack = result_text or ""
    if "tool_use" in haystack and "unique" in haystack:
        return "S2_tool_use_ids"
    if result_is_error:
        return "S2_or_other_error"
    if tool_use_count == 0:
        return "S1_no_tool_call"
    return "S5_unknown"


async def run_cell(permission_mode: str, *, timeout: float, log_path: Path) -> CellResult:
    work = Path(tempfile.mkdtemp(prefix="claude-sdk-cell-"))
    target = work / "foo.txt"
    target.write_text(TARGET_INITIAL, encoding="utf-8")
    prompt = PROMPT_TPL.format(path=str(target))

    options = ClaudeAgentOptions(
        cwd=str(work),
        allowed_tools=["Edit", "Read"],
        permission_mode=permission_mode if permission_mode != "default" else None,  # type: ignore[arg-type]
        add_dirs=[str(work)],
    )

    log_lines: list[str] = []
    tool_use_count = 0
    tool_result_count = 0
    result_subtype: str | None = None
    result_is_error: bool | None = None
    result_text = ""
    exception: str | None = None

    start = time.monotonic()
    try:
        async def _consume() -> None:
            nonlocal tool_use_count, tool_result_count, result_subtype, result_is_error, result_text
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, ToolUseBlock):
                            tool_use_count += 1
                            log_lines.append(f"tool_use id={block.id} name={block.name}")
                        elif isinstance(block, TextBlock):
                            log_lines.append(f"text: {block.text[:200]}")
                elif isinstance(msg, UserMessage):
                    items = msg.content if isinstance(msg.content, list) else []
                    for block in items:
                        if isinstance(block, ToolResultBlock):
                            tool_result_count += 1
                            log_lines.append(f"tool_result id={block.tool_use_id} is_error={block.is_error}")
                elif isinstance(msg, ResultMessage):
                    result_subtype = msg.subtype
                    result_is_error = msg.is_error
                    if isinstance(msg.result, str):
                        result_text = msg.result[:400]
                    elif msg.result is not None:
                        result_text = str(msg.result)[:400]
                elif isinstance(msg, SystemMessage):
                    pass
                else:
                    log_lines.append(f"other: {type(msg).__name__}")

        await asyncio.wait_for(_consume(), timeout=timeout)
    except asyncio.TimeoutError:
        exception = "asyncio.TimeoutError"
    except Exception as exc:
        exception = f"{type(exc).__name__}: {exc}"

    duration = time.monotonic() - start
    after = target.read_text(encoding="utf-8") if target.exists() else "<missing>"
    edited = after == TARGET_EXPECTED

    symptom = classify(
        edited=edited,
        exception=exception,
        result_subtype=result_subtype,
        result_is_error=result_is_error,
        result_text=result_text,
        duration=duration,
        timeout=timeout,
        tool_use_count=tool_use_count,
    )

    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    return CellResult(
        label=f"sdk_{permission_mode}",
        permission_mode=permission_mode,
        exit_code=0 if symptom == "S4_normal" else (None if symptom == "S3_timeout" else 1),
        duration_s=round(duration, 2),
        tool_use_count=tool_use_count,
        tool_result_count=tool_result_count,
        edited=edited,
        symptom=symptom,
        result_subtype=result_subtype,
        result_is_error=result_is_error,
        result_text=result_text,
        exception=exception,
        stdout_log=str(log_path),
    )


async def main_async(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = list(SDK_PERMISSION_MODES)
    if args.cells > 0:
        modes = modes[: args.cells]

    print(f"# SDK modes: {modes}", flush=True)
    print(f"# timeout per cell: {args.timeout}s\n", flush=True)

    results: list[CellResult] = []
    for idx, mode in enumerate(modes, start=1):
        print(f"[{idx}/{len(modes)}] sdk_{mode} ...", flush=True)
        log_path = out_dir / f"sdk_{mode}.log"
        result = await run_cell(mode, timeout=args.timeout, log_path=log_path)
        results.append(result)
        print(
            f"    -> symptom={result.symptom} edited={result.edited} "
            f"tool_use={result.tool_use_count} tool_result={result.tool_result_count} "
            f"dur={result.duration_s}s",
            flush=True,
        )

    matrix = {
        "transport": "claude_agent_sdk.SubprocessCLITransport (stream-json)",
        "sdk_version": _sdk_version(),
        "results": [r.__dict__ for r in results],
    }
    (out_dir / "sdk_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")

    print("\n| # | permission_mode | Symptom | Edited | tool_use | duration_s |")
    print("|---|---|---|---|---|---|")
    for idx, r in enumerate(results, start=1):
        print(f"| {idx} | `{r.permission_mode}` | **{r.symptom}** | {'yes' if r.edited else 'no'} | {r.tool_use_count} | {r.duration_s} |")

    counts: dict[str, int] = {}
    for r in results:
        counts[r.symptom] = counts.get(r.symptom, 0) + 1
    print(f"\n# symptom counts: {counts}")

    s4 = [r for r in results if r.symptom.startswith("S4")]
    if len(s4) == len(results):
        print(f"\n# VERDICT: 모든 SDK permission mode 에서 S4 정상 동작 — SDK transport 가 -p print mode 의 직렬화 버그를 우회.")
        return 0
    print(f"\n# VERDICT: {len(s4)}/{len(results)} mode 만 S4 — SDK 도 일부 mode 에서 분기 깨짐.")
    return 1


def _sdk_version() -> str:
    try:
        import claude_agent_sdk
        return getattr(claude_agent_sdk, "__version__", "unknown")
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/agent_loop/claude_edit_repro_sdk")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--cells", type=int, default=0)
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
