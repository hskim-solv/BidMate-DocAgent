"""Shared pytest fixtures for the tests/ tree (issue #258)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_core import build_index_payload


ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def shared_raw_index() -> dict:
    """Hashing-backend index built once per session from data/raw."""
    return build_index_payload(ROOT_DIR / "data" / "raw", embedding_backend="hashing")
