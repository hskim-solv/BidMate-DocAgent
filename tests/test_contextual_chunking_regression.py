"""Regression guards for opt-in deterministic contextual chunking."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rag_indexing  # noqa: E402
from rag_embedding import EmbeddingResult  # noqa: E402


DOCUMENT = {
    "doc_id": "doc-a",
    "title": "RFP Alpha",
    "agency": "Agency A",
    "project": "Project A",
    "metadata": {},
    "source_path": "doc-a.txt",
    "sections": [
        {
            "heading": "Security",
            "section_path": ["Requirements", "Security"],
            "text": "Access logs must be retained. Audit trails must be searchable.",
        }
    ],
}


def test_contextual_chunking_adds_prefix_without_changing_base_strategy() -> None:
    chunks, _parents, diagnostics = rag_indexing.build_chunk_records(
        [DOCUMENT],
        chunking_strategy="contextual",
        max_chars=1000,
    )

    assert diagnostics["requested_strategy"] == "contextual"
    assert diagnostics["base_strategy"] == "auto"
    assert diagnostics["contextual"] is True
    assert diagnostics["chunker_version"] == rag_indexing.CONTEXTUAL_CHUNKER_VERSION
    assert chunks[0]["chunking_strategy"] == "section"
    assert chunks[0]["contextual"] is True
    assert chunks[0]["chunker_version"] == rag_indexing.CONTEXTUAL_CHUNKER_VERSION
    assert chunks[0]["contextual_prefix"].startswith("Document title: RFP Alpha.")
    assert "Requirements > Security" in chunks[0]["contextual_prefix"]


def test_default_fixed_chunking_has_no_contextual_prefix() -> None:
    chunks, _parents, diagnostics = rag_indexing.build_chunk_records(
        [DOCUMENT],
        chunking_strategy="fixed",
        max_chars=1000,
    )

    assert diagnostics["contextual"] is False
    assert "contextual_prefix" not in chunks[0]
    assert chunks[0]["contextual"] is False


def test_contextual_prefix_participates_in_embedding_input(monkeypatch) -> None:
    captured_inputs: list[str] = []

    def fake_embed_texts(texts, model_name, backend):
        captured_inputs.extend(texts)
        return EmbeddingResult(
            vectors=np.ones((len(texts), 4), dtype=np.float32),
            backend="fake",
            model="fake-model",
        )

    monkeypatch.setattr(rag_indexing, "embed_texts", fake_embed_texts)
    payload = rag_indexing.build_index_payload_from_documents(
        [DOCUMENT],
        source_dir="fixtures",
        embedding_backend="hashing",
        chunking_strategy="contextual",
        chunk_max_chars=1000,
    )

    assert payload["embedding"]["dimension"] == 4
    assert captured_inputs
    assert "Document title: RFP Alpha." in captured_inputs[0]
    assert "Access logs must be retained" in captured_inputs[0]
