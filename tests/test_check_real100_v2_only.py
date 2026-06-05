from __future__ import annotations

from scripts import check_real100_v2_only as guard


def test_task_block_returns_only_requested_queue_section():
    text = """
## T-2026-0028
Use real100_v2 and make real-eval-v2-check.
## T-2026-0029
Next task text.
"""
    block = guard._task_block(text, "T-2026-0028", "T-2026-0029")
    assert "T-2026-0028" in block
    assert "real100_v2" in block
    assert "T-2026-0029" not in block
    assert guard._task_block(text, "T-2026-9999", None) == ""


def test_command_lines_only_reports_fenced_commands():
    text = """
make real-eval
```bash
make real-eval
make real-eval-v2-check
```
"""
    assert guard._command_lines(text) == [
        (4, "make real-eval"),
        (5, "make real-eval-v2-check"),
    ]


def test_ban_context_and_stale_command_detection_are_separate():
    assert guard._is_ban_context("legacy reports/real100 is banned") is True
    assert guard._is_ban_context("reports/real100 사용하지 말고 real100_v2를 사용") is True
    assert guard._is_ban_context("legacy real100 집계는 금지") is True
    assert guard._is_ban_context("Use reports/real100 for a new claim") is False
    assert guard.STALE_COMMAND_RE.match("make real-eval")
    assert guard.STALE_COMMAND_RE.match("REAL_EVAL_ROOT=/x make real-eval --foo")
    assert not guard.STALE_COMMAND_RE.match("make real-eval-v2-check")
