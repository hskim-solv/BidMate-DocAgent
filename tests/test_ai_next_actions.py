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


def _run(
    tmp_path: Path,
    *,
    summary: dict | None = None,
    prs: list[dict] | None = None,
    real100_dir: Path | None = None,
    page_metadata_index_dir: Path | None = None,
) -> tuple[str, dict[str, str]]:
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
    if real100_dir is not None:
        args.extend(["--real100-dir", str(real100_dir)])
    if page_metadata_index_dir is not None:
        args.extend(["--page-metadata-index-dir", str(page_metadata_index_dir)])
    out_md = tmp_path / "reports" / "ai_next_actions.md"
    out_html = tmp_path / "reports" / "ai_next_actions.html"
    tasks_dir = tmp_path / "reports" / "codex_tasks"
    rc = planner.main(
        [*args, "--out-md", str(out_md), "--out-html", str(out_html), "--tasks-dir", str(tasks_dir)]
    )
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
    assert "Prepare private delta evidence lane" in md
    assert "Source PRs: `#1449`" in md
    assert any(name.endswith("private-delta-lane.md") for name in tasks)
    assert any("- Workset: `private-delta`" in body for body in tasks.values())


def test_no_go_pr_is_failed_experiment_before_unstable_merge_state(tmp_path: Path) -> None:
    md, tasks = _run(
        tmp_path,
        summary=_summary(),
        prs=[
            _pr(
                number=1448,
                title="Add hybrid BM25 dense retrieval v1 eval row",
                headRefName="feat/issue-1447-hybrid-bm25-dense-v1",
                isDraft=True,
                mergeStateStatus="UNSTABLE",
                body=(
                    "Latest private aggregate experiment is NO-GO and not "
                    "claim-ready; keep this as a draft measurement PR."
                ),
            ),
            _pr(
                number=1430,
                title="[codex] Separate smoke eval from naive RAG benchmark",
                isDraft=True,
                mergeStateStatus="UNSTABLE",
            ),
        ],
    )

    assert "Top task: `failed_experiment` - Document failed measurement PR lane" in md
    assert "not merge-ready" in md
    assert "Latest private aggregate experiment" not in "\n".join(tasks.values())
    assert any(name.endswith("failed-measurement-lane.md") for name in tasks)


def test_superseded_draft_pr_is_close_candidate_not_unblock(tmp_path: Path) -> None:
    md, tasks = _run(
        tmp_path,
        summary=_summary(),
        prs=[
            _pr(
                number=1430,
                title="[codex] Separate smoke eval from naive RAG benchmark",
                isDraft=True,
                mergeStateStatus="UNSTABLE",
                body="Superseded by the newer planner PR; do not merge.",
            )
        ],
    )

    assert "Clean stale draft PR lane" in md
    assert "Unblock PR #1430" not in md
    assert any(name.endswith("stale-draft-cleanup.md") for name in tasks)


def test_pr_corpus_plans_workset_tasks_instead_of_selecting_one_pr(tmp_path: Path) -> None:
    md, tasks = _run(
        tmp_path,
        prs=[
            _pr(number=10, mergeStateStatus="UNSTABLE"),
            _pr(number=11, isDraft=True, body="Superseded by PR #12."),
            _pr(number=12, isDraft=False),
            _pr(number=13, isDraft=True),
        ],
    )

    generated = md + "\n".join(tasks.values())

    assert "Triage blocked PR lane" in generated
    assert "Clean stale draft PR lane" in generated
    assert "Ship ready PR lane" in generated
    assert "Continue draft PR workset" in generated
    assert "Source PRs: `#10`" in generated
    assert "Source PRs: `#11`" in generated
    assert "Source PRs: `#12`" in generated
    assert "Source PRs: `#13`" in generated
    assert "Review PR #12" not in generated
    assert "Continue draft PR #13" not in generated


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


def test_real100_aggregates_add_retrieval_miss_task_when_mapping_fix_absent(tmp_path: Path) -> None:
    real100_dir = tmp_path / "real100"
    variance_dir = real100_dir / "variance_measurement"
    variance_dir.mkdir(parents=True)
    (real100_dir / "failure_distribution.aggregate.json").write_text(
        json.dumps({"failure_category_counts": {"retrieval_miss": 0}}),
        encoding="utf-8",
    )
    (real100_dir / "failure_slices.aggregate.json").write_text(
        json.dumps({"categories": {"retrieval_miss": {"total": 67}}}),
        encoding="utf-8",
    )
    (variance_dir / "aggregate.json").write_text(
        json.dumps({"category_stats": {"retrieval_miss": {"mean": 64}}}),
        encoding="utf-8",
    )
    (real100_dir / "multi_chunk_evidence_failures.aggregate.json").write_text(
        json.dumps(
            {
                "population": {
                    "multi_chunk_gold_cases": 99,
                    "multi_chunk_top10_evidence_failures": 97,
                },
                "expected_impact": {"unknown_due_to_limited_depth": 97},
            }
        ),
        encoding="utf-8",
    )

    items = planner._real100_aggregate_items(
        real100_dir,
        retrieval_miss_mapping_fix_done=False,
    )
    generated = "\n".join(planner.render_task_markdown(item) for item in items)

    assert "Audit retrieval_miss aggregate mapping" in generated
    assert "retrieval_miss aggregate signals differ" in generated
    assert "Use multi-chunk evidence analysis" in generated
    assert "97/99 top-10 failures" in generated


def test_real100_aggregates_skip_retrieval_miss_task_when_mapping_fix_exists(tmp_path: Path) -> None:
    real100_dir = tmp_path / "real100"
    variance_dir = real100_dir / "variance_measurement"
    variance_dir.mkdir(parents=True)
    (real100_dir / "failure_distribution.aggregate.json").write_text(
        json.dumps({"failure_category_counts": {"retrieval_miss": 0}}),
        encoding="utf-8",
    )
    (variance_dir / "aggregate.json").write_text(
        json.dumps({"category_stats": {"retrieval_miss": {"mean": 64}}}),
        encoding="utf-8",
    )
    (real100_dir / "multi_chunk_evidence_failures.aggregate.json").write_text(
        json.dumps(
            {
                "population": {
                    "multi_chunk_gold_cases": 99,
                    "multi_chunk_top10_evidence_failures": 97,
                },
                "expected_impact": {"unknown_due_to_limited_depth": 97},
            }
        ),
        encoding="utf-8",
    )

    md, tasks = _run(tmp_path, real100_dir=real100_dir)
    generated = md + "\n".join(tasks.values())

    assert planner._retrieval_miss_mapping_fix_available()
    assert "Audit retrieval_miss aggregate mapping" not in generated
    assert "Use multi-chunk evidence analysis" in generated


def test_page_metadata_index_dir_marks_page_level_claim_no_go(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "documents": [{"doc_id": "doc-a", "metadata": {}}],
                "parent_sections": [],
                "chunks": [{"chunk_id": "doc-a::chunk-1", "doc_id": "doc-a"}],
            }
        ),
        encoding="utf-8",
    )

    md, tasks = _run(tmp_path, page_metadata_index_dir=index_dir)

    assert "Page citation claim: `NO-GO`" in md
    assert any("Keep page-level citation claims disabled" in body for body in tasks.values())


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
    html = (tmp_path / "reports" / "ai_next_actions.html").read_text(encoding="utf-8")
    generated = md + html + "\n".join(tasks.values())

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
    first_html = (tmp_path / "first" / "reports" / "ai_next_actions.html").read_text(
        encoding="utf-8"
    )
    second_html = (tmp_path / "second" / "reports" / "ai_next_actions.html").read_text(
        encoding="utf-8"
    )

    assert first_md == second_md
    assert first_tasks == second_tasks
    assert first_html == second_html


def test_default_outputs_are_gitignored() -> None:
    for rel in (
        "reports/ai_next_actions.md",
        "reports/ai_next_actions.html",
        "reports/codex_tasks/001-example.md",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", rel],
            cwd=ROOT,
            text=True,
            check=False,
        )
        assert result.returncode == 0, rel


def test_html_output_can_be_disabled(tmp_path: Path) -> None:
    out_md = tmp_path / "reports" / "ai_next_actions.md"
    tasks_dir = tmp_path / "reports" / "codex_tasks"

    rc = planner.main(["--out-md", str(out_md), "--out-html", "", "--tasks-dir", str(tasks_dir)])

    assert rc == 0
    assert out_md.exists()
    assert not (tmp_path / "reports" / "ai_next_actions.html").exists()


def test_missing_required_pr_json_fields_fail_closed(tmp_path: Path) -> None:
    incomplete = _pr()
    incomplete.pop("mergeStateStatus")

    md, tasks = _run(tmp_path, summary=_summary(), prs=[incomplete])

    assert "Top task: `blocked` - Triage blocked PR lane" in md
    assert "missing required PR JSON fields" in md
    assert any("Resolve shared CI, review, or merge blockers" in body for body in tasks.values())


def test_unstable_merge_state_is_blocked(tmp_path: Path) -> None:
    md, tasks = _run(tmp_path, summary=_summary(), prs=[_pr(mergeStateStatus="UNSTABLE")])

    assert "Top task: `blocked` - Triage blocked PR lane" in md
    assert "merge state is UNSTABLE" in md
    assert any("Resolve shared CI, review, or merge blockers" in body for body in tasks.values())


def test_html_report_escapes_pr_text(tmp_path: Path) -> None:
    _run(
        tmp_path,
        summary=_summary(),
        prs=[
            _pr(
                title="<script>alert('x')</script>",
                body="No blocker.",
            )
        ],
    )
    html = (tmp_path / "reports" / "ai_next_actions.html").read_text(encoding="utf-8")

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" not in html
    assert "Recommended Workset Task" in html
    assert "Ship ready PR lane" in html
    assert "PR corpus" in html
    assert "Human-readable view of the deterministic Codex planner" in html
