from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

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


def test_render_task_yaml_quotes_colon_signals() -> None:
    # P2 (cross-family review): a governance-style signal containing a colon must
    # render as a string, not silently reparse into a mapping that corrupts the
    # acceptance contract.
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_colon_test")

    tasks, _summary = mining.mine_tasks(
        [
            {
                "number": 1500,
                "merged": True,
                "category": "doc_contract",
                "signals": ["ADR 0005: privacy guard"],
            }
        ],
        mineable_floor=1,
        holdout_target=1,
    )
    parsed = yaml.safe_load(mining.render_task_yaml(tasks[0]))

    assert parsed["acceptance"] == ["preserve ADR 0005: privacy guard"]


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


def test_string_signals_is_not_mineable() -> None:
    # signals must be a non-string Sequence. A bare string would otherwise satisfy
    # a naive truthiness check and then be iterated character-by-character into the
    # acceptance contract, so is_mineable rejects it outright.
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_str_signals_test")

    assert not mining.is_mineable(
        {
            "number": 1500,
            "merged": True,
            "category": "hook_privacy",
            "signals": "deny-by-default guard",
        }
    )


def test_empty_signals_is_not_mineable() -> None:
    # A record with no signals carries no behavior to preserve, so it is not a
    # usable task contract even when every other gate passes.
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_empty_signals_test")

    assert not mining.is_mineable(
        {
            "number": 1500,
            "merged": True,
            "category": "hook_privacy",
            "signals": [],
        }
    )


def test_mine_tasks_warns_when_holdout_target_exceeds_mineable_count() -> None:
    # The holdout-target warning is a DISTINCT contract from the mineable-floor
    # warning (existing coverage only trips the floor warning with holdout == count).
    # When the requested holdout split is larger than the mineable set, mine_tasks
    # must surface it so an undersized holdout is never claimed silently. Set the
    # floor low enough to be met, isolating the holdout warning.
    mining = load_module("agent-evals/adapters/bidmate/task_mining.py", "agent_evals_task_mining_holdout_warn_test")

    tasks, summary = mining.mine_tasks(
        [
            {"number": 1, "merged": True, "category": "eval_guard", "signals": ["paired delta primitive"]},
            {"number": 2, "merged": True, "category": "eval_guard", "signals": ["min-N guard"]},
        ],
        mineable_floor=1,
        holdout_target=5,
    )

    assert len(tasks) == 2
    assert summary.mineable_count == 2
    assert summary.holdout_target == 5
    assert summary.warnings == ("holdout target exceeds mineable count: 5 > 2",)
