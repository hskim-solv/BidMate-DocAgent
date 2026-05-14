"""Real100 case-level failure breakdown. Reads eval_summary.json and writes case_breakdown.md.

Usage:
    python scripts/analyze_real100_failures.py [EVAL_SUMMARY_JSON] [OUTPUT_MD]

Defaults:
    EVAL_SUMMARY_JSON = reports/real100/eval_summary.json
    OUTPUT_MD         = reports/real100/case_breakdown.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Failure bucket classification
# ---------------------------------------------------------------------------

def _classify(case: dict) -> str:
    qt = case.get("query_type", "")
    acc = case.get("accuracy")       # float | None
    gnd = case.get("groundedness") or 0.0
    status = case.get("answer_status", "")
    abstained = case.get("abstained", False)

    if qt == "abstention":
        if abstained:
            return "correct_abstention"
        return "wrong_answer"          # should have abstained but produced an answer

    if abstained:
        return "wrong_abstention"      # should have answered but abstained

    if acc == 1.0 and gnd >= 0.9:
        return "pass"

    if status == "supported" and acc == 0.0:
        return "wrong_answer"

    if status in ("insufficient", "partial") and acc == 0.0:
        return "wrong_abstention"

    if acc == 0.0 or gnd < 0.5:
        return "low_quality"

    return "pass"


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float | None:
    filtered = [v for v in values if v is not None]
    return sum(filtered) / len(filtered) if filtered else None


def _fmt(v: float | None, decimals: int = 3) -> str:
    return f"{v:.{decimals}f}" if v is not None else "—"


# ---------------------------------------------------------------------------
# Markdown builders
# ---------------------------------------------------------------------------

def _section(title: str) -> str:
    return f"\n## {title}\n"


def _case_table(cases: list[dict]) -> str:
    rows = [
        "| id | query_type | acc | gnd | status | abstained | chunk_r@5 | chunk_r@10 | bucket | query |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cases:
        row = " | ".join([
            c.get("id", "")[:40],
            c.get("query_type", ""),
            _fmt(c.get("accuracy"), 1),
            _fmt(c.get("groundedness"), 2),
            c.get("answer_status", ""),
            str(c.get("abstained", False)),
            _fmt(c.get("chunk_recall_at_5"), 2),
            _fmt(c.get("chunk_recall_at_10"), 2),
            _classify(c),
            (c.get("query") or "")[:60].replace("|", "｜"),
        ])
        rows.append(f"| {row} |")
    return "\n".join(rows)


def _dim_table(cases: list[dict], dim: str) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        key = str(c.get(dim) or "unknown")
        groups[key].append(c)

    rows = [
        f"| {dim} | count | acc_mean | gnd_mean | pass | wrong_abstention | wrong_answer | correct_abstention | low_quality |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key in sorted(groups):
        g = groups[key]
        buckets = [_classify(c) for c in g]
        row = " | ".join([
            key,
            str(len(g)),
            _fmt(_mean([c.get("accuracy") for c in g])),
            _fmt(_mean([c.get("groundedness") for c in g])),
            str(buckets.count("pass")),
            str(buckets.count("wrong_abstention")),
            str(buckets.count("wrong_answer")),
            str(buckets.count("correct_abstention")),
            str(buckets.count("low_quality")),
        ])
        rows.append(f"| {row} |")
    return "\n".join(rows)


def _failure_detail(cases: list[dict]) -> str:
    failures = [c for c in cases if _classify(c) != "pass" and _classify(c) != "correct_abstention"]
    if not failures:
        return "_No failures._"
    lines = []
    for c in failures:
        bucket = _classify(c)
        lines.append(
            f"**{c.get('id')}** `{bucket}` {c.get('query_type')} "
            f"acc={_fmt(c.get('accuracy'),1)} gnd={_fmt(c.get('groundedness'),2)} "
            f"status={c.get('answer_status')} abstained={c.get('abstained')}"
        )
        q = (c.get("query") or "")[:120]
        lines.append(f"  > {q}")
        r5 = c.get("chunk_recall_at_5")
        r10 = c.get("chunk_recall_at_10")
        lines.append(f"  chunk_recall@5={_fmt(r5,2)} @10={_fmt(r10,2)}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(eval_summary_path: Path, output_path: Path) -> None:
    with eval_summary_path.open() as f:
        data = json.load(f)

    cases: list[dict] = data.get("case_results", [])
    if not cases:
        print("No case_results found.", file=sys.stderr)
        sys.exit(1)

    accs = [c["accuracy"] for c in cases if c.get("accuracy") is not None]
    gnds = [c["groundedness"] for c in cases if c.get("groundedness") is not None]
    buckets = [_classify(c) for c in cases]

    lines: list[str] = [
        "# Real100 Case-Level Failure Breakdown",
        "",
        f"Source: `{eval_summary_path}`  ",
        f"Cases: {len(cases)}  ",
        f"accuracy (n={len(accs)}): **{_fmt(_mean(accs))}**  ",
        f"groundedness (n={len(gnds)}): **{_fmt(_mean(gnds))}**",
        "",
        "**Bucket summary**",
        "",
        "| bucket | count |",
        "|---|---|",
    ]
    for bucket in ("pass", "correct_abstention", "wrong_abstention", "wrong_answer", "low_quality"):
        lines.append(f"| {bucket} | {buckets.count(bucket)} |")

    lines.append(_section("All Cases"))
    lines.append(_case_table(sorted(cases, key=lambda c: (_classify(c) != "pass", c.get("query_type", "")))))

    lines.append(_section("By query_type"))
    lines.append(_dim_table(cases, "query_type"))

    lines.append(_section("By answer_status"))
    lines.append(_dim_table(cases, "answer_status"))

    lines.append(_section("Failure Detail"))
    lines.append(_failure_detail(sorted(cases, key=lambda c: c.get("query_type", ""))))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Written: {output_path}")


def main() -> None:
    args = sys.argv[1:]
    eval_path = Path(args[0]) if args else Path("reports/real100/eval_summary.json")
    out_path = Path(args[1]) if len(args) > 1 else eval_path.parent / "case_breakdown.md"
    generate(eval_path, out_path)


if __name__ == "__main__":
    main()
