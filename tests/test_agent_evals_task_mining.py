from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_task_mining_uses_sanitized_metadata_only() -> None:
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_test")

    tasks, summary = mining.mine_tasks(
        [
            {
                "number": 1336,
                "merged": True,
                "category": "hook_privacy",
                "signals": ["deny-by-default guard", "local precommit mirror"],
            },
            {
                "number": 1337,
                "merged": False,
                "category": "hook_privacy",
                "signals": ["ignored because not merged"],
            },
            {
                "number": 1338,
                "merged": True,
                "category": "hook_privacy",
                "signals": ["ignored because raw payload was detected"],
                "contains_raw_payload": True,
            },
        ],
        mineable_floor=2,
        holdout_target=1,
    )

    assert len(tasks) == 1
    assert summary.mineable_count == 1
    assert summary.warnings == ("mineable floor not met: 1 < 2",)
    task = tasks[0]
    assert task["task_id"] == "T-1336"
    forbidden = {"title", "issue_id", "pr_body", "patch", "filename", "path", "query", "answer", "evidence"}
    assert forbidden.isdisjoint(task)


def test_rendered_task_yaml_passes_content_scanner() -> None:
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_render_test")
    scanner = load_module("agent-evals/core/report.py", "agent_evals_report_for_task_mining_test")

    tasks, _summary = mining.mine_tasks(
        [
            {
                "number": 1820,
                "merged": True,
                "category": "eval_guard",
                "signals": ["paired delta primitive"],
            }
        ],
        mineable_floor=1,
        holdout_target=1,
    )
    text = mining.render_task_yaml(tasks[0])

    violations = scanner.validate_agent_eval_file("agent-evals/tasks/T-1820/task.yaml", text)

    assert [violation.render() for violation in violations] == []


def test_non_allowlisted_category_is_not_mineable() -> None:
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_category_test")

    assert not mining.is_mineable(
        {
            "number": 1500,
            "merged": True,
            "category": "freeform",
            "signals": ["would be too unconstrained"],
        }
    )
