import json
import subprocess
from pathlib import Path

from scripts import agent_loop_codex_turn as codex_turn


def test_run_turn_maps_codex_result_to_review_core(tmp_path: Path) -> None:
    companion = tmp_path / "codex-companion.mjs"
    companion.write_text("// fake\n")

    def runner(path, base, scope, focus, model):
        assert (path, base, scope, focus, model) == (companion, "main", "diff", "rag", "gpt-test")
        payload = {
            "result": {
                "verdict": "approve",
                "summary": "Looks good",
                "findings": [{"severity": "high", "title": "Risk", "body": "fix", "file": "a.py", "line_start": 7, "line_end": 9, "recommendation": "patch"}],
                "next_steps": ["ship", 123],
            }
        }
        return subprocess.CompletedProcess(["node"], 0, stdout=json.dumps(payload))

    result = codex_turn.run_turn(base="main", scope="diff", focus="rag", model="gpt-test", companion_path=str(companion), runner=runner)

    assert result == {
        "verdict": "approved",
        "summary": "Looks good",
        "findings": [{"severity": "blocker", "title": "Risk", "body": "[a.py:7-9] fix", "recommendation": "patch"}],
        "next_steps": ["ship"],
    }


def test_run_turn_returns_error_core_for_runner_failure(tmp_path: Path) -> None:
    companion = tmp_path / "codex-companion.mjs"
    companion.write_text("// fake\n")

    def runner(*_args):
        return subprocess.CompletedProcess(["node"], 2, stderr="first\nlast detail\n")

    result = codex_turn.run_turn(companion_path=str(companion), runner=runner)

    assert result == {
        "verdict": "error",
        "summary": "codex companion rc=2: last detail",
        "findings": [],
        "next_steps": [],
    }
