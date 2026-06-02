"""Regression guard: the ``memory`` VectorStore backend must never become the
default/baseline backend (issue #1765).

``chroma`` is the default (ADR 0081) and ``naive_baseline`` is Chroma-backed
(ADR 0001).  ``memory`` (``InMemoryVectorStore``) stays a legitimate
*test-control* for chroma/memory/qdrant ranking parity, so this guard pins the
*default* resolution to chroma **without** removing the explicit opt-in — the
parity suites that set ``BIDMATE_INDEX_BACKEND=memory`` keep working untouched.

Positive-shape: every assertion pins the expected ``chroma`` outcome (or the
chroma dispatch) rather than scanning source for a forbidden ``memory`` literal
(cf. feedback_destructive_op_precheck — guard tests assert the allowed shape,
not the banned literal).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

import rag_vector_store
from rag_vector_store import DEFAULT_INDEX_BACKEND, ENV_INDEX_BACKEND
from rag_pipeline_presets import resolve_pipeline_config
from eval.run_eval import normalize_run_config, vector_store_backend_for_runs


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"


def _eval_ablation_rows() -> list[dict]:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return list(config.get("ablation_runs", []))


# --- gap A: rag_vector_store default chokepoint -------------------------------


def test_default_index_backend_constant_is_chroma() -> None:
    """ADR 0081 — the module default backend is chroma, never memory."""
    assert DEFAULT_INDEX_BACKEND == "chroma"


def test_resolve_backend_is_chroma_when_env_unset(monkeypatch) -> None:
    """The default resolution path (no arg, no env) yields chroma."""
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    assert rag_vector_store._resolve_backend() == "chroma"


def test_default_build_path_dispatches_to_chroma_store(monkeypatch) -> None:
    """With no backend override, ``vector_store_from_matrix`` materializes the
    Chroma store, not the InMemory fallthrough in ``vector_store_from_matrix``.

    Spied so the assertion holds without a real chromadb build and proves the
    *dispatch* lands on chroma rather than leaking to memory.
    """
    monkeypatch.delenv(ENV_INDEX_BACKEND, raising=False)
    dispatched: dict[str, object] = {}
    sentinel = object()

    def _spy_chroma(vectors: np.ndarray) -> object:
        dispatched["chroma"] = vectors
        return sentinel

    monkeypatch.setattr(rag_vector_store, "_build_chroma_store", _spy_chroma)
    store = rag_vector_store.vector_store_from_matrix(
        np.zeros((2, 3), dtype=np.float32)
    )
    assert store is sentinel
    assert "chroma" in dispatched


# --- gap B: pipeline-config / preset default ----------------------------------


def test_pipeline_preset_default_vector_store_is_chroma() -> None:
    """A config without an explicit backend resolves to chroma via
    ``resolve_pipeline_config`` default-fill — the path every non-naive eval
    row relies on.
    """
    resolved = resolve_pipeline_config({"name": "probe", "pipeline": "agentic_full"})
    assert resolved["vector_store_backend"] == "chroma"


# --- gap C: eval/config.yaml production rows ----------------------------------


def test_every_eval_ablation_row_resolves_to_chroma() -> None:
    """Every production eval row resolves to chroma — none silently leaks to
    memory (issue #1765). naive_baseline pins it explicitly (ADR 0001); the rest
    inherit the chroma default."""
    rows = _eval_ablation_rows()
    assert rows, "eval/config.yaml must declare ablation_runs"
    resolved = {
        row["name"]: normalize_run_config(row)["vector_store_backend"]
        for row in rows
    }
    assert set(resolved.values()) == {"chroma"}, resolved


def test_eval_runs_share_chroma_backend() -> None:
    """The runner's cross-row single-backend aggregation
    (``vector_store_backend_for_runs``) returns chroma — the chokepoint the eval
    runner actually calls, distinct from the per-row check above.
    """
    normalized = [normalize_run_config(row) for row in _eval_ablation_rows()]
    assert vector_store_backend_for_runs(normalized) == "chroma"


# --- control opt-in stays available (parity tests must keep working) ----------


def test_explicit_memory_backend_remains_available_as_test_control(
    monkeypatch,
) -> None:
    """The guard pins the *default* only; the explicit memory opt-in that the
    chroma/memory/qdrant parity suites depend on must keep resolving."""
    assert rag_vector_store._resolve_backend("memory") == "memory"
    monkeypatch.setenv(ENV_INDEX_BACKEND, "memory")
    assert rag_vector_store._resolve_backend() == "memory"
