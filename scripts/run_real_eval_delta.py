#!/usr/bin/env python3
"""Aggregate-only delta between two real-data eval summaries.

Designed for the **private real-data surface only**. The script:

1. Reads the current run (`reports/real100/eval_summary.json` by
   default) and a committed baseline snapshot
   (`reports/real100/baseline.aggregate.json`).
2. Extracts an explicit allow-list of **aggregate-only fields** — no
   `case_results`, no `query` text, no per-case `evidence`, no
   `doc_id`. The extractor refuses to even look at forbidden keys, so
   schema drift cannot accidentally leak per-case content into the
   committable diff.
3. Renders a markdown delta table to stdout for the contributor to
   paste into the PR body (or for the optional Decision Log stub
   appender to use).

This is the structural mechanism behind ADR 0005's commit boundary
on the contributor side: aggregates are committable, anything
case-level is not.

CLI:

    python3 scripts/run_real_eval_delta.py \
        --head reports/real100/eval_summary.json \
        --base reports/real100/baseline.aggregate.json \
        [--title "Real-data delta — #NN"] \
        [--write-decision-log-stub]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Issue #473: share the silence-band + formatting helpers with
# scripts/_eval_delta.py rather than carrying parallel copies. The
# sys.path insert mirrors scripts/compare_eval.py so the same module
# resolves whether the script is invoked as `python3 scripts/run_real_eval_delta.py`
# or imported as `scripts.run_real_eval_delta` (the test suite does both).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eval_delta import (  # noqa: E402
    fmt_delta as _fmt_delta,
    fmt_value as _fmt_value,
    get_path as _get_path,
    min_num_predictions as _min_num_predictions_shared,
    silence_threshold as _silence_threshold,
)


def _min_num_predictions(base: dict[str, Any], head: dict[str, Any]) -> int | None:
    """Thin wrapper around :func:`_eval_delta.min_num_predictions`.

    Kept as a module-private name so callers and tests can keep using
    the underscore-prefixed identifier they already imported.
    """
    return _min_num_predictions_shared(base, head)

# Top-level aggregate keys that are safe to commit. Anything else in
# the input JSONs is ignored. Keep this list intentionally narrow —
# adding a key requires a privacy review.
SAFE_TOPLEVEL_KEYS = frozenset(
    {
        "num_predictions",
        "accuracy",
        "groundedness",
        "citation_precision",
        "citation_grounding",
        "claim_citation_alignment",
        "answer_format_compliance",
        "abstention",
        "retry",
        "latency",  # only sub-keys "p50", "p95", "mean" extracted below
        "stage_latency",  # aggregated p50/p95/mean per stage
        "retry_reason_counts",  # reason strings are non-identifying
        # Issue #120: retry effectiveness aggregates. All sub-fields are
        # counts/rates over the case set with no per-case payload; the
        # extractor below whitelists the exact sub-keys.
        "retry_effectiveness",
        # Run identity for leaderboard (#166) + judge calibration (#169).
        # Only git_commit / git_dirty / config_sha256 / generated_at cross
        # the commit boundary — the local filesystem path is dropped.
        "run_manifest",
        "pipeline",
        "primary_run",
        "prompt_profile",
        "top_k",
        # Run-state metadata (no per-case content). Surfaces eval-vs-baseline
        # commit skew in the rendered delta — see issue #160. Sub-keys are
        # git_commit (12-char SHA), git_dirty (bool), generated_at (ISO 8601).
        "provenance",
        # LLM-judge aggregates (ADR 0006). Only status_distribution /
        # grounded_rate / agreement_with_verifier / n cross the commit
        # boundary; per-case judge text stays in
        # reports/real100/judge.local.json.
        "judge",
        # ADR 0012 RAGAS-style judge aggregates on the synthetic surface.
        # Only the four metric means + their 95% bootstrap CIs cross the
        # commit boundary; per-case verdicts stay in
        # reports/eval_summary.judge.local.json and reports/judge_cache/.
        "judge_ragas",
        # Bootstrap 95% CI per headline metric (issue #166 / #267 leaderboard).
        # The block is {metric: {mean, ci_lo, ci_hi, n, num_resamples, alpha}};
        # the extractor below whitelists both the metric and sub-key sets.
        "ci",
        # Issue #463: integer counts decomposing intended-abstention cases
        # into 3 outcome bins. The extractor whitelists the bin names below
        # and casts to int — no per-case text crosses the boundary.
        "abstention_outcomes",
        # Issue #476 / ADR 0029: headline metrics of the `agentic_full`
        # ablation run, surfaced so the synthetic leaderboard renders the
        # `full` pipeline as a parallel time series alongside `naive_baseline`.
        # The extractor below explicitly whitelists each scalar + the
        # CI sub-block; case-level fields are dropped.
        "ablation_full",
        # Issue #650 / ADR 0039: per-format accuracy breakdown keyed by
        # document source_format (hwp / pdf / synthetic_public_sample).
        # Bucket keys are whitelisted in SAFE_FORMAT_BUCKET_KEYS (fail-closed);
        # metric sub-keys mirror SAFE_ABLATION_FULL_SCALAR_KEYS; no per-case
        # payload crosses the boundary.
        "by_format",
    }
)

# Allowed bucket keys inside ``by_format``. Fail-closed: any key not in
# this set is silently dropped before the aggregate is committed.
SAFE_FORMAT_BUCKET_KEYS = frozenset({"hwp", "pdf", "synthetic_public_sample"})

# Whitelisted bin names for ``abstention_outcomes``. Integer counts only.
SAFE_ABSTENTION_OUTCOME_KEYS = ("correct_refusal", "incorrect_answer", "boundary_partial")

# Headline scalars allowed inside ``ablation_full``. Mirrors the top-level
# scalar inventory (run_eval.py:838-847) so the two surfaces never carry
# different metric sets.
SAFE_ABLATION_FULL_SCALAR_KEYS = (
    "num_predictions",
    "accuracy",
    "groundedness",
    "citation_precision",
    "citation_grounding",
    "claim_citation_alignment",
    "answer_format_compliance",
    "abstention",
    "retry",
)

# Headline metrics whose bootstrap CI is allowed to round-trip the
# extractor. Mirrors the scalar metrics already whitelisted at the top
# level (run_eval.py:1213) so `aggregate.json` and `aggregate.json["ci"]`
# can never carry different metric inventories.
SAFE_CI_METRIC_KEYS = (
    "accuracy",
    "groundedness",
    "citation_precision",
    "citation_page_precision",
    "citation_region_precision",
    "citation_grounding",
    "claim_citation_alignment",
    "answer_format_compliance",
    "abstention",
    "retry",
    # Comparison-aware retrieval metrics (run_eval.py:1273-1279) — only
    # populated when the eval includes comparison cases.
    "comparison_target_recall",
    "comparison_pool_recall",
)
SAFE_CI_SUB_KEYS = ("mean", "ci_lo", "ci_hi", "n", "num_resamples", "alpha")

# RAGAS metric sub-keys whitelisted from `judge_ragas`. Float scalars + CI dicts.
SAFE_JUDGE_RAGAS_METRIC_KEYS = (
    "faithfulness",
    "answer_relevance",
    "context_precision",
    "context_recall",
)
SAFE_JUDGE_RAGAS_META_KEYS = ("n", "ci")

# Sub-keys whitelisted from `retry_effectiveness` — all numeric or count
# aggregates over the case set, no per-case payload.
SAFE_RETRY_EFFECTIVENESS_KEYS = (
    "cases_with_retry",
    "cases_without_retry",
    "recovery_rate",
    "residual_failure_rate",
    "retry_resolution_rate",
    "retry_lift_vs_no_retry",
)
SAFE_RETRY_EFFECTIVENESS_CROSS_KEYS = (
    "n_retry_triggered",
    "n_evaluable",
    "true_positive_triggers",
    "false_positive_triggers",
    "retry_precision",
    "method",
)
SAFE_RETRY_EFFECTIVENESS_CI_KEYS = ("recovery_rate", "residual_failure_rate")

# Sub-keys whitelisted from `run_manifest`. ``config_path`` is dropped
# (filesystem layout is not committable); ``config_sha256`` is the
# canonical config identifier.
SAFE_RUN_MANIFEST_KEYS = ("git_commit", "git_dirty", "config_sha256", "generated_at")

# Per-slice subkeys extracted from `by_query_type`.
SAFE_SLICE_METRICS = (
    "num_predictions",
    "accuracy",
    "groundedness",
    "abstention",
    "abstention_outcomes",
    "answer_format_compliance",
)

# Keys that must never be read or written by this script. The
# extractor asserts none of these are present in its output as a
# defense against schema drift.
FORBIDDEN_KEYS = frozenset(
    {
        "case_results",
        "query",
        "answer",
        "answer_text",
        "evidence",
        "expected_doc_ids",
        "expected_terms",
        "expected_citation_terms",
        "expected_citation_pages",
        "expected_citation_regions",
        "expected_claim_citations",
        "evidence_doc_ids",
        "metadata_selected_doc_ids",
        "doc_id",
        "chunk_id",
        "resolved_query",
    }
)

# Metric direction for the rendered delta arrow.
# (path, label, higher_is_better)
METRICS: list[tuple[str, str, bool]] = [
    ("accuracy", "accuracy", True),
    ("groundedness", "groundedness", True),
    ("citation_precision", "citation_precision", True),
    ("citation_grounding", "citation_grounding", True),
    ("claim_citation_alignment", "claim_citation_alignment", True),
    ("answer_format_compliance", "answer_format_compliance", True),
    ("abstention", "abstention (intended)", True),
    ("retry", "retry_rate", False),
    ("latency.p50", "latency_p50_ms", False),
    ("latency.p95", "latency_p95_ms", False),
]


# -----------------------------------------------------------------------------
# Extraction
# -----------------------------------------------------------------------------


def _extract_ablation_full(run_summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ADR 0005-safe headline metrics for one ablation run.

    Used by :func:`extract_aggregate` to fold the `name == "full"` run
    out of ``eval_summary.json::ablation.runs[]`` into a top-level
    ``ablation_full`` key. Sub-keys are explicitly whitelisted: scalar
    metrics, the latency p50/p95/mean, the 3-bin abstention outcomes,
    and the bootstrap CI sub-block — same defense-in-depth pattern as
    `judge_ragas` (ADR 0012) and `retry_effectiveness` (#120). Case-level
    fields and per-attempt latencies are dropped.
    """
    if not isinstance(run_summary, dict):
        return None
    out: dict[str, Any] = {}
    for key in SAFE_ABLATION_FULL_SCALAR_KEYS:
        value = run_summary.get(key)
        if value is not None:
            out[key] = value
    latency = run_summary.get("latency")
    if isinstance(latency, dict):
        out["latency"] = {
            sub: latency.get(sub)
            for sub in ("p50", "p95", "mean")
            if latency.get(sub) is not None
        }
    outcomes = run_summary.get("abstention_outcomes")
    if isinstance(outcomes, dict):
        bin_out = {
            sub: int(outcomes[sub])
            for sub in SAFE_ABSTENTION_OUTCOME_KEYS
            if isinstance(outcomes.get(sub), (int, float))
        }
        if bin_out:
            out["abstention_outcomes"] = bin_out
    ci = run_summary.get("ci")
    if isinstance(ci, dict):
        ci_out: dict[str, Any] = {}
        for metric in SAFE_CI_METRIC_KEYS:
            metric_ci = ci.get(metric)
            if not isinstance(metric_ci, dict):
                continue
            trimmed = {
                sub: metric_ci.get(sub)
                for sub in SAFE_CI_SUB_KEYS
                if metric_ci.get(sub) is not None
            }
            if trimmed:
                ci_out[metric] = trimmed
        if ci_out:
            out["ci"] = ci_out
    return out or None


def extract_aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a dict containing only ADR-0005-safe aggregate fields.

    Anything outside :data:`SAFE_TOPLEVEL_KEYS` is dropped. The output
    is then re-validated against :data:`FORBIDDEN_KEYS` as a guard
    against silent schema drift; an :class:`AssertionError` is raised
    if a forbidden key somehow makes it through.
    """
    if not isinstance(summary, dict):
        raise ValueError("Eval summary must be a JSON object.")

    out: dict[str, Any] = {}
    for key in SAFE_TOPLEVEL_KEYS:
        if key not in summary:
            continue
        value = summary[key]
        if key == "latency" and isinstance(value, dict):
            out[key] = {
                sub: value.get(sub)
                for sub in ("p50", "p95", "mean")
                if value.get(sub) is not None
            }
        elif key == "stage_latency" and isinstance(value, dict):
            # value is {stage_name: {p50,p95,mean,count}}
            out[key] = {
                stage: {k: v.get(k) for k in ("p50", "p95", "mean") if v.get(k) is not None}
                for stage, v in value.items()
                if isinstance(v, dict)
            }
        elif key == "retry_reason_counts" and isinstance(value, dict):
            # Reason strings are taxonomy codes ("topic_not_grounded"), not
            # identifying. Counts are integers. Safe.
            out[key] = {str(k): int(v) for k, v in value.items()}
        elif key == "retry_effectiveness" and isinstance(value, dict):
            extracted: dict[str, Any] = {
                sub: value.get(sub)
                for sub in SAFE_RETRY_EFFECTIVENESS_KEYS
                if value.get(sub) is not None
            }
            ci = value.get("ci")
            if isinstance(ci, dict):
                ci_out = {
                    sub: ci.get(sub)
                    for sub in SAFE_RETRY_EFFECTIVENESS_CI_KEYS
                    if isinstance(ci.get(sub), dict)
                }
                if ci_out:
                    extracted["ci"] = ci_out
            cross = value.get("cross_ablation")
            if isinstance(cross, dict):
                cross_out = {
                    sub: cross.get(sub)
                    for sub in SAFE_RETRY_EFFECTIVENESS_CROSS_KEYS
                    if cross.get(sub) is not None
                }
                if cross_out:
                    extracted["cross_ablation"] = cross_out
            if extracted:
                out[key] = extracted
        elif key == "ablation_full" and isinstance(value, dict):
            extracted = _extract_ablation_full(value)
            if extracted:
                out[key] = extracted
        elif key == "abstention_outcomes" and isinstance(value, dict):
            bin_out = {
                sub: int(value[sub])
                for sub in SAFE_ABSTENTION_OUTCOME_KEYS
                if isinstance(value.get(sub), (int, float))
            }
            if bin_out:
                out[key] = bin_out
        elif key == "ci" and isinstance(value, dict):
            ci_out: dict[str, Any] = {}
            for metric in SAFE_CI_METRIC_KEYS:
                metric_ci = value.get(metric)
                if not isinstance(metric_ci, dict):
                    continue
                trimmed = {
                    sub: metric_ci.get(sub)
                    for sub in SAFE_CI_SUB_KEYS
                    if metric_ci.get(sub) is not None
                }
                if trimmed:
                    ci_out[metric] = trimmed
            if ci_out:
                out[key] = ci_out
        elif key == "run_manifest" and isinstance(value, dict):
            # Drop config_path (filesystem layout, not committable).
            # Keep git_commit / git_dirty / config_sha256 / generated_at.
            out[key] = {
                sub: value.get(sub)
                for sub in SAFE_RUN_MANIFEST_KEYS
                if value.get(sub) is not None
            }
        elif key == "judge_ragas" and isinstance(value, dict):
            ragas: dict[str, Any] = {}
            for metric in SAFE_JUDGE_RAGAS_METRIC_KEYS:
                if value.get(metric) is not None:
                    ragas[metric] = value[metric]
            for meta in SAFE_JUDGE_RAGAS_META_KEYS:
                if meta == "ci" and isinstance(value.get(meta), dict):
                    ragas[meta] = {
                        m: value[meta].get(m)
                        for m in SAFE_JUDGE_RAGAS_METRIC_KEYS
                        if isinstance(value[meta].get(m), dict)
                    }
                elif value.get(meta) is not None:
                    ragas[meta] = value[meta]
            if ragas:
                out[key] = ragas
        else:
            out[key] = value

    # Issue #476 / ADR 0029: when fed a raw eval_summary.json (i.e. the
    # `ablation.runs[]` shape rather than the aggregate-form `ablation_full`
    # key), pull the `full` run's headline metrics into our schema. This
    # is what `scripts/write_synthetic_history.py` relies on so its writer
    # stays a one-liner: it just hands the raw summary to extract_aggregate
    # and the surface conversion happens here.
    if "ablation_full" not in out:
        ablation = summary.get("ablation")
        if isinstance(ablation, dict):
            runs = ablation.get("runs") or []
            full_run = next(
                (r for r in runs if isinstance(r, dict) and r.get("name") == "full"),
                None,
            )
            if full_run is not None:
                extracted = _extract_ablation_full(full_run)
                if extracted:
                    out["ablation_full"] = extracted

    by_query_type = summary.get("by_query_type")
    if isinstance(by_query_type, dict):
        slice_out: dict[str, dict[str, Any]] = {}
        for slice_name, slice_summary in by_query_type.items():
            if not isinstance(slice_summary, dict):
                continue
            extracted_slice: dict[str, Any] = {}
            for m in SAFE_SLICE_METRICS:
                raw = slice_summary.get(m)
                if raw is None:
                    continue
                if m == "abstention_outcomes" and isinstance(raw, dict):
                    bin_out = {
                        sub: int(raw[sub])
                        for sub in SAFE_ABSTENTION_OUTCOME_KEYS
                        if isinstance(raw.get(sub), (int, float))
                    }
                    if bin_out:
                        extracted_slice[m] = bin_out
                else:
                    extracted_slice[m] = raw
            slice_out[str(slice_name)] = extracted_slice
        out["by_query_type"] = slice_out

    # Issue #650 / ADR 0039 — by_format aggregate. Fail-closed: only bucket
    # keys in SAFE_FORMAT_BUCKET_KEYS are retained; unknown formats are dropped
    # so new source_format values added to fixtures cannot leak payload.
    by_format = summary.get("by_format")
    if isinstance(by_format, dict):
        format_out: dict[str, dict[str, Any]] = {}
        for bucket_name, bucket_summary in by_format.items():
            if str(bucket_name) not in SAFE_FORMAT_BUCKET_KEYS:
                continue
            if not isinstance(bucket_summary, dict):
                continue
            extracted_bucket: dict[str, Any] = {}
            for m in SAFE_SLICE_METRICS:
                raw = bucket_summary.get(m)
                if raw is None:
                    continue
                if m == "abstention_outcomes" and isinstance(raw, dict):
                    bin_out = {
                        sub: int(raw[sub])
                        for sub in SAFE_ABSTENTION_OUTCOME_KEYS
                        if isinstance(raw.get(sub), (int, float))
                    }
                    if bin_out:
                        extracted_bucket[m] = bin_out
                else:
                    extracted_bucket[m] = raw
            if extracted_bucket:
                format_out[str(bucket_name)] = extracted_bucket
        if format_out:
            out["by_format"] = format_out

    _assert_no_forbidden(out)
    return out


def _assert_no_forbidden(obj: Any, path: str = "") -> None:
    """Recursively assert that no forbidden key appears in the aggregate."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key) in FORBIDDEN_KEYS:
                raise AssertionError(
                    f"Aggregate output contains forbidden key '{key}' at '{path}'. "
                    "This indicates a schema drift in the extractor and would "
                    "violate ADR 0005's commit boundary. Refusing to emit."
                )
            _assert_no_forbidden(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_forbidden(item, f"{path}[{i}]")


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------


def _fmt_ci(summary: dict[str, Any], metric_key: str) -> str:
    """Return `` [ci_lo, ci_hi]`` for the metric or empty string.

    Issue #463: surface the single-run bootstrap CI (already aggregate-
    safe via ADR 0005 whitelist, see ``SAFE_CI_METRIC_KEYS``) next to
    each base/head value so reviewers can eyeball whether a delta sits
    inside the noise band. Dotted paths (``latency.p50``) and metrics
    without a CI block render as empty string and the table falls back
    to bare values.
    """
    if not isinstance(summary, dict) or "." in metric_key:
        return ""
    ci_block = summary.get("ci")
    if not isinstance(ci_block, dict):
        return ""
    metric_ci = ci_block.get(metric_key)
    if not isinstance(metric_ci, dict):
        return ""
    lo = metric_ci.get("ci_lo")
    hi = metric_ci.get("ci_hi")
    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
        return ""
    return f" [{lo:.3f}, {hi:.3f}]"


def render_markdown(
    base: dict[str, Any],
    head: dict[str, Any],
    title: str,
) -> str:
    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("")
    lines.append(
        f"- pipeline: `{head.get('pipeline', '?')}` "
        f"(primary run: `{head.get('primary_run', '?')}`)"
    )
    lines.append(
        f"- cases: base={base.get('num_predictions', '?')} · "
        f"head={head.get('num_predictions', '?')}"
    )
    base_sha = str(((base.get("provenance") or {}).get("git_commit")) or "?")
    head_sha = str(((head.get("provenance") or {}).get("git_commit")) or "?")
    if base_sha != "?" or head_sha != "?":
        lines.append(f"- commits: base=`{base_sha}` · head=`{head_sha}`")
    n_min = _min_num_predictions(base, head)
    if n_min:
        lines.append(
            f"- silence band: ±{_silence_threshold(n_min):.3f} (N={n_min})"
        )
    lines.append("")
    lines.append("| metric | base (95% CI) | head (95% CI) | Δ |")
    lines.append("|---|---|---|---|")
    for path, label, higher in METRICS:
        b = _get_path(base, path)
        h = _get_path(head, path)
        lines.append(
            f"| {label} | {_fmt_value(b)}{_fmt_ci(base, path)} "
            f"| {_fmt_value(h)}{_fmt_ci(head, path)} "
            f"| {_fmt_delta(b, h, higher, n_min=n_min)} |"
        )

    # Slice-level abstention is the most important signal we surfaced
    # from #69 — render it explicitly so future regressions are obvious.
    base_slices = base.get("by_query_type") or {}
    head_slices = head.get("by_query_type") or {}
    slice_names = sorted(set(base_slices) | set(head_slices))
    if slice_names:
        lines.append("")
        lines.append("#### Slice abstention rate (intended-abstention preservation)")
        lines.append("")
        lines.append("| slice | base | head | Δ |")
        lines.append("|---|---|---|---|")
        for name in slice_names:
            b = (base_slices.get(name) or {}).get("abstention")
            h = (head_slices.get(name) or {}).get("abstention")
            lines.append(
                f"| {name} | {_fmt_value(b)} | {_fmt_value(h)} | "
                f"{_fmt_delta(b, h, True, n_min=n_min)} |"
            )

    # Issue #463: 3-bin breakdown so a confident-refusal → hallucination
    # regression and a confident-refusal → boundary-partial regression
    # don't collapse onto the same scalar abstention delta.
    base_outcomes = (base_slices.get("abstention") or {}).get("abstention_outcomes")
    head_outcomes = (head_slices.get("abstention") or {}).get("abstention_outcomes")
    if isinstance(base_outcomes, dict) or isinstance(head_outcomes, dict):
        lines.append("")
        lines.append("#### Abstention outcome breakdown (intended-abstention slice)")
        lines.append("")
        lines.append("| outcome | base | head |")
        lines.append("|---|---:|---:|")
        for outcome_key in SAFE_ABSTENTION_OUTCOME_KEYS:
            b_count = (base_outcomes or {}).get(outcome_key, 0)
            h_count = (head_outcomes or {}).get(outcome_key, 0)
            lines.append(f"| {outcome_key} | {b_count} | {h_count} |")

    base_reasons = base.get("retry_reason_counts") or {}
    head_reasons = head.get("retry_reason_counts") or {}
    if base_reasons or head_reasons:
        lines.append("")
        lines.append("#### Retry reason counts")
        lines.append("")
        lines.append("| reason | base | head |")
        lines.append("|---|---:|---:|")
        for reason in sorted(set(base_reasons) | set(head_reasons)):
            lines.append(
                f"| `{reason}` | {base_reasons.get(reason, 0)} | "
                f"{head_reasons.get(reason, 0)} |"
            )

    base_retry_eff = base.get("retry_effectiveness") or {}
    head_retry_eff = head.get("retry_effectiveness") or {}
    if base_retry_eff or head_retry_eff:
        lines.append("")
        lines.append("#### Retry effectiveness (#120)")
        lines.append("")
        lines.append("| metric | base | head | Δ |")
        lines.append("|---|---|---|---|")
        for key, label, higher in (
            ("recovery_rate", "recovery_rate", True),
            ("residual_failure_rate", "residual_failure_rate", False),
            ("retry_resolution_rate", "retry_resolution_rate", True),
            ("retry_lift_vs_no_retry", "retry_lift_vs_no_retry", True),
        ):
            b = base_retry_eff.get(key)
            h = head_retry_eff.get(key)
            lines.append(
                f"| {label} | {_fmt_value(b)} | {_fmt_value(h)} | "
                f"{_fmt_delta(b, h, higher, n_min=n_min)} |"
            )
        base_cross = base_retry_eff.get("cross_ablation") or {}
        head_cross = head_retry_eff.get("cross_ablation") or {}
        if base_cross or head_cross:
            lines.append("")
            lines.append(
                "_Cross-ablation retry_precision (vs no_verifier_retry baseline): "
                f"base={_fmt_value(base_cross.get('retry_precision'))} · "
                f"head={_fmt_value(head_cross.get('retry_precision'))} · "
                f"method=`{head_cross.get('method') or base_cross.get('method', '—')}`_"
            )

    base_ragas = base.get("judge_ragas") or {}
    head_ragas = head.get("judge_ragas") or {}
    if base_ragas or head_ragas:
        lines.append("")
        lines.append("#### RAGAS judge (ADR 0012, opt-in)")
        lines.append("")
        lines.append("| metric | base | head | Δ |")
        lines.append("|---|---|---|---|")
        for metric in SAFE_JUDGE_RAGAS_METRIC_KEYS:
            b = base_ragas.get(metric)
            h = head_ragas.get(metric)
            lines.append(
                f"| {metric} | {_fmt_value(b)} | {_fmt_value(h)} | "
                f"{_fmt_delta(b, h, True, n_min=n_min)} |"
            )

    base_judge = base.get("judge") or {}
    head_judge = head.get("judge") or {}
    if base_judge or head_judge:
        lines.append("")
        lines.append("#### LLM-judge aggregate (ADR 0006)")
        lines.append("")
        lines.append("| metric | base | head | Δ |")
        lines.append("|---|---|---|---|")
        for key, label, higher in (
            ("grounded_rate", "judge_grounded_rate", True),
            ("agreement_with_verifier", "agreement_with_verifier", True),
        ):
            b = base_judge.get(key)
            h = head_judge.get(key)
            lines.append(
                f"| {label} | {_fmt_value(b)} | {_fmt_value(h)} | "
                f"{_fmt_delta(b, h, higher, n_min=n_min)} |"
            )
        base_dist = base_judge.get("status_distribution") or {}
        head_dist = head_judge.get("status_distribution") or {}
        statuses = sorted(set(base_dist) | set(head_dist))
        if statuses:
            lines.append("")
            lines.append("| judge_status | base count | head count |")
            lines.append("|---|---:|---:|")
            for status in statuses:
                lines.append(
                    f"| {status} | {base_dist.get(status, 0)} | "
                    f"{head_dist.get(status, 0)} |"
                )

    lines.append("")
    lines.append(
        "_Aggregate-only. Per-case data is never read or rendered by this "
        "script (ADR 0005). ✅ direction-of-improvement; ⚠️ "
        "direction-of-regression._"
    )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Decision Log stub
# -----------------------------------------------------------------------------


_DECISION_LOG_TEMPLATE = """

### Entry: {date} — TODO short title

**Change.** TODO 1-2 sentences. Link the PR/issue.

**Surface.** Local private real-data set (`eval/real_config.local.yaml`,
N={cases} cases). Same index, same case set, same tooling for both
sides.

{table}

**Interpretation.** TODO — what worked? what regressed? what to do
next?

**Decision.** TODO — ship / revert / tighten / follow-up issue.
"""


def append_decision_log_stub(
    docs_path: Path,
    table_md: str,
    cases: int,
) -> None:
    import datetime

    if not docs_path.exists():
        raise FileNotFoundError(f"Decision log target not found: {docs_path}")
    date = datetime.date.today().isoformat()
    body = _DECISION_LOG_TEMPLATE.format(date=date, cases=cases, table=table_md)
    with docs_path.open("a", encoding="utf-8") as fh:
        fh.write(body)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--head",
        default="reports/real100/eval_summary.json",
        help="Current real-data eval_summary.json path.",
    )
    ap.add_argument(
        "--base",
        default="reports/real100/baseline.aggregate.json",
        help="Committed baseline aggregate snapshot path.",
    )
    ap.add_argument("--title", default="Real-data eval delta")
    ap.add_argument(
        "--write-decision-log-stub",
        action="store_true",
        help=(
            "Append a Decision Log entry stub (with the rendered table) to "
            "docs/real-data/private-100-doc-experiments.md so you only fill the "
            "interpretation paragraph."
        ),
    )
    ap.add_argument(
        "--decision-log-path",
        default="docs/real-data/private-100-doc-experiments.md",
        help="Target file for the Decision Log stub (default is the public doc).",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    head_path = Path(args.head)
    base_path = Path(args.base)
    if not head_path.exists():
        print(
            f"[ERROR] Head eval summary not found: {head_path}\n"
            "Run `make real-eval` first to generate it.",
            file=sys.stderr,
        )
        return 2
    if not base_path.exists():
        print(
            f"[ERROR] Baseline aggregate not found: {base_path}\n"
            "Run `make real-eval-baseline-update` once to seed it.",
            file=sys.stderr,
        )
        return 2

    head_raw = json.loads(head_path.read_text(encoding="utf-8"))
    base_raw = json.loads(base_path.read_text(encoding="utf-8"))

    head = extract_aggregate(head_raw)

    # ADR 0006: if a judge.local.json sits beside the head eval
    # summary, fold its aggregate into the head view so the delta
    # surfaces judge_grounded_rate / agreement_with_verifier when the
    # user just ran `make real-eval-with-judge`. The per-case judge
    # text is never copied into the head aggregate.
    judge_local = head_path.parent / "judge.local.json"
    if judge_local.exists():
        from collections import Counter

        judge_payload = json.loads(judge_local.read_text(encoding="utf-8"))
        cases = judge_payload.get("cases") or []
        statuses = [c.get("judge_status") for c in cases if c.get("judge_status")]
        grounded = [bool(c.get("judge_grounded")) for c in cases]
        agreements = [bool(c.get("agrees")) for c in cases if c.get("agrees") is not None]
        head["judge"] = {
            "status_distribution": dict(Counter(statuses)),
            "grounded_rate": (sum(grounded) / len(grounded)) if grounded else None,
            "agreement_with_verifier": (
                sum(agreements) / len(agreements) if agreements else None
            ),
            "n": len(cases),
        }
        # Privacy guard: assert nothing leaked.
        _assert_no_forbidden(head["judge"], "judge")

    base = extract_aggregate(base_raw) if "case_results" in base_raw else base_raw
    # If the baseline file was already in aggregate form (it should be),
    # re-running the extractor is a no-op but also re-asserts the
    # privacy invariant. Do it anyway:
    base = extract_aggregate(base)

    table = render_markdown(base, head, args.title)
    print(table)

    if args.write_decision_log_stub:
        cases = head.get("num_predictions") or "?"
        append_decision_log_stub(Path(args.decision_log_path), table, cases)
        print(
            f"\n[OK] Decision Log stub appended to {args.decision_log_path}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
