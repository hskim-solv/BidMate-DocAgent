from __future__ import annotations

import json
from pathlib import Path
import subprocess

from scripts import ai_next_actions as planner
from scripts._governance import find_redacted_summary_forbidden_fields


ROOT = Path(__file__).resolve().parents[1]


def _summary(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "audit_type": "private_data_readiness",
        "ready_for_improvement": True,
        "flags_summary": {"blocker": 0, "warning": 0, "info": 0},
        "index_integrity": {
            "missing_page_metadata_rate": 0.0,
            "page_metadata": {
                "citation_page_claim_go_no_go": "GO",
                "chunk": {"missing_page_metadata_rate": 0.0},
            },
        },
    }
    payload.update(overrides)
    return payload


def _run(tmp_path: Path, *, summary: dict | None = None, prs: list[dict] | None = None) -> tuple[str, dict[str, str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    if summary is not None:
        summary_path = tmp_path / "readiness_summary.json"
        summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        args.extend(["--readiness-summary", str(summary_path)])
    if prs is not None:
        pr_path = tmp_path / "prs.json"
        pr_path.write_text(json.dumps(prs, sort_keys=True), encoding="utf-8")
        args.extend(["--pr-json", str(pr_path)])
    out_md = tmp_path / "reports" / "ai_next_actions.md"
    tasks_dir = tmp_path / "reports" / "codex_tasks"
    rc = planner.main([*args, "--out-md", str(out_md), "--tasks-dir", str(tasks_dir)])
    assert rc == 0
    tasks = {path.name: path.read_text(encoding="utf-8") for path in sorted(tasks_dir.glob("*.md"))}
    return out_md.read_text(encoding="utf-8"), tasks


def _pr(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": 12,
        "title": "chore: fixture PR",
        "url": "https://github.com/example/repo/pull/12",
        "headRefName": "chore/issue-12-fixture",
        "baseRefName": "main",
        "isDraft": False,
        "reviewDecision": "REVIEW_REQUIRED",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [],
        "labels": [],
        "body": "",
        "updatedAt": "2026-05-24T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_blocker_present_recommends_blocker_fix(tmp_path: Path) -> None:
    md, tasks = _run(
        tmp_path,
        summary=_summary(
            ready_for_improvement=False,
            flags_summary={"blocker": 2, "warning": 0, "info": 0},
        ),
    )

    assert "Top task: `blocked` - Fix readiness blockers" in md
    assert next(iter(tasks)).startswith("001-fix-blocker")
    assert "Remove readiness blockers" in next(iter(tasks.values()))


def test_1448_pending_private_delta_recommends_private_delta(tmp_path: Path) -> None:
    md, tasks = _run(
        tmp_path,
        summary=_summary(),
        prs=[
            _pr(
                number=1449,
                title="feat: pending private delta for #1448",
                headRefName="feat/issue-1448-private-delta",
                statusCheckRollup=[
                    {"name": "test", "status": "COMPLETED", "conclusion": "SUCCESS"}
                ],
                labels=[{"name": "private delta"}],
                body="Needs private delta evidence before merge.",
            )
        ],
    )

    assert "Private delta needed: `True`" in md
    assert "Run private delta for PR #1449" in md
    assert any(name.endswith("run-private-delta.md") for name in tasks)


def test_missing_page_metadata_rate_marks_page_citation_no_go(tmp_path: Path) -> None:
    md, tasks = _run(
        tmp_path,
        summary=_summary(
            index_integrity={
                "missing_page_metadata_rate": 1.0,
                "page_metadata": {
                    "citation_page_claim_go_no_go": "GO",
                    "chunk": {"missing_page_metadata_rate": 1.0},
                },
            },
        ),
    )

    assert "Page citation claim: `NO-GO`" in md
    joined_tasks = "\n".join(tasks.values())
    assert "page citation accuracy claims" in joined_tasks
    assert "Readiness summary reports page citation/page claim as GO." in joined_tasks


def test_forbidden_private_keys_do_not_leak_to_generated_reports(tmp_path: Path) -> None:
    unsafe = _summary(
        **{
            "question": "PRIVATE RAW QUERY",
            "support_text": "PRIVATE SUPPORT",
            "doc_id": "PRIVATE-DOC",
            "path": "/Users/example/private/file.pdf",
        }
    )

    md, tasks = _run(tmp_path, summary=unsafe)
    generated = md + "\n".join(tasks.values())

    assert "sanitized input contained forbidden fields" in generated
    assert "PRIVATE RAW QUERY" not in generated
    assert "PRIVATE SUPPORT" not in generated
    assert "PRIVATE-DOC" not in generated
    assert "/Users/example/private/file.pdf" not in generated
    assert find_redacted_summary_forbidden_fields({"rendered": generated}) == {}


def test_output_is_deterministic_from_fixture_inputs(tmp_path: Path) -> None:
    summary = _summary()
    prs = [
        _pr(
            number=12,
            title="chore: continue draft",
            headRefName="chore/issue-12-draft",
            isDraft=True,
        )
    ]

    first_md, first_tasks = _run(tmp_path / "first", summary=summary, prs=prs)
    second_md, second_tasks = _run(tmp_path / "second", summary=summary, prs=prs)

    assert first_md == second_md
    assert first_tasks == second_tasks


def test_default_outputs_are_gitignored() -> None:
    for rel in ("reports/ai_next_actions.md", "reports/codex_tasks/001-example.md"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", rel],
            cwd=ROOT,
            text=True,
            check=False,
        )
        assert result.returncode == 0, rel


def test_missing_required_pr_json_fields_fail_closed(tmp_path: Path) -> None:
    incomplete = _pr()
    incomplete.pop("mergeStateStatus")

    md, tasks = _run(tmp_path, summary=_summary(), prs=[incomplete])

    assert "Top task: `blocked` - Unblock PR #12" in md
    assert "missing required PR JSON fields" in md
    assert any("Resolve review, merge, or CI blockers" in body for body in tasks.values())


def test_unstable_merge_state_is_blocked(tmp_path: Path) -> None:
    md, tasks = _run(tmp_path, summary=_summary(), prs=[_pr(mergeStateStatus="UNSTABLE")])

    assert "Top task: `blocked` - Unblock PR #12" in md
    assert "merge state is UNSTABLE" in md
    assert any("Resolve review, merge, or CI blockers" in body for body in tasks.values())
