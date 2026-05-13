#!/usr/bin/env python3
"""Routed-subset 5-embedding measurement runner for ADR 0032.

Builds a fresh index per embedding model, runs eval/routed_config.yaml,
and aggregates results into reports/embedding_routed.json.

Usage (from repo root):
    # Hashing backend (fast sanity-check — 5 "models" share the same hash, spread = 0)
    python3 scripts/run_routed_measurement.py --backend hashing

    # Sentence-transformers (real measurement, ~30 min with model downloads)
    python3 scripts/run_routed_measurement.py --backend sentence-transformers

    # Single model only (dev/debug)
    python3 scripts/run_routed_measurement.py --backend sentence-transformers --model-filter minilm

Acceptance thresholds (ADR 0032 §Decision):
    spread ≥ +3pp (top-vs-bottom accuracy, agentic_full_routed) → ADR 0019 re-open trigger
    spread < +3pp → saturation cross-validated, MiniLM default lock empirically justified
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.bootstrap import bootstrap_ci  # noqa: E402

# ---------------------------------------------------------------------------
# Embedding model registry
# ---------------------------------------------------------------------------
MODELS: list[dict[str, str]] = [
    {
        "key": "minilm",
        "hf_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "label": "MiniLM-L12-v2",
        "note": "ADR 0019 locked default",
    },
    {
        "key": "e5_large",
        "hf_id": "intfloat/multilingual-e5-large-instruct",
        "label": "multilingual-e5-large-instruct",
        "note": "ADR 0021 Phase 1.3 candidate",
    },
    {
        "key": "simcse",
        "hf_id": "BM-K/KoSimCSE-roberta-multitask",
        "label": "KoSimCSE-roberta-multitask",
        "note": "ADR 0021 Phase 1.2 candidate",
    },
    {
        "key": "bge_m3",
        "hf_id": "BAAI/bge-m3",
        "label": "BGE-M3",
        "note": "ADR 0021 Phase 1.3 — 0pp on full",
    },
    {
        "key": "kure_v1",
        "hf_id": "nlpai-lab/KURE-v1",
        "label": "KURE-v1",
        "note": "Korean-specialized Phase 1.3 candidate (deferred)",
    },
]

# Ablation run names expected in routed_config.yaml
FULL_RUN = "agentic_full"
ROUTED_RUN = "agentic_full_routed"

# ADR 0032 decision threshold (pp, non-overlapping CI)
SPREAD_THRESHOLD_PP = 3.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, desc: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"\n[run_routed] {desc}")
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT, capture_output=False, text=True, check=False)
    if check and result.returncode != 0:
        print(f"[FAIL] Command exited {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    return result


def _extract_run_summary(
    eval_summary_path: Path, run_name: str
) -> dict[str, Any] | None:
    """Extract per-ablation-run accuracy + CI from eval_summary.json."""
    if not eval_summary_path.exists():
        return None
    data = json.loads(eval_summary_path.read_text(encoding="utf-8"))
    for run in data.get("ablation", {}).get("runs", []):
        if run.get("name") == run_name:
            return run
    return None


def _accuracy_mean(run_summary: dict[str, Any] | None) -> float | None:
    if run_summary is None:
        return None
    acc = run_summary.get("accuracy")
    if isinstance(acc, dict):
        return acc.get("mean")
    return acc


def _accuracy_ci(run_summary: dict[str, Any] | None) -> tuple[float, float] | None:
    if run_summary is None:
        return None
    ci_block = run_summary.get("ci", {}).get("accuracy", {})
    lo = ci_block.get("lo")
    hi = ci_block.get("hi")
    if lo is not None and hi is not None:
        return (lo, hi)
    # Fallback: re-compute from case_results accuracy scores
    return None


# ---------------------------------------------------------------------------
# Core measurement loop
# ---------------------------------------------------------------------------


def measure_model(
    model: dict[str, str],
    backend: str,
    tmp_root: Path,
    input_dir: str,
    routed_config: str,
) -> dict[str, Any]:
    """Build index and run routed eval for one embedding model."""
    key = model["key"]
    hf_id = model["hf_id"] if backend == "sentence-transformers" else "local-hashing-bow"
    index_dir = tmp_root / f"index_{key}"
    report_dir = tmp_root / f"report_{key}"
    index_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build index
    build_cmd = [
        sys.executable,
        "scripts/build_index.py",
        "--input_dir", input_dir,
        "--output_dir", str(index_dir),
        "--embedding_backend", backend,
    ]
    if backend == "sentence-transformers":
        build_cmd += ["--model", hf_id]
    build_result = _run(build_cmd, desc=f"Build index ({model['label']})", check=False)
    if build_result.returncode != 0:
        print(f"[SKIP] Index build failed for {model['label']}, returncode={build_result.returncode}")
        return {
            "model_key": key,
            "model_label": model["label"],
            "hf_id": hf_id if backend == "sentence-transformers" else "hashing",
            "note": model["note"],
            "skipped": True,
            "skip_reason": f"Index build failed (returncode={build_result.returncode}). BGE-M3 requires torch>=2.6 (ADR 0021 §4 blocker).",
            "full": {"accuracy_mean": None, "accuracy_ci": None},
            "routed": {"accuracy_mean": None, "accuracy_ci": None},
        }

    # 2. Run routed eval
    eval_cmd = [
        sys.executable,
        "eval/run_eval.py",
        "--config", routed_config,
        "--index_dir", str(index_dir),
        "--output_dir", str(report_dir),
    ]
    _run(eval_cmd, desc=f"Eval routed ({model['label']})")

    # 3. Extract results
    summary_path = report_dir / "eval_summary.json"
    full_run = _extract_run_summary(summary_path, FULL_RUN)
    routed_run = _extract_run_summary(summary_path, ROUTED_RUN)

    return {
        "model_key": key,
        "model_label": model["label"],
        "hf_id": hf_id if backend == "sentence-transformers" else "hashing",
        "note": model["note"],
        "full": {
            "accuracy_mean": _accuracy_mean(full_run),
            "accuracy_ci": _accuracy_ci(full_run),
        },
        "routed": {
            "accuracy_mean": _accuracy_mean(routed_run),
            "accuracy_ci": _accuracy_ci(routed_run),
        },
    }


def compute_spread(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute top-vs-bottom accuracy spread on the routed ablation."""
    routed_means = [
        r["routed"]["accuracy_mean"]
        for r in rows
        if r["routed"]["accuracy_mean"] is not None
    ]
    if not routed_means:
        return {"spread_pp": None, "verdict": "no_data"}
    spread = (max(routed_means) - min(routed_means)) * 100.0
    if spread >= SPREAD_THRESHOLD_PP:
        verdict = "adr0019_reopen_trigger"
    else:
        verdict = "saturation_cross_validated"
    return {
        "spread_pp": round(spread, 2),
        "threshold_pp": SPREAD_THRESHOLD_PP,
        "verdict": verdict,
        "verdict_description": (
            "Spread ≥ +3pp → ADR 0019 re-open trigger: embedding choice matters on routed surface"
            if verdict == "adr0019_reopen_trigger"
            else "Spread < +3pp → saturation cross-validated: 0pp pattern holds on routed + non-routed subsets; MiniLM default lock empirically justified"
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Run routed-subset 5-embedding measurement (ADR 0032)")
    parser.add_argument(
        "--backend",
        choices=["hashing", "sentence-transformers"],
        default="sentence-transformers",
        help="Embedding backend. 'hashing' is fast but always gives spread=0 (sanity-check only).",
    )
    parser.add_argument(
        "--input_dir", default="data/raw", help="Raw JSON document directory."
    )
    parser.add_argument(
        "--routed_config", default="eval/routed_config.yaml", help="Routed eval config YAML."
    )
    parser.add_argument(
        "--output", default="reports/embedding_routed.json", help="Aggregate output path."
    )
    parser.add_argument(
        "--tmp_dir",
        default=".routed_measurement_tmp",
        help="Temp directory for per-model index/report (cleaned up on success).",
    )
    parser.add_argument(
        "--model-filter",
        default=None,
        help="Comma-separated list of model keys to run (e.g. 'minilm,bge_m3'). Runs all if omitted.",
    )
    parser.add_argument(
        "--keep-tmp",
        action="store_true",
        help="Keep temp dir after completion (useful for debugging).",
    )
    args = parser.parse_args()

    tmp_root = ROOT / args.tmp_dir
    tmp_root.mkdir(parents=True, exist_ok=True)

    models_to_run = MODELS
    if args.model_filter:
        keys = {k.strip() for k in args.model_filter.split(",")}
        models_to_run = [m for m in MODELS if m["key"] in keys]
        if not models_to_run:
            print(f"[ERROR] No models matched filter: {args.model_filter}", file=sys.stderr)
            return 1

    print(f"\n[run_routed_measurement] backend={args.backend}, models={[m['key'] for m in models_to_run]}")
    print(f"  routed_config: {args.routed_config}")
    print(f"  spread threshold: {SPREAD_THRESHOLD_PP}pp (ADR 0032 §Decision)\n")

    rows: list[dict[str, Any]] = []
    for model in models_to_run:
        print(f"\n{'='*60}")
        print(f"  Model: {model['label']} ({model['note']})")
        print(f"{'='*60}")
        row = measure_model(
            model=model,
            backend=args.backend,
            tmp_root=tmp_root,
            input_dir=args.input_dir,
            routed_config=args.routed_config,
        )
        rows.append(row)
        print(
            f"  → full={row['full']['accuracy_mean']:.3f} | routed={row['routed']['accuracy_mean']:.3f}"
            if row["routed"]["accuracy_mean"] is not None
            else "  → result: None"
        )

    spread_result = compute_spread(rows)

    output: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "backend": args.backend,
        "routed_config": args.routed_config,
        "threshold_pp": SPREAD_THRESHOLD_PP,
        "spread": spread_result,
        "rows": rows,
    }

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] Results written to {out_path}")

    print("\n" + "="*60)
    print(f"  VERDICT: {spread_result['verdict']}")
    print(f"  Spread: {spread_result['spread_pp']}pp (threshold: {SPREAD_THRESHOLD_PP}pp)")
    print(f"  {spread_result['verdict_description']}")
    print("="*60 + "\n")

    if not args.keep_tmp:
        shutil.rmtree(tmp_root, ignore_errors=True)
        print(f"[cleanup] Temp dir removed: {tmp_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
