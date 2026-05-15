"""Regression: ``_PROCESS_WARM`` documentation caveat must remain (issue #842).

RAG senior-review critique #7.3. ``rag_core._PROCESS_WARM`` is a
module-level boolean that flips ``True`` after the first
``run_rag_query`` call. It captures per-process bootstrap cost
(embedding/reranker lazy-load, BM25 cache warm-up) for the
``cold_start_samples`` warm-vs-cold latency split in
``eval/run_eval.py``.

The behavior has a long-tail caveat: subsequent calls always log
``cold_start=False``, even if the process was idle long enough that
real cold-start latency would re-emerge (model evicted from OS page
cache, BM25 cache reclaimed by GC, etc.). Per #842's decision rule,
this is acceptable because current consumers only need the per-process
bootstrap diagnostic — but the limitation must be documented so a
future operator who wants long-tail latency tracking knows to upgrade
to a TTL-based "warm if active within last N min" tracker instead of
silently relying on the boolean.

This test pins the docstring caveat so a future refactor that drops or
weakens the comment fails CI before it ships.
"""
from __future__ import annotations

import inspect
import unittest

import rag_core


class TestProcessWarmDocstringPinning(unittest.TestCase):
    def test_process_warm_module_comment_documents_long_tail_caveat(self) -> None:
        """The block-comment header above ``_PROCESS_WARM`` must mention
        the long-tail caveat + the multi-worker semantics + the issue
        number, so a future maintainer cannot remove the caveat without
        tripping this test."""
        source = inspect.getsource(rag_core)
        idx = source.find("_PROCESS_WARM = False")
        self.assertNotEqual(
            idx,
            -1,
            "_PROCESS_WARM definition not found in rag_core.py — "
            "definition moved or renamed; update this regression test too.",
        )
        # Grab the 30 lines of comment header preceding the assignment.
        preceding = source[:idx]
        last_n_lines = "\n".join(preceding.splitlines()[-30:])

        for required_phrase in (
            "issue #842",  # Provenance pointer.
            "Multi-worker semantics",  # Per-process state explanation.
            "Long-tail caveat",  # Long-tail caveat header.
            "page cache",  # Concrete example of the failure mode.
            "TTL",  # Pointer to the upgrade path if needed.
        ):
            self.assertIn(
                required_phrase,
                last_n_lines,
                f"_PROCESS_WARM block comment must mention {required_phrase!r} "
                "(issue #842 decision-rule docstring contract). "
                f"Last 30 lines before assignment:\n{last_n_lines}",
            )


if __name__ == "__main__":
    unittest.main()
