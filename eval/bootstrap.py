#!/usr/bin/env python3
"""Deterministic bootstrap confidence intervals for eval metrics.

For a metric that is a *mean* over per-case scores (accuracy,
groundedness, citation_precision, claim_citation_alignment, abstention,
answer_format_compliance, comparison_target_recall, comparison_pool_recall,
retry), the 95 % CI is obtained by resampling cases *with replacement*
``num_resamples`` times and reading the (α/2, 1−α/2) percentiles of the
resampled means. The estimator is seeded by ``numpy.random.default_rng``
so two runs over the same case results produce byte-identical CI output
across platforms — required for the ``update_readme_metrics.py --check``
flow under ADR 0001 / ADR 0005.

Not applicable to (intentionally skipped):

* ``latency`` — already reported with percentiles (p50, p95). Bootstrap
  on latency would mix sampling noise with cold-start variance and is
  better treated separately (see plan §2.1 latency-variance analysis).
* ``retry_reason_counts`` / ``citation_grounding_error_counts`` —
  categorical histograms; CI on a count requires a different model.
"""
from __future__ import annotations

import numpy as np

DEFAULT_NUM_RESAMPLES = 1000
DEFAULT_ALPHA = 0.05
DEFAULT_SEED = 17


def bootstrap_ci(
    values: list[float],
    *,
    num_resamples: int = DEFAULT_NUM_RESAMPLES,
    alpha: float = DEFAULT_ALPHA,
    seed: int = DEFAULT_SEED,
) -> dict[str, float | int] | None:
    """Return ``{mean, ci_lo, ci_hi, n, num_resamples, alpha}`` or ``None``.

    ``values`` is the per-case score list (typically 0.0 or 1.0 for the
    binary metrics; fractional for citation_precision and friends).
    ``None`` if ``values`` is empty — the caller should keep the metric
    out of any CI-aware rendering rather than fabricate a band.
    """
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    n = int(arr.shape[0])
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(num_resamples, n), replace=True).mean(axis=1)
    return {
        "mean": float(arr.mean()),
        "ci_lo": float(np.percentile(means, 100 * alpha / 2, method="linear")),
        "ci_hi": float(np.percentile(means, 100 * (1 - alpha / 2), method="linear")),
        "n": n,
        "num_resamples": int(num_resamples),
        "alpha": float(alpha),
    }


def format_ci_band(ci: dict[str, float | int] | None, *, digits: int = 3) -> str:
    """Render a CI dict for human-readable tables: ``0.906 (0.81–0.95)``.

    ``digits`` controls precision uniformly for mean and bounds. Returns
    ``"N/A"`` if ``ci`` is None (matching the existing N/A convention in
    ``scripts/update_readme_metrics.py``).
    """
    if not ci or ci.get("mean") is None:
        return "N/A"
    mean = ci["mean"]
    lo = ci.get("ci_lo")
    hi = ci.get("ci_hi")
    if lo is None or hi is None:
        return f"{mean:.{digits}f}"
    return f"{mean:.{digits}f} ({lo:.{digits}f}–{hi:.{digits}f})"


__all__ = [
    "DEFAULT_NUM_RESAMPLES",
    "DEFAULT_ALPHA",
    "DEFAULT_SEED",
    "bootstrap_ci",
    "format_ci_band",
]
