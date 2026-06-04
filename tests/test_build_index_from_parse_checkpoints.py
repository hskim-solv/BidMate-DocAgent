from __future__ import annotations

import json

import pytest

from scripts.build_index_from_parse_checkpoints import (
    _checkpoint_signature,
    _existing_index_matches,
    _load_documents,
)


def _write_checkpoint(checkpoint_dir, *, text: str = "Body") -> None:
    checkpoint_dir.mkdir()
    (checkpoint_dir / "row_001.json").write_text(
        json.dumps(
            {
                "status": "indexed",
                "document": {
                    "doc_id": "doc_001",
                    "title": "Doc 1",
                    "source_path": "doc_001.pdf",
                    "sections": [
                        {
                            "heading": "Intro",
                            "text": text,
                            "page_span": [1, 1],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def test_load_documents_from_parse_checkpoints(tmp_path):
    checkpoint_dir = tmp_path / "_parse_checkpoints"
    _write_checkpoint(checkpoint_dir)

    docs = _load_documents(checkpoint_dir)

    assert [doc["doc_id"] for doc in docs] == ["doc_001"]
    assert docs[0]["sections"][0]["page_span"] == [1, 1]



def test_load_documents_requires_checkpoint_directory(tmp_path):
    missing_dir = tmp_path / "_parse_checkpoints"

    with pytest.raises(ValueError, match="must be a directory"):
        _load_documents(missing_dir)


def test_load_documents_ignores_rows_without_document_dict(tmp_path):
    checkpoint_dir = tmp_path / "_parse_checkpoints"
    _write_checkpoint(checkpoint_dir)
    (checkpoint_dir / "row_000.json").write_text(
        json.dumps({"status": "skipped", "document": "not-a-dict"}),
        encoding="utf-8",
    )

    docs = _load_documents(checkpoint_dir)

    assert [doc["doc_id"] for doc in docs] == ["doc_001"]

def test_checkpoint_signature_changes_when_checkpoint_content_changes(tmp_path):
    checkpoint_dir = tmp_path / "_parse_checkpoints"
    _write_checkpoint(checkpoint_dir, text="Before")
    before = _checkpoint_signature(checkpoint_dir)

    (checkpoint_dir / "row_001.json").write_text(
        (checkpoint_dir / "row_001.json").read_text(encoding="utf-8").replace("Before", "After"),
        encoding="utf-8",
    )
    after = _checkpoint_signature(checkpoint_dir)

    assert before["file_count"] == 1
    assert after["file_count"] == 1
    assert before["sha256"] != after["sha256"]


def test_existing_checkpoint_index_reuse_requires_matching_signature(tmp_path):
    checkpoint_dir = tmp_path / "_parse_checkpoints"
    output_dir = tmp_path / "index"
    output_dir.mkdir()
    _write_checkpoint(checkpoint_dir)
    signature = _checkpoint_signature(checkpoint_dir)
    (output_dir / "embeddings.npy").write_bytes(b"sidecar")
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "embedding": {
                    "backend": "sentence-transformers",
                    "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                },
                "build": {
                    "source_dir": str(checkpoint_dir),
                    "chunking": {"requested_strategy": "section"},
                    "checkpoint_source": {"signature": signature},
                },
            }
        ),
        encoding="utf-8",
    )

    reusable, reason = _existing_index_matches(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        signature=signature,
        model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedding_backend="sentence-transformers",
        chunking_strategy="section",
    )

    assert reusable is True
    assert "matching" in reason

    reusable, reason = _existing_index_matches(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        signature={**signature, "sha256": "different"},
        model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        embedding_backend="sentence-transformers",
        chunking_strategy="section",
    )

    assert reusable is False
    assert "signature" in reason

    mismatch_cases = [
        ({"model": "different-model"}, "model"),
        ({"embedding_backend": "hashing"}, "backend"),
        ({"chunking_strategy": "fixed"}, "chunking"),
    ]
    for overrides, expected_reason in mismatch_cases:
        reusable, reason = _existing_index_matches(
            output_dir=output_dir,
            checkpoint_dir=checkpoint_dir,
            signature=signature,
            model=overrides.get("model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
            embedding_backend=overrides.get("embedding_backend", "sentence-transformers"),
            chunking_strategy=overrides.get("chunking_strategy", "section"),
        )

        assert reusable is False
        assert expected_reason in reason
