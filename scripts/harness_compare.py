#!/usr/bin/env python3
"""Compare two harness runs or render a matrix-cell delta table.

Two entry points:

  python3 scripts/harness_compare.py --run-a <dir> --run-b <dir> [--out FILE]
    Standalone two-run compare. Either argument can point at a run directory
    (resolves to <dir>/metrics/eval_summary.json) or directly at the JSON.

  render_matrix_compare(cells, base_cell) -> str
    Library helper used by scripts/run_harness.py --matrix to write
    artifacts/matrices/<id>/compare.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eval_delta import METRICS, fmt_delta, fmt_value, get_path  # noqa: E402


def resolve_summary(path: Path) -> Path:
    """Accept either a run directory or a direct eval_summary.json path."""
    if path.is_dir():
        candidate = path / "metrics" / "eval_summary.json"
        if not candidate.exists():
            raise SystemExit(f"[ERROR] No eval_summary.json under {path}")
        return candidate
    if not path.exists():
        raise SystemExit(f"[ERROR] Path does not exist: {path}")
    return path


def render_pair(base: dict[str, Any], head: dict[str, Any], *, title: str,
                base_label: str = "A", head_label: str = "B") -> str:
    """Two-column delta table."""
    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")
    lines.append(
        f"- cases: {base_label}={base.get('num_predictions', '?')} · "
        f"{head_label}={head.get('num_predictions', '?')}"
    )
    lines.append("")
    lines.append(f"| metric | {base_label} | {head_label} | Δ |")
    lines.append("|---|---|---|---|")
    for path, label, higher in METRICS:
        b = get_path(base, path)
        h = get_path(head, path)
        lines.append(
            f"| {label} | {fmt_value(b)} | {fmt_value(h)} | {fmt_delta(b, h, higher)} |"
        )
    lines.append("")
    lines.append(
        "_✅ direction-of-improvement; ⚠️ direction-of-regression. "
        "Synthetic-data delta — does not gate CI._"
    )
    return "\n".join(lines) + "\n"


def render_matrix_compare(
    cells: Sequence[dict[str, Any]],
    base_cell_name: str,
    *,
    matrix_id: str,
) -> str:
    """N-column delta table: one base cell + N-1 cells with per-metric deltas.

    Each cell dict must have:
      - "name": str
      - "status": "passed" | "failed"
      - "eval_summary": dict (loaded eval_summary.json contents; may be {})
    """
    if not cells:
        raise ValueError("matrix_compare requires at least one cell")
    cell_names = [c["name"] for c in cells]
    if base_cell_name not in cell_names:
        raise ValueError(
            f"base_cell '{base_cell_name}' not in cells {cell_names}"
        )
    base = next(c["eval_summary"] for c in cells if c["name"] == base_cell_name)
    others = [c for c in cells if c["name"] != base_cell_name]

    lines: list[str] = []
    lines.append(f"### Matrix compare — {matrix_id}")
    lines.append("")
    lines.append(f"- base cell: `{base_cell_name}` · cases: {base.get('num_predictions', '?')}")
    if any(c["status"] != "passed" for c in cells):
        failed = [c["name"] for c in cells if c["status"] != "passed"]
        lines.append(f"- failed cells: {', '.join(failed)} (rows show `—`)")
    lines.append("")

    header_cells = [base_cell_name] + [c["name"] for c in others]
    delta_headers = [f"Δ {c['name']}" for c in others]
    lines.append("| metric | " + " | ".join(header_cells) + " | " + " | ".join(delta_headers) + " |")
    lines.append("|" + "---|" * (1 + len(header_cells) + len(delta_headers)))

    for path, label, higher in METRICS:
        base_val = get_path(base, path)
        row = [label, fmt_value(base_val)]
        for c in others:
            if c["status"] != "passed":
                row.append("—")
            else:
                row.append(fmt_value(get_path(c["eval_summary"], path)))
        for c in others:
            if c["status"] != "passed":
                row.append("—")
            else:
                row.append(fmt_delta(base_val, get_path(c["eval_summary"], path), higher))
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append(
        "_✅ direction-of-improvement; ⚠️ direction-of-regression. "
        "Synthetic-data delta — does not gate CI._"
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-a", required=True, help="Run dir or eval_summary.json (baseline)")
    ap.add_argument("--run-b", required=True, help="Run dir or eval_summary.json (head)")
    ap.add_argument("--out", default=None, help="Write markdown to file in addition to stdout")
    ap.add_argument("--title", default="Harness compare")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    a_path = resolve_summary(Path(args.run_a))
    b_path = resolve_summary(Path(args.run_b))
    a = json.loads(a_path.read_text(encoding="utf-8"))
    b = json.loads(b_path.read_text(encoding="utf-8"))
    markdown = render_pair(a, b, title=args.title)
    print(markdown, end="")
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
