#!/usr/bin/env python3
"""Analyze ``.claude/.hook-fires.log`` outcomes for governance ROI measurement.

거버넌스 비판 보고서 (2026-05-19) #7 후속.

90일 데이터 누적 후 사용자가 실행해 (a) hook 별 fire 분포 + outcome
breakdown, (b) memory-lines AWARE/BLOCK threshold 정당화 데이터, (c)
fire 0 회 hook (surface 축소 후보) 식별을 얻는 분석 스크립트.

PR4 (outcome telemetry, issue 별도) 이전에는 fire-log 가 mixed 포맷
(3-field legacy + 4-field + 5-field) — 이 스크립트는 세 가지 모두 parse.

포맷 spec
=========

PR4 표준 (5-field+)::

    <ts>|<outcome>|<hook>|<category>|<path>[|<extra>]

    outcome ∈ {aware, blocked, bypassed, false_positive,
               false_negative, nudged, pipeline_start, pipeline_end}
    hook    ∈ {bash-guard, loadbearing, memory-lines, adr-template,
               plan-slug-race, delegation-gate, stop-ship}

Legacy 3-field (loadbearing 현재 포맷)::

    <ts>|aware|<path>            (hook 추정: "loadbearing")

Legacy 4-field (memory-lines / delegation-gate 현재 포맷)::

    <ts>|<action>|<reason>|<path>
    # action ∈ {aware, ok}, reason 이 hook 식별자 (e.g. "memory-lines")

이미 bash-guard 는 5-field 포맷을 사용 중 (scripts/claude-hooks/
pretooluse-bash-guard.sh:131-133). PR4 가 나머지 hook 으로 확산.

Usage
=====

::

    python scripts/analyze_hook_outcomes.py
    python scripts/analyze_hook_outcomes.py --window 90d
    python scripts/analyze_hook_outcomes.py --window 30d --hook memory-lines
    python scripts/analyze_hook_outcomes.py --format json

Exit codes
==========

    0  분석 성공 + 출력 완료
    1  fire-log 파일 부재 또는 파싱 실패
    2  CLI usage 에러
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# 5-field+ 표준: <ts>|<outcome>|<hook>|<category>|<path>[|extra]
# 4-field legacy: <ts>|<action>|<reason>|<path>
# 3-field legacy: <ts>|<category>|<path>

KNOWN_OUTCOMES = {
    "aware", "blocked", "bypassed",
    "false_positive", "false_negative",
    "nudged", "pipeline_start", "pipeline_end",
    "ok",  # legacy memory-lines silent pass
}

# Legacy 3-field category → hook name mapping. PR4 후 이 매핑은
# fire-log 자체가 hook 명을 명시하므로 deprecated.
LEGACY_CATEGORY_TO_HOOK = {
    "load-bearing": "loadbearing",
    "memory-lines": "memory-lines",
    "loadbearing": "loadbearing",
}


def parse_log_line(line: str) -> dict | None:
    """Parse a single ``.hook-fires.log`` line into a normalized dict.

    Returns ``None`` for malformed / empty / comment lines.

    Output keys (always present)::

        ts:       ISO 8601 UTC string (raw, parsing deferred to caller)
        outcome:  one of KNOWN_OUTCOMES (or "unknown" if unrecognized)
        hook:     short hook name (e.g. "bash-guard", "loadbearing")
        category: hook-internal sub-category (may be empty)
        path:     affected file path or branch (may be empty)
        extra:    free-form trailing fields joined by "|" (may be empty)
        format:   "v1-3field" / "v1-4field" / "v2-5field" (parse provenance)
    """
    line = line.rstrip("\n")
    if not line or line.startswith("#"):
        return None
    parts = line.split("|")
    if len(parts) < 3:
        return None
    ts = parts[0]
    # Quick sanity: ts should look like ISO 8601 ("YYYY-MM-DDTHH:MM:SSZ").
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$", ts):
        return None

    if len(parts) >= 5:
        # v2-5field: ts | outcome | hook | category | path [| extra...]
        outcome = parts[1]
        hook = parts[2]
        category = parts[3]
        path = parts[4]
        extra = "|".join(parts[5:]) if len(parts) > 5 else ""
        if outcome not in KNOWN_OUTCOMES:
            outcome = "unknown"
        return {
            "ts": ts, "outcome": outcome, "hook": hook,
            "category": category, "path": path, "extra": extra,
            "format": "v2-5field",
        }

    if len(parts) == 4:
        # v1-4field: ts | action | reason | path
        # action ∈ {aware, ok, blocked, ...}, reason ≈ hook id
        action = parts[1]
        reason = parts[2]
        path = parts[3]
        hook = LEGACY_CATEGORY_TO_HOOK.get(reason, reason)
        outcome = action if action in KNOWN_OUTCOMES else "unknown"
        return {
            "ts": ts, "outcome": outcome, "hook": hook,
            "category": reason, "path": path, "extra": "",
            "format": "v1-4field",
        }

    # len(parts) == 3 → v1-3field: ts | category | path
    category = parts[1]
    path = parts[2]
    hook = LEGACY_CATEGORY_TO_HOOK.get(category, category)
    # 3-field never recorded anything but awareness in observed data
    outcome = "aware"
    return {
        "ts": ts, "outcome": outcome, "hook": hook,
        "category": category, "path": path, "extra": "",
        "format": "v1-3field",
    }


def parse_ts(ts: str) -> datetime | None:
    try:
        # Accept both "...Z" and "...+00:00".
        s = ts.rstrip("Z")
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Loading + filtering
# ---------------------------------------------------------------------------


def load_log(path: Path) -> list[dict]:
    """Read fire-log file, returning parsed events (malformed lines dropped)."""
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            ev = parse_log_line(raw)
            if ev is not None:
                out.append(ev)
    return out


def filter_window(events: list[dict], window: str) -> list[dict]:
    """Filter events to a sliding window from now.

    Window format: ``Nd`` (days), ``Nh`` (hours), or ``all``.
    """
    if window == "all":
        return events
    m = re.match(r"^(\d+)([dh])$", window)
    if not m:
        raise ValueError(f"invalid --window: {window!r} (expected Nd / Nh / all)")
    n = int(m.group(1))
    unit = m.group(2)
    delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
    cutoff = datetime.now(timezone.utc) - delta
    out: list[dict] = []
    for ev in events:
        ts = parse_ts(ev["ts"])
        if ts is not None and ts >= cutoff:
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


# Canonical hook inventory — matches scripts/claude-hooks/README.md table.
ALL_HOOKS = [
    "bash-guard", "loadbearing", "memory-lines",
    "adr-template", "plan-slug-race",
    "delegation-gate", "stop-ship",
]


def outcome_breakdown(events: list[dict]) -> dict[str, dict[str, int]]:
    """Return ``{hook: {outcome: count}}``."""
    out: dict[str, Counter] = defaultdict(Counter)
    for ev in events:
        out[ev["hook"]][ev["outcome"]] += 1
    return {k: dict(v) for k, v in out.items()}


def threshold_recommendation(events: list[dict]) -> dict:
    """Recommend memory-lines AWARE/BLOCK thresholds from observed fire dist.

    Current thresholds (scripts/_governance.py THRESHOLDS):
        MEMORY_LINE_AWARE = 20
        MEMORY_LINE_BLOCK = 30

    Logic: count AWARE vs BLOCK fires for memory-lines. If BLOCK fires
    are rare (<5% of total) and AWARE fires regular, current thresholds
    are catching outliers — maintain. If BLOCK fires are common (>20%),
    BLOCK threshold may be too low. If AWARE fires rare (<5% of edits),
    AWARE threshold may be too high.

    Returns a structured dict — no auto-adjust.
    """
    ml_events = [e for e in events if e["hook"] == "memory-lines"]
    total = len(ml_events)
    aware = sum(1 for e in ml_events if e["outcome"] in ("aware", "ok"))
    blocked = sum(1 for e in ml_events if e["outcome"] == "blocked")
    if total == 0:
        return {
            "current": {"aware": 20, "block": 30},
            "observed_total": 0,
            "verdict": "insufficient_data",
            "rationale": "memory-lines hook 이 윈도우 안에 0회 fire — 데이터 부족.",
        }
    block_ratio = blocked / total
    if block_ratio < 0.05:
        verdict = "maintain"
        rationale = (
            f"BLOCK fire ratio = {block_ratio:.1%} (<5%) — 임계값이 outlier 만 "
            "catch. 현재 30 유지 합리적."
        )
    elif block_ratio > 0.20:
        verdict = "raise_block"
        rationale = (
            f"BLOCK fire ratio = {block_ratio:.1%} (>20%) — 임계값이 너무 낮아 "
            "정상 작업이 BLOCK 됨. 30 → 40+ 검토."
        )
    else:
        verdict = "maintain"
        rationale = f"BLOCK fire ratio = {block_ratio:.1%} — 정상 범위."
    return {
        "current": {"aware": 20, "block": 30},
        "observed_total": total,
        "observed_aware": aware,
        "observed_blocked": blocked,
        "block_ratio": block_ratio,
        "verdict": verdict,
        "rationale": rationale,
    }


def surface_reduction_candidates(events: list[dict], window: str) -> list[str]:
    """Return hooks with 0 fires in the window — candidates for removal."""
    fired = {ev["hook"] for ev in events}
    return sorted(h for h in ALL_HOOKS if h not in fired)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_text(events: list[dict], window: str) -> str:
    breakdown = outcome_breakdown(events)
    threshold = threshold_recommendation(events)
    silent = surface_reduction_candidates(events, window)
    fmt_counts = Counter(ev["format"] for ev in events)

    lines: list[str] = []
    lines.append(f"=== Hook outcome breakdown (window={window}) ===")
    lines.append(f"Total events: {len(events)}")
    lines.append(
        f"Format mix: v2-5field={fmt_counts.get('v2-5field', 0)}  "
        f"v1-4field={fmt_counts.get('v1-4field', 0)}  "
        f"v1-3field={fmt_counts.get('v1-3field', 0)}"
    )
    lines.append("")

    for hook in ALL_HOOKS:
        counts = breakdown.get(hook, {})
        if not counts:
            lines.append(f"{hook}: (no fires)")
            continue
        lines.append(f"{hook}:")
        for outcome in sorted(counts):
            lines.append(f"  {outcome:18s} {counts[outcome]:>6d}")

    # Any unexpected hook names (e.g. typo'd legacy reason)
    unknown_hooks = sorted(set(breakdown) - set(ALL_HOOKS))
    if unknown_hooks:
        lines.append("")
        lines.append("Unrecognized hook names (legacy / typo):")
        for h in unknown_hooks:
            counts = breakdown[h]
            lines.append(f"  {h:25s} {sum(counts.values())} events")

    lines.append("")
    lines.append("=== Threshold recommendations ===")
    lines.append("memory-lines:")
    lines.append(f"  current: AWARE={threshold['current']['aware']} / "
                 f"BLOCK={threshold['current']['block']}")
    if threshold.get("verdict") == "insufficient_data":
        lines.append(f"  verdict: insufficient data ({threshold['rationale']})")
    else:
        lines.append(f"  observed: total={threshold['observed_total']} "
                     f"aware={threshold['observed_aware']} "
                     f"blocked={threshold['observed_blocked']} "
                     f"({threshold['block_ratio']:.1%})")
        lines.append(f"  verdict: {threshold['verdict']}")
        lines.append(f"  rationale: {threshold['rationale']}")

    lines.append("")
    lines.append("=== Surface reduction candidates ===")
    if silent:
        for h in silent:
            lines.append(f"  {h} — 0 fires in window")
        lines.append("")
        lines.append("(removal 결정 전에 90일 이상 데이터 + 회귀 테스트 검토)")
    else:
        lines.append("(none — all hooks fired ≥1 time in window)")

    return "\n".join(lines) + "\n"


def render_json(events: list[dict], window: str) -> str:
    return json.dumps({
        "window": window,
        "total_events": len(events),
        "format_mix": dict(Counter(ev["format"] for ev in events)),
        "outcome_breakdown": outcome_breakdown(events),
        "threshold_memory_lines": threshold_recommendation(events),
        "surface_reduction_candidates": surface_reduction_candidates(events, window),
    }, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log",
        default=".claude/.hook-fires.log",
        help="fire-log path (default: .claude/.hook-fires.log)",
    )
    parser.add_argument(
        "--window",
        default="90d",
        help="time window: Nd (days) / Nh (hours) / all (default: 90d)",
    )
    parser.add_argument(
        "--hook",
        default="all",
        help="filter to single hook name (default: all)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    events = load_log(log_path)
    if not events and not log_path.exists():
        sys.stderr.write(f"fire-log not found: {log_path}\n")
        return 1

    try:
        events = filter_window(events, args.window)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    if args.hook != "all":
        events = [e for e in events if e["hook"] == args.hook]

    if args.format == "json":
        sys.stdout.write(render_json(events, args.window))
    else:
        sys.stdout.write(render_text(events, args.window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
