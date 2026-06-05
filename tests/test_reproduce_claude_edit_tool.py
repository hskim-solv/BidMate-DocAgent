from __future__ import annotations

from scripts import reproduce_claude_edit_tool as repro


def test_subscription_env_strips_raw_anthropic_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/safe/oauth/config")
    env = repro.subscription_env()
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"}.isdisjoint(env)
    assert env["CLAUDE_CONFIG_DIR"] == "/safe/oauth/config"


def test_classify_preserves_reproducer_symptom_order():
    cases = [
        ({"exit_code": 0, "stdout": "", "stderr": "", "edited": True, "duration": 1}, "S4_normal"),
        ({"exit_code": None, "stdout": "", "stderr": "", "edited": False, "duration": 30}, "S3_timeout"),
        ({"exit_code": 1, "stdout": '{"result":"tool_use ids must be unique"}', "stderr": "", "edited": False, "duration": 1}, "S2_tool_use_ids"),
        ({"exit_code": 0, "stdout": "no edit", "stderr": "", "edited": False, "duration": 1}, "S1_no_tool_call"),
    ]
    for kwargs, expected in cases:
        assert repro.classify(**kwargs, timeout=30) == expected


def test_classify_detects_tool_use_unique_error_from_stderr():
    assert repro.classify(
        exit_code=1,
        stdout="",
        stderr="API error: tool_use ids must be unique",
        edited=False,
        duration=1,
        timeout=30,
    ) == "S2_tool_use_ids"


def test_render_markdown_table_escapes_pipe_cells():
    result = repro.CellResult(
        label="cell", cmd=["claude"], exit_code=None, duration_s=3.5,
        stdout_head="", stderr_tail="bad | tail", file_after="a\n",
        edited=False, symptom="S3_timeout", note="note | detail",
    )
    table = repro.render_markdown_table([result])
    assert "timeout" in table
    assert "bad \\| tail" in table
    assert "note \\| detail" in table
