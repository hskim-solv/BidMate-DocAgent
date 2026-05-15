#!/usr/bin/env python3
"""Table extraction metrics (issue #790, PR-A3).

Scores an extractor JSONL (PR-A0 ``pyhwp_native_tables`` or PR-A1
``upstage_document_parser``) against a human-labeled golden JSONL. Both
inputs share ``eval/data/table_extraction_golden.schema.json``.

Computed metrics (parser-intrinsic, all micro-aggregated across the
intersection of ``(doc_id, table_index)`` pairs):

* **Cell-level F1** — Levenshtein-similarity match (default threshold
  0.9, NFKC + whitespace-collapse + casefold) over the intersection of
  ``(row, col)`` coordinates.
* **Table-level recall / precision / F1** — does the extractor find
  each golden table? Does it fabricate any?
* **Merge-cell preservation rate** — fraction of golden cells with
  ``rowspan > 1`` or ``colspan > 1`` that the extractor reproduces at
  the same coordinate with matching span dimensions.

PR-B consumes the output JSON when evaluating the preregistered
decision criteria (Δ ≥ +5%p threshold for adopting the Upstage opt-in
ablation).

Off-pipeline. Pure stdlib (no Levenshtein library); load-bearing paths
untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_SIMILARITY_THRESHOLD = 0.9
PER_PAIR_SAMPLE_CAP = 50


# --- text normalization + Levenshtein (stdlib, no deps) ---------------


def _normalize_text(text: Any) -> str:
    """NFKC + whitespace-collapse + casefold. Preserves punctuation.

    RFP IDs (``FR-007``, ``R3.1``) and scores (``60점``) carry meaning
    in punctuation, so we do not strip it.
    """
    if text is None:
        return ""
    nfkc = unicodedata.normalize("NFKC", str(text))
    return " ".join(nfkc.split()).casefold()


def levenshtein(a: str, b: str) -> int:
    """Wagner-Fischer edit distance. O(len(a)*len(b)) time, O(min(...)) space."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            ins = curr[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]


def similarity(a: Any, b: Any) -> float:
    """Levenshtein similarity in ``[0, 1]`` after normalization."""
    na = _normalize_text(a)
    nb = _normalize_text(b)
    if not na and not nb:
        return 1.0
    m = max(len(na), len(nb))
    if m == 0:
        return 1.0
    return 1.0 - levenshtein(na, nb) / m


# --- JSONL + indexing ------------------------------------------------


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _index_records(records: Iterable[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for rec in records:
        doc_id = str(rec.get("doc_id", ""))
        table_index = int(rec.get("table_index", 0) or 0)
        out[(doc_id, table_index)] = rec
    return out


def _cells_by_coord(rec: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for cell in rec.get("cells") or []:
        coord = (int(cell.get("row", 0) or 0), int(cell.get("col", 0) or 0))
        out[coord] = cell
    return out


# --- per-table metrics ------------------------------------------------


def _p_r_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else (1.0 if fn == 0 else 0.0)
    r = tp / (tp + fn) if (tp + fn) else (1.0 if fp == 0 else 0.0)
    f1 = (2 * p * r) / (p + r) if (p + r) else 0.0
    return p, r, f1


def cell_f1(
    golden_rec: dict[str, Any],
    extracted_rec: dict[str, Any],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    """Cell-level F1 over coord intersection with fuzzy text match.

    TP = golden coord present in extracted AND similarity ≥ threshold.
    FP = extracted coord absent from golden OR fails similarity.
    FN = golden coord absent from extracted OR fails similarity.
    """
    g_cells = _cells_by_coord(golden_rec)
    e_cells = _cells_by_coord(extracted_rec)
    tp = 0
    for coord, g_cell in g_cells.items():
        e_cell = e_cells.get(coord)
        if not e_cell:
            continue
        if similarity(g_cell.get("text", ""), e_cell.get("text", "")) >= similarity_threshold:
            tp += 1
    fp = len(e_cells) - tp
    fn = len(g_cells) - tp
    p, r, f1 = _p_r_f1(tp, fp, fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


def merge_cell_preservation(
    golden_rec: dict[str, Any],
    extracted_rec: dict[str, Any],
) -> dict[str, Any]:
    """Fraction of golden merged cells reproduced with matching span dims."""
    g_cells = _cells_by_coord(golden_rec)
    e_cells = _cells_by_coord(extracted_rec)
    g_merged = {
        coord: cell
        for coord, cell in g_cells.items()
        if int(cell.get("rowspan", 1) or 1) > 1
        or int(cell.get("colspan", 1) or 1) > 1
    }
    if not g_merged:
        return {"golden_merge_count": 0, "preserved": 0, "rate": 1.0}
    preserved = 0
    for coord, g_cell in g_merged.items():
        e_cell = e_cells.get(coord)
        if not e_cell:
            continue
        if int(e_cell.get("rowspan", 1) or 1) == int(g_cell.get("rowspan", 1) or 1) and int(
            e_cell.get("colspan", 1) or 1
        ) == int(g_cell.get("colspan", 1) or 1):
            preserved += 1
    return {
        "golden_merge_count": len(g_merged),
        "preserved": preserved,
        "rate": round(preserved / len(g_merged), 4),
    }


# --- aggregate -------------------------------------------------------


def table_level_metrics(
    golden: Iterable[dict[str, Any]],
    extracted: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    g_keys = set(_index_records(golden))
    e_keys = set(_index_records(extracted))
    tp = len(g_keys & e_keys)
    fp = len(e_keys - g_keys)
    fn = len(g_keys - e_keys)
    p, r, f1 = _p_r_f1(tp, fp, fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


def compute(
    golden: list[dict[str, Any]],
    extracted: list[dict[str, Any]],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    """Run all metrics and return a summary dict."""
    g_index = _index_records(golden)
    e_index = _index_records(extracted)
    common = sorted(set(g_index) & set(e_index))

    per_pair: list[dict[str, Any]] = []
    total_tp = total_fp = total_fn = 0
    total_merge_g = total_merge_p = 0
    for key in common:
        cell = cell_f1(
            g_index[key],
            e_index[key],
            similarity_threshold=similarity_threshold,
        )
        merge = merge_cell_preservation(g_index[key], e_index[key])
        per_pair.append(
            {
                "doc_id": key[0],
                "table_index": key[1],
                "cell_f1": cell,
                "merge_preservation": merge,
            }
        )
        total_tp += cell["tp"]
        total_fp += cell["fp"]
        total_fn += cell["fn"]
        total_merge_g += merge["golden_merge_count"]
        total_merge_p += merge["preserved"]

    micro_p, micro_r, micro_f1 = _p_r_f1(total_tp, total_fp, total_fn)
    merge_rate = (total_merge_p / total_merge_g) if total_merge_g else 1.0

    return {
        "similarity_threshold": similarity_threshold,
        "table_level": table_level_metrics(golden, extracted),
        "cell_level_micro": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "precision": round(micro_p, 4),
            "recall": round(micro_r, 4),
            "f1": round(micro_f1, 4),
        },
        "merge_cell_preservation_micro": {
            "golden_merge_count": total_merge_g,
            "preserved": total_merge_p,
            "rate": round(merge_rate, 4),
        },
        "common_table_pair_count": len(common),
        "per_pair_sample": per_pair[:PER_PAIR_SAMPLE_CAP],
    }


# --- CLI -------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute table-extraction metrics (issue #790, PR-A3). "
            "Inputs share eval/data/table_extraction_golden.schema.json. "
            "Off-pipeline."
        )
    )
    parser.add_argument(
        "--golden",
        type=Path,
        required=True,
        help="Human-labeled golden JSONL.",
    )
    parser.add_argument(
        "--extracted",
        type=Path,
        required=True,
        help="Extractor JSONL (PR-A0 native or PR-A1 upstage output).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "reports" / "table_extraction_metrics.json",
        help=(
            "Output metrics JSON path "
            "(default: reports/table_extraction_metrics.json)."
        ),
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help=(
            "Levenshtein similarity threshold for cell text match "
            "(default: 0.9)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for label, path in (("--golden", args.golden), ("--extracted", args.extracted)):
        if not path.exists() or not path.is_file():
            print(
                f"error: {label} does not exist or is not a file: {path}",
                file=sys.stderr,
            )
            return 2
    golden = load_jsonl(args.golden)
    extracted = load_jsonl(args.extracted)
    report = compute(
        golden,
        extracted,
        similarity_threshold=args.similarity_threshold,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {k: v for k, v in report.items() if k != "per_pair_sample"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote {args.out}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
