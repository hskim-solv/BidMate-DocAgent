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

Scope status:

* PR1 — skeleton + Protocol + backend dispatch (landed).
* PR2 (this PR) — stub backend emits metadata-driven template
  queries from ``data/data_list.csv`` + index; CSV reader, index
  reader, deterministic YAML writer, ``main()`` CLI.
* PR3 — ``openai_compatible`` live backend with ADR 0008
  ``EVIDENCE_BOUNDARY`` sanitization.
* PR4 — ``proposer.aggregate.json`` writer and ADR 0029 promotion
  to ``accepted``.

Backends:

* ``stub`` (default) — deterministic. Emits one ``single_doc`` +
  one ``abstention`` template per seed doc; ``expected_doc_ids``
  derived from the source row, ``answerable`` derived from
  ``query_type``. Byte-equal across runs given the same inputs and
  ``now_iso``. Used by tests and CI plumbing. Never invokes a
  network call or LLM SDK.
* ``csv_metadata`` — programmatic single-doc cases driven by
  ``data/data_list.csv``. For each seed row, emits up to four
  cases (one per metadata field: ``agency`` / ``project`` /
  ``budget`` / ``deadline``) with ``expected_terms`` populated
  verbatim from the CSV cell. Each case carries the ADR 0048
  ``metadata_field`` tag so the ``by_metadata_field`` aggregate in
  PR #879 buckets it correctly. Fields whose cell is empty are
  skipped. Deterministic; no LLM call; no human review needed for
  the gold label (CSV is authoritative).
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
        "backend": "stub" | "csv_metadata" | "openai_compatible",
        "model": "<model-id or 'stub' or 'csv_metadata'>",
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
      # Optional (ADR 0048): only emitted by csv_metadata backend.
      # Drives by_metadata_field aggregate in eval/run_eval.py.
      "metadata_field": "agency" | "project" | "budget" | "deadline",
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

import argparse
import csv
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Protocol

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_METADATA_PATH = ROOT / "data" / "data_list.csv"
DEFAULT_INDEX_PATH = ROOT / "data" / "index" / "real100" / "index.json"
DEFAULT_PROPOSED_PATH = ROOT / "reports" / "proposed" / "proposed_cases.local.yaml"
DEFAULT_REVIEWED_PATH = ROOT / "reports" / "proposed" / "reviewed_cases.local.yaml"
DEFAULT_AGGREGATE_PATH = ROOT / "reports" / "proposed" / "proposer.aggregate.json"

PROPOSER_VERSION = 1
BACKEND_ENV_VAR = "BIDMATE_CASE_PROPOSER_BACKEND"

QUERY_TYPES = ("single_doc", "comparison", "follow_up", "abstention")

# Single-source-of-truth column names from ``ingestion.REQUIRED_COLUMNS``.
# Hard-coded here (not imported) so this module stays free of
# ``rag_core``-transitive imports (ADR 0001 byte-identity guard).
# A drift guard test in tests/test_case_proposer_pipeline.py asserts
# these match ingestion.REQUIRED_COLUMNS at runtime.
CSV_COLUMN_NOTICE_ID = "공고 번호"
CSV_COLUMN_PROJECT = "사업명"
CSV_COLUMN_AGENCY = "발주 기관"
CSV_COLUMN_FILE_FORMAT = "파일형식"
CSV_COLUMN_FILE_NAME = "파일명"
CSV_COLUMN_TEXT = "텍스트"

# ADR 0048: column mappings for the four single-doc metadata fields the
# CSV-metadata backend emits as gold cases. Each tuple is
# ``(metadata_field, query_template, csv_column)``. Optional — these
# columns are not in REQUIRED_CSV_COLUMNS (the existing ``stub`` backend
# does not need them) so the backend gracefully skips a field when its
# cell is empty or the column is absent.
CSV_COLUMN_BUDGET = "사업 금액"
CSV_COLUMN_DEADLINE = "입찰 참여 마감일"
CSV_METADATA_FIELD_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("agency", "{agency} {project} 사업의 발주 기관을 알려줘", CSV_COLUMN_AGENCY),
    ("project", "{agency} 사업의 사업명을 알려줘", CSV_COLUMN_PROJECT),
    ("budget", "{agency} {project}의 사업 예산을 알려줘", CSV_COLUMN_BUDGET),
    ("deadline", "{agency} {project}의 입찰 참여 마감일을 알려줘", CSV_COLUMN_DEADLINE),
)

REQUIRED_CSV_COLUMNS = (
    CSV_COLUMN_NOTICE_ID,
    CSV_COLUMN_PROJECT,
    CSV_COLUMN_AGENCY,
    CSV_COLUMN_FILE_FORMAT,
    CSV_COLUMN_FILE_NAME,
    CSV_COLUMN_TEXT,
)


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
        now_iso: str,
    ) -> list[dict[str, Any]]:
        ...


def _template_single_doc(row: dict[str, Any]) -> str:
    agency = (row.get(CSV_COLUMN_AGENCY) or "").strip()
    project = (row.get(CSV_COLUMN_PROJECT) or "").strip()
    return f"{agency} {project}의 사업기간과 사업예산을 알려줘".strip()


def _template_abstention(row: dict[str, Any]) -> str:
    agency = (row.get(CSV_COLUMN_AGENCY) or "").strip()
    project = (row.get(CSV_COLUMN_PROJECT) or "").strip()
    return f"{agency} {project} 문서에 명시되지 않은 조건을 알려줘".strip()


def _make_proposed_id(now_iso: str, idx: int) -> str:
    # now_iso looks like "2026-05-13T08:45:50Z"; we want YYYYMMDD prefix.
    day = now_iso[:10].replace("-", "")
    return f"proposed_{day}_{idx:03d}"


def _make_proposer_meta(
    *,
    backend: str,
    model: str,
    seed_doc_id: str,
    now_iso: str,
) -> dict[str, Any]:
    return {
        "backend": backend,
        "model": model,
        "seed_doc_id": seed_doc_id,
        "generated_at": now_iso,
        "proposer_version": PROPOSER_VERSION,
    }


def _stub_backend(
    rows: list[dict[str, Any]],
    *,
    model: str,
    now_iso: str,
) -> list[dict[str, Any]]:
    """Deterministic stub backend (PR2).

    For each seed-doc row, emit two cases:
    - ``single_doc``: asks for the project period + budget.
    - ``abstention``: asks for a fact deliberately not in the doc.

    The 1:1 ratio is the cheapest defense against ADR 0029 §Risks #1
    (systematic bias toward easy single_doc queries inflating the
    `agentic_full_llm` vs `naive_baseline` delta) — the PR4
    ``by_query_type`` χ²-test still has a balanced base to compare
    against. ``expected_doc_ids`` is derived from the row, never
    from a model response. ``expected_terms`` /
    ``expected_citation_terms`` are intentionally left empty for the
    stub — they are the high-edit-rate fields the live backend (PR3)
    will fill and the human reviewer trims.

    Byte-equal across runs by construction, given the same ``rows``
    + ``now_iso``.
    """
    _ = model  # always "stub"; kept for symmetry with live backend
    cases: list[dict[str, Any]] = []
    counter = 1
    for row in rows:
        doc_id = str(row.get("doc_id") or "").strip()
        if not doc_id:
            # Without a doc_id we cannot produce a useful case; skip
            # rather than fabricate one. The CSV→doc_id mapping is the
            # caller's responsibility (see ``_attach_doc_ids``).
            continue
        agency = (row.get(CSV_COLUMN_AGENCY) or "").strip()

        cases.append(
            {
                "id": _make_proposed_id(now_iso, counter),
                "source": "proposed-then-reviewed",
                "proposer_meta": _make_proposer_meta(
                    backend="stub", model="stub", seed_doc_id=doc_id, now_iso=now_iso
                ),
                "query_type": "single_doc",
                "query": _template_single_doc(row),
                "expected_doc_ids": [doc_id],
                "expected_terms": [],
                "expected_citation_terms": [],
                "expected_claim_targets": [agency] if agency else [],
                "answerable": True,
            }
        )
        counter += 1

        cases.append(
            {
                "id": _make_proposed_id(now_iso, counter),
                "source": "proposed-then-reviewed",
                "proposer_meta": _make_proposer_meta(
                    backend="stub", model="stub", seed_doc_id=doc_id, now_iso=now_iso
                ),
                "query_type": "abstention",
                "query": _template_abstention(row),
                "expected_doc_ids": [],
                "expected_terms": [],
                "expected_citation_terms": [],
                "expected_claim_targets": [],
                "answerable": False,
            }
        )
        counter += 1
    return cases


def _csv_metadata_backend(
    rows: list[dict[str, Any]],
    *,
    model: str,
    now_iso: str,
) -> list[dict[str, Any]]:
    """Programmatic CSV-metadata backend (ADR 0048 tagging surface).

    For each seed-doc row, emits up to four ``single_doc`` cases — one
    per metadata field (``agency`` / ``project`` / ``budget`` /
    ``deadline``, see :data:`CSV_METADATA_FIELD_SOURCES`). The
    ``expected_terms`` / ``expected_citation_terms`` /
    ``expected_claim_targets`` are populated verbatim from the CSV cell
    so the case is immediately reviewable without an LLM pass — the CSV
    is the gold source.

    A field is **skipped** (no case emitted) when its cell is empty —
    ``입찰 참여 마감일`` is at 92% fill rate in real100, so ~8% of rows
    emit only 3 of the 4 cases. That's by design; ``by_metadata_field``
    aggregation handles the imbalanced bucket sizes via its own n
    count.

    Each emitted case carries ``metadata_field`` matching ADR 0048's
    ``METADATA_FIELD_KEYS``, so PR #879's ``by_metadata_field``
    aggregate buckets them correctly.

    Determinism: byte-equal across runs given the same ``rows`` +
    ``now_iso``. The (row, field) iteration order is fixed by
    :data:`CSV_METADATA_FIELD_SOURCES` declaration order.
    """
    cases: list[dict[str, Any]] = []
    counter = 1
    backend_model = model or "csv_metadata"
    for row in rows:
        doc_id = str(row.get("doc_id") or "").strip()
        if not doc_id:
            continue
        agency = (row.get(CSV_COLUMN_AGENCY) or "").strip()
        project = (row.get(CSV_COLUMN_PROJECT) or "").strip()
        for field_key, template, cell_column in CSV_METADATA_FIELD_SOURCES:
            cell_value = (row.get(cell_column) or "").strip()
            if not cell_value:
                continue
            query = template.format(agency=agency, project=project).strip()
            cases.append(
                {
                    "id": _make_proposed_id(now_iso, counter),
                    "source": "proposed-then-reviewed",
                    "proposer_meta": _make_proposer_meta(
                        backend="csv_metadata",
                        model=backend_model,
                        seed_doc_id=doc_id,
                        now_iso=now_iso,
                    ),
                    "query_type": "single_doc",
                    "query": query,
                    "expected_doc_ids": [doc_id],
                    "expected_terms": [cell_value],
                    "expected_citation_terms": [cell_value],
                    "expected_claim_targets": [cell_value],
                    "answerable": True,
                    "metadata_field": field_key,
                }
            )
            counter += 1
    return cases


def _openai_compatible_backend(  # pragma: no cover - PR3
    rows: list[dict[str, Any]],
    *,
    model: str,
    now_iso: str,
) -> list[dict[str, Any]]:
    """Generic OpenAI-compatible endpoint (PR3).

    Will lazily import the openai SDK so the stub-only path has no
    network / SDK dependency, mirroring ``eval/synthetic_judge.py``
    and ``scripts/llm_judge.py``.
    """
    _ = rows
    _ = model
    _ = now_iso
    raise NotImplementedError(
        "openai_compatible backend lands in PR3 (ADR 0029). "
        "Use BIDMATE_CASE_PROPOSER_BACKEND=stub or =csv_metadata for now."
    )


_BACKENDS: dict[str, CaseProposerBackend] = {
    "stub": _stub_backend,
    "csv_metadata": _csv_metadata_backend,
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


def _utcnow_iso_z() -> str:
    """ISO-8601 UTC timestamp with trailing ``Z`` (seconds precision)."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def propose_cases(
    rows: list[dict[str, Any]] | None = None,
    *,
    backend: str | None = None,
    model: str | None = None,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Public entry point.

    Args:
        rows: List of metadata rows. Each row must have ``doc_id`` set
            (already filtered against the active index — see
            ``propose_cases_from_files`` for the CSV→index pipeline).
            ``CSV_COLUMN_AGENCY`` / ``CSV_COLUMN_PROJECT`` are read
            for template substitution; missing values degrade
            gracefully (the template just renders without them).
        backend: Backend name; see ``resolve_backend`` for precedence.
        model: Model identifier to pass through to the backend. For
            ``stub`` this is recorded as ``"stub"`` in
            ``proposer_meta.model``; for ``openai_compatible`` it is
            the live model id.
        now_iso: Override timestamp for tests / reproducibility. When
            ``None``, ``datetime.now(UTC)`` is used.

    Returns:
        A list of proposed case dicts. The order is deterministic
        given the same ``rows`` ordering.
    """
    rows = rows or []
    resolved_name, backend_fn = resolve_backend(backend)
    resolved_model = model or ("stub" if resolved_name == "stub" else "")
    resolved_now = now_iso or _utcnow_iso_z()
    return backend_fn(rows, model=resolved_model, now_iso=resolved_now)


# -----------------------------------------------------------------------------
# CSV + index readers
# -----------------------------------------------------------------------------


class CaseProposerInputError(Exception):
    """Raised when CSV/index inputs are malformed or missing."""


def _read_data_list_csv(path: Path) -> list[dict[str, Any]]:
    """Read ``data_list.csv`` rows, validating required columns.

    Returns the raw dict per row (column → cell value). Caller is
    responsible for the CSV→doc_id mapping (see ``_attach_doc_ids``).

    Uses ``utf-8-sig`` to transparently strip the BOM that several
    Korean spreadsheet exports prepend — matches the canonical CSV
    opener in ``ingestion.py`` (issue #873). ``utf-8-sig`` is a strict
    superset of ``utf-8`` for BOM-less files, so this is safe to apply
    unconditionally.
    """
    if not path.exists():
        raise CaseProposerInputError(f"data_list.csv not found at {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise CaseProposerInputError(f"data_list.csv at {path} has no header")
        missing = [c for c in REQUIRED_CSV_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise CaseProposerInputError(
                f"data_list.csv at {path} missing required columns: {missing}"
            )
        return list(reader)


def _read_index_doc_ids(index_dir: Path) -> set[str]:
    """Extract the set of doc_ids present in ``index.json``.

    Reads ``index.json["build"]["documents"][*]["doc_id"]`` if the
    block is present (full build summary), else falls back to the
    chunk-level ``index["chunks"][*]["doc_id"]`` set. Either path
    yields the same set in a well-formed index.
    """
    index_path = index_dir / "index.json"
    if not index_path.exists():
        raise CaseProposerInputError(f"index.json not found at {index_path}")
    with index_path.open("r", encoding="utf-8") as fh:
        index = json.load(fh)
    documents = (index.get("build") or {}).get("documents") or []
    if documents:
        return {str(d["doc_id"]) for d in documents if d.get("doc_id")}
    chunks = index.get("chunks") or []
    return {str(c["doc_id"]) for c in chunks if c.get("doc_id")}


def _attach_doc_ids(
    rows: list[dict[str, Any]],
    valid_doc_ids: set[str],
) -> list[dict[str, Any]]:
    """Derive ``doc_id`` per row via ``ingestion.canonical_doc_id`` and
    drop rows whose derived id is not present in the active index.

    The lazy import keeps ``rag_core`` out of this module's import
    graph (ADR 0001 byte-identity guard) — ``ingestion.py`` does not
    import ``rag_core`` directly, but the lazy form is the cheapest
    defense against future drift.
    """
    from ingestion import canonical_doc_id  # noqa: WPS433 (intentional lazy import)

    out: list[dict[str, Any]] = []
    for row in rows:
        doc_id = canonical_doc_id(
            row.get(CSV_COLUMN_NOTICE_ID),
            row.get("회차"),  # optional; absent in many CSVs
            row.get(CSV_COLUMN_FILE_NAME),
        )
        if not doc_id or doc_id not in valid_doc_ids:
            continue
        out.append({**row, "doc_id": doc_id})
    return out


# -----------------------------------------------------------------------------
# YAML writer (deterministic, no PyYAML default-dict reordering)
# -----------------------------------------------------------------------------


def _yaml_escape_scalar(value: Any) -> str:
    """Conservative quoting for YAML scalar values.

    The writer is intentionally hand-rolled (rather than ``yaml.dump``)
    so the output ordering is exactly the ADR 0029 schema order:
    ``id`` → ``source`` → ``proposer_meta`` (5 keys) → 8 schema
    fields. PyYAML's default order is alphabetical for dicts on Python
    pre-3.7 semantics and ``sort_keys=False`` only gets us part way —
    the dict iteration order is our promise here. Strings always
    double-quoted (with `"`-escape) so Korean text + colons survive
    round-trip; booleans and integers emit as-is.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _write_case_yaml_block(case: dict[str, Any], lines: list[str]) -> None:
    """Emit one case as a YAML list element preserving schema order."""
    lines.append(f"  - id: {_yaml_escape_scalar(case['id'])}")
    lines.append(f"    source: {_yaml_escape_scalar(case['source'])}")
    lines.append("    proposer_meta:")
    meta = case["proposer_meta"]
    for key in ("backend", "model", "seed_doc_id", "generated_at", "proposer_version"):
        lines.append(f"      {key}: {_yaml_escape_scalar(meta[key])}")
    lines.append(f"    query_type: {_yaml_escape_scalar(case['query_type'])}")
    lines.append(f"    query: {_yaml_escape_scalar(case['query'])}")
    for key in (
        "expected_doc_ids",
        "expected_terms",
        "expected_citation_terms",
        "expected_claim_targets",
    ):
        values = case[key]
        if not values:
            lines.append(f"    {key}: []")
        else:
            lines.append(f"    {key}:")
            for item in values:
                lines.append(f"      - {_yaml_escape_scalar(item)}")
    lines.append(f"    answerable: {_yaml_escape_scalar(case['answerable'])}")
    # ADR 0048 opt-in tag — only emit when the backend populated it
    # (currently csv_metadata; stub keeps the field absent so its
    # historical byte-output is preserved for existing fixtures).
    if "metadata_field" in case:
        lines.append(
            f"    metadata_field: {_yaml_escape_scalar(case['metadata_field'])}"
        )


def write_proposed_yaml(cases: list[dict[str, Any]], path: Path) -> None:
    """Write proposed cases to ``path`` in deterministic block style.

    Output shape:

        proposed_cases:
          - id: "..."
            source: "..."
            proposer_meta: { ... }
            query_type: "..."
            ...
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["proposed_cases:"]
    if not cases:
        lines = ["proposed_cases: []"]
    else:
        for case in cases:
            _write_case_yaml_block(case, lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_real_config_covered_doc_ids(real_config_path: Path) -> set[str]:
    """Return the doc_ids already referenced by some case's
    ``expected_doc_ids`` in the active local real_config.

    Missing file is treated as "no doc covered yet" (empty set) — the
    local config is gitignored under ADR 0005 so a fresh clone never
    has it. Malformed YAML or unexpected shape raises so the proposer
    never silently widens coverage to docs that ARE already covered.
    """
    if not real_config_path.exists():
        return set()
    import yaml  # lazy: only needed when the local config exists

    text = real_config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    if config is None:
        return set()
    if not isinstance(config, dict):
        # NB: ``yaml.safe_load("[]") or {}`` would silently coerce a list to
        # an empty dict (empty-list is falsy), defeating the check below.
        # Branch on ``is None`` explicitly so a top-level list still raises.
        raise CaseProposerInputError(
            f"{real_config_path} must contain a YAML mapping at top level."
        )
    covered: set[str] = set()
    for case in config.get("cases") or []:
        if not isinstance(case, dict):
            continue
        for doc_id in case.get("expected_doc_ids") or []:
            value = str(doc_id).strip()
            if value:
                covered.add(value)
    return covered


def _select_uncovered_docs(
    rows_with_ids: list[dict[str, Any]],
    covered_doc_ids: set[str],
    n_seed_docs: int,
) -> list[dict[str, Any]]:
    """Reorder ``rows_with_ids`` so uncovered docs come first, then take
    the first ``n_seed_docs``.

    Direct realization of ADR 0044 §case selection criteria #3 ("prefer
    documents not yet covered by existing cases"). Within each group
    (covered / uncovered) the original CSV row order is preserved, so
    determinism survives and ``proposer.aggregate.json`` stays
    comparable across runs.

    When the uncovered pool is smaller than ``n_seed_docs``, the tail
    is filled with covered rows rather than truncated — a small
    uncovered pool must not starve the proposer.
    """
    if n_seed_docs <= 0:
        return []
    uncovered: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []
    for row in rows_with_ids:
        if str(row.get("doc_id") or "") in covered_doc_ids:
            covered.append(row)
        else:
            uncovered.append(row)
    return (uncovered + covered)[:n_seed_docs]


def propose_cases_from_files(
    *,
    metadata_csv: Path = DEFAULT_METADATA_PATH,
    index_dir: Path = DEFAULT_INDEX_PATH.parent,
    n_seed_docs: int = 10,
    backend: str | None = None,
    model: str | None = None,
    now_iso: str | None = None,
    real_config_path: Path | None = None,
    prioritize_uncovered: bool = True,
) -> list[dict[str, Any]]:
    """End-to-end: read CSV + index, filter, propose, return cases.

    Selects ``n_seed_docs`` rows whose ``canonical_doc_id`` is present
    in the active index. Selection order:

    * Default (``real_config_path=None``): first N by CSV row order
      — preserves the PR2 contract for callers that have no notion of
      an existing eval set (tests, CI plumbing).
    * Coverage-aware (``real_config_path`` set + ``prioritize_uncovered``):
      rows whose doc_id is *not* yet referenced in the active
      ``real_config.local.yaml`` come first, then covered rows fill
      the tail if needed. Realizes ADR 0044 §case selection criteria #3.

    Determinism is preserved in both modes — within each group the
    original CSV row order is used. ``proposer.aggregate.json`` stays
    byte-comparable across runs given the same inputs.
    """
    raw_rows = _read_data_list_csv(metadata_csv)
    valid_doc_ids = _read_index_doc_ids(index_dir)
    rows_with_ids = _attach_doc_ids(raw_rows, valid_doc_ids)
    if not rows_with_ids:
        raise CaseProposerInputError(
            f"No CSV rows from {metadata_csv} resolve to a doc_id present in "
            f"{index_dir / 'index.json'}. Run `make build-index` first."
        )
    if real_config_path is not None and prioritize_uncovered:
        covered = _read_real_config_covered_doc_ids(real_config_path)
        selected = _select_uncovered_docs(rows_with_ids, covered, n_seed_docs)
    else:
        selected = rows_with_ids[: max(n_seed_docs, 0)]
    return propose_cases(
        selected, backend=backend, model=model, now_iso=now_iso
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="case_proposer",
        description=(
            "Propose candidate cases for the real-data eval set (ADR 0029). "
            "Output is deterministic; review with `make case-review`."
        ),
    )
    p.add_argument(
        "--metadata-csv",
        type=Path,
        default=DEFAULT_METADATA_PATH,
        help=f"Path to data_list.csv (default: {DEFAULT_METADATA_PATH}).",
    )
    p.add_argument(
        "--index-dir",
        type=Path,
        default=DEFAULT_INDEX_PATH.parent,
        help=(
            f"Directory containing index.json (default: "
            f"{DEFAULT_INDEX_PATH.parent})."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PROPOSED_PATH,
        help=(
            f"Output yaml path (default: {DEFAULT_PROPOSED_PATH}, "
            f"gitignored under reports/proposed/)."
        ),
    )
    p.add_argument(
        "--n-seed-docs",
        type=int,
        default=10,
        help=(
            "Number of seed docs to use (default: 10). With 2 templates "
            "per doc, this yields ~20 candidate cases."
        ),
    )
    p.add_argument(
        "--backend",
        type=str,
        default=None,
        help=(
            "Backend override. Precedence: arg > "
            f"${BACKEND_ENV_VAR} > 'stub'. Allowed: "
            + ", ".join(sorted(_BACKENDS))
        ),
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "Model id passed to the backend. Ignored for stub "
            "(always recorded as 'stub')."
        ),
    )
    p.add_argument(
        "--real-config",
        type=Path,
        default=None,
        help=(
            "Path to the active real_config.local.yaml. When set, the "
            "proposer prioritizes docs whose doc_id is NOT yet referenced "
            "by any case's expected_doc_ids (ADR 0044 §case selection #3). "
            "Missing file → no rows are skipped; fresh-clone behaves "
            "identically to the default-ordered mode. ADR 0005 boundary: "
            "the file itself is gitignored — this argument is read-only."
        ),
    )
    p.add_argument(
        "--no-prioritize-uncovered",
        dest="prioritize_uncovered",
        action="store_false",
        default=True,
        help=(
            "Disable ADR 0044 doc_coverage prioritization even when "
            "--real-config is set (falls back to first-N CSV row order). "
            "Useful for byte-equal reproductions of the PR2-era proposer "
            "behavior."
        ),
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    try:
        cases = propose_cases_from_files(
            metadata_csv=args.metadata_csv,
            index_dir=args.index_dir,
            n_seed_docs=args.n_seed_docs,
            backend=args.backend,
            model=args.model,
            real_config_path=args.real_config,
            prioritize_uncovered=args.prioritize_uncovered,
        )
    except CaseProposerInputError as exc:
        print(f"case_proposer: {exc}", file=sys.stderr)
        return 2
    write_proposed_yaml(cases, args.out)
    print(
        f"case_proposer: wrote {len(cases)} candidate(s) to {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())


__all__ = [
    "BACKEND_ENV_VAR",
    "CSV_COLUMN_AGENCY",
    "CSV_COLUMN_FILE_FORMAT",
    "CSV_COLUMN_FILE_NAME",
    "CSV_COLUMN_NOTICE_ID",
    "CSV_COLUMN_PROJECT",
    "CSV_COLUMN_TEXT",
    "DEFAULT_AGGREGATE_PATH",
    "DEFAULT_INDEX_PATH",
    "DEFAULT_METADATA_PATH",
    "DEFAULT_PROPOSED_PATH",
    "DEFAULT_REVIEWED_PATH",
    "PROPOSER_VERSION",
    "QUERY_TYPES",
    "REQUIRED_CSV_COLUMNS",
    "CaseProposerBackend",
    "CaseProposerInputError",
    "main",
    "propose_cases",
    "propose_cases_from_files",
    "resolve_backend",
    "write_proposed_yaml",
]
