#!/usr/bin/env python3
"""Render a markdown delta table comparing two eval_summary.json files.

Used by the PR eval workflow to post a base-vs-head comparison comment.
Metric list and formatting helpers live in scripts/_eval_delta.py so the
harness matrix compare reuses the same surface.

Regression gate:
  Pass ``--regression-threshold <delta>`` (default 0.05) to additionally
  enforce that no *gated* metric (quality metrics — accuracy,
  groundedness, citation_precision, etc.; latency is excluded) regresses
  by more than ``threshold`` absolute points relative to the base run.
  On regression, exit code is 1 and a "FAIL" block is appended to the
  rendered table for the PR comment.

  An intentional regression can be acknowledged in the PR body with
  ``[ALLOW_REGRESSION: <reason>]`` — when ``--allow-regression`` is
  passed (or env ``ALLOW_REGRESSION=true``), the script still annotates
  the regression in the comment but exits 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eval_delta import (  # noqa: E402
    METRICS,
    detect_abstention_outcome_regressions,
    detect_regressions,
    fmt_delta,
    fmt_value,
    get_path,
    min_num_predictions,
)

DEFAULT_REGRESSION_THRESHOLD = 0.05
ENV_ALLOW_REGRESSION = "ALLOW_REGRESSION"
REQUIRED_PROVENANCE_FIELDS = ("run", "config", "index", "dataset")
COMPARABLE_PROVENANCE_FIELDS = ("config", "index", "dataset")
UNKNOWN_PROVENANCE_SENTINELS = {"unknown", "none", "null", "n/a", "na", "?"}
DATASET_COUNT_ONLY_PREFIX = "counts_only: "
PRIVATE_RELATIVE_PATH_PREFIXES = (
    "data/private/",
    "experiments/private",
    "reports/real",
)
PRIVATE_PATH_SUFFIXES = {
    ".bin",
    ".csv",
    ".json",
    ".jsonl",
    ".npy",
    ".pkl",
    ".pt",
    ".safetensors",
    ".txt",
    ".yaml",
    ".yml",
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="Base (main) eval_summary.json")
    ap.add_argument("--head", required=True, help="Head (PR) eval_summary.json")
    ap.add_argument("--title", default="Eval delta")
    ap.add_argument(
        "--scope-note",
        default="",
        help=(
            "Optional markdown note rendered immediately under the title, "
            "used by CI to make the measurement surface explicit."
        ),
    )
    ap.add_argument(
        "--fail-on-surface-mismatch",
        action="store_true",
        help=(
            "Exit 2 when the compared eval_summary.json files are classified "
            "as different evaluation surfaces. Unknown surfaces are rendered "
            "but do not fail the gate."
        ),
    )
    ap.add_argument(
        "--fail-on-missing-provenance",
        action="store_true",
        help=(
            "Exit 2 when either eval_summary.json is missing run/config/index/"
            "dataset provenance needed to interpret metric claims. Missing "
            "provenance is always rendered before the metric table."
        ),
    )
    ap.add_argument(
        "--fail-on-provenance-mismatch",
        action="store_true",
        help=(
            "Exit 2 when comparable config/index/dataset provenance is present "
            "on both eval_summary.json files but differs. The run provenance "
            "itself may differ across base/head and is not compared."
        ),
    )
    ap.add_argument(
        "--regression-threshold",
        type=float,
        default=DEFAULT_REGRESSION_THRESHOLD,
        help=(
            "Absolute threshold for the gate on quality metrics "
            f"(default {DEFAULT_REGRESSION_THRESHOLD}). 0 disables the gate."
        ),
    )
    ap.add_argument(
        "--allow-regression",
        action="store_true",
        default=_env_flag(ENV_ALLOW_REGRESSION),
        help=(
            "Acknowledge an intentional regression. The comment still "
            f"surfaces the regression; the script exits 0. Env: {ENV_ALLOW_REGRESSION}."
        ),
    )
    ap.add_argument(
        "--paired-ci",
        action="store_true",
        help=(
            "Append a paired-bootstrap 95%% CI block computed from per-case "
            "`case_results` (local runs only; the aggregate baseline carries "
            "no per-case data per ADR 0005). Display-only — the regression "
            "gate is unchanged."
        ),
    )
    ap.add_argument(
        "--paired-ci-seeds",
        default="17,19,23",
        help="Comma-separated bootstrap seeds for seed-averaged paired CI (default 17,19,23).",
    )
    return ap.parse_args()


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "y")


def classify_eval_surface(summary: dict, *, path: str | Path | None = None) -> str:
    """Best-effort eval surface classification for reviewer-visible output.

    The classifier is intentionally conservative: unknown summaries are labeled
    as unknown instead of being coerced into a claim-bearing surface.
    """
    benchmark_type = str(summary.get("benchmark_type") or summary.get("eval_type") or "").strip().lower()
    if benchmark_type == "private_real_eval":
        return "private_real_eval"
    if benchmark_type == "naive_rag_benchmark":
        return "public_synthetic_benchmark"
    if benchmark_type == "public_fixture_smoke_regression":
        return "public_fixture_smoke"

    if path is not None:
        normalized = Path(path).as_posix()
        relativeish = normalized.lstrip("./")
        if (
            relativeish.startswith("reports/real")
            or "/reports/real" in relativeish
        ) and relativeish.endswith("/eval_summary.json"):
            return "private_real_eval"
        if relativeish == "reports/eval_summary.json" or relativeish.endswith("/reports/eval_summary.json"):
            return "public_fixture_smoke"
        if (
            relativeish.startswith("artifacts/runs/")
            or "/artifacts/runs/" in relativeish
        ) and relativeish.endswith("/metrics/eval_summary.json"):
            return "harness_run"

    return "unknown_eval_summary"


def surfaces_compatible(base_surface: str, head_surface: str) -> bool:
    if base_surface.startswith("unknown") or head_surface.startswith("unknown"):
        return True
    return base_surface == head_surface


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        return bool(text) and text.lower() not in UNKNOWN_PROVENANCE_SENTINELS
    return True


def _first_present(summary: dict, *paths: str) -> Any:
    for path in paths:
        value = get_path(summary, path)
        if _present(value):
            return value
    return None


def _short_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = " ".join(str(value or "").strip().split())
    return text if text else "unknown"


def _privacy_safe_scalar(value: Any) -> str:
    text = _short_scalar(value)
    if text == "unknown":
        return text
    if _looks_like_local_path(text) or _looks_like_private_relative_path(text):
        return _basename_label(text)
    return text


def _looks_like_local_path(text: str) -> bool:
    if text.startswith(("file://", "/", "~", "\\\\")):
        return True
    return len(text) >= 3 and text[1] == ":" and text[2] in ("\\", "/")


def _looks_like_private_relative_path(text: str) -> bool:
    normalized = text.replace("\\", "/")
    if any(normalized.startswith(prefix) for prefix in PRIVATE_RELATIVE_PATH_PREFIXES):
        return True
    return "/" in normalized and Path(normalized).suffix.lower() in PRIVATE_PATH_SUFFIXES


def _basename_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    if text.startswith("file://"):
        text = text[len("file://"):]
    if "\\" in text or (len(text) >= 2 and text[1] == ":"):
        return PureWindowsPath(text).name or "path-present"
    return Path(text).name or "path-present"


def _path_provenance_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    return f"{_basename_label(text)}#{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


def eval_provenance_summary(summary: dict) -> dict[str, str]:
    """Return privacy-safe provenance labels for reviewer-visible output.

    Only aggregate metadata is read. Local filesystem paths are reduced to a
    basename so the comparator can surface that provenance exists without
    rendering private absolute paths.
    """
    git_commit = _first_present(
        summary,
        "provenance.git_commit",
        "run_manifest.git_commit",
    )
    git_tree = _first_present(summary, "provenance.git_tree")
    git_dirty = _first_present(summary, "provenance.git_dirty", "run_manifest.git_dirty")
    generated_at = _first_present(
        summary,
        "provenance.generated_at",
        "run_manifest.generated_at",
        "generated_at",
    )
    run_bits: list[str] = []
    if _present(git_commit):
        run_bits.append(f"git={_short_scalar(git_commit)}")
    if _present(git_tree):
        run_bits.append(f"tree={_short_scalar(git_tree)}")
    if _present(generated_at):
        run_bits.append(f"generated={_short_scalar(generated_at)}")
    if run_bits and _present(git_dirty):
        run_bits.append(f"dirty={_short_scalar(git_dirty)}")

    config_sha = _first_present(summary, "run_manifest.config_sha256", "config_sha256")
    config_path = _first_present(summary, "run_manifest.config_path", "config_path")
    if _present(config_sha):
        config = f"sha={_short_scalar(config_sha)}"
    elif _present(config_path):
        config = f"path={_path_provenance_label(config_path)}"
    else:
        config = "unknown"

    embedding_backend = _first_present(
        summary,
        "run_manifest.embedding_backend",
        "index_provenance.embedding_backend",
        "model_config.backend",
        "embedding.backend",
    )
    embedding_model = _first_present(
        summary,
        "run_manifest.embedding_model_id",
        "index_provenance.model",
        "model_config.model",
        "embedding.model",
    )
    vector_store_backend = _first_present(
        summary,
        "run_manifest.vector_store_backend",
        "vector_store_backend",
    )
    index_dir = _first_present(summary, "index_dir")
    if _present(embedding_backend) and _present(embedding_model):
        index = (
            f"embedding={_privacy_safe_scalar(embedding_backend)}/"
            f"{_privacy_safe_scalar(embedding_model)} · "
            f"vector_store={_privacy_safe_scalar(vector_store_backend)}"
        )
    elif _present(index_dir):
        index = f"path={_path_provenance_label(index_dir)}"
    else:
        index = "unknown"

    dataset_source = summary.get("dataset")
    if not isinstance(dataset_source, dict):
        dataset_source = summary.get("dataset_summary")
    dataset_bits: list[str] = []
    dataset_identity_present = False
    if isinstance(dataset_source, dict):
        dataset_id = _first_present(
            dataset_source,
            "id",
            "name",
            "sha256",
            "fingerprint",
        )
        if _present(dataset_id):
            dataset_identity_present = True
            dataset_bits.append(f"id={_privacy_safe_scalar(dataset_id)}")
        for label, keys in (
            ("questions", ("num_questions", "question_count", "n_questions")),
            (
                "docs",
                ("num_documents", "num_docs", "document_count", "doc_count", "corpus_size"),
            ),
            ("chunks", ("num_chunks", "chunk_count", "n_chunks")),
            ("answerable", ("answerable_count", "answerable_question_count")),
            ("unanswerable", ("unanswerable_count", "unanswerable_question_count")),
        ):
            value = _first_present(dataset_source, *keys)
            if isinstance(value, int):
                dataset_bits.append(f"{label}={value}")
    dataset_id = _first_present(
        summary,
        "dataset_id",
        "dataset_sha256",
        "dataset_hash",
        "dataset_fingerprint",
    )
    dataset_path = _first_present(summary, "dataset_path", "questions_path", "corpus_path")
    if _present(dataset_id) and not dataset_bits:
        dataset_identity_present = True
        dataset_bits.append(f"id={_privacy_safe_scalar(dataset_id)}")
    elif _present(dataset_path):
        dataset_identity_present = True
        if not any(bit.startswith(("id=", "path=")) for bit in dataset_bits):
            dataset_bits.insert(0, f"path={_path_provenance_label(dataset_path)}")

    return {
        "run": ", ".join(run_bits) if run_bits else "unknown",
        "config": config,
        "index": index,
        "dataset": (
            ", ".join(dataset_bits)
            if dataset_identity_present
            else (
                DATASET_COUNT_ONLY_PREFIX + ", ".join(dataset_bits)
                if dataset_bits
                else "unknown"
            )
        ),
    }


def missing_required_provenance(summary: dict) -> list[str]:
    provenance = eval_provenance_summary(summary)
    return [
        field
        for field in REQUIRED_PROVENANCE_FIELDS
        if provenance.get(field) == "unknown"
        or (
            field == "dataset"
            and str(provenance.get(field) or "").startswith(DATASET_COUNT_ONLY_PREFIX)
        )
    ]


def provenance_mismatches(base: dict, head: dict) -> dict[str, tuple[str, str]]:
    base_provenance = eval_provenance_summary(base)
    head_provenance = eval_provenance_summary(head)
    out: dict[str, tuple[str, str]] = {}
    for field in COMPARABLE_PROVENANCE_FIELDS:
        base_value = base_provenance.get(field, "unknown")
        head_value = head_provenance.get(field, "unknown")
        if "unknown" in (base_value, head_value):
            continue
        if base_value != head_value:
            out[field] = (base_value, head_value)
    return out


def _render_provenance(label: str, summary: dict) -> str:
    provenance = eval_provenance_summary(summary)
    return (
        f"- provenance({label}): run=`{provenance['run']}` · "
        f"config=`{provenance['config']}` · index=`{provenance['index']}` · "
        f"dataset=`{provenance['dataset']}`"
    )


def _render_gate_block(regressions: list[dict], *, allow: bool) -> list[str]:
    if not regressions:
        return [
            "_✅ direction-of-improvement; ⚠️ direction-of-regression. "
            "Gated quality metrics passed within threshold._"
        ]
    bullets = []
    for r in regressions:
        bullets.append(
            f"  - **{r['metric']}**: base {r['base']:.3f} → PR {r['head']:.3f} "
            f"(Δ {r['delta']:+.3f}, threshold ±{r['threshold']})"
        )
    if allow:
        header = (
            "**⚠️ Acknowledged regression** — `[ALLOW_REGRESSION]` tag detected. "
            "Reviewers please confirm the trade-off is intentional."
        )
    else:
        header = (
            "**❌ Regression gate failed** — the metrics below dropped beyond "
            "the threshold. Add `[ALLOW_REGRESSION: <reason>]` to the PR body "
            "to acknowledge an intentional trade-off."
        )
    return [header, *bullets]


def _render_paired_ci_block(base, head, *, seeds) -> list[str]:
    """Per-metric paired-bootstrap CI of (head − base) from ``case_results``.

    Reuses the tested estimators in ``scripts/_ablation_common`` (which the
    retrieval-eval ablation runners already share): cases are paired by
    ``id`` (intersection), ``None`` scores are dropped per ADR 0054
    conditional-metric semantics, and the paired delta CI is seed-averaged.
    Display-only: the regression gate above is unchanged, and a committed
    aggregate baseline (no ``case_results``) degrades to an explanatory note
    rather than a crash.
    """
    # Lazy import: keeps the default compare path free of the eval.bootstrap
    # dependency (imported transitively by _ablation_common). Repo root must
    # be importable for `eval.bootstrap`.
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from _ablation_common import (  # noqa: E402
            _drop_paired_nones,
            _fmt_ci,
            _seed_averaged_paired_ci,
        )
    except Exception as exc:  # pragma: no cover - import guard
        return [f"_Paired CI unavailable: {exc}_"]

    base_cases = base.get("case_results") if isinstance(base, dict) else None
    head_cases = head.get("case_results") if isinstance(head, dict) else None
    if not isinstance(base_cases, list) or not isinstance(head_cases, list):
        return [
            "_Paired CI: requires `case_results` in both runs (local "
            "`eval_summary.json`, not the aggregate baseline — ADR 0005)._"
        ]

    base_by_id = {c["id"]: c for c in base_cases if isinstance(c, dict) and "id" in c}
    common_ids = [
        c["id"]
        for c in head_cases
        if isinstance(c, dict) and c.get("id") in base_by_id
    ]
    head_by_id = {c["id"]: c for c in head_cases if isinstance(c, dict) and "id" in c}
    if not common_ids:
        return ["_Paired CI: no shared case ids between the two runs._"]

    lines = [
        "#### Paired bootstrap 95% CI — head − base (per-case, seed-averaged)",
        "",
        f"- paired cases: {len(common_ids)} · seeds: {list(seeds)}",
        "",
        "| metric | Δ (95% CI) |",
        "|---|---|",
    ]
    for path, label, _higher, gated in METRICS:
        if not gated or "." in path:
            continue
        a = [head_by_id[i].get(path) for i in common_ids]  # other = head
        b = [base_by_id[i].get(path) for i in common_ids]  # current = base
        a_clean, b_clean = _drop_paired_nones(a, b)
        if len(a_clean) < 2:
            lines.append(f"| {label} | N/A (n<2) |")
            continue
        ci = _seed_averaged_paired_ci(a_clean, b_clean, list(seeds))
        lines.append(f"| {label} | {_fmt_ci(ci)} |")
    lines.append("")
    lines.append(
        "_Significance = 95% CI excludes 0 (seed-averaged paired bootstrap). "
        "Display-only; the regression gate above is unchanged._"
    )
    return lines


def main() -> int:
    args = parse_args()
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    head = json.loads(Path(args.head).read_text(encoding="utf-8"))
    base_surface = classify_eval_surface(base, path=args.base)
    head_surface = classify_eval_surface(head, path=args.head)
    surface_mismatch = not surfaces_compatible(base_surface, head_surface)
    base_missing_provenance = missing_required_provenance(base)
    head_missing_provenance = missing_required_provenance(head)
    missing_provenance = bool(base_missing_provenance or head_missing_provenance)
    mismatched_provenance = provenance_mismatches(base, head)

    lines: list[str] = []
    lines.append(f"### {args.title}")
    lines.append("")
    if args.scope_note:
        lines.append(f"> {args.scope_note}")
        lines.append("")
    lines.append(
        f"- pipeline: `{head.get('pipeline', '?')}` "
        f"(primary run: `{head.get('primary_run', '?')}`)"
    )
    lines.append(f"- surface: base=`{base_surface}` · head=`{head_surface}`")
    lines.append(_render_provenance("base", base))
    lines.append(_render_provenance("head", head))
    lines.append(
        f"- cases: base={base.get('num_predictions', '?')} · "
        f"head={head.get('num_predictions', '?')}"
    )
    if surface_mismatch:
        lines.append(
            "> ⚠️ Surface mismatch: compare smoke, synthetic benchmark, "
            "private real-eval, and harness artifacts only with matching "
            "dataset/config/index provenance."
        )
    if missing_provenance:
        missing_bits = []
        if base_missing_provenance:
            missing_bits.append(
                "base missing "
                + ", ".join(f"`{field}`" for field in base_missing_provenance)
            )
        if head_missing_provenance:
            missing_bits.append(
                "head missing "
                + ", ".join(f"`{field}`" for field in head_missing_provenance)
            )
        lines.append(
            "> ⚠️ Missing provenance: " + "; ".join(missing_bits) + ". "
            "Metric deltas should not be used as benchmark/performance claims "
            "until run/config/index/dataset provenance is explicit."
        )
    if mismatched_provenance:
        mismatch_bits = [
            f"`{field}` base=`{base_value}` head=`{head_value}`"
            for field, (base_value, head_value) in mismatched_provenance.items()
        ]
        lines.append(
            "> ⚠️ Provenance mismatch: " + "; ".join(mismatch_bits) + ". "
            "Treat metric deltas as non-comparable unless this is an intentional "
            "config/index/dataset change."
        )
    lines.append("")
    n_min = min_num_predictions(base, head)
    lines.append("| metric | main | PR | Δ |")
    lines.append("|---|---|---|---|")
    for path, label, higher, _gated in METRICS:
        b = get_path(base, path)
        h = get_path(head, path)
        lines.append(
            f"| {label} | {fmt_value(b)} | {fmt_value(h)} | "
            f"{fmt_delta(b, h, higher, n_min=n_min)} |"
        )
    lines.append("")

    regressions: list[dict] = []
    if args.regression_threshold > 0:
        regressions = detect_regressions(base, head, threshold=args.regression_threshold)
        regressions += detect_abstention_outcome_regressions(base, head)
    lines.extend(_render_gate_block(regressions, allow=args.allow_regression))

    if args.paired_ci:
        seeds = [int(s) for s in str(args.paired_ci_seeds).split(",") if s.strip()]
        lines.append("")
        lines.extend(_render_paired_ci_block(base, head, seeds=seeds))

    print("\n".join(lines))

    if surface_mismatch and args.fail_on_surface_mismatch:
        return 2
    if missing_provenance and args.fail_on_missing_provenance:
        return 2
    if mismatched_provenance and args.fail_on_provenance_mismatch:
        return 2
    if regressions and not args.allow_regression:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
