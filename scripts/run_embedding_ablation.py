#!/usr/bin/env python3
"""Embedding model ablation runner (issues #148, #161).

Builds the public synthetic index once per requested embedding model and
runs the full ``eval/config.yaml`` ablation suite against each. Prints a
side-by-side delta table reviewers can transcribe into
``docs/embedding-ablation.md``.

This is a measurement tool, not a CI gate. The CI path stays on the
deterministic ``hashing`` backend for reproducibility; this runner is
how a contributor evaluates whether a candidate model is worth changing
the default to (ADR 0001 baseline is preserved either way).

Usage:
    # Default — MiniLM-L12-v2 vs multilingual-e5-base (already in cache)
    python3 scripts/run_embedding_ablation.py

    # Phase 1.2 second comparison (#161) — opt-in for disk-heavy models
    python3 scripts/run_embedding_ablation.py --models \\
        sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \\
        BAAI/bge-m3 \\
        intfloat/multilingual-e5-large-instruct \\
        nlpai-lab/KURE-v1

    # OpenAI text-embedding-3-large (requires BIDMATE_OPENAI_API_KEY)
    export BIDMATE_OPENAI_API_KEY=sk-...
    python3 scripts/run_embedding_ablation.py --models text-embedding-3-large

Backend is auto-derived from model ID: any name starting with
``text-embedding-`` routes to the OpenAI backend, everything else uses
sentence-transformers. Override per run with ``--embedding-backend``.

Approximate disk + cost guide (opt-in models):

    BAAI/bge-m3                          ~2.0GB disk, 1024-dim, free
    intfloat/multilingual-e5-large-instruct  ~1.3GB disk, 1024-dim, free
    nlpai-lab/KURE-v1                    ~1.1GB disk, 768-dim, free (Korean-specialized)
    text-embedding-3-large               OpenAI, 3072-dim, ~$0.004 for n=42
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODELS = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "intfloat/multilingual-e5-base",
)

ABLATION_NAMES = (
    "naive_baseline",
    "full",
    "hierarchical",
    "no_metadata_first",
    "no_rerank",
    "no_verifier_retry",
)

METRICS = (
    ("accuracy", "accuracy"),
    ("groundedness", "groundedness"),
    ("citation_precision", "citation"),
    ("abstention", "abstention"),
    ("answer_format_compliance", "format"),
)


def _slug(model_id: str) -> str:
    return model_id.replace("/", "_").replace("-", "_").replace(".", "_")


def _adapter_suffix() -> str:
    """Slug fragment that disambiguates base vs LoRA-adapted runs.

    Issue #179 / ADR 0027: when ``BIDMATE_EMBEDDING_LORA_ADAPTER`` is set,
    the index + report directory slugs get an ``__lora_<adapter>`` suffix
    so running this script twice (baseline + adapted) on the same base
    model writes to *separate* output paths instead of overwriting.
    Without the env var (CI default), the suffix is empty — slug stays
    identical to pre-#434 output.
    """
    adapter = os.environ.get("BIDMATE_EMBEDDING_LORA_ADAPTER")
    if not adapter:
        return ""
    # Drop ``@<sha>`` pin for a stable on-disk slug; the SHA is captured
    # in the eval_summary.json provenance block, not the path.
    repo = adapter.split("@", 1)[0]
    return "__lora_" + _slug(repo)


def _derive_backend(model_id: str) -> str:
    if model_id.startswith("text-embedding-"):
        return "openai"
    return "sentence-transformers"


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Command failed (exit {proc.returncode}): {' '.join(cmd)}")


def build_index(model_id: str, index_dir: Path, backend: str | None = None) -> None:
    backend = backend or _derive_backend(model_id)
    _run(
        [
            sys.executable,
            "scripts/build_index.py",
            "--input_dir",
            "data/raw",
            "--output_dir",
            str(index_dir),
            "--embedding_backend",
            backend,
            "--model",
            model_id,
        ]
    )


def run_eval(index_dir: Path, output_dir: Path) -> Path:
    _run(
        [
            sys.executable,
            "eval/run_eval.py",
            "--index_dir",
            str(index_dir),
            "--output_dir",
            str(output_dir),
            "--config",
            "eval/config.yaml",
        ]
    )
    return output_dir / "eval_summary.json"


def load_ablation_runs(summary_path: Path) -> dict[str, dict]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    return {run["name"]: run for run in payload["ablation"]["runs"]}


def print_table(per_model: dict[str, dict[str, dict]]) -> None:
    models = list(per_model)
    if len(models) < 2:
        print(json.dumps(per_model, ensure_ascii=False, indent=2))
        return

    baseline_id = models[0]
    # n= is read from the eval config rather than hardcoded; keep header generic
    # so it stays accurate as eval/config.yaml grows (was n=42, now n=100+).
    print(f"\nEMBEDDING ABLATION (baseline = {baseline_id})\n")
    header = f"{'metric':<22}"
    for m in models:
        header += f" {m.split('/')[-1][:22]:>22}"
    header += f" {'Δ vs baseline (pp)':>22}"
    print(header)
    print("-" * len(header))

    for ablation in ABLATION_NAMES:
        print(f"\n--- {ablation}:")
        for key, label in METRICS:
            row = f"  {label:<20}"
            baseline_val = per_model[baseline_id][ablation].get(key)
            for m in models:
                val = per_model[m][ablation].get(key)
                row += f" {val:>22.3f}" if val is not None else f" {'N/A':>22}"
            if baseline_val is None or per_model[models[-1]][ablation].get(key) is None:
                row += f" {'N/A':>22}"
            else:
                delta = (per_model[models[-1]][ablation][key] - baseline_val) * 100
                row += f" {delta:>+22.1f}"
            print(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        help="Embedding model IDs (sentence-transformers compatible). First entry is the baseline.",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Skip build_index / run_eval if reports/embedding-ablation/<model>/eval_summary.json already exists.",
    )
    parser.add_argument(
        "--embedding-backend",
        default=None,
        choices=["auto", "sentence-transformers", "hashing", "openai"],
        help=(
            "Override per-model backend selection. By default the backend is auto-derived "
            "from the model ID (text-embedding-* → openai, else sentence-transformers)."
        ),
    )
    args = parser.parse_args()

    base_index = REPO_ROOT / "data" / "embedding-ablation"
    base_reports = REPO_ROOT / "reports" / "embedding-ablation"
    base_index.mkdir(parents=True, exist_ok=True)
    base_reports.mkdir(parents=True, exist_ok=True)

    per_model: dict[str, dict[str, dict]] = {}
    adapter_suffix = _adapter_suffix()
    for model_id in args.models:
        slug = _slug(model_id) + adapter_suffix
        index_dir = base_index / slug
        report_dir = base_reports / slug
        summary_path = report_dir / "eval_summary.json"

        if args.reuse_existing and summary_path.exists():
            print(f"[skip] {model_id} — using cached {summary_path}", flush=True)
        else:
            backend = args.embedding_backend or _derive_backend(model_id)
            print(f"\n[build] index for {model_id} (backend={backend})", flush=True)
            build_index(model_id, index_dir, backend=backend)
            print(f"[eval]  {model_id}", flush=True)
            run_eval(index_dir, report_dir)

        per_model[model_id] = load_ablation_runs(summary_path)

    print_table(per_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
