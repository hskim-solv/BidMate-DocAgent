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
const LEADERBOARD_DATA = {"labels": ["2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-11", "2026-05-12", "2026-05-12", "2026-05-12", "2026-05-12"], "commits": ["e8d861cbcda7", "4e1519ea687a", "f35c684e93b2", "9e69e00be4a4", "7e9652de3106", "ce5ebc491bd5", "2697ef73fdb7", "6a089029e19a", "54ac135cb5f2", "bb8d703b4534", "3a8732dee232", "4376819b1ae4", "f94284324d8b", "524fcaa3cde6", "51455adf8ba9", "e7593a4e3351", "0d6570f869c5", "7dc5a59d790c", "f8d697980016", "5eddb08c9b44", "df0a5303e3c5", "0f6aab94baa6", "761149ba475f", "d70c8df904f2"], "metrics": {"accuracy": {"values": [0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375, 0.84375], "ci_lo": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.71875, 0.71875, 0.71875, 0.71875, 0.71875], "ci_hi": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.96875, 0.96875, 0.96875, 0.96875, 0.96875]}, "groundedness": {"values": [0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143, 0.7142857142857143], "ci_lo": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.5714285714285714, 0.5714285714285714, 0.5714285714285714, 0.5714285714285714, 0.5714285714285714], "ci_hi": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.8333333333333334, 0.8333333333333334, 0.8333333333333334, 0.8333333333333334, 0.8333333333333334]}, "citation_precision": {"values": [0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619, 0.5119047619047619], "ci_lo": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.39285714285714285, 0.39285714285714285, 0.39285714285714285, 0.39285714285714285, 0.39285714285714285], "ci_hi": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.6309523809523809, 0.6309523809523809, 0.6309523809523809, 0.6309523809523809, 0.6309523809523809]}, "answer_format_compliance": {"values": [0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666, 0.6666666666666666], "ci_lo": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.5238095238095238, 0.5238095238095238, 0.5238095238095238, 0.5238095238095238, 0.5238095238095238], "ci_hi": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.8095238095238095, 0.8095238095238095, 0.8095238095238095, 0.8095238095238095, 0.8095238095238095]}}};
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

| Date | Commit | N | Accuracy | Groundedness | Citation | Format | Abstention | Retry |
|---|---|---|---|---|---|---|---|---|
| 2026-05-11 | `e8d861cbcda7` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `4e1519ea687a` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `f35c684e93b2` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `9e69e00be4a4` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `7e9652de3106` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `ce5ebc491bd5` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `2697ef73fdb7` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `6a089029e19a` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `54ac135cb5f2` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `bb8d703b4534` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `3a8732dee232` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `4376819b1ae4` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `f94284324d8b` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `524fcaa3cde6` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `51455adf8ba9` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `e7593a4e3351` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `0d6570f869c5` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `7dc5a59d790c` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `f8d697980016` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-11 | `5eddb08c9b44` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-12 | `df0a5303e3c5` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-12 | `0f6aab94baa6` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-12 | `761149ba475f` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |
| 2026-05-12 | `d70c8df904f2` | 42 | 0.844 | 0.714 | 0.512 | 0.667 | 0.300 | 0.000 |


---

_Tooling: `scripts/leaderboard.py` reads `reports/history/*.aggregate.json` and re-runs `extract_aggregate` as defense-in-depth. Live page rebuild is on merge to main via `.github/workflows/leaderboard.yml`._
