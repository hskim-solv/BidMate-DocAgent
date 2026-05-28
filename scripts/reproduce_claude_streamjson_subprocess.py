#!/usr/bin/env python3
"""Direct-subprocess mirror of `reproduce_claude_sdk_edit.py`.

Question this script answers: does the #1598 F4 bypass come from `claude-agent-sdk`
itself, or from the underlying `--input-format stream-json --output-format
stream-json --verbose` CLI transport? If the latter, BidMate could adopt the
streaming transport without taking the SDK dependency (relevant under Anthropic's
2026-06-15 separate agent-credit policy — fewer prereqs to drop later).

Mirrors the SDK transport's command shape from
`claude_agent_sdk/_internal/transport/subprocess_cli.py:225,408`:
    claude --output-format stream-json --verbose --input-format stream-json
           [--permission-mode ...] [--allowedTools ...] [--add-dir ...]

stdin protocol (from `claude_agent_sdk/client.py:263`):
    {"type":"user","message":{"role":"user","content":"<prompt>"}}\\n

stdout protocol: one JSON object per line. The terminal object has
`type=="result"` with `subtype`, `is_error`, `result`.

Subscription OAuth is forced by stripping ANTHROPIC_API_KEY / BASE_URL /
AUTH_TOKEN before invocation.

Usage:
    python3 scripts/reproduce_claude_streamjson_subprocess.py [--out DIR] [--timeout SEC] [--cells N]
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


TARGET_INITIAL = "a\n"
TARGET_EXPECTED = "b\n"
PROMPT_TPL = (
    "Edit the file {path} so its only line reads exactly 'b' instead of 'a'. "
    "Use the Edit tool. After one successful edit, stop."
)
# Mirror SDK 0.2.87's `PermissionMode` Literal. CLI 2.1.3 also accepts
# `delegate` (not in SDK enum); SDK adds `auto` (not in CLI 2.1.3 print-mode
# matrix). We test what the SDK matrix tested for direct comparison.
SDK_PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto")
_API_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


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
    raw_lines: int
    log_path: str


def subscription_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _API_ENV_KEYS}


def build_command(*, permission_mode: str, work: Path) -> list[str]:
    cmd = [
        "claude",
        "--output-format", "stream-json",
        "--verbose",
        "--input-format", "stream-json",
        "--allowedTools", "Edit,Read",
        "--add-dir", str(work),
    ]
    if permission_mode != "default":
        cmd += ["--permission-mode", permission_mode]
    return cmd


def classify(*, edited: bool, exception: str | None, result_subtype: str | None,
             result_is_error: bool | None, result_text: str, duration: float,
             timeout: float, tool_use_count: int) -> str:
    if edited:
        return "S4_normal"
    if duration >= timeout - 0.5:
        return "S3_timeout"
    haystack = (result_text or "") + (exception or "")
    if "tool_use" in haystack and "unique" in haystack:
        return "S2_tool_use_ids"
    if exception:
        return "S2_or_other_exception"
    if result_subtype == "success" and not result_is_error and tool_use_count >= 1:
        return "S4_success_without_target_match"
    if result_is_error:
        return "S2_or_other_error"
    if tool_use_count == 0:
        return "S1_no_tool_call"
    return "S5_unknown"


async def run_cell(permission_mode: str, *, timeout: float, log_path: Path) -> CellResult:
    work = Path(tempfile.mkdtemp(prefix="claude-streamjson-cell-"))
    target = work / "foo.txt"
    target.write_text(TARGET_INITIAL, encoding="utf-8")
    prompt = PROMPT_TPL.format(path=str(target))

    cmd = build_command(permission_mode=permission_mode, work=work)
    user_message = json.dumps(
        {"type": "user", "message": {"role": "user", "content": prompt}}
    ) + "\n"

    raw_lines_collected: list[str] = []
    tool_use_count = 0
    tool_result_count = 0
    result_subtype: str | None = None
    result_is_error: bool | None = None
    result_text = ""
    exception: str | None = None
    exit_code: int | None = None

    start = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(work),
        env=subscription_env(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _drive() -> None:
        nonlocal tool_use_count, tool_result_count, result_subtype, result_is_error, result_text
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(user_message.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            raw_lines_collected.append(line)
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_type = obj.get("type")
            if msg_type == "assistant":
                content = obj.get("message", {}).get("content") or []
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_count += 1
                        elif block.get("type") == "text":
                            pass
            elif msg_type == "user":
                content = obj.get("message", {}).get("content") or []
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_result_count += 1
            elif msg_type == "result":
                result_subtype = obj.get("subtype")
                result_is_error = obj.get("is_error")
                raw_result = obj.get("result")
                if isinstance(raw_result, str):
                    result_text = raw_result[:400]
                elif raw_result is not None:
                    result_text = str(raw_result)[:400]

    try:
        await asyncio.wait_for(_drive(), timeout=timeout)
        exit_code = await proc.wait()
    except asyncio.TimeoutError:
        exception = "asyncio.TimeoutError"
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
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

    log_path.write_text("\n".join(raw_lines_collected), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    return CellResult(
        label=f"streamjson_{permission_mode}",
        permission_mode=permission_mode,
        exit_code=exit_code,
        duration_s=round(duration, 2),
        tool_use_count=tool_use_count,
        tool_result_count=tool_result_count,
        edited=edited,
        symptom=symptom,
        result_subtype=result_subtype,
        result_is_error=result_is_error,
        result_text=result_text,
        exception=exception,
        raw_lines=len(raw_lines_collected),
        log_path=str(log_path),
    )


async def main_async(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = list(SDK_PERMISSION_MODES)
    if args.cells > 0:
        modes = modes[: args.cells]

    print(f"# modes: {modes}", flush=True)
    print(f"# timeout per cell: {args.timeout}s\n", flush=True)

    results: list[CellResult] = []
    for idx, mode in enumerate(modes, start=1):
        print(f"[{idx}/{len(modes)}] streamjson_{mode} ...", flush=True)
        log_path = out_dir / f"streamjson_{mode}.jsonl"
        result = await run_cell(mode, timeout=args.timeout, log_path=log_path)
        results.append(result)
        print(
            f"    -> symptom={result.symptom} edited={result.edited} "
            f"tool_use={result.tool_use_count} tool_result={result.tool_result_count} "
            f"raw_lines={result.raw_lines} dur={result.duration_s}s",
            flush=True,
        )

    matrix = {
        "transport": "direct subprocess (--input-format stream-json --output-format stream-json --verbose)",
        "results": [r.__dict__ for r in results],
    }
    (out_dir / "streamjson_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")

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
        print(f"\n# VERDICT: 모든 mode 에서 S4 — SDK 없이 stream-json transport 만으로 #1598 F4 우회 가능.")
        return 0
    print(f"\n# VERDICT: {len(s4)}/{len(results)} mode 만 S4 — SDK 가 transport 외에 추가 layer 를 제공.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/agent_loop/claude_edit_repro_streamjson")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--cells", type=int, default=0)
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
