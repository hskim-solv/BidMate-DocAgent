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

    assert args.topology == "expanded-eight"
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
