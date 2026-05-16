"""Chunk-level corpus sanity metrics (issue #715).

Bookend to ``eval/scorers/chunk_metrics.py``: that module measures *retrieval*
quality given the gold set; this module measures the *chunks themselves* —
length distribution, near-empty count, mid-sentence cuts, HWP table coverage.
The two are deliberately kept in separate files so retrieval-time scorers
and ingest-time corpus health stay independently testable.

``compute_chunk_health`` is called once at index-build time by
``scripts/build_index.py`` and the result is folded into
``ingestion_report.json`` under ``summary.chunk_health``. The output shape is
stable JSON-serializable.
"""

from __future__ import annotations

import re
from statistics import mean
from typing import Any, Iterable


_SENTENCE_ENDERS_ASCII = (".", "!", "?", "。", "…")

# Issue #902: kordoc (ADR 0049) leaves a ``[중첩 테이블 #N]`` placeholder when a
# nested table cannot be reconstructed in markdown. 89/100 files in the private
# real100 corpus contain at least one marker, so the loss is the dominant
# kordoc gap. Count + sample so a regression points to specific files / lines.
_NESTED_TABLE_RE = re.compile(r"\[중첩 테이블 #(\d+)\]")

# Cap on samples folded into the report — prevents the JSON from ballooning on
# pathological corpora while keeping enough to triage. Top-N by marker count
# is not worth the complexity; first-N (deterministic insertion order) is
# fine because the report's audience is "which files broke and where".
_NESTED_TABLE_SAMPLE_LIMIT = 20

# Adjacent text captured after the marker so the sample reads as "here's what
# the nested table got flattened into". 80 chars is enough for a phrase but
# short enough that 20 samples stay under ~2 KB.
_NESTED_TABLE_ADJACENT_CHARS = 80
# Heuristic Korean sentence-final endings. Conservative set — false negatives
# (mis-flagging a clean chunk as mid-cut) are preferred over false positives
# (silently passing a truncated chunk). Mirrors common formal RFP verb
# endings; informal speech endings are intentionally excluded.
_SENTENCE_ENDERS_KOREAN = ("다", "음", "임", "함", "됨", "요", "오", "라", "어", "지")

# Closing brackets / quotes that may follow a true sentence terminator.
# Stripping one of these before checking the terminal char lets ``'다.'`` and
# ``'다."'`` and ``'다)'`` all register as terminated.
_TRAILING_CLOSERS = "”\"')]}」』"


def _percentile(sorted_values: list[int], pct: float) -> float:
    """Linear-interpolation percentile (NIST type 7 / numpy default).

    ``sorted_values`` MUST be sorted ascending. Returns 0.0 for empty input.
    """
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


def _is_hwp_table_chunk(chunk: dict[str, Any]) -> bool:
    """Return True for chunks emitted from the HWP native-tables loader.

    Pattern is set in ``ingestion.build_sections_with_native_tables`` — table
    sections are labeled ``"표 N (HWP native)"``. We require both the prefix
    and the marker so plain "표 ..." section headings in a PDF/HWP CSV body do
    not get mis-flagged.
    """
    metadata = chunk.get("metadata") or {}
    if metadata.get("file_format") != "hwp":
        return False
    section = str(chunk.get("section") or "")
    return section.startswith("표 ") and "HWP native" in section


def _is_mid_sentence_cut(text: str) -> bool:
    """True if the chunk does not end in a recognized sentence terminator.

    Conservative heuristic — Korean morphology means a hard answer is
    impossible without a full parser. We treat a chunk ending in ASCII /
    full-width sentence terminators (., !, ?, 。, …) or one of the common
    formal Korean sentence-final morphemes (다, 음, 임, 함, 됨, …) as
    "ended cleanly". Trailing closing brackets / quotes are stripped before
    the check.

    Empty chunks return ``False`` here — they are accounted for separately by
    the ``empty_chunks`` metric and should not double-count.
    """
    stripped = text.rstrip()
    if not stripped:
        return False
    while stripped and stripped[-1] in _TRAILING_CLOSERS:
        stripped = stripped[:-1]
    if not stripped:
        return False
    last = stripped[-1]
    if last in _SENTENCE_ENDERS_ASCII:
        return False
    if last in _SENTENCE_ENDERS_KOREAN:
        return False
    return True


def compute_chunk_health(chunks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute corpus-level chunk sanity metrics.

    Args:
        chunks: iterable of chunk dicts as produced by ``rag_core.make_chunk``.
            Each item is expected to expose ``text``, ``metadata.file_format``,
            and ``section``. Missing fields are treated leniently (empty
            string / ``"unknown"`` format) so the function never raises on a
            half-formed corpus — a partially-built index should still produce
            a usable health report.

    Returns:
        A JSON-serializable dict with keys:

        - ``total_chunks``: int
        - ``by_format``: ``{file_format: count}``
        - ``length_chars``: ``{p50, p95, max, min, mean}`` (zero-filled when
          there are no chunks)
        - ``empty_chunks``: count where ``len(text) == 0``
        - ``near_empty_chunks``: count where ``0 < len(text) < 50``
        - ``mid_sentence_cut_ratio``: float in ``[0, 1]``, computed over
          non-table non-empty chunks. Table chunks are excluded because they
          have no sentence structure to terminate.
        - ``hwp_table_chunks``: count of HWP native-tables-mode table chunks
        - ``hwp_table_chunk_ratio``: float in ``[0, 1]``,
          ``hwp_table_chunks / (total HWP chunks)``; ``0.0`` when there are no
          HWP chunks.
        - ``nested_table_loss_count``: total ``[중첩 테이블 #N]`` markers across
          the corpus (issue #902 — kordoc gap surface).
        - ``nested_table_loss_files``: number of distinct ``doc_id`` values
          that contain at least one marker.
        - ``nested_table_loss_samples``: list of up to
          ``_NESTED_TABLE_SAMPLE_LIMIT`` dicts with ``doc_id``, ``marker_id``,
          and ``adjacent_text`` (first 80 chars after the marker). Insertion
          order is deterministic — first markers encountered, which makes the
          report stable across re-runs of the same index.
    """
    chunk_list = list(chunks)
    total = len(chunk_list)
    by_format: dict[str, int] = {}
    lengths: list[int] = []
    empty = 0
    near_empty = 0
    hwp_total = 0
    hwp_table = 0
    eligible_for_cut = 0
    mid_cut = 0
    nested_total = 0
    nested_files: set[str] = set()
    nested_samples: list[dict[str, Any]] = []

    for chunk in chunk_list:
        text = str(chunk.get("text") or "")
        length = len(text)
        lengths.append(length)
        metadata = chunk.get("metadata") or {}
        fmt = str(metadata.get("file_format") or "unknown")
        by_format[fmt] = by_format.get(fmt, 0) + 1
        if length == 0:
            empty += 1
        elif length < 50:
            near_empty += 1
        is_table = _is_hwp_table_chunk(chunk)
        if fmt == "hwp":
            hwp_total += 1
            if is_table:
                hwp_table += 1
        if length > 0 and not is_table:
            eligible_for_cut += 1
            if _is_mid_sentence_cut(text):
                mid_cut += 1

        # Issue #902: ``[중첩 테이블 #N]`` is kordoc's marker for a nested
        # table that could not be reconstructed in markdown. We count every
        # occurrence (89/100 files have at least one in the real100 corpus),
        # track distinct documents, and keep a deterministic prefix of
        # samples so regression triage points to specific files / IDs.
        if text:
            doc_id = str(chunk.get("doc_id") or "")
            for match in _NESTED_TABLE_RE.finditer(text):
                nested_total += 1
                if doc_id:
                    nested_files.add(doc_id)
                if len(nested_samples) < _NESTED_TABLE_SAMPLE_LIMIT:
                    end = match.end()
                    adjacent = text[end : end + _NESTED_TABLE_ADJACENT_CHARS]
                    nested_samples.append(
                        {
                            "doc_id": doc_id,
                            "marker_id": match.group(1),
                            "adjacent_text": adjacent,
                        }
                    )

    lengths_sorted = sorted(lengths)
    length_stats = {
        "p50": _percentile(lengths_sorted, 0.5),
        "p95": _percentile(lengths_sorted, 0.95),
        "max": float(lengths_sorted[-1]) if lengths_sorted else 0.0,
        "min": float(lengths_sorted[0]) if lengths_sorted else 0.0,
        "mean": float(mean(lengths)) if lengths else 0.0,
    }
    mid_ratio = (mid_cut / eligible_for_cut) if eligible_for_cut else 0.0
    hwp_table_ratio = (hwp_table / hwp_total) if hwp_total else 0.0

    return {
        "total_chunks": total,
        "by_format": by_format,
        "length_chars": length_stats,
        "empty_chunks": empty,
        "near_empty_chunks": near_empty,
        "mid_sentence_cut_ratio": mid_ratio,
        "hwp_table_chunks": hwp_table,
        "hwp_table_chunk_ratio": hwp_table_ratio,
        "nested_table_loss_count": nested_total,
        "nested_table_loss_files": len(nested_files),
        "nested_table_loss_samples": nested_samples,
    }
