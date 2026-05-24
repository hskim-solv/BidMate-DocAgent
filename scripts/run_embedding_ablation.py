#!/usr/bin/env python3
"""Embedding model ablation runner (issues #148, #161).

Builds an index once per requested embedding model and runs the full
ablation suite against each. Prints a side-by-side delta table reviewers
can transcribe into ``docs/eval/embedding-ablation.md``.

Two surfaces are printed per ablation (issue #1359): the answer-quality
``METRICS`` (accuracy / groundedness / …) and the retrieval-quality
``RETRIEVAL_METRICS`` (chunk_recall@k / mrr / ndcg) that ADR 0069 exposed in
``eval_summary.json``. Retrieval rows carry the bootstrap CI band + a
``(SIG)`` / ``(overlap)`` flag so the ADR 0019 condition-3 trigger reads off
directly. Δ is computed per non-baseline model, so a 3+-model sweep is read
correctly.

Corpus: public fixture ``--input-dir eval/fixtures/smoke_rfp/raw`` by default, or the real
PDF/HWP corpus via ``--metadata-csv data/data_list.csv --files-dir data/files
--eval-config eval/real_config.local.yaml``. Real runs write to a ``*_real``
subtree and stay local — commit only the aggregate deltas (ADR 0005).

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

# Retrieval-quality aggregates surfaced by ADR 0069 (PR #1331). Prior phases
# (1.1–1.5) only printed the answer-quality METRICS above, which conflate
# retrieval with the answer/verifier pipeline — so "did this embedding retrieve
# better chunks?" was never directly readable (e.g. KURE-v1's +19.2pp on
# naive_baseline accuracy could not be attributed to recall vs answer quality).
# These keys + their parallel ``run["ci"][key]`` bootstrap bands now live in
# every ablation run block via metric_block, so the runner just has to print
# them.
RETRIEVAL_METRICS = (
    ("chunk_recall_at_5", "chunk_recall@5"),
    ("chunk_recall_at_10", "chunk_recall@10"),
    ("chunk_recall_at_20", "chunk_recall@20"),
    ("chunk_mrr", "chunk_mrr"),
    ("chunk_ndcg_at_10", "chunk_ndcg@10"),
)
_RETRIEVAL_KEYS = frozenset(key for key, _ in RETRIEVAL_METRICS)


def _ci_band(run: dict, key: str) -> tuple[float, float] | None:
    """Bootstrap CI ``(lo, hi)`` for ``key`` from a run block, or ``None``.

    ``metric_block`` writes ``run["ci"][key] = {"ci_lo", "ci_hi", ...}`` (or
    ``None`` for an all-gold-free slice). Returns ``None`` whenever the band is
    absent so callers can fall back to a point-estimate-only display.
    """
    ci = (run.get("ci") or {}).get(key)
    if not ci:
        return None
    lo, hi = ci.get("ci_lo"), ci.get("ci_hi")
    if lo is None or hi is None:
        return None
    return (float(lo), float(hi))


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


def build_index(
    model_id: str,
    index_dir: Path,
    backend: str | None = None,
    *,
    input_dir: str | None = None,
    metadata_csv: str | None = None,
    files_dir: str | None = None,
) -> None:
    """Build one index for ``model_id``.

    Corpus source is either the public fixture ``--input_dir`` (default
    ``eval/fixtures/smoke_rfp/raw``, backward-compatible with Phase 1.x) or the real PDF/HWP
    corpus via ``--metadata_csv`` + ``--files_dir`` (build_index.py requires
    files_dir when metadata_csv is given). ``metadata_csv`` takes precedence.
    """
    backend = backend or _derive_backend(model_id)
    cmd = [sys.executable, "scripts/build_index.py", "--output_dir", str(index_dir)]
    if metadata_csv:
        cmd += ["--metadata_csv", metadata_csv]
        if files_dir:
            cmd += ["--files_dir", files_dir]
    else:
        cmd += ["--input_dir", input_dir or "eval/fixtures/smoke_rfp/raw"]
    cmd += ["--embedding_backend", backend, "--model", model_id]
    _run(cmd)


def run_eval(index_dir: Path, output_dir: Path, config: str = "eval/config.yaml") -> Path:
    """Run the ablation suite. ``config`` defaults to the public fixture
    smoke ``eval/config.yaml``; real100 runs pass ``eval/real_config.local.yaml``
    (private, gitignored per ADR 0005)."""
    _run(
        [
            sys.executable,
            "eval/run_eval.py",
            "--index_dir",
            str(index_dir),
            "--output_dir",
            str(output_dir),
            "--config",
            config,
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
    base_label = baseline_id.split("/")[-1]
    all_metrics = list(METRICS) + list(RETRIEVAL_METRICS)
    # Ablation run names are read from the eval_summary itself, not hardcoded:
    # the public fixture config and the real config define different runs
    # (e.g. real100 has full / random_retrieval / single_chunk / full_bm25s and
    # no naive_baseline). Use the baseline model's run order; intersect so a run
    # missing from a candidate model is skipped rather than KeyError-ing.
    ablation_names = [
        name for name in per_model[baseline_id] if all(name in per_model[m] for m in models)
    ]
    print(f"\nEMBEDDING ABLATION (baseline = {baseline_id})\n")
    header = f"{'metric':<22}"
    for m in models:
        header += f" {m.split('/')[-1][:22]:>22}"
    print(header)
    print("-" * len(header))

    for ablation in ablation_names:
        print(f"\n--- {ablation}:")
        # Point-estimate rows: answer-quality + retrieval metrics, one column
        # per model. Retrieval rows are the ADR 0069 addition.
        for key, label in all_metrics:
            row = f"  {label:<20}"
            for m in models:
                val = per_model[m][ablation].get(key)
                row += f" {val:>22.3f}" if val is not None else f" {'N/A':>22}"
            print(row)
        # Δ vs baseline, computed per non-baseline model (the old single-column
        # delta only compared the LAST model, which misreads a 3+-model sweep).
        # Retrieval rows additionally carry the bootstrap CI band + a (SIG) /
        # (overlap) flag so the ADR 0019 condition-3 trigger (≥+5pp on `full`
        # with non-overlapping 95% CI) can be read off directly.
        print(f"  Δ vs baseline ({base_label}, pp):")
        for m in models[1:]:
            m_label = m.split("/")[-1][:22]
            for key, label in all_metrics:
                base_val = per_model[baseline_id][ablation].get(key)
                val = per_model[m][ablation].get(key)
                if base_val is None or val is None:
                    print(f"    {m_label:<22} {label:<16} {'N/A':>7}")
                    continue
                delta = (val - base_val) * 100
                line = f"    {m_label:<22} {label:<16} {delta:>+7.1f}"
                if key in _RETRIEVAL_KEYS:
                    cand = _ci_band(per_model[m][ablation], key)
                    base = _ci_band(per_model[baseline_id][ablation], key)
                    if cand and base:
                        overlap = not (cand[0] > base[1] or base[0] > cand[1])
                        flag = "(overlap)" if overlap else "(SIG)"
                        line += (
                            f"  CI[{cand[0]:.3f},{cand[1]:.3f}]"
                            f" vs [{base[0]:.3f},{base[1]:.3f}] {flag}"
                        )
                print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
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
    parser.add_argument(
        "--input-dir",
        default="eval/fixtures/smoke_rfp/raw",
        help="Public fixture corpus dir (default eval/fixtures/smoke_rfp/raw). Ignored when --metadata-csv is set.",
    )
    parser.add_argument(
        "--metadata-csv",
        default=None,
        help=(
            "data_list.csv for the real PDF/HWP corpus (real100). When set, the index is "
            "built from this CSV + --files-dir instead of --input-dir. Indexes/reports stay "
            "local per ADR 0005 — commit only aggregate deltas."
        ),
    )
    parser.add_argument(
        "--files-dir",
        default="data/files",
        help="Directory of PDF/HWP files referenced by --metadata-csv (required with it).",
    )
    parser.add_argument(
        "--eval-config",
        default="eval/config.yaml",
        help=(
            "Eval config. Default eval/config.yaml (public fixture cases); real100 runs "
            "pass eval/real_config.local.yaml (private, gitignored)."
        ),
    )
    args = parser.parse_args()

    # Real-corpus runs land under a *_real subtree so they never collide with
    # cached public fixture indexes/reports of the same model slug.
    suffix = "_real" if args.metadata_csv else ""
    base_index = REPO_ROOT / "data" / f"embedding-ablation{suffix}"
    base_reports = REPO_ROOT / "reports" / f"embedding-ablation{suffix}"
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
            build_index(
                model_id,
                index_dir,
                backend=backend,
                input_dir=args.input_dir,
                metadata_csv=args.metadata_csv,
                files_dir=args.files_dir,
            )
            print(f"[eval]  {model_id}", flush=True)
            run_eval(index_dir, report_dir, config=args.eval_config)

        per_model[model_id] = load_ablation_runs(summary_path)

    print_table(per_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
