#!/usr/bin/env python3
"""Cost-accuracy frontier extractor (ADR 0038, follow-up to issue #177).

Reads ``reports/eval_summary.json`` (in-repo ablations) and
``reports/external_baselines.json`` (real-API backends) and emits a Markdown
table at ``reports/cost_frontier.md``. Optionally renders
``reports/cost_frontier.png`` when matplotlib is available; the PNG render is
skipped cleanly otherwise so the same script runs in CI containers that don't
install matplotlib.

ADR 0038 interpretation:

- **x-axis** ``sum(case_results[i].cost_estimate_usd)`` in USD. Self-hosted
  ablations (cost = ``None`` at source) are placed at ``x = 0`` and labelled
  "self-hosted" in the legend.
- **y-axis** ``accuracy.mean`` with bootstrap 95% CI band (when populated).
- **Production sweet spot** — lowest-cost external backend whose accuracy CI
  lower bound exceeds the acceptable floor threshold (default ``0.70``).
- **Accuracy ceiling** — best in-repo ablation accuracy at ``x = 0``.
- **Cheapest acceptable floor** — lowest-cost external backend whose accuracy
  mean exceeds the floor; points below the floor are plotted as grey
  non-Pareto dots.

Read-only consumer; does not modify the eval pipeline or the answer contract.
The ADR 0001 ``naive_baseline`` invariant is preserved (no eval logic
touched).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple, Optional, Sequence


DEFAULT_ACCEPTABLE_FLOOR = 0.70


class FrontierPoint(NamedTuple):
    name: str
    cost_usd: float  # 0.0 for self-hosted (cost = None at source)
    accuracy: float  # mean
    ci_lo: Optional[float]
    ci_hi: Optional[float]
    is_self_hosted: bool
    backend: Optional[str]
    model: Optional[str]
    extras: dict


def sum_case_cost(case_results: Sequence[dict]) -> Optional[float]:
    """Sum ``cost_estimate_usd`` across case_results.

    Returns ``None`` if every case has ``cost_estimate_usd is None`` (the
    stub-backend pattern per ADR 0038) or if the input is empty. Callers
    should treat ``None`` as "no cost data — exclude from cost axis".
    """
    total = 0.0
    has_any = False
    for cr in case_results:
        if not isinstance(cr, dict):
            continue
        cost = cr.get("cost_estimate_usd")
        if cost is None:
            continue
        try:
            total += float(cost)
            has_any = True
        except (TypeError, ValueError):
            continue
    return total if has_any else None


def _accuracy_mean(value: object) -> Optional[float]:
    """Coerce ``accuracy`` field (float or {"mean": ...} dict) to a float."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        mean = value.get("mean")
        if isinstance(mean, (int, float)):
            return float(mean)
    return None


def _ci_band(
    run_or_metric: dict, metric: str = "accuracy"
) -> tuple[Optional[float], Optional[float]]:
    """Extract (ci_lo, ci_hi) from a run / metric dict.

    Supports two shapes:
    - ``run["ci"]["accuracy"]`` — eval_summary ablation pattern
    - ``run["accuracy"]`` itself when it's a dict with ci_lo/ci_hi —
      external_baselines.json metrics pattern
    """
    ci_block = run_or_metric.get("ci")
    if isinstance(ci_block, dict):
        ci = ci_block.get(metric)
        if isinstance(ci, dict):
            return ci.get("ci_lo"), ci.get("ci_hi")
    inline = run_or_metric.get(metric)
    if isinstance(inline, dict):
        return inline.get("ci_lo"), inline.get("ci_hi")
    return None, None


def extract_inrepo_points(summary: dict) -> list[FrontierPoint]:
    """Extract one FrontierPoint per ablation run from eval_summary.json.

    Per ADR 0038, in-repo ablations are placed at ``x = 0`` ("self-hosted")
    regardless of any case-level cost data — the in-repo pipeline does not
    pay an external API. Synthesis cost, when populated, is for opt-in
    external-backend ablations and is handled by ``external_baselines.json``,
    not this path.
    """
    points: list[FrontierPoint] = []
    runs = summary.get("ablation", {}).get("runs") or []
    for run in runs:
        if not isinstance(run, dict):
            continue
        name = str(run.get("name") or "")
        if not name:
            continue
        accuracy = _accuracy_mean(run.get("accuracy"))
        if accuracy is None:
            continue
        ci_lo, ci_hi = _ci_band(run, "accuracy")
        points.append(
            FrontierPoint(
                name=name,
                cost_usd=0.0,
                accuracy=accuracy,
                ci_lo=ci_lo,
                ci_hi=ci_hi,
                is_self_hosted=True,
                backend=None,
                model=None,
                extras={"groundedness": run.get("groundedness")},
            )
        )
    return points


def extract_external_points(external: dict) -> list[FrontierPoint]:
    """Extract one FrontierPoint from external_baselines.json (single backend).

    Per ADR 0038, cost is ``sum(case_results[i].cost_estimate_usd)``. If the
    external file lacks per-case cost data (e.g. the langchain runner did not
    emit ``cost_estimate_usd`` per case), the point is excluded from the plot
    with a stderr note — without cost, there is nothing to put on the x-axis.
    """
    backend = external.get("backend")
    model = external.get("model")
    metrics = external.get("metrics") or {}
    acc_block = metrics.get("accuracy")
    accuracy = _accuracy_mean(acc_block)
    if accuracy is None:
        return []
    ci_lo, ci_hi = _ci_band({"accuracy": acc_block}, "accuracy")
    case_results = external.get("case_results") or []
    cost = sum_case_cost(case_results) if case_results else None
    if cost is None:
        sys.stderr.write(
            "[plot_cost_frontier] external_baselines.json has no per-case "
            f"cost (backend={backend}, model={model}). Run "
            "`make external-baselines-langchain` with ANTHROPIC_API_KEY to "
            "populate case_results[i].cost_estimate_usd; external point "
            "excluded.\n"
        )
        return []
    name = (
        f"{backend}:{model}"
        if backend and model
        else (backend or model or "external")
    )
    return [
        FrontierPoint(
            name=name,
            cost_usd=cost,
            accuracy=accuracy,
            ci_lo=ci_lo,
            ci_hi=ci_hi,
            is_self_hosted=False,
            backend=backend,
            model=model,
            extras={},
        )
    ]


def compute_frontier(points: Sequence[FrontierPoint]) -> list[FrontierPoint]:
    """2-D Pareto frontier: lower cost + higher accuracy dominates.

    Identical rule to ``scripts/plot_pareto.compute_pareto_frontier`` but on
    the (cost_usd, accuracy) plane: ``P`` is dominated iff some ``Q`` has
    ``Q.cost <= P.cost`` and ``Q.accuracy >= P.accuracy`` with at least one
    strict. Ties are kept.
    """
    frontier: list[FrontierPoint] = []
    for cand in points:
        dominated = False
        for other in points:
            if other is cand:
                continue
            if (
                other.cost_usd <= cand.cost_usd
                and other.accuracy >= cand.accuracy
                and (
                    other.cost_usd < cand.cost_usd
                    or other.accuracy > cand.accuracy
                )
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(cand)
    return frontier


def find_sweet_spot(
    external: Sequence[FrontierPoint],
    floor: float = DEFAULT_ACCEPTABLE_FLOOR,
) -> Optional[FrontierPoint]:
    """Lowest-cost external backend whose accuracy CI lower bound > floor."""
    qualified = [p for p in external if p.ci_lo is not None and p.ci_lo > floor]
    if not qualified:
        return None
    return min(qualified, key=lambda p: p.cost_usd)


def find_accuracy_ceiling(
    in_repo: Sequence[FrontierPoint],
) -> Optional[FrontierPoint]:
    """Best in-repo ablation accuracy (x = 0)."""
    if not in_repo:
        return None
    return max(in_repo, key=lambda p: p.accuracy)


def find_cheapest_floor(
    external: Sequence[FrontierPoint],
    floor: float = DEFAULT_ACCEPTABLE_FLOOR,
) -> Optional[FrontierPoint]:
    """Lowest-cost external backend whose accuracy mean > floor."""
    qualified = [p for p in external if p.accuracy > floor]
    if not qualified:
        return None
    return min(qualified, key=lambda p: p.cost_usd)


def _fmt_cost(p: FrontierPoint) -> str:
    return f"${p.cost_usd:.4f}" if p.cost_usd > 0 else "$0 (self-hosted)"


def _fmt_ci(p: FrontierPoint) -> str:
    if p.ci_lo is None or p.ci_hi is None:
        return "—"
    return f"[{p.ci_lo:.3f}–{p.ci_hi:.3f}]"


def _fmt_type(p: FrontierPoint) -> str:
    if p.is_self_hosted:
        return "self-hosted"
    if p.backend and p.model:
        return f"{p.backend}/{p.model}"
    return "external"


def render_markdown(
    in_repo: Sequence[FrontierPoint],
    external: Sequence[FrontierPoint],
    frontier: Sequence[FrontierPoint],
    floor: float,
) -> str:
    """Render the cost-accuracy table + ADR 0038 anchors."""
    frontier_names = {p.name for p in frontier}
    sweet_spot = find_sweet_spot(external, floor)
    ceiling = find_accuracy_ceiling(in_repo)
    cheapest_floor = find_cheapest_floor(external, floor)

    lines: list[str] = [
        "# Cost-accuracy frontier (ADR 0038)",
        "",
        f"Acceptable floor: accuracy > {floor:.2f}. CI band: 95% bootstrap "
        "(when populated). Self-hosted ablations are plotted at x=0 per "
        "ADR 0038.",
        "",
        "## Anchors",
        "",
    ]

    if ceiling is not None:
        lines.append(
            f"- **Accuracy ceiling** (in-repo, self-hosted): "
            f"`{ceiling.name}` — {ceiling.accuracy:.3f} {_fmt_ci(ceiling)}"
        )
    else:
        lines.append(
            "- **Accuracy ceiling** (in-repo): — *no in-repo ablations*"
        )

    if sweet_spot is not None:
        lines.append(
            f"- **Production sweet spot** (external, lowest-cost CI_lo > "
            f"{floor:.2f}): `{sweet_spot.name}` — {_fmt_cost(sweet_spot)}, "
            f"acc {sweet_spot.accuracy:.3f} {_fmt_ci(sweet_spot)}"
        )
    else:
        lines.append(
            f"- **Production sweet spot** (external, lowest-cost CI_lo > "
            f"{floor:.2f}): — *no qualifying external backend*"
        )

    if cheapest_floor is not None and (
        sweet_spot is None or cheapest_floor.name != sweet_spot.name
    ):
        lines.append(
            f"- **Cheapest acceptable floor** (external, lowest-cost mean > "
            f"{floor:.2f}): `{cheapest_floor.name}` — "
            f"{_fmt_cost(cheapest_floor)}, "
            f"acc {cheapest_floor.accuracy:.3f}"
        )

    lines.extend(
        [
            "",
            "## All points",
            "",
            "| On frontier | Run | Cost (USD) | Accuracy | 95% CI | Type |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    all_points = sorted(
        list(in_repo) + list(external),
        key=lambda p: (p.cost_usd, -p.accuracy),
    )
    for p in all_points:
        marker = "✓" if p.name in frontier_names else ""
        lines.append(
            f"| {marker} | {p.name} | {_fmt_cost(p)} | {p.accuracy:.3f} | "
            f"{_fmt_ci(p)} | {_fmt_type(p)} |"
        )
    lines.append("")
    if frontier_names:
        lines.append(
            f"Frontier members ({len(frontier_names)}): "
            + ", ".join(sorted(frontier_names))
            + "."
        )
    return "\n".join(lines) + "\n"


def try_render_png(
    in_repo: Sequence[FrontierPoint],
    external: Sequence[FrontierPoint],
    frontier: Sequence[FrontierPoint],
    floor: float,
    out_path: Path,
) -> bool:
    """Attempt matplotlib PNG render; return False if matplotlib missing."""
    try:
        import matplotlib  # type: ignore  # noqa: F401

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError:
        return False

    frontier_names = {p.name for p in frontier}
    fig, ax = plt.subplots(figsize=(9, 6))

    for p in list(in_repo) + list(external):
        on_frontier = p.name in frontier_names
        below_floor = (not p.is_self_hosted) and p.accuracy <= floor
        color = (
            "tab:orange"
            if on_frontier
            else "tab:gray"
            if below_floor
            else "tab:blue"
        )
        size = 120 if on_frontier else 60
        ax.scatter(
            p.cost_usd,
            p.accuracy,
            s=size,
            facecolors=color,
            edgecolors="black",
            zorder=3 if on_frontier else 2,
        )
        ax.annotate(
            p.name,
            (p.cost_usd, p.accuracy),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=8,
        )
        if p.ci_lo is not None and p.ci_hi is not None:
            ax.errorbar(
                p.cost_usd,
                p.accuracy,
                yerr=[[p.accuracy - p.ci_lo], [p.ci_hi - p.accuracy]],
                fmt="none",
                ecolor="black",
                alpha=0.3,
                zorder=1,
            )

    ax.axhline(
        floor,
        color="red",
        linestyle="--",
        alpha=0.5,
        label=f"Acceptable floor ({floor:.2f})",
    )
    frontier_sorted = sorted(frontier, key=lambda p: p.cost_usd)
    if len(frontier_sorted) >= 2:
        ax.plot(
            [p.cost_usd for p in frontier_sorted],
            [p.accuracy for p in frontier_sorted],
            color="tab:orange",
            linestyle="--",
            linewidth=1,
            zorder=1,
            label="Pareto frontier",
        )

    ax.set_xlabel("Cost (USD per eval suite; x=0 means self-hosted)")
    ax.set_ylabel("Accuracy (mean, 95% CI band)")
    ax.set_title("Cost-accuracy frontier — ADR 0038")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", fontsize=8)
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
        "--external",
        default="reports/external_baselines.json",
        help=(
            "Path to external_baselines.json "
            "(default: reports/external_baselines.json)."
        ),
    )
    parser.add_argument(
        "--markdown-out",
        default="reports/cost_frontier.md",
        help="Where to write the Markdown frontier table.",
    )
    parser.add_argument(
        "--png-out",
        default="reports/cost_frontier.png",
        help="Where to write the PNG render (if matplotlib is installed).",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=DEFAULT_ACCEPTABLE_FLOOR,
        help=f"Acceptable accuracy floor (default {DEFAULT_ACCEPTABLE_FLOOR}).",
    )
    args = parser.parse_args(argv)

    in_repo: list[FrontierPoint] = []
    external: list[FrontierPoint] = []

    summary_path = Path(args.summary)
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            sys.stderr.write(
                f"[plot_cost_frontier] Failed to parse {summary_path}: {exc}\n"
            )
            return 2
        in_repo = extract_inrepo_points(summary)
    else:
        sys.stderr.write(
            f"[plot_cost_frontier] {summary_path} not found; skipping in-repo "
            "ablations. Run `make eval` to generate.\n"
        )

    external_path = Path(args.external)
    if external_path.exists():
        try:
            external_data = json.loads(external_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            sys.stderr.write(
                f"[plot_cost_frontier] Failed to parse {external_path}: {exc}\n"
            )
            return 2
        external = extract_external_points(external_data)
    else:
        sys.stderr.write(
            f"[plot_cost_frontier] {external_path} not found; skipping "
            "external baselines. Run `make external-baselines-langchain` to "
            "generate.\n"
        )

    all_points = in_repo + external
    if not all_points:
        sys.stderr.write(
            "[plot_cost_frontier] No points to plot. Generate inputs first.\n"
        )
        return 1

    frontier = compute_frontier(all_points)

    markdown_out = Path(args.markdown_out)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(
        render_markdown(in_repo, external, frontier, args.floor),
        encoding="utf-8",
    )
    print(f"[plot_cost_frontier] Wrote {markdown_out}")

    png_out = Path(args.png_out)
    png_out.parent.mkdir(parents=True, exist_ok=True)
    if try_render_png(in_repo, external, frontier, args.floor, png_out):
        print(f"[plot_cost_frontier] Wrote {png_out}")
    else:
        print(
            "[plot_cost_frontier] matplotlib not installed; PNG skipped. "
            "Install with `pip install matplotlib` and re-run.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
