#!/usr/bin/env python3
"""Real-100 corpus EDA generator (4-axis profile).

Reads:
  - data/data_list.csv                         (metadata manifest, BOM-tolerant)
  - data/index/real100/index.json              (chunks for chunk_health + text_source)
  - reports/real100/baseline.aggregate.json    (eval aggregate by_query_type)
  - reports/real100/eval_summary.json          [optional] case_results for cross

Writes:
  - reports/real100/eda.md                     (markdown report)
  - reports/real100/eda.aggregate.json         (machine-readable dump)
  - reports/figures/real100_*.png|.svg         (matplotlib optional, 5-7 figures)

ADR 0005 boundary: raw RFP body / 사업명 / 사업 요약 / 파일명 are read only for
length statistics — never rendered to md/json. Agency names beyond top-10
are anonymized to ``agency_NN`` rank labels. The only public-facing string
fields that survive into output are 공고 번호 (procurement notice ID, public)
and 파일형식 (hwp/pdf).

Usage:
    python scripts/eda_real100.py [--data-list ...] [--index ...] [--baseline ...]
        [--eval-summary ...] [--out-md ...] [--out-json ...] [--figures-dir ...]
        [--seed 0]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from eval.scorers.chunk_health import compute_chunk_health  # noqa: E402


CSV_COL_AGENCY = "발주 기관"
CSV_COL_BUDGET = "사업 금액"
CSV_COL_TITLE = "사업명"
CSV_COL_SUMMARY = "사업 요약"
CSV_COL_TEXT = "텍스트"
CSV_COL_FORMAT = "파일형식"
CSV_COL_FILE_NAME = "파일명"
CSV_COL_NOTICE_ID = "공고 번호"
CSV_COL_NOTICE_ROUND = "공고 차수"
CSV_COL_PUBLISHED = "공개 일자"

OUTPUT_TOP_N_AGENCIES = 10
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_data_list(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def load_index(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_json_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Parsers / helpers
# ---------------------------------------------------------------------------

_BUDGET_NON_DIGIT = re.compile(r"[^0-9.\-]")


def parse_budget(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = _BUDGET_NON_DIGIT.sub("", raw)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        v = float(cleaned)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if pct <= 0:
        return float(sorted_values[0])
    if pct >= 1:
        return float(sorted_values[-1])
    idx = (len(sorted_values) - 1) * pct
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return float(sorted_values[lo]) * (1 - frac) + float(sorted_values[hi]) * frac


def safe_mean(values: Iterable[float]) -> float:
    arr = [v for v in values if v is not None]
    return float(mean(arr)) if arr else 0.0


def anonymize_agency(rank: int) -> str:
    """rank is 1-based; only called for rank > OUTPUT_TOP_N_AGENCIES."""
    return f"agency_{rank:02d}"


# ---------------------------------------------------------------------------
# Axis 1: Metadata domain
# ---------------------------------------------------------------------------

def axis1_metadata(rows: list[dict[str, str]]) -> dict[str, Any]:
    n = len(rows)
    agency_counts = Counter()
    for r in rows:
        name = (r.get(CSV_COL_AGENCY) or "").strip()
        agency_counts[name or "unknown"] += 1

    sorted_agencies = agency_counts.most_common()
    top = sorted_agencies[:OUTPUT_TOP_N_AGENCIES]
    tail = sorted_agencies[OUTPUT_TOP_N_AGENCIES:]
    other_count = sum(c for _, c in tail)

    budgets_raw = [parse_budget(r.get(CSV_COL_BUDGET)) for r in rows]
    budgets = sorted(b for b in budgets_raw if b is not None)
    budget_stats = {
        "available_count": len(budgets),
        "missing_count": n - len(budgets),
        "min": budgets[0] if budgets else 0.0,
        "max": budgets[-1] if budgets else 0.0,
        "p10": percentile(budgets, 0.10),
        "p50": percentile(budgets, 0.50),
        "p90": percentile(budgets, 0.90),
        "mean": float(mean(budgets)) if budgets else 0.0,
    }

    def length_stats(values: list[int]) -> dict[str, float]:
        s = sorted(values)
        return {
            "p50": percentile([float(v) for v in s], 0.50),
            "p95": percentile([float(v) for v in s], 0.95),
            "max": float(s[-1]) if s else 0.0,
            "mean": float(mean(values)) if values else 0.0,
        }

    title_lens = [len(r.get(CSV_COL_TITLE) or "") for r in rows]
    summary_lens = [len(r.get(CSV_COL_SUMMARY) or "") for r in rows]
    text_lens = [len(r.get(CSV_COL_TEXT) or "") for r in rows]

    fmt_counts = Counter((r.get(CSV_COL_FORMAT) or "").lower() or "unknown" for r in rows)

    months: Counter[str] = Counter()
    for r in rows:
        pub = parse_iso_datetime(r.get(CSV_COL_PUBLISHED))
        if pub is not None:
            months[pub.strftime("%Y-%m")] += 1

    return {
        "total_docs": n,
        "agency": {
            "unique_count": len(agency_counts),
            "top": [
                {"rank": i + 1, "name": name, "count": cnt}
                for i, (name, cnt) in enumerate(top)
            ],
            "tail_anonymized": [
                {"rank": OUTPUT_TOP_N_AGENCIES + i + 1, "label": anonymize_agency(OUTPUT_TOP_N_AGENCIES + i + 1), "count": cnt}
                for i, (_, cnt) in enumerate(tail)
            ],
            "other_count": other_count,
        },
        "budget_krw": budget_stats,
        "title_length_chars": length_stats(title_lens),
        "summary_length_chars": length_stats(summary_lens),
        "csv_text_length_chars": length_stats(text_lens),
        "file_format_counts": dict(sorted(fmt_counts.items())),
        "monthly_published_counts": dict(sorted(months.items())),
    }


# ---------------------------------------------------------------------------
# Axis 2: Chunk / index health
# ---------------------------------------------------------------------------

def _doc_id_of_chunk(chunk: dict[str, Any]) -> str:
    md = chunk.get("metadata") or {}
    return str(chunk.get("doc_id") or md.get("doc_id") or "unknown")


def axis2_chunk_health(index_data: dict[str, Any]) -> dict[str, Any]:
    chunks = index_data.get("chunks") or []
    corpus_health = compute_chunk_health(chunks)

    per_doc: Counter[str] = Counter()
    per_doc_lengths: dict[str, list[int]] = defaultdict(list)
    length_by_format: dict[str, list[int]] = defaultdict(list)

    for c in chunks:
        doc_id = _doc_id_of_chunk(c)
        per_doc[doc_id] += 1
        text_len = len(str(c.get("text") or ""))
        per_doc_lengths[doc_id].append(text_len)
        fmt = str((c.get("metadata") or {}).get("file_format") or "unknown").lower()
        length_by_format[fmt].append(text_len)

    counts_sorted = sorted(per_doc.values())
    per_doc_stats = {
        "n_docs": len(per_doc),
        "min": counts_sorted[0] if counts_sorted else 0,
        "p50": percentile([float(v) for v in counts_sorted], 0.50),
        "p95": percentile([float(v) for v in counts_sorted], 0.95),
        "max": counts_sorted[-1] if counts_sorted else 0,
        "mean": float(mean(counts_sorted)) if counts_sorted else 0.0,
    }

    length_by_format_stats: dict[str, dict[str, float]] = {}
    for fmt, lens in sorted(length_by_format.items()):
        sorted_lens = sorted(lens)
        length_by_format_stats[fmt] = {
            "count": len(lens),
            "p50": percentile([float(v) for v in sorted_lens], 0.50),
            "p95": percentile([float(v) for v in sorted_lens], 0.95),
            "max": float(sorted_lens[-1]) if sorted_lens else 0.0,
            "mean": float(mean(lens)) if lens else 0.0,
        }

    return {
        "corpus_chunk_health": corpus_health,
        "per_doc_chunk_count": per_doc_stats,
        "length_by_format": length_by_format_stats,
        # raw per-doc counts retained for plotting; doc_id is the public notice id
        "_per_doc_counts_sorted": counts_sorted,
        "_length_by_format_raw": {k: sorted(v) for k, v in length_by_format.items()},
    }


# ---------------------------------------------------------------------------
# Axis 3: text_source fallback patterns
# ---------------------------------------------------------------------------

def axis3_text_source(index_data: dict[str, Any]) -> dict[str, Any]:
    chunks = index_data.get("chunks") or []
    chunk_level: dict[str, Counter[str]] = defaultdict(Counter)
    doc_source: dict[str, tuple[str, str]] = {}

    for c in chunks:
        md = c.get("metadata") or {}
        fmt = str(md.get("file_format") or "unknown").lower()
        src = str(md.get("text_source") or "unknown")
        chunk_level[fmt][src] += 1
        doc_id = _doc_id_of_chunk(c)
        if doc_id not in doc_source:
            doc_source[doc_id] = (fmt, src)

    doc_level: dict[str, Counter[str]] = defaultdict(Counter)
    for fmt, src in doc_source.values():
        doc_level[fmt][src] += 1

    def serialize(d: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {k: dict(sorted(v.items())) for k, v in sorted(d.items())}

    return {
        "chunk_level_by_format": serialize(chunk_level),
        "doc_level_by_format": serialize(doc_level),
        "total_chunks": sum(sum(v.values()) for v in chunk_level.values()),
        "total_docs": len(doc_source),
    }


# ---------------------------------------------------------------------------
# Axis 4: Eval cross-decomposition
# ---------------------------------------------------------------------------

def _build_doc_id_to_format(rows: list[dict[str, str]]) -> dict[str, str]:
    table: dict[str, str] = {}
    for r in rows:
        notice = (r.get(CSV_COL_NOTICE_ID) or "").strip()
        fmt = (r.get(CSV_COL_FORMAT) or "").lower().strip()
        if notice and fmt:
            table[notice] = fmt
            # canonical doc_id form: <notice>-<round>
            rnd = (r.get(CSV_COL_NOTICE_ROUND) or "").strip()
            if rnd:
                table[f"{notice}-{rnd}"] = fmt
    return table


def _resolve_format(doc_id: str, table: dict[str, str]) -> str | None:
    if doc_id in table:
        return table[doc_id]
    base = doc_id.split("-")[0] if "-" in doc_id else doc_id
    return table.get(base)


def axis4_eval_cross(
    eval_summary: dict[str, Any] | None,
    baseline: dict[str, Any],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    base_by_qt = baseline.get("by_query_type") or {}
    cases = (eval_summary or {}).get("case_results") or []
    if not cases:
        return {
            "baseline_by_query_type": base_by_qt,
            "case_cross_available": False,
            "reason": "eval_summary.case_results not available locally",
        }

    fmt_table = _build_doc_id_to_format(rows)
    metrics_of_interest = ("accuracy", "groundedness", "citation_precision")

    cross_qt_fmt: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    by_doc_length_bucket: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    # doc-length tertile buckets using csv text length
    text_lens_sorted = sorted(len(r.get(CSV_COL_TEXT) or "") for r in rows)
    t1 = percentile([float(v) for v in text_lens_sorted], 1 / 3) if text_lens_sorted else 0
    t2 = percentile([float(v) for v in text_lens_sorted], 2 / 3) if text_lens_sorted else 0

    doc_id_to_text_len: dict[str, int] = {}
    for r in rows:
        notice = (r.get(CSV_COL_NOTICE_ID) or "").strip()
        if not notice:
            continue
        text_len = len(r.get(CSV_COL_TEXT) or "")
        doc_id_to_text_len[notice] = text_len
        rnd = (r.get(CSV_COL_NOTICE_ROUND) or "").strip()
        if rnd:
            doc_id_to_text_len[f"{notice}-{rnd}"] = text_len

    def text_len_bucket(text_len: int) -> str:
        if text_len <= t1:
            return "short"
        if text_len <= t2:
            return "medium"
        return "long"

    for c in cases:
        qt = c.get("query_type") or "unknown"
        eids = c.get("expected_doc_ids") or []
        fmts = sorted({f for eid in eids if (f := _resolve_format(eid, fmt_table))})
        fmt_key = "+".join(fmts) if fmts else "unknown"

        for metric in metrics_of_interest:
            v = c.get(metric)
            if isinstance(v, (int, float)):
                cross_qt_fmt[qt][fmt_key][metric].append(float(v))

        # doc length bucket — use first expected doc id
        if eids:
            first = eids[0]
            tl = doc_id_to_text_len.get(first)
            if tl is None and "-" in first:
                tl = doc_id_to_text_len.get(first.split("-")[0])
            if tl is not None:
                bucket = text_len_bucket(tl)
                for metric in metrics_of_interest:
                    v = c.get(metric)
                    if isinstance(v, (int, float)):
                        by_doc_length_bucket[bucket][metric].append(float(v))

    qt_fmt_means: dict[str, dict[str, dict[str, float]]] = {}
    for qt, fmt_block in cross_qt_fmt.items():
        qt_fmt_means[qt] = {}
        for fmt, metric_lists in fmt_block.items():
            qt_fmt_means[qt][fmt] = {
                m: safe_mean(metric_lists.get(m) or []) for m in metrics_of_interest
            }
            qt_fmt_means[qt][fmt]["n"] = float(
                max((len(metric_lists.get(m) or []) for m in metrics_of_interest), default=0)
            )

    length_bucket_means = {
        bucket: {
            m: safe_mean(by_doc_length_bucket[bucket].get(m) or [])
            for m in metrics_of_interest
        }
        for bucket in ("short", "medium", "long")
    }
    for bucket in length_bucket_means:
        any_metric = by_doc_length_bucket[bucket].get("accuracy") or []
        length_bucket_means[bucket]["n"] = float(len(any_metric))

    return {
        "baseline_by_query_type": base_by_qt,
        "case_cross_available": True,
        "n_cases": len(cases),
        "doc_length_tertile_thresholds": {"t1": t1, "t2": t2},
        "query_type_x_file_format": qt_fmt_means,
        "by_doc_length_bucket": length_bucket_means,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _fmt_num(v: Any, decimals: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_krw(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1e9:
        return f"{n/1e8:.2f}억"
    if n >= 1e7:
        return f"{n/1e7:.2f}천만"
    if n >= 1e4:
        return f"{n/1e4:.0f}만"
    return f"{n:.0f}"


def render_markdown(stats: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Real-100 Corpus EDA")
    lines.append("")
    lines.append(
        "Aggregate-only profile of the private 100-document RFP dataset. "
        "ADR 0005 boundary: 사업명 / 사업 요약 / 텍스트 / 파일명 are read for "
        "length statistics only; never rendered. Agency names beyond rank "
        f"{OUTPUT_TOP_N_AGENCIES} are anonymized to `agency_NN` labels."
    )
    lines.append("")
    lines.append(f"Sources: `{stats['_sources']['data_list']}`, `{stats['_sources']['index']}`, "
                 f"`{stats['_sources']['baseline']}`"
                 + (f", `{stats['_sources']['eval_summary']}`" if stats['_sources'].get('eval_summary') else ""))
    lines.append("")

    # ---------------- Axis 1 ----------------
    a1 = stats["axis1_metadata"]
    lines.append("## Axis 1 — Metadata domain")
    lines.append("")
    lines.append(f"- Total docs: **{a1['total_docs']}**")
    lines.append(f"- Unique agencies: **{a1['agency']['unique_count']}** "
                 f"(top {OUTPUT_TOP_N_AGENCIES} below, {a1['agency']['other_count']} docs in long tail)")
    lines.append(f"- File formats: " + ", ".join(f"`{k}`={v}" for k, v in a1["file_format_counts"].items()))
    lines.append("")
    lines.append("### Agency distribution (top)")
    lines.append("")
    lines.append("| rank | agency | doc count |")
    lines.append("|---|---|---|")
    for entry in a1["agency"]["top"]:
        lines.append(f"| {entry['rank']} | {entry['name']} | {entry['count']} |")
    if a1["agency"]["tail_anonymized"]:
        lines.append(f"| … | _(rank {OUTPUT_TOP_N_AGENCIES+1}+, anonymized)_ | {a1['agency']['other_count']} |")
    lines.append("")
    lines.append("### Budget (KRW) — available rows only")
    lines.append("")
    b = a1["budget_krw"]
    lines.append(f"- available: {b['available_count']} / missing: {b['missing_count']}")
    lines.append(f"- p10 / p50 / p90: **{_fmt_krw(b['p10'])} / {_fmt_krw(b['p50'])} / {_fmt_krw(b['p90'])}**")
    lines.append(f"- min / max: {_fmt_krw(b['min'])} / {_fmt_krw(b['max'])}")
    lines.append("")
    lines.append("### Text-length distribution (chars; raw text never rendered)")
    lines.append("")
    lines.append("| field | p50 | p95 | max | mean |")
    lines.append("|---|---|---|---|---|")
    for label, key in [("사업명", "title_length_chars"), ("사업 요약", "summary_length_chars"), ("CSV 텍스트", "csv_text_length_chars")]:
        s = a1[key]
        lines.append(f"| {label} | {_fmt_int(s['p50'])} | {_fmt_int(s['p95'])} | {_fmt_int(s['max'])} | {_fmt_num(s['mean'], 0)} |")
    lines.append("")
    months = a1["monthly_published_counts"]
    if months:
        lines.append(f"### Published-date timeline ({len(months)} months covered)")
        lines.append("")
        lines.append("| month | docs |")
        lines.append("|---|---|")
        for ym, c in months.items():
            lines.append(f"| {ym} | {c} |")
        lines.append("")

    # ---------------- Axis 2 ----------------
    a2 = stats["axis2_chunk_health"]
    lines.append("## Axis 2 — Chunk / index health")
    lines.append("")
    ch = a2["corpus_chunk_health"]
    lines.append(f"- total chunks: **{_fmt_int(ch['total_chunks'])}**")
    lines.append(f"- by format: " + ", ".join(f"`{k}`={v}" for k, v in ch["by_format"].items()))
    lens = ch["length_chars"]
    lines.append(f"- length p50 / p95 / max: **{_fmt_int(lens['p50'])} / {_fmt_int(lens['p95'])} / {_fmt_int(lens['max'])}** chars")
    lines.append(f"- empty / near-empty (<50): {ch['empty_chunks']} / {ch['near_empty_chunks']}")
    lines.append(f"- mid-sentence cut ratio: **{_fmt_num(ch['mid_sentence_cut_ratio'], 3)}**")
    lines.append(f"- HWP native table chunks: {ch['hwp_table_chunks']} (ratio of HWP chunks: {_fmt_num(ch['hwp_table_chunk_ratio'], 3)})")
    lines.append("")
    pd = a2["per_doc_chunk_count"]
    lines.append("### Per-document chunk count")
    lines.append("")
    lines.append("| n_docs | min | p50 | p95 | max | mean |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(f"| {pd['n_docs']} | {pd['min']} | {_fmt_num(pd['p50'], 1)} | {_fmt_num(pd['p95'], 1)} | {pd['max']} | {_fmt_num(pd['mean'], 1)} |")
    lines.append("")
    lbf = a2["length_by_format"]
    if lbf:
        lines.append("### Chunk length by file format")
        lines.append("")
        lines.append("| format | count | p50 | p95 | max | mean |")
        lines.append("|---|---|---|---|---|---|")
        for fmt, s in lbf.items():
            lines.append(f"| {fmt} | {s['count']} | {_fmt_int(s['p50'])} | {_fmt_int(s['p95'])} | {_fmt_int(s['max'])} | {_fmt_num(s['mean'], 0)} |")
        lines.append("")

    # ---------------- Axis 3 ----------------
    a3 = stats["axis3_text_source"]
    lines.append("## Axis 3 — `text_source` fallback distribution")
    lines.append("")
    lines.append(f"- total chunks: {_fmt_int(a3['total_chunks'])} across {a3['total_docs']} docs")
    lines.append("")
    lines.append("### Doc-level (one row per document)")
    lines.append("")
    sources_seen = sorted({s for fmt_block in a3["doc_level_by_format"].values() for s in fmt_block})
    if sources_seen:
        header = "| format | " + " | ".join(f"`{s}`" for s in sources_seen) + " | total |"
        sep = "|---|" + "---|" * (len(sources_seen) + 1)
        lines.append(header)
        lines.append(sep)
        for fmt, block in a3["doc_level_by_format"].items():
            row_total = sum(block.values())
            row = f"| {fmt} | " + " | ".join(str(block.get(s, 0)) for s in sources_seen) + f" | {row_total} |"
            lines.append(row)
    lines.append("")
    lines.append("### Chunk-level (one row per chunk)")
    lines.append("")
    sources_chunk = sorted({s for fmt_block in a3["chunk_level_by_format"].values() for s in fmt_block})
    if sources_chunk:
        header = "| format | " + " | ".join(f"`{s}`" for s in sources_chunk) + " | total |"
        sep = "|---|" + "---|" * (len(sources_chunk) + 1)
        lines.append(header)
        lines.append(sep)
        for fmt, block in a3["chunk_level_by_format"].items():
            row_total = sum(block.values())
            row = f"| {fmt} | " + " | ".join(str(block.get(s, 0)) for s in sources_chunk) + f" | {row_total} |"
            lines.append(row)
    lines.append("")

    # ---------------- Axis 4 ----------------
    a4 = stats["axis4_eval_cross"]
    lines.append("## Axis 4 — Eval cross-decomposition")
    lines.append("")
    lines.append("### Baseline `by_query_type` (from `baseline.aggregate.json`)")
    lines.append("")
    bqt = a4["baseline_by_query_type"]
    if bqt:
        metric_keys = sorted({k for v in bqt.values() for k in v if k != "num_predictions"})
        header = "| query_type | n | " + " | ".join(metric_keys) + " |"
        sep = "|---|" + "---|" * (1 + len(metric_keys))
        lines.append(header)
        lines.append(sep)
        for qt in sorted(bqt):
            row = bqt[qt]
            n = row.get("num_predictions", "—")
            cells = " | ".join(_fmt_num(row.get(k), 3) for k in metric_keys)
            lines.append(f"| {qt} | {n} | {cells} |")
        lines.append("")
    if a4["case_cross_available"]:
        lines.append(f"### query_type × file_format ({a4['n_cases']} cases)")
        lines.append("")
        lines.append("| query_type | file_format | n | accuracy | groundedness | citation_precision |")
        lines.append("|---|---|---|---|---|---|")
        for qt in sorted(a4["query_type_x_file_format"]):
            for fmt in sorted(a4["query_type_x_file_format"][qt]):
                row = a4["query_type_x_file_format"][qt][fmt]
                lines.append(
                    f"| {qt} | {fmt} | {int(row.get('n', 0))} | "
                    f"{_fmt_num(row.get('accuracy'), 3)} | "
                    f"{_fmt_num(row.get('groundedness'), 3)} | "
                    f"{_fmt_num(row.get('citation_precision'), 3)} |"
                )
        lines.append("")
        thr = a4["doc_length_tertile_thresholds"]
        lines.append(f"### By doc-length tertile (CSV text length; t1={_fmt_int(thr['t1'])}, t2={_fmt_int(thr['t2'])} chars)")
        lines.append("")
        lines.append("| bucket | n | accuracy | groundedness | citation_precision |")
        lines.append("|---|---|---|---|---|")
        for bucket in ("short", "medium", "long"):
            row = a4["by_doc_length_bucket"][bucket]
            lines.append(
                f"| {bucket} | {int(row.get('n', 0))} | "
                f"{_fmt_num(row.get('accuracy'), 3)} | "
                f"{_fmt_num(row.get('groundedness'), 3)} | "
                f"{_fmt_num(row.get('citation_precision'), 3)} |"
            )
        lines.append("")
    else:
        lines.append(f"_{a4.get('reason', 'cross unavailable')}_")
        lines.append("")

    # ---------------- Figures pointer ----------------
    # Render filenames only (no directory) so the md is deterministic across
    # different --figures-dir invocations. Reviewers can locate the files via
    # the path noted in the script's stdout.
    figs = stats.get("_figures_written") or []
    if figs:
        stems = sorted({Path(fp).name for fp in figs})
        lines.append("## Figures")
        lines.append("")
        for name in stems:
            lines.append(f"- `{name}`")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def render_figures(stats: dict[str, Any], out_dir: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def _save(fig, stem: str) -> None:
        for ext in ("png", "svg"):
            p = out_dir / f"{stem}.{ext}"
            fig.savefig(p, dpi=144)
            try:
                written.append(str(p.relative_to(REPO_ROOT)))
            except ValueError:
                written.append(str(p))
        plt.close(fig)

    a1 = stats["axis1_metadata"]
    a2 = stats["axis2_chunk_health"]
    a3 = stats["axis3_text_source"]

    # Figure 1: agency top-N bar (rank labels only — keeps figure ascii-safe
    # and reinforces ADR 0005 anonymization). Raw agency names live in the md.
    top = a1["agency"]["top"]
    if top:
        fig, ax = plt.subplots(figsize=(9, 5))
        labels = [f"#{t['rank']}" for t in top] + (["tail"] if a1["agency"]["other_count"] else [])
        counts = [t["count"] for t in top] + ([a1["agency"]["other_count"]] if a1["agency"]["other_count"] else [])
        ax.barh(range(len(labels))[::-1], counts, color="tab:blue")
        ax.set_yticks(range(len(labels))[::-1])
        ax.set_yticklabels(labels, fontsize=10)
        ax.set_xlabel("Doc count")
        ax.set_title(f"Top {OUTPUT_TOP_N_AGENCIES} agencies by doc count (rank-labeled)")
        ax.grid(True, axis="x", linestyle=":", alpha=0.4)
        fig.tight_layout()
        _save(fig, "real100_meta_agency_topN")

    # Figure 2: budget log-histogram
    b = a1["budget_krw"]
    if b["available_count"] > 0:
        # need raw budgets — recompute from stats? We don't keep them. Plot percentile markers.
        fig, ax = plt.subplots(figsize=(8, 4))
        markers = [("min", b["min"]), ("p10", b["p10"]), ("p50", b["p50"]), ("p90", b["p90"]), ("max", b["max"])]
        markers = [(label, v) for label, v in markers if v and v > 0]
        if markers:
            xs = [v for _, v in markers]
            ax.scatter(xs, [1] * len(xs), s=80, color="tab:orange")
            for label, v in markers:
                ax.annotate(label, (v, 1), textcoords="offset points", xytext=(0, 8),
                            ha="center", fontsize=9)
            ax.set_xscale("log")
            ax.set_yticks([])
            ax.set_xlabel("Budget (KRW, log scale)")
            ax.set_title(f"Budget percentiles — {b['available_count']} docs with budget")
            ax.grid(True, axis="x", linestyle=":", alpha=0.4, which="both")
            fig.tight_layout()
            _save(fig, "real100_meta_budget_loghist")

    # Figure 3: monthly timeline
    months = a1["monthly_published_counts"]
    if months:
        fig, ax = plt.subplots(figsize=(10, 4))
        labels = list(months.keys())
        vals = list(months.values())
        ax.bar(range(len(labels)), vals, color="tab:green")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("Docs published")
        ax.set_title("Published-date timeline (real-100)")
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        fig.tight_layout()
        _save(fig, "real100_meta_timeline")

    # Figure 4: per-doc chunk count histogram
    counts = a2.get("_per_doc_counts_sorted") or []
    if counts:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(counts, bins=min(30, len(set(counts))), color="tab:purple", edgecolor="black", alpha=0.85)
        ax.set_xlabel("Chunks per document")
        ax.set_ylabel("Doc count")
        ax.set_title(f"Per-document chunk count (n={len(counts)} docs)")
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        fig.tight_layout()
        _save(fig, "real100_chunks_per_doc_hist")

    # Figure 5: chunk length boxplot by format
    by_fmt = a2.get("_length_by_format_raw") or {}
    if by_fmt:
        fmts = sorted(by_fmt.keys())
        data = [by_fmt[f] for f in fmts]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.boxplot(data, tick_labels=fmts, showfliers=False)
        ax.set_ylabel("Chunk length (chars)")
        ax.set_title("Chunk length by file format (outliers hidden)")
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        fig.tight_layout()
        _save(fig, "real100_chunks_length_box")

    # Figure 6: text_source stacked bar by format (doc-level)
    doc_level = a3["doc_level_by_format"]
    if doc_level:
        sources = sorted({s for v in doc_level.values() for s in v})
        fmts = sorted(doc_level.keys())
        fig, ax = plt.subplots(figsize=(7, 4))
        bottom = [0.0] * len(fmts)
        palette = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
        for i, src in enumerate(sources):
            vals = [doc_level[f].get(src, 0) for f in fmts]
            ax.bar(fmts, vals, bottom=bottom, label=src, color=palette[i % len(palette)])
            bottom = [bottom[j] + vals[j] for j in range(len(fmts))]
        ax.set_ylabel("Doc count")
        ax.set_title("text_source distribution by format (doc-level)")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        fig.tight_layout()
        _save(fig, "real100_text_source_stacked")

    # Figure 7: eval cross (only if available)
    a4 = stats["axis4_eval_cross"]
    bqt = a4.get("baseline_by_query_type") or {}
    if bqt:
        qts = sorted(bqt.keys())
        metrics = ["accuracy", "groundedness", "citation_precision"]
        # filter to metrics that exist in at least one row
        metrics = [m for m in metrics if any(m in bqt[qt] for qt in qts)]
        if metrics:
            fig, ax = plt.subplots(figsize=(9, 4.5))
            n_qt = len(qts)
            width = 0.8 / max(len(metrics), 1)
            x = list(range(n_qt))
            palette = ["tab:blue", "tab:orange", "tab:green"]
            for i, m in enumerate(metrics):
                vals = [bqt[qt].get(m) or 0.0 for qt in qts]
                ax.bar([xi + (i - (len(metrics) - 1) / 2) * width for xi in x], vals,
                       width=width, label=m, color=palette[i % len(palette)])
            ax.set_xticks(x)
            ax.set_xticklabels(qts)
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("Score (0–1)")
            ax.set_title("Baseline metrics by query_type")
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, axis="y", linestyle=":", alpha=0.4)
            fig.tight_layout()
            _save(fig, "real100_eval_cross")

    return sorted(written)


# ---------------------------------------------------------------------------
# Aggregate-only JSON serialization (strips internal _raw fields)
# ---------------------------------------------------------------------------

_PRIVATE_KEYS = ("_per_doc_counts_sorted", "_length_by_format_raw", "_sources", "_figures_written")


def strip_private(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if k not in _PRIVATE_KEYS}
    if isinstance(obj, list):
        return [strip_private(x) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-list", default="data/data_list.csv")
    parser.add_argument("--index", default="data/index/real100/index.json")
    parser.add_argument("--baseline", default="reports/real100/baseline.aggregate.json")
    parser.add_argument("--eval-summary", default="reports/real100/eval_summary.json")
    parser.add_argument("--out-md", default="reports/real100/eda.md")
    parser.add_argument("--out-json", default="reports/real100/eda.aggregate.json")
    parser.add_argument("--figures-dir", default="reports/figures")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    random.seed(args.seed)

    rows = load_data_list(Path(args.data_list))
    index_data = load_index(Path(args.index))
    baseline = load_json_optional(Path(args.baseline)) or {}
    eval_summary = load_json_optional(Path(args.eval_summary))

    stats: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "axis1_metadata": axis1_metadata(rows),
        "axis2_chunk_health": axis2_chunk_health(index_data),
        "axis3_text_source": axis3_text_source(index_data),
        "axis4_eval_cross": axis4_eval_cross(eval_summary, baseline, rows),
        "_sources": {
            "data_list": args.data_list,
            "index": args.index,
            "baseline": args.baseline,
            "eval_summary": args.eval_summary if eval_summary else None,
        },
    }

    figures_written = render_figures(stats, Path(args.figures_dir))
    stats["_figures_written"] = figures_written

    md_text = render_markdown(stats)
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md_text, encoding="utf-8")

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    json_obj = strip_private(stats)
    with out_json.open("w", encoding="utf-8") as fh:
        json.dump(json_obj, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
    if figures_written:
        print(f"Wrote {len(figures_written)} figure files under {args.figures_dir}")
    else:
        print("matplotlib not available — figures skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
