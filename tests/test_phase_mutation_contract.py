"""Regression: each ``_phase_*`` writes only the ``ctx`` fields its docstring documents (issue #840).

RAG senior-review critique #5 flagged that ``_phase_*`` functions
*look like* a functional pipeline (named "phase") but actually
mutate a shared ``_RunContext`` dataclass passed by reference. With
no contract surface, accidental cross-phase coupling — adding a
mutation in one phase that another phase depends on — is invisible
in code review.

The full fix would be an explicit state machine with named
transitions and immutable per-stage payloads (ADR-grade refactor;
tracked as part of #840). The surgical fix in this PR is to
**document** the mutation contract per phase and **pin** it via
this regression test:

1. Inspect each ``_phase_*`` function's source for ``ctx.<attr> = ...``
   assignments via the ``ast`` module (no runtime fixture needed).
2. Compare the discovered set of ctx attribute writes against the
   set the phase's docstring claims (parsed from the
   "Writes to ``ctx``" line).
3. Fail if the two sets diverge — forces every PR that adds or
   removes a phase-level write to update the docstring (which is
   the contract surface the critique flagged as missing).
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import unittest

import rag_core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DOCSTRING_WRITES_RE = re.compile(
    r"Writes to ``ctx``[^:]*:\s*(.+?)(?:\.\s|\.$|\n\n)",
    re.DOTALL,
)
# Match either ``backticked`` attribute names or bare attribute names
# in the comma-separated "Writes to ctx:" list.
_ATTR_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)``")


def _ctx_attribute_writes(func: object) -> set[str]:
    """Return the set of ``ctx.<name>`` attribute assignments inside ``func``.

    Walks the AST and collects the names of every ``ctx.X = ...``
    assignment. Augmented assignments (``ctx.X += ...``) and attribute
    deletions are out of scope (none currently exist in the phases).
    """
    source = inspect.getsource(func)
    # ``inspect.getsource`` returns the function with whatever
    # indentation it had at definition site. Module-level functions
    # are at column 0 already; nested funcs (none in this codebase
    # for ``_phase_*``) would need ``textwrap.dedent``. Defensive
    # dedent costs nothing.
    tree = ast.parse(textwrap.dedent(source))
    writes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "ctx"
            ):
                writes.add(target.attr)
    return writes


def _docstring_documented_writes(func: object) -> set[str]:
    """Return the set of ``ctx`` attributes the function docstring claims to write.

    Parses the "Writes to ``ctx``" line of the docstring's
    ``Mutation contract`` block. Returns an empty set for functions
    whose docstring documents "Writes to ``ctx``: none." (that's
    the explicit no-write contract).
    """
    doc = inspect.getdoc(func) or ""
    match = _DOCSTRING_WRITES_RE.search(doc)
    if not match:
        return set()
    fragment = match.group(1)
    if "none" in fragment.lower():
        return set()
    return set(_ATTR_NAME_RE.findall(fragment))


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestPhaseMutationContract(unittest.TestCase):
    def _assert_phase_contract(self, func: object) -> None:
        actual = _ctx_attribute_writes(func)
        documented = _docstring_documented_writes(func)
        self.assertEqual(
            actual,
            documented,
            msg=(
                f"\n{func.__name__} ctx-write contract drift:\n"
                f"  AST-discovered writes: {sorted(actual)}\n"
                f"  Docstring-claimed   : {sorted(documented)}\n"
                f"  In actual but not documented: {sorted(actual - documented)}\n"
                f"  Documented but not in actual: {sorted(documented - actual)}\n"
                f"Update the docstring's 'Writes to ``ctx``' line to match "
                f"the AST, then update this test only if the mutation is "
                f"intentional (RAG senior-review critique #5 fix, #840)."
            ),
        )

    def test_phase_analyze_contract(self) -> None:
        self._assert_phase_contract(rag_core._phase_analyze)

    def test_phase_retrieve_loop_contract(self) -> None:
        self._assert_phase_contract(rag_core._phase_retrieve_loop)

    def test_phase_build_answer_contract(self) -> None:
        # This phase's documented contract is "Writes to ``ctx``: none.",
        # so the AST set should be empty.
        self.assertEqual(
            _ctx_attribute_writes(rag_core._phase_build_answer),
            set(),
            msg=(
                "_phase_build_answer is documented as ctx-read-only but "
                "the AST found ctx attribute assignments. Either remove "
                "the assignments or update the docstring's mutation "
                "contract (RAG senior-review critique #5 fix, #840)."
            ),
        )
        self._assert_phase_contract(rag_core._phase_build_answer)

    def test_all_phases_have_mutation_contract_section(self) -> None:
        # The docstring marker must be present on every _phase_* — so
        # a future PR that adds a new _phase_X function gets caught
        # by the test even before they wire up the regression.
        for name, func in inspect.getmembers(rag_core, inspect.isfunction):
            if not name.startswith("_phase_"):
                continue
            doc = inspect.getdoc(func) or ""
            self.assertIn(
                "Mutation contract",
                doc,
                msg=(
                    f"{name} is missing the 'Mutation contract' "
                    "docstring section (RAG senior-review critique #5 "
                    "fix, #840). Every _phase_* function must document "
                    "its ctx-write set so the regression test in "
                    "tests/test_phase_mutation_contract.py can pin it."
                ),
            )


if __name__ == "__main__":
    unittest.main()
