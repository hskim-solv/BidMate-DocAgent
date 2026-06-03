"""Characterization regression suite for ``scripts/update_readme_metrics.py``.

``update_readme_metrics.py`` reads ``reports/eval_summary.json`` and rewrites the
human-facing README metrics table in place; ``--check`` is the CI/Makefile drift
gate. It is the most-churned untested governance renderer, and its
``splice_table_rows`` core encodes hard-won behavior with no regression defense:

  - issue #792  — scoped numeric-row splice (only ``|``-rows inside the markers)
  - issue #1116 — Korean ``<details>``/``<summary>``/caption prose preservation
  - issue #1156 — ADR-count rewrite is the ONLY sanctioned outside-marker edit
  - ``structural_match`` detection (row-count parity → safe in-place splice)

These tests lock the CURRENT correct behavior (no fail-first stage — behavior is
unchanged). The production code is the source of truth: if an expectation here is
wrong, the TEST is fixed, never the renderer.

Import bootstrap: ``update_readme_metrics`` lives in ``scripts/`` and itself does
``from eval.bootstrap import format_ci_band`` / ``from _utils import fmt_rate`` /
``from _governance import ...``. Inserting BOTH the repo root (so ``eval`` resolves
as a namespace package) and ``scripts/`` (so the bare module + its ``_utils`` /
``_governance`` siblings resolve) makes every one of those imports succeed at
runtime. The module also self-inserts the same paths at import time, so this is
belt-and-suspenders, matching the ``tests/test_doc_links.py`` convention.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import update_readme_metrics as urm  # noqa: E402
from eval.bootstrap import format_ci_band  # noqa: E402
from _utils import fmt_rate  # noqa: E402


# ---------------------------------------------------------------------------
# splice_table_rows — the crown jewel (issue #792 / #1116 scoped splice)
# ---------------------------------------------------------------------------


def _block(rows: str) -> str:
    """Wrap pipe-rows in the real marker block (markers imported, never hardcoded)."""
    return f"{urm.START_MARKER}\n{rows}\n{urm.END_MARKER}\n"


def test_splice_replaces_only_marker_block_rows_outside_byte_identical():
    readme = (
        "intro line\n"
        "| OUTSIDE | ROW |\n"
        + urm.START_MARKER
        + "\n| h1 | h2 |\n| old1 | old2 |\n"
        + urm.END_MARKER
        + "\nfooter line\n"
    )
    new_table = "| NH1 | NH2 |\n| NEW1 | NEW2 |"
    spliced, _ = urm.splice_table_rows(readme, new_table)

    # Inside-marker rows were replaced by the rendered rows.
    assert "| NH1 | NH2 |" in spliced
    assert "| NEW1 | NEW2 |" in spliced
    assert "| old1 | old2 |" not in spliced
    # Lines outside the markers are byte-identical untouched.
    assert "intro line\n" in spliced
    assert "footer line\n" in spliced


def test_splice_leaves_pipe_row_outside_markers_untouched():
    readme = "| OUTSIDE | ROW |\n" + _block("| in |")
    spliced, _ = urm.splice_table_rows(readme, "| ZZZ |")
    # The outside ``|``-row must NOT be spliced even though it looks like a table row.
    assert "| OUTSIDE | ROW |" in spliced
    assert "| ZZZ |" in spliced  # the inside row WAS replaced
    assert "| in |" not in spliced


def test_splice_preserves_nontable_prose_inside_block():
    # <details>/<summary>/Korean caption are hand-curated prose the renderer
    # does not own (PR #1116) — only the numeric ``|``-row is spliced.
    readme = _block(
        "<details>\n"
        "<summary>한국어 캡션 — 검출 불가 ablation</summary>\n"
        "| in |\n"
        "</details>"
    )
    spliced, _ = urm.splice_table_rows(readme, "| ZZZ |")
    assert "<details>" in spliced
    assert "<summary>한국어 캡션 — 검출 불가 ablation</summary>" in spliced
    assert "</details>" in spliced
    assert "| ZZZ |" in spliced
    assert "| in |" not in spliced


def test_splice_structural_match_true_when_row_counts_equal():
    readme = _block("| h1 | h2 |\n| old | old |")  # 2 README pipe-rows
    new_table = "| NH1 | NH2 |\n| NEW | NEW |"  # 2 rendered rows
    _, structural_match = urm.splice_table_rows(readme, new_table)
    assert structural_match is True


def test_splice_structural_match_false_when_readme_has_more_rows():
    readme = _block("| a |\n| b |\n| c |")  # 3 README pipe-rows
    new_table = "| NH |\n| NEW |"  # 2 rendered rows
    spliced, structural_match = urm.splice_table_rows(readme, new_table)
    assert structural_match is False
    # The surplus README row is kept verbatim (only the first 2 were consumed).
    assert "| c |" in spliced


def test_splice_structural_match_false_when_table_has_more_rows():
    readme = _block("| a |")  # 1 README pipe-row
    new_table = "| NH |\n| NEW |"  # 2 rendered rows
    _, structural_match = urm.splice_table_rows(readme, new_table)
    assert structural_match is False


def test_splice_preserves_trailing_newline_when_present():
    readme = _block("| in |")  # _block ends with "\n"
    assert readme.endswith("\n")
    spliced, _ = urm.splice_table_rows(readme, "| ZZZ |")
    assert spliced.endswith("\n")


def test_splice_omits_trailing_newline_when_absent():
    readme = _block("| in |").rstrip("\n")
    assert not readme.endswith("\n")
    spliced, _ = urm.splice_table_rows(readme, "| ZZZ |")
    assert not spliced.endswith("\n")


# ---------------------------------------------------------------------------
# normalize_outside_markers
# ---------------------------------------------------------------------------


def test_normalize_strips_marker_block():
    text = "BEFORE" + urm.START_MARKER + "MIDDLE" + urm.END_MARKER + "AFTER"
    assert urm.normalize_outside_markers(text) == "BEFOREAFTER"


def test_normalize_unchanged_when_start_missing():
    text = "hello " + urm.END_MARKER
    assert urm.normalize_outside_markers(text) == text


def test_normalize_unchanged_when_end_missing():
    text = urm.START_MARKER + " hello"
    assert urm.normalize_outside_markers(text) == text


def test_normalize_unchanged_when_end_before_start():
    text = urm.END_MARKER + "x" + urm.START_MARKER
    assert urm.normalize_outside_markers(text) == text


# ---------------------------------------------------------------------------
# fmt_latency — guarded fallback, never crashes
# ---------------------------------------------------------------------------


def test_fmt_latency_dict_with_p50_p95():
    assert urm.fmt_latency({"p50": 1.234, "p95": 5.678}) == "p50 1.2ms / p95 5.7ms"


def test_fmt_latency_dict_missing_p95_is_na():
    assert urm.fmt_latency({"p50": 1.0}) == "N/A"


@pytest.mark.parametrize("value", [None, "not-a-dict", 42])
def test_fmt_latency_non_dict_is_na(value):
    assert urm.fmt_latency(value) == "N/A"


# ---------------------------------------------------------------------------
# fmt_flag / fmt_top_k
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, 1, "x", [0]])
def test_fmt_flag_truthy_is_on(value):
    assert urm.fmt_flag(value) == "on"


@pytest.mark.parametrize("value", [False, 0, "", None, []])
def test_fmt_flag_falsy_is_off(value):
    assert urm.fmt_flag(value) == "off"


def test_fmt_top_k_int_is_str():
    assert urm.fmt_top_k(5) == "5"


@pytest.mark.parametrize("value", [None, "5", 1.5])
def test_fmt_top_k_non_int_is_auto(value):
    assert urm.fmt_top_k(value) == "auto"


# ---------------------------------------------------------------------------
# fmt_rate_ci — delegates to format_ci_band or falls back to fmt_rate
# ---------------------------------------------------------------------------


def test_fmt_rate_ci_with_ci_dict_delegates_to_format_ci_band():
    ci = {"mean": 0.906, "ci_lo": 0.78, "ci_hi": 1.0}
    assert urm.fmt_rate_ci(0.5, ci) == format_ci_band(ci, digits=3)


def test_fmt_rate_ci_none_falls_back_to_fmt_rate():
    assert urm.fmt_rate_ci(0.5, None) == fmt_rate(0.5)


def test_fmt_rate_ci_non_dict_falls_back_to_fmt_rate():
    assert urm.fmt_rate_ci(0.5, "nope") == fmt_rate(0.5)


def test_fmt_rate_ci_mean_none_falls_back_to_fmt_rate():
    assert urm.fmt_rate_ci(0.5, {"mean": None}) == fmt_rate(0.5)


# ---------------------------------------------------------------------------
# fmt_rate_ci_compact — half-width band
# ---------------------------------------------------------------------------


def test_fmt_rate_ci_compact_full_band_uses_max_half_width():
    # half = max(hi-mean, mean-lo) = max(0.094, 0.126) = 0.126 -> 0.13 at .2f
    ci = {"mean": 0.906, "ci_lo": 0.78, "ci_hi": 1.0}
    assert urm.fmt_rate_ci_compact(0.5, ci) == "0.906±0.13"


def test_fmt_rate_ci_compact_missing_bounds_is_mean_only():
    assert urm.fmt_rate_ci_compact(0.5, {"mean": 0.906}) == "0.906"


def test_fmt_rate_ci_compact_mean_none_falls_back_to_fmt_rate():
    assert urm.fmt_rate_ci_compact(0.42, {"mean": None}) == fmt_rate(0.42)


def test_fmt_rate_ci_compact_non_dict_falls_back_to_fmt_rate():
    assert urm.fmt_rate_ci_compact(0.42, "nope") == fmt_rate(0.42)


# ---------------------------------------------------------------------------
# fmt_abstention_breakdown
# ---------------------------------------------------------------------------


def test_fmt_abstention_breakdown_full_outcomes():
    outcomes = {"correct_refusal": 3, "incorrect_answer": 7, "boundary_partial": 0}
    assert urm.fmt_abstention_breakdown(0.3, outcomes) == f"{fmt_rate(0.3)} (3/7/0)"


def test_fmt_abstention_breakdown_non_dict_is_base_only():
    assert urm.fmt_abstention_breakdown(0.3, None) == fmt_rate(0.3)


def test_fmt_abstention_breakdown_any_key_none_is_base_only():
    outcomes = {"correct_refusal": 3, "incorrect_answer": 7, "boundary_partial": None}
    assert urm.fmt_abstention_breakdown(0.3, outcomes) == fmt_rate(0.3)


# ---------------------------------------------------------------------------
# ci_for — dict navigation with documented fallback
# ---------------------------------------------------------------------------


def test_ci_for_returns_metric_block_when_ci_is_dict():
    summary = {"ci": {"accuracy": {"mean": 0.9}}}
    assert urm.ci_for(summary, "accuracy") == {"mean": 0.9}


def test_ci_for_none_when_ci_absent():
    assert urm.ci_for({}, "accuracy") is None


def test_ci_for_none_when_ci_not_dict():
    assert urm.ci_for({"ci": 5}, "accuracy") is None


# ---------------------------------------------------------------------------
# ci_from_type / metric_from_type — by_slice→by_query_type + comparison→multi_doc
# ---------------------------------------------------------------------------


def test_metric_from_type_uses_by_slice_first():
    summary = {"by_slice": {"single_doc": {"accuracy": 0.8}}}
    assert urm.metric_from_type(summary, "single_doc", "accuracy") == 0.8


def test_metric_from_type_falls_back_to_by_query_type():
    summary = {"by_query_type": {"single_doc": {"accuracy": 0.7}}}
    assert urm.metric_from_type(summary, "single_doc", "accuracy") == 0.7


def test_metric_from_type_comparison_resolves_via_multi_doc():
    summary = {"by_slice": {"multi_doc": {"groundedness": 0.8}}}
    assert urm.metric_from_type(summary, "comparison", "groundedness") == 0.8


def test_metric_from_type_none_when_by_type_not_dict():
    assert urm.metric_from_type({"by_slice": 5}, "comparison", "groundedness") is None


def test_metric_from_type_none_when_block_missing():
    assert urm.metric_from_type({}, "comparison", "groundedness") is None


def test_ci_from_type_comparison_resolves_via_multi_doc():
    summary = {"by_slice": {"multi_doc": {"ci": {"groundedness": {"mean": 0.8}}}}}
    assert urm.ci_from_type(summary, "comparison", "groundedness") == {"mean": 0.8}


def test_ci_from_type_none_when_by_type_not_dict():
    assert urm.ci_from_type({"by_slice": 5}, "comparison", "groundedness") is None


def test_ci_from_type_none_when_block_missing():
    assert urm.ci_from_type({}, "comparison", "groundedness") is None


# ---------------------------------------------------------------------------
# _find_run — skips non-dict elements
# ---------------------------------------------------------------------------


def test_find_run_returns_matching_dict_skipping_non_dicts():
    runs = [1, "a", {"name": "naive_baseline"}, {"name": "full", "accuracy": 0.9}]
    assert urm._find_run(runs, "full") == {"name": "full", "accuracy": 0.9}


def test_find_run_none_when_absent():
    assert urm._find_run([{"name": "x"}], "full") is None


# ---------------------------------------------------------------------------
# _delta_pp — percentage-point delta with sign boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("full,base", [(None, 0.5), (0.5, None), (None, None)])
def test_delta_pp_em_dash_when_either_side_none(full, base):
    assert urm._delta_pp(full, base) == "—"


def test_delta_pp_positive_scaled_by_100():
    assert urm._delta_pp(0.9, 0.5) == "+40.0pp"


def test_delta_pp_negative():
    assert urm._delta_pp(0.5, 0.9) == "-40.0pp"


def test_delta_pp_exact_zero_is_positive_sign():
    # delta >= 0 boundary: an exactly-zero delta renders with a leading "+".
    assert urm._delta_pp(0.5, 0.5) == "+0.0pp"


# ---------------------------------------------------------------------------
# load_summary — setdefault every REQUIRED_KEYS, keep present values
# ---------------------------------------------------------------------------


def test_load_summary_fills_required_keys_and_keeps_present(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"accuracy": 0.91}), encoding="utf-8")
    data = urm.load_summary(path)
    # Present key keeps its value.
    assert data["accuracy"] == 0.91
    # Every REQUIRED key is present afterward.
    for key in urm.REQUIRED_KEYS:
        assert key in data
    # Missing keys defaulted to None (not dropped, not fabricated).
    assert data["retry"] is None
    assert data["latency"] is None


# ---------------------------------------------------------------------------
# render_table — light structural lock + non-crash on degenerate ablation
# ---------------------------------------------------------------------------


def test_render_table_with_full_run_emits_pipe_rows():
    summary = {
        "accuracy": 0.9,
        "ablation": {
            "runs": [{"name": "full", "accuracy": 0.9, "latency": {"p50": 1.0, "p95": 2.0}}]
        },
    }
    rendered = urm.render_table(summary)
    assert isinstance(rendered, str)
    assert any(line.lstrip().startswith("|") for line in rendered.splitlines())


def test_render_table_missing_ablation_does_not_crash():
    assert isinstance(urm.render_table({"accuracy": 0.9}), str)


def test_render_table_non_dict_ablation_does_not_crash():
    assert isinstance(urm.render_table({"ablation": 5}), str)
