#!/usr/bin/env python3
"""Real-data case proposer (ADR 0029).

Generates candidate case dicts that match
``eval/real_config.example.yaml``'s 8-field schema, for the private
real-data eval surface (ADR 0005 commit boundary). A human reviews
each candidate before it can be appended to
``eval/real_config.local.yaml`` — the proposer is upstream of, and
strictly separate from, the active eval input.

This is the case-input sibling of ``scripts/llm_judge.py`` (ADR 0006
real-data judge) and ``eval/synthetic_judge.py`` (ADR 0012 synthetic
judge). All three reuse the stub-default + opt-in live backend
pattern from ADR 0011.

PR1 scope (this file): skeleton + Protocol + backend dispatch. The
``stub`` backend returns an empty list; the ``openai_compatible``
backend raises NotImplementedError. PR2 fills the stub with
metadata-driven template queries; PR3 wires the live backend.

Backends:

* ``stub`` (default, PR1: empty) — deterministic; PR2 will emit
  metadata-driven template queries from ``data/data_list.csv``.
  Byte-equal across runs. Used by tests and CI plumbing. Never
  invokes a network call or LLM SDK.
* ``openai_compatible`` (PR3) — generic OpenAI-compatible endpoint.
  Will reuse ``BIDMATE_JUDGE_API_KEY`` / ``BIDMATE_JUDGE_MODEL`` /
  ``BIDMATE_JUDGE_BASE_URL`` (shared with the real-data judge).
  Backend selection is independent
  (``BIDMATE_CASE_PROPOSER_BACKEND``).

Per-case proposed schema (never committed; ADR 0005):

    {
      "id": "proposed_<YYYYMMDD>_<NNN>",
      "source": "proposed-then-reviewed",
      "proposer_meta": {
        "backend": "stub" | "openai_compatible",
        "model": "<model-id or 'stub'>",
        "seed_doc_id": "<doc-id from index>",
        "generated_at": "<ISO8601Z>",
        "proposer_version": 1,
      },
      "query_type": "single_doc" | "comparison" | "follow_up" | "abstention",
      "query": "...",
      "expected_doc_ids": [...],
      "expected_terms": [...],
      "expected_citation_terms": [...],
      "expected_claim_targets": [...],
      "answerable": bool,
    }

Importantly, this module does NOT import ``rag_core`` or any
retrieval / verifier code path. The proposer is upstream of
``run_rag_query`` — it produces eval *inputs* that downstream
pipelines consume. Keeping the import surface narrow is the
mechanical guarantee that ADR 0001's ``naive_baseline`` golden
cannot drift as a side-effect of loading this module (covered by
``tests/test_case_proposer_stub.py``).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Protocol

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_METADATA_PATH = ROOT / "data" / "data_list.csv"
DEFAULT_INDEX_PATH = ROOT / "data" / "index" / "real100" / "index.json"
DEFAULT_PROPOSED_PATH = ROOT / "reports" / "proposed" / "proposed_cases.local.yaml"
DEFAULT_REVIEWED_PATH = ROOT / "reports" / "proposed" / "reviewed_cases.local.yaml"
DEFAULT_AGGREGATE_PATH = ROOT / "reports" / "proposed" / "proposer.aggregate.json"

PROPOSER_VERSION = 1
BACKEND_ENV_VAR = "BIDMATE_CASE_PROPOSER_BACKEND"

QUERY_TYPES = ("single_doc", "comparison", "follow_up", "abstention")


class CaseProposerBackend(Protocol):
    """Backend contract for case proposers.

    A backend takes a sequence of metadata rows (each describing one
    seed document plus the top-3 chunks from the index) and returns a
    list of proposed case dicts conforming to the schema in this
    module's docstring. Implementations must be deterministic when
    given the same inputs *and* the same model snapshot — the
    ``openai_compatible`` backend uses ``temperature=0`` to satisfy
    this in practice.
    """

    def __call__(
        self,
        rows: list[dict[str, Any]],
        *,
        model: str,
    ) -> list[dict[str, Any]]:
        ...


def _stub_backend(
    rows: list[dict[str, Any]],
    *,
    model: str,
) -> list[dict[str, Any]]:
    """Deterministic stub backend.

    PR1: returns an empty list — the skeleton is plumbing-only.
    PR2 will emit metadata-driven template queries (e.g.
    ``"{발주기관} {사업명}의 사업기간은?"``) from each row, with
    ``expected_doc_ids`` derived directly from ``row["doc_id"]`` and
    ``answerable`` derived from ``query_type``.

    Byte-equal across runs by construction. Used by CI plumbing.
    """
    _ = rows  # PR2 will consume
    _ = model  # always "stub" for this backend; kept for symmetry
    return []


def _openai_compatible_backend(  # pragma: no cover - PR3
    rows: list[dict[str, Any]],
    *,
    model: str,
) -> list[dict[str, Any]]:
    """Generic OpenAI-compatible endpoint (PR3).

    Will lazily import the openai SDK so the stub-only path has no
    network / SDK dependency, mirroring ``eval/synthetic_judge.py``
    and ``scripts/llm_judge.py``.
    """
    _ = rows
    _ = model
    raise NotImplementedError(
        "openai_compatible backend lands in PR3 (ADR 0029). "
        "Use BIDMATE_CASE_PROPOSER_BACKEND=stub for now."
    )


_BACKENDS: dict[str, CaseProposerBackend] = {
    "stub": _stub_backend,
    "openai_compatible": _openai_compatible_backend,
}


def resolve_backend(name: str | None = None) -> tuple[str, CaseProposerBackend]:
    """Resolve a backend name to its (name, callable) pair.

    Precedence: explicit ``name`` argument > ``$BIDMATE_CASE_PROPOSER_BACKEND``
    env var > ``"stub"`` default. Raises ``ValueError`` for unknown
    backends so callers fail loudly rather than silently falling back.
    """
    resolved = name or os.environ.get(BACKEND_ENV_VAR) or "stub"
    backend = _BACKENDS.get(resolved)
    if backend is None:
        raise ValueError(
            f"Unknown case proposer backend: {resolved!r}. "
            f"Available: {sorted(_BACKENDS)}"
        )
    return resolved, backend


def propose_cases(
    rows: list[dict[str, Any]] | None = None,
    *,
    backend: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Public entry point.

    PR1 scope: dispatch to the resolved backend and return its raw
    output. PR2 will add CSV reading, index loading, and YAML writing
    (currently the caller is responsible for both ends — the proposer
    only owns the generation step).

    Args:
        rows: List of metadata rows. Each row should contain at
            minimum ``doc_id`` + the standard ``data_list.csv``
            columns. PR2 will define the precise schema as it wires
            the CSV reader.
        backend: Backend name; see ``resolve_backend`` for precedence.
        model: Model identifier to pass through to the backend. For
            ``stub`` this is recorded as ``"stub"`` in
            ``proposer_meta.model``; for ``openai_compatible`` it is
            the live model id.

    Returns:
        A list of proposed case dicts. PR1's stub returns ``[]``.
    """
    rows = rows or []
    resolved_name, backend_fn = resolve_backend(backend)
    resolved_model = model or ("stub" if resolved_name == "stub" else "")
    return backend_fn(rows, model=resolved_model)


__all__ = [
    "BACKEND_ENV_VAR",
    "DEFAULT_AGGREGATE_PATH",
    "DEFAULT_INDEX_PATH",
    "DEFAULT_METADATA_PATH",
    "DEFAULT_PROPOSED_PATH",
    "DEFAULT_REVIEWED_PATH",
    "PROPOSER_VERSION",
    "QUERY_TYPES",
    "CaseProposerBackend",
    "propose_cases",
    "resolve_backend",
]
