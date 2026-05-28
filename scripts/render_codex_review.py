"""Render Codex adversarial review JSON output into markdown/check artifacts.

The Codex companion (`codex-companion.mjs adversarial-review --json`) emits a payload
with shape:

    {
      "review": "Adversarial Review",
      "target": {"mode", "label", "baseRef"},
      "result": {                              # JSON-schema validated, may be null
        "verdict": "approve" | "needs-attention",
        "summary": "...",
        "findings": [
          {"severity", "title", "body", "file",
           "line_start", "line_end", "confidence", "recommendation"},
          ...
        ],
        "next_steps": [...]
      },
      "rawOutput": "...",
      "parseError": null | "..."
    }

This script turns that payload into:
  --output            : full rendered markdown
  --check-summary     : 50-line summary for automation/check consumers
  --check-conclusion  : single word "success" | "neutral"

Branching rules:
  rc != 0                  → "Codex failed to run" + stderr tail, conclusion=neutral
  parseError non-null      → "Codex returned malformed output" + raw tail, conclusion=neutral
  result.verdict=approve   → terse ack + findings (if any), conclusion=success
  result.verdict=needs-attention → severity-sorted finding table, conclusion=neutral

Hallucination guard: if --changed-files is provided, any finding whose `file` is not
in the changed set gets a warning sticker (the model may have hallucinated a path).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_BADGE = {
    "critical": "🔴 critical",
    "high": "🟠 high",
    "medium": "🟡 medium",
    "low": "🔵 low",
}
COMMENT_MARKER = "<!-- codex-adversarial-review-bot -->"


def load_codex_output(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_changed_files(path: pathlib.Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _file_link(repo: str | None, sha: str | None, file: str, start: int, end: int) -> str:
    if not repo or not sha:
        return f"`{file}:{start}-{end}`"
    return f"[`{file}:{start}-{end}`](https://github.com/{repo}/blob/{sha}/{file}#L{start}-L{end})"


def _sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda f: (SEVERITY_RANK.get(f.get("severity", "low"), 99), f.get("file", "")),
    )


def _hallucination_marker(file: str, changed: set[str]) -> str:
    if not changed:
        return ""
    if file in changed:
        return ""
    return " ⚠️ *file not in PR diff — possible hallucination*"


def render_failure(rc: int, stderr_tail: str) -> str:
    return (
        "## Codex adversarial review — **execution failed**\n\n"
        f"`codex-companion.mjs` returned non-zero exit (rc={rc}).\n\n"
        "Run `/codex:adversarial-review` locally to debug or check whether the ChatGPT "
        "session is logged in (`codex login --status`) / Codex usage limit was hit.\n\n"
        f"```\n{stderr_tail}\n```\n"
    )


def render_parse_error(payload: dict[str, Any]) -> str:
    raw = (payload.get("rawOutput") or "")[:2000]
    err = payload.get("parseError") or "(no parseError message)"
    return (
        "## Codex adversarial review — **malformed output**\n\n"
        f"Codex finished but the structured-output validator rejected the response:\n\n"
        f"> {err}\n\n"
        "Raw model output (truncated 2k chars):\n\n"
        f"```\n{raw}\n```\n"
    )


def render_finding(
    finding: dict[str, Any],
    repo: str | None,
    sha: str | None,
    changed: set[str],
) -> str:
    severity = finding.get("severity", "low")
    badge = SEVERITY_BADGE.get(severity, f"⚪ {severity}")
    title = finding.get("title", "(untitled)")
    body = finding.get("body", "")
    rec = finding.get("recommendation", "")
    file = finding.get("file", "")
    start = int(finding.get("line_start", 1))
    end = int(finding.get("line_end", start))
    confidence = finding.get("confidence")
    link = _file_link(repo, sha, file, start, end)
    halluc = _hallucination_marker(file, changed)
    conf_str = f" · confidence {confidence:.2f}" if isinstance(confidence, (int, float)) else ""
    parts = [
        f"### {badge} — {title}",
        f"{link}{halluc}{conf_str}",
        "",
        body.strip(),
    ]
    if rec:
        parts.append("")
        parts.append(f"**Recommendation:** {rec.strip()}")
    return "\n".join(parts)


def render_markdown(
    payload: dict[str, Any] | None,
    rc: int,
    repo: str | None,
    sha: str | None,
    changed: set[str],
    stderr_tail: str,
) -> str:
    if rc != 0:
        return render_failure(rc, stderr_tail)
    if payload is None:
        return render_failure(
            rc=-1,
            stderr_tail="Codex output file missing or unreadable.",
        )
    if payload.get("parseError"):
        return render_parse_error(payload)

    result = payload.get("result") or {}
    verdict = result.get("verdict", "(unknown)")
    summary = (result.get("summary") or "").strip()
    findings = _sort_findings(list(result.get("findings") or []))
    next_steps = result.get("next_steps") or []

    head_emoji = "✅" if verdict == "approve" else "⚠️"
    lines = [
        f"## {head_emoji} Codex adversarial review — `{verdict}`",
        "",
        "_Informational only — not a merge gate. Reviewer judgment overrides._",
        "",
        f"**Summary:** {summary}" if summary else "",
        "",
    ]
    if findings:
        lines.append(f"### Findings ({len(findings)})")
        lines.append("")
        for f in findings:
            lines.append(render_finding(f, repo, sha, changed))
            lines.append("")
    elif verdict == "approve":
        lines.append("_No findings raised._")
        lines.append("")

    if next_steps:
        lines.append("### Next steps")
        for step in next_steps:
            lines.append(f"- {step}")
        lines.append("")

    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def render_check_summary(
    payload: dict[str, Any] | None,
    rc: int,
    changed: set[str],
) -> str:
    if rc != 0:
        return f"Codex execution failed (rc={rc}). See PR comment for details."
    if payload is None:
        return "Codex output missing."
    if payload.get("parseError"):
        return f"Codex returned malformed output: {payload['parseError']}"

    result = payload.get("result") or {}
    verdict = result.get("verdict", "unknown")
    findings = list(result.get("findings") or [])
    by_severity: dict[str, int] = {}
    halluc = 0
    for f in findings:
        sev = f.get("severity", "low")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if changed and f.get("file", "") not in changed:
            halluc += 1

    parts = [f"Verdict: **{verdict}**"]
    if findings:
        order = ("critical", "high", "medium", "low")
        chips = [f"{by_severity[s]} {s}" for s in order if by_severity.get(s)]
        parts.append("Findings: " + ", ".join(chips))
    else:
        parts.append("Findings: none")
    if halluc:
        parts.append(f"⚠️ {halluc} finding(s) reference files not in PR diff (possible hallucination)")
    return "\n".join(parts)


def pick_conclusion(payload: dict[str, Any] | None, rc: int) -> str:
    if rc != 0 or payload is None:
        return "neutral"
    if payload.get("parseError"):
        return "neutral"
    verdict = (payload.get("result") or {}).get("verdict")
    if verdict == "approve":
        return "success"
    return "neutral"


def build_comment_body(rendered: str) -> str:
    return f"{COMMENT_MARKER}\n\n{rendered}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=pathlib.Path)
    parser.add_argument("--rc", required=True, type=int)
    parser.add_argument("--repo", default=None, help="owner/name for blob links")
    parser.add_argument("--sha", default=None, help="commit SHA for blob links")
    parser.add_argument(
        "--changed-files",
        type=pathlib.Path,
        default=None,
        help="Optional newline-delimited file listing PR-changed paths (hallucination guard).",
    )
    parser.add_argument(
        "--stderr",
        type=pathlib.Path,
        default=None,
        help="Optional path to companion stderr log (tailed into failure body).",
    )
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--check-summary", required=True, type=pathlib.Path)
    parser.add_argument("--check-conclusion", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    payload = load_codex_output(args.input)
    changed = load_changed_files(args.changed_files)
    stderr_tail = ""
    if args.stderr and args.stderr.exists():
        stderr_tail = "\n".join(args.stderr.read_text(encoding="utf-8").splitlines()[-30:])

    rendered = render_markdown(
        payload=payload,
        rc=args.rc,
        repo=args.repo,
        sha=args.sha,
        changed=changed,
        stderr_tail=stderr_tail,
    )
    args.output.write_text(build_comment_body(rendered), encoding="utf-8")
    args.check_summary.write_text(render_check_summary(payload, args.rc, changed), encoding="utf-8")
    args.check_conclusion.write_text(pick_conclusion(payload, args.rc), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
