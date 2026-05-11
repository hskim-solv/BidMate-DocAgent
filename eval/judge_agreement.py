#!/usr/bin/env python3
"""Judge LLM ↔ human label agreement for the real-data eval surface (#169).

Inputs:
    A CSV with columns ``case_id, judge_status, human_status``.
    ``*_status`` values are restricted to the ADR 0006 vocabulary
    (``supported`` / ``partial`` / ``insufficient``).

Outputs (stdout JSON when ``--json`` is set; otherwise human-readable):
    {
      "n": int,
      "cohens_kappa": float,
      "spearman_rho": float,
      "confusion": {human: {judge: count}},
      "threshold": float,
      "passes": bool
    }

CLI:
    python eval/judge_agreement.py --input labels.csv [--threshold 0.6] [--json]

Exit code 0 if κ ≥ threshold; 1 otherwise. Designed for documented
calibration passes (ADR 0016), not for the public CI path — the
labels themselves live on the private side of ADR 0005.

Implementation is dependency-free (stdlib only) so the eval surface
stays import-light. Cohen's κ and Spearman's ρ are implemented
inline; for n ≪ 100 the precision is identical to scipy.stats.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence


LABELS: tuple[str, ...] = ("supported", "partial", "insufficient")
# Ordinal mapping for Spearman correlation: ``supported`` is the
# strongest grounding claim, ``insufficient`` is the weakest.
_LABEL_RANK: dict[str, int] = {"supported": 2, "partial": 1, "insufficient": 0}

DEFAULT_THRESHOLD = 0.6


def _validate_label(value: str, *, field: str, case_id: str) -> str:
    if value not in LABELS:
        raise ValueError(
            f"{field}={value!r} for case_id={case_id!r} not in {LABELS}"
        )
    return value


def load_labels(path: Path) -> list[tuple[str, str, str]]:
    """Load ``(case_id, judge_status, human_status)`` rows from a CSV."""
    rows: list[tuple[str, str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"case_id", "judge_status", "human_status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path} missing required columns: {sorted(missing)}"
            )
        for raw in reader:
            case_id = (raw.get("case_id") or "").strip()
            if not case_id:
                continue  # tolerate blank trailing line
            judge = _validate_label(
                (raw.get("judge_status") or "").strip().lower(),
                field="judge_status",
                case_id=case_id,
            )
            human = _validate_label(
                (raw.get("human_status") or "").strip().lower(),
                field="human_status",
                case_id=case_id,
            )
            rows.append((case_id, judge, human))
    return rows


def cohens_kappa(judge: Sequence[str], human: Sequence[str]) -> float:
    """Cohen's κ over the LABELS vocabulary. NaN for empty inputs."""
    n = len(judge)
    if n == 0:
        return float("nan")
    if n != len(human):
        raise ValueError("judge and human label sequences differ in length")
    observed = sum(1 for a, b in zip(judge, human) if a == b) / n
    cj = Counter(judge)
    ch = Counter(human)
    expected = sum(cj[k] * ch[k] for k in LABELS) / (n * n)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def _rank_average(values: Sequence[float]) -> list[float]:
    """Return average 1-based ranks; ties share the mean rank of their run."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j + 2) / 2.0  # 1-based average across the tied run
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rho(judge: Sequence[str], human: Sequence[str]) -> float:
    """Spearman's ρ over the ordinal mapping. NaN if n<2 or zero variance."""
    n = len(judge)
    if n < 2 or n != len(human):
        return float("nan")
    rj = _rank_average([float(_LABEL_RANK[v]) for v in judge])
    rh = _rank_average([float(_LABEL_RANK[v]) for v in human])
    mj = sum(rj) / n
    mh = sum(rh) / n
    numerator = sum((rj[i] - mj) * (rh[i] - mh) for i in range(n))
    denominator = math.sqrt(
        sum((r - mj) ** 2 for r in rj) * sum((r - mh) ** 2 for r in rh)
    )
    if denominator == 0:
        return float("nan")
    return numerator / denominator


def confusion_matrix(
    judge: Sequence[str], human: Sequence[str]
) -> dict[str, dict[str, int]]:
    """``confusion[human][judge] = count``. Rows are human, columns are judge."""
    matrix: dict[str, dict[str, int]] = {
        h: {j: 0 for j in LABELS} for h in LABELS
    }
    for j, h in zip(judge, human):
        matrix[h][j] += 1
    return matrix


def compute_agreement(
    rows: Iterable[tuple[str, str, str]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Aggregate the agreement report from labeled rows.

    A NaN κ (zero variance, empty input) does not pass the threshold,
    so ``passes`` is conservatively False in that case.
    """
    materialised = list(rows)
    judges = [r[1] for r in materialised]
    humans = [r[2] for r in materialised]
    kappa = cohens_kappa(judges, humans)
    rho = spearman_rho(judges, humans)
    return {
        "n": len(materialised),
        "cohens_kappa": kappa,
        "spearman_rho": rho,
        "confusion": confusion_matrix(judges, humans),
        "threshold": threshold,
        "passes": (not math.isnan(kappa)) and kappa >= threshold,
    }


def _format_human(report: dict) -> str:
    lines: list[str] = [f"n = {report['n']}"]
    kappa = report["cohens_kappa"]
    if math.isnan(kappa):
        lines.append("Cohen's kappa  = nan  (no labeled cases or zero variance)")
    else:
        verdict = "PASS" if report["passes"] else "BELOW THRESHOLD"
        lines.append(
            f"Cohen's kappa  = {kappa:+.3f}  "
            f"({verdict}; threshold = {report['threshold']:.2f})"
        )
    rho = report["spearman_rho"]
    if math.isnan(rho):
        lines.append("Spearman rho   = nan")
    else:
        lines.append(f"Spearman rho   = {rho:+.3f}")
    lines.append("")
    lines.append("Confusion (rows = human, cols = judge):")
    header = "  " + " " * 18 + "  ".join(f"{lbl[:6]:>6}" for lbl in LABELS)
    lines.append(header)
    for h in LABELS:
        body = "  ".join(f"{report['confusion'][h][j]:>6d}" for j in LABELS)
        lines.append(f"  human={h:<13}  {body}")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute judge↔human agreement (Cohen's κ + Spearman ρ).",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="CSV with columns case_id,judge_status,human_status",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Pass threshold for Cohen's κ (default {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON instead of human-readable text.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rows = load_labels(args.input)
    report = compute_agreement(rows, threshold=args.threshold)
    if args.json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(_format_human(report))
    return 0 if report["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
