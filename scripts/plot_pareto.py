#!/usr/bin/env python3
"""Cost-quality Pareto frontier extractor for eval ablation results (issue #124).

Reads ``reports/eval_summary.json`` (produced by ``make eval``) and emits a
Markdown table at ``reports/pareto.md`` highlighting which ablation runs sit
on the cost-quality Pareto frontier. Optionally renders ``reports/pareto.png``
when matplotlib is available; the PNG render is skipped cleanly otherwise so
the same script runs in CI containers that don't install matplotlib.

Cost axis (lower-is-better): primary summary latency p95 in milliseconds.
Quality axis (higher-is-better): citation_precision (the metric whose CI
separation is most discriminating per docs/eval/ablation-results.md).

The script does not modify the eval pipeline or the answer contract; it is
a read-only consumer of ``reports/eval_summary.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence


class ParetoPoint(NamedTuple):
    name: str
    cost: float
    quality: float
    extras: dict


def compute_pareto_frontier(points: Sequence[ParetoPoint]) -> list[ParetoPoint]:
    """Return the subset of points on the 2D Pareto frontier.

    Frontier rule: a point ``P`` is on the frontier iff no other point ``Q``
    has both strictly lower cost and strictly higher quality (``Q`` dominates
    ``P``). Tied points are both kept — neither dominates the other.
    """
    frontier: list[ParetoPoint] = []
    for candidate in points:
        dominated = False
        for other in points:
            if other is candidate:
                continue
            if (
                other.cost <= candidate.cost
                and other.quality >= candidate.quality
                and (other.cost < candidate.cost or other.quality > candidate.quality)
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return frontier


def extract_points(summary: dict) -> list[ParetoPoint]:
    """Pull ``(name, cost, quality, extras)`` tuples out of an eval_summary."""
    points: list[ParetoPoint] = []
    for run in summary.get("ablation", {}).get("runs", []) or []:
        name = str(run.get("name") or "")
        if not name:
            continue
        latency_p95 = (
            run.get("latency", {}).get("p95")
            if isinstance(run.get("latency"), dict)
            else None
        )
        citation_precision = run.get("citation_precision")
        if isinstance(citation_precision, dict):
            citation_precision = citation_precision.get("mean")
        if latency_p95 is None or citation_precision is None:
            continue
        try:
            cost = float(latency_p95)
            quality = float(citation_precision)
        except (TypeError, ValueError):
            continue
        points.append(
            ParetoPoint(
                name=name,
                cost=cost,
                quality=quality,
                extras={
                    "accuracy": run.get("accuracy"),
                    "groundedness": run.get("groundedness"),
                    "retry_rate": run.get("retry"),
                },
            )
        )
    return points


def render_markdown(
    points: Sequence[ParetoPoint],
    frontier: Iterable[ParetoPoint],
) -> str:
    frontier_names = {p.name for p in frontier}
    lines = [
        "# Cost-quality Pareto frontier",
        "",
        "Cost axis = primary-run latency p95 (ms, lower is better).",
        "Quality axis = citation_precision (higher is better).",
        "",
        "| On frontier | Run | Latency p95 (ms) | Citation precision | Accuracy | Groundedness |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for point in sorted(points, key=lambda p: (p.cost, -p.quality)):
        marker = "✓" if point.name in frontier_names else ""
        accuracy = point.extras.get("accuracy")
        groundedness = point.extras.get("groundedness")
        lines.append(
            f"| {marker} | {point.name} | {point.cost:.2f} | {point.quality:.3f} | "
            f"{_fmt(accuracy)} | {_fmt(groundedness)} |"
        )
    lines.append("")
    if frontier_names:
        lines.append(
            f"Frontier members ({len(frontier_names)}): "
            + ", ".join(sorted(frontier_names))
            + "."
        )
    return "\n".join(lines) + "\n"


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, dict):
        value = value.get("mean")
    if value is None:
        return "—"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "—"


def try_render_png(
    points: Sequence[ParetoPoint],
    frontier: Iterable[ParetoPoint],
    out_path: Path,
) -> bool:
    """Attempt PNG render; return True on success, False if matplotlib missing."""
    try:
        import matplotlib  # type: ignore  # noqa: F401

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError:
        return False

    frontier_names = {p.name for p in frontier}
    fig, ax = plt.subplots(figsize=(8, 6))
    for point in points:
        on_frontier = point.name in frontier_names
        ax.scatter(
            point.cost,
            point.quality,
            s=120 if on_frontier else 60,
            facecolors="tab:orange" if on_frontier else "tab:gray",
            edgecolors="black",
            zorder=3 if on_frontier else 2,
        )
        ax.annotate(
            point.name,
            (point.cost, point.quality),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=9,
        )
    frontier_sorted = sorted(frontier, key=lambda p: p.cost)
    if len(frontier_sorted) >= 2:
        ax.plot(
            [p.cost for p in frontier_sorted],
            [p.quality for p in frontier_sorted],
            color="tab:orange",
            linestyle="--",
            linewidth=1,
            zorder=1,
        )
    ax.set_xlabel("Cost — latency p95 (ms, lower is better)")
    ax.set_ylabel("Quality — citation_precision (higher is better)")
    ax.set_title("Ablation runs: cost-quality Pareto frontier")
    ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(out_path, dpi=144)
    plt.close(fig)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        default="reports/eval_summary.json",
        help="Path to eval_summary.json (default: reports/eval_summary.json).",
    )
    parser.add_argument(
        "--markdown-out",
        default="reports/pareto.md",
        help="Where to write the Markdown frontier table (default: reports/pareto.md).",
    )
    parser.add_argument(
        "--png-out",
        default="reports/pareto.png",
        help="Where to write the PNG render if matplotlib is installed (default: reports/pareto.png).",
    )
    args = parser.parse_args(argv)

    summary_path = Path(args.summary)
    if not summary_path.exists():
        sys.stderr.write(
            f"[plot_pareto] {summary_path} not found. Run `make eval` first.\n"
        )
        return 2

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[plot_pareto] Failed to parse {summary_path}: {exc}\n")
        return 2

    points = extract_points(summary)
    if not points:
        sys.stderr.write(
            "[plot_pareto] No ablation runs with both latency.p95 and "
            "citation_precision found.\n"
        )
        return 1

    frontier = compute_pareto_frontier(points)

    markdown_out = Path(args.markdown_out)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(render_markdown(points, frontier), encoding="utf-8")
    print(f"[plot_pareto] Wrote {markdown_out}")

    png_out = Path(args.png_out)
    png_out.parent.mkdir(parents=True, exist_ok=True)
    if try_render_png(points, frontier, png_out):
        print(f"[plot_pareto] Wrote {png_out}")
    else:
        print(
            "[plot_pareto] matplotlib not installed; PNG render skipped. "
            "Install with `pip install matplotlib` and re-run.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
