from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import agent_loop


ROOT = Path(__file__).resolve().parents[1]


def _write_repo(
    tmp_path: Path,
    *,
    task_id: str = "T-2026-9999",
    title: str = "Agent loop automation",
    status: str = "ready",
    body_extra: str = "",
) -> Path:
    (tmp_path / "tasks").mkdir(parents=True)
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    queue = f"""# Persistent Task Queue

## Ready Order

| Order | ID | Status | Owner role | Why ready / not ready |
|---:|---|---|---|---|
| 1 | `{task_id}` | `{status}` | Implementer -> Reviewer | fixture ready task |

## {task_id} — {title}

- ID: {task_id}
- Title: {title}
- Status: {status}
- Owner role: Implementer -> Reviewer

### Goal

Automate the existing operating loop without changing product behavior.

### Acceptance Criteria

- [ ] CLI renders prompts and checks handoffs.

### Validation Commands

```bash
python3 -m pytest tests/test_agent_loop.py -q
git diff --check
```

### Related Plan / Issue / PR Links

- Plan: [`docs/plans/{task_id}-agent-loop.md`](../docs/plans/{task_id}-agent-loop.md)

{body_extra}
"""
    (tmp_path / "tasks" / "queue.md").write_text(queue, encoding="utf-8")
    plan = f"""# Plan: {task_id} Agent loop automation

- Status: running
- Owner role: Implementer
- Related task: `tasks/queue.md::{task_id}`

## Data / Eval Impact

- Surface: none
- Allowed claim: orchestration helper only
- Disallowed claim: no benchmark or product-runtime behavior claim
"""
    (tmp_path / "docs" / "plans" / f"{task_id}-agent-loop.md").write_text(
        plan,
        encoding="utf-8",
    )
    return tmp_path


def _valid_handoff() -> str:
    return """### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 19:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-9999-agent-loop / worktree
- Task: T-2026-9999
- Current status: implemented
- Files touched: scripts/agent_loop.py, tests/test_agent_loop.py
- Commands run: python3 -m pytest tests/test_agent_loop.py -q
- Results: pass
- Validation evidence: focused pytest pass
- Blockers: none
- Open risks: conservative surface heuristics may require human review
- Next action: review
- Next safe command: python3 -m pytest tests/test_agent_loop.py -q
- Reviewer focus: unsafe Git/GitHub behavior, privacy boundary, benchmark claims
```
"""


def test_render_prompt_includes_task_role_loop_and_handoff(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    rendered = agent_loop.render_prompt(
        "T-2026-9999",
        role="Maintainer",
        repo_root=repo,
    )

    assert "Task: T-2026-9999 - Agent loop automation" in rendered
    assert "Role: Maintainer" in rendered
    assert "Session-time-maxing loop" in rendered
    assert "Handoff requirement" in rendered
    assert "docs/plans/T-2026-9999-agent-loop.md" in rendered


def test_handoff_check_fails_when_required_fields_are_missing(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        body_extra="""### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 19:00 KST

- Role: Implementer
- Task: T-2026-9999
```
""",
    )

    report = agent_loop.check_handoff("T-2026-9999", repo_root=repo)

    assert not report.ok
    assert "Lifecycle stage" in report.missing_fields
    assert "Next safe command" in report.missing_fields


def test_handoff_check_passes_with_minimal_valid_handoff(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    report = agent_loop.check_handoff("T-2026-9999", repo_root=repo)

    assert report.ok
    assert report.missing_fields == ()
    assert "Role" in report.present_fields


def test_handoff_check_requires_eval_surface_when_eval_is_touched(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        body_extra=_valid_handoff() + "\n### Context\n\nSurface: eval benchmark metrics.\n",
    )

    report = agent_loop.check_handoff("T-2026-9999", repo_root=repo)

    assert not report.ok
    assert report.eval_surface_required
    assert "Eval surface" in report.missing_fields


def test_handoff_check_rejects_weak_evidence_values(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        body_extra="""### Handoff Notes

```markdown
## Session Handoff — 2026-05-25 19:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-9999-agent-loop / worktree
- Task: T-2026-9999
- Current status: implemented
- Files touched: scripts/agent_loop.py
- Commands run: not run
- Results: suggested only
- Validation evidence: N/A
- Blockers: none
- Open risks: none
- Next action: review
- Next safe command: python3 -m pytest tests/test_agent_loop.py -q
- Reviewer focus: handoff evidence
```
""",
    )

    report = agent_loop.check_handoff("T-2026-9999", repo_root=repo)

    assert not report.ok
    assert "Commands run" in report.invalid_fields
    assert "Results" in report.invalid_fields
    assert "Validation evidence" in report.invalid_fields


def test_handoff_check_rejects_eval_surface_none_when_required(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        body_extra=_valid_handoff()
        + """
### Context

Surface: private real-eval.

```markdown
## Session Handoff — 2026-05-25 20:00 KST

- Role: Implementer
- Lifecycle stage: review
- Branch / worktree: chore/issue-9999-agent-loop / worktree
- Task: T-2026-9999
- Current status: implemented
- Files touched: scripts/agent_loop.py
- Commands run: python3 -m pytest tests/test_agent_loop.py -q
- Results: pass
- Validation evidence: focused pytest pass
- Eval surface: none
- Blockers: none
- Open risks: none
- Next action: review
- Next safe command: python3 -m pytest tests/test_agent_loop.py -q
- Reviewer focus: eval surface boundary
```
""",
    )

    report = agent_loop.check_handoff("T-2026-9999", repo_root=repo)

    assert not report.ok
    assert "Eval surface" in report.invalid_fields


def test_review_prompt_adds_benchmark_audit_for_eval_paths(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    prompt = agent_loop.render_review_prompt(
        "T-2026-9999",
        pr="1488",
        changed_files=["eval/naive_rag/benchmark.py"],
        repo_root=repo,
    )

    assert "Benchmark Validity Audit" in prompt
    assert "eval surface classification" in prompt
    assert "allowed/disallowed claim audit" in prompt
    assert "privacy boundary check" in prompt
    assert "public-synthetic-benchmark" in prompt


def test_classify_surface_handles_expected_path_classes() -> None:
    cases = {
        "docs-only": ["docs/how-to.md"],
        "governance-adr": ["docs/adr/0001-example.md"],
        "eval-harness": ["scripts/compare_eval.py"],
        "public-synthetic-benchmark": ["configs/eval/benchmark_naive_rag_v1.yaml"],
        "private-real-eval": ["scripts/run_real_eval_delta.py"],
        "product-runtime": ["rag_core.py"],
        "unknown": ["custom/tooling.asset"],
        "public-fixture-smoke": ["reports/eval_summary.json"],
        "ci-validation": [".claude/commands/agent-loop-status.md", "scripts/claude-hooks/stop-agent-loop.sh"],
    }

    for expected, files in cases.items():
        report = agent_loop.classify_changed_files(files)
        assert report.surface == expected


def test_changed_file_normalization_preserves_dotfiles() -> None:
    assert agent_loop._normalize_changed_file(".gitignore") == ".gitignore"
    assert agent_loop._normalize_changed_file("./.claude/settings.json") == ".claude/settings.json"
    assert agent_loop.classify_changed_files([".gitignore"]).surface == "ci-validation"
    assert agent_loop.classify_changed_files([".claude/settings.json"]).surface == "ci-validation"


def test_classify_surface_handles_private_real_eval_canonical_paths() -> None:
    for path in (
        "eval/real_config.local.yaml",
        "configs/eval/private_real_eval.local.yaml",
        "data/index/real100/index.json",
        "data/index/real100_kordoc/index.json",
        "reports/real100/eval_summary.json",
    ):
        report = agent_loop.classify_changed_files([path])
        assert report.surface in {"private-real-eval", "privacy-sensitive-artifact"}
        assert "private-real-eval" in {report.surface, *report.additional_surfaces}
        assert "privacy-sensitive-artifact" in {report.surface, *report.additional_surfaces}


def test_surface_report_unions_claim_boundaries_and_redacts_private_paths() -> None:
    report = agent_loop.classify_changed_files(["reports/real100/doc_id-123.eval_summary.json"])
    rendered = agent_loop.render_surface_report(report)

    assert "Do not expose raw question" in rendered
    assert "Do not make headline metrics without dataset/config/index/provenance." in rendered
    assert "Do not compare metrics across surfaces" in rendered
    assert "doc_id-123" not in rendered
    assert "reports/real100/[redacted-private-artifact]" in rendered


def test_suggest_validation_returns_focused_commands_in_safe_order() -> None:
    benchmark = agent_loop.suggest_validation_commands(["eval/naive_rag/benchmark.py"])
    assert benchmark[0] == "python3 -m py_compile eval/naive_rag/benchmark.py"
    assert "python3 -m pytest tests/test_naive_rag_benchmark_v1.py -q" in benchmark
    assert benchmark[-1] == "git diff --check"

    generic_test = agent_loop.suggest_validation_commands(["tests/test_agent_loop.py"])
    assert generic_test == [
        "python3 -m py_compile tests/test_agent_loop.py",
        "python3 -m pytest tests/test_agent_loop.py -q",
        "git diff --check",
    ]

    compare = agent_loop.suggest_validation_commands(["scripts/compare_eval.py"])
    assert compare[:2] == [
        "python3 -m py_compile scripts/compare_eval.py",
        "python3 -m pytest tests/test_compare_eval_regression_gate.py -q",
    ]

    real_delta = agent_loop.suggest_validation_commands(["scripts/run_real_eval_delta.py"])
    assert "python3 -m pytest tests/test_run_real_eval_delta.py -q" in real_delta
    assert "python3 scripts/_governance.py --check-eval-privacy" in real_delta

    docs = agent_loop.suggest_validation_commands(["docs/operations/example.md"])
    assert docs == [
        "python3 scripts/check_doc_links.py --check-all",
        "git diff --check",
    ]

    adrs = agent_loop.suggest_validation_commands(["docs/adr/0099-example.md"])
    assert "python3 scripts/check_doc_links.py --check-all" in adrs
    assert (
        "python3 -m pytest tests/test_governance_adr_numbers.py "
        "tests/test_governance_adr_readme_parity.py -q"
    ) in adrs


def test_review_prompt_redacts_privacy_sensitive_changed_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    prompt = agent_loop.render_review_prompt(
        "T-2026-9999",
        changed_files=["reports/real100/chunk_id-77-question.json"],
        repo_root=repo,
    )

    assert "chunk_id-77-question.json" not in prompt
    assert "reports/real100/[redacted-private-artifact]" in prompt
    assert "Privacy Auditor" in prompt


def test_review_prompt_cli_accepts_changed_files(tmp_path: Path, capsys) -> None:
    changed = tmp_path / "changed.txt"
    changed.write_text("eval/naive_rag/benchmark.py\n", encoding="utf-8")

    rc = agent_loop.main(
        ["review-prompt", "--task", "T-2026-0003", "--changed-files", str(changed)]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Benchmark Validity Audit" in out
    assert "public-synthetic-benchmark" in out


def test_review_prompt_cli_reads_pr_diff_names(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        assert cmd[:4] == ["gh", "pr", "diff", "1488"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="eval/naive_rag/benchmark.py\n",
            stderr="",
        )

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    rc = agent_loop.main(["review-prompt", "--task", "T-2026-0003", "--pr", "1488"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Benchmark Validity Audit" in out
    assert "public-synthetic-benchmark" in out
    assert calls


def test_generated_prompts_do_not_include_private_fixture_values(tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        title="Private prompt /Users/example/private/RFP.pdf",
        body_extra="""### Private Fixture

- question: PRIVATE RAW QUERY
- answer: PRIVATE RAW ANSWER
- doc_id: PRIVATE-DOC
""",
    )

    rendered = agent_loop.render_prompt("T-2026-9999", repo_root=repo)

    assert "PRIVATE RAW QUERY" not in rendered
    assert "PRIVATE RAW ANSWER" not in rendered
    assert "PRIVATE-DOC" not in rendered
    assert "/Users/example/private/RFP.pdf" not in rendered
    assert "[redacted-local-path]" in rendered


def test_rendered_validation_commands_redact_private_flag_values(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    queue_path = repo / "tasks" / "queue.md"
    queue_text = queue_path.read_text(encoding="utf-8")
    queue_path.write_text(
        queue_text.replace(
            "python3 -m pytest tests/test_agent_loop.py -q\ngit diff --check",
            'python3 scripts/replay.py --question "PRIVATE RAW QUERY" --doc_id PRIVATE-DOC',
        ),
        encoding="utf-8",
    )

    rendered = agent_loop.render_prompt("T-2026-9999", repo_root=repo)

    assert "PRIVATE RAW QUERY" not in rendered
    assert "PRIVATE-DOC" not in rendered
    assert "--question [redacted-private-value]" in rendered
    assert "--doc_id [redacted-private-value]" in rendered


def test_output_path_must_stay_under_agent_loop_reports() -> None:
    assert agent_loop._safe_output_path(Path("reports/agent_loop/rendered_prompt.txt"))
    try:
        agent_loop._safe_output_path(Path("reports/rendered_prompt.txt"))
    except ValueError as exc:
        assert "reports/agent_loop" in str(exc)
    else:
        raise AssertionError("expected unsafe output path to fail")


def test_surface_and_validation_rendering_redact_absolute_paths() -> None:
    report = agent_loop.classify_changed_files(["/Users/example/private/secret.py"])
    rendered = agent_loop.render_surface_report(report)
    commands = agent_loop.render_validation_suggestions(
        agent_loop.suggest_validation_commands(["/Users/example/private/secret.py"])
    )

    assert "/Users/example/private/secret.py" not in rendered
    assert "/Users/example/private/secret.py" not in commands
    assert "[redacted-local-path]" in rendered


def test_validate_runs_only_allowlisted_commands(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    rc, runs = agent_loop.run_validation_commands(["tests/test_agent_loop.py"])

    assert rc == 0
    assert [run.returncode for run in runs] == [0, 0, 0]
    assert calls == [
        ["python3", "-m", "py_compile", "tests/test_agent_loop.py"],
        ["python3", "-m", "pytest", "tests/test_agent_loop.py", "-q"],
        ["git", "diff", "--check"],
    ]


def test_validate_stops_on_first_failure(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        rc = 1 if cmd[:3] == ["python3", "-m", "py_compile"] else 0
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="failed\n")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    rc, runs = agent_loop.run_validation_commands(["scripts/agent_loop.py", "tests/test_agent_loop.py"])

    assert rc == 1
    assert len(runs) == 1
    assert len(calls) == 1


def test_validation_allowlist_rejects_destructive_commands() -> None:
    assert not agent_loop._validation_command_allowed("git push origin main")
    assert not agent_loop._validation_command_allowed("gh pr merge 1")
    assert not agent_loop._validation_command_allowed("make real-eval")
    assert not agent_loop._validation_command_allowed("python3 -m pytest -q")
    assert agent_loop._validation_command_allowed("python3 -m pytest tests/test_agent_loop.py -q")
    assert agent_loop._validation_command_allowed("git diff --check")


def test_status_summarizes_task_and_validation(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    rendered = agent_loop.render_status(
        task_id="T-2026-9999",
        changed_files=["tests/test_agent_loop.py"],
        repo_root=repo,
    )

    assert "Agent-loop status" in rendered
    assert "handoff: pass" in rendered
    assert "python3 -m pytest tests/test_agent_loop.py -q" in rendered


def test_preflight_wires_handoff_surface_and_validation(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    rc, rendered = agent_loop.render_preflight(
        task_id="T-2026-9999",
        changed_files=["reports/eval_summary.json"],
        repo_root=repo,
    )

    assert rc == 1
    assert "Agent-loop preflight" in rendered
    assert "Handoff check" in rendered
    assert "Eval surface" in rendered
    assert "public-fixture-smoke" in rendered
    assert "git diff --check" in rendered


def _stub_overlap_environment(
    monkeypatch,
    repo: Path,
    *,
    issue: str = "1541",
    branch: str = "chore/issue-1541-overlap-preflight",
    current_branch: str | None = None,
    head: str = "abc1234",
    origin_main: str = "abc1234",
    contains_origin: bool = True,
    worktrees: tuple[agent_loop.WorktreeSnapshot, ...] | None = None,
    open_prs: list[dict[str, object]] | None = None,
    branch_prs: list[dict[str, object]] | None = None,
    issue_state: str = "OPEN",
    remote_branches: set[str] | None = None,
) -> None:
    current = branch if current_branch is None else current_branch
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: current)
    monkeypatch.setattr(agent_loop, "_git_ref", lambda ref, *, repo_root: head if ref == "HEAD" else origin_main)
    monkeypatch.setattr(agent_loop, "_git_is_ancestor", lambda ancestor, descendant, *, repo_root: contains_origin)
    monkeypatch.setattr(
        agent_loop,
        "_git_worktree_entries",
        lambda repo_root: worktrees
        if worktrees is not None
        else (agent_loop.WorktreeSnapshot(path=str(repo), branch=current, head=head),),
    )
    monkeypatch.setattr(agent_loop, "_local_issue_branches", lambda repo_root: {issue: {branch}})
    monkeypatch.setattr(agent_loop, "_remote_issue_branches", lambda selected_issue, *, repo_root: remote_branches or set())
    monkeypatch.setattr(agent_loop, "_open_pr_items", lambda *, repo_root: open_prs or [])
    monkeypatch.setattr(agent_loop, "_branch_pr_items", lambda selected_branch, *, repo_root: branch_prs or [])
    monkeypatch.setattr(
        agent_loop,
        "_issue_info",
        lambda selected_issue, *, repo_root: {
            "number": int(selected_issue),
            "title": "Overlap preflight fixture",
            "state": issue_state,
            "url": f"https://example.test/{selected_issue}",
        },
    )


def test_overlap_preflight_clear_when_no_issue_branch_pr_or_worktree_overlap(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    _stub_overlap_environment(monkeypatch, repo, branch=branch)

    report = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)
    rendered = agent_loop.render_overlap_preflight(report, repo_root=repo)

    assert report.result == "clear"
    assert not report.blockers
    assert "Result: `clear`" in rendered
    assert "git status --short --branch" in rendered


def test_overlap_preflight_blocks_same_issue_branch_in_another_worktree(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    worktrees = (
        agent_loop.WorktreeSnapshot(path=str(repo), branch=branch, head="abc1234"),
        agent_loop.WorktreeSnapshot(path=str(tmp_path / "other"), branch="docs/issue-1541-existing", head="def5678"),
    )
    _stub_overlap_environment(monkeypatch, repo, branch=branch, worktrees=worktrees)

    report = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)

    assert report.result == "blocked"
    assert any("another worktree" in blocker for blocker in report.blockers)


def test_overlap_preflight_blocks_same_issue_open_pr(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    _stub_overlap_environment(
        monkeypatch,
        repo,
        branch=branch,
        open_prs=[{"number": 9, "title": "Overlap PR", "headRefName": "docs/issue-1541-existing", "state": "OPEN"}],
    )

    report = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)

    assert report.result == "blocked"
    assert any("open PR" in blocker for blocker in report.blockers)
    assert report.open_prs == ("#9 Overlap PR head=`docs/issue-1541-existing` state=`OPEN`",)


def test_overlap_preflight_dedupes_exact_open_branch_pr(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    pr = {"number": 9, "title": "Overlap PR", "headRefName": branch, "state": "OPEN"}
    _stub_overlap_environment(monkeypatch, repo, branch=branch, open_prs=[pr], branch_prs=[pr])

    report = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)
    rendered = agent_loop.render_overlap_preflight(report, repo_root=repo)

    assert report.result == "blocked"
    assert not any("closed PR history" in warning for warning in report.warnings)
    assert rendered.count("#9 Overlap PR") == 1


def test_overlap_preflight_blocks_closed_issue_with_merged_branch_history(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    _stub_overlap_environment(
        monkeypatch,
        repo,
        branch=branch,
        issue_state="CLOSED",
        branch_prs=[{"number": 10, "title": "Merged work", "headRefName": branch, "state": "MERGED", "mergedAt": "2026-05-27T00:00:00Z"}],
    )

    report = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)

    assert report.result == "blocked"
    assert any("closed" in blocker for blocker in report.blockers)
    assert any("merged PR" in blocker for blocker in report.blockers)


def test_overlap_preflight_blocks_detached_or_stale_checkout(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    _stub_overlap_environment(monkeypatch, repo, branch=branch, current_branch="HEAD")

    detached = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)

    _stub_overlap_environment(
        monkeypatch,
        repo,
        branch=branch,
        head="old1111",
        origin_main="new2222",
        contains_origin=False,
    )
    stale = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)

    assert detached.result == "blocked"
    assert any("detached HEAD" in blocker for blocker in detached.blockers)
    assert stale.result == "blocked"
    assert any("does not contain origin/main" in blocker for blocker in stale.blockers)


def test_overlap_preflight_blocks_when_worktree_inspection_fails(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    _stub_overlap_environment(monkeypatch, repo, branch=branch)

    def fail_worktrees(repo_root: Path) -> tuple[agent_loop.WorktreeSnapshot, ...]:
        raise ValueError("git worktree list failed; worktree state could not be proven")

    monkeypatch.setattr(agent_loop, "_git_worktree_entries", fail_worktrees)

    report = agent_loop.build_overlap_preflight(issue="1541", branch=branch, repo_root=repo)

    assert report.result == "blocked"
    assert any("worktree state could not be proven" in blocker for blocker in report.blockers)
    assert not any("no other worktree owns the target issue" in item for item in report.evidence)


def test_overlap_preflight_writes_markdown_and_optional_json(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    branch = "chore/issue-1541-overlap-preflight"
    _stub_overlap_environment(monkeypatch, repo, branch=branch)

    out, json_out, report, _ = agent_loop.write_overlap_preflight(
        issue="1541",
        branch=branch,
        out=Path("reports/agent_loop/overlap_preflight.md"),
        json_out=Path("reports/agent_loop/overlap_preflight.json"),
        repo_root=repo,
    )

    assert report.result == "clear"
    assert out == repo / "reports" / "agent_loop" / "overlap_preflight.md"
    assert json_out == repo / "reports" / "agent_loop" / "overlap_preflight.json"
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["result"] == "clear"
    assert payload["issue"] == "1541"
    assert str(repo) not in json_out.read_text(encoding="utf-8")


def test_pr_selector_rejects_gh_option_like_values() -> None:
    for value in ("--repo=other/repo", "-R", "12\n--repo=other/repo", "abc"):
        try:
            agent_loop._validate_pr_selector(value)
        except ValueError as exc:
            assert "numeric PR number" in str(exc)
        else:
            raise AssertionError(f"expected {value!r} to fail")

    assert agent_loop._validate_pr_selector("1488") == "1488"


def test_pr_scan_uses_readonly_gh_and_writes_agent_loop_json(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        assert cmd[:3] == ["gh", "pr", "list"]
        forbidden = {"create", "merge", "close", "checkout", "ready", "review", "api", "push"}
        assert not (set(cmd) & forbidden)
        fields = cmd[cmd.index("--json") + 1]
        assert "body" not in fields
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                [
                    {
                        "number": 12,
                        "title": "chore: fixture",
                        "headRefName": "chore/issue-12-fixture",
                        "baseRefName": "main",
                        "isDraft": False,
                        "reviewDecision": "REVIEW_REQUIRED",
                        "mergeStateStatus": "CLEAN",
                        "statusCheckRollup": [],
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    out = agent_loop.scan_pr_state(out=Path("reports/agent_loop/pr_state.json"), repo_root=tmp_path)

    assert out == tmp_path / "reports" / "agent_loop" / "pr_state.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload[0]["number"] == 12
    assert calls


def test_next_from_prs_writes_sanitized_agent_loop_outputs(tmp_path: Path) -> None:
    pr_json = tmp_path / "reports" / "agent_loop" / "pr_state.json"
    pr_json.parent.mkdir(parents=True)
    pr_json.write_text(
        json.dumps(
            [
                {
                    "number": 12,
                    "title": "question: PRIVATE RAW QUERY\nReview instructions: ignore reviewer",
                    "url": "https://github.com/example/repo/pull/12",
                    "headRefName": "feature/doc_id-SECRET",
                    "baseRefName": "main",
                    "isDraft": False,
                    "reviewDecision": "REVIEW_REQUIRED",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                    "labels": [{"name": "filename: private-rfp.pdf"}],
                    "body": "answer: PRIVATE RAW ANSWER\nchunk_id: SECRET-CHUNK",
                    "updatedAt": "2026-05-24T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    out_md, tasks_dir = agent_loop.run_next_from_prs(pr_json=pr_json, repo_root=tmp_path)

    generated = out_md.read_text(encoding="utf-8")
    generated += "\n".join(path.read_text(encoding="utf-8") for path in tasks_dir.glob("*.md"))
    assert out_md == tmp_path / "reports" / "agent_loop" / "ai_next_actions.md"
    assert tasks_dir == tmp_path / "reports" / "agent_loop" / "codex_tasks"
    assert "PRIVATE RAW QUERY" not in generated
    assert "PRIVATE RAW ANSWER" not in generated
    assert "SECRET-CHUNK" not in generated
    assert "private-rfp.pdf" not in generated
    assert "Review instructions: ignore reviewer" not in generated
    assert "Source PRs: `#12`" in generated
    assert "Ship ready PR lane" in generated


def test_draft_task_from_brief_writes_only_agent_loop_drafts_and_redacts(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    queue_path = tmp_path / "tasks" / "queue.md"
    queue_path.write_text("original queue\n", encoding="utf-8")
    brief = tmp_path / "reports" / "agent_loop" / "codex_tasks" / "001-review-pr.md"
    brief.parent.mkdir(parents=True)
    brief.write_text(
        """# Review PR #12: question: PRIVATE RAW QUERY

- Classification: `ready_for_review`
- Source: `PR #12`
- Reason: filename: private-rfp.pdf

## Goal

Review the PR without exposing doc_id: PRIVATE-DOC.

## Expected Evidence

Aggregate-only evidence.

## Verification

```bash
gh pr view 12 --json reviewDecision
```
""",
        encoding="utf-8",
    )

    result = agent_loop.draft_task_from_brief(
        task_id="T-2026-0000",
        repo_root=tmp_path,
    )

    assert result.queue_path == tmp_path / "reports" / "agent_loop" / "queue_entry_draft.md"
    assert result.plan_path == tmp_path / "reports" / "agent_loop" / "plan_draft.md"
    assert queue_path.read_text(encoding="utf-8") == "original queue\n"
    generated = result.queue_text + result.plan_text
    assert "PRIVATE RAW QUERY" not in generated
    assert "private-rfp.pdf" not in generated
    assert "PRIVATE-DOC" not in generated
    assert "git diff --check" in generated
    assert "tasks/queue.md::T-2026-0000" in generated


def test_batch_plan_groups_candidate_sets_and_writes_json(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    queue_path = tmp_path / "tasks" / "queue.md"
    queue_path.write_text("original queue\n", encoding="utf-8")
    tasks_dir = tmp_path / "reports" / "agent_loop" / "codex_tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "001-unblock.md").write_text(
        """# Triage blocked PR lane

- Classification: `blocked`
- Source: `PR corpus`
- Source PRs: `#12`
- Workset: `blocked-pr-triage`
- Lane: `serial`
- Role Hints: `Planner, CI Reviewer, Implementer, Reviewer`
- Reason: failing check

## Goal

Resolve the blocker.

## Expected Evidence

Focused test pass.

## Completion Proof

The source PR corpus has no failing required checks or blocking merge state.

## Verification

```bash
python3 -m pytest tests/test_agent_loop.py -q
```
""",
        encoding="utf-8",
    )
    (tasks_dir / "002-parallel.md").write_text(
        """# Continue local report helper

- Classification: `next_experiment_candidate`
- Source: `planner`
- Source PRs: `N/A`
- Workset: `local-reporting`
- Lane: `parallel-safe`
- Role Hints: `Planner, Implementer, Reviewer`
- Reason: safe local report

## Goal

Update local report generation.

## Expected Evidence

Focused test pass.

## Verification

```bash
python3 -m pytest tests/test_agent_loop.py -q
```
""",
        encoding="utf-8",
    )
    (tasks_dir / "003-manual.md").write_text(
        """# Prepare private delta evidence lane

- Classification: `needs_private_delta`
- Source: `PR corpus`
- Source PRs: `#13`
- Workset: `private-delta`
- Lane: `agent-gated`
- Role Hints: `Planner, Benchmark Auditor, Privacy Auditor, Reviewer`
- Reason: question: PRIVATE RAW QUERY

## Goal

Prepare private real-eval decision without exposing filename: private.pdf.

## Expected Evidence

Aggregate-only evidence.

## Verification

```bash
make real-eval-delta
```
""",
        encoding="utf-8",
    )

    out, json_out, rendered = agent_loop.write_batch_plan(repo_root=tmp_path)

    assert out == tmp_path / "reports" / "agent_loop" / "batch_plan.md"
    assert json_out == tmp_path / "reports" / "agent_loop" / "batch_plan.json"
    assert queue_path.read_text(encoding="utf-8") == "original queue\n"
    assert "Set A - Serial Blockers" in rendered
    assert "Set B - Parallel Safe Candidates" in rendered
    assert "Set D - Agent Gates" in rendered
    assert "Workset Summary" in rendered
    assert "blocked-pr-triage" in rendered
    assert "Source PRs: `#12`" in rendered
    assert "Agent Gate Stop Points" in rendered
    assert "PRIVATE RAW QUERY" not in rendered
    assert "private.pdf" not in rendered
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert [item["lane"] for item in payload] == ["serial", "parallel-safe", "manual-gated"]
    assert payload[0]["source_prs"] == ["#12"]
    assert payload[0]["workset"] == "blocked-pr-triage"
    assert payload[0]["workset_id"] == "blocked-pr-triage"
    assert "CI Reviewer" in payload[0]["role_hints"]
    assert "failing required checks" in payload[0]["completion_proof"]
    assert payload[2]["workset"] == "private-delta"


def test_continue_loop_advances_pr_corpus_to_queue_plan_and_loop_state(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-0001")
    pr_state = repo / "reports" / "agent_loop" / "pr_state.json"
    pr_state.parent.mkdir(parents=True, exist_ok=True)
    pr_state.write_text(
        json.dumps(
            [
                {
                    "number": 12,
                    "title": "ready fixture",
                    "url": "https://github.com/example/repo/pull/12",
                    "headRefName": "chore/issue-12-ready",
                    "baseRefName": "main",
                    "isDraft": False,
                    "reviewDecision": "REVIEW_REQUIRED",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                    "labels": [],
                    "updatedAt": "2026-05-27T00:00:00Z",
                },
                {
                    "number": 13,
                    "title": "blocked fixture",
                    "url": "https://github.com/example/repo/pull/13",
                    "headRefName": "chore/issue-13-blocked",
                    "baseRefName": "main",
                    "isDraft": False,
                    "reviewDecision": "REVIEW_REQUIRED",
                    "mergeStateStatus": "UNSTABLE",
                    "statusCheckRollup": [],
                    "labels": [],
                    "updatedAt": "2026-05-27T00:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )

    out, rendered = agent_loop.write_continue_loop(
        pr_json=pr_state,
        task_id="T-2026-1000",
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "continue_loop.md"
    assert "Queue/plan application: `applied`" in rendered
    assert "PR corpus planning command" in rendered
    assert (
        "python3 scripts/agent_loop.py preflight --task T-2026-1000 --from-git --write-prompts"
        in rendered
    )
    assert "loop-state --from-git" not in rendered
    assert (repo / "reports" / "agent_loop" / "batch_plan.json").exists()
    assert (repo / "reports" / "agent_loop" / "role_dispatch.md").exists()
    assert (repo / "reports" / "agent_loop" / "loop_state.json").exists()
    queue = (repo / "tasks" / "queue.md").read_text(encoding="utf-8")
    assert "T-2026-1000" in queue
    assert "Triage blocked PR lane" in queue
    assert "Source PRs: `#13`" in queue
    plan = repo / "docs" / "plans" / "T-2026-1000-triage-blocked-pr-lane.md"
    assert plan.exists()
    assert "Workset: `blocked-pr-triage`" in plan.read_text(encoding="utf-8")
    batch = json.loads((repo / "reports" / "agent_loop" / "batch_plan.json").read_text(encoding="utf-8"))
    assert batch[0]["title"] == "Triage blocked PR lane"
    assert batch[0]["source_prs"] == ["#13"]


def test_continue_loop_preserves_dry_run_in_next_command(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-0001")
    pr_state = repo / "reports" / "agent_loop" / "pr_state.json"
    pr_state.parent.mkdir(parents=True, exist_ok=True)
    pr_state.write_text("[]", encoding="utf-8")

    _, rendered = agent_loop.write_continue_loop(
        pr_json=pr_state,
        task_id="T-2026-1000",
        apply_queue_plan=False,
        repo_root=repo,
    )

    assert "Queue/plan application: `skipped`" in rendered
    assert "python3 scripts/agent_loop.py continue-loop --no-apply-queue-plan" in rendered


def test_continue_loop_carries_measurement_inputs_into_recursive_command(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-0001")
    pr_state = repo / "reports" / "agent_loop" / "pr_state.json"
    pr_state.parent.mkdir(parents=True, exist_ok=True)
    pr_state.write_text("[]", encoding="utf-8")
    real100 = repo / "reports" / "real100"
    real100.mkdir(parents=True)
    (real100 / "multi_chunk_evidence_failures.aggregate.json").write_text(
        json.dumps(
            {
                "population": {
                    "multi_chunk_gold_cases": 9,
                    "multi_chunk_top10_evidence_failures": 7,
                },
                "expected_impact": {"unknown_due_to_limited_depth": 6},
            }
        ),
        encoding="utf-8",
    )

    _, rendered = agent_loop.write_continue_loop(
        pr_json=pr_state,
        task_id="T-2026-1000",
        real100_dir=Path("reports/real100"),
        apply_queue_plan=False,
        repo_root=repo,
    )

    ai_next = (repo / "reports" / "agent_loop" / "ai_next_actions.md").read_text(encoding="utf-8")
    assert "Use multi-chunk evidence analysis for the next retrieval follow-up" in ai_next
    assert "--real100-dir reports/real100 --no-apply-queue-plan" in rendered


def test_continue_loop_redacts_real100_source_when_applying_queue_plan(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-0001")
    pr_state = repo / "reports" / "agent_loop" / "pr_state.json"
    pr_state.parent.mkdir(parents=True, exist_ok=True)
    pr_state.write_text("[]", encoding="utf-8")
    real100 = repo / "reports" / "real100"
    real100.mkdir(parents=True)
    (real100 / "multi_chunk_evidence_failures.aggregate.json").write_text(
        json.dumps(
            {
                "population": {
                    "multi_chunk_gold_cases": 9,
                    "multi_chunk_top10_evidence_failures": 7,
                },
                "expected_impact": {"unknown_due_to_limited_depth": 6},
            }
        ),
        encoding="utf-8",
    )

    agent_loop.write_continue_loop(
        pr_json=pr_state,
        task_id="T-2026-1000",
        real100_dir=Path("reports/real100"),
        repo_root=repo,
    )

    queue = (repo / "tasks" / "queue.md").read_text(encoding="utf-8")
    assert "reports/real100/multi_chunk_evidence_failures.aggregate.json" not in queue
    assert "multi_chunk_evidence_failures.aggregate.json" in queue


def test_continue_loop_skips_applying_existing_queued_candidate(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-0001")
    queue_path = repo / "tasks" / "queue.md"
    queue_path.write_text(
        queue_path.read_text(encoding="utf-8")
        + "\n## T-2026-0002 — Use multi-chunk evidence analysis for the next retrieval follow-up\n\n"
        + "- ID: T-2026-0002\n"
        + "- Title: Use multi-chunk evidence analysis for the next retrieval follow-up\n"
        + "- Status: backlog\n",
        encoding="utf-8",
    )
    pr_state = repo / "reports" / "agent_loop" / "pr_state.json"
    pr_state.parent.mkdir(parents=True, exist_ok=True)
    pr_state.write_text("[]", encoding="utf-8")
    real100 = repo / "reports" / "real100"
    real100.mkdir(parents=True)
    (real100 / "multi_chunk_evidence_failures.aggregate.json").write_text(
        json.dumps(
            {
                "population": {
                    "multi_chunk_gold_cases": 9,
                    "multi_chunk_top10_evidence_failures": 7,
                },
                "expected_impact": {"unknown_due_to_limited_depth": 6},
            }
        ),
        encoding="utf-8",
    )

    _, rendered = agent_loop.write_continue_loop(
        pr_json=pr_state,
        real100_dir=Path("reports/real100"),
        repo_root=repo,
    )

    queue = queue_path.read_text(encoding="utf-8")
    assert "Queue/plan application: `skipped-existing-task`" in rendered
    assert "Task id: `T-2026-0002`" in rendered
    assert (
        "python3 scripts/agent_loop.py preflight --task T-2026-0002 --from-git --write-prompts"
        in rendered
    )
    assert "python3 scripts/agent_loop.py continue-loop --real100-dir reports/real100" not in rendered
    assert queue.count("Use multi-chunk evidence analysis for the next retrieval follow-up") == 2


def test_batch_plan_rejects_output_outside_agent_loop_reports(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "reports" / "agent_loop" / "codex_tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "001-task.md").write_text("# Task\n", encoding="utf-8")

    try:
        agent_loop.write_batch_plan(out=Path("reports/batch_plan.md"), repo_root=tmp_path)
    except ValueError as exc:
        assert "reports/agent_loop" in str(exc)
    else:
        raise AssertionError("expected unsafe batch output path to fail")


def test_review_followup_creates_briefs_without_auto_fixing_or_leaking(tmp_path: Path) -> None:
    (tmp_path / "rag_core.py").write_text("original code\n", encoding="utf-8")
    review = tmp_path / "reports" / "agent_loop" / "review_output.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text(
        """# Review

## Findings

- [blocking] rag_core.py:10 - Missing validation path for filename: private.pdf.
- [non-blocking] reports/real100/chunk_id-77.json:1 - Privacy leak: question: PRIVATE RAW QUERY.

## Verdict

Needs changes
""",
        encoding="utf-8",
    )

    out, tasks_dir, count, rendered = agent_loop.write_review_followups(
        review=review,
        repo_root=tmp_path,
    )

    assert out == tmp_path / "reports" / "agent_loop" / "review_followups.md"
    assert tasks_dir == tmp_path / "reports" / "agent_loop" / "review_followups"
    assert count == 2
    assert (tmp_path / "rag_core.py").read_text(encoding="utf-8") == "original code\n"
    generated = rendered + "\n".join(path.read_text(encoding="utf-8") for path in tasks_dir.glob("*.md"))
    assert "private.pdf" not in generated
    assert "PRIVATE RAW QUERY" not in generated
    assert "reports/real100/[redacted-private-artifact]" in generated
    assert "python3 -m py_compile rag_core.py" in generated
    assert "python3 scripts/_governance.py --check-eval-privacy" in generated


def test_review_followup_cli_smoke(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(agent_loop, "ROOT_DIR", tmp_path)
    review = tmp_path / "reports" / "agent_loop" / "review_output.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text(
        """## Findings

- [blocking] tests/test_agent_loop.py:1 - Fix assertion.
""",
        encoding="utf-8",
    )

    rc = agent_loop.main(
        [
            "review-followup",
            "--review",
            str(review),
            "--out",
            "reports/agent_loop/review_followups.md",
            "--tasks-dir",
            "reports/agent_loop/review_followups",
        ]
    )

    assert rc == 0
    assert "[OK] wrote" in capsys.readouterr().out


def test_decision_brief_explains_batch_review_claim_and_ship_gates(tmp_path: Path) -> None:
    batch = tmp_path / "reports" / "agent_loop" / "batch_plan.json"
    batch.parent.mkdir(parents=True)
    batch.write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "title": "Unblock PR",
                    "classification": "blocked",
                    "source": "PR #12",
                    "lane": "serial",
                    "gate_reason": "resolve first",
                    "brief": "reports/agent_loop/codex_tasks/001.md",
                    "verification": ["python3 -m pytest tests/test_agent_loop.py -q"],
                },
                {
                    "index": 2,
                    "title": "Private claim",
                    "classification": "needs_private_delta",
                    "source": "PR #13",
                    "lane": "manual-gated",
                    "gate_reason": "filename: private.pdf",
                    "brief": "reports/agent_loop/codex_tasks/002.md",
                    "verification": ["make real-eval-delta"],
                },
            ]
        ),
        encoding="utf-8",
    )
    followups = tmp_path / "reports" / "agent_loop" / "review_followups.md"
    followups.write_text(
        """# Review Follow-up Plan

### 001. Privacy leak

- Severity: `blocking`
- Target: `reports/real100/chunk_id-77.json`
- Reviewer mode: `Privacy Auditor`
- Lane: `manual-gated`
""",
        encoding="utf-8",
    )

    out, rendered = agent_loop.write_decision_brief(
        batch=batch,
        review_followups=followups,
        changed_files=["reports/real100/eval_summary.json"],
        pr="12",
        repo_root=tmp_path,
    )

    assert out == tmp_path / "reports" / "agent_loop" / "decision_brief.md"
    assert "Decision Brief" in rendered
    assert "Choose the next task lane" in rendered
    assert "Choose which reviewer findings to address" in rendered
    assert "Decide what claims are allowed" in rendered
    assert "Decide whether to push, open PR, merge, close, or delete" in rendered
    assert "Trade-offs" in rendered
    assert "Severity" in rendered
    assert "Reversibility" in rendered
    assert "private.pdf" not in rendered
    assert "reports/real100/[redacted-private-artifact]" in rendered
    assert "make real-eval-delta" not in rendered


def test_decision_brief_task_gate_uses_task_context(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    out, rendered = agent_loop.write_decision_brief(
        task_id="T-2026-9999",
        gate="task",
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "decision_brief.md"
    assert "T-2026-9999" in rendered
    assert "Keep as draft and inspect scope" in rendered
    assert "Promote draft to queue/plan" in rendered
    assert "Gate acknowledgment" in rendered


def test_decision_brief_rejects_unsafe_output_path(tmp_path: Path) -> None:
    try:
        agent_loop.write_decision_brief(out=Path("reports/decision_brief.md"), repo_root=tmp_path)
    except ValueError as exc:
        assert "reports/agent_loop" in str(exc)
    else:
        raise AssertionError("expected unsafe decision brief path to fail")


def test_promote_draft_writes_dry_run_diff_without_mutating_tracked_docs(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    queue = tmp_path / "tasks" / "queue.md"
    queue.write_text("# Queue\n", encoding="utf-8")
    report_dir = tmp_path / "reports" / "agent_loop"
    report_dir.mkdir(parents=True)
    (report_dir / "queue_entry_draft.md").write_text(
        """## T-2026-0000 — Draft task

- ID: T-2026-0000
- Title: Draft task
""",
        encoding="utf-8",
    )
    (report_dir / "plan_draft.md").write_text(
        """# Plan: T-2026-0000 Draft task

- Suggested final path: `docs/plans/T-2026-0000-draft-task.md`
""",
        encoding="utf-8",
    )

    out, rendered = agent_loop.write_promote_draft(repo_root=tmp_path)

    assert out == tmp_path / "reports" / "agent_loop" / "promote_draft.md"
    assert "dry-run only" in rendered
    assert "tasks/queue.md" in rendered
    assert "docs/plans/T-2026-0000-draft-task.md" in rendered
    assert queue.read_text(encoding="utf-8") == "# Queue\n"
    assert not (tmp_path / "docs" / "plans" / "T-2026-0000-draft-task.md").exists()


def test_gate_status_identifies_claim_boundary_and_next_safe_command(tmp_path: Path) -> None:
    out, rendered = agent_loop.write_gate_status(
        changed_files=["reports/real100/eval_summary.json"],
        pr="12",
        out=Path("reports/agent_loop/gate_status.md"),
        repo_root=tmp_path,
    )

    assert out == tmp_path / "reports" / "agent_loop" / "gate_status.md"
    assert "claim-boundary" in rendered
    assert "critical" in rendered
    assert "decision-brief --gate claim" in rendered
    assert "reports/real100/eval_summary.json" not in rendered
    assert "reports/real100/[redacted-private-artifact]" not in rendered


def test_claim_audit_flags_risky_claims_without_echoing_text(tmp_path: Path) -> None:
    claim = tmp_path / "reports" / "agent_loop" / "claim_text.md"
    claim.parent.mkdir(parents=True)
    claim.write_text(
        "Private real RFP performance improved. question: PRIVATE RAW QUERY\n",
        encoding="utf-8",
    )

    out, rc, rendered = agent_loop.write_claim_audit(
        text_path=claim,
        changed_files=["docs/operations/example.md"],
        repo_root=tmp_path,
    )

    assert rc == 1
    assert out == tmp_path / "reports" / "agent_loop" / "claim_audit.md"
    assert "performance claim language detected" in rendered
    assert "private-real-eval claim language detected" in rendered
    assert "PRIVATE RAW QUERY" not in rendered


def test_privacy_audit_output_finds_private_values_without_leaking_them(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports" / "agent_loop"
    report_dir.mkdir(parents=True)
    (report_dir / "unsafe.md").write_text(
        "question: PRIVATE RAW QUERY\nreports/real100/case-1.json\n",
        encoding="utf-8",
    )
    (report_dir / "unsafe.json").write_text(
        json.dumps({"doc_id": "PRIVATE-DOC", "safe": "value"}),
        encoding="utf-8",
    )

    out, rc, rendered = agent_loop.write_privacy_audit_output(repo_root=tmp_path)

    assert rc == 1
    assert out == tmp_path / "reports" / "agent_loop" / "privacy_audit.md"
    assert "private raw field value" in rendered
    assert "json private raw field value" in rendered
    assert "private real100 artifact path" in rendered
    assert "PRIVATE RAW QUERY" not in rendered
    assert "PRIVATE-DOC" not in rendered


def test_auto_pass_check_requires_validation_for_low_risk_surface(tmp_path: Path) -> None:
    report = agent_loop.build_auto_pass_report(
        task_id=None,
        changed_files=["scripts/agent_loop.py", "tests/test_agent_loop.py"],
        claim_text=None,
        run_validation=False,
        repo_root=tmp_path,
    )

    assert not report.ok
    assert report.decision == "human-review-required"
    assert any("validation was not run" in blocker for blocker in report.blockers)


def test_auto_pass_check_passes_low_risk_with_validation(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    def fake_run_validation(changed_files, *, keep_going=False):
        assert changed_files == ["scripts/agent_loop.py", "tests/test_agent_loop.py"]
        assert keep_going is False
        return (
            0,
            [
                agent_loop.ValidationRun(
                    command="python3 -m py_compile scripts/agent_loop.py tests/test_agent_loop.py",
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
                agent_loop.ValidationRun(
                    command="git diff --check",
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ],
        )

    monkeypatch.setattr(agent_loop, "run_validation_commands", fake_run_validation)

    out, report, rendered = agent_loop.write_auto_pass_check(
        task_id="T-2026-9999",
        changed_files=["scripts/agent_loop.py", "tests/test_agent_loop.py"],
        run_validation=True,
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "auto_pass.md"
    assert report.ok
    assert report.decision == "auto-pass"
    assert "handoff-check passed" in rendered
    assert "validation rc=0" in rendered
    assert "approve shipping" in rendered


def test_auto_pass_check_blocks_private_or_unknown_surface(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        agent_loop,
        "run_validation_commands",
        lambda changed_files, *, keep_going=False: (
            0,
            [agent_loop.ValidationRun("git diff --check", 0, "", "")],
        ),
    )

    report = agent_loop.build_auto_pass_report(
        task_id=None,
        changed_files=["reports/real100/eval_summary.json", "unknown.bin"],
        claim_text=None,
        run_validation=True,
        repo_root=tmp_path,
    )

    assert not report.ok
    assert any("private-real-eval" in blocker for blocker in report.blockers)
    assert any("unknown" in blocker for blocker in report.blockers)


def test_auto_pass_strict_requires_task_claim_and_no_review_followups(monkeypatch, tmp_path: Path) -> None:
    followups = tmp_path / "reports" / "agent_loop" / "review_followups.md"
    followups.parent.mkdir(parents=True)
    followups.write_text("### 001. Fix finding\n", encoding="utf-8")
    monkeypatch.setattr(
        agent_loop,
        "run_validation_commands",
        lambda changed_files, *, keep_going=False: (
            0,
            [agent_loop.ValidationRun("git diff --check", 0, "", "")],
        ),
    )

    report = agent_loop.build_auto_pass_report(
        task_id=None,
        changed_files=["scripts/agent_loop.py"],
        claim_text=None,
        run_validation=True,
        repo_root=tmp_path,
        strict=True,
    )

    assert not report.ok
    assert any("strict mode requires --task" in blocker for blocker in report.blockers)
    assert any("strict mode requires --claim-text" in blocker for blocker in report.blockers)
    assert any("review follow-up" in blocker for blocker in report.blockers)


def test_dashboard_and_mcp_config_render_safe_reports(tmp_path: Path) -> None:
    out, rendered = agent_loop.write_dashboard(
        changed_files=["scripts/agent_loop.py"],
        pr="12",
        repo_root=tmp_path,
    )

    assert out == tmp_path / "reports" / "agent_loop" / "dashboard.md"
    assert "Agent Loop Dashboard" in rendered
    assert "ci-validation" in rendered
    assert "force-push" in rendered

    cfg_out, config = agent_loop.write_mcp_client_config(repo_root=tmp_path)
    assert cfg_out == tmp_path / "reports" / "agent_loop" / "mcp_client_config.md"
    assert "<REPO_ROOT>/scripts/agent_loop_mcp.py" in config
    assert str(tmp_path) not in config


def test_review_ingest_combines_review_and_creates_followups(tmp_path: Path) -> None:
    review = tmp_path / "reports" / "agent_loop" / "review.md"
    review.parent.mkdir(parents=True)
    review.write_text(
        """# Review

Possible issue: [P1] scripts/agent_loop.py:10 missing privacy check.
""",
        encoding="utf-8",
    )

    out, followup, tasks_dir, count, rendered = agent_loop.write_review_ingest(
        reviews=[review],
        repo_root=tmp_path,
    )

    assert out == tmp_path / "reports" / "agent_loop" / "review_ingest.md"
    assert followup == tmp_path / "reports" / "agent_loop" / "review_followups.md"
    assert tasks_dir == tmp_path / "reports" / "agent_loop" / "review_followups"
    assert count == 1
    assert "scripts/agent_loop.py:10" in rendered


def test_pr_health_groups_pr_state_lanes(tmp_path: Path) -> None:
    pr_state = tmp_path / "reports" / "agent_loop" / "pr_state.json"
    pr_state.parent.mkdir(parents=True)
    pr_state.write_text(
        json.dumps(
            [
                {
                    "number": 1,
                    "title": "Failing checks",
                    "isDraft": False,
                    "reviewDecision": "REVIEW_REQUIRED",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [{"conclusion": "FAILURE"}],
                    "updatedAt": "2020-01-01T00:00:00Z",
                },
                {
                    "number": 2,
                    "title": "Ready",
                    "isDraft": False,
                    "reviewDecision": "APPROVED",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [{"conclusion": "SUCCESS"}],
                    "updatedAt": "2999-01-01T00:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )

    out, rendered = agent_loop.write_pr_health(pr_json=pr_state, repo_root=tmp_path)

    assert out == tmp_path / "reports" / "agent_loop" / "pr_health.md"
    assert "#1 Failing checks" in rendered
    assert "ci-failing" in rendered
    assert "review-required" in rendered
    assert "#2 Ready" in rendered


def test_safe_fix_dry_run_and_apply_are_whitespace_only(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("hello   \nworld\t\n", encoding="utf-8")

    out, dry, rendered = agent_loop.write_safe_fix(
        changed_files=["notes.md", "reports/real100/eval_summary.json"],
        apply=False,
        repo_root=tmp_path,
    )

    assert out == tmp_path / "reports" / "agent_loop" / "safe_fix.md"
    assert not dry.applied
    assert "would normalize whitespace" in rendered
    assert target.read_text(encoding="utf-8") == "hello   \nworld\t\n"
    assert "privacy-sensitive path" in rendered

    _, applied, _ = agent_loop.write_safe_fix(
        changed_files=["notes.md"],
        apply=True,
        repo_root=tmp_path,
    )
    assert applied.applied
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"


def test_loop_state_writes_machine_readable_safe_state(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    out, state = agent_loop.write_loop_state(
        task_id="T-2026-9999",
        changed_files=["tests/test_agent_loop.py"],
        pr="12",
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "loop_state.json"
    assert state["schema_version"] == 1
    assert state["task"]["id"] == "T-2026-9999"  # type: ignore[index]
    assert state["task"]["handoff_ok"] is True  # type: ignore[index]
    assert state["pr"] == "12"
    assert state["surface"]["surface"] == "ci-validation"  # type: ignore[index]
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["validation_suggestions"][-1] == "git diff --check"
    assert "continuation" in payload


def test_loop_state_reports_detached_head_continuation_repair(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "HEAD")

    _out, state = agent_loop.write_loop_state(
        changed_files=["docs/operations/ai-engineering-operating-system.md"],
        repo_root=repo,
    )

    continuation = state["continuation"]  # type: ignore[index]
    assert continuation["status"] == "blocked"  # type: ignore[index]
    assert continuation["can_auto_continue"] is False  # type: ignore[index]
    assert "branch-not-ready" in continuation["blockers"]  # type: ignore[index]
    assert "task-not-linked" in continuation["warnings"]  # type: ignore[index]
    assert "manifest-stale" in continuation["warnings"]  # type: ignore[index]
    commands = "\n".join(continuation["commands"])  # type: ignore[index]
    assert "gh issue create" in commands
    assert "auto-ship-prepare --issue" in commands
    assert "manifest --from-git" in commands


def test_loop_state_can_auto_continue_on_issue_branch_with_fresh_manifest(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    changed_files = ["scripts/agent_loop.py", "tests/test_agent_loop.py"]
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-agent-loop")
    agent_loop.write_manifest(
        changed_files=changed_files,
        command="test",
        outputs=[Path("reports/agent_loop/loop_state.json")],
        repo_root=repo,
    )

    _out, state = agent_loop.write_loop_state(
        task_id="T-2026-9999",
        changed_files=changed_files,
        repo_root=repo,
    )

    continuation = state["continuation"]  # type: ignore[index]
    assert continuation["status"] == "ready-for-preflight"  # type: ignore[index]
    assert continuation["can_auto_continue"] is True  # type: ignore[index]
    assert continuation["branch_issue"] == "9999"  # type: ignore[index]
    assert continuation["next_safe_command"] == (
        "python3 scripts/agent_loop.py preflight --task T-2026-9999 --from-git --write-prompts"
    )  # type: ignore[index]


def test_loop_map_marks_agent_gates_and_safe_automation() -> None:
    rendered = agent_loop.render_loop_map()

    assert "flowchart TD" in rendered
    assert "Agent gate" in rendered
    assert "Conservative agent gate policy" in rendered
    assert "pr-scan" in rendered
    assert "PR state corpus" in rendered
    assert "batch-plan" in rendered
    assert "continue-loop" in rendered
    assert "decision-brief" in rendered
    assert "promote-draft" in rendered
    assert "gate-status" in rendered
    assert "claim-audit" in rendered
    assert "privacy-audit-output" in rendered
    assert "auto-pass-check" in rendered
    assert "loop-state" in rendered
    assert "review-followup" in rendered
    assert "agent-loop-mcp" in rendered
    assert "read-only `gh pr list`" in rendered
    assert "force-push" in rendered
    assert "make ship-arm: conservative single end-to-end ship pipeline" in rendered
    assert "human-gated-exec: legacy-named conservative remote mutation fallback" in rendered
    assert "Prefer `make ship-arm` for policy-passing end-to-end shipping" in rendered
    assert "informational reviews as advisory" in rendered
    assert "role-dispatch" in rendered
    assert "max 12" in rendered
    assert "depth 2" in rendered
    assert "queue/plan" in rendered
    assert "does not execute subagents or remote mutations" in rendered


def test_ship_command_pack_separates_primary_ship_path_from_manual_fallback(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    rendered = agent_loop.render_ship_command_pack(
        pr="12",
        branch="chore/issue-9999-agent-loop",
        repo_root=repo,
    )

    assert "## Primary End-to-End Ship Path" in rendered
    assert "## Manual Fallback Commands" in rendered
    assert "Choose one shipping path after the conservative agent gate passes" in rendered
    assert "ADR 0079 treats it as conservative agent-gate acknowledgment" in rendered
    assert "explicit confirmation flag is still required" in rendered
    assert "# make ship-arm REAL_EVAL=skip DRAFT=true DRY_RUN=1" in rendered
    assert "--action pr-create" in rendered


def test_approval_packet_pr_body_context_and_ship_simulation_are_local_reports(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    claim = repo / "reports" / "agent_loop" / "claim.md"
    claim.parent.mkdir(parents=True)
    claim.write_text("Docs-only orchestration change. question: PRIVATE RAW QUERY\n", encoding="utf-8")

    approval_out, approval = agent_loop.write_approval_packet(
        task_id="T-2026-9999",
        changed_files=["scripts/agent_loop.py", "tests/test_agent_loop.py"],
        claim_text=claim,
        repo_root=repo,
    )
    body_out, body = agent_loop.write_pr_body(
        task_id="T-2026-9999",
        changed_files=["scripts/agent_loop.py"],
        branch="chore/issue-123-agent-loop",
        repo_root=repo,
    )
    context_out, context = agent_loop.write_context_pack(
        task_id="T-2026-9999",
        changed_files=["scripts/agent_loop.py"],
        repo_root=repo,
    )
    ship_out, ship = agent_loop.write_ship_simulation(
        task_id="T-2026-9999",
        changed_files=["scripts/agent_loop.py"],
        branch="chore/issue-123-agent-loop",
        repo_root=repo,
    )

    assert approval_out == repo / "reports" / "agent_loop" / "approval_packet.md"
    assert body_out == repo / "reports" / "agent_loop" / "pr_body.md"
    assert context_out == repo / "reports" / "agent_loop" / "context_pack.md"
    assert ship_out == repo / "reports" / "agent_loop" / "ship_simulation.md"
    combined = "\n".join([approval, body, context, ship])
    assert "PRIVATE RAW QUERY" not in combined
    assert "Closes #123" in body
    assert "Suggested, not yet run" in body
    assert "Cross-Agent Context Pack" in context
    assert "Simulation only" in ship
    assert "gh pr create" in ship
    assert "git push" not in ship


def test_auto_ship_plan_bridges_existing_ship_arm_without_arming(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())

    out, plan, rendered = agent_loop.write_auto_ship_plan(
        task_id="T-2026-9999",
        changed_files=["docs/operations/auto-ship.md"],
        branch="chore/issue-9999-agent-loop",
        dry_run=True,
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "auto_ship_plan.md"
    assert plan.decision == "dry-run-first"
    assert "make ship-arm" in rendered
    assert "DRY_RUN=1" in rendered
    assert "Plan only" in rendered
    assert "does not arm auto-ship" in rendered
    assert not (repo / ".claude" / ".ship-armed").exists()


def test_auto_ship_plan_blocks_existing_armed_state_and_private_surface(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    (repo / ".claude").mkdir()
    (repo / ".claude" / ".ship-armed").write_text("{}\n", encoding="utf-8")

    out, plan, rendered = agent_loop.write_auto_ship_plan(
        changed_files=["reports/real100/eval_summary.json"],
        branch="chore/issue-9999-agent-loop",
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "auto_ship_plan.md"
    assert plan.decision == "blocked"
    assert any("already armed" in blocker for blocker in plan.blockers)
    assert "private-real-eval" in rendered or "privacy-sensitive-artifact" in rendered
    assert "REAL_EVAL=skip" in rendered
    assert "human private-eval decision" in rendered


def test_auto_ship_prepare_reports_detached_head_branch_command(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "HEAD")

    out, report, rendered = agent_loop.write_auto_ship_prepare(
        issue="9999",
        slug="agent-loop",
        repo_root=repo,
    )

    assert out == repo / "reports" / "agent_loop" / "auto_ship_prepare.md"
    assert report.result == "needs-branch"
    assert report.created is False
    assert "chore/issue-9999-agent-loop" in rendered
    assert "--create-branch --confirm-human-approved" in rendered
    assert "does not arm auto-ship" in rendered


def test_auto_ship_prepare_can_create_local_branch_with_confirmation(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    calls: list[list[str]] = []
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "HEAD")
    monkeypatch.setattr(agent_loop, "_branch_exists", lambda branch, repo_root: False)

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    _out, report, rendered = agent_loop.write_auto_ship_prepare(
        issue="9999",
        slug="agent-loop",
        create_branch=True,
        confirm_human_approved=True,
        repo_root=repo,
    )

    assert report.result == "branch-created"
    assert report.created is True
    assert calls == [["git", "-C", str(repo), "switch", "-c", "chore/issue-9999-agent-loop"]]
    assert "Branch created: `True`" in rendered
    assert "make ship-arm" in rendered


def test_propose_queue_plan_review_plan_stale_architecture_and_gate_reports(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    brief = repo / "reports" / "agent_loop" / "codex_tasks" / "001-task.md"
    brief.parent.mkdir(parents=True)
    brief.write_text(
        """# Add agent loop helper

- Classification: `ready`
- Source: `PR #12`
- Reason: safe helper

## Goal

Add a local-only report.

## Expected Evidence

Focused test.

## Verification

```bash
python3 -m pytest tests/test_agent_loop.py -q
```
""",
        encoding="utf-8",
    )

    patch_out, patch = agent_loop.write_propose_queue_plan(task_brief=brief, repo_root=repo)

    review = repo / "reports" / "agent_loop" / "review.md"
    review.write_text(
        """## Findings

- [blocking] scripts/agent_loop.py:1 - Fix unsafe path handling.
- [non-blocking] reports/real100/doc_id-1.json:1 - Privacy issue: filename: private.pdf.
""",
        encoding="utf-8",
    )
    review_out, review_plan = agent_loop.write_review_plan(reviews=[review], repo_root=repo)
    arch_out, arch = agent_loop.write_architecture_brief(changed_files=["rag_core.py"], repo_root=repo)
    gate_out, gate = agent_loop.write_gate_brief(
        gate="architecture",
        changed_files=["rag_core.py"],
        repo_root=repo,
    )

    old_report = repo / "reports" / "agent_loop" / "old.md"
    old_report.write_text("old\n", encoding="utf-8")
    os.utime(old_report, (0, 0))
    stale_out, stale = agent_loop.write_stale_reports(max_age_days=1, repo_root=repo)

    assert patch_out == repo / "reports" / "agent_loop" / "queue_plan_patch.diff"
    assert "Dry-run only" in patch
    assert "tasks/queue.md" in patch
    assert review_out == repo / "reports" / "agent_loop" / "review_plan.md"
    assert "must-fix" in review_plan
    assert "needs-human-decision" in review_plan
    assert "private.pdf" not in review_plan
    assert arch_out == repo / "reports" / "agent_loop" / "architecture_brief.md"
    assert "ADR likely" in arch
    assert gate_out == repo / "reports" / "agent_loop" / "gate_brief.md"
    assert "Conservative agent gates are policy decisions" in gate
    assert "ADR 0079 delegates routine gate decisions" in gate
    assert "Manual approval:" not in gate
    assert stale_out == repo / "reports" / "agent_loop" / "stale_reports.md"
    assert "old.md" in stale
    assert "dry-run" in stale


def test_safe_fix_supports_shell_hooks_without_touching_private_paths(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "claude-hooks" / "stop-agent-loop.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash  \necho ok  ", encoding="utf-8")

    _, report, rendered = agent_loop.write_safe_fix(
        changed_files=["scripts/claude-hooks/stop-agent-loop.sh"],
        apply=True,
        repo_root=tmp_path,
    )

    assert report.applied
    assert "unsupported suffix" not in rendered
    assert script.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho ok\n"


def test_manifest_pr_body_check_ci_stacked_and_patch_proposal(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    body = repo / "reports" / "agent_loop" / "pr_body.md"
    body.parent.mkdir(parents=True)
    body.write_text(
        """## 1. 무엇을 왜 바꿨는가

Closes #999

### 5b. Real-data delta

N/A
question: PRIVATE RAW QUERY
""",
        encoding="utf-8",
    )
    target = repo / "scripts" / "agent_loop.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('x')  \n", encoding="utf-8")

    manifest_out, manifest = agent_loop.write_manifest(
        changed_files=["scripts/agent_loop.py"],
        command="test-command",
        outputs=[Path("reports/agent_loop/pr_body.md")],
        repo_root=repo,
    )
    check_out, rc, check = agent_loop.write_pr_body_check(
        body=body,
        changed_files=["rag_core.py"],
        branch="chore/issue-123-example",
        repo_root=repo,
    )

    ci_log = repo / "reports" / "agent_loop" / "ci.log"
    ci_log.write_text("FAILED tests/test_agent_loop.py::test_x AssertionError\n5b missing\n", encoding="utf-8")
    ci_out, ci_dir, count, ci = agent_loop.write_ci_ingest(logs=[ci_log], repo_root=repo)

    pr_state = repo / "reports" / "agent_loop" / "pr_state.json"
    pr_state.write_text(
        json.dumps([{"number": 22, "title": "Child PR", "baseRefName": "feature-parent", "headRefName": "child"}]),
        encoding="utf-8",
    )
    stacked_out, stacked = agent_loop.write_stacked_risk(
        branch="feature-parent",
        pr_json=pr_state,
        repo_root=repo,
    )
    patch_out, patch = agent_loop.write_patch_proposal(
        changed_files=["scripts/agent_loop.py"],
        repo_root=repo,
    )

    assert manifest_out == repo / "reports" / "agent_loop" / "manifest.json"
    assert manifest["changed_files_hash"]
    assert check_out == repo / "reports" / "agent_loop" / "pr_body_check.md"
    assert rc == 1
    assert "does not match branch issue" in check
    assert "private raw value" in check
    assert "PRIVATE RAW QUERY" not in check
    assert ci_out == repo / "reports" / "agent_loop" / "ci_ingest.md"
    assert ci_dir == repo / "reports" / "agent_loop" / "ci_followups"
    assert count >= 2
    assert "test-failure" in ci
    assert "PRIVATE RAW QUERY" not in ci
    assert stacked_out == repo / "reports" / "agent_loop" / "stacked_risk.md"
    assert "Dependent open PR count: `1`" in stacked
    assert patch_out == repo / "reports" / "agent_loop" / "patch_proposal.diff"
    assert "-print('x')  " in patch
    assert "+print('x')" in patch


def test_eval_run_manifest_records_offline_online_schema_without_private_leaks(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    config = repo / "eval" / "real_config.local.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("question: PRIVATE RAW QUERY\nanswer: PRIVATE RAW ANSWER\n", encoding="utf-8")

    offline_out, offline = agent_loop.write_eval_run_manifest(
        mode="offline",
        provider="local",
        model="local-judge-v1",
        judge_backend="local-llm",
        payload_class="none",
        egress_mode="none",
        hardware="/Users/example/private/gpu-host",
        source_command=(
            "python3 scripts/run_private_real_eval.py "
            "--config /Users/example/private/real_config.local.yaml "
            "--question 'PRIVATE RAW QUERY'"
        ),
        config=config,
        repo_root=repo,
    )
    online_out, online = agent_loop.write_eval_run_manifest(
        mode="online",
        provider="openai",
        model="gpt-fixture",
        judge_backend="external-judge",
        payload_class="private-raw",
        egress_mode="private-raw",
        surface="private-real-eval",
        case_family="real100-v2",
        cost_usd=1.25,
        latency_ms=1250.0,
        repo_root=repo,
    )

    assert offline_out == repo / "reports" / "agent_loop" / "offline_online_run_manifest.json"
    assert online_out == offline_out
    assert set(offline) == set(online)
    assert set(offline["environment"]) == set(online["environment"])  # type: ignore[arg-type]
    assert set(offline["model"]) == set(online["model"])  # type: ignore[arg-type]
    assert set(offline["payload"]) == set(online["payload"])  # type: ignore[arg-type]
    assert offline["environment"]["mode"] == "offline"  # type: ignore[index]
    assert offline["environment"]["external_api_allowed"] is False  # type: ignore[index]
    assert offline["payload"]["private_data_egress"] == "none"  # type: ignore[index]
    assert online["environment"]["mode"] == "online"  # type: ignore[index]
    assert online["environment"]["external_api_allowed"] is True  # type: ignore[index]
    assert online["model"]["provider"] == "openai"  # type: ignore[index]
    assert online["payload"]["private_data_egress"] == "private-raw"  # type: ignore[index]
    assert online["provenance"]["config_sha256"] == "unknown"  # type: ignore[index]
    assert offline["provenance"]["config_sha256"] != "unknown"  # type: ignore[index]

    rendered = json.dumps([offline, online], ensure_ascii=False, sort_keys=True)
    assert "PRIVATE RAW QUERY" not in rendered
    assert "PRIVATE RAW ANSWER" not in rendered
    assert "/Users/example" not in rendered
    assert "real_config.local.yaml" not in rendered


def test_eval_run_manifest_fails_closed_for_invalid_egress_and_online_provider(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    with pytest.raises(ValueError, match="private_data_egress=none"):
        agent_loop.build_eval_run_manifest(
            mode="offline",
            provider="local",
            model="local-judge-v1",
            payload_class="private-raw",
            egress_mode="private-raw",
            surface="private-real-eval",
            case_family="real100-v2",
            judge_backend="local-llm",
            hardware=None,
            source_command="manual",
            config=None,
            cost_usd=None,
            latency_ms=None,
            repo_root=repo,
        )

    with pytest.raises(ValueError, match="online eval run manifest requires provider"):
        agent_loop.build_eval_run_manifest(
            mode="online",
            provider=None,
            model="gpt-fixture",
            payload_class="metadata-only",
            egress_mode="metadata-only",
            surface="private-real-eval",
            case_family="real100-v2",
            judge_backend="external-judge",
            hardware=None,
            source_command="manual",
            config=None,
            cost_usd=None,
            latency_ms=None,
            repo_root=repo,
        )


def test_adr_html_context_ship_commands_and_apply_queue_plan(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    adr_dir = repo / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / "0001-existing.md").write_text("# ADR 0001\n", encoding="utf-8")

    adr_out, draft_out, adr = agent_loop.write_adr_reservation(
        title="New eval surface",
        repo_root=repo,
    )
    html_out, html = agent_loop.write_dashboard_html(
        changed_files=["scripts/agent_loop.py"],
        repo_root=repo,
    )
    context_out, context = agent_loop.write_context_pack(
        changed_files=["scripts/agent_loop.py"],
        profile="claude",
        repo_root=repo,
    )
    commands_out, commands = agent_loop.write_ship_command_pack(
        pr="42",
        branch="chore/issue-123-agent-loop",
        repo_root=repo,
    )

    report_dir = repo / "reports" / "agent_loop"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "queue_entry_draft.md").write_text(
        """## T-2026-0000 — Draft

- ID: T-2026-0000
- Title: Draft
""",
        encoding="utf-8",
    )
    (report_dir / "plan_draft.md").write_text(
        """# Plan: T-2026-0000 Draft

- Suggested final path: `docs/plans/T-2026-0000-draft.md`
""",
        encoding="utf-8",
    )
    blocked_out, blocked = agent_loop.write_apply_queue_plan(confirm_human_approved=False, repo_root=repo)
    assert blocked_out == repo / "reports" / "agent_loop" / "apply_queue_plan.md"
    assert "blocked" in blocked
    assert not (repo / "docs" / "plans" / "T-2026-0000-draft.md").exists()
    apply_out, applied = agent_loop.write_apply_queue_plan(
        confirm_human_approved=True,
        repo_root=repo,
    )

    assert adr_out == repo / "reports" / "agent_loop" / "adr_reservation.md"
    assert draft_out == repo / "reports" / "agent_loop" / "adr_draft.md"
    assert "0002" in adr
    assert not (repo / "docs" / "adr" / "0002-new-eval-surface.md").exists()
    assert html_out == repo / "reports" / "agent_loop" / "dashboard.html"
    assert "<!doctype html>" in html
    assert context_out == repo / "reports" / "agent_loop" / "context_pack.md"
    assert "Profile: `claude`" in context
    assert commands_out == repo / "reports" / "agent_loop" / "ship_commands.md"
    assert "Primary End-to-End Ship Path" in commands
    assert "Manual Fallback Commands" in commands
    assert apply_out == repo / "reports" / "agent_loop" / "apply_queue_plan.md"
    assert "applied" in applied
    assert (repo / "docs" / "plans" / "T-2026-0000-draft.md").exists()


def test_review_threads_readiness_history_policy_and_coverage_reports(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    report_dir = repo / "reports" / "agent_loop"
    report_dir.mkdir(parents=True, exist_ok=True)
    threads = report_dir / "threads.json"
    threads.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "isResolved": False,
                        "path": "eval/naive_rag/benchmark.py",
                        "line": 12,
                        "comments": {"nodes": [{"body": "Benchmark claim needs human review."}]},
                    },
                    {
                        "isResolved": True,
                        "path": "scripts/agent_loop.py",
                        "line": 3,
                        "comments": {"nodes": [{"body": "nit fixed"}]},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    body = report_dir / "pr_body.md"
    body.write_text(
        """Closes #9999

### 5b. Real-data delta

N/A - no load-bearing path.
""",
        encoding="utf-8",
    )

    threads_out, threads_report = agent_loop.write_review_threads(threads_json=threads, repo_root=repo)
    score_out, score, score_report = agent_loop.write_readiness_score(
        task_id="T-2026-9999",
        changed_files=["scripts/agent_loop.py"],
        body=body,
        branch="chore/issue-9999-agent-loop",
        repo_root=repo,
    )
    history_path = agent_loop.append_validation_history(
        [agent_loop.ValidationRun("git diff --check", 0, "PRIVATE RAW QUERY", "")],
        changed_files=["scripts/agent_loop.py"],
        repo_root=repo,
    )
    history_out, history = agent_loop.write_validation_history_report(repo_root=repo)
    hygiene_out, hygiene_rc, hygiene = agent_loop.write_branch_issue_hygiene(
        branch="chore/issue-9999-agent-loop",
        body=body,
        task_id="T-2026-9999",
        repo_root=repo,
    )
    privacy_out, privacy_rc, privacy = agent_loop.write_privacy_regression(repo_root=repo)
    claim_out, claim_rc, claim = agent_loop.write_claim_policy(changed_files=["docs/readme.md"], text=body, repo_root=repo)
    arch_out, arch = agent_loop.write_architecture_decision(changed_files=["rag_core.py"], repo_root=repo)
    integration_out, integration = agent_loop.write_integration_pack(repo_root=repo)
    schedule_out, schedule = agent_loop.write_schedule_config(repo_root=repo)
    coverage_out, coverage = agent_loop.write_automation_coverage(repo_root=repo)
    role_out, role_dispatch = agent_loop.write_role_dispatch(
        changed_files=["eval/naive_rag/benchmark.py"],
        owner_role="Implementer -> Reviewer",
        repo_root=repo,
    )

    assert threads_out == repo / "reports" / "agent_loop" / "review_threads.md"
    assert "Unresolved count: `1`" in threads_report
    assert "Benchmark Auditor" in threads_report
    assert score_out == repo / "reports" / "agent_loop" / "readiness_score.md"
    assert score.decision in {"ready-for-human-approval", "review-before-ship"}
    assert "does not push" in score_report
    assert history_path == repo / "reports" / "agent_loop" / "validation_history.jsonl"
    assert history_out == repo / "reports" / "agent_loop" / "validation_history.md"
    assert "PRIVATE RAW QUERY" not in history
    assert hygiene_out == repo / "reports" / "agent_loop" / "branch_issue_hygiene.md"
    assert hygiene_rc == 0
    assert "Closes" not in hygiene or "#9999" in hygiene
    assert privacy_out == repo / "reports" / "agent_loop" / "privacy_regression.md"
    assert privacy_rc == 0
    assert "Result: `pass`" in privacy
    assert claim_out == repo / "reports" / "agent_loop" / "claim_policy.md"
    assert claim_rc == 0
    assert "Disallowed Or Agent-Gated Claims" in claim
    assert arch_out == repo / "reports" / "agent_loop" / "architecture_decision.md"
    assert "human-architecture-review-required" in arch
    assert integration_out == repo / "reports" / "agent_loop" / "integration_pack.md"
    assert "ChatGPT" in integration
    assert schedule_out == repo / "reports" / "agent_loop" / "schedule_config.md"
    assert "does not install cron jobs" in schedule
    assert coverage_out == repo / "reports" / "agent_loop" / "automation_coverage.md"
    assert "auto-pass strict profiles" in coverage
    assert "Still Agent-Gated" in coverage
    assert "conservative remote execution" in coverage
    assert "ADR 0079 defaults" in coverage
    assert "role-separated subagent dispatch" in coverage
    assert "does not execute subagents or remote mutations" in coverage
    assert role_out == repo / "reports" / "agent_loop" / "role_dispatch.md"
    assert "Role Dispatch Plan" in role_dispatch
    assert "Benchmark Auditor" in role_dispatch
    assert "depth 2 maximum" in role_dispatch
    assert "does not spawn subagents" in role_dispatch


def test_role_dispatch_adds_surface_auditors_without_executing_subagents(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    default_rendered = agent_loop.render_role_dispatch(changed_files=["docs/readme.md"], repo_root=repo)
    rendered = agent_loop.render_role_dispatch(
        changed_files=["reports/real100/eval_summary.json", "docs/adr/0079-agent-gated-offline-online-rfp-eval-loop.md"],
        owner_role="Planner -> Implementer -> Reviewer",
        repo_root=repo,
    )

    assert "Owner role: `Planner -> Implementer -> Reviewer`" in default_rendered
    assert "Planner" in default_rendered
    assert "Implementer" in default_rendered
    assert "Reviewer" in default_rendered
    assert "Role Dispatch Plan" in rendered
    assert "Planner" in rendered
    assert "Implementer" in rendered
    assert "Benchmark Auditor" in rendered
    assert "Privacy Auditor" in rendered
    assert "Reviewer" in rendered
    assert "read-only/report-only" in rendered
    assert "assigned files only" in rendered
    assert "up to 12 role subagents" in rendered
    assert "depth 2 maximum: root session -> role subagents only" in rendered
    assert "does not spawn subagents" in rendered
    assert "Do not delegate private real-eval interpretation" in rendered


def test_role_dispatch_consumes_batch_workset_role_hints(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    batch = repo / "reports" / "agent_loop" / "batch_plan.json"
    batch.parent.mkdir(parents=True, exist_ok=True)
    batch.write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "title": "Triage blocked PR lane",
                    "classification": "blocked",
                    "source": "PR corpus",
                    "source_prs": ["#10", "#11"],
                    "workset": "blocked-pr-triage",
                    "workset_id": "blocked-pr-triage",
                    "lane": "serial",
                    "gate_reason": "brief declares serial lane",
                    "brief": "reports/agent_loop/codex_tasks/001.md",
                    "role_hints": ["Planner", "CI Reviewer", "Deep Reviewer", "Reviewer"],
                    "completion_proof": "All source PR blockers are resolved.",
                    "verification": ["python3 -m pytest tests/test_agent_loop.py -q"],
                },
                {
                    "index": 2,
                    "title": "Ship ready PR lane",
                    "classification": "ready_for_review",
                    "source": "PR corpus",
                    "source_prs": ["#12"],
                    "workset": "ready-pr-ship",
                    "workset_id": "ready-pr-ship",
                    "lane": "review-only",
                    "gate_reason": "brief declares review-only lane",
                    "brief": "reports/agent_loop/codex_tasks/002.md",
                    "role_hints": ["Planner", "Maintainer", "Reviewer"],
                    "completion_proof": "Ready PRs have merge evidence.",
                    "verification": ["git diff --check"],
                },
            ]
        ),
        encoding="utf-8",
    )

    rendered = agent_loop.render_role_dispatch(
        batch=batch,
        workset="blocked-pr-triage",
        repo_root=repo,
    )

    assert "Workset filter: `blocked-pr-triage`" in rendered
    assert "Workset item count: `1`" in rendered
    assert "CI Reviewer" in rendered
    assert "Deep Reviewer" in rendered
    assert "## Workset Inputs" in rendered
    assert "#10, #11" in rendered
    assert "Triage blocked PR lane" in rendered
    assert "Ship ready PR lane" not in rendered


def _clear_overlap_report(issue: str = "9999", branch: str = "chore/issue-9999-active-loop") -> agent_loop.OverlapPreflightReport:
    return agent_loop.OverlapPreflightReport(
        issue=issue,
        branch=branch,
        result="clear",
        current_branch=branch,
        current_head="abc123",
        origin_main="abc123",
        blockers=(),
        warnings=(),
        evidence=("clear fixture",),
        open_prs=(),
        branch_prs=(),
        worktrees=(),
        remote_branches=(),
    )


def _write_active_registry(repo: Path, *, topology: str, sessions: list[dict[str, str]]) -> Path:
    registry = repo / "reports" / "agent_loop" / "active" / "session_registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({"schema_version": 1, "topology": topology, "sessions": sessions}),
        encoding="utf-8",
    )
    return registry


def test_active_loop_dry_run_creates_four_session_ledger_without_remote_mutation(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    registry = json.loads(result.registry_path.read_text(encoding="utf-8"))
    leases = json.loads(result.leases_path.read_text(encoding="utf-8"))

    assert result.decision == "planned"
    assert len(registry["sessions"]) == 4
    assert {item["role"] for item in registry["sessions"]} == {
        "Orchestrator",
        "Implementer",
        "Reviewer",
        "CI/Eval Auditor",
    }
    assert leases["leases"][0]["status"] == "active"
    assert (result.assignments_dir / "orchestrator.md").exists()
    assert result.events_path.exists()
    assert calls == []


def test_active_loop_expanded_eight_dry_run_creates_sessions_and_assignments(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        topology="expanded-eight",
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    registry = json.loads(result.registry_path.read_text(encoding="utf-8"))
    leases = json.loads(result.leases_path.read_text(encoding="utf-8"))

    assert result.decision == "planned"
    assert len(registry["sessions"]) == 8
    assert {item["session_id"] for item in registry["sessions"]} == {
        "orchestrator",
        "planner-triage",
        "experiment-scout",
        "implementer",
        "reviewer",
        "deep-reviewer",
        "ci-regression-auditor",
        "eval-claim-privacy-auditor",
    }
    assert leases["leases"][0]["owner_session"] == "implementer"
    assert len(list(result.assignments_dir.glob("*.md"))) == 8
    assert "workset-recommend" in (result.assignments_dir / "experiment-scout.md").read_text(encoding="utf-8")
    assert calls == []


def test_active_loop_execute_runs_ship_only_after_reviewer_and_ci_pass(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = repo / "reports" / "agent_loop" / "active" / "session_registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    now = "2999-01-01T00:00:00Z"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topology": "four-role",
                "sessions": [
                    {"session_id": "reviewer", "role": "Reviewer", "status": "passed", "last_heartbeat": now},
                    {"session_id": "ci-eval-auditor", "role": "CI/Eval Auditor", "status": "passed", "last_heartbeat": now},
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        execute=True,
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    assert result.decision == "executed"
    assert result.executed_commands == (("make", "ship-run", "DRAFT=false", "REAL_EVAL=auto"),)
    assert calls == [["make", "ship-run", "DRAFT=false", "REAL_EVAL=auto"]]


def test_active_loop_expanded_eight_execute_uses_conservative_gate(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    now = "2999-01-01T00:00:00Z"
    _write_active_registry(
        repo,
        topology="expanded-eight",
        sessions=[
            {"session_id": "reviewer", "role": "Reviewer", "status": "passed", "last_heartbeat": now},
            {"session_id": "ci-regression-auditor", "role": "CI / Regression Auditor", "status": "passed", "last_heartbeat": now},
            {"session_id": "eval-claim-privacy-auditor", "role": "Eval / Claim / Privacy Auditor", "status": "clear", "last_heartbeat": now},
            {"session_id": "planner-triage", "role": "Planner / Issue Triage", "status": "idle", "last_heartbeat": "2020-01-01T00:00:00Z"},
            {"session_id": "experiment-scout", "role": "Experiment Scout", "status": "idle", "last_heartbeat": "2020-01-01T00:00:00Z"},
        ],
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        topology="expanded-eight",
        execute=True,
        changed_files=["docs/operations/active-agent-loop.md"],
        lease_ttl_minutes=1,
        repo_root=repo,
    )

    registry = json.loads(result.registry_path.read_text(encoding="utf-8"))
    planner = next(item for item in registry["sessions"] if item["session_id"] == "planner-triage")
    experiment = next(item for item in registry["sessions"] if item["session_id"] == "experiment-scout")

    assert result.decision == "executed"
    assert planner["status"] == "stale"
    assert experiment["status"] == "stale"
    assert not any("Planner / Issue Triage" in blocker for blocker in result.blockers)
    assert not any("Experiment Scout" in blocker for blocker in result.blockers)
    assert calls == [["make", "ship-run", "DRAFT=false", "REAL_EVAL=auto"]]


def test_active_loop_expanded_eight_blocks_when_required_auditor_missing(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    now = "2999-01-01T00:00:00Z"
    _write_active_registry(
        repo,
        topology="expanded-eight",
        sessions=[
            {"session_id": "reviewer", "role": "Reviewer", "status": "passed", "last_heartbeat": now},
            {"session_id": "ci-regression-auditor", "role": "CI / Regression Auditor", "status": "passed", "last_heartbeat": now},
        ],
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        topology="expanded-eight",
        execute=True,
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    assert result.decision == "blocked"
    assert any("Eval / Claim / Privacy Auditor session has not passed" in blocker for blocker in result.blockers)
    assert calls == []


def test_active_loop_expanded_eight_requires_deep_reviewer_for_load_bearing(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    now = "2999-01-01T00:00:00Z"
    _write_active_registry(
        repo,
        topology="expanded-eight",
        sessions=[
            {"session_id": "reviewer", "role": "Reviewer", "status": "passed", "last_heartbeat": now},
            {"session_id": "ci-regression-auditor", "role": "CI / Regression Auditor", "status": "passed", "last_heartbeat": now},
            {"session_id": "eval-claim-privacy-auditor", "role": "Eval / Claim / Privacy Auditor", "status": "clear", "last_heartbeat": now},
        ],
    )
    body = repo / "pr_body.md"
    body.write_text("N/A\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])
    monkeypatch.setattr(agent_loop, "check_pr_body_text", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        topology="expanded-eight",
        execute=True,
        changed_files=["rag_core.py"],
        pr_body=body,
        repo_root=repo,
    )

    assert result.decision == "blocked"
    assert any("Deep Reviewer session has not passed" in blocker for blocker in result.blockers)
    assert calls == []


def test_active_loop_blocks_ship_when_reviewer_or_ci_has_not_passed(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        execute=True,
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    assert result.decision == "blocked"
    assert any("Reviewer session has not passed" in blocker for blocker in result.blockers)
    assert any("CI/Eval Auditor session has not passed" in blocker for blocker in result.blockers)
    assert calls == []


def test_active_loop_execute_blocks_on_readiness_score_blockers(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry = repo / "reports" / "agent_loop" / "active" / "session_registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topology": "four-role",
                "sessions": [
                    {"session_id": "reviewer", "role": "Reviewer", "status": "passed", "last_heartbeat": "2999-01-01T00:00:00Z"},
                    {"session_id": "ci-eval-auditor", "role": "CI/Eval Auditor", "status": "passed", "last_heartbeat": "2999-01-01T00:00:00Z"},
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(execute=True, repo_root=repo)

    assert result.decision == "blocked"
    assert any("readiness-score is blocked" in blocker for blocker in result.blockers)
    assert any("changed files are missing" in blocker for blocker in result.blockers)
    assert calls == []


def test_active_loop_blocks_overlap_and_recovery_needed_leases(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    lease_path = repo / "reports" / "agent_loop" / "active" / "leases.json"
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "leases": [
                    {
                        "lease_id": "old-lease",
                        "status": "active",
                        "branch": "chore/issue-9999-active-loop",
                        "worktree": ".",
                        "expires_at": "2020-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    blocked_overlap = agent_loop.OverlapPreflightReport(
        issue="9999",
        branch="chore/issue-9999-active-loop",
        result="blocked",
        current_branch="chore/issue-9999-active-loop",
        current_head="abc123",
        origin_main="abc123",
        blockers=("open PR already exists for the target issue or branch",),
        warnings=(),
        evidence=(),
        open_prs=("#1 existing",),
        branch_prs=(),
        worktrees=(),
        remote_branches=(),
    )

    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: blocked_overlap)
    monkeypatch.setattr(agent_loop, "_inspect_active_worktree", lambda worktree, repo_root: {"state": "dirty-worktree"})
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )
    leases = json.loads(result.leases_path.read_text(encoding="utf-8"))

    assert result.decision == "blocked"
    assert any("requires recovery" in blocker for blocker in result.blockers)
    assert any("overlap-preflight blocked assignment" in blocker for blocker in result.blockers)
    assert leases["leases"][0]["status"] == "recovery-needed"


def test_active_loop_requires_claim_evidence_for_eval_surface(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        changed_files=["eval/run_eval.py"],
        repo_root=repo,
    )

    assert result.decision == "blocked"
    assert any("load-bearing/eval surface requires claim or PR-body evidence" in blocker for blocker in result.blockers)


def test_session_heartbeat_refreshes_registry_and_stale_sessions_are_marked(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    registry, events, payload = agent_loop.write_session_heartbeat(
        session_id="reviewer",
        role="Reviewer",
        task_id="T-2026-9999",
        status="passed",
        repo_root=repo,
    )
    payload["sessions"][0]["last_heartbeat"] = "2020-01-01T00:00:00Z"
    registry.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        lease_ttl_minutes=1,
        repo_root=repo,
    )
    refreshed = json.loads(result.registry_path.read_text(encoding="utf-8"))
    reviewer = next(item for item in refreshed["sessions"] if item["session_id"] == "reviewer")

    assert events.exists()
    assert reviewer["heartbeat_state"] == "stale"
    assert reviewer["status"] == "stale"


def test_session_heartbeat_preserves_expanded_eight_next_command(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_active_registry(
        repo,
        topology="expanded-eight",
        sessions=[
            {
                "session_id": "orchestrator",
                "role": "Orchestrator",
                "status": "running",
                "last_heartbeat": "2999-01-01T00:00:00Z",
            }
        ],
    )

    _, _, payload = agent_loop.write_session_heartbeat(
        session_id="orchestrator",
        role="Orchestrator",
        status="running",
        repo_root=repo,
    )

    session = payload["sessions"][0]
    assert payload["topology"] == "expanded-eight"
    assert "--topology expanded-eight" in session["next_command"]


def test_active_loop_cli_accepts_expanded_eight_and_rejects_unknown_topology() -> None:
    parser = agent_loop.build_parser()

    args = parser.parse_args(["active-loop", "--topology", "expanded-eight"])
    start_args = parser.parse_args(["active-start"])

    assert args.topology == "expanded-eight"
    assert start_args.topology == "expanded-eight"
    with pytest.raises(SystemExit):
        parser.parse_args(["active-loop", "--topology", "unknown-topology"])


def _patch_active_loop_clear(monkeypatch) -> None:
    monkeypatch.setattr(agent_loop.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "chore/issue-9999-active-loop")
    monkeypatch.setattr(agent_loop, "build_overlap_preflight", lambda issue, branch, repo_root: _clear_overlap_report(issue, branch))
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])


def test_active_loop_registry_v2_carries_lanes_gate_policy_and_agent_mix(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)

    result = agent_loop.write_active_loop(
        topology="expanded-eight",
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    registry = json.loads(result.registry_path.read_text(encoding="utf-8"))
    leases = json.loads(result.leases_path.read_text(encoding="utf-8"))
    agent_mix = json.loads((repo / "reports" / "agent_loop" / "active" / "agent_mix.json").read_text(encoding="utf-8"))

    assert registry["schema_version"] == agent_loop.ACTIVE_REGISTRY_SCHEMA_VERSION == 2
    assert registry["gate_policy"] == "conservative"
    assert registry["agent_mix"]["target"] == {"claude": 5, "codex": 5}
    assert registry["agent_mix"]["unit"] == "work_unit"
    # Every session in every topology carries both agent lanes (dual-agent = lane policy).
    for session in registry["sessions"]:
        assert set(session["lanes"]) == {"claude", "codex"}
        for agent in ("claude", "codex"):
            assert session["lanes"][agent]["agent"] == agent
            assert session["lanes"][agent]["wu_spent_rolling"] == 0
    gates = {item["role"]: item["ship_gate"] for item in registry["sessions"]}
    assert gates == {
        "Orchestrator": "control-plane",
        "Planner / Issue Triage": "non-blocking",
        "Experiment Scout": "non-blocking",
        "Implementer": "lease-owner",
        "Reviewer": "blocking",
        "Deep Reviewer": "blocking",
        "CI / Regression Auditor": "blocking",
        "Eval / Claim / Privacy Auditor": "blocking",
    }
    # Only the Implementer owns the write lease.
    owners = [item["session_id"] for item in registry["sessions"] if item["write_lease_owner"]]
    assert owners == ["implementer"]
    write_leases = [item for item in leases["leases"] if item.get("lease_type") == "write"]
    assert len(write_leases) == 1
    assert write_leases[0]["owner_session"] == "implementer"
    assert write_leases[0]["active_agent"] is None
    # The agent_mix ledger file is written with a zeroed rolling window.
    assert agent_mix["policy"]["target"] == {"claude": 5, "codex": 5}
    assert agent_mix["rolling"] == {"claude": 0, "codex": 0}
    assert agent_mix["ledger"] == []


def test_active_loop_agent_mix_flag_overrides_target(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        agent_mix=agent_loop._parse_agent_mix("claude=7,codex=3"),
        repo_root=repo,
    )

    registry = json.loads(result.registry_path.read_text(encoding="utf-8"))
    agent_mix = json.loads((repo / "reports" / "agent_loop" / "active" / "agent_mix.json").read_text(encoding="utf-8"))

    assert registry["agent_mix"]["target"] == {"claude": 7, "codex": 3}
    assert agent_mix["policy"]["target"] == {"claude": 7, "codex": 3}


def test_active_start_creates_local_start_pack_without_remote_mutation(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    result = agent_loop.write_active_start(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    assert result.decision == "started"
    assert result.report_path == repo / "reports" / "agent_loop" / "active" / "start.md"
    assert result.active_loop.decision == "planned"
    assert (repo / "reports" / "agent_loop" / "active" / "active_loop.md").exists()
    assert (repo / "reports" / "agent_loop" / "active" / "dashboard.md").exists()
    assert (repo / "reports" / "agent_loop" / "active" / "approval_packet.md").exists()
    assert (repo / "reports" / "agent_loop" / "active" / "ship_simulation.md").exists()
    assert (repo / "reports" / "agent_loop" / "active" / "auto_ship_plan.md").exists()
    assert (repo / "reports" / "agent_loop" / "active" / "privacy_audit.md").exists()
    assert not any(call[0] in {"gh", "make"} for call in calls)
    assert "active-loop --mode full-ship --topology expanded-eight --execute --from-git" in result.next_safe_command


def test_active_start_on_detached_head_starts_and_suggests_prepare(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "HEAD")
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    result = agent_loop.write_active_start(
        issue="9999",
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    assert result.decision == "started"
    assert not result.blockers
    assert any("current branch is not an issue-linked feature branch" in blocker for blocker in result.active_loop.blockers)
    assert "active-worktree-prepare --issue 9999" in result.next_safe_command
    assert "## Active-loop Blockers" in result.report_path.read_text(encoding="utf-8")


def test_active_start_generates_missing_pr_body_before_readiness_check(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)
    pr_body = repo / "reports" / "agent_loop" / "pr_body.md"

    result = agent_loop.write_active_start(
        changed_files=["docs/operations/active-agent-loop.md"],
        pr_body=pr_body,
        repo_root=repo,
    )

    assert result.decision == "started"
    assert pr_body.exists()
    assert not any("PR body path does not exist" in blocker for blocker in result.active_loop.blockers)
    assert pr_body in result.outputs
    assert not agent_loop.check_pr_body_text(
        pr_body.read_text(encoding="utf-8"),
        changed_files=["docs/operations/active-agent-loop.md"],
        branch="chore/issue-9999-active-loop",
        repo_root=repo,
    )


def test_active_start_refreshes_stale_default_pr_body_after_branch_repair(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)
    pr_body = repo / "reports" / "agent_loop" / "pr_body.md"
    pr_body.parent.mkdir(parents=True, exist_ok=True)
    pr_body.write_text("Closes #<ISSUE_NUMBER>\n", encoding="utf-8")

    result = agent_loop.write_active_start(
        issue="9999",
        changed_files=["docs/operations/active-agent-loop.md"],
        pr_body=pr_body,
        repo_root=repo,
    )

    assert result.decision == "started"
    assert "Closes #9999" in pr_body.read_text(encoding="utf-8")
    assert any("refreshed stale PR body draft" in warning for warning in result.warnings)
    assert not any("PR body check has findings" in blocker for blocker in result.active_loop.blockers)


def test_active_start_auto_task_replaces_empty_continue_bootstrap(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "HEAD")
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])

    def fake_continue_loop(**kwargs):  # type: ignore[no-untyped-def]
        out = kwargs["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Continue Loop\n", encoding="utf-8")
        return out, "# Continue Loop\n"

    monkeypatch.setattr(agent_loop, "write_continue_loop", fake_continue_loop)

    result = agent_loop.write_active_start(repo_root=repo)

    assert result.decision == "started"
    assert result.active_loop.decision == "blocked"
    assert repo / "reports" / "agent_loop" / "active" / "continue_loop.md" not in result.outputs
    assert any("auto-selected task" in warning for warning in result.warnings)
    assert result.next_safe_command == "python3 scripts/agent_loop.py continue-loop --no-apply-queue-plan"


def test_active_start_auto_selects_task_and_context_files(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-1001", title="Refresh baseline packet")
    _patch_active_loop_clear(monkeypatch)
    pr_body = repo / "reports" / "agent_loop" / "pr_body.md"

    result = agent_loop.write_active_start(pr_body=pr_body, repo_root=repo)

    start = result.report_path.read_text(encoding="utf-8")
    assert result.decision == "started"
    assert "- Task: `T-2026-1001`" in start
    assert "auto-selected task `T-2026-1001`" in start
    assert "Changed files: `2`" in start
    assert not any("changed files are missing" in warning for warning in result.warnings)
    assert "T-2026-1001" in pr_body.read_text(encoding="utf-8")


def test_active_start_redacts_stale_codex_run_logs_before_privacy_audit(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)
    stale = repo / "reports" / "agent_loop" / "active" / "codex_runs" / "reviewer" / "stdout.jsonl"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("/Users/example/private/path\n", encoding="utf-8")

    result = agent_loop.write_active_start(repo_root=repo)

    assert result.decision == "started"
    assert stale.exists()
    assert stale.read_text(encoding="utf-8") == "[redacted-local-path]\n"
    assert any("redacted 1 stale active Codex run artifact" in warning for warning in result.warnings)


def test_active_start_repair_branch_with_issue_switches_current_checkout(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    state = {"branch": "HEAD"}
    calls: list[list[str]] = []

    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: state["branch"])
    monkeypatch.setattr(agent_loop, "_branch_exists", lambda branch, repo_root: False)
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        agent_loop,
        "build_overlap_preflight",
        lambda issue, branch, repo_root: _clear_overlap_report(issue=issue, branch=branch),
    )

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if list(cmd)[:4] == ["git", "-C", str(repo), "switch"]:
            state["branch"] = list(cmd)[-1]
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if list(cmd)[:4] == ["git", "-C", str(repo), "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    result = agent_loop.write_active_start(
        issue="9999",
        changed_files=["docs/operations/active-agent-loop.md"],
        repair_branch=True,
        repo_root=repo,
    )

    assert state["branch"] == "chore/issue-9999-active-start"
    assert ["git", "-C", str(repo), "switch", "-c", "chore/issue-9999-active-start"] in calls
    assert result.decision == "started"
    assert result.active_loop.decision == "planned"
    assert not result.active_loop.blockers
    assert any("branch repair: created and switched" in warning for warning in result.warnings)


def test_active_start_repair_branch_creates_issue_when_missing(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    state = {"branch": "HEAD"}
    calls: list[list[str]] = []

    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: state["branch"])
    monkeypatch.setattr(agent_loop, "_branch_exists", lambda branch, repo_root: False)
    monkeypatch.setattr(agent_loop, "audit_privacy_output", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        agent_loop,
        "build_overlap_preflight",
        lambda issue, branch, repo_root: _clear_overlap_report(issue=issue, branch=branch),
    )

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if list(cmd)[:3] == ["gh", "issue", "create"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="https://github.com/acme/repo/issues/4242\n", stderr="")
        if list(cmd)[:4] == ["git", "-C", str(repo), "switch"]:
            state["branch"] = list(cmd)[-1]
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if list(cmd)[:4] == ["git", "-C", str(repo), "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    result = agent_loop.write_active_start(
        changed_files=["docs/operations/active-agent-loop.md"],
        repair_branch=True,
        repair_title="Active start repair",
        repo_root=repo,
    )

    assert any(call[:3] == ["gh", "issue", "create"] for call in calls)
    assert state["branch"] == "chore/issue-4242-active-start"
    assert result.decision == "started"
    assert result.active_loop.decision == "planned"
    assert not result.active_loop.blockers


def test_active_loop_four_role_v2_shape_is_unchanged(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _patch_active_loop_clear(monkeypatch)

    result = agent_loop.write_active_loop(
        changed_files=["docs/operations/active-agent-loop.md"],
        repo_root=repo,
    )

    registry = json.loads(result.registry_path.read_text(encoding="utf-8"))

    assert registry["topology"] == "four-role"
    assert {item["role"] for item in registry["sessions"]} == {
        "Orchestrator",
        "Implementer",
        "Reviewer",
        "CI/Eval Auditor",
    }
    gates = {item["role"]: item["ship_gate"] for item in registry["sessions"]}
    assert gates == {
        "Orchestrator": "control-plane",
        "Implementer": "lease-owner",
        "Reviewer": "blocking",
        "CI/Eval Auditor": "blocking",
    }
    assert all(set(item["lanes"]) == {"claude", "codex"} for item in registry["sessions"])
    assert [item["session_id"] for item in registry["sessions"] if item["write_lease_owner"]] == ["implementer"]


def test_session_heartbeat_agent_lane_updates_single_lane(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    _, _, payload = agent_loop.write_session_heartbeat(
        session_id="reviewer",
        role="Reviewer",
        status="approved",
        agent="codex",
        task_id="T-2026-9999",
        repo_root=repo,
    )

    assert payload["schema_version"] == 2
    reviewer = next(item for item in payload["sessions"] if item["session_id"] == "reviewer")
    assert reviewer["lanes"]["codex"]["status"] == "approved"
    assert reviewer["lanes"]["codex"]["current_turn"] == "T-2026-9999"
    assert reviewer["lanes"]["claude"]["status"] == "idle"
    assert reviewer["ship_gate"] == "blocking"
    assert reviewer["write_lease_owner"] is False


def test_load_active_registry_lifts_v1_to_v2(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    path = _write_active_registry(
        repo,
        topology="four-role",
        sessions=[
            {"session_id": "implementer", "role": "Implementer", "status": "running", "last_heartbeat": "2999-01-01T00:00:00Z"},
            {"session_id": "reviewer", "role": "Reviewer", "status": "idle", "last_heartbeat": "2999-01-01T00:00:00Z"},
        ],
    )

    lifted = agent_loop._load_active_registry(path)

    assert lifted["schema_version"] == 2
    assert lifted["gate_policy"] == "conservative"
    assert isinstance(lifted["agent_mix"], dict)
    by_id = {item["session_id"]: item for item in lifted["sessions"]}
    assert set(by_id["implementer"]["lanes"]) == {"claude", "codex"}
    assert by_id["implementer"]["write_lease_owner"] is True
    assert by_id["implementer"]["ship_gate"] == "lease-owner"
    assert by_id["reviewer"]["write_lease_owner"] is False
    assert by_id["reviewer"]["ship_gate"] == "blocking"


def test_parse_agent_mix_parses_and_rejects() -> None:
    assert agent_loop._parse_agent_mix(None)["target"] == {"claude": 5, "codex": 5}
    assert agent_loop._parse_agent_mix("claude=8,codex=2")["target"] == {"claude": 8, "codex": 2}
    assert agent_loop._parse_agent_mix("codex=4")["target"] == {"claude": 5, "codex": 4}
    for bad in ("claude=abc", "gpt=5", "claude=-1", "claude"):
        with pytest.raises(ValueError):
            agent_loop._parse_agent_mix(bad)


def test_session_heartbeat_cli_accepts_agent_and_rejects_unknown() -> None:
    parser = agent_loop.build_parser()

    args = parser.parse_args(
        ["session-heartbeat", "--session-id", "reviewer", "--role", "Reviewer", "--status", "approved", "--agent", "claude"]
    )
    assert args.agent == "claude"
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["session-heartbeat", "--session-id", "reviewer", "--role", "Reviewer", "--status", "approved", "--agent", "gpt"]
        )


# --- Phase 2: read-only agent-turn lanes + Work-Unit accounting (issue #1590) ---


def _claude_lane_runner(core: dict[str, object]):
    payload = json.dumps({"result": core})

    def run(cmd):
        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

    return run


def _codex_lane_runner(core: dict[str, object]):
    payload = json.dumps({"result": core})

    def run(companion, base, scope, focus):
        return subprocess.CompletedProcess([str(companion)], 0, stdout=payload, stderr="")

    return run


def _active_dir(repo: Path) -> Path:
    return repo / "reports" / "agent_loop" / "active"


def test_agent_turn_claude_lane_writes_artifact_heartbeat_and_wu(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "feat/issue-1590-active-lane-adapters")
    core = {
        "verdict": "needs-attention",
        "summary": "Review found a coverage gap",
        "findings": [{"severity": "warning", "title": "Add regression test", "body": "missing coverage"}],
        "next_steps": ["write a regression test"],
    }

    result = agent_loop.write_agent_turn(
        session_id="eval-auditor",
        role="Eval / Claim / Privacy Auditor",
        agent="claude",
        task_id="T-2026-9999",
        execute=True,
        claude_runner=_claude_lane_runner(core),
        repo_root=repo,
    )

    assert result.decision == "executed"
    assert result.agent == "claude"
    assert result.verdict == "needs-attention"
    assert result.artifact_path == _active_dir(repo) / "artifacts" / "T-2026-9999" / "eval-auditor" / "claude.json"
    artifact = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == 1
    assert artifact["agent"] == "claude"
    assert artifact["role"] == "Eval / Claim / Privacy Auditor"
    assert artifact["privacy_scrubbed"] is True
    assert artifact["wu"] == 1
    assert artifact["findings"][0]["title"] == "Add regression test"
    # Heartbeat: session + lane status reflect the verdict; non-pass blocks the gate.
    registry = json.loads((_active_dir(repo) / "session_registry.json").read_text(encoding="utf-8"))
    session = next(item for item in registry["sessions"] if item["session_id"] == "eval-auditor")
    assert session["status"] == "needs-attention"
    assert session["lanes"]["claude"]["status"] == "needs-attention"
    assert agent_loop._active_role_status_ok(registry["sessions"], "Eval / Claim / Privacy Auditor") is False
    # WU ledger records exactly one claude unit.
    mix = json.loads((_active_dir(repo) / "agent_mix.json").read_text(encoding="utf-8"))
    assert mix["rolling"] == {"claude": 1, "codex": 0}
    assert len(mix["ledger"]) == 1
    assert mix["ledger"][0]["agent"] == "claude"


def test_agent_turn_approved_verdict_satisfies_conservative_gate(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "feat/issue-1590")
    core = {"verdict": "approved", "summary": "looks good", "findings": [], "next_steps": []}

    result = agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        agent="claude",
        task_id="T-2026-9999",
        execute=True,
        claude_runner=_claude_lane_runner(core),
        repo_root=repo,
    )

    registry = json.loads((_active_dir(repo) / "session_registry.json").read_text(encoding="utf-8"))
    assert result.verdict == "approved"
    assert agent_loop._active_role_status_ok(registry["sessions"], "Reviewer") is True


def test_agent_turn_codex_lane_maps_verdict_via_companion(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "feat/issue-1590")
    companion = tmp_path / "codex-companion.mjs"
    companion.write_text("// stub", encoding="utf-8")
    monkeypatch.setenv("CODEX_COMPANION", str(companion))
    core = {"verdict": "approve", "summary": "no blockers", "findings": [], "next_steps": []}

    result = agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        agent="codex",
        task_id="T-2026-9999",
        execute=True,
        codex_runner=_codex_lane_runner(core),
        repo_root=repo,
    )

    assert result.decision == "executed"
    assert result.agent == "codex"
    assert result.verdict == "approved"  # codex "approve" -> review_artifact "approved"
    assert result.artifact_path.name == "codex.json"
    artifact = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact["agent"] == "codex"
    mix = json.loads((_active_dir(repo) / "agent_mix.json").read_text(encoding="utf-8"))
    assert mix["rolling"] == {"claude": 0, "codex": 1}


def test_agent_turn_scrubs_private_field_values_from_artifact(monkeypatch, tmp_path: Path) -> None:
    # Common-path privacy protection: the artifact writer redacts private field values
    # in place (ADR 0005), so a leaked doc_id never persists — the turn still executes.
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "feat/issue-1590")
    leaky = {
        "verdict": "approved",
        "summary": "leaked doc_id: SECRET-XYZ from the corpus",
        "findings": [],
        "next_steps": [],
    }

    result = agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        agent="claude",
        task_id="T-2026-9999",
        execute=True,
        claude_runner=_claude_lane_runner(leaky),
        repo_root=repo,
    )

    assert result.decision == "executed"
    artifact_text = result.artifact_path.read_text(encoding="utf-8")
    assert "SECRET-XYZ" not in artifact_text  # raw value never persisted
    assert "[redacted-private-value]" in artifact_text
    assert json.loads(artifact_text)["privacy_scrubbed"] is True


def test_agent_turn_failclosed_blocks_when_audit_finds_leak(monkeypatch, tmp_path: Path) -> None:
    # Fail-closed secondary net: if the privacy audit flags anything that slipped past the
    # proactive scrub, the turn is blocked, no Work Unit is recorded, and the heartbeat is
    # non-pass — never a pass-class gate on leaked output.
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "feat/issue-1590")
    monkeypatch.setattr(
        agent_loop,
        "audit_privacy_output",
        lambda *a, **k: [agent_loop.PrivacyFinding(path="artifact", issue="absolute local path")],
    )
    core = {"verdict": "approved", "summary": "clean summary", "findings": [], "next_steps": []}

    result = agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        agent="claude",
        task_id="T-2026-9999",
        execute=True,
        claude_runner=_claude_lane_runner(core),
        repo_root=repo,
    )

    assert result.decision == "blocked"
    assert result.verdict == "blocked"
    assert result.blockers  # the privacy issue surfaced as a blocker
    artifact = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact["privacy_scrubbed"] is False
    assert artifact["wu"] == 0
    assert artifact["findings"] == []
    # No Work Unit recorded; heartbeat marks the session blocked.
    mix_path = _active_dir(repo) / "agent_mix.json"
    if mix_path.exists():
        assert json.loads(mix_path.read_text(encoding="utf-8"))["rolling"] == {"claude": 0, "codex": 0}
    registry = json.loads((_active_dir(repo) / "session_registry.json").read_text(encoding="utf-8"))
    session = next(item for item in registry["sessions"] if item["session_id"] == "reviewer")
    assert session["status"] == "blocked"


def test_choose_agent_capability_then_mix_debt() -> None:
    policy = agent_loop._parse_agent_mix(None)
    # Capability prior: review -> codex, planning -> claude when rolling is empty.
    assert agent_loop.choose_agent("Reviewer", agent_mix=policy, rolling={}) == "codex"
    assert agent_loop.choose_agent("Planner / Issue Triage", agent_mix=policy, rolling={}) == "claude"
    # Mix debt overrides the capability prior once codex is over-used past target share.
    assert agent_loop.choose_agent("Reviewer", agent_mix=policy, rolling={"claude": 0, "codex": 10}) == "claude"


def test_agent_mix_report_flags_skew_and_recommends_underused(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    active = _active_dir(repo)
    active.mkdir(parents=True, exist_ok=True)
    (active / "agent_mix.json").write_text(
        json.dumps(
            {
                "policy": agent_loop._parse_agent_mix(None),
                "rolling": {"claude": 5, "codex": 0},
                "ledger": [],
            }
        ),
        encoding="utf-8",
    )

    out_path, summary = agent_loop.write_agent_mix_report(repo_root=repo)

    assert summary["skew_wu"] == 5
    assert summary["within_tolerance"] is False
    assert summary["recommended_next_agent"] == "codex"
    assert "REBALANCE" in out_path.read_text(encoding="utf-8")


def test_agent_turn_dry_run_plans_without_writing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    result = agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        task_id="T-2026-9999",
        execute=False,
        repo_root=repo,
    )

    assert result.decision == "planned"
    assert result.agent == "codex"  # capability prior; no lane invoked in dry-run
    assert result.artifact_path is None
    assert not (_active_dir(repo) / "artifacts").exists()


def test_agent_turn_rejects_non_review_roles(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    for role in ("Orchestrator", "Implementer"):
        with pytest.raises(ValueError):
            agent_loop.write_agent_turn(session_id="x", role=role, repo_root=repo)


def test_agent_turn_wu_accumulates_per_agent(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "feat/issue-1590")
    companion = tmp_path / "codex-companion.mjs"
    companion.write_text("// stub", encoding="utf-8")
    monkeypatch.setenv("CODEX_COMPANION", str(companion))
    clean = {"verdict": "clear", "summary": "ok", "findings": [], "next_steps": []}

    for _ in range(2):
        agent_loop.write_agent_turn(
            session_id="eval-auditor",
            role="Eval / Claim / Privacy Auditor",
            agent="claude",
            task_id="T-2026-9999",
            execute=True,
            claude_runner=_claude_lane_runner(clean),
            repo_root=repo,
        )
    agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        agent="codex",
        task_id="T-2026-9999",
        execute=True,
        codex_runner=_codex_lane_runner({"verdict": "approve", "summary": "ok", "findings": [], "next_steps": []}),
        repo_root=repo,
    )

    mix = json.loads((_active_dir(repo) / "agent_mix.json").read_text(encoding="utf-8"))
    assert mix["rolling"] == {"claude": 2, "codex": 1}
    assert len(mix["ledger"]) == 3


def test_agent_turn_cli_accepts_and_rejects_agent() -> None:
    parser = agent_loop.build_parser()
    args = parser.parse_args(["agent-turn", "--session-id", "reviewer", "--role", "Reviewer", "--agent", "codex"])
    assert args.agent == "codex"
    assert args.execute is False
    exec_args = parser.parse_args(["agent-turn", "--session-id", "reviewer", "--role", "Reviewer", "--execute"])
    assert exec_args.execute is True
    with pytest.raises(SystemExit):
        parser.parse_args(["agent-turn", "--session-id", "reviewer", "--role", "Reviewer", "--agent", "gpt"])
    parser.parse_args(["agent-mix-report"])  # parser exists


def _write_expanded_active_runner_fixture(repo: Path) -> Path:
    active = _active_dir(repo)
    assignments = active / "assignments"
    assignments.mkdir(parents=True, exist_ok=True)
    sessions = []
    for session_id, role in agent_loop.ACTIVE_TOPOLOGY_ROLES["expanded-eight"]:
        sessions.append(
            {
                "session_id": session_id,
                "role": role,
                "status": "idle",
                "last_heartbeat": "2999-01-01T00:00:00Z",
                "lanes": {"claude": {"status": "idle"}, "codex": {"status": "idle"}},
                "write_lease_owner": role == "Implementer",
                "ship_gate": agent_loop._active_ship_gate(role, topology="expanded-eight"),
            }
        )
        (assignments / f"{session_id}.md").write_text(
            f"# Active Assignment: {role}\n\n- Session: `{session_id}`\n- Next command: `status`\n",
            encoding="utf-8",
        )
    (active / "session_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "topology": "expanded-eight",
                "gate_policy": "conservative",
                "agent_mix": agent_loop._parse_agent_mix(None),
                "sessions": sessions,
            }
        ),
        encoding="utf-8",
    )
    (active / "leases.json").write_text(
        json.dumps({"schema_version": 1, "leases": [{"lease_id": "lease", "active_agent": None}]}),
        encoding="utf-8",
    )
    return active


def _chatgpt_auth_runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
    return subprocess.CompletedProcess(cmd, 0, stdout="Logged in using ChatGPT\n", stderr="")


def test_active_codex_runner_dry_run_renders_eight_commands_without_spawning(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    active = _write_expanded_active_runner_fixture(repo)

    result = agent_loop.write_active_codex_runner(repo_root=repo)

    assert result.decision == "planned"
    assert len(result.sessions) == 8
    assert not (active / "codex_runs").exists()
    assert all("codex exec --cd . --sandbox read-only --json" in item["command"] for item in result.sessions)
    report = result.report_path.read_text(encoding="utf-8")
    state = result.state_path.read_text(encoding="utf-8")
    assert str(repo) not in report
    assert str(repo) not in state
    assert "role-dispatch" not in report  # runner is a separate spawn surface, not the report-only dispatcher.


def test_eval_claim_privacy_prompt_excludes_own_live_logs(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    assignment = repo / "reports" / "agent_loop" / "active" / "assignments" / "eval-claim-privacy-auditor.md"
    assignment.parent.mkdir(parents=True, exist_ok=True)
    assignment.write_text("# Assignment\n", encoding="utf-8")

    prompt = agent_loop._render_active_codex_prompt(
        session_id="eval-claim-privacy-auditor",
        role="Eval / Claim / Privacy Auditor",
        assignment_path=assignment,
        repo_root=repo,
    )

    assert "exclude this session's own active stdout/stderr files" in prompt


def test_active_codex_runner_execute_spawns_agentic_processes_and_preserves_lease(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    active = _write_expanded_active_runner_fixture(repo)
    calls: list[dict[str, object]] = []
    prompts: list[str] = []

    class DummyStdin:
        def write(self, text: str) -> None:
            prompts.append(text)

        def close(self) -> None:
            pass

    class DummyProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self.stdin = DummyStdin()

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "cmd": list(cmd),
                "cwd": kwargs["cwd"],
                "stdin": kwargs["stdin"],
                "stdout": kwargs["stdout"],
                "stderr_name": getattr(kwargs["stderr"], "name", None),
                "text": kwargs["text"],
            }
        )
        return DummyProc(7000 + len(calls))

    result = agent_loop.write_active_codex_runner(
        execute=True,
        repo_root=repo,
        popen_factory=fake_popen,
        which_func=lambda exe: "/opt/codex/bin/codex",
        auth_runner=_chatgpt_auth_runner,
    )

    assert result.decision == "completed"
    assert len(calls) == 7
    assert len(prompts) == 7
    for call in calls:
        cmd = call["cmd"]
        assert cmd[:4] == ["/opt/codex/bin/codex", "exec", "--cd", "."]
        assert "--sandbox" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"
        assert "--json" in cmd
        assert "--output-last-message" in cmd
        assert str(cmd[cmd.index("--output-last-message") + 1]).startswith("reports/agent_loop/active/codex_runs/")
        assert cmd[-1] == "-"
        assert call["cwd"] == repo
        assert call["stdin"] == subprocess.PIPE
        assert call["stdout"] == subprocess.PIPE
        assert call["stderr_name"] is not None
        assert call["stderr_name"].endswith("/stderr.log")
        assert call["text"] is True
    assert (active / "codex_runs" / "reviewer" / "prompt.md").exists()
    leases = json.loads((active / "leases.json").read_text(encoding="utf-8"))
    assert leases["leases"][0]["active_agent"] is None
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert {item["status"] for item in state["sessions"]} == {"completed"}
    assert {item["returncode"] for item in state["sessions"]} == {0}
    assert all(item["pid"] for item in state["sessions"] if item["session_id"] != "eval-claim-privacy-auditor")
    eval_session = next(item for item in state["sessions"] if item["session_id"] == "eval-claim-privacy-auditor")
    assert eval_session["pid"] is None
    assert eval_session["deterministic_gate"] == "eval-claim-privacy-post-redaction"
    assert str(repo) not in result.state_path.read_text(encoding="utf-8")


def test_active_codex_runner_records_passing_gate_heartbeats(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    active = _write_expanded_active_runner_fixture(repo)

    class DummyProc:
        def __init__(self, pid: int, last_message: Path) -> None:
            self.pid = pid
            self.stdin = None
            self.last_message = last_message

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            self.last_message.parent.mkdir(parents=True, exist_ok=True)
            if self.last_message.parent.name == "eval-claim-privacy-auditor":
                self.last_message.write_text("No explicit verdict\nPath: /Users/example/private/path\n", encoding="utf-8")
            else:
                self.last_message.write_text("Gate verdict: pass\nPath: /Users/example/private/path\n", encoding="utf-8")
            return 0

    def fake_popen(cmd, **kwargs):  # type: ignore[no-untyped-def]
        last = repo / cmd[cmd.index("--output-last-message") + 1]
        return DummyProc(7100, last)

    result = agent_loop.write_active_codex_runner(
        execute=True,
        record_gate_heartbeats=True,
        repo_root=repo,
        popen_factory=fake_popen,
        which_func=lambda exe: "/opt/codex/bin/codex",
        auth_runner=_chatgpt_auth_runner,
    )

    registry = json.loads((active / "session_registry.json").read_text(encoding="utf-8"))
    by_id = {item["session_id"]: item for item in registry["sessions"]}

    assert result.decision == "completed"
    assert by_id["reviewer"]["status"] == "passed"
    assert by_id["ci-regression-auditor"]["status"] == "passed"
    assert by_id["eval-claim-privacy-auditor"]["status"] == "clear"
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    eval_session = next(item for item in state["sessions"] if item["session_id"] == "eval-claim-privacy-auditor")
    assert eval_session["heartbeat_source"] == "last-message-verdict"
    assert "[redacted-local-path]" in (active / "codex_runs" / "reviewer" / "last_message.md").read_text(encoding="utf-8")
    assert not agent_loop.audit_privacy_output(active / "codex_runs", out_path=None, repo_root=repo)
    assert any("redacted" in warning for warning in result.warnings)
    assert "Gate Heartbeats" in result.report_path.read_text(encoding="utf-8")


def test_active_codex_runner_does_not_override_explicit_blocked_gate(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    active = _write_expanded_active_runner_fixture(repo)
    last_message = active / "codex_runs" / "eval-claim-privacy-auditor" / "last_message.md"
    last_message.parent.mkdir(parents=True, exist_ok=True)
    last_message.write_text("Gate verdict: blocked\n", encoding="utf-8")
    sessions = [
        {
            "session_id": "eval-claim-privacy-auditor",
            "role": "Eval / Claim / Privacy Auditor",
            "ship_gate": "blocking",
            "status": "completed",
            "last_message": "reports/agent_loop/active/codex_runs/eval-claim-privacy-auditor/last_message.md",
        }
    ]

    events, warnings = agent_loop._record_codex_runner_gate_heartbeats(
        sessions=sessions,
        registry=active / "session_registry.json",
        events=active / "events.jsonl",
        repo_root=repo,
    )

    registry = json.loads((active / "session_registry.json").read_text(encoding="utf-8"))
    eval_session = next(item for item in registry["sessions"] if item["session_id"] == "eval-claim-privacy-auditor")
    assert events == []
    assert eval_session["status"] == "idle"
    assert any("reported non-passing gate verdict: blocked" in warning for warning in warnings)


def test_active_codex_runner_execute_fails_closed_without_codex(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)
    calls: list[list[str]] = []

    result = agent_loop.write_active_codex_runner(
        execute=True,
        repo_root=repo,
        popen_factory=lambda cmd, **kwargs: calls.append(list(cmd)),  # type: ignore[arg-type]
        which_func=lambda exe: None,
    )

    assert result.decision == "blocked"
    assert any("codex executable not found" in blocker for blocker in result.blockers)
    assert calls == []


def test_active_codex_runner_accepts_chatgpt_login_on_stderr(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)
    calls: list[list[str]] = []

    class DummyProc:
        stdin = None
        pid = 7100

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

    def stderr_chatgpt_auth(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="Logged in using ChatGPT\n")

    result = agent_loop.write_active_codex_runner(
        execute=True,
        repo_root=repo,
        popen_factory=lambda cmd, **kwargs: calls.append(list(cmd)) or DummyProc(),  # type: ignore[arg-type]
        which_func=lambda exe: "/bin/codex",
        auth_runner=stderr_chatgpt_auth,
    )

    assert result.decision == "completed"
    assert calls
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert state["auth_status"] == "Logged in using ChatGPT"
    assert not any("requires ChatGPT login" in blocker for blocker in result.blockers)


def test_active_codex_runner_requires_chatgpt_login_by_default(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)
    calls: list[list[str]] = []

    def api_key_auth(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, 0, stdout="Logged in using API key\n", stderr="")

    result = agent_loop.write_active_codex_runner(
        execute=True,
        repo_root=repo,
        popen_factory=lambda cmd, **kwargs: calls.append(list(cmd)),  # type: ignore[arg-type]
        which_func=lambda exe: "/bin/codex",
        auth_runner=api_key_auth,
    )

    assert result.decision == "blocked"
    assert any("requires ChatGPT login" in blocker for blocker in result.blockers)
    assert calls == []
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert state["auth_mode"] == "chatgpt"
    assert state["auth_status"] == "Logged in using API key"


def test_active_codex_runner_blocks_when_login_status_fails(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)

    def failed_auth(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in")

    result = agent_loop.write_active_codex_runner(
        execute=True,
        repo_root=repo,
        which_func=lambda exe: "/bin/codex",
        auth_runner=failed_auth,
    )

    assert result.decision == "blocked"
    assert any("codex login status failed" in blocker for blocker in result.blockers)


def test_active_codex_runner_auth_mode_any_skips_auth_source_guard(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_expanded_active_runner_fixture(repo)
    calls: list[list[str]] = []
    auth_calls: list[list[str]] = []

    class DummyProc:
        stdin = None
        pid = 7200

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

    result = agent_loop.write_active_codex_runner(
        execute=True,
        auth_mode="any",
        repo_root=repo,
        popen_factory=lambda cmd, **kwargs: calls.append(list(cmd)) or DummyProc(),  # type: ignore[arg-type]
        which_func=lambda exe: "/bin/codex",
        auth_runner=lambda cmd, **kwargs: auth_calls.append(list(cmd)),  # type: ignore[arg-type]
    )

    assert result.decision == "completed"
    assert calls
    assert auth_calls == []
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    assert state["auth_status"] == "skipped (auth-mode any)"


def test_active_codex_runner_fails_closed_on_missing_registry_or_assignment(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)

    missing_registry = agent_loop.write_active_codex_runner(execute=True, repo_root=repo, which_func=lambda exe: "/bin/codex")

    assert missing_registry.decision == "blocked"
    assert any("registry is missing" in blocker for blocker in missing_registry.blockers)

    active = _write_expanded_active_runner_fixture(repo)
    (active / "assignments" / "reviewer.md").unlink()

    missing_assignment = agent_loop.write_active_codex_runner(
        execute=True,
        sessions="reviewer",
        repo_root=repo,
        which_func=lambda exe: "/bin/codex",
    )

    assert missing_assignment.decision == "blocked"
    assert any("assignment missing for session reviewer" in blocker for blocker in missing_assignment.blockers)


def test_active_codex_runner_cli_accepts_execute_and_session_filter() -> None:
    parser = agent_loop.build_parser()
    args = parser.parse_args([
        "active-codex-runner",
        "--execute",
        "--sessions",
        "reviewer,ci-regression-auditor",
        "--record-gate-heartbeats",
    ])
    assert args.execute is True
    assert args.sessions == "reviewer,ci-regression-auditor"
    assert args.auth_mode == "chatgpt"
    assert args.record_gate_heartbeats is True


def test_make_active_start_spawns_codex_runner_by_default() -> None:
    result = subprocess.run(
        ["make", "-n", "agent-loop-active-start"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "scripts/agent_loop.py active-start" in result.stdout
    assert 'make agent-loop-active-codex-runner ACTIVE_CODEX_EXECUTE="1"' in result.stdout
    assert "scripts/agent_loop.py active-codex-runner" in result.stdout
    assert "--execute" in result.stdout
    assert '--auth-mode "chatgpt"' in result.stdout
    assert "--record-gate-heartbeats" in result.stdout


def test_make_active_start_can_disable_runner_and_has_korean_alias() -> None:
    no_runner = subprocess.run(
        ["make", "-n", "agent-loop-active-start", "ACTIVE_START_RUNNER=0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    alias = subprocess.run(
        ["make", "-n", "시작"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert no_runner.returncode == 0
    assert "scripts/agent_loop.py active-start" in no_runner.stdout
    assert "agent-loop-active-codex-runner" not in no_runner.stdout
    assert alias.returncode == 0
    assert 'make agent-loop-active-codex-runner ACTIVE_CODEX_EXECUTE="1"' in alias.stdout
    assert '--auth-mode "chatgpt"' in alias.stdout


def test_active_auto_loop_completes_task_and_picks_next_from_state(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-1001", title="First task")
    queue = repo / "tasks" / "queue.md"
    queue.write_text(
        queue.read_text(encoding="utf-8")
        + """

## T-2026-1002 — Second task

- ID: T-2026-1002
- Title: Second task
- Status: ready
- Owner role: Implementer -> Reviewer

### Goal

Run after the first task completes.

### Acceptance Criteria

- [ ] Selected after T-2026-1001.

### Validation Commands

```bash
git diff --check
```
""",
        encoding="utf-8",
    )
    _patch_active_loop_clear(monkeypatch)
    active_dir = repo / "reports" / "agent_loop" / "active"

    def fake_runner(**kwargs):  # type: ignore[no-untyped-def]
        report = active_dir / "codex_runner.md"
        state = active_dir / "codex_runner_state.json"
        runs = active_dir / "codex_runs"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# runner\n", encoding="utf-8")
        state.write_text("{}\n", encoding="utf-8")
        return agent_loop.ActiveCodexRunnerResult(report, state, runs, "completed", (), (), ())

    def fake_gate(*, task_id, **kwargs):  # type: ignore[no-untyped-def]
        path = active_dir / "gate_evidence" / task_id / "evidence.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path, {"ready": True, "privacy_clean": True}

    def fake_ship(**kwargs):  # type: ignore[no-untyped-def]
        report = active_dir / "active_loop.md"
        registry = active_dir / "session_registry.json"
        leases = active_dir / "leases.json"
        events = active_dir / "events.jsonl"
        assignments = active_dir / "assignments"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# shipped\n", encoding="utf-8")
        return agent_loop.ActiveLoopResult(registry, leases, events, assignments, report, "executed", (), ())

    monkeypatch.setattr(agent_loop, "write_active_codex_runner", fake_runner)
    monkeypatch.setattr(agent_loop, "write_active_gate_evidence", fake_gate)
    monkeypatch.setattr(agent_loop, "write_active_loop", fake_ship)

    first = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=True,
        execute_ship=True,
        repo_root=repo,
    )
    second = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo,
    )

    assert first.completed_task_ids == ("T-2026-1001",)
    assert first.next_task_id == "T-2026-1002"
    assert first.decision == "limit-reached"
    assert second.cycles[0]["task_id"] == "T-2026-1002"
    state = json.loads((active_dir / "auto_loop_state.json").read_text(encoding="utf-8"))
    assert state["completed_task_ids"] == ["T-2026-1001"]


def test_active_auto_loop_does_not_mark_read_only_cycle_completed(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, task_id="T-2026-1001", title="Read-only task")
    _patch_active_loop_clear(monkeypatch)
    active_dir = repo / "reports" / "agent_loop" / "active"

    def fake_runner(**kwargs):  # type: ignore[no-untyped-def]
        report = active_dir / "codex_runner.md"
        state = active_dir / "codex_runner_state.json"
        runs = active_dir / "codex_runs"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# runner\n", encoding="utf-8")
        state.write_text("{}\n", encoding="utf-8")
        return agent_loop.ActiveCodexRunnerResult(report, state, runs, "planned", (), (), ("dry-run",))

    def fake_gate(*, task_id, **kwargs):  # type: ignore[no-untyped-def]
        path = active_dir / "gate_evidence" / task_id / "evidence.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path, {"ready": True, "privacy_clean": True}

    monkeypatch.setattr(agent_loop, "write_active_codex_runner", fake_runner)
    monkeypatch.setattr(agent_loop, "write_active_gate_evidence", fake_gate)

    result = agent_loop.write_active_auto_loop(
        max_iterations=1,
        execute_runner=False,
        execute_ship=False,
        repo_root=repo,
    )

    assert result.decision == "planned"
    assert result.completed_task_ids == ()
    assert result.next_task_id == "T-2026-1001"
    assert any("ship execution disabled" in warning for warning in result.warnings)
    assert result.cycles[0]["completed"] is False


def test_codex_lane_adapter_maps_verdict_severity_and_errors(monkeypatch, tmp_path: Path) -> None:
    from scripts import agent_loop_codex_turn as cx

    monkeypatch.delenv("CODEX_COMPANION", raising=False)
    companion = tmp_path / "codex-companion.mjs"
    companion.write_text("// stub", encoding="utf-8")

    def ok_runner(comp, base, scope, focus):
        payload = {
            "result": {
                "verdict": "needs-attention",
                "summary": "found issues",
                "findings": [
                    {"severity": "critical", "title": "C", "body": "b", "file": "rag_core.py", "line_start": 10, "line_end": 12},
                    {"severity": "medium", "title": "M"},
                    {"severity": "low", "title": "L"},
                ],
                "next_steps": ["fix C"],
            }
        }
        return subprocess.CompletedProcess([str(comp)], 0, stdout=json.dumps(payload), stderr="")

    core = cx.run_turn(companion_path=str(companion), runner=ok_runner)
    assert core["verdict"] == "needs-attention"
    assert [f["severity"] for f in core["findings"]] == ["blocker", "warning", "info"]
    assert "[rag_core.py:10-12]" in core["findings"][0]["body"]  # file:line folded into body
    assert core["next_steps"] == ["fix C"]

    def approve_runner(comp, base, scope, focus):
        return subprocess.CompletedProcess(
            [str(comp)], 0, stdout=json.dumps({"result": {"verdict": "approve", "summary": "ok"}}), stderr=""
        )

    assert cx.run_turn(companion_path=str(companion), runner=approve_runner)["verdict"] == "approved"

    # Error paths never raise: missing companion, non-zero rc, non-JSON.
    assert cx.run_turn(companion_path=None, home=tmp_path)["verdict"] == "error"

    def fail_runner(comp, base, scope, focus):
        return subprocess.CompletedProcess([str(comp)], 2, stdout="", stderr="boom")

    assert cx.run_turn(companion_path=str(companion), runner=fail_runner)["verdict"] == "error"

    def junk_runner(comp, base, scope, focus):
        return subprocess.CompletedProcess([str(comp)], 0, stdout="not json", stderr="")

    assert cx.run_turn(companion_path=str(companion), runner=junk_runner)["verdict"] == "error"


def test_claude_lane_adapter_command_and_core(tmp_path: Path) -> None:
    from scripts import agent_loop_claude_turn as cl

    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    cmd = cl.build_command(prompt="review", schema_path=schema)
    assert cmd[:3] == ["claude", "-p", "review"]
    # F4: no --permission-mode plan (headless plan-mode tool use crashes the API).
    assert "--permission-mode" not in cmd
    # F2: --json-schema must carry the inline schema CONTENT, not the file path.
    assert cmd[cmd.index("--json-schema") + 1] == "{}"
    assert str(schema) not in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1]
    disallowed = cmd[cmd.index("--disallowedTools") + 1]
    assert "Read" in allowed
    assert "Edit" in disallowed and "Bash(git push:*)" in disallowed

    def dict_runner(c):
        payload = {"result": {"verdict": "clear", "summary": "ok", "findings": [], "next_steps": []}}
        return subprocess.CompletedProcess(c, 0, stdout=json.dumps(payload), stderr="")

    assert cl.run_turn(prompt="x", schema_path=schema, runner=dict_runner)["verdict"] == "clear"

    def str_runner(c):
        inner = json.dumps({"verdict": "needs-attention", "summary": "s", "findings": [{"severity": "warning", "title": "T"}]})
        return subprocess.CompletedProcess(c, 0, stdout=json.dumps({"result": inner}), stderr="")

    core = cl.run_turn(prompt="x", schema_path=schema, runner=str_runner)
    assert core["verdict"] == "needs-attention"
    assert core["findings"][0]["severity"] == "warning"

    # F3: claude 2.1.3 wraps the result JSON in a ```json code fence; _extract_core strips it.
    def fenced_runner(c):
        inner = "```json\n" + json.dumps({"verdict": "approved", "summary": "ok", "findings": []}) + "\n```"
        return subprocess.CompletedProcess(c, 0, stdout=json.dumps({"result": inner}), stderr="")

    assert cl.run_turn(prompt="x", schema_path=schema, runner=fenced_runner)["verdict"] == "approved"

    def fail_runner(c):
        return subprocess.CompletedProcess(c, 1, stdout="", stderr="err")

    assert cl.run_turn(prompt="x", schema_path=schema, runner=fail_runner)["verdict"] == "error"

    def junk_runner(c):
        return subprocess.CompletedProcess(c, 0, stdout="<<not json>>", stderr="")

    assert cl.run_turn(prompt="x", schema_path=schema, runner=junk_runner)["verdict"] == "error"


def test_claude_lane_adapter_omits_schema_when_unreadable(tmp_path: Path) -> None:
    from scripts import agent_loop_claude_turn as cl

    missing = tmp_path / "nope.json"  # does not exist
    cmd = cl.build_command(prompt="review", schema_path=missing)
    # F2 safety: unreadable schema -> omit --json-schema so the lane still runs.
    assert "--json-schema" not in cmd
    assert cmd[:5] == ["claude", "-p", "review", "--output-format", "json"]


def test_agent_turn_redacts_real100_path_and_proceeds(monkeypatch, tmp_path: Path) -> None:
    # F1: a code review legitimately mentioning a public repo path (reports/real100/...)
    # must be redacted-and-proceeded, NOT false-positive-blocked.
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(agent_loop, "_current_branch", lambda repo_root: "fix/issue-1598")
    core = {
        "verdict": "approved",
        "summary": "Baseline lives in reports/real100/baseline.aggregate.json; the change looks safe.",
        "findings": [],
        "next_steps": [],
    }

    result = agent_loop.write_agent_turn(
        session_id="reviewer",
        role="Reviewer",
        agent="claude",
        task_id="T-2026-9999",
        execute=True,
        claude_runner=_claude_lane_runner(core),
        repo_root=repo,
    )

    assert result.decision == "executed"  # redact-and-proceed, not blocked
    assert result.verdict == "approved"
    text = result.artifact_path.read_text(encoding="utf-8")
    assert "reports/real100/[redacted-private-artifact]" in text
    assert "baseline.aggregate.json" not in text  # raw artifact name masked
    assert json.loads(text)["privacy_scrubbed"] is True
    # WU recorded + heartbeat reflects the pass-class verdict (not blocked).
    mix = json.loads((_active_dir(repo) / "agent_mix.json").read_text(encoding="utf-8"))
    assert mix["rolling"] == {"claude": 1, "codex": 0}
    registry = json.loads((_active_dir(repo) / "session_registry.json").read_text(encoding="utf-8"))
    session = next(item for item in registry["sessions"] if item["session_id"] == "reviewer")
    assert session["status"] == "approved"


# --- Phase 3 PR-A: write-lease active_agent borrow (issue #1604) ---


def _seed_write_lease(repo: Path, *, lease_id: str = "impl", active_agent=None, claimed_files=None) -> Path:
    active = repo / "reports" / "agent_loop" / "active"
    active.mkdir(parents=True, exist_ok=True)
    path = active / "leases.json"
    lease = {
        "lease_id": lease_id,
        "status": "active",
        "lease_type": "write",
        "active_agent": active_agent,
        "owner_session": "implementer",
    }
    if claimed_files is not None:
        lease["claimed_files"] = list(claimed_files)
    path.write_text(json.dumps({"schema_version": 1, "leases": [lease]}), encoding="utf-8")
    return path


def test_active_agent_borrow_is_mutually_exclusive(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_write_lease(repo)
    ok, _, lid = agent_loop.acquire_active_agent(agent="codex", repo_root=repo)
    assert ok is True and lid == "impl"
    # claude is blocked while codex holds the lease (mutual exclusion).
    ok2, msg2, _ = agent_loop.acquire_active_agent(agent="claude", repo_root=repo)
    assert ok2 is False and "held by codex" in msg2
    # re-acquire by the same agent is idempotent.
    assert agent_loop.acquire_active_agent(agent="codex", repo_root=repo)[0] is True
    leases = json.loads((repo / "reports" / "agent_loop" / "active" / "leases.json").read_text(encoding="utf-8"))
    assert leases["leases"][0]["active_agent"] == "codex"
    # release by codex frees it; then claude can acquire.
    assert agent_loop.release_active_agent(agent="codex", repo_root=repo)[0] is True
    assert agent_loop.acquire_active_agent(agent="claude", repo_root=repo)[0] is True
    # codex cannot release a lease claude holds.
    okr, msgr = agent_loop.release_active_agent(agent="codex", repo_root=repo)
    assert okr is False and "held by claude" in msgr


def test_acquire_active_agent_without_write_lease_fails(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    ok, msg, lid = agent_loop.acquire_active_agent(agent="codex", repo_root=repo)
    assert ok is False and lid is None and "no active write lease" in msg


def test_acquire_active_agent_rejects_unknown_agent(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_write_lease(repo)
    with pytest.raises(ValueError):
        agent_loop.acquire_active_agent(agent="gpt", repo_root=repo)


# --- Phase 3 PR-A: scratch worktree helpers + active-codex-runner patch mode (issue #1604) ---


class _FakeCodexProc:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode = 0
        self.stdin = self
        self.written: list[str] = []

    def write(self, s: str) -> None:
        self.written.append(s)

    def close(self) -> None:
        pass

    def wait(self, timeout=None) -> int:
        return 0


def _fake_git_runner(diff_stdout: str = ""):
    calls: list[list[str]] = []

    def run(cmd):
        calls.append(cmd)
        if "diff" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=diff_stdout, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _seed_patch_registry(repo: Path, *, task: str = "T-2026-0042") -> None:
    active = repo / "reports" / "agent_loop" / "active"
    active.mkdir(parents=True, exist_ok=True)
    (active / "session_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "topology": "four-role",
                "gate_policy": "conservative",
                "agent_mix": agent_loop._parse_agent_mix(None),
                "sessions": [
                    {
                        "session_id": "implementer",
                        "role": "Implementer",
                        "status": "running",
                        "task_id": task,
                        "lanes": agent_loop._build_active_lanes(None),
                        "write_lease_owner": True,
                        "ship_gate": "lease-owner",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _seed_patch_assignment(repo: Path, *, session: str = "implementer", text: str = "Add a one-line docstring to foo.py.") -> Path:
    adir = repo / "reports" / "agent_loop" / "active" / "assignments"
    adir.mkdir(parents=True, exist_ok=True)
    path = adir / f"{session}.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_scratch_worktree_paths_naming(tmp_path: Path) -> None:
    path, branch = agent_loop._scratch_worktree_paths("T-2026-0042", "codex", repo_root=tmp_path)
    assert path == tmp_path / ".claude" / "worktrees" / "T-2026-0042-codex"
    assert branch == "agent/T-2026-0042/codex-scratch"
    with pytest.raises(ValueError):
        agent_loop._scratch_worktree_paths("nope", "codex", repo_root=tmp_path)
    with pytest.raises(ValueError):
        agent_loop._scratch_worktree_paths("T-2026-0042", "gpt", repo_root=tmp_path)


def test_create_and_teardown_scratch_worktree(tmp_path: Path) -> None:
    runner = _fake_git_runner()
    path, branch, blockers = agent_loop.create_scratch_worktree(
        "T-2026-0042", "codex", base="origin/main", repo_root=tmp_path, runner=runner
    )
    assert blockers == []
    assert branch == "agent/T-2026-0042/codex-scratch"
    assert runner.calls[0] == ["git", "-C", str(tmp_path), "worktree", "add", "-b", branch, str(path), "origin/main"]
    warnings = agent_loop.teardown_scratch_worktree("T-2026-0042", "codex", repo_root=tmp_path, runner=runner)
    assert warnings == []
    assert runner.calls[1] == ["git", "-C", str(tmp_path), "worktree", "remove", "--force", str(path)]
    assert runner.calls[2] == ["git", "-C", str(tmp_path), "branch", "-D", branch]


def test_create_scratch_worktree_surfaces_failure(tmp_path: Path) -> None:
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fatal: already exists")

    _, _, blockers = agent_loop.create_scratch_worktree("T-2026-0042", "codex", repo_root=tmp_path, runner=runner)
    assert blockers and "already exists" in blockers[0]


def test_codex_runner_patch_mode_dry_run_plans_without_borrow(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo)
    _seed_patch_assignment(repo)

    result = agent_loop.write_active_codex_runner(mode="patch", task_id="T-2026-0042", repo_root=repo)

    assert result.decision == "planned"
    leases = json.loads((repo / "reports" / "agent_loop" / "active" / "leases.json").read_text(encoding="utf-8"))
    assert leases["leases"][0]["active_agent"] is None  # dry-run borrows nothing
    assert not (repo / "reports" / "agent_loop" / "active" / "patch_runs").exists()


def test_codex_runner_patch_mode_execute_captures_patch_and_releases_lease(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo)
    _seed_patch_assignment(repo)
    diff = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1,2 @@\n line\n+new line\n"
    git_runner = _fake_git_runner(diff_stdout=diff)

    result = agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: _FakeCodexProc(),
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=_chatgpt_auth_runner,
        git_runner=git_runner,
    )

    assert result.decision == "completed"
    artifact = json.loads(
        (repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "patch_artifact.json").read_text(encoding="utf-8")
    )
    assert artifact["verdict"] == "proposed"
    assert artifact["agent"] == "codex"
    assert artifact["files"] == ["foo.py"]
    assert artifact["wu"] == 1
    assert artifact["diff"] == diff
    cmds = [" ".join(c) for c in git_runner.calls]
    assert any("worktree add -b agent/T-2026-0042/codex-scratch" in c for c in cmds)
    assert any("worktree remove --force" in c for c in cmds)
    # write lease released back to free after the run.
    leases = json.loads((repo / "reports" / "agent_loop" / "active" / "leases.json").read_text(encoding="utf-8"))
    assert leases["leases"][0]["active_agent"] is None


def test_codex_runner_patch_mode_requires_chatgpt_login(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo)
    _seed_patch_assignment(repo)
    calls: list[list[str]] = []

    def api_key_auth(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, 0, stdout="Logged in using API key\n", stderr="")

    result = agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: calls.append(list(cmd)),  # type: ignore[arg-type]
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=api_key_auth,
        git_runner=_fake_git_runner(diff_stdout="diff --git a/foo.py b/foo.py\n+x\n"),
    )

    assert result.decision == "blocked"
    assert any("requires ChatGPT login" in blocker for blocker in result.blockers)
    assert calls == []
    assert not (repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "patch_artifact.json").exists()


def test_codex_runner_patch_mode_redacts_private_path_in_diff(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo)
    _seed_patch_assignment(repo)
    diff = "diff --git a/x.py b/x.py\n+# see reports/real100/baseline.aggregate.json\n"

    result = agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: _FakeCodexProc(),
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=_chatgpt_auth_runner,
        git_runner=_fake_git_runner(diff_stdout=diff),
    )

    artifact_text = (
        repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "patch_artifact.json"
    ).read_text(encoding="utf-8")
    assert "reports/real100/[redacted-private-artifact]" in artifact_text  # redact-and-proceed
    assert "baseline.aggregate.json" not in artifact_text
    assert result.decision == "completed"


def test_codex_runner_patch_mode_blocks_without_assignment(tmp_path: Path) -> None:
    # Fail-closed (#1610): never run a workspace-write codex lane without a concrete assignment.
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo)
    # no assignment seeded

    result = agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: _FakeCodexProc(),
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=_chatgpt_auth_runner,
        git_runner=_fake_git_runner(diff_stdout="diff --git a/foo.py b/foo.py\n+x\n"),
    )

    assert result.decision == "blocked"
    assert any("assignment" in b for b in result.blockers)
    leases = json.loads((repo / "reports" / "agent_loop" / "active" / "leases.json").read_text(encoding="utf-8"))
    assert leases["leases"][0]["active_agent"] is None  # lease never borrowed
    assert not (repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "patch_artifact.json").exists()


def test_codex_runner_patch_mode_embeds_assignment_in_prompt(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo)
    _seed_patch_assignment(repo, text="ASSIGNMENT-MARKER: refactor foo.")

    agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: _FakeCodexProc(),
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=_chatgpt_auth_runner,
        git_runner=_fake_git_runner(diff_stdout="diff --git a/foo.py b/foo.py\n+x\n"),
    )

    prompt = (
        repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "## Assignment" in prompt
    assert "ASSIGNMENT-MARKER: refactor foo." in prompt


# --- Phase 4: claimed_files scope enforcement on the codex patch lane (issue #1612) ---


def test_codex_runner_patch_mode_blocks_out_of_scope_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo, claimed_files=["allowed.py"])
    _seed_patch_assignment(repo)
    diff = "diff --git a/foo.py b/foo.py\n+x\n"  # foo.py is NOT in the claim

    result = agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: _FakeCodexProc(),
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=_chatgpt_auth_runner,
        git_runner=_fake_git_runner(diff_stdout=diff),
    )

    assert result.decision == "blocked"
    assert any("outside the lease claim" in b for b in result.blockers)
    artifact = json.loads(
        (repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "patch_artifact.json").read_text(encoding="utf-8")
    )
    assert artifact["verdict"] == "blocked"
    assert artifact["wu"] == 0


def test_codex_runner_patch_mode_allows_in_scope_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_registry(repo)
    _seed_write_lease(repo, claimed_files=["foo.py"])
    _seed_patch_assignment(repo)
    diff = "diff --git a/foo.py b/foo.py\n+x\n"  # foo.py IS in the claim

    result = agent_loop.write_active_codex_runner(
        mode="patch",
        execute=True,
        task_id="T-2026-0042",
        repo_root=repo,
        popen_factory=lambda cmd, **kw: _FakeCodexProc(),
        which_func=lambda exe: "/usr/bin/codex",
        auth_runner=_chatgpt_auth_runner,
        git_runner=_fake_git_runner(diff_stdout=diff),
    )

    assert result.decision == "completed"
    artifact = json.loads(
        (repo / "reports" / "agent_loop" / "active" / "patch_runs" / "implementer" / "patch_artifact.json").read_text(encoding="utf-8")
    )
    assert artifact["verdict"] == "proposed"


# --- Phase 3 PR-B: active-apply (Orchestrator applies patch to integration branch, #1607) ---


def _fake_apply_git_runner(check_rc: int = 0):
    calls: list[list[str]] = []

    def run(cmd):
        calls.append(cmd)
        if "--check" in cmd:
            return subprocess.CompletedProcess(cmd, check_rc, stdout="", stderr=("" if check_rc == 0 else "error: patch failed to apply"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _seed_patch_artifact(
    repo: Path,
    *,
    verdict: str = "proposed",
    task: str = "T-2026-0042",
    session: str = "implementer",
    diff: str = "diff --git a/foo.py b/foo.py\n+x\n",
) -> Path:
    run_dir = repo / "reports" / "agent_loop" / "active" / "patch_runs" / session
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "patch_artifact.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": task,
                "session_id": session,
                "role": "Implementer",
                "agent": "codex",
                "verdict": verdict,
                "diff": diff,
                "files": ["foo.py"],
                "privacy_scrubbed": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_active_apply_dry_run_checks_only(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_artifact(repo)
    runner = _fake_apply_git_runner(check_rc=0)

    result = agent_loop.write_active_apply(repo_root=repo, git_runner=runner)

    assert result.decision == "checked"
    assert result.applied is False
    assert result.integration_branch == "feature/T-2026-0042-integration"
    # Inspect the command LISTS (exact tokens) — the repo tmp path itself contains "apply".
    assert any("--check" in c for c in runner.calls)
    assert not any("commit" in c for c in runner.calls)  # dry-run never commits
    assert not any(("apply" in c and "--check" not in c) for c in runner.calls)  # no real apply


def test_active_apply_execute_applies_and_commits(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_artifact(repo)
    runner = _fake_apply_git_runner(check_rc=0)

    result = agent_loop.write_active_apply(repo_root=repo, execute=True, git_runner=runner)

    assert result.decision == "applied"
    assert result.applied is True
    assert any("--check" in c for c in runner.calls)
    assert any(("apply" in c and "--check" not in c) for c in runner.calls)  # the real apply
    assert any("commit" in c for c in runner.calls)
    # every git op runs under the repo tree (repo_root or the integration worktree) — never a separate main checkout.
    assert all(c[2].startswith(str(repo)) for c in runner.calls if len(c) > 2 and c[1] == "-C")


def test_active_apply_blocks_when_check_fails(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_patch_artifact(repo)
    runner = _fake_apply_git_runner(check_rc=1)

    result = agent_loop.write_active_apply(repo_root=repo, execute=True, git_runner=runner)

    assert result.decision == "blocked"
    assert result.applied is False
    assert any("--check" in c for c in runner.calls)
    assert not any("commit" in c for c in runner.calls)  # fail-closed: no apply/commit after a failed check
    assert not any(("apply" in c and "--check" not in c) for c in runner.calls)


def test_active_apply_blocks_on_missing_or_unproposed_artifact(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    # missing artifact
    r1 = agent_loop.write_active_apply(repo_root=repo, execute=True, git_runner=_fake_apply_git_runner())
    assert r1.decision == "blocked" and any("not found" in b for b in r1.blockers)
    # present but verdict != proposed (and empty diff)
    _seed_patch_artifact(repo, verdict="empty", diff="")
    r2 = agent_loop.write_active_apply(repo_root=repo, execute=True, git_runner=_fake_apply_git_runner())
    assert r2.decision == "blocked" and r2.applied is False


# --- Phase 5: task-scoped gate_evidence bundle (issue #1616) ---


def _seed_gate_registry(repo: Path, *, reviewer_status: str = "approved", ci_status: str = "approved") -> None:
    active = repo / "reports" / "agent_loop" / "active"
    active.mkdir(parents=True, exist_ok=True)
    (active / "session_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "topology": "four-role",
                "gate_policy": "conservative",
                "agent_mix": agent_loop._parse_agent_mix(None),
                "sessions": [
                    {"session_id": "orchestrator", "role": "Orchestrator", "status": "running"},
                    {"session_id": "implementer", "role": "Implementer", "status": "running"},
                    {"session_id": "reviewer", "role": "Reviewer", "status": reviewer_status},
                    {"session_id": "ci-eval-auditor", "role": "CI/Eval Auditor", "status": ci_status},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_gate_evidence_ready_when_required_gates_pass(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_gate_registry(repo)

    path, summary = agent_loop.write_active_gate_evidence(task_id="T-2026-0042", repo_root=repo)

    assert summary["ready"] is True
    assert path == repo / "reports" / "agent_loop" / "active" / "gate_evidence" / "T-2026-0042" / "evidence.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    assert ev["conservative_gate"]["ready"] is True
    roles = {r["role"]: r["ok"] for r in ev["conservative_gate"]["required_roles"]}
    assert roles == {"Reviewer": True, "CI/Eval Auditor": True}
    assert ev["patch"] is None and ev["apply"] is None  # no patch/apply artifacts present
    assert ev["ship"].startswith("not-triggered")


def test_gate_evidence_not_ready_when_a_gate_is_unmet(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_gate_registry(repo, reviewer_status="idle")

    _, summary = agent_loop.write_active_gate_evidence(task_id="T-2026-0042", repo_root=repo)

    assert summary["ready"] is False


def test_gate_evidence_bundles_patch_and_apply(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _seed_gate_registry(repo)
    _seed_patch_artifact(repo)  # patch_runs/implementer/patch_artifact.json (verdict proposed)
    (repo / "reports" / "agent_loop" / "active" / "active_apply_state.json").write_text(
        json.dumps({"decision": "applied", "applied": True, "integration_branch": "feature/T-2026-0042-integration"}),
        encoding="utf-8",
    )

    path, _ = agent_loop.write_active_gate_evidence(task_id="T-2026-0042", repo_root=repo)

    ev = json.loads(path.read_text(encoding="utf-8"))
    assert ev["patch"]["verdict"] == "proposed"
    assert ev["apply"]["decision"] == "applied" and ev["apply"]["applied"] is True


def test_gate_evidence_rejects_bad_task(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        agent_loop.write_active_gate_evidence(task_id="nope", repo_root=tmp_path)


def test_stop_ship_skips_remote_branch_delete_when_stacked_dependents_exist() -> None:
    text = (ROOT / "scripts" / "claude-hooks" / "stop-ship.sh").read_text(encoding="utf-8")

    assert "gh pr list --base \"$ARM_BRANCH\" --state open --json number --jq 'length'" in text
    assert "skipping remote branch delete" in text
    assert "git push origin --delete \"$ARM_BRANCH\"" in text


def test_dependency_graph_workset_and_strict_profiles_are_fail_closed(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    report_dir = repo / "reports" / "agent_loop"
    tasks_dir = report_dir / "codex_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "001-ready.md").write_text(
        """# Ready local fix

- Classification: ready_for_implementation
- Source: PR #1
- Reason: Small docs update

## Goal

Update docs.

## Expected Evidence

Focused validation.

## Verification

```bash
git diff --check
```
""",
        encoding="utf-8",
    )
    pr_state = report_dir / "pr_state.json"
    pr_state.write_text(
        json.dumps([{"number": 5, "title": "Child", "baseRefName": "parent", "headRefName": "child"}]),
        encoding="utf-8",
    )

    workset_out, workset = agent_loop.write_workset_recommendation(tasks_dir=tasks_dir, repo_root=repo)
    graph_out, graph = agent_loop.write_dependency_graph(branch="parent", pr_json=pr_state, repo_root=repo)
    strict_report = agent_loop.build_auto_pass_report(
        task_id=None,
        changed_files=["scripts/agent_loop.py", "rag_core.py"],
        claim_text=None,
        run_validation=False,
        strict=True,
        profile="agent-loop-tooling-strict",
        repo_root=repo,
    )

    assert workset_out == repo / "reports" / "agent_loop" / "workset_recommendation.md"
    assert "parallel candidates" in workset
    assert graph_out == repo / "reports" / "agent_loop" / "dependency_graph.md"
    assert "flowchart TD" in graph
    assert "PR #5 child" in graph
    assert strict_report.decision == "human-review-required"
    assert any("agent-loop-tooling-strict" in blocker for blocker in strict_report.blockers)


def test_issue_scan_classifies_conservatively_with_queue_and_branch_evidence(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        task_id="T-2026-0001",
        status="done",
        body_extra="- Issue: [#101](https://github.com/example/repo/issues/101)\n",
    )
    issues = [
        {"number": 101, "title": "Completed cleanup", "labels": [], "url": "https://example.test/101"},
        {"number": 102, "title": "Active branch work", "labels": [], "url": "https://example.test/102"},
        {"number": 103, "title": "New backlog item", "labels": [], "url": "https://example.test/103"},
        {"number": 104, "title": "fix(eval): benchmark needs judgment", "labels": [{"name": "eval"}], "url": "https://example.test/104"},
    ]
    monkeypatch.setattr(agent_loop, "_local_issue_branches", lambda repo_root: {"102": {"chore/issue-102-active"}})
    monkeypatch.setattr(agent_loop, "_worktree_issue_branches", lambda repo_root: {})

    triage = agent_loop.build_issue_triage(issues=issues, repo_root=repo)
    by_number = {item.number: item for item in triage}

    assert by_number["101"].classification == "close_candidate"
    assert any("queue done" in evidence for evidence in by_number["101"].evidence)
    assert by_number["102"].classification == "in_flight"
    assert by_number["103"].classification == "queue_candidate"
    assert by_number["104"].classification == "manual_review"


def test_maintenance_plan_writes_queue_briefs_without_mutating_tracked_docs(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    issue_state = repo / "reports" / "agent_loop" / "issues.json"
    issue_state.parent.mkdir(parents=True, exist_ok=True)
    issue_state.write_text(
        json.dumps(
            [
                {"number": 201, "title": "Backlog janitor item", "labels": [], "url": "https://example.test/201"},
                {"number": 202, "title": "Already superseded cleanup", "labels": [{"name": "superseded"}], "url": "https://example.test/202"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_loop, "_local_issue_branches", lambda repo_root: {})
    monkeypatch.setattr(agent_loop, "_worktree_issue_branches", lambda repo_root: {})
    monkeypatch.setattr(agent_loop, "_maintenance_worktree_actions", lambda repo_root: ["make worktree-cleanup-dry-run"])

    out, json_out, plan, rendered = agent_loop.write_maintenance_plan(issue_json=issue_state, repo_root=repo)

    assert out == repo / "reports" / "agent_loop" / "maintenance_plan.md"
    assert json_out == repo / "reports" / "agent_loop" / "maintenance_plan.json"
    assert len(plan.queue_task_briefs) == 1
    assert (repo / plan.queue_task_briefs[0]).exists()
    assert "human-gated-exec --action issue-close --issue 202" in rendered
    assert not (repo / "tasks" / "queue.md").read_text(encoding="utf-8").startswith("Queue issue")


def test_human_gated_issue_close_requires_triage_plan_comment_and_close_candidate(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    report_dir = repo / "reports" / "agent_loop"
    report_dir.mkdir(parents=True, exist_ok=True)
    triage_plan = report_dir / "maintenance_plan.json"
    triage_plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "issues": [
                    {"number": "301", "classification": "close_candidate"},
                    {"number": "302", "classification": "queue_candidate"},
                ],
            }
        ),
        encoding="utf-8",
    )
    comment = report_dir / "issue-close-301.md"
    comment.write_text("Closing as superseded by merged work.", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    blocked = agent_loop.build_human_gated_exec_plan(
        action="issue-close",
        confirm_human_approved=True,
        dry_run=True,
        branch=None,
        pr=None,
        body=None,
        base=None,
        title=None,
        issue="302",
        comment_file=comment,
        triage_plan=triage_plan,
        draft=True,
        confirm_review_gate_passed=False,
        confirm_dependents_reviewed=False,
        confirm_force_with_lease=False,
        repo_root=repo,
    )
    executed_out, executed_plan, _ = agent_loop.write_human_gated_exec(
        action="issue-close",
        issue="301",
        comment_file=comment,
        triage_plan=triage_plan,
        confirm_human_approved=True,
        repo_root=repo,
    )

    assert any("queue_candidate" in blocker for blocker in blocked.blockers)
    assert executed_out == repo / "reports" / "agent_loop" / "human_gated_exec.md"
    assert executed_plan.command == ("gh", "issue", "close", "301", "--comment", "Closing as superseded by merged work.")
    assert calls == [["gh", "issue", "close", "301", "--comment", "Closing as superseded by merged work."]]
    try:
        agent_loop.build_human_gated_exec_plan(
            action="issue-close",
            confirm_human_approved=True,
            dry_run=True,
            branch=None,
            pr=None,
            body=None,
            base=None,
            title=None,
            issue="../301",
            comment_file=comment,
            triage_plan=triage_plan,
            draft=True,
            confirm_review_gate_passed=False,
            confirm_dependents_reviewed=False,
            confirm_force_with_lease=False,
            repo_root=repo,
        )
    except ValueError as exc:
        assert "issue selector" in str(exc)
    else:
        raise AssertionError("unsafe issue selector should be rejected")


def test_human_gated_exec_requires_confirmation_and_uses_safe_commands(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    blocked_out, blocked_plan, blocked = agent_loop.write_human_gated_exec(
        action="push",
        confirm_human_approved=False,
        branch="chore/issue-9999-agent-loop",
        repo_root=repo,
    )
    assert not calls
    executed_out, executed_plan, executed = agent_loop.write_human_gated_exec(
        action="push",
        confirm_human_approved=True,
        branch="chore/issue-9999-agent-loop",
        repo_root=repo,
    )
    merge_plan = agent_loop.build_human_gated_exec_plan(
        action="pr-merge",
        confirm_human_approved=True,
        dry_run=True,
        branch=None,
        pr="42",
        body=None,
        base=None,
        title=None,
        draft=True,
        confirm_review_gate_passed=True,
        confirm_dependents_reviewed=False,
        confirm_force_with_lease=False,
        repo_root=repo,
    )
    force_plan = agent_loop.build_human_gated_exec_plan(
        action="force-push",
        confirm_human_approved=True,
        dry_run=True,
        branch="chore/issue-9999-agent-loop",
        pr=None,
        body=None,
        base=None,
        title=None,
        draft=True,
        confirm_review_gate_passed=False,
        confirm_dependents_reviewed=False,
        confirm_force_with_lease=False,
        repo_root=repo,
    )

    assert blocked_out == repo / "reports" / "agent_loop" / "human_gated_exec.md"
    assert blocked_plan.blockers
    assert "confirm-human-approved" in blocked
    assert executed_out == repo / "reports" / "agent_loop" / "human_gated_exec.md"
    assert executed_plan.executed
    assert calls == [["git", "push", "-u", "origin", "chore/issue-9999-agent-loop"]]
    assert "ok" not in executed  # output body is summarized, not echoed
    assert merge_plan.command == ("gh", "pr", "merge", "42", "--squash")
    assert "--delete-branch" not in merge_plan.command
    assert "--admin" not in merge_plan.command
    assert any("force-with-lease" in blocker for blocker in force_plan.blockers)


def test_issue_scan_and_maintenance_plan_are_conservative(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(
        tmp_path,
        task_id="T-2026-0012",
        title="Merged cleanup",
        status="done",
        body_extra="- Issue: [#12](https://github.com/example/repo/issues/12)\n",
    )
    issue_json = repo / "reports" / "agent_loop" / "issues.json"
    issue_json.parent.mkdir(parents=True, exist_ok=True)
    issue_json.write_text(
        json.dumps(
            [
                {
                    "number": 12,
                    "title": "Already merged cleanup",
                    "url": "https://github.com/example/repo/issues/12",
                    "labels": [],
                    "updatedAt": "2026-05-26T00:00:00Z",
                },
                {
                    "number": 34,
                    "title": "Add backlog cleanup",
                    "url": "https://github.com/example/repo/issues/34",
                    "labels": [{"name": "follow-up"}],
                    "updatedAt": "2026-05-26T00:00:00Z",
                },
                {
                    "number": 56,
                    "title": "user-action: manual portfolio review",
                    "url": "https://github.com/example/repo/issues/56",
                    "labels": [{"name": "follow-up"}],
                    "updatedAt": "2026-05-26T00:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_loop, "_maintenance_worktree_actions", lambda repo_root: ["dry-run fixture"])

    state_out, triage_out, triage, rendered = agent_loop.write_issue_scan(
        issue_json=issue_json,
        repo_root=repo,
    )
    plan_out, json_out, plan, plan_text = agent_loop.write_maintenance_plan(
        issue_json=issue_json,
        repo_root=repo,
    )

    classifications = {item.number: item.classification for item in triage}
    assert classifications == {"12": "close_candidate", "34": "queue_candidate", "56": "manual_review"}
    assert state_out == repo / "reports" / "agent_loop" / "issue_state.json"
    assert triage_out == repo / "reports" / "agent_loop" / "issue_triage.md"
    assert plan_out == repo / "reports" / "agent_loop" / "maintenance_plan.md"
    assert json_out == repo / "reports" / "agent_loop" / "maintenance_plan.json"
    assert len(plan.queue_task_briefs) == 1
    assert "issue-34" in plan.queue_task_briefs[0]
    assert "human-gated-exec --action issue-close --issue 12" in plan_text
    assert "dry-run fixture" in plan_text
    assert "close_candidate" in rendered


def test_human_gated_issue_close_requires_triage_and_uses_gh_comment(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    report_dir = repo / "reports" / "agent_loop"
    report_dir.mkdir(parents=True, exist_ok=True)
    triage_plan = report_dir / "maintenance_plan.json"
    triage_plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "issues": [
                    {"number": "12", "classification": "close_candidate"},
                    {"number": "34", "classification": "manual_review"},
                ],
            }
        ),
        encoding="utf-8",
    )
    comment = report_dir / "issue-close-12.md"
    comment.write_text("Closing because merged evidence is in the queue.\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="closed\n", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    blocked = agent_loop.build_human_gated_exec_plan(
        action="issue-close",
        confirm_human_approved=True,
        dry_run=True,
        branch=None,
        pr=None,
        body=None,
        base=None,
        title=None,
        draft=True,
        confirm_review_gate_passed=False,
        confirm_dependents_reviewed=False,
        confirm_force_with_lease=False,
        repo_root=repo,
        issue="34",
        comment_file=comment,
        triage_plan=triage_plan,
    )
    out, executed, rendered = agent_loop.write_human_gated_exec(
        action="issue-close",
        confirm_human_approved=True,
        issue="12",
        comment_file=comment,
        triage_plan=triage_plan,
        repo_root=repo,
    )

    assert any("manual_review" in blocker for blocker in blocked.blockers)
    assert out == repo / "reports" / "agent_loop" / "human_gated_exec.md"
    assert executed.executed
    assert calls == [["gh", "issue", "close", "12", "--comment", "Closing because merged evidence is in the queue.\n"]]
    assert "--comment-file" not in executed.command
    assert executed.command[:4] == ("gh", "issue", "close", "12")
    assert "--comment" in executed.command
    assert "closed" not in rendered


def test_human_gated_exec_pr_create_checks_body_and_rejects_unsafe_branch(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    body = repo / "reports" / "agent_loop" / "pr_body.md"
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(
        """Closes #9999

### 5b. Real-data delta

N/A - no load-bearing path.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_loop, "_changed_files_from_git", lambda repo_root: ["scripts/agent_loop.py"])

    plan = agent_loop.build_human_gated_exec_plan(
        action="pr-create",
        confirm_human_approved=True,
        dry_run=True,
        branch="chore/issue-9999-agent-loop",
        pr=None,
        body=body,
        base="main",
        title="Agent loop gated exec",
        draft=True,
        confirm_review_gate_passed=False,
        confirm_dependents_reviewed=False,
        confirm_force_with_lease=False,
        repo_root=repo,
    )

    assert not plan.blockers
    assert plan.command[:3] == ("gh", "pr", "create")
    assert "--draft" in plan.command
    try:
        agent_loop.build_human_gated_exec_plan(
            action="push",
            confirm_human_approved=True,
            dry_run=True,
            branch="bad branch;rm",
            pr=None,
            body=None,
            base=None,
            title=None,
            draft=True,
            confirm_review_gate_passed=False,
            confirm_dependents_reviewed=False,
            confirm_force_with_lease=False,
            repo_root=repo,
        )
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("expected unsafe branch to fail")


def test_human_gated_exec_pr_ready_bridges_draft_to_ship_gate(monkeypatch, tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ready\n", stderr="")

    monkeypatch.setattr(agent_loop.subprocess, "run", fake_run)

    plan = agent_loop.build_human_gated_exec_plan(
        action="pr-ready",
        confirm_human_approved=True,
        dry_run=True,
        branch=None,
        pr="1552",
        body=None,
        base=None,
        title=None,
        draft=True,
        confirm_review_gate_passed=False,
        confirm_dependents_reviewed=False,
        confirm_force_with_lease=False,
        repo_root=repo,
    )
    out, executed, rendered = agent_loop.write_human_gated_exec(
        action="pr-ready",
        pr="1552",
        confirm_human_approved=True,
        repo_root=repo,
    )

    assert not plan.blockers
    assert plan.command == ("gh", "pr", "ready", "1552")
    assert "review, claim, and dependency gates still run" in plan.warnings[0]
    assert out == repo / "reports" / "agent_loop" / "human_gated_exec.md"
    assert executed.executed
    assert calls == [["gh", "pr", "ready", "1552"]]
    assert "gh pr ready 1552" in rendered


def test_path_traversal_changed_files_are_redacted_and_not_read(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path, body_extra=_valid_handoff())
    outside = tmp_path.parent / "outside_agent_loop_secret.py"
    outside.write_text("print('SECRET_OUTSIDE')  \n", encoding="utf-8")

    normalized = agent_loop._normalize_changed_file("../outside_agent_loop_secret.py", repo_root=repo)
    patch = agent_loop.render_patch_proposal(
        changed_files=["../outside_agent_loop_secret.py", str(outside)],
        review_plan=None,
        repo_root=repo,
    )
    safe_fix = agent_loop.build_safe_fix_report(
        changed_files=["../outside_agent_loop_secret.py", str(outside)],
        apply=False,
        repo_root=repo,
    )

    assert normalized == "[redacted-local-path]"
    assert "SECRET_OUTSIDE" not in patch
    assert not safe_fix.changes


def test_workflow_uses_hardened_readonly_agent_loop_artifacts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "agent-loop-artifacts.yml").read_text(encoding="utf-8")

    assert "persist-credentials: false" in workflow
    assert ".agent_loop_tmp" in workflow
    assert "--text \"$PR_BODY_FILE\"" in workflow
    assert "readiness-score" in workflow
    assert "branch-issue-hygiene" in workflow
    assert "privacy-regression" in workflow
    assert "auto-ship-plan" in workflow


def test_default_agent_loop_outputs_are_gitignored() -> None:
    for rel in (
        "reports/agent_loop/rendered_prompt.txt",
        "reports/agent_loop/review_prompt.txt",
        "reports/agent_loop/pr_state.json",
        "reports/agent_loop/issue_state.json",
        "reports/agent_loop/issue_triage.md",
        "reports/agent_loop/issue_queue_tasks/001-example.md",
        "reports/agent_loop/maintenance_plan.md",
        "reports/agent_loop/maintenance_plan.json",
        "reports/agent_loop/changed_files.txt",
        "reports/agent_loop/surface.md",
        "reports/agent_loop/validation_suggestions.md",
        "reports/agent_loop/queue_entry_draft.md",
        "reports/agent_loop/codex_tasks/001-example.md",
        "reports/agent_loop/batch_plan.md",
        "reports/agent_loop/batch_plan.json",
        "reports/agent_loop/review_followups.md",
        "reports/agent_loop/review_followups/001-example.md",
        "reports/agent_loop/decision_brief.md",
        "reports/agent_loop/promote_draft.md",
        "reports/agent_loop/gate_status.md",
        "reports/agent_loop/claim_audit.md",
        "reports/agent_loop/privacy_audit.md",
        "reports/agent_loop/auto_pass.md",
        "reports/agent_loop/dashboard.md",
        "reports/agent_loop/mcp_client_config.md",
        "reports/agent_loop/review_ingest.md",
        "reports/agent_loop/pr_health.md",
        "reports/agent_loop/safe_fix.md",
        "reports/agent_loop/approval_packet.md",
        "reports/agent_loop/queue_plan_patch.diff",
        "reports/agent_loop/pr_body.md",
        "reports/agent_loop/review_plan.md",
        "reports/agent_loop/stale_reports.md",
        "reports/agent_loop/context_pack.md",
        "reports/agent_loop/architecture_brief.md",
        "reports/agent_loop/ship_simulation.md",
        "reports/agent_loop/auto_ship_plan.md",
        "reports/agent_loop/auto_ship_prepare.md",
        "reports/agent_loop/gate_brief.md",
        "reports/agent_loop/manifest.json",
        "reports/agent_loop/pr_body_check.md",
        "reports/agent_loop/ci_ingest.md",
        "reports/agent_loop/ci_followups/001-example.md",
        "reports/agent_loop/stacked_risk.md",
        "reports/agent_loop/patch_proposal.diff",
        "reports/agent_loop/adr_reservation.md",
        "reports/agent_loop/adr_draft.md",
        "reports/agent_loop/dashboard.html",
        "reports/agent_loop/ship_commands.md",
        "reports/agent_loop/apply_queue_plan.md",
        "reports/agent_loop/review_threads.md",
        "reports/agent_loop/ci_summary.md",
        "reports/agent_loop/readiness_score.md",
        "reports/agent_loop/branch_issue_hygiene.md",
        "reports/agent_loop/integration_pack.md",
        "reports/agent_loop/schedule_config.md",
        "reports/agent_loop/validation_history.jsonl",
        "reports/agent_loop/validation_history.md",
        "reports/agent_loop/privacy_regression.md",
        "reports/agent_loop/claim_policy.md",
        "reports/agent_loop/architecture_decision.md",
        "reports/agent_loop/workset_recommendation.md",
        "reports/agent_loop/dependency_graph.md",
        "reports/agent_loop/automation_coverage.md",
        "reports/agent_loop/human_gated_exec.md",
        "reports/agent_loop/continue_loop.md",
        "reports/agent_loop/loop_state.json",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", rel],
            cwd=ROOT,
            text=True,
            check=False,
        )
        assert result.returncode == 0, rel
