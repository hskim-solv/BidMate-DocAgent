#!/usr/bin/env python3
"""Time-series leaderboard renderer for the synthetic public eval (#166).

Reads every committed aggregate snapshot under ``reports/history/`` and
writes two artifacts:

* ``reports/leaderboard.md`` — chronological markdown table for in-repo viewing
* ``docs/eval/leaderboard.md`` — Jekyll-rendered page with an embedded Chart.js
  line chart for each headline metric, plus bootstrap CI shaded bands.
  Surfaced at ``hskim-solv.github.io/BidMate-DocAgent/leaderboard/``.

Mirrors the ``scripts/render_real_eval_history.py`` pattern but for the
public synthetic surface (ADR 0005 aggregate-only commit boundary
respected by reusing ``extract_aggregate`` from
``scripts/run_real_eval_delta.py``).

Modes:

* (default) overwrite the two rendered files in place.
* ``--check`` exit non-zero if either file would differ from disk.
  Suitable for CI gating.

Usage:

    python3 scripts/leaderboard.py
    python3 scripts/leaderboard.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._utils import render_history_table  # noqa: E402
from scripts.run_real_eval_delta import extract_aggregate  # noqa: E402

HISTORY_DIR = ROOT / "reports" / "history"
LEADERBOARD_MD = ROOT / "reports" / "leaderboard.md"
LEADERBOARD_PAGE = ROOT / "docs" / "eval" / "leaderboard.md"

HEADLINE_METRICS: list[tuple[str, str]] = [
    ("accuracy", "Accuracy"),
    ("groundedness", "Groundedness"),
    ("citation_precision", "Citation Precision"),
    ("answer_format_compliance", "Format Compliance"),
]

TABLE_COLUMNS: list[tuple[str, str]] = [
    ("date", "Date"),
    ("commit", "Commit"),
    ("num_predictions", "N"),
    ("accuracy", "Accuracy"),
    ("groundedness", "Groundedness"),
    ("citation_precision", "Citation"),
    ("answer_format_compliance", "Format"),
    ("abstention", "Abstention"),
    ("retry", "Retry"),
]


def load_history(history_dir: Path = HISTORY_DIR) -> list[dict[str, Any]]:
    """Load all aggregate snapshots in chronological order.

    Each snapshot is re-passed through ``extract_aggregate`` as a
    defense-in-depth privacy guard against committed history files
    containing fields outside the ADR 0005 allowlist. Issue #476 /
    ADR 0029 adds an ``ablation_full`` sub-aggregate alongside the
    primary ``naive_baseline`` metrics — absent on pre-#476 snapshots,
    which the renderer surfaces as ``—`` rather than dropping the row.
    Issue #650 / ADR 0039 adds ``by_format_hwp`` extracted from the
    ``by_format.hwp`` bucket; absent on pre-#650 snapshots (shows ``—``
    per ADR 0030 forward-only).
    """
    if not history_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.aggregate.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        agg = extract_aggregate(raw)
        provenance = raw.get("provenance") or agg.get("run_manifest") or {}
        ci = agg.get("ci") or {}
        ablation_full = agg.get("ablation_full") or {}
        by_format = agg.get("by_format") or {}
        by_format_hwp = by_format.get("hwp") or {}
        rows.append(
            {
                "file": path.name,
                "commit": str(provenance.get("git_commit") or "")[:12],
                "date": str(provenance.get("generated_at") or "")[:10],
                "num_predictions": agg.get("num_predictions"),
                "accuracy": agg.get("accuracy"),
                "groundedness": agg.get("groundedness"),
                "citation_precision": agg.get("citation_precision"),
                "answer_format_compliance": agg.get("answer_format_compliance"),
                "abstention": agg.get("abstention"),
                "retry": agg.get("retry"),
                "ci": ci,
                "ablation_full": ablation_full,
                "by_format_hwp": by_format_hwp,
            }
        )
    rows.sort(key=lambda row: (row["date"], row["file"]))
    return rows


def _full_row_view(row: dict[str, Any]) -> dict[str, Any]:
    """Project an `ablation_full` sub-aggregate onto the leaderboard row shape.

    The renderer feeds the same column inventory (``TABLE_COLUMNS``) for
    both pipelines, so the full-pipeline row reuses the same keys
    (``accuracy``, ``citation_precision``, …) — they just carry the
    `agentic_full` value instead of the `naive_baseline` one.
    """
    full = row.get("ablation_full") or {}
    return {
        "date": row["date"],
        "commit": row["commit"],
        "num_predictions": full.get("num_predictions"),
        "accuracy": full.get("accuracy"),
        "groundedness": full.get("groundedness"),
        "citation_precision": full.get("citation_precision"),
        "answer_format_compliance": full.get("answer_format_compliance"),
        "abstention": full.get("abstention"),
        "retry": full.get("retry"),
        "ci": full.get("ci") or {},
    }


def _hwp_format_row_view(row: dict[str, Any]) -> dict[str, Any]:
    """Project the ``by_format_hwp`` bucket onto the leaderboard row shape.

    Absent on pre-#650 snapshots (shows ``—`` per ADR 0030 forward-only).
    """
    hwp = row.get("by_format_hwp") or {}
    return {
        "date": row["date"],
        "commit": row["commit"],
        "num_predictions": hwp.get("num_predictions"),
        "accuracy": hwp.get("accuracy"),
        "groundedness": hwp.get("groundedness"),
        "citation_precision": hwp.get("citation_precision"),
        "answer_format_compliance": hwp.get("answer_format_compliance"),
        "abstention": hwp.get("abstention"),
        "retry": hwp.get("retry"),
        "ci": {},
    }


def _render_table_only(rows: list[dict[str, Any]]) -> str:
    """Return just the markdown table (header + rows), with no document title or intro.

    Used by both ``render_markdown_table`` (for the standalone
    ``reports/leaderboard.md``, which wraps it in title + intro) and
    ``render_page`` (which embeds it under its own ``## Tabular view``
    section, where a duplicate title would be a bug).
    """
    return render_history_table(
        rows,
        TABLE_COLUMNS,
        empty_message="",
        trailing_newline=True,
    )


def render_markdown_table(rows: list[dict[str, Any]]) -> str:
    """Standalone ``reports/leaderboard.md`` body — title + intro + two pipeline tables."""
    if not rows:
        return (
            "# Synthetic Eval Leaderboard\n\n"
            "_No history entries yet. CI populates `reports/history/` on "
            "every merge to main._\n"
        )
    intro = [
        "# Synthetic Eval Leaderboard",
        "",
        "Time-series view of headline metrics across commits to main. "
        "Each row is one CI run on merge. Bootstrap 95% CI bands are "
        "visualized on the [GitHub Pages chart](https://hskim-solv.github.io/BidMate-DocAgent/leaderboard/).",
        "",
        "Two pipelines render side by side: `naive_baseline` (ADR 0001 — "
        "intentionally stable extractive floor) and `agentic_full` "
        "(ADR 0029 — production surface where merges actually move "
        "metrics). A static baseline against a moving full series is "
        "the *intended* story, not stagnation.",
        "",
        "Generated by `scripts/leaderboard.py` from "
        "`reports/history/*.aggregate.json`. ADR 0005 aggregate-only "
        "boundary enforced by `extract_aggregate`.",
        "",
        "",
        "## Pipeline: naive_baseline (ADR 0001)",
        "",
        "",
    ]
    full_rows = [_full_row_view(row) for row in rows]
    hwp_rows = [_hwp_format_row_view(row) for row in rows]
    return (
        "\n".join(intro)
        + _render_table_only(rows)
        + "\n## Pipeline: agentic_full (ADR 0024 / ADR 0029)\n\n"
        + "_`—` cells are pre-#476 snapshots that predate the "
        + "`ablation_full` schema; daily cron snapshots fill in going forward._\n\n"
        + render_history_table(
            full_rows,
            TABLE_COLUMNS,
            empty_message="",
            trailing_newline=True,
        )
        + "\n## HWP Slice: by_format[hwp] (ADR 0039 / issue #650)\n\n"
        + "_HWP-format case accuracy extracted from `eval_summary.json:by_format.hwp`. "
        + "`—` cells predate PR-B (#650). Forward-only per ADR 0030._\n\n"
        + render_history_table(
            hwp_rows,
            TABLE_COLUMNS,
            empty_message="",
            trailing_newline=True,
        )
    )


def _chart_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the JSON payload consumed by Chart.js.

    Each metric carries three series:
    - ``baseline``: ``naive_baseline`` time series
    - ``full``: ``agentic_full`` time series (ADR 0029; gaps on pre-#476)
    - ``hwp_format``: ``by_format.hwp`` slice (ADR 0039; gaps on pre-#650)
    """
    labels = [row["date"] for row in rows]
    commits = [row["commit"] for row in rows]
    metrics: dict[str, dict[str, dict[str, list[Any]]]] = {}
    for key, _ in HEADLINE_METRICS:
        metrics[key] = {
            "baseline": {
                "values": [row.get(key) for row in rows],
                "ci_lo": [
                    (row.get("ci") or {}).get(key, {}).get("ci_lo")
                    for row in rows
                ],
                "ci_hi": [
                    (row.get("ci") or {}).get(key, {}).get("ci_hi")
                    for row in rows
                ],
            },
            "full": {
                "values": [
                    (row.get("ablation_full") or {}).get(key) for row in rows
                ],
                "ci_lo": [
                    ((row.get("ablation_full") or {}).get("ci") or {})
                    .get(key, {})
                    .get("ci_lo")
                    for row in rows
                ],
                "ci_hi": [
                    ((row.get("ablation_full") or {}).get("ci") or {})
                    .get(key, {})
                    .get("ci_hi")
                    for row in rows
                ],
            },
            "hwp_format": {
                "values": [
                    (row.get("by_format_hwp") or {}).get(key) for row in rows
                ],
            },
        }
    return {"labels": labels, "commits": commits, "metrics": metrics}


def render_page(rows: list[dict[str, Any]]) -> str:
    """Render the docs/eval/leaderboard.md page with embedded Chart.js."""
    chart_payload = _chart_data(rows)
    metric_canvases = "\n".join(
        f'<h2 id="{key}">{label}</h2>\n<canvas id="chart-{key}" height="240"></canvas>'
        for key, label in HEADLINE_METRICS
    )
    table_md = _render_table_only(rows)
    metric_keys_js = json.dumps([k for k, _ in HEADLINE_METRICS])
    data_json = json.dumps(chart_payload, ensure_ascii=False)

    return f"""---
title: Synthetic Eval Leaderboard
layout: page
permalink: /leaderboard/
---

# Synthetic Eval Leaderboard

Time-series view of headline metrics across commits to main. Two pipelines render as overlaid series: `naive_baseline` (ADR 0001 — intentionally stable extractive floor) and `agentic_full` (ADR 0029 — production surface where pipeline merges actually move metrics). Bootstrap 95% CI bands are shaded on the baseline series; wide bands mean *we cannot yet detect a difference*, which is just as informative as a narrow band showing a trend.

Source data is in `reports/history/` and the rendering source is in `scripts/leaderboard.py`. ADR 0005 aggregate-only boundary respected.

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" defer></script>

{metric_canvases}

<script>
const LEADERBOARD_DATA = {data_json};
const METRIC_KEYS = {metric_keys_js};

window.addEventListener('DOMContentLoaded', () => {{
  for (const metric of METRIC_KEYS) {{
    const el = document.getElementById(`chart-${{metric}}`);
    if (!el) continue;
    const baseline = LEADERBOARD_DATA.metrics[metric].baseline;
    const full = LEADERBOARD_DATA.metrics[metric].full;
    const hwpFormat = LEADERBOARD_DATA.metrics[metric].hwp_format;
    new Chart(el, {{
      type: 'line',
      data: {{
        labels: LEADERBOARD_DATA.labels,
        datasets: [
          {{
            label: 'naive_baseline CI lower',
            data: baseline.ci_lo,
            borderColor: 'transparent',
            backgroundColor: 'rgba(54, 162, 235, 0.15)',
            fill: '+1',
            pointRadius: 0,
            order: 5,
          }},
          {{
            label: 'naive_baseline',
            data: baseline.values,
            borderColor: 'rgb(54, 162, 235)',
            backgroundColor: 'rgb(54, 162, 235)',
            fill: false,
            tension: 0.1,
            order: 3,
          }},
          {{
            label: 'naive_baseline CI upper',
            data: baseline.ci_hi,
            borderColor: 'transparent',
            pointRadius: 0,
            order: 4,
          }},
          {{
            label: 'agentic_full',
            data: full.values,
            borderColor: 'rgb(255, 159, 64)',
            backgroundColor: 'rgb(255, 159, 64)',
            fill: false,
            tension: 0.1,
            spanGaps: false,
            order: 1,
          }},
          {{
            label: 'hwp_format (by_format[hwp])',
            data: hwpFormat.values,
            borderColor: 'rgb(75, 192, 192)',
            backgroundColor: 'rgb(75, 192, 192)',
            fill: false,
            tension: 0.1,
            spanGaps: false,
            order: 2,
          }},
        ],
      }},
      options: {{
        responsive: true,
        plugins: {{
          legend: {{
            display: true,
            labels: {{
              filter: (item) => !item.text.includes(' CI '),
            }},
          }},
          tooltip: {{
            callbacks: {{
              label: (ctx) => {{
                const i = ctx.dataIndex;
                const sha = LEADERBOARD_DATA.commits[i] || '?';
                return `${{ctx.dataset.label}}: ${{ctx.parsed.y?.toFixed(3) ?? '—'}} @ ${{sha}}`;
              }},
            }},
          }},
        }},
        scales: {{
          y: {{ beginAtZero: false, suggestedMin: 0, suggestedMax: 1.0 }},
        }},
      }},
    }});
  }}
}});
</script>

## Tabular view

{table_md}

---

_Tooling: `scripts/leaderboard.py` reads `reports/history/*.aggregate.json` and re-runs `extract_aggregate` as defense-in-depth. Live page rebuild is on merge to main via `.github/workflows/leaderboard.yml`._
"""


def write_artifacts(
    rows: list[dict[str, Any]],
    *,
    md_path: Path = LEADERBOARD_MD,
    page_path: Path = LEADERBOARD_PAGE,
) -> tuple[str, str]:
    md = render_markdown_table(rows)
    page = render_page(rows)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    page_path.write_text(page, encoding="utf-8")
    return md, page


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if either rendered file would differ from disk.",
    )
    ap.add_argument(
        "--history-dir",
        default=str(HISTORY_DIR),
        help="History directory to read aggregate snapshots from.",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_history(Path(args.history_dir))
    new_md = render_markdown_table(rows)
    new_page = render_page(rows)

    if args.check:
        stale = False
        if LEADERBOARD_MD.exists() and LEADERBOARD_MD.read_text(encoding="utf-8") != new_md:
            print(f"[FAIL] {LEADERBOARD_MD} is stale.", file=sys.stderr)
            stale = True
        if LEADERBOARD_PAGE.exists() and LEADERBOARD_PAGE.read_text(encoding="utf-8") != new_page:
            print(f"[FAIL] {LEADERBOARD_PAGE} is stale.", file=sys.stderr)
            stale = True
        if stale:
            print("Run: python3 scripts/leaderboard.py", file=sys.stderr)
            return 1
        print("[OK] Leaderboard artifacts up to date.")
        return 0

    LEADERBOARD_MD.parent.mkdir(parents=True, exist_ok=True)
    LEADERBOARD_PAGE.parent.mkdir(parents=True, exist_ok=True)
    LEADERBOARD_MD.write_text(new_md, encoding="utf-8")
    LEADERBOARD_PAGE.write_text(new_page, encoding="utf-8")
    print(f"[OK] Wrote {LEADERBOARD_MD.relative_to(ROOT)} ({len(rows)} rows).")
    print(f"[OK] Wrote {LEADERBOARD_PAGE.relative_to(ROOT)} (Chart.js page).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
