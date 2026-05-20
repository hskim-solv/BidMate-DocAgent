"""Tests for ``scripts/analyze_hook_outcomes.py`` (issue #1037).

거버넌스 비판 #7 후속. 90일 데이터 누적 후 사용자가 실행하는 분석
스크립트의 (a) 3/4/5-field 포맷 parse, (b) window filtering, (c)
threshold 추천 분기, (d) surface reduction 후보 식별 회귀 테스트.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_hook_outcomes.py"


def _load_script():
    """Import the script module without making it a package import."""
    spec = importlib.util.spec_from_file_location(
        "analyze_hook_outcomes", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def aho():
    return _load_script()


# ---------------------------------------------------------------------------
# parse_log_line
# ---------------------------------------------------------------------------


def test_parse_v2_5field(aho):
    line = (
        "2026-05-19T10:30:00Z|blocked|bash-guard|gh-pr-create-stacked|"
        "feat/issue-99-foo|on=feat/issue-88-bar"
    )
    ev = aho.parse_log_line(line)
    assert ev is not None
    assert ev["outcome"] == "blocked"
    assert ev["hook"] == "bash-guard"
    assert ev["category"] == "gh-pr-create-stacked"
    assert ev["path"] == "feat/issue-99-foo"
    assert ev["extra"] == "on=feat/issue-88-bar"
    assert ev["format"] == "v2-5field"


def test_parse_v1_4field_memory_lines(aho):
    line = "2026-05-15T09:51:19Z|ok|memory-lines|MEMORY.md"
    ev = aho.parse_log_line(line)
    assert ev is not None
    assert ev["outcome"] == "ok"
    assert ev["hook"] == "memory-lines"
    assert ev["category"] == "memory-lines"
    assert ev["path"] == "MEMORY.md"
    assert ev["format"] == "v1-4field"


def test_parse_v1_3field_loadbearing(aho):
    line = "2026-05-14T09:51:19Z|load-bearing|rag_core.py"
    ev = aho.parse_log_line(line)
    assert ev is not None
    assert ev["outcome"] == "aware"  # 3-field implies awareness
    assert ev["hook"] == "loadbearing"
    assert ev["category"] == "load-bearing"
    assert ev["path"] == "rag_core.py"
    assert ev["format"] == "v1-3field"


def test_parse_unknown_outcome_normalized(aho):
    line = "2026-05-19T10:30:00Z|made_up|bash-guard|cat|path|extra"
    ev = aho.parse_log_line(line)
    assert ev is not None
    assert ev["outcome"] == "unknown"


def test_parse_malformed_skipped(aho):
    assert aho.parse_log_line("") is None
    assert aho.parse_log_line("# comment line") is None
    assert aho.parse_log_line("not-a-timestamp|x|y") is None
    assert aho.parse_log_line("2026-05-19T10:30:00Z|only-two") is None


# ---------------------------------------------------------------------------
# filter_window
# ---------------------------------------------------------------------------


def _make_event(ts: datetime, hook: str = "bash-guard", outcome: str = "aware"):
    return {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome,
        "hook": hook,
        "category": "",
        "path": "",
        "extra": "",
        "format": "v2-5field",
    }


def test_filter_window_days(aho):
    now = datetime.now(timezone.utc)
    events = [
        _make_event(now - timedelta(days=1)),
        _make_event(now - timedelta(days=10)),
        _make_event(now - timedelta(days=100)),
    ]
    out = aho.filter_window(events, "30d")
    assert len(out) == 2  # 1d + 10d, not 100d


def test_filter_window_hours(aho):
    now = datetime.now(timezone.utc)
    events = [
        _make_event(now - timedelta(hours=1)),
        _make_event(now - timedelta(hours=24)),
    ]
    out = aho.filter_window(events, "6h")
    assert len(out) == 1


def test_filter_window_all(aho):
    events = [_make_event(datetime(2000, 1, 1, tzinfo=timezone.utc))]
    assert aho.filter_window(events, "all") == events


def test_filter_window_invalid_raises(aho):
    with pytest.raises(ValueError):
        aho.filter_window([], "30")


# ---------------------------------------------------------------------------
# outcome_breakdown
# ---------------------------------------------------------------------------


def test_outcome_breakdown(aho):
    now = datetime.now(timezone.utc)
    events = [
        _make_event(now, "bash-guard", "blocked"),
        _make_event(now, "bash-guard", "blocked"),
        _make_event(now, "bash-guard", "aware"),
        _make_event(now, "loadbearing", "aware"),
    ]
    out = aho.outcome_breakdown(events)
    assert out["bash-guard"] == {"blocked": 2, "aware": 1}
    assert out["loadbearing"] == {"aware": 1}


# ---------------------------------------------------------------------------
# threshold_recommendation
# ---------------------------------------------------------------------------


def test_threshold_insufficient_data(aho):
    out = aho.threshold_recommendation([])
    assert out["verdict"] == "insufficient_data"
    assert out["observed_total"] == 0


def test_threshold_maintain_low_block_ratio(aho):
    now = datetime.now(timezone.utc)
    events = [_make_event(now, "memory-lines", "aware") for _ in range(40)]
    events.append(_make_event(now, "memory-lines", "blocked"))  # 1/41 ≈ 2.4%
    out = aho.threshold_recommendation(events)
    assert out["verdict"] == "maintain"
    assert out["observed_blocked"] == 1
    assert out["observed_aware"] == 40


def test_threshold_raise_block_high_ratio(aho):
    now = datetime.now(timezone.utc)
    events = [_make_event(now, "memory-lines", "blocked") for _ in range(5)]
    events.extend(_make_event(now, "memory-lines", "aware") for _ in range(5))
    # 5/10 = 50% blocked → recommendation raise
    out = aho.threshold_recommendation(events)
    assert out["verdict"] == "raise_block"


def test_threshold_ignores_other_hooks(aho):
    now = datetime.now(timezone.utc)
    events = [_make_event(now, "bash-guard", "blocked")]
    out = aho.threshold_recommendation(events)
    assert out["verdict"] == "insufficient_data"


# ---------------------------------------------------------------------------
# surface_reduction_candidates
# ---------------------------------------------------------------------------


def test_surface_reduction_all_silent(aho):
    out = aho.surface_reduction_candidates([], "90d")
    assert set(out) == set(aho.ALL_HOOKS)


def test_surface_reduction_partial(aho):
    now = datetime.now(timezone.utc)
    events = [
        _make_event(now, "bash-guard", "blocked"),
        _make_event(now, "loadbearing", "aware"),
    ]
    out = aho.surface_reduction_candidates(events, "90d")
    assert "bash-guard" not in out
    assert "loadbearing" not in out
    assert "memory-lines" in out  # didn't fire


# ---------------------------------------------------------------------------
# End-to-end: load_log + render_json
# ---------------------------------------------------------------------------


def test_load_log_and_render(tmp_path, aho):
    log = tmp_path / ".hook-fires.log"
    log.write_text(
        # mix of all three formats
        "2026-05-19T10:30:00Z|blocked|bash-guard|gh-pr-create-stacked|br|on=other\n"
        "2026-05-15T09:51:19Z|ok|memory-lines|MEMORY.md\n"
        "2026-05-14T09:51:19Z|load-bearing|rag_core.py\n"
        "\n"
        "# this is a comment, skip\n"
        "malformed line with no timestamp\n",
        encoding="utf-8",
    )
    events = aho.load_log(log)
    assert len(events) == 3
    formats = {e["format"] for e in events}
    assert formats == {"v2-5field", "v1-4field", "v1-3field"}

    js = json.loads(aho.render_json(events, "all"))
    assert js["total_events"] == 3
    assert js["format_mix"]["v2-5field"] == 1
    assert "loadbearing" in js["outcome_breakdown"]


def test_load_log_missing_file_returns_empty(aho, tmp_path):
    assert aho.load_log(tmp_path / "nonexistent.log") == []


def test_render_text_includes_all_hooks(aho):
    out = aho.render_text([], "90d")
    # 0-fire 시에도 모든 hook 이 표 안에 있어야 surface 측정 가능
    for hook in aho.ALL_HOOKS:
        assert hook in out
