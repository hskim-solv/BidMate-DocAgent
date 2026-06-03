from __future__ import annotations

from scripts import reproduce_claude_streamjson_subprocess as repro


def test_subscription_env_strips_raw_anthropic_keys(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(key, "secret")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/safe/oauth/config")
    env = repro.subscription_env()
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"}.isdisjoint(env)
    assert env["CLAUDE_CONFIG_DIR"] == "/safe/oauth/config"


def test_build_command_uses_streamjson_transport_and_default_mode(tmp_path):
    default_cmd = repro.build_command(permission_mode="default", work=tmp_path)
    plan_cmd = repro.build_command(permission_mode="plan", work=tmp_path)
    assert default_cmd[:6] == ["claude", "--output-format", "stream-json", "--verbose", "--input-format", "stream-json"]
    assert "--permission-mode" not in default_cmd
    assert ["--permission-mode", "plan"] == plan_cmd[-2:]
    assert ["--add-dir", str(tmp_path)] == default_cmd[-2:]


def test_classify_preserves_streamjson_symptom_order():
    cases = [
        ({"edited": True}, "S4_normal"),
        ({"duration": 30}, "S3_timeout"),
        ({"result_text": "tool_use ids must be unique"}, "S2_tool_use_ids"),
        ({"exception": "RuntimeError"}, "S2_or_other_exception"),
        ({"result_subtype": "success", "result_is_error": False, "tool_use_count": 1}, "S4_success_without_target_match"),
        ({"result_is_error": True}, "S2_or_other_error"),
        ({"tool_use_count": 0}, "S1_no_tool_call"),
    ]
    defaults = {
        "edited": False, "exception": None, "result_subtype": None,
        "result_is_error": None, "result_text": "", "duration": 1,
        "timeout": 30, "tool_use_count": 1,
    }
    for overrides, expected in cases:
        assert repro.classify(**(defaults | overrides)) == expected
