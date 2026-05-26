from __future__ import annotations

from scripts.pr_eval_change_scope import classify


def test_agent_loop_change_runs_pytest_but_skips_fixture_smoke() -> None:
    scope = classify(["scripts/agent_loop.py"])

    assert scope.pytest is True
    assert scope.runtime is False


def test_rag_module_runs_pytest_and_fixture_smoke() -> None:
    scope = classify(["rag_core.py"])

    assert scope.pytest is True
    assert scope.runtime is True


def test_docs_only_skips_pytest_and_fixture_smoke() -> None:
    scope = classify(["docs/operations/auto-ship.md"])

    assert scope.pytest is False
    assert scope.runtime is False


def test_report_only_skips_pytest_and_fixture_smoke() -> None:
    scope = classify(["reports/real100/baseline.aggregate.json"])

    assert scope.pytest is False
    assert scope.runtime is False


def test_eval_tree_runs_pytest_and_fixture_smoke() -> None:
    scope = classify(["eval/naive_rag/benchmark.py"])

    assert scope.pytest is True
    assert scope.runtime is True


def test_requirements_run_pytest_and_fixture_smoke() -> None:
    scope = classify(["requirements-dev.txt"])

    assert scope.pytest is True
    assert scope.runtime is True


def test_pr_eval_workflow_runs_pytest_and_fixture_smoke() -> None:
    scope = classify([".github/workflows/pr-eval.yml"])

    assert scope.pytest is True
    assert scope.runtime is True


def test_eval_delta_helper_runs_pytest_and_fixture_smoke() -> None:
    scope = classify(["scripts/_eval_delta.py"])

    assert scope.pytest is True
    assert scope.runtime is True


def test_other_workflow_runs_pytest_but_skips_fixture_smoke() -> None:
    scope = classify([".github/workflows/agent-loop-artifacts.yml"])

    assert scope.pytest is True
    assert scope.runtime is False


def test_unknown_tooling_file_fails_toward_pytest_not_fixture_smoke() -> None:
    scope = classify(["Dockerfile"])

    assert scope.pytest is True
    assert scope.runtime is False
