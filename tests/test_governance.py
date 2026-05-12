"""Drift guard for the load-bearing path SSoT (`scripts/_governance.py`)
plus regex-level checks for the §5b enforcement in
`scripts/check_branch_and_issue.py`.

The same conceptual list previously lived in three places with subtle
differences. These tests ensure all three consumers reach back to the
SSoT instead of carrying their own copy. The §5b tests confirm the
gating logic accepts the documented escape sentence and rejects an
empty/comment-only template body (which would otherwise let PR #69-class
regressions through).

Additional invariants (issue #315, parent #284):
- `naive_baseline` preset retained in `eval/config.yaml` (ADR 0001).
- Every ADR row in `docs/adr/README.md` resolves to a file on disk
  (CLAUDE.md "Prohibited: Deleting or renaming ADR files").
- `rag_core.py` defines no `pydantic.BaseModel` / `TypedDict` subclass
  (CLAUDE.md "Prohibited: parallel ... model that shadows
  run_rag_query's answer dict"; ADR 0003).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import _governance as gov  # noqa: E402
import check_branch_and_issue as cbi  # noqa: E402


@pytest.mark.parametrize("entry", [
    "rag_core.py",
    "ingestion.py",
    "visual_ingestion.py",
    "eval/",
    "api/",
    "docs/adr/",
])
def test_canonical_list_contains_claude_md_entries(entry):
    assert entry in gov.LOAD_BEARING_PATHS, (
        f"CLAUDE.md lists {entry!r} as load-bearing but the SSoT does not."
    )


@pytest.mark.parametrize("path", [
    "rag_core.py",
    "./rag_core.py",
    "ingestion.py",
    "visual_ingestion.py",
    "eval/config.yaml",
    "eval/run_eval.py",
    "api/main.py",
    "docs/adr/0001-preserve-naive-baseline.md",
    "scripts/build_index.py",
    "/Users/x/proj/rag_core.py",
    "/abs/path/to/api/main.py",
    "/abs/path/to/docs/adr/0007.md",
])
def test_is_load_bearing_accepts(path):
    assert gov.is_load_bearing(path), f"expected load-bearing: {path!r}"


@pytest.mark.parametrize("path", [
    "",
    "README.md",
    "CHANGELOG.md",
    "myapi/main.py",
    "preeval/foo.py",
    "tests/test_governance.py",
    "scripts/check_branch_and_issue.py",
    "data/raw/example.pdf",
    "rag_core_helper.py",
])
def test_is_load_bearing_rejects(path):
    assert not gov.is_load_bearing(path), f"expected NOT load-bearing: {path!r}"


def test_pre_push_hook_uses_governance_module():
    text = (ROOT_DIR / ".githooks" / "pre-push").read_text()
    assert "_governance.py" in text, (
        ".githooks/pre-push must call scripts/_governance.py (SSoT) "
        "instead of carrying its own WATCH_PATTERNS array."
    )


def test_pretooluse_hook_uses_governance_module():
    text = (
        ROOT_DIR / "scripts" / "claude-hooks" / "pretooluse-loadbearing.sh"
    ).read_text()
    assert "_governance.py" in text, (
        "PreToolUse hook must call scripts/_governance.py (SSoT) "
        "instead of carrying its own LOAD_BEARING_PATTERNS array."
    )


def test_pr_template_mentions_all_canonical_entries():
    template = (
        ROOT_DIR / ".github" / "pull_request_template.md"
    ).read_text()
    for entry in gov.LOAD_BEARING_PATHS:
        assert entry in template, (
            f"PR template must mention load-bearing entry {entry!r} "
            f"so reviewers see the §5b trigger surface. "
            f"Update .github/pull_request_template.md to keep it in sync "
            f"with scripts/_governance.LOAD_BEARING_PATHS."
        )


def test_five_b_section_absent_when_no_header():
    assert cbi._five_b_section("nothing here") is None


def test_five_b_section_found_with_default_template_only():
    body = (
        "### 5b. Real-data delta\n\n"
        "<!--\n"
        "Required if load-bearing path changed.\n"
        "Attach `make real-eval-delta` table or state:\n"
        "'No behavior change in retrieval / verifier path.'\n"
        "-->\n"
    )
    section = cbi._five_b_section(body)
    assert section is not None, "header is present, even if section is empty"
    assert not cbi.FIVE_B_TABLE_RE.search(section), (
        "comment-only template body must NOT count as a markdown table"
    )
    assert not cbi.FIVE_B_ESCAPE_RE.search(section), (
        "escape sentence inside an HTML comment must be stripped, "
        "otherwise the default empty template would silently satisfy §5b"
    )


def test_five_b_table_regex_matches_real_eval_delta_aggregate():
    section = (
        "\n\n"
        "| metric | base | head | delta |\n"
        "|---|---|---|---|\n"
        "| accuracy | 0.82 | 0.84 | +0.02 |\n"
    )
    assert cbi.FIVE_B_TABLE_RE.search(section)


@pytest.mark.parametrize("sentence", [
    "No behavior change in retrieval path.",
    "No behavior change in verifier path.",
    "No behavior change in retrieval / verifier path.",
    "no behavior change in eval path",
    "No behavior change in API path.",
    "No behavior change in ingestion path.",
])
def test_five_b_escape_regex_accepts_documented_escape(sentence):
    assert cbi.FIVE_B_ESCAPE_RE.search(sentence), (
        f"Escape sentence not recognized: {sentence!r}"
    )


@pytest.mark.parametrize("sentence", [
    "No behavior change anywhere.",
    "We changed retrieval behavior.",
    "TODO: add real-eval delta.",
])
def test_five_b_escape_regex_rejects_off_pattern(sentence):
    assert not cbi.FIVE_B_ESCAPE_RE.search(sentence), (
        f"Should not match escape: {sentence!r}"
    )


# ---------------------------------------------------------------------------
# G2 — `naive_baseline` preset retained in eval/config.yaml (ADR 0001).
# ---------------------------------------------------------------------------


def test_naive_baseline_preset_present_in_eval_config():
    cfg = yaml.safe_load((ROOT_DIR / "eval" / "config.yaml").read_text())

    ablation_names = {a.get("name") for a in cfg.get("ablation_runs") or []}
    assert "naive_baseline" in ablation_names, (
        "ADR 0001 — `naive_baseline` must remain in eval/config.yaml "
        "`ablation_runs`. It is the side-by-side comparison floor every "
        "other ablation is measured against; removing it silently "
        "invalidates every ablation delta. If a legitimate change "
        "demands its removal, write an ADR superseding 0001 first."
    )

    assert "naive_baseline" in (cfg.get("latency_budgets") or {}), (
        "`latency_budgets.naive_baseline` is the absolute p95 ceiling "
        "enforced by scripts/check_latency_slo.py. Removing it silently "
        "disables the baseline ablation's latency regression gate."
    )


# ---------------------------------------------------------------------------
# G4 — every ADR row in docs/adr/README.md resolves to a file on disk and
# vice versa (CLAUDE.md "Prohibited: Deleting or renaming ADR files").
# ---------------------------------------------------------------------------


_ADR_INDEX_ROW_RE = re.compile(
    r"\|\s*\[(\d{4})\]\(\./(\d{4}-[^)]+\.md)\)\s*\|"
)


def _parsed_adr_index() -> list[tuple[str, str]]:
    readme = (ROOT_DIR / "docs" / "adr" / "README.md").read_text()
    rows = _ADR_INDEX_ROW_RE.findall(readme)
    assert rows, (
        "Could not parse any ADR rows in docs/adr/README.md. "
        "Expected rows of the form `| [NNNN](./NNNN-slug.md) | status | title |`."
    )
    return rows


def test_adr_index_rows_resolve_to_files():
    adr_dir = ROOT_DIR / "docs" / "adr"
    for number, filename in _parsed_adr_index():
        path = adr_dir / filename
        assert path.exists(), (
            f"ADR {number} is listed in docs/adr/README.md but the file "
            f"{filename!r} does not exist. CLAUDE.md Prohibited: "
            f"'Deleting or renaming ADR files. Mark Superseded in the "
            f"Status block; keep the file.' Restore the file or remove "
            f"the README row with an explicit ADR-renumber rationale."
        )


def test_no_unlinked_adr_files_on_disk():
    adr_dir = ROOT_DIR / "docs" / "adr"
    indexed = {filename for _, filename in _parsed_adr_index()}
    for path in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        assert path.name in indexed, (
            f"ADR file {path.name!r} exists on disk but is not listed in "
            f"docs/adr/README.md index table. Either add a row to the "
            f"index (preferred) or delete the file with a rationale in "
            f"the PR description."
        )


# ---------------------------------------------------------------------------
# G5 — rag_core.py must not introduce a pydantic/TypedDict class that
# shadows the answer dict (CLAUDE.md "Prohibited"; ADR 0003).
# ---------------------------------------------------------------------------


_SHADOW_BASES = {"BaseModel", "TypedDict"}


def test_rag_core_has_no_shadow_answer_models():
    tree = ast.parse((ROOT_DIR / "rag_core.py").read_text())

    offenders: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name: str | None = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in _SHADOW_BASES:
                offenders.append((node.name, base_name, node.lineno))

    assert not offenders, (
        "rag_core.py defines class(es) that shadow the answer dict:\n"
        + "\n".join(
            f"  - line {ln}: class {name}({base})"
            for name, base, ln in offenders
        )
        + "\n\nCLAUDE.md Prohibited: 'Adding a parallel pydantic / "
        "TypedDict model that shadows run_rag_query's answer dict — "
        "the dict is the contract (ADR 0003).' The answer dict is "
        "constructed near rag_core.py:2778 with `ANSWER_SCHEMA_VERSION`; "
        "bump that constant on contract change, but do not introduce a "
        "parallel class. If a structural model is genuinely needed, "
        "write an ADR superseding 0003 first."
    )


# ---------------------------------------------------------------------------
# G6 — docs/senior-positioning.md narrative must stay in sync with the
# actual docs/adr/ directory (issue #317).
#
# The narrative mirrors three pieces of ADR-directory state:
#   1. an "{N}개 ADR" count label (in the signal-overview table intro AND
#      in an in-body interview talking-point quote),
#   2. an "{N} accepted / {M} proposed" status breakdown alongside (1),
#   3. an ADR table with one row per `docs/adr/NNNN-*.md` file, each row
#      carrying a status cell that must match the file's
#      `- **Status**: ...` header.
#
# Without these guards, merging a new ADR (or flipping a status from
# proposed → accepted) silently drifts the reviewer-facing narrative.
# ---------------------------------------------------------------------------


_SENIOR_POS_PATH = ROOT_DIR / "docs" / "senior-positioning.md"

_SENIOR_POS_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(\./adr/(\d{4}-[^)]+\.md)\)\s*\|\s*(\w+)\s*\|",
    re.MULTILINE,
)

_SENIOR_POS_COUNT_RE = re.compile(r"(\d+)\s*개\s+ADR")

_SENIOR_POS_STATUS_LABEL_RE = re.compile(
    r"(\d+)\s+accepted\s*/\s*(\d+)\s+proposed"
)

_ADR_STATUS_HEADER_RE = re.compile(
    r"^-\s*\*\*Status\*\*\s*:\s*(\w+)\s*$",
    re.MULTILINE,
)


def _adr_files() -> list[Path]:
    return sorted(
        (ROOT_DIR / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")
    )


def _adr_statuses() -> dict[str, str]:
    """Map ADR number ('0001') -> declared status ('accepted'/'proposed')."""
    result: dict[str, str] = {}
    for path in _adr_files():
        m = _ADR_STATUS_HEADER_RE.search(path.read_text())
        assert m, (
            f"ADR {path.name}: missing `- **Status**: ...` header line. "
            f"Add it near the top of the file (see ADR 0001 for the pattern)."
        )
        result[path.name[:4]] = m.group(1)
    return result


def test_senior_positioning_count_label_matches_adr_files():
    text = _SENIOR_POS_PATH.read_text()
    label_values = {int(n) for n in _SENIOR_POS_COUNT_RE.findall(text)}
    assert label_values, (
        "docs/senior-positioning.md must contain a '{N}개 ADR' count label."
    )
    actual = len(_adr_files())
    assert label_values == {actual}, (
        f"senior-positioning.md '{{N}}개 ADR' labels = {sorted(label_values)}, "
        f"docs/adr/ file count = {actual}. Issue #317: when a new ADR is "
        f"merged, update every '{{N}}개 ADR' occurrence in "
        f"docs/senior-positioning.md (signal-overview table intro + interview "
        f"talking-point quote)."
    )


def test_senior_positioning_status_breakdown_matches_adr_files():
    text = _SENIOR_POS_PATH.read_text()
    m = _SENIOR_POS_STATUS_LABEL_RE.search(text)
    assert m, (
        "docs/senior-positioning.md must contain a "
        "'{N} accepted / {M} proposed' status breakdown label "
        "(near the '{N}개 ADR' count)."
    )
    declared = (int(m.group(1)), int(m.group(2)))

    statuses = list(_adr_statuses().values())
    actual = (statuses.count("accepted"), statuses.count("proposed"))

    assert declared == actual, (
        f"senior-positioning.md status breakdown = "
        f"{declared[0]} accepted / {declared[1]} proposed, "
        f"actual ADR file headers = "
        f"{actual[0]} accepted / {actual[1]} proposed. "
        f"Issue #317: update the breakdown label whenever an ADR's "
        f"`- **Status**: ...` header changes or a new ADR is added."
    )


def test_senior_positioning_table_rows_match_adr_files():
    text = _SENIOR_POS_PATH.read_text()
    rows = _SENIOR_POS_ROW_RE.findall(text)
    assert rows, (
        "docs/senior-positioning.md must contain ADR table rows of the form "
        "`| [NNNN](./adr/NNNN-slug.md) | <status> | ... |`."
    )

    narrative_numbers = {row[0] for row in rows}
    narrative_filenames = {row[1] for row in rows}
    narrative_status_by_num = {row[0]: row[2] for row in rows}

    actual_files = _adr_files()
    actual_numbers = {p.name[:4] for p in actual_files}
    actual_filenames = {p.name for p in actual_files}
    actual_statuses = _adr_statuses()

    assert narrative_numbers == actual_numbers, (
        f"ADR set drift between docs/senior-positioning.md table and "
        f"docs/adr/ files.\n"
        f"  missing from narrative: "
        f"{sorted(actual_numbers - narrative_numbers)}\n"
        f"  unknown in narrative:   "
        f"{sorted(narrative_numbers - actual_numbers)}\n"
        f"Issue #317: add/remove rows in docs/senior-positioning.md so the "
        f"narrative table tracks the directory."
    )

    assert narrative_filenames == actual_filenames, (
        f"ADR filename drift between narrative table link targets and "
        f"docs/adr/. Check `./adr/...` link targets in "
        f"senior-positioning.md.\n"
        f"  narrative-only: "
        f"{sorted(narrative_filenames - actual_filenames)}\n"
        f"  disk-only:      "
        f"{sorted(actual_filenames - narrative_filenames)}"
    )

    mismatches = [
        (n, narrative_status_by_num[n], actual_statuses[n])
        for n in sorted(narrative_numbers)
        if narrative_status_by_num[n] != actual_statuses[n]
    ]
    assert not mismatches, (
        "Status cell drift between senior-positioning.md table and ADR "
        "file `- **Status**:` headers:\n"
        + "\n".join(
            f"  {n}: narrative={narr!r}, file={file!r}"
            for n, narr, file in mismatches
        )
        + "\nIssue #317: update the status cell in the narrative row when "
        "the ADR file's status changes (e.g., proposed -> accepted)."
    )
