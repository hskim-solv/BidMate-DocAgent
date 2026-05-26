#!/usr/bin/env python3
"""Export private index chunks to local Markdown plus aggregate inventory.

The Markdown output is raw private content and must be written only under a
gitignored local directory. The optional aggregate JSON is public-safe: counts,
rates, closed labels, and hashed provenance only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.private_data_quality_audit_utils import (  # noqa: E402
    assert_public_safe,
    gitignored_or_outside_repo,
    page_metadata_present,
    percentile,
)

TABLE_RE = re.compile(r"(<table\b|</t[dh]>|rowspan=|colspan=|\|[^\n]+\||\t)", re.IGNORECASE)
DATE_RE = re.compile(r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}\s*년\s*\d{1,2}\s*월|\d{1,2}\s*월\s*\d{1,2}\s*일)")
SCORE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:점|%)|(?:배점|평가점수|정량|정성)")
AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:원|천원|만원|억원|%)|(?:예산|금액|사업비)")
LOCAL_SUFFIX = ".local.json"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("text") or "")


def _doc_ref(chunk: dict[str, Any]) -> str:
    return str(chunk.get("doc_id") or (chunk.get("metadata") or {}).get("doc_id") or "<missing>")


def _page_start(chunk: dict[str, Any]) -> int:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    for node in (chunk, metadata):
        span = node.get("page_span")
        if isinstance(span, list) and span:
            try:
                return int(span[0])
            except (TypeError, ValueError):
                pass
        for key in ("page", "page_number", "page_start"):
            value = node.get(key)
            if value not in (None, ""):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return 10**9


def _safe_hash(value: Any, namespace: str) -> str:
    digest = hashlib.sha256(f"{namespace}\0{value}".encode("utf-8")).hexdigest()[:16]
    return f"redacted_{digest}"


def _source(path: Path) -> dict[str, Any]:
    return {
        "artifact": "private_local_index",
        "sha256_12": hashlib.sha256(path.read_bytes()).hexdigest()[:12],
    }


def _length_block(values: list[int]) -> dict[str, Any]:
    return {
        "min": min(values) if values else None,
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def _condition_counts(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for chunks in grouped.values():
        texts = [_text(chunk) for chunk in chunks]
        joined = "\n".join(texts)
        chars = len(joined.strip())
        table_hits = sum(1 for text in texts if TABLE_RE.search(text))
        date_hits = len(DATE_RE.findall(joined))
        score_hits = len(SCORE_RE.findall(joined))
        amount_hits = len(AMOUNT_RE.findall(joined))
        page_count = len({p for p in (_page_start(chunk) for chunk in chunks) if p != 10**9}) or len(chunks)
        chars_per_page = chars / page_count if page_count else 0.0
        if chars == 0:
            counts["empty_text"] += 1
        if chars_per_page < 120:
            counts["image_only_or_low_text"] += 1
        if table_hits >= 3:
            counts["table_heavy"] += 1
        if table_hits >= 3 and score_hits >= 3:
            counts["score_table_like"] += 1
        if table_hits >= 3 and date_hits >= 5:
            counts["schedule_or_gantt_like"] += 1
        if amount_hits >= 5:
            counts["amount_heavy"] += 1
        if all(not page_metadata_present(chunk) for chunk in chunks):
            counts["page_metadata_missing"] += 1
    for key in (
        "empty_text",
        "image_only_or_low_text",
        "table_heavy",
        "score_table_like",
        "schedule_or_gantt_like",
        "amount_heavy",
        "page_metadata_missing",
    ):
        counts.setdefault(key, 0)
    return dict(sorted(counts.items()))


def export_markdown(index: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    chunks = [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        grouped[_doc_ref(chunk)].append(chunk)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    for idx, (doc_ref, doc_chunks) in enumerate(sorted(grouped.items()), start=1):
        doc_chunks.sort(key=lambda chunk: (_page_start(chunk), str(chunk.get("chunk_id") or "")))
        filename = f"doc_{idx:03d}.md"
        body = "\n\n".join(_text(chunk).strip() for chunk in doc_chunks if _text(chunk).strip())
        (out_dir / filename).write_text(body + ("\n" if body else ""), encoding="utf-8")
        manifest_rows.append(
            {
                "doc_ref": _safe_hash(doc_ref, "doc"),
                "markdown_file": filename,
                "chunk_count": len(doc_chunks),
                "content_chars": len(body),
            }
        )
    manifest_path = out_dir / f"export_manifest{LOCAL_SUFFIX}"
    manifest_path.write_text(
        json.dumps({"documents": manifest_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"grouped": grouped, "manifest_rows": manifest_rows}


def build_aggregate(index: dict[str, Any], *, index_path: Path, out_dir: Path, exported: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]
    grouped = exported["grouped"]
    lengths = [len(_text(chunk)) for chunk in chunks]
    page_ready = sum(1 for chunk in chunks if page_metadata_present(chunk))
    text_source_counts: Counter[str] = Counter()
    for chunk in chunks:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        source = metadata.get("text_source") or chunk.get("text_source") or "unknown"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(source))[:64] or "unknown"
        text_source_counts[safe] += 1
    aggregate = {
        "schema_version": 1,
        "profile_type": "private_real100_v2_parse_inventory",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": {"index": _source(index_path)},
        "markdown_export": {
            "location": "gitignored_private_dir",
            "document_markdown_count": len(exported["manifest_rows"]),
            "raw_content_written": True,
        },
        "population": {
            "document_count": len(grouped),
            "chunk_count": len(chunks),
        },
        "chunk_length_chars": _length_block(lengths),
        "page_metadata": {
            "ready_count": page_ready,
            "missing_count": len(chunks) - page_ready,
            "ready_rate": (page_ready / len(chunks)) if chunks else None,
        },
        "text_source_distribution": dict(sorted(text_source_counts.items())),
        "artifact_condition_counts": _condition_counts(grouped),
        "privacy": {
            "aggregate_only": True,
            "raw_questions_omitted": True,
            "raw_answers_omitted": True,
            "raw_evidence_omitted": True,
            "raw_text_omitted": True,
            "doc_ids_omitted": True,
            "chunk_ids_omitted": True,
            "filenames_omitted": True,
            "paths_omitted": True,
        },
    }
    assert_public_safe(aggregate)
    return aggregate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-aggregate", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not gitignored_or_outside_repo(args.out_dir, ROOT):
            raise ValueError("--out-dir must be gitignored or outside the repository")
        index = _load_json(args.index)
        exported = export_markdown(index, args.out_dir)
        if args.out_aggregate:
            aggregate = build_aggregate(index, index_path=args.index, out_dir=args.out_dir, exported=exported)
            args.out_aggregate.parent.mkdir(parents=True, exist_ok=True)
            args.out_aggregate.write_text(
                json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(
            "[OK] exported private markdown:",
            f"documents={len(exported['manifest_rows'])}",
            f"out_dir={args.out_dir}",
        )
    except Exception as exc:
        print(f"[ERROR] private markdown export failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
