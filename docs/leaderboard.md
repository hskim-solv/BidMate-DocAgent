---
title: Synthetic Eval Leaderboard
layout: page
permalink: /leaderboard/
---

# Synthetic Eval Leaderboard

Time-series view of headline metrics across commits to main. Bootstrap 95% CI bands are shaded — wide bands mean *we cannot yet detect a difference*, which is just as informative as a narrow band showing a trend.

Source data is in `reports/history/` and the rendering source is in `scripts/leaderboard.py`. ADR 0005 aggregate-only boundary respected.

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" defer></script>

<h2 id="accuracy">Accuracy</h2>
<canvas id="chart-accuracy" height="240"></canvas>
<h2 id="groundedness">Groundedness</h2>
<canvas id="chart-groundedness" height="240"></canvas>
<h2 id="citation_precision">Citation Precision</h2>
<canvas id="chart-citation_precision" height="240"></canvas>
<h2 id="answer_format_compliance">Format Compliance</h2>
<canvas id="chart-answer_format_compliance" height="240"></canvas>

<script>
const LEADERBOARD_DATA = {"labels": [], "commits": [], "metrics": {"accuracy": {"values": [], "ci_lo": [], "ci_hi": []}, "groundedness": {"values": [], "ci_lo": [], "ci_hi": []}, "citation_precision": {"values": [], "ci_lo": [], "ci_hi": []}, "answer_format_compliance": {"values": [], "ci_lo": [], "ci_hi": []}}};
const METRIC_KEYS = ["accuracy", "groundedness", "citation_precision", "answer_format_compliance"];

window.addEventListener('DOMContentLoaded', () => {
  for (const metric of METRIC_KEYS) {
    const el = document.getElementById(`chart-${metric}`);
    if (!el) continue;
    const m = LEADERBOARD_DATA.metrics[metric];
    new Chart(el, {
      type: 'line',
      data: {
        labels: LEADERBOARD_DATA.labels,
        datasets: [
          {
            label: `${metric} CI lower`,
            data: m.ci_lo,
            borderColor: 'transparent',
            backgroundColor: 'rgba(54, 162, 235, 0.15)',
            fill: '+1',
            pointRadius: 0,
            order: 3,
          },
          {
            label: metric,
            data: m.values,
            borderColor: 'rgb(54, 162, 235)',
            backgroundColor: 'rgb(54, 162, 235)',
            fill: false,
            tension: 0.1,
            order: 1,
          },
          {
            label: `${metric} CI upper`,
            data: m.ci_hi,
            borderColor: 'transparent',
            pointRadius: 0,
            order: 2,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                const sha = LEADERBOARD_DATA.commits[i] || '?';
                return `${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(3) ?? '—'} @ ${sha}`;
              },
            },
          },
        },
        scales: {
          y: { beginAtZero: false, suggestedMin: 0, suggestedMax: 1.0 },
        },
      },
    });
  }
});
</script>

## Tabular view



---

_Tooling: `scripts/leaderboard.py` reads `reports/history/*.aggregate.json` and re-runs `extract_aggregate` as defense-in-depth. Live page rebuild is on merge to main via `.github/workflows/leaderboard.yml`._
