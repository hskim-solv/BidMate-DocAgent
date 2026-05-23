#!/usr/bin/env python3
"""Distinguishing-power gauge for real-data eval ablations (ADR 0053 §Consequences).

Reads an ``eval_summary.json`` (default ``reports/real100/eval_summary.json``)
that contains three ablation runs — ``full``, ``random_retrieval``,
``single_chunk`` (ADR 0053 floors) — and computes per-metric gauges:

* **Raw gap** = ``default − floor`` for each (metric, floor) pair.
* **Normalized score** = ``(default − floor) / (1 − floor)`` — what fraction
  of the remaining headroom above the floor the default occupies. ADR 0053
  §Consequences names this the "is the signal alive" gauge.

Two outputs (both committable per ADR 0005 — aggregate-only, no per-case
data is ever read):

* ``reports/real100/distinguishing_power.md`` — markdown table for human
  inspection / PR-D README ingestion.
* ``reports/real100/distinguishing_power.aggregate.json`` — machine-readable
  schema for downstream tooling (PR-D's README auto-regen).

CLI::

    python3 scripts/distinguishing_power.py
    python3 scripts/distinguishing_power.py --summary path/to/eval_summary.json
    python3 scripts/distinguishing_power.py --out-md path.md --out-json path.json

Exit codes::

    0 — wrote both artifacts successfully
    1 — summary file missing / missing ablation runs / unexpected schema
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Repo root sentinel so the script works whether invoked as
# ``python3 scripts/distinguishing_power.py`` or imported as
# ``scripts.distinguishing_power`` from the test suite.
ROOT = Path(__file__).resolve().parents[1]

# scripts-dir-on-path so ``build_provenance`` imports cleanly whether the
# script is run directly (sys.path[0] == scripts/) or imported as
# ``scripts.distinguishing_power`` from pytest (repo root on path). Matches
# the sibling pattern documented in scripts/_utils.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _utils import build_provenance  # noqa: E402

# Default I/O paths — all relative to repo root. Overridable via CLI.
DEFAULT_SUMMARY = ROOT / "reports" / "real100" / "eval_summary.json"
DEFAULT_OUT_MD = ROOT / "reports" / "real100" / "distinguishing_power.md"
DEFAULT_OUT_JSON = ROOT / "reports" / "real100" / "distinguishing_power.aggregate.json"

# Required ablation names. The two floors come from ADR 0053; the default
# label is fixed to ``full`` to match eval/real_config.local.yaml convention
# (ablation_runs[0].name).
DEFAULT_RUN = "full"
FLOOR_RUNS = ("random_retrieval", "single_chunk")
REQUIRED_RUNS = (DEFAULT_RUN, *FLOOR_RUNS)

# Metrics gauged. "abstention" is excluded from the gauge because it is
# a *different objective surface* (correct refusal) — random_retrieval
# legitimately scores high on it (e.g. 0.89 at n=221) without indicating
# the default has lost distinguishing power. The eval_summary will still
# include abstention numbers in its raw run aggregates.
GAUGED_METRICS = (
    "accuracy",
    "groundedness",
    "citation_precision",
    "claim_citation_alignment",
    "answer_format_compliance",
)


def _load_summary(path: Path) -> dict[str, Any]:
    """Load ``eval_summary.json`` and verify the three ablation runs exist.

    Raises ``SystemExit(1)`` with a human-readable error on any structural
    surprise (missing file, missing ``ablation.runs``, missing required run).
    Test-friendly: callers (including the unit test) can catch SystemExit.
    """
    if not path.exists():
        sys.exit(
            f"[ERROR] eval_summary not found: {path}\n"
            f"        Run `make real-eval` first (writes the gitignored summary)."
        )
    with path.open() as fh:
        data = json.load(fh)
    runs = data.get("ablation", {}).get("runs")
    if not isinstance(runs, list):
        sys.exit(
            f"[ERROR] eval_summary {path} has no ablation.runs list — "
            f"distinguishing-power gauge requires the 3-row ablation surface "
            f"(see ADR 0053 + eval/real_config.local.yaml ablation_runs)."
        )
    names = {r.get("name") for r in runs}
    missing = [name for name in REQUIRED_RUNS if name not in names]
    if missing:
        sys.exit(
            f"[ERROR] eval_summary {path} missing required ablation runs: "
            f"{missing}. Expected all of {list(REQUIRED_RUNS)} per ADR 0053. "
            f"Got: {sorted(names)}"
        )
    return data


def _runs_by_name(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index ablation runs by name for O(1) lookup."""
    return {r["name"]: r for r in summary["ablation"]["runs"]}


def _safe_metric(run: dict[str, Any], metric: str) -> float | None:
    """Pull a metric value from an ablation run, tolerating absence.

    Some metrics (e.g. ``citation_precision``) may be ``None`` when n=0
    for the relevant slice. Return ``None`` rather than raising — the
    gauge row for that metric will be marked ``n/a`` in both outputs.
    """
    value = run.get(metric)
    if value is None:
        ci = run.get("ci", {}).get(metric)
        if isinstance(ci, dict):
            value = ci.get("mean")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_metric_n(run: dict[str, Any], metric: str) -> int | None:
    """Pull the CI denominator (``n``) for one (run, metric) pair.

    ADR 0054 makes the quality metrics conditional on a substantive answer
    attempt, so ``accuracy`` / ``groundedness`` / ``citation_precision`` are
    ``None`` on the correct-refusal path and excluded from their mean — giving
    them a *smaller* denominator (e.g. 118) than ``answer_format_compliance``
    (199) and ``claim_citation_alignment`` (173), which stay measurable on
    over-answered / answered cases. The single per-run ``effective_n`` only
    approximates the accuracy/groundedness/citation_precision denominator, so
    the gauge surfaces this per-(metric, run) ``n`` to keep the divergence
    visible rather than implying every quality metric shares one denominator.

    Returns ``None`` when the run has no ``ci`` block for the metric (e.g. the
    inline test fixtures, or a metric absent from the slice).
    """
    ci = run.get("ci")
    if isinstance(ci, dict):
        entry = ci.get(metric)
        if isinstance(entry, dict):
            n = entry.get("n")
            if isinstance(n, int):
                return n
    return None


def _safe_abstention(run: dict[str, Any]) -> dict[str, Any]:
    """Extract per-run abstention transparency fields (ADR 0054 §Consequences).

    Returns a dict with three keys:

    * ``abstention_rate`` — float | None. The existing ``abstention`` field
      from ``metric_block`` (eval/run_eval.py:597) — fraction of *unanswerable*
      cases on which the model correctly refused. High values (e.g. 0.89 for
      random_retrieval at n=221) explain why pre-ADR-0054 quality means
      inflated: 89% of the unanswerable subset got vacuous-truth 1.0s folded
      into groundedness / citation_precision / answer_format_compliance.
      Post-ADR-0054 the quality means are computed on the substantive subset
      only, so this field is a *transparency signal*, not a metric.
    * ``num_predictions`` — int | None. Total cases the run scored.
    * ``effective_n`` — int | None. Approximate count of substantive answer
      attempts (= ``num_predictions - n_unanswerable``). Computed from the
      ``abstention_outcomes`` 3-bin (PR #464) when available. This is the
      denominator for the quality metrics under ADR 0054.

    Per ADR 0054 §Consequences: these fields are surfaced for transparency
    only. ``signal_alive`` is computed strictly from the GAUGED_METRICS and
    is NOT modified by abstention_rate — the scorer fix (eval/scorers/case.py)
    is the primary defense; this gauge transparency is the secondary one.
    """
    abstention_rate = _safe_metric(run, "abstention")
    num_predictions = run.get("num_predictions")
    if not isinstance(num_predictions, int):
        num_predictions = None
    outcomes = run.get("abstention_outcomes") or {}
    n_unanswerable: int | None
    if isinstance(outcomes, dict) and outcomes:
        try:
            n_unanswerable = sum(int(v) for v in outcomes.values() if v is not None)
        except (TypeError, ValueError):
            n_unanswerable = None
    else:
        n_unanswerable = None
    if num_predictions is not None and n_unanswerable is not None:
        effective_n: int | None = max(num_predictions - n_unanswerable, 0)
    else:
        effective_n = None
    return {
        "abstention_rate": abstention_rate,
        "num_predictions": num_predictions,
        "effective_n": effective_n,
    }


def _safe_ci(run: dict[str, Any], metric: str) -> dict[str, float] | None:
    """Pull a metric's bootstrap CI ``{ci_lo, ci_hi}`` from an ablation run.

    The eval_summary writes a per-run ``ci`` block keyed by metric name, each
    value ``{mean, ci_lo, ci_hi, n, num_resamples, alpha}`` (eval/bootstrap.py).
    Returns ``None`` (rather than raising) when the block, the metric, or either
    bound is absent — the gauge then reports CI separation as ``n/a`` for that
    metric instead of over-claiming ``alive``.
    """
    ci = run.get("ci")
    if not isinstance(ci, dict):
        return None
    block = ci.get(metric)
    if not isinstance(block, dict):
        return None
    lo = block.get("ci_lo")
    hi = block.get("ci_hi")
    if lo is None or hi is None:
        return None
    try:
        return {"ci_lo": float(lo), "ci_hi": float(hi)}
    except (TypeError, ValueError):
        return None


def _ci_separated(
    default_ci: dict[str, float] | None, floor_ci: dict[str, float] | None
) -> bool | None:
    """Is the default CI strictly above the floor CI?

    Returns ``True`` when ``default.ci_lo > floor.ci_hi`` (the two 95% CIs do
    not overlap and the default is the higher one), ``False`` when they overlap
    or the default is below, and ``None`` when either CI is missing — the
    "cannot verify separation" state. This is a deliberately conservative
    non-overlap test (stricter than a paired-difference test) per ADR 0053's
    noise-aware framing.
    """
    if not default_ci or not floor_ci:
        return None
    return default_ci["ci_lo"] > floor_ci["ci_hi"]


def _signal_state(vs_random: dict[str, Any], vs_single: dict[str, Any]) -> str:
    """Derive the 3-state distinguishing-power verdict for one metric.

    States (ADR 0053 §Consequences, CI-aware amendment):

    * ``n/a``       — a floor is missing this metric (gap is ``None``).
    * ``dead``      — default at or below a floor on the point estimate
                      (``gap <= 0``). The Goodhart warning state.
    * ``alive``     — default beats both floors AND its CI is strictly above
                      both floors' CIs (separated). The only state that licenses
                      a "distinguishing power" claim in README / portfolio.
    * ``uncertain`` — default beats both floors on the point estimate but at
                      least one CI overlaps (or is missing). Positive but not
                      yet distinguishable from noise.
    """
    gr = vs_random["gap"]
    gs = vs_single["gap"]
    if gr is None or gs is None:
        return "n/a"
    if gr <= 0 or gs <= 0:
        return "dead"
    if vs_random["ci_separated"] is True and vs_single["ci_separated"] is True:
        return "alive"
    return "uncertain"


def _gauge_row(default: float | None, floor: float | None) -> dict[str, Any]:
    """Compute the raw gap + normalized headroom score for one (metric, floor).

    ``normalized`` is the ADR 0053 §Consequences formula::

        score = (default - floor) / (1 - floor)

    which is the fraction of the remaining headroom-above-floor (ceiling
    of 1.0 assumed since these are all 0..1 rates) that the default occupies.
    A score > 0 means the default beats the floor; ≤ 0 means the default is
    at or below the floor — the "signal is dead" warning state.

    Returns ``{"gap": None, "normalized": None}`` if either input is missing
    or if ``floor == 1`` (degenerate denominator).
    """
    if default is None or floor is None:
        return {"gap": None, "normalized": None}
    gap = default - floor
    denom = 1.0 - floor
    if denom <= 0:
        return {"gap": gap, "normalized": None}
    return {"gap": gap, "normalized": gap / denom}


def compute_gauge(summary: dict[str, Any]) -> dict[str, Any]:
    """Compute the full distinguishing-power gauge from a loaded summary.

    Returns a JSON-serializable dict with this structure::

        {
          "num_predictions": int,
          "provenance":   {git_commit, git_dirty, generated_at} | None,
          "run_manifest": {git_commit, config_sha256, ...}        | None,
          "runs": {
            "full":             {"accuracy": 0.297, ...},
            "random_retrieval": {"accuracy": 0.025, ...},
            "single_chunk":     {"accuracy": 0.068, ...},
          },
          "gauge": {
            "accuracy": {
              "default":      0.297,
              "default_ci":   {"ci_lo": 0.21, "ci_hi": 0.38} | None,
              "vs_random":    {"gap": 0.272, "normalized": 0.279,
                               "floor_ci": {...} | None, "ci_separated": True},
              "vs_single":    {"gap": 0.229, "normalized": 0.245,
                               "floor_ci": {...} | None, "ci_separated": True},
              "signal_state": "alive",  # alive | uncertain | dead | n/a
              "signal_alive": True,     # == (signal_state == "alive")
            },
            ...
          }
        }

    ``signal_alive`` is CI-aware (ADR 0053 amendment): it is ``True`` only when
    the default's 95% CI is strictly above both floors' CIs. A positive point
    gap whose CI overlaps a floor yields ``signal_state == "uncertain"`` and
    ``signal_alive == False`` — the gauge no longer over-claims on noise.
    """
    runs = _runs_by_name(summary)
    default = runs[DEFAULT_RUN]
    random_run = runs["random_retrieval"]
    single_run = runs["single_chunk"]
    n = default.get("num_predictions") or summary.get("num_predictions")

    out_runs = {
        name: {
            **{m: _safe_metric(runs[name], m) for m in GAUGED_METRICS},
            # ADR 0054 — per-(metric, run) CI denominator. The quality metrics
            # are conditional on a substantive answer attempt, so their n
            # diverges from answer_format_compliance / claim_citation_alignment;
            # surfacing it here keeps that divergence from being hidden behind a
            # single per-run effective_n. See _safe_metric_n.
            "metric_n": {m: _safe_metric_n(runs[name], m) for m in GAUGED_METRICS},
            # ADR 0054 — transparency fields next to metrics so a reader can
            # see at a glance why a high-abstention run's pre-fix means were
            # inflated. These are independent of signal_state (which is driven
            # by GAUGED_METRICS + their CIs only).
            **_safe_abstention(runs[name]),
        }
        for name in REQUIRED_RUNS
    }
    gauge: dict[str, Any] = {}
    for metric in GAUGED_METRICS:
        d = _safe_metric(default, metric)
        r = _safe_metric(random_run, metric)
        s = _safe_metric(single_run, metric)
        d_ci = _safe_ci(default, metric)
        vs_random = {
            **_gauge_row(d, r),
            "floor_ci": _safe_ci(random_run, metric),
            "ci_separated": None,
        }
        vs_random["ci_separated"] = _ci_separated(d_ci, vs_random["floor_ci"])
        vs_single = {
            **_gauge_row(d, s),
            "floor_ci": _safe_ci(single_run, metric),
            "ci_separated": None,
        }
        vs_single["ci_separated"] = _ci_separated(d_ci, vs_single["floor_ci"])
        state = _signal_state(vs_random, vs_single)
        gauge[metric] = {
            "default": d,
            "default_ci": d_ci,
            "vs_random": vs_random,
            "vs_single": vs_single,
            "signal_state": state,
            "signal_alive": state == "alive",
        }
    return {
        "num_predictions": n,
        "provenance": summary.get("provenance"),
        "run_manifest": summary.get("run_manifest"),
        "runs": out_runs,
        "gauge": gauge,
    }


def check_provenance_skew(
    gauge: dict[str, Any], head_provenance: dict[str, Any] | None = None
) -> list[str]:
    """Return human-readable warnings about source-vs-HEAD provenance skew.

    The committed gauge aggregate is derived from a private (gitignored)
    eval_summary, so a reviewer cannot otherwise tell which commit / dirty
    state produced the numbers (issue #1367 F2). This mirrors the
    baseline-provenance guard (pr-eval.yml, #160/#413) at the gauge surface:

    * no ``provenance`` block → cannot verify at all.
    * source ``git_commit`` != current HEAD → numbers are stale relative to HEAD.
    * source ``git_dirty`` → numbers may include uncommitted changes.

    ``head_provenance`` is injectable for tests; defaults to the current HEAD
    via ``build_provenance()``.
    """
    warnings: list[str] = []
    prov = gauge.get("provenance") or {}
    src_commit = prov.get("git_commit")
    if not src_commit:
        warnings.append(
            "source eval_summary has no provenance block — cannot verify which "
            "commit produced these numbers. Regenerate with `make real-eval` on "
            "a clean checkout of a known HEAD."
        )
        return warnings
    head = head_provenance or build_provenance()
    head_commit = str(head.get("git_commit"))
    if str(src_commit) != head_commit:
        warnings.append(
            f"provenance skew — gauge numbers were produced at {src_commit} but "
            f"current HEAD is {head_commit}. Regenerate on a clean checkout of HEAD."
        )
    if prov.get("git_dirty"):
        warnings.append(
            f"source run at {src_commit} was git_dirty=True — numbers may include "
            f"uncommitted changes (regenerate from a clean tree)."
        )
    return warnings


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _fmt_pp(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.2f}pp"


def _fmt_ci(ci: dict[str, float] | None) -> str:
    if not ci:
        return "n/a"
    return f"[{ci['ci_lo'] * 100:.1f}, {ci['ci_hi'] * 100:.1f}]"


def _fmt_sep(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def render_markdown(gauge: dict[str, Any]) -> str:
    """Render the gauge as a markdown report.

    Layout:
    * Header with ``num_predictions``
    * Raw ablation table (3 columns: full / random / single_chunk)
    * Distinguishing-power gauge table (vs each floor)
    * One-line verdict per metric
    """
    n = gauge["num_predictions"]
    prov = gauge.get("provenance") or {}
    if prov.get("git_commit"):
        prov_line = (
            f"source: `{prov.get('git_commit')}` "
            f"(git_dirty={prov.get('git_dirty')}) · generated_at {prov.get('generated_at')}"
        )
    else:
        prov_line = "source: _provenance unavailable — regenerate via `make real-eval` (issue #1367 F2)._"
    lines: list[str] = [
        "# Distinguishing-power gauge (real-eval, ADR 0053 §Consequences)",
        "",
        f"`num_predictions = {n}` · 3 ablation_runs: `full` / `random_retrieval` / `single_chunk`",
        "",
        prov_line,
        "",
        "`signal` is CI-aware (ADR 0053 amendment, issue #1367): `alive` only when the "
        "default's 95% CI is strictly above **both** floors' CIs; a positive point gap "
        "with overlapping CI is `uncertain`, not `alive`.",
        "",
        "Per ADR 0053 §Consequences:",
        "> PR-5b's `scripts/distinguishing_power.py` can compute "
        "`(default - floor) / (ceiling - floor)` for every leaderboard metric "
        "— a single-number 'is the signal alive' gauge.",
        "",
        "## Ablation raw values",
        "",
        "| metric | full | random_retrieval | single_chunk |",
        "|---|---:|---:|---:|",
    ]
    for metric in GAUGED_METRICS:
        row = [metric]
        for run_name in REQUIRED_RUNS:
            run = gauge["runs"][run_name]
            cell = _fmt_pct(run[metric])
            n = run.get("metric_n", {}).get(metric)
            if n is not None:
                cell += f" (n={n})"
            row.append(cell)
        lines.append("| " + " | ".join(row) + " |")

    # ADR 0054 — disclose the per-(metric, run) denominator divergence so the
    # single per-run effective_n below is not read as a shared denominator.
    lines += [
        "",
        "_Per-cell `n` = CI denominator for that (metric, run). Quality metrics "
        "(`accuracy` / `groundedness` / `citation_precision`) are conditional on a "
        "substantive answer attempt (ADR 0054) and so share the smaller "
        "`effective_n` below. `answer_format_compliance` and "
        "`claim_citation_alignment` stay measurable on over-answered / answered "
        "cases (format and alignment need no gold), so their `n` is larger and "
        "differs per run — disclosed per-cell here, not folded into one denominator. "
        "Each `gap vs floor` therefore compares means on per-metric denominators, "
        "not a single shared `n`._",
    ]

    # ADR 0054 §Consequences — transparency block. Surfaces per-run
    # abstention_rate (correct-refusal rate on the unanswerable subset)
    # + effective_n (substantive-attempt count, ≈ the denominator for
    # accuracy/groundedness/citation_precision only — answer_format_compliance
    # and claim_citation_alignment use the larger per-metric n shown per-cell
    # in the raw-values table above). Helps a reader see why a high-abstention
    # run's quality means are based on a small denominator. signal_alive is
    # NOT influenced by these numbers.
    lines += [
        "",
        "## Per-run abstention transparency (ADR 0054)",
        "",
        "| run | num_predictions | abstention_rate (unanswerable subset) | effective_n (≈ accuracy/groundedness/citation_precision denom) |",
        "|---|---:|---:|---:|",
    ]
    for run_name in REQUIRED_RUNS:
        r = gauge["runs"][run_name]
        n_pred = r.get("num_predictions")
        eff_n = r.get("effective_n")
        lines.append(
            "| " + " | ".join([
                run_name,
                str(n_pred) if n_pred is not None else "n/a",
                _fmt_pct(r.get("abstention_rate")),
                str(eff_n) if eff_n is not None else "n/a",
            ]) + " |"
        )

    lines += [
        "",
        "## Gauge — default vs floors (CI-aware)",
        "",
        "| metric | default | default 95% CI | gap vs random | CI-sep vs random | gap vs single_chunk | CI-sep vs single_chunk | signal |",
        "|---|---:|---:|---:|:---:|---:|:---:|:---:|",
    ]
    for metric in GAUGED_METRICS:
        g = gauge["gauge"][metric]
        row = [
            metric,
            _fmt_pct(g["default"]),
            _fmt_ci(g.get("default_ci")),
            _fmt_pp(g["vs_random"]["gap"]),
            _fmt_sep(g["vs_random"].get("ci_separated")),
            _fmt_pp(g["vs_single"]["gap"]),
            _fmt_sep(g["vs_single"].get("ci_separated")),
            g["signal_state"],
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "## Verdict",
        "",
    ]
    for metric in GAUGED_METRICS:
        g = gauge["gauge"][metric]
        state = g["signal_state"]
        if state == "alive":
            lines.append(
                f"- **{metric}**: signal alive — default's CI is strictly above "
                f"both floors ({_fmt_pp(g['vs_random']['gap'])} vs random, "
                f"{_fmt_pp(g['vs_single']['gap'])} vs single_chunk; CIs non-overlapping)."
            )
        elif state == "n/a":
            lines.append(
                f"- **{metric}**: n/a — one or both floors missing this metric."
            )
        elif state == "uncertain":
            lines.append(
                f"- **{metric}**: ⚠️ signal uncertain — default beats both floors on "
                f"the point estimate ({_fmt_pp(g['vs_random']['gap'])} vs random, "
                f"{_fmt_pp(g['vs_single']['gap'])} vs single_chunk) but its 95% CI "
                f"overlaps at least one floor (not CI-separated). Not yet "
                f"distinguishable from noise."
            )
        else:  # dead
            lines.append(
                f"- **{metric}**: ⚠️ signal NOT alive — default does not beat "
                f"both floors ({_fmt_pp(g['vs_random']['gap'])} vs random, "
                f"{_fmt_pp(g['vs_single']['gap'])} vs single_chunk). "
                f"Retrieval or pipeline not pulling weight on this metric."
            )
    lines.append("")
    lines.append(
        "_Aggregate-only per ADR 0005. No per-case data is read by this script._"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="Path to eval_summary.json (default: %(default)s)",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=DEFAULT_OUT_MD,
        help="Path to markdown output (default: %(default)s)",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_OUT_JSON,
        help="Path to JSON aggregate output (default: %(default)s)",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print markdown to stdout, do not write files.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if the source eval_summary is stale relative to the "
        "current HEAD or was produced from a dirty tree (provenance skew, #1367 F2).",
    )
    args = parser.parse_args(argv)

    summary = _load_summary(args.summary)
    gauge = compute_gauge(summary)
    md = render_markdown(gauge)

    skew_warnings = check_provenance_skew(gauge)
    for warning in skew_warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    if args.strict and skew_warnings:
        print(
            "[ERROR] --strict: provenance skew detected (see warnings above). "
            "Refusing to write stale gauge artifacts.",
            file=sys.stderr,
        )
        return 1

    if args.print_only:
        sys.stdout.write(md)
        return 0

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(md)
    args.out_json.write_text(json.dumps(gauge, indent=2, sort_keys=True))
    print(f"[OK] Wrote {args.out_md}")
    print(f"[OK] Wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
