"""Multi-turn accuracy decay measurement helpers (issue #125).

Adds a turn-depth dimension to the dev-side evaluator. A query is
considered turn-1 if its ``parent_qid`` is empty / null. Each follow-up
chains via ``parent_qid``; depth is derived by walking the chain back
to the root.

ADR 0001 invariant: this is an **additive measurement axis** on top of
``naive_baseline`` and ``agentic_full``. Neither pipeline is modified,
neither baseline is replaced — the decay curve is layered over the
existing per-question scoring.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional


def derive_turn_depth(
    qid: str,
    parent_qid: Optional[str],
    qid_to_parent: Mapping[str, Optional[str]],
    *,
    max_depth: int = 16,
) -> int:
    """Return the turn depth for ``qid`` (1-indexed; turn-1 has no parent).

    The walk is bounded by ``max_depth`` to defend against accidental
    cycles or malformed parent chains. When the bound is hit, the depth
    is reported as ``max_depth`` and the caller can decide how to
    surface that.
    """
    if not parent_qid or parent_qid in {"", "null", "None"}:
        return 1
    depth = 2
    current_parent: Optional[str] = parent_qid
    seen: set[str] = {qid}
    while current_parent and current_parent not in seen and depth < max_depth:
        seen.add(current_parent)
        next_parent = qid_to_parent.get(current_parent)
        if not next_parent or next_parent in {"", "null", "None"}:
            return depth
        depth += 1
        current_parent = next_parent
    return depth


def build_qid_parent_map(rows: Iterable[Mapping[str, object]]) -> dict[str, Optional[str]]:
    """Pre-build a {qid: parent_qid} map from result rows.

    ``parent_qid`` is normalised — empty strings, the literal "null", and
    "None" all map to ``None`` so :func:`derive_turn_depth` sees a single
    sentinel for "this is a root turn."
    """
    mapping: dict[str, Optional[str]] = {}
    for row in rows:
        qid = str(row.get("qid") or "")
        if not qid:
            continue
        raw_parent = row.get("parent_qid")
        parent: Optional[str]
        if raw_parent is None:
            parent = None
        else:
            text = str(raw_parent).strip()
            parent = None if text in {"", "null", "None"} else text
        mapping[qid] = parent
    return mapping
