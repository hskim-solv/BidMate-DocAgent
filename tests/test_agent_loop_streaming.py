"""Tests for issue #1654 — agent-loop live progress streaming.

Covers the JSONL → emoji summary formatter, the env-gated progress emitter,
and the reader-thread tee for codex subprocess stdout.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_stream_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIDMATE_AGENT_LOOP_QUIET", raising=False)
    monkeypatch.delenv("BIDMATE_AGENT_LOOP_RAW", raising=False)


def test_stream_enabled_default_true() -> None:
    assert agent_loop._agent_loop_stream_enabled() is True


def test_stream_enabled_quiet_env_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "yes", "ON"):
        monkeypatch.setenv("BIDMATE_AGENT_LOOP_QUIET", value)
        assert agent_loop._agent_loop_stream_enabled() is False


def test_stream_enabled_quiet_blank_still_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIDMATE_AGENT_LOOP_QUIET", "0")
    assert agent_loop._agent_loop_stream_enabled() is True
    monkeypatch.setenv("BIDMATE_AGENT_LOOP_QUIET", "")
    assert agent_loop._agent_loop_stream_enabled() is True


def test_emit_progress_writes_and_flushes(capsys: pytest.CaptureFixture[str]) -> None:
    agent_loop._emit_progress("[active-start] hello world")
    captured = capsys.readouterr()
    assert captured.out == "[active-start] hello world\n"


def test_emit_progress_noop_when_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BIDMATE_AGENT_LOOP_QUIET", "1")
    agent_loop._emit_progress("should not appear")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_emit_progress_skips_empty() -> None:
    # Must not raise / not write — no capsys check needed beyond no exception.
    agent_loop._emit_progress("")


def test_format_jsonl_summary_agent_message() -> None:
    line = json.dumps({"type": "agent_message", "content": "Reading rag_core.py to understand structure..."})
    result = agent_loop._format_codex_jsonl_summary("claude-impl", line)
    assert result.startswith("[claude-impl] 💬 ")
    assert "Reading rag_core.py" in result


def test_format_jsonl_summary_agent_message_nested_msg() -> None:
    line = json.dumps({"msg": {"type": "agent_message", "content": "Hello from codex"}})
    result = agent_loop._format_codex_jsonl_summary("codex-review", line)
    assert "💬" in result
    assert "Hello from codex" in result


def test_format_jsonl_summary_tool_use_extracts_args() -> None:
    line = json.dumps(
        {
            "type": "tool_use",
            "name": "Read",
            "input": {"path": "rag_core.py", "limit": 100},
        }
    )
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert "🔧" in result
    assert "Read(" in result
    assert "path" in result


def test_format_jsonl_summary_exec_command() -> None:
    line = json.dumps(
        {"type": "exec_command_begin", "command": ["git", "diff", "--stat"]}
    )
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert "⚙" in result
    assert "git diff" in result


def test_format_jsonl_summary_task_complete() -> None:
    line = json.dumps(
        {"type": "task_complete", "exit_code": 0, "duration_s": 42.3}
    )
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert "✓" in result
    assert "rc=0" in result
    assert "42.3" in result


def test_format_jsonl_summary_error() -> None:
    line = json.dumps({"type": "error", "message": "auth required"})
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert "❌" in result
    assert "auth required" in result


def test_format_jsonl_summary_unknown_type_uses_questionmark() -> None:
    line = json.dumps({"type": "novel_event_v99", "content": "future schema"})
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert "❔" in result
    assert "novel_event_v99" in result


def test_format_jsonl_summary_parse_failure_uses_warn() -> None:
    result = agent_loop._format_codex_jsonl_summary("impl", "not-a-json-line {{{")
    assert "⚠" in result
    assert "not-a-json-line" in result


def test_format_jsonl_summary_non_dict_payload() -> None:
    result = agent_loop._format_codex_jsonl_summary("impl", '"just a string"')
    assert "⚠" in result


def test_format_jsonl_summary_empty_line_returns_empty() -> None:
    assert agent_loop._format_codex_jsonl_summary("impl", "") == ""
    assert agent_loop._format_codex_jsonl_summary("impl", "   \n") == ""


def test_format_jsonl_summary_raw_env_returns_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIDMATE_AGENT_LOOP_RAW", "1")
    line = json.dumps({"type": "agent_message", "content": "hi"})
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert result.startswith("[impl] ")
    # When RAW=1 the unparsed line is returned, so the literal JSON should appear.
    assert "agent_message" in result
    assert "💬" not in result


def test_format_jsonl_summary_message_segments_list() -> None:
    # Codex sometimes sends content as a list of segments.
    line = json.dumps(
        {
            "type": "agent_message",
            "content": [
                {"text": "Found bug in"},
                {"text": "retrieve_candidates"},
            ],
        }
    )
    result = agent_loop._format_codex_jsonl_summary("impl", line)
    assert "Found bug in" in result
    assert "retrieve_candidates" in result


def test_spawn_codex_reader_thread_writes_file_and_emits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stream = io.StringIO(
        json.dumps({"type": "task_started"}) + "\n"
        + json.dumps({"type": "agent_message", "content": "hello"}) + "\n"
        + json.dumps({"type": "task_complete", "exit_code": 0}) + "\n"
    )

    class FakeProc:
        def __init__(self, stream_: io.StringIO) -> None:
            self.stdout = stream_

    proc = FakeProc(stream)
    stdout_path = tmp_path / "session" / "stdout.jsonl"
    thread = agent_loop._spawn_codex_reader_thread(proc, "test-session", stdout_path)
    assert thread is not None
    thread.join(timeout=5.0)
    assert not thread.is_alive()

    written = stdout_path.read_text(encoding="utf-8")
    assert '"task_started"' in written
    assert '"agent_message"' in written
    assert '"task_complete"' in written

    captured = capsys.readouterr()
    assert "▶" in captured.out
    assert "💬 hello" in captured.out
    assert "✓ rc=0" in captured.out


def test_spawn_codex_reader_thread_none_stdout_creates_empty_file(tmp_path: Path) -> None:
    class FakeProc:
        stdout = None

    proc = FakeProc()
    stdout_path = tmp_path / "no-stdout" / "stdout.jsonl"
    thread = agent_loop._spawn_codex_reader_thread(proc, "x", stdout_path)
    assert thread is None
    assert stdout_path.exists()
    assert stdout_path.read_text(encoding="utf-8") == ""


def test_spawn_codex_reader_thread_quiet_env_no_stdout_but_file_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BIDMATE_AGENT_LOOP_QUIET", "1")
    stream = io.StringIO(json.dumps({"type": "agent_message", "content": "secret"}) + "\n")

    class FakeProc:
        def __init__(self, stream_: io.StringIO) -> None:
            self.stdout = stream_

    proc = FakeProc(stream)
    stdout_path = tmp_path / "quiet" / "stdout.jsonl"
    thread = agent_loop._spawn_codex_reader_thread(proc, "q", stdout_path)
    assert thread is not None
    thread.join(timeout=5.0)
    captured = capsys.readouterr()
    # File contract preserved even when stdout muted.
    assert "secret" in stdout_path.read_text(encoding="utf-8")
    # Nothing emitted to stdout under QUIET mode.
    assert captured.out == ""


def test_spawn_codex_reader_thread_no_readline_attr_creates_file(tmp_path: Path) -> None:
    class FakeStream:
        # No readline attribute — reader should bail and touch the file.
        def __repr__(self) -> str:
            return "<no-readline>"

    class FakeProc:
        stdout = FakeStream()

    proc = FakeProc()
    stdout_path = tmp_path / "nopen" / "stdout.jsonl"
    thread = agent_loop._spawn_codex_reader_thread(proc, "x", stdout_path)
    assert thread is None
    assert stdout_path.exists()
