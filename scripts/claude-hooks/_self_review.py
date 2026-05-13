#!/usr/bin/env python3
"""Self-review quarterly: raw statistics collector for collaboration ROI.

Reads transcripts (.jsonl), memory frontmatter, and git log within a
quarter window, emits a stats.json containing ONLY metadata — never
user/assistant body text, tool arguments, code diffs, or memory body.

The interpretation (4-axis + 5-axis verdicts) is left to the LLM via
`.claude/skills/self-review-quarterly/SKILL.md`. This driver only
gathers the inputs.

Exit codes:
    0  stats / report emitted successfully
    1  invalid input (quarter format, missing arg)
    2  internal / I/O error
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUARTER_RE = re.compile(r"^Q([1-4])-(\d{4})$")
ADR_FILENAME_RE = re.compile(r"^(\d{4})-.+\.md$")
PR_MERGE_RE = re.compile(r"\(#(\d+)\)\s*$")

DEFAULT_TRANSCRIPTS_GLOB = (
    "~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/*.jsonl"
)
DEFAULT_MEMORY_DIR = (
    "~/.claude/projects/-Users-hskim-Desktop-projects-BidMate-DocAgent/memory"
)


def load_load_bearing_paths(repo: str) -> list[str]:
    """Import LOAD_BEARING_PATHS from scripts/_governance.py if available.

    Fails soft to an empty list — driver still produces stats, the
    load_bearing_touches count just stays 0 in non-BidMate contexts.
    """
    scripts_dir = os.path.join(repo, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from _governance import LOAD_BEARING_PATHS  # type: ignore
        return list(LOAD_BEARING_PATHS)
    except (ImportError, AttributeError):
        return []


def parse_quarter(q: str) -> tuple[str, str]:
    """Q2-2026 -> (2026-04-01, 2026-06-30)."""
    m = QUARTER_RE.match(q)
    if not m:
        raise ValueError(f"invalid quarter '{q}' (expected Qx-YYYY, e.g. Q2-2026)")
    n, year = int(m.group(1)), int(m.group(2))
    start_month = (n - 1) * 3 + 1
    end_month = n * 3
    end_day = {3: 31, 6: 30, 9: 30, 12: 31}[end_month]
    return (
        f"{year:04d}-{start_month:02d}-01",
        f"{year:04d}-{end_month:02d}-{end_day:02d}",
    )


def parse_frontmatter(text: str) -> dict[str, str]:
    """Single-line key:value parse. Multi-line values ignored.

    Memory files use simple single-line values for type/originSessionId,
    so a full YAML parser is unnecessary (and avoids the dependency).
    """
    if not text.startswith("---"):
        return {}
    try:
        end = text.index("\n---", 4)
    except ValueError:
        return {}
    block = text[4:end]
    fm: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key:
            fm[key] = val
    return fm


def collect_sessions(transcripts_glob: str, start: str, end: str) -> dict[str, Any]:
    """Walk .jsonl files, count tool uses and Agent delegations.

    Only `type`, `name`, `subagent_type`, `timestamp` are read.
    Message content, tool arguments, and Agent prompts are never touched.
    """
    expanded = os.path.expanduser(transcripts_glob)
    files = sorted(Path(f) for f in glob.glob(expanded))
    tool_counter: Counter[str] = Counter()
    agent_counter: Counter[str] = Counter()
    session_ids: set[str] = set()

    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(
        tzinfo=timezone.utc, hour=23, minute=59, second=59
    )

    for f in files:
        try:
            with f.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp")
                    if not isinstance(ts, str):
                        continue
                    try:
                        rec_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if rec_dt < start_dt or rec_dt > end_dt:
                        continue
                    sid = rec.get("sessionId")
                    if isinstance(sid, str):
                        session_ids.add(sid)
                    msg = rec.get("message")
                    if not isinstance(msg, dict):
                        continue
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue
                        name = block.get("name")
                        if not isinstance(name, str) or not name:
                            continue
                        tool_counter[name] += 1
                        if name == "Agent":
                            inp = block.get("input")
                            if isinstance(inp, dict):
                                sub = inp.get("subagent_type")
                                if isinstance(sub, str) and sub:
                                    agent_counter[sub] += 1
        except OSError:
            continue

    return {
        "count": len(session_ids),
        "tool_call_distribution": dict(tool_counter.most_common()),
        "agent_delegations": dict(agent_counter.most_common()),
    }


def collect_memory(memory_dir: str) -> dict[str, Any]:
    """Scan memory/*.md frontmatter. Body never read.

    Returns counts by type plus per-file metadata (name, type,
    originSessionId, mtime). The stale-vs-fresh judgment is left to the
    LLM since session-ID-to-date mapping requires session metadata not
    available here.
    """
    expanded = os.path.expanduser(memory_dir)
    p = Path(expanded)
    if not p.is_dir():
        return {"files_total": 0, "by_type": {}, "files": []}
    by_type: Counter[str] = Counter()
    files_meta: list[dict[str, str]] = []
    for f in sorted(p.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            text = f.read_text()
        except OSError:
            continue
        fm = parse_frontmatter(text)
        mtype = fm.get("type", "")
        if mtype:
            by_type[mtype] += 1
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).date().isoformat()
        files_meta.append({
            "filename": f.name,
            "name": fm.get("name", ""),
            "type": mtype,
            "originSessionId": fm.get("originSessionId", ""),
            "mtime": mtime,
        })
    return {
        "files_total": len(files_meta),
        "by_type": dict(by_type),
        "files": files_meta,
    }


def _run_git(repo: str, args: list[str]) -> str:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=repo, capture_output=True, text=True, check=False
        )
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def collect_git(repo: str, start: str, end: str) -> dict[str, Any]:
    """Count commits, ADR changes, PR merges, load-bearing touches.

    Commit subjects are parsed for PR numbers only — the full subject
    is not stored in stats. ADR ids come from filenames in docs/adr/.
    """
    since = f"--since={start}"
    until = f"--until={end}"

    commits_out = _run_git(repo, ["log", since, until, "--pretty=format:%H"])
    commit_count = len([l for l in commits_out.splitlines() if l.strip()])

    pr_subjects = _run_git(
        repo, ["log", since, until, "--pretty=format:%H|%s|%ai"]
    )
    prs: list[dict[str, Any]] = []
    seen_prs: set[int] = set()
    for line in pr_subjects.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, subj, date = parts
        m = PR_MERGE_RE.search(subj)
        if not m:
            continue
        num = int(m.group(1))
        if num in seen_prs:
            continue
        seen_prs.add(num)
        prs.append({"number": num, "sha": sha[:12], "date": date.split(" ")[0]})

    adr_out = _run_git(repo, [
        "log", since, until, "--diff-filter=AM", "--name-only",
        "--pretty=format:", "--", "docs/adr/",
    ])
    adr_changes: list[dict[str, str]] = []
    seen_adr: set[str] = set()
    for line in adr_out.splitlines():
        line = line.strip()
        if not line.startswith("docs/adr/"):
            continue
        fname = Path(line).name
        m = ADR_FILENAME_RE.match(fname)
        if not m:
            continue
        adr_id = m.group(1)
        if adr_id in seen_adr:
            continue
        seen_adr.add(adr_id)
        adr_changes.append({"id": adr_id, "filename": fname})

    lb_paths = load_load_bearing_paths(repo)
    if lb_paths:
        lb_out = _run_git(repo, [
            "log", since, until, "--name-only", "--pretty=format:", "--",
        ] + lb_paths)
        load_bearing_touches = sum(1 for l in lb_out.splitlines() if l.strip())
    else:
        load_bearing_touches = 0

    return {
        "commits": commit_count,
        "load_bearing_touches": load_bearing_touches,
        "load_bearing_paths_source": (
            "scripts/_governance.py" if lb_paths else "unavailable"
        ),
        "adr_changes": adr_changes,
        "prs_merged": prs,
    }


def _compute_adr_lags(repo: str, start: str, end: str) -> list[dict[str, Any]]:
    """Return ADR proposed→accepted lag for ADRs accepted within the quarter.

    proposed_date: timestamp of the commit that first added the ADR file.
    accepted_date: timestamp of the commit that introduced ``**Status**: accepted``.
    Only emits ADRs whose accepted_date falls in [start, end].
    lag_days = (accepted - proposed).days  (clamped to 0 if negative).
    """
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(
        tzinfo=timezone.utc, hour=23, minute=59, second=59
    )
    adr_dir = Path(repo) / "docs" / "adr"
    if not adr_dir.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for adr_path in sorted(adr_dir.glob("*.md")):
        m = ADR_FILENAME_RE.match(adr_path.name)
        if not m:
            continue
        adr_id = m.group(1)
        rel_path = str(adr_path.relative_to(repo))
        try:
            proposed_lines = subprocess.run(
                ["git", "log", "--diff-filter=A", "--pretty=format:%aI", "--", rel_path],
                cwd=repo, text=True, capture_output=True, timeout=15,
            ).stdout.strip().splitlines()
            if not proposed_lines:
                continue
            proposed_dt = datetime.fromisoformat(proposed_lines[-1])
            if proposed_dt.tzinfo is None:
                proposed_dt = proposed_dt.replace(tzinfo=timezone.utc)

            accepted_lines = subprocess.run(
                ["git", "log", "-S", "**Status**: accepted",
                 "--pretty=format:%aI", "--", rel_path],
                cwd=repo, text=True, capture_output=True, timeout=15,
            ).stdout.strip().splitlines()
            if not accepted_lines:
                continue
            accepted_dt = datetime.fromisoformat(accepted_lines[0])
            if accepted_dt.tzinfo is None:
                accepted_dt = accepted_dt.replace(tzinfo=timezone.utc)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            continue

        if accepted_dt < start_dt or accepted_dt > end_dt:
            continue
        lag_days = max((accepted_dt - proposed_dt).days, 0)
        results.append({
            "adr_id": adr_id,
            "proposed_date": proposed_dt.date().isoformat(),
            "accepted_date": accepted_dt.date().isoformat(),
            "lag_days": lag_days,
        })
    return results


def collect_governance_hooks(repo: str, start: str, end: str) -> dict[str, Any]:
    """Parse `.claude/.hook-fires.log` for PreToolUse load-bearing fires.

    Log line formats (both accepted):
    - legacy 2-field: ``<ISO8601 UTC>|<file_path>``
    - current 4-field: ``<ISO8601 UTC>|<action>|<context>|<detail>``
      loadbearing fires use ``aware|load-bearing|<file_path>``
      bash-guard blocks use ``blocked|gh-merge-delete-branch|<branch>``
    """
    log_path = Path(repo) / ".claude" / ".hook-fires.log"
    if not log_path.is_file():
        return {
            "pretooluse_loadbearing_fires": 0,
            "fires_by_path": {},
            "fires_by_action": {},
            "rule_to_automation_lag_days": _compute_adr_lags(repo, start, end),
            "note": "Hook fire log absent at .claude/.hook-fires.log; emit 0.",
        }
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(
        tzinfo=timezone.utc, hour=23, minute=59, second=59
    )
    fires = 0
    by_path: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    try:
        for line in log_path.read_text().splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|", 3)
            ts = parts[0]
            try:
                fire_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if fire_dt < start_dt or fire_dt > end_dt:
                continue
            if len(parts) >= 4:
                action, path = parts[1], parts[3]
            else:
                action, path = "aware", parts[1] if len(parts) > 1 else ""
            fires += 1
            if path:
                by_path[path] += 1
            if action:
                by_action[action] += 1
    except OSError:
        pass
    lags = _compute_adr_lags(repo, start, end)
    note = f"Lag: {len(lags)} ADR(s) with accepted date in window."
    return {
        "pretooluse_loadbearing_fires": fires,
        "fires_by_path": dict(by_path.most_common(10)),
        "fires_by_action": dict(by_action),
        "rule_to_automation_lag_days": lags,
        "note": note,
    }


def assemble_stats(
    quarter: str, transcripts_glob: str, memory_dir: str, repo: str
) -> dict[str, Any]:
    start, end = parse_quarter(quarter)
    return {
        "quarter": quarter,
        "date_range": [start, end],
        "sessions": collect_sessions(transcripts_glob, start, end),
        "memory": collect_memory(memory_dir),
        "git": collect_git(repo, start, end),
        "governance_hooks": collect_governance_hooks(repo, start, end),
    }


def emit_report(stats: dict[str, Any]) -> str:
    """Render Markdown skeleton from stats. LLM (SKILL.md) fills verdicts."""
    quarter = stats["quarter"]
    lines: list[str] = [
        f"# Self-Review {quarter}",
        "",
        f"- Date range: {stats['date_range'][0]} – {stats['date_range'][1]}",
        f"- Sessions: {stats['sessions'].get('count', 0)}",
        f"- Commits: {stats['git'].get('commits', 0)}",
        f"- Load-bearing touches: {stats['git'].get('load_bearing_touches', 0)}",
        f"- ADR changes: {len(stats['git'].get('adr_changes', []))}",
        f"- PRs merged: {len(stats['git'].get('prs_merged', []))}",
        "",
        "## Raw stats (metadata-only — no body excerpts)",
        "",
        "```json",
        json.dumps(stats, indent=2, ensure_ascii=False),
        "```",
        "",
        "## 4-axis + 5-axis verdicts",
        "",
        f"Run `/self-review-quarterly {quarter}` in Claude Code to fill the "
        "rubric tables. The skill loads `feedback_portfolio_evaluation.md` "
        "(4-axis portfolio) and `feedback_collaboration_axes.md` (5-axis "
        "collaboration) and writes ✓/△/✗ verdicts with citation evidence.",
        "",
        "_This Markdown was generated by `scripts/claude-hooks/_self_review.py`. "
        "Body text from transcripts is never included — only counts, names, "
        "and frontmatter-level identifiers._",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quarter", required=True, help="Qx-YYYY (e.g. Q2-2026)")
    p.add_argument("--transcripts-glob", default=DEFAULT_TRANSCRIPTS_GLOB)
    p.add_argument("--memory-dir", default=DEFAULT_MEMORY_DIR)
    p.add_argument("--repo", default=os.getcwd())
    p.add_argument("--emit-stats", action="store_true",
                   help="emit stats.json to stdout")
    p.add_argument("--emit-report", action="store_true",
                   help="emit Markdown report")
    p.add_argument("--output", default="-",
                   help="report path (default stdout; ignored without --emit-report)")
    args = p.parse_args()

    if not args.emit_stats and not args.emit_report:
        sys.stderr.write("self-review: pass --emit-stats or --emit-report\n")
        return 1

    try:
        stats = assemble_stats(
            args.quarter, args.transcripts_glob, args.memory_dir, args.repo
        )
    except ValueError as e:
        sys.stderr.write(f"self-review: {e}\n")
        return 1
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"self-review: {e}\n")
        return 2

    if args.emit_stats:
        sys.stdout.write(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")

    if args.emit_report:
        report = emit_report(stats)
        if args.output == "-":
            sys.stdout.write(report)
        else:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report)
            sys.stdout.write(f"self-review: report written to {out_path}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
