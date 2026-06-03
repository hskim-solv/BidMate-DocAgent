from __future__ import annotations

import json

from scripts.pr_eval_change_scope import _read_changed_files_jsonl, classify


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


def test_agent_evals_raw_md_force_add_runs_pytest_guard() -> None:
    # ADR 0100: a force-added raw artifact disguised as .md/.txt under agent-evals/ would be
    # classified docs-only and skip pytest — leaving the index-aware privacy guard toothless
    # in CI. Any agent-evals/ path except README must force the pytest job.
    scope = classify(["agent-evals/runs/T-1/secret.md"])

    assert scope.pytest is True
    assert scope.runtime is False


def test_agent_evals_readme_only_does_not_force_pytest() -> None:
    # The sole committable agent-evals/ file (README) is the explicit exception: a
    # README-only change stays docs-only (no forced pytest).
    scope = classify(["agent-evals/README.md"])

    assert scope.pytest is False
    assert scope.runtime is False


def test_agent_evals_readme_whitespace_variant_forces_pytest() -> None:
    # ADR 0100: a trailing-whitespace path is a DIFFERENT git file than the exact README
    # exception. It must fail closed to pytest (not be normalized into the exception and
    # skip the index-aware privacy guard).
    scope = classify(["agent-evals/README.md "])

    assert scope.pytest is True


def test_leading_whitespace_path_fails_closed_to_pytest() -> None:
    # Any leading/trailing-whitespace path fails closed (do not trim meaningful path chars
    # before the policy check).
    scope = classify([" agent-evals/runs/x.md"])

    assert scope.pytest is True


def test_jsonl_transport_preserves_embedded_newline(tmp_path) -> None:
    # ADR 0100: a newline-delimited transport (`splitlines()`) would split a hostile filename
    # `agent-evals/README.md\n` into a clean `agent-evals/README.md` token that masquerades as
    # the README exception. The JSONL transport (@json per line) round-trips the embedded
    # newline intact so the classifier can see — and fail closed on — it.
    p = tmp_path / "files.jsonl"
    p.write_text(json.dumps("agent-evals/README.md\n") + "\n", encoding="utf-8")

    assert _read_changed_files_jsonl(str(p)) == ["agent-evals/README.md\n"]


def test_jsonl_newline_suffixed_readme_forces_pytest(tmp_path) -> None:
    # End-to-end: a JSONL list whose only entry is the newline-suffixed README must still
    # force pytest (so the index-aware privacy guard runs), not be waved through as docs-only.
    p = tmp_path / "files.jsonl"
    p.write_text(json.dumps("agent-evals/README.md\n") + "\n", encoding="utf-8")

    scope = classify(_read_changed_files_jsonl(str(p)))

    assert scope.pytest is True


def test_jsonl_clean_readme_does_not_force_pytest(tmp_path) -> None:
    # The clean README path over the JSONL transport stays docs-only (no forced pytest) —
    # the newline-safe transport must not over-trigger on the legitimate exception.
    p = tmp_path / "files.jsonl"
    p.write_text(json.dumps("agent-evals/README.md") + "\n", encoding="utf-8")

    scope = classify(_read_changed_files_jsonl(str(p)))

    assert scope.pytest is False
