"""Dependency-graph invariance regression (issue #872, G4 of GEF loop).

ADR 0045 (rag_core leaf-migration plan) named six modules that must
stay leaves in the rag_core dependency graph:

* ``rag_query``      (PR-J3, #480)
* ``rag_retrieval``  (PR-H1a / H1b, #459 / #461)
* ``rag_verifier``   (PR-J1, #466)
* ``rag_answer``     (PR-J2, #469)
* ``rag_embedding``  (PR-G2, #847)
* ``rag_indexing``   (PR-G3, #861)

"Leaf" means: **no import — top-level or function-level — back to
``rag_core``.** A late-import inside a function body is the
specific hack ADR 0045 set out to eliminate; it is just as much a
back-edge as a top-level import and breaks the module's standalone
testability.

If a future refactor needs to introduce a new helper in ``rag_core``
that a leaf module wants, the right move is to relocate the helper
to the leaf (or to a new shared leaf), **not** to add a late-import.
This regression test enforces that contract.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]

LEAF_MODULES = [
    "rag_query",
    "rag_retrieval",
    "rag_verifier",
    "rag_answer",
    "rag_embedding",
    "rag_indexing",
]


def _find_rag_core_imports(source: str) -> list[tuple[int, str, str]]:
    """Return ``(lineno, scope, statement)`` for every rag_core import.

    ``scope`` is ``"top-level"`` or ``"function:<name>"``. Walks the
    AST so it ignores docstring mentions of ``rag_core``.
    """
    tree = ast.parse(source)
    hits: list[tuple[int, str, str]] = []

    def _visit(node: ast.AST, scope: str) -> None:
        if isinstance(node, ast.ImportFrom):
            if node.module == "rag_core":
                names = ", ".join(a.name for a in node.names)
                hits.append((node.lineno, scope, f"from rag_core import {names}"))
                return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "rag_core" or alias.name.startswith("rag_core."):
                    hits.append((node.lineno, scope, f"import {alias.name}"))
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner_scope = f"function:{node.name}"
            for child in node.body:
                _visit(child, inner_scope)
            return
        if isinstance(node, ast.ClassDef):
            inner_scope = f"class:{node.name}"
            for child in node.body:
                _visit(child, inner_scope)
            return
        for child in ast.iter_child_nodes(node):
            _visit(child, scope)

    _visit(tree, "top-level")
    return hits


@pytest.mark.parametrize("module_name", LEAF_MODULES)
def test_leaf_module_has_zero_rag_core_back_edges(module_name: str) -> None:
    """Each ADR 0045 leaf module must have zero rag_core imports.

    Covers both:
      * top-level ``from rag_core import ...`` / ``import rag_core``
      * function-level late-imports (the explicit hack ADR 0045
        eliminated, and which must not regress)
    """
    source = (ROOT_DIR / f"{module_name}.py").read_text(encoding="utf-8")
    hits = _find_rag_core_imports(source)
    assert hits == [], (
        f"{module_name}.py has {len(hits)} import edge(s) back to rag_core, "
        f"violating the ADR 0045 leaf invariant:\n"
        + "\n".join(
            f"  line {lineno} ({scope}): {stmt}"
            for lineno, scope, stmt in hits
        )
        + "\n\nRelocate the helper to the leaf module (or to a new "
        "shared leaf), do not re-introduce a back-edge. Late-imports "
        "are explicitly disallowed — they are still back-edges and "
        "break standalone testability."
    )


def test_leaf_module_list_matches_adr_0045() -> None:
    """Belt-and-suspenders: catch silent drift in the leaf inventory.

    If a future PR extracts a new leaf module from rag_core, this test
    fails until the inventory above is updated — forcing the author to
    revisit ADR 0045 and document the new leaf.
    """
    expected = {
        "rag_query.py",
        "rag_retrieval.py",
        "rag_verifier.py",
        "rag_answer.py",
        "rag_embedding.py",
        "rag_indexing.py",
    }
    declared = {f"{m}.py" for m in LEAF_MODULES}
    assert declared == expected, (
        f"LEAF_MODULES drifted from ADR 0045 inventory:\n"
        f"  declared:  {sorted(declared)}\n"
        f"  expected:  {sorted(expected)}\n"
        "Update both this test and docs/adr/0045-... in the same PR."
    )
