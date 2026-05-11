#!/usr/bin/env python3
"""Annotation aid for issue #175.

Dumps the chunks belonging to a case's ``expected_doc_ids`` so a human
can pick the ``gold_chunk_ids`` to add to ``eval/config.yaml``. Marks
chunks that the substring heuristic (``expected_terms``) would already
catch with a ``*`` so the annotator can spot blind spots quickly.

Usage:

    python3 scripts/dump_case_chunks.py \
        --config eval/config.yaml \
        --index_dir data/index \
        --case follow_up_schedule
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def load_case(config_path: Path, case_id: str) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for case in config.get("cases") or []:
        if case.get("id") == case_id:
            return case
    raise SystemExit(f"case id not found: {case_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="eval/config.yaml")
    parser.add_argument("--index_dir", default="data/index")
    parser.add_argument("--case", required=True, help="case id from eval config")
    parser.add_argument(
        "--text_chars", type=int, default=240, help="characters of chunk text to show"
    )
    args = parser.parse_args()

    case = load_case(Path(args.config), args.case)
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(t) for t in case.get("expected_terms") or [] if t]

    index = json.loads((Path(args.index_dir) / "index.json").read_text(encoding="utf-8"))
    chunks = index.get("chunks") or []

    print(f"case: {args.case}")
    print(f"query: {case.get('query')}")
    print(f"expected_doc_ids: {sorted(expected_doc_ids)}")
    print(f"expected_terms: {expected_terms}")
    explicit = case.get("gold_chunk_ids") or []
    print(f"current explicit gold_chunk_ids: {explicit}")
    print("-" * 80)

    if not expected_doc_ids:
        print("(no expected_doc_ids — abstention / unanswerable case)")
        return 0

    for chunk in chunks:
        if chunk.get("doc_id") not in expected_doc_ids:
            continue
        text = str(chunk.get("text") or "")
        hits = [t for t in expected_terms if t in text]
        marker = "*" if hits else " "
        preview = text[: args.text_chars].replace("\n", " ")
        print(f"{marker} {chunk.get('chunk_id')}  hits={hits}")
        print(f"    {preview}")
    print("-" * 80)
    print("(*) = chunk would be picked up by the substring heuristic today")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
