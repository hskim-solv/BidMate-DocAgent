"""Regression: narrative-gap raw signals (issue #1088).

Locks the RAW-SIGNAL contract — the collector juxtaposes a memory self-claim
with the git ground-truth value and emits the arithmetic gap, never a verdict.
Out of scope (asserted absent): word-count ratios, semantic matching, and
auto-grading (the discarded first attempt, stash-dropped).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "claude-hooks" / "_self_review.py"
)
_spec = importlib.util.spec_from_file_location("_self_review_nb", _MOD_PATH)
assert _spec is not None and _spec.loader is not None  # _MOD_PATH is a real file
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


GIT_FIXTURE = {
    "commits": 42,
    "load_bearing_touches": 5,
    "prs_merged": [{"number": n} for n in range(1, 16)],  # 15
    "adr_changes": [{"id": "0099"}, {"id": "0100"}],       # 2
}


def test_gap_is_arithmetic_difference():
    claims = [{"signal": "prs_merged_count", "claim_value": 20,
               "source_memory": "x.md", "window": "Q2-2026"}]
    s = sr.compute_narrative_gaps(claims, GIT_FIXTURE, "Q2-2026")[0]
    assert s["claim_value"] == 20
    assert s["git_value"] == 15
    assert s["gap"] == 5
    assert s["grounded"] is True
    assert s["window_match"] is True
    assert s["source_memory"] == "x.md"


def test_commits_signal_grounded_negative_gap():
    claims = [{"signal": "commits", "claim_value": 40}]
    s = sr.compute_narrative_gaps(claims, GIT_FIXTURE, "Q2-2026")[0]
    assert s["git_value"] == 42
    assert s["gap"] == -2
    assert s["window"] is None
    assert s["window_match"] is None


def test_unknown_signal_ungrounded_not_error():
    claims = [{"signal": "plan_calls", "claim_value": 3}]
    s = sr.compute_narrative_gaps(claims, GIT_FIXTURE, "Q2-2026")[0]
    assert s["git_value"] is None
    assert s["gap"] is None
    assert s["grounded"] is False


def test_window_mismatch_flagged_gap_still_raw():
    claims = [{"signal": "commits", "claim_value": 1, "window": "Q1-2026"}]
    s = sr.compute_narrative_gaps(claims, GIT_FIXTURE, "Q2-2026")[0]
    assert s["window_match"] is False
    assert s["gap"] == 1 - 42  # raw difference regardless of window mismatch


def test_non_numeric_claim_value_gap_none():
    claims = [{"signal": "commits", "claim_value": "lots"}]
    s = sr.compute_narrative_gaps(claims, GIT_FIXTURE, "Q2-2026")[0]
    assert s["gap"] is None
    assert s["git_value"] == 42  # git side still grounded


def test_no_verdict_keys_emitted():
    """RAW SIGNAL contract: no ✓/△/✗ / verdict / grade fields leak in."""
    claims = [{"signal": "commits", "claim_value": 40}]
    s = sr.compute_narrative_gaps(claims, GIT_FIXTURE, "Q2-2026")[0]
    forbidden = {"verdict", "grade", "status", "pass", "rating", "band", "score"}
    assert forbidden.isdisjoint(s.keys())


def test_empty_claims_empty_signals():
    assert sr.compute_narrative_gaps([], GIT_FIXTURE, "Q2-2026") == []


def test_load_registry_missing_file_empty(tmp_path):
    assert sr.load_narrative_claims(str(tmp_path / "nope.json")) == []


def test_load_registry_malformed_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert sr.load_narrative_claims(str(p)) == []


def test_load_registry_non_dict_claims_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"claims": "oops"}))
    assert sr.load_narrative_claims(str(p)) == []


def test_load_registry_filters_non_dict_entries(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"claims": [
        {"signal": "commits", "claim_value": 10},
        "not-a-dict",
        {"signal": "prs_merged_count", "claim_value": 3},
    ]}))
    out = sr.load_narrative_claims(str(p))
    assert len(out) == 2  # non-dict entry filtered
    assert out[0]["signal"] == "commits"


def test_committed_registry_loads_and_is_list():
    """The repo-committed registry must parse (even with claims empty)."""
    repo_root = _MOD_PATH.parent.parent.parent
    reg = repo_root / "docs" / "self-review" / "narrative-claims.json"
    assert isinstance(sr.load_narrative_claims(str(reg)), list)


def test_assemble_stats_wires_narrative_gap_signals(tmp_path):
    """Wire check (#1828 dead-param lesson): signal reaches assembled stats."""
    reg = tmp_path / "narrative-claims.json"
    reg.write_text(json.dumps({"claims": [
        {"signal": "adr_changes_count", "claim_value": 9, "window": "Q2-2026"}
    ]}))
    repo_root = _MOD_PATH.parent.parent.parent  # real git worktree
    stats = sr.assemble_stats(
        "Q2-2026",
        transcripts_glob=str(tmp_path / "none*.jsonl"),
        memory_dir=str(tmp_path / "no-memory"),
        repo=str(repo_root),
        narrative_claims_path=str(reg),
    )
    assert "narrative_gap_signals" in stats
    sigs = stats["narrative_gap_signals"]
    assert len(sigs) == 1
    assert sigs[0]["signal"] == "adr_changes_count"
    assert sigs[0]["claim_value"] == 9
    assert isinstance(sigs[0]["git_value"], int)  # grounded against real git
    assert sigs[0]["grounded"] is True
