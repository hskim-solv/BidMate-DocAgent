from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_private_index_markdown import build_aggregate, export_markdown, main


def _index() -> dict:
    return {
        "schema_version": 2,
        "chunks": [
            {
                "doc_id": "SECRET-DOC-001",
                "chunk_id": "SECRET-CHUNK-001",
                "text": "SECRET RAW RFP TEXT | item | value | 2026년 1월 1일 10점 100원",
                "metadata": {"page_span": [1, 1], "text_source": "pdf_pymupdf4llm"},
            },
            {
                "doc_id": "SECRET-DOC-001",
                "chunk_id": "SECRET-CHUNK-002",
                "text": "more private text",
                "metadata": {"page_span": [2, 2], "text_source": "pdf_pymupdf4llm"},
            },
        ],
    }


def test_export_writes_private_markdown_but_aggregate_is_public_safe(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index()), encoding="utf-8")
    out_dir = tmp_path / "private_md"
    exported = export_markdown(_index(), out_dir)
    aggregate = build_aggregate(_index(), index_path=index_path, out_dir=out_dir, exported=exported)

    assert (out_dir / "doc_001.md").read_text(encoding="utf-8").startswith("SECRET RAW")
    rendered = json.dumps(aggregate, ensure_ascii=False, sort_keys=True)
    assert "SECRET" not in rendered
    assert "SECRET-DOC-001" not in rendered
    assert "SECRET-CHUNK-001" not in rendered
    assert "index.json" not in rendered
    assert str(tmp_path) not in rendered
    assert aggregate["population"] == {"document_count": 1, "chunk_count": 2}
    assert aggregate["page_metadata"]["ready_count"] == 2
    assert aggregate["artifact_condition_counts"]["table_heavy"] == 0


def test_main_rejects_non_ignored_repo_output(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index()), encoding="utf-8")

    rc = main(["--index", str(index_path), "--out-dir", "not_ignored_private_md"])

    assert rc == 2


def test_main_writes_aggregate_for_private_output(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    out_dir = tmp_path / "outside_private_md"
    out_aggregate = tmp_path / "parse_inventory.aggregate.json"
    index_path.write_text(json.dumps(_index()), encoding="utf-8")

    rc = main([
        "--index",
        str(index_path),
        "--out-dir",
        str(out_dir),
        "--out-aggregate",
        str(out_aggregate),
    ])

    assert rc == 0
    written = json.loads(out_aggregate.read_text(encoding="utf-8"))
    assert written["profile_type"] == "private_real100_v2_parse_inventory"
