from __future__ import annotations

import json

from rag_indexing import load_raw_documents


def test_load_raw_documents_skips_local_export_manifest(tmp_path):
    (tmp_path / "doc_001.md").write_text("# Doc 1\n\nBody\n", encoding="utf-8")
    (tmp_path / "export_manifest.local.json").write_text(
        json.dumps({"documents": [{"path": "doc_001.md"}]}),
        encoding="utf-8",
    )

    docs = load_raw_documents(tmp_path)

    assert [doc["doc_id"] for doc in docs] == ["doc_001"]


def test_load_raw_documents_skips_metadata_siblings_and_hidden_files(tmp_path):
    (tmp_path / ".hidden.md").write_text("# Hidden\n\nNot a corpus doc\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Local corpus notes\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{not valid json if loaded", encoding="utf-8")
    (tmp_path / "doc_001.md").write_text("# Doc 1\n\nBody\n", encoding="utf-8")
    (tmp_path / "doc_002.TXT").write_text("Doc 2\n\nMore body\n", encoding="utf-8")

    docs = load_raw_documents(tmp_path)

    assert [doc["doc_id"] for doc in docs] == ["doc_001", "doc_002"]
