#!/usr/bin/env python3
"""Single source of truth for the load-bearing path list (CLAUDE.md).

A "load-bearing" path is one whose change requires PR template item 5b
(real-data eval delta) per CLAUDE.md and the PR #69 lesson — synthetic
CI delta alone missed an intended-abstention regression there.

Three call sites that previously hardcoded their own copy now read this
module:

- `.githooks/pre-push` (soft-warn reminder)
- `scripts/claude-hooks/pretooluse-loadbearing.sh` (Claude awareness)
- `.github/workflows/branch-and-issue-check.yml` via
  `scripts/check_branch_and_issue.py --check-5b` (hard-fail CI gate)

Exit codes:
    0  match (CLI succeeded — for --is-load-bearing / --any-match
       this means "path is load-bearing")
    1  no match
    2  internal / usage error
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple


# Canonical load-bearing path list. The order is not significant; add
# new entries here and the three consumers above pick them up
# automatically. Entries ending in "/" are treated as directories
# (prefix match); others as files (exact name or "/<name>" suffix match).
LOAD_BEARING_PATHS: list[str] = [
    "rag_core.py",
    "rag_retrieval.py",
    "rag_verifier.py",
    "rag_answer.py",
    "rag_query.py",
    "ingestion.py",
    "visual_ingestion.py",
    "eval/",
    "api/",
    "docs/adr/",
    "scripts/build_index.py",
]


# Numeric thresholds shared across the governance surface. Single source
# of truth for hook scripts, the self-review collector, and any future
# CI gate. SKILL.md (`.claude/skills/self-review-quarterly/SKILL.md`) is
# the parallel SoT for *grading bands* (✓/△/✗); this dict only holds the
# *raw values* that bash hooks + python collectors need to agree on.
THRESHOLDS: dict[str, int] = {
    # PR #747 PreToolUse MEMORY.md line-count matcher
    "MEMORY_LINE_AWARE": 20,
    "MEMORY_LINE_BLOCK": 30,
    # PR #745 axis #2 (Agent delegation) non-trivial-PR LOC cut-off
    "AXIS_2_LOC": 50,
    # ADR 0047 proposed-status lifecycle SLA, in days. proposed_adr_age()
    # flags proposed ADRs first committed on/after 2026-05-15 that exceed it.
    "ADR_PROPOSED_SLA_DAYS": 30,
}


# ---------------------------------------------------------------------------
# Outcome telemetry — v2-5field hook-fires.log emit (ADR 0060, issue #1039).
#
# Canonical fire-log format:
#     <ts>|<outcome>|<hook>|<category>|<path>[|<extra>]
#
# emit_hook_fire() is the single helper used by both bash hooks (via the
# `--emit-fire` CLI subcommand) and Python collectors. KNOWN_OUTCOMES /
# KNOWN_HOOKS enforce typo guard so silent drift between hook scripts is
# caught at emit time, not at analysis time.
# ---------------------------------------------------------------------------

KNOWN_OUTCOMES: set[str] = {
    "aware",            # stderr warning only, exit 0
    "blocked",          # exit 2 refuse
    "bypassed",         # user explicitly skipped (--no-verify, env var)
    "false_positive",   # hook fired but action was legitimate (manual tag)
    "false_negative",   # hook should have fired but didn't (manual tag)
    "nudged",           # UserPromptSubmit stdout context injection
    "pipeline_start",   # stop-ship pipeline began
    "pipeline_end",     # stop-ship pipeline completed (success or abort)
    "ok",               # legacy memory-lines silent pass
}

KNOWN_HOOKS: set[str] = {
    "bash-guard",
    "loadbearing",
    "memory-lines",
    "adr-template",
    "adr-collision",
    "plan-slug-race",
    "delegation-gate",
    "stop-ship",
}


def emit_hook_fire(
    outcome: str,
    hook: str,
    category: str = "",
    path: str = "",
    extra: str = "",
    log_path: str | Path = ".claude/.hook-fires.log",
) -> None:
    """Append a v2-5field event to the canonical hook-fires log.

    Format (ADR 0060):
        <ts>|<outcome>|<hook>|<category>|<path>[|<extra>]

    Raises ``ValueError`` on unknown outcome / hook (silent-drift guard).
    I/O errors are swallowed — telemetry must never block the hook.
    """
    if outcome not in KNOWN_OUTCOMES:
        raise ValueError(
            f"unknown outcome: {outcome!r}; valid: {sorted(KNOWN_OUTCOMES)}"
        )
    if hook not in KNOWN_HOOKS:
        raise ValueError(
            f"unknown hook: {hook!r}; valid: {sorted(KNOWN_HOOKS)}"
        )
    import datetime as _dt
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = [ts, outcome, hook, category, path]
    if extra:
        fields.append(extra)
    line = "|".join(fields) + "\n"
    p = Path(log_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        # Telemetry must never block the hook. Swallow silently.
        pass


def _normalize(path: str) -> str:
    if path.startswith("./"):
        return path[2:]
    return path


def is_load_bearing(path: str) -> bool:
    """Return True if `path` matches any canonical load-bearing entry.

    Accepts both repo-relative paths (`rag_core.py`, `eval/config.yaml`)
    and absolute paths (`/Users/.../rag_core.py`). Matching is anchored
    so that `myapi/main.py` does NOT match the `api/` directory entry.
    """
    if not path:
        return False
    p = _normalize(path)
    for entry in LOAD_BEARING_PATHS:
        if entry.endswith("/"):
            stripped = entry.rstrip("/")
            if p == stripped or p.startswith(entry) or f"/{entry}" in p:
                return True
        else:
            if p == entry or p.endswith("/" + entry):
                return True
    return False


# ---------------------------------------------------------------------------
# ADR number reservation (issue #757 — A2 fix from governance self-audit).
#
# CLAUDE.md `Reserve ADR numbers up front` rule was manual + repeatedly
# broken under concurrent worktree work (collisions 0022→0023, 0023→0025,
# 0029→0030; live collision on 0044 caught 2026-05-15). These helpers and
# the pre-commit hook that calls them make the rule mechanical.
#
# Scope deliberately small:
#   - Filesystem scan only (no `gh pr list` — keeps the hook offline-safe).
#   - Catches duplicate `NNNN-*.md` in the same worktree, which is the
#     concrete failure mode after a merge from another branch that also
#     added an ADR with the same number.
#   - Cross-worktree / open-PR collisions still need manual `gh pr list
#     --search "ADR" --state open` before drafting, per CLAUDE.md.
# ---------------------------------------------------------------------------

ADR_DIR_DEFAULT = "docs/adr"

# Phase 4 retrieval-eval artifacts under reports/retrieval/phase4*/ are
# committable (allowlisted in .gitignore) but live OUTSIDE the pre-commit ADR
# 0005 path block, which only matches `^reports/real[^/]*/` and so never sees
# `reports/retrieval/...`. Two merged PRs leaked private real-eval data this
# way — #1108 (coverage.json sample_queries = raw query text) and #1123
# (raw_results.json per-case agency/project labels). The committable boundary
# is "qid + categories + metric values only" (ADR 0005 private-local + ADR
# 0065). This set is the forbidden dict-key list for a CONTENT scan the
# path-regex hook structurally cannot perform. Exact-key match, so safe
# siblings (`query_type`, `agency_match`, `has_gold_agency`, …) never trip it.
PHASE4_PRIVATE_KEYS: frozenset[str] = frozenset(
    {
        "query",              # raw query text
        "sample_queries",     # raw query text (coverage.json buckets, #1108)
        "gold_agency",        # private 발주기관 label (raw_results.json, #1123)
        "gold_project",       # private 사업명 label
        "extracted_agency",   # query-time extracted agency string
        "extracted_project",  # query-time extracted project string
    }
)
PHASE4_ARTIFACT_GLOB = "reports/retrieval/phase4*"

# Issue #1204: a structural (no-name-list) privacy gate for committable
# eval-data JSON. The Phase 4 key-name gate above only catches a fixed set of
# forbidden KEYS; it misses private VALUES that hide elsewhere — qids that
# embed 발주기관/사업명 (`real_<agency>_<topic>`), retry-reason map KEYS that
# embed agency names or 공고번호 doc-ids after a colon
# (`missing_comparison_entity:<agency>`), and eda agency labels. Listing the
# 73 real agency names in this committed source would itself re-leak them, so
# the gate is purely STRUCTURAL: under the eval-data globs, a committable JSON
# artifact must contain (a) zero Hangul codepoints anywhere (anonymized qids
# are `real_<hex>`; categories/query_type are ASCII; metrics are numeric) and
# (b) zero dict KEYS containing a colon (retry-reason payloads are stripped to
# their enum prefix). reports/self_review_agreement/ is intentionally NOT in
# scope — its axis labels are public Korean prose, not private RFP data.
EVAL_PRIVACY_ARTIFACT_GLOBS = ("reports/retrieval", "reports/real100")
_EVAL_PRIVACY_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏ꥠ-꥿]")

# Private real-eval readiness scaffold: local inputs, raw outputs, and private
# indexes must remain ignored. The redacted aggregate summary is the only
# default private-real output path that may cross the commit boundary after
# exporter + governance checks pass.
PRIVATE_REAL_EVAL_REQUIRED_IGNORES: tuple[str, ...] = (
    "eval/real_config.local.yaml",
    "configs/eval/private_real_eval.local.yaml",
    "data/files/",
    "data/files_kordoc/",
    "data/private/",
    "data/data_list.csv",
    "data/index/real100/",
    "data/index/real100_kordoc/",
    "data/index-private-hardcase/",
    "experiments/private_runs/",
    "reports/real100/eval_summary.json",
    "reports/real100/raw/",
    "reports/private_real_eval_summary.raw.json",
)
PRIVATE_REAL_EVAL_REDACTED_SUMMARIES: tuple[str, ...] = (
    "reports/private_real_eval_summary.redacted.json",
)
PRIVATE_REDACTED_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "question",
        "answer",
        "support_text",
        "claims",
        "citations",
        "gold_evidence",
        "retrieved_chunks",
        "text",
        "text_preview",
        "doc_id",
        "chunk_id",
        "file",
        "file_name",
        "filename",
        "path",
        "config_path",
        "index_dir",
        "output_dir",
        "document_text",
        "raw_text",
        "file_path",
        "absolute_path",
    }
)
_ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(^|[\s'\"])/(Users|home|private|var|tmp|Volumes)/[^\s'\"]+"
)

# Issue #818: detection-only relaxation. The kebab-lowercase slug remains the
# *convention* (see ``docs/adr/README.md`` File layout), but the live bug
# discovery on ``0044-realN-eval-case-expansion.md`` showed that a strict
# lowercase character class silently hides legitimate-but-mixed-case ADRs from
# the pre-commit collision scanner and from ``--next-adr-number``. We widen
# the character class to accept ``[a-zA-Z0-9]`` so detection is robust; a
# separate lint that warns when an ADR slug is mixed-case is out of scope.
ADR_FILENAME_RE = re.compile(r"^(\d{4})-[a-zA-Z0-9][a-zA-Z0-9-]*\.md$")


def existing_adr_numbers(adr_dir: str | Path = ADR_DIR_DEFAULT) -> set[int]:
    """Return ADR numbers found as `NNNN-slug.md` files in `adr_dir`.

    Ignores `README.md`, `_template.md`, and any file not matching the
    canonical `NNNN-slug.md` pattern. Returns an empty set if the
    directory is missing — callers decide whether that's an error.
    """
    p = Path(adr_dir)
    if not p.is_dir():
        return set()
    found: set[int] = set()
    for entry in p.iterdir():
        if not entry.is_file():
            continue
        m = ADR_FILENAME_RE.match(entry.name)
        if m:
            found.add(int(m.group(1)))
    return found


def next_adr_number(adr_dir: str | Path = ADR_DIR_DEFAULT) -> int:
    """Return the next available ADR number (max existing + 1, or 1 if empty).

    Filesystem-only — does NOT inspect open PRs in concurrent worktrees.
    Per CLAUDE.md `Reserve ADR numbers up front`, also run
    `gh pr list --search "ADR" --state open` before drafting.
    """
    nums = existing_adr_numbers(adr_dir)
    if not nums:
        return 1
    return max(nums) + 1


def find_duplicate_adr_numbers(
    adr_dir: str | Path = ADR_DIR_DEFAULT,
) -> dict[int, list[str]]:
    """Return ``{number: [filenames…]}`` for ADR numbers used by 2+ files.

    Empty dict means no collisions. Used by the pre-commit hook to fail
    fast when a merge or concurrent worktree drop produced two ADRs with
    the same NNNN prefix.
    """
    p = Path(adr_dir)
    if not p.is_dir():
        return {}
    by_num: dict[int, list[str]] = {}
    for entry in p.iterdir():
        if not entry.is_file():
            continue
        m = ADR_FILENAME_RE.match(entry.name)
        if m:
            num = int(m.group(1))
            by_num.setdefault(num, []).append(entry.name)
    return {n: sorted(names) for n, names in by_num.items() if len(names) > 1}


# ---------------------------------------------------------------------------
# ADR Consequences verification lint (issue #793 — B3 fix from governance
# self-audit).
#
# ADR 0041 promised `stage_attempts` telemetry, ADR 0042 promised a
# regression test, ADR 0043 promised PR comments — and nothing actively
# checks any of it. Without a verification circuit, ADRs become Decision
# Theatre: "we wrote it down" with no signal months later about whether
# the commitment held.
#
# The contract introduced here is tiny:
#
#   ## Verification
#   <!-- verifies-key: <relative-path>:<key-substring> -->
#
# `lint_adr_verification()` confirms:
#   1. Verification H2 section present
#   2. ≥1 verifies-key marker
#   3. for each marker whose target file exists, the key substring
#      appears somewhere in that file (lenient — substring not JSON path)
#
# Step 3 is the actual two-way circuit B3 demanded. Step 2 is the floor
# (no marker = no claim = Decision Theatre survives). Pre-commit hook
# applies this only to *newly added* ADR files so the 41 existing ADRs
# are grandfathered; retrofit happens per-ADR in follow-up PRs.
# ---------------------------------------------------------------------------

ADR_VERIFIES_KEY_RE = re.compile(
    r"<!--\s*verifies-key:\s*([^\s:][^:]*?)\s*:\s*([^\s>][^>]*?)\s*-->"
)
ADR_VERIFICATION_HEADER_RE = re.compile(r"^##\s+Verification\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# ADR ↔ README index parity (issue #803).
#
# `tests/test_governance.py::test_no_unlinked_adr_files_on_disk` enforces
# parity in CI Pytest. That runs *after* push, so a missing index row
# reds main on merge and cascades a red Pytest gate across every open PR
# until someone authors a fix. The pre-commit hook calls
# ``adr_readme_parity_violations`` to shift this same check left so the
# author finds out at ``git commit`` time.
#
# The check is deliberately string-grep on the staged README text rather
# than a markdown parser — it must match exactly the row format the
# Pytest gate parses (``| [NNNN](./NNNN-slug.md) |``) and stay zero-dep
# (Python stdlib + git).
# ---------------------------------------------------------------------------


_ADR_INDEX_ROW_RE = re.compile(
    r"\|\s*\[(\d{4})\]\(\./(\d{4}-[^)]+\.md)\)\s*\|"
)


def adr_readme_parity_violations(
    adr_filenames: list[str],
    readme_text: str,
) -> list[str]:
    """Return the ADR filenames that have no matching row in ``readme_text``.

    A "matching row" follows the canonical index format::

        | [NNNN](./NNNN-slug.md) | status | title |

    which is what ``test_no_unlinked_adr_files_on_disk`` already parses
    (see ``tests/test_governance.py::_ADR_INDEX_ROW_RE``). Empty input
    returns an empty list — the caller should only invoke this when at
    least one ADR file is staged for add/rename.
    """
    rows = {filename for _, filename in _ADR_INDEX_ROW_RE.findall(readme_text)}
    missing: list[str] = []
    for path in adr_filenames:
        name = Path(path).name
        if name not in rows:
            missing.append(name)
    return missing


# ---------------------------------------------------------------------------
# Top-level README ADR-count parity (issue #1156).
#
# README.md states the ADR count in two human-facing spots — the prose
# headline ("… 59개 설계 결정 (ADR).") and the 주요 링크 table row
# ("| ADR 인덱스 (59개 결정) | … |"). Both were hand-edited and re-staled
# every time an ADR landed in a concurrent worktree (#1059 corrected the
# number but not the mechanism — it was off-by-one the moment it merged).
#
# Source of truth for the count is the number of NNNN-slug.md ADR *files*,
# i.e. `len(existing_adr_numbers())` — the same canonical introspection
# `--next-adr-number` and the collision scanner already use. The
# docs/adr/README.md index is deliberately NOT the count SoT: its
# reopen-condition tables re-list ADRs (e.g. one row for `0019 + 0021`), so
# its row count exceeds the file count. File ↔ index-row parity is held by
# `test_repo_adr_dir_parity_today`, so the headline count and the ADR index
# cannot disagree once both are pinned to the file set.
#
# `rewrite_readme_adr_count` regenerates both spots (scripts/update_readme_
# metrics.py calls it on every metrics refresh); `readme_adr_count_violations`
# is the read-only check the pytest gate uses so drift cannot merge silently.
# Each pattern's *full match* is only the digit run (the surrounding Korean
# is a zero-width look-around), so a sub replaces just the number and a
# rewrite is idempotent.
# ---------------------------------------------------------------------------

_README_ADR_COUNT_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("prose headline", re.compile(r"\d+(?=개 설계 결정)")),
    ("주요 링크 table", re.compile(r"(?<=ADR 인덱스 \()\d+(?=개 결정\))")),
)


def rewrite_readme_adr_count(readme_text: str, count: int) -> str:
    """Return ``readme_text`` with every ADR-count claim set to ``count``.

    Idempotent — re-running with the already-correct count is a no-op. Only
    the digit run is rewritten; the surrounding text is preserved verbatim.
    """
    out = readme_text
    for _, pattern in _README_ADR_COUNT_PATTERNS:
        out = pattern.sub(str(count), out)
    return out


def readme_adr_count_violations(readme_text: str, expected_count: int) -> list[str]:
    """Return human-readable messages for ADR-count claims that disagree
    with ``expected_count`` (the SoT = number of NNNN-slug.md files).

    A claim already equal to ``expected_count`` is clean. Absence of any
    claim is NOT a violation — dropping the count (e.g. switching the
    headline to a bare ``docs/adr/README.md`` pointer) is an intentional act.
    """
    violations: list[str] = []
    for label, pattern in _README_ADR_COUNT_PATTERNS:
        for m in pattern.finditer(readme_text):
            stated = int(m.group(0))
            if stated != expected_count:
                violations.append(
                    f"README {label}: states {stated} ADRs, actual is {expected_count}"
                )
    return violations


# ---------------------------------------------------------------------------
# ADR file Status header ↔ README *main index* Status-column parity
# (issue #1181). The third README↔ADR parity dimension, alongside
# adr_readme_parity_violations (filename membership, #803) and
# readme_adr_count_violations (count, #1156): this compares the Status
# *cell*. Catches a proposed->accepted flip that updates the ADR file's
# `- **Status**:` header but leaves the docs/adr/README.md index row stale —
# which both the filename-parity check and test_no_unlinked_adr_files_on_disk
# miss (they only assert the row exists). Re-enables the status-sync
# guarantee the adr-lifecycle-manager skill had to walk back in #1165.
# ---------------------------------------------------------------------------

# The main index runs from the `## Index` H2 to the next H2 (or EOF). The
# `## Roadmap` ("Promote 조건") and `## Deferred decisions` tables reuse the
# same `| [NNNN](./NNNN-*.md) |` link form, but their 2nd column is a Title /
# locked-default, NOT a Status — slicing to this section is what keeps them
# out of the comparison.
_ADR_INDEX_SECTION_RE = re.compile(
    r"^##\s+Index\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
)

# A main-index row: ADR number, filename, then the Status cell (up to the
# next pipe). Unlike _ADR_INDEX_ROW_RE this also captures the status column.
# `^`-anchored (MULTILINE) so an inline link in a later column can't be
# mistaken for a row start.
_ADR_INDEX_STATUS_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(\./(\d{4}-[^)]+\.md)\)\s*\|\s*([^|]*?)\s*\|",
    re.MULTILINE,
)


def _normalize_adr_status(raw: str | None) -> str:
    """Reduce a Status string to its leading lifecycle word, lowercased.

    README index cells are canonical/short (`superseded by 0005`) while ADR
    file headers carry free-form suffixes (`Superseded`, `accepted
    (kordoc-corpus measurement landed ...)`). Comparing the first whitespace
    token lowercased collapses both onto the four states the README "Status
    lifecycle" table defines (proposed / accepted / superseded / deprecated)
    — the only distinction a status-drift check needs. Empty / None -> "".
    """
    head = (raw or "").strip().lower().split()
    return head[0] if head else ""


def adr_readme_status_violations(
    adr_dir: str | Path,
    readme_text: str,
) -> list[str]:
    """Return messages where an ADR file's Status disagrees with its row in
    the docs/adr/README.md *main index* Status column. Empty list = clean.

    Complements ``adr_readme_parity_violations`` (filename membership):
    compares the Status *column* on the normalized leading lifecycle word
    (see ``_normalize_adr_status``), so a canonical README cell
    (`superseded by 0005`) matches a file header of `Superseded`, and a
    free-form file suffix (`accepted (kordoc-corpus ...)`) matches a bare
    README `accepted`. Reuses ``parse_adr_status`` for the file side.

    Only the main index (between `## Index` and the next H2) is parsed; the
    Roadmap / `Promote 조건` and Deferred-decisions tables are excluded. ADRs
    present on disk but absent from the index (or vice versa) are out of
    scope here — ``adr_readme_parity_violations`` /
    ``test_no_unlinked_adr_files_on_disk`` own that membership check.

    Fails *loud* (returns a violation) rather than passing vacuously if the
    `## Index` section can't be located or parses zero rows; otherwise a
    renamed header would silently disable the check.
    """
    section = _ADR_INDEX_SECTION_RE.search(readme_text)
    if section is None:
        return [
            "docs/adr/README.md: '## Index' section not found — cannot "
            "verify ADR status parity. If the header was renamed, update "
            "_ADR_INDEX_SECTION_RE in scripts/_governance.py."
        ]
    readme_status = {
        num: _normalize_adr_status(cell)
        for num, _, cell in _ADR_INDEX_STATUS_ROW_RE.findall(
            section.group(1)
        )
    }
    if not readme_status:
        return [
            "docs/adr/README.md: main index parsed zero status rows — the "
            "table format likely changed. Update _ADR_INDEX_STATUS_ROW_RE "
            "in scripts/_governance.py."
        ]

    violations: list[str] = []
    for adr_path in sorted(Path(adr_dir).glob("[0-9][0-9][0-9][0-9]-*.md")):
        num = adr_path.name[:4]
        if num not in readme_status:
            continue  # membership is adr_readme_parity_violations' job
        file_status = _normalize_adr_status(parse_adr_status(adr_path))
        if file_status and file_status != readme_status[num]:
            violations.append(
                f"{adr_path.name}: file Status '{file_status}' != README "
                f"index Status '{readme_status[num]}'"
            )
    return violations


# ---------------------------------------------------------------------------
# ADR ↔ ADR supersede cross-ref integrity (issue #1077). The fourth ADR
# integrity lint, alongside the README-parity trio (#803 membership / #1156
# count / #1181 status). Those three compare an ADR file against its
# docs/adr/README.md row; this one compares *ADR files against each other*.
#
# The recurrence #1077 targets: an ADR that supersedes / changes the invariant
# of an older ADR lands without the older ADR getting its Status block +
# cross-ref updated (ADR 0022's proposed->accepted flip surfaced only in a
# later external-review round). PR #1068/#1075 patched instances after the
# fact; this shifts the *structural* half left to PR time.
#
# Hard semantic enforcement is impossible without false positives (issue
# #1027 philosophy: CI enforces structure, reviewers enforce meaning). The
# repo's accepted consolidation convention (e.g. ADR 0005/0011 absorb several
# ADRs in prose, NOT via a structured `Supersedes` field) means a full
# reciprocity rule would mis-fire on ~10 legitimate pairs. So this lint is
# scoped to three rules that pass clean on the current tree:
#
#   R1 self-consistency : an ADR carrying a `Superseded by NNNN` cross-ref
#                         must have 'superseded' in its Status (catches a
#                         back-pointer added without flipping Status).
#   R2 dangling         : every `Superseded by` / `Supersedes` target NNNN
#                         must be an ADR file that exists (catches typos).
#   R3 forward recip.   : an ADR declaring `Supersedes NNNN` via the
#                         structured field must have the target carry a
#                         matching `Superseded by` back-pointer (catches the
#                         #1077 forget-to-update-target case; also nudges new
#                         ADRs toward the structured field).
#
# Deliberately NOT enforced: reverse reciprocity (`Superseded by` ⇒ the
# superseder must declare a structured `Supersedes`). That conflicts with the
# prose-consolidation convention. README Status-column drift is already owned
# by adr_readme_status_violations (#1181), so it is not re-checked here.
# ---------------------------------------------------------------------------

# Dedicated metablock-or-list fields. Tolerant of a leading table pipe
# (`| **Superseded by** | ... |`) and a list bullet (`- **Superseded by**:`).
# `[:|]` accepts both the `: value` (list) and `| value` (table) separators.
_ADR_SUPERSEDED_BY_FIELD_RE = re.compile(
    r"^[ \t]*(?:\|[ \t]*)?(?:[-*][ \t]*)?\*\*Superseded by\*\*"
    r"[ \t]*[:|][ \t]*(?P<val>.+?)[ \t]*\|?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_ADR_SUPERSEDES_FIELD_RE = re.compile(
    r"^[ \t]*(?:\|[ \t]*)?(?:[-*][ \t]*)?\*\*Supersedes\*\*"
    r"[ \t]*[:|][ \t]*(?P<val>.+?)[ \t]*\|?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# A "superseded by ... NNNN" relationship can also live inside the Status
# value (e.g. ADR 0036: `Status: superseded by [0049](...)`). Non-greedy so it
# binds the FIRST 4-digit run after "superseded by" (the target), not a later
# year/number elsewhere in the value.
_ADR_STATUS_SUPERSEDED_BY_RE = re.compile(
    r"superseded\s+by\b.*?(\d{4})", re.IGNORECASE
)
# Target extractor for a FIELD value: a markdown link (`[0049]` / `[ADR 0005]`)
# or an `ADR NNNN` prose ref. Bare 4-digit runs are intentionally NOT matched
# so a stray year (e.g. "2026") in a free-form field can't become a phantom
# dangling-pointer target.
_ADR_FIELD_TARGET_RE = re.compile(
    r"\[(?:ADR\s*)?(\d{4})\]|ADR\s*(\d{4})", re.IGNORECASE
)


def _adr_field_targets(value: str) -> set[str]:
    """Return the set of ADR numbers referenced in a supersede field value.

    Em-dash / 'N/A' / empty placeholders (`| **Supersedes** | — |`) yield an
    empty set because they contain no link or `ADR NNNN` token.
    """
    return {
        next(g for g in m.groups() if g)
        for m in _ADR_FIELD_TARGET_RE.finditer(value)
    }


def _collect_adr_supersede_pointers(
    adr_dir: str | Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, bool]]:
    """Scan ``adr_dir`` and return three maps keyed by ADR number (NNNN str):

      - ``superseded_by``: NNNN -> {targets it claims supersede it}
      - ``supersedes``:    NNNN -> {targets it claims to supersede}
      - ``status_superseded``: NNNN -> Status contains 'superseded'

    ``superseded_by`` unions the dedicated `**Superseded by**` field and any
    `superseded by NNNN` form embedded in the Status value; ``supersedes``
    reads only the dedicated `**Supersedes**` field.
    """
    superseded_by: dict[str, set[str]] = {}
    supersedes: dict[str, set[str]] = {}
    status_superseded: dict[str, bool] = {}
    for path in sorted(Path(adr_dir).glob("[0-9][0-9][0-9][0-9]-*.md")):
        num = path.name[:4]
        text = path.read_text(encoding="utf-8", errors="replace")
        status = parse_adr_status(path) or ""
        status_superseded[num] = "superseded" in status

        sb: set[str] = set()
        for m in _ADR_SUPERSEDED_BY_FIELD_RE.finditer(text):
            sb |= _adr_field_targets(m.group("val"))
        for m in _ADR_STATUS_SUPERSEDED_BY_RE.finditer(status):
            sb.add(m.group(1))
        if sb:
            superseded_by[num] = sb

        sup: set[str] = set()
        for m in _ADR_SUPERSEDES_FIELD_RE.finditer(text):
            sup |= _adr_field_targets(m.group("val"))
        if sup:
            supersedes[num] = sup

    return superseded_by, supersedes, status_superseded


def adr_supersede_crossref_violations(adr_dir: str | Path) -> list[str]:
    """Return messages for broken ADR↔ADR supersede cross-refs (issue #1077).

    Empty list = clean. Implements R1 (self-consistency), R2 (dangling
    target), R3 (forward reciprocity) described in the section comment above.
    Pure filesystem read of ``adr_dir``; no git, no README.
    """
    superseded_by, supersedes, status_superseded = (
        _collect_adr_supersede_pointers(adr_dir)
    )
    present = {
        p.name[:4]
        for p in Path(adr_dir).glob("[0-9][0-9][0-9][0-9]-*.md")
    }
    violations: list[str] = []

    # R1 — a Superseded-by cross-ref without a 'superseded' Status.
    for x, targets in sorted(superseded_by.items()):
        if not status_superseded.get(x):
            violations.append(
                f"{x}: carries a 'Superseded by {sorted(targets)}' cross-ref "
                "but its Status block does not contain 'superseded' — flip "
                "the Status (the back-pointer and Status drifted apart)."
            )

    # R2 — dangling supersede targets in either direction.
    for x, targets in sorted(superseded_by.items()):
        for y in sorted(targets):
            if y not in present:
                violations.append(
                    f"{x}: 'Superseded by {y}' points at ADR {y}, which has "
                    "no file in docs/adr/ (typo'd or deleted cross-ref)."
                )
    for x, targets in sorted(supersedes.items()):
        for y in sorted(targets):
            if y not in present:
                violations.append(
                    f"{x}: 'Supersedes {y}' points at ADR {y}, which has no "
                    "file in docs/adr/ (typo'd or deleted cross-ref)."
                )

    # R3 — a structured `Supersedes Y` must be reciprocated by Y's
    # `Superseded by X` back-pointer. This is the #1077 forget-to-update catch.
    for x, targets in sorted(supersedes.items()):
        for y in sorted(targets):
            if y in present and x not in superseded_by.get(y, set()):
                violations.append(
                    f"{x}: declares 'Supersedes {y}' but ADR {y} has no "
                    f"'Superseded by {x}' back-pointer (add it to {y}'s "
                    "Status block or a dedicated `**Superseded by**` field)."
                )

    return violations


def adr_has_verification_section(adr_path: str | Path) -> bool:
    """Return True if the ADR file contains a `## Verification` H2 header."""
    p = Path(adr_path)
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8", errors="replace")
    return bool(ADR_VERIFICATION_HEADER_RE.search(text))


def extract_adr_verification_markers(
    adr_path: str | Path,
) -> list[tuple[str, str]]:
    """Return ``[(path, key_substring), ...]`` from `<!-- verifies-key: ... -->`.

    Empty list if the file is missing or contains no markers. Whitespace
    around the path / key is stripped. Order matches source order so the
    lint output reads top-to-bottom.
    """
    p = Path(adr_path)
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    return [
        (m.group(1).strip(), m.group(2).strip())
        for m in ADR_VERIFIES_KEY_RE.finditer(text)
    ]


def lint_adr_verification(
    adr_path: str | Path,
    repo_root: str | Path = ".",
) -> list[str]:
    """Return list of human-readable error messages; empty = clean.

    Lint rules:
      - section: `## Verification` H2 header must exist
      - markers: at least one `<!-- verifies-key: path:key -->`
      - resolvability: for each marker whose `path` file exists,
        the `key` substring must appear in the file content
      - missing target file (e.g. `reports/eval_summary.json` in a fresh
        clone) is NOT an error — just skipped silently. The hook fires
        in many envs that don't run `make real-eval`.
    """
    p = Path(adr_path)
    if not p.is_file():
        return [f"ADR file not found: {adr_path}"]

    text = p.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []

    if not ADR_VERIFICATION_HEADER_RE.search(text):
        errors.append("missing `## Verification` H2 section")
        return errors  # other checks moot without the section

    markers = [
        (m.group(1).strip(), m.group(2).strip())
        for m in ADR_VERIFIES_KEY_RE.finditer(text)
    ]
    if not markers:
        errors.append(
            "Verification section present but contains zero "
            "`<!-- verifies-key: <path>:<key> -->` markers"
        )
        return errors

    root = Path(repo_root)
    for rel_path, key in markers:
        target = root / rel_path
        if not target.exists():
            # Missing target file is informational, not fatal — many envs
            # don't generate reports/. Skip silently per docstring.
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"cannot read {rel_path}: {exc}")
            continue
        if key not in content:
            errors.append(
                f"key `{key}` not found in {rel_path} "
                "(marker exists but the measurement isn't wired up)"
            )

    return errors


# ---------------------------------------------------------------------------
# Proposed-ADR lifecycle SLA collector (ADR 0047 — deferred follow-up).
#
# ADR 0047 declared a 30-day SLA: a `Status: proposed` ADR first committed
# on/after 2026-05-15 must resolve within 30 days. 0047 decision #2 defines
# resolution two ways: a git-history Status mutation (accepted / superseded
# by NNNN / deprecated) — which drops the ADR out of the proposed filter
# entirely — OR an in-place `## Resolution` H2 paragraph append that records
# the outcome while Status legitimately stays `proposed`. The collector
# honors both: the latter surfaces as `resolved_in_place` instead of
# OVER_SLA (issue #1178), so an append-resolved ADR stops being a false
# OVER_SLA signal. 0047 fixed the contract but explicitly deferred the
# measurement collector ("proposed_adr_age(); 측정 collector 는 나중에").
# This implements that collector — reporting only (exit 0). The
# promote/supersede *decision* is a judgment layer (the adr-lifecycle-manager
# skill); any hard CI gate is a separate later policy choice.
#
# Pure/I-O split mirrors the readme-parity pair: status parsing is
# filesystem-pure, and the git first-commit-date lookup is injected via
# `date_resolver` so the core is unit-testable without a git repo.
# ---------------------------------------------------------------------------

# ADR 0047 acceptance date. Proposed ADRs first committed before this are
# grandfathered: reported, but never flagged OVER_SLA.
ADR_SLA_GRANDFATHER_DATE = date(2026, 5, 15)

# Tolerant of the three Status metablock forms live in docs/adr/:
#   - **Status**: proposed       (bold list item)
#   - Status: Proposed           (plain list item)
#   | **Status** | Proposed |    (2-column table — value in the next cell,
#                                  no colon; e.g. ADR 0052/0044/0034)
# First match on the file wins. The table branch must open with a pipe and
# terminate the value with one, since it lives between cells not after a colon.
ADR_STATUS_RE = re.compile(
    r"^\s*(?:"
    r"[-*]?\s*(?:\*\*)?status(?:\*\*)?\s*:\s*(?P<colon>.+?)"
    r"|"
    r"\|\s*(?:\*\*)?status(?:\*\*)?\s*\|\s*(?P<table>.+?)\s*\|"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ADR 0047 decision #2 sanctions an in-place `## Resolution` H2 append as a
# resolution even when Status stays `proposed`. Mirrors the
# `ADR_VERIFICATION_HEADER_RE` `## Verification` detector — exact H2, so
# `### Resolution` (H3) and `## Resolution notes` do NOT match.
ADR_RESOLUTION_HEADER_RE = re.compile(r"^##\s+Resolution\s*$", re.MULTILINE)


class ProposedADR(NamedTuple):
    number: int
    filename: str
    status: str
    first_commit: date | None
    age_days: int | None
    grandfathered: bool
    over_sla: bool
    # ADR 0047 in-place resolution: a `## Resolution` H2 was appended while
    # Status legitimately stays `proposed`. True suppresses `over_sla`.
    resolved_in_place: bool


def parse_adr_status(adr_path: str | Path) -> str | None:
    """Return the first Status meta-value (lowercased), or None.

    None if the file is missing or has no Status meta-line. Tolerant of the
    three variants present in docs/adr/: the bold (`- **Status**: proposed`)
    and plain (`- Status: Proposed`) list forms, and the 2-column metablock
    table form (`| **Status** | Proposed |`, e.g. ADR 0052) where the value
    lives in the next cell with no colon.
    """
    p = Path(adr_path)
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    m = ADR_STATUS_RE.search(text)
    if not m:
        return None
    value = m.group("colon")
    if value is None:
        value = m.group("table")
    return value.strip().lower()


def adr_has_resolution_section(adr_path: str | Path) -> bool:
    """Return True if the ADR file contains a `## Resolution` H2 header.

    This is the in-place resolution marker ADR 0047 decision #2 sanctions:
    a proposed ADR that appends `## Resolution` is resolved even though its
    Status stays `proposed`, so the SLA collector should stop flagging it
    OVER_SLA. Missing file → False. Mirrors ``adr_has_verification_section``.
    """
    p = Path(adr_path)
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8", errors="replace")
    return bool(ADR_RESOLUTION_HEADER_RE.search(text))


def _git_first_commit_date(path: str | Path) -> date | None:
    """First-add author date of `path` as a UTC calendar date, or None.

    `%aI` carries the commit's local tz (+09:00 KST in this repo); normalizing
    to UTC keeps the date on the same frame as the UTC `today` — else an ADR
    committed just after KST midnight ages to -1 until UTC rolls over.
    """
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "log", "--diff-filter=A", "--reverse",
             "--format=%aI", "--", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        dt = datetime.fromisoformat(lines[0].strip())
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.date()


def proposed_adr_age(
    adr_dir: str | Path = ADR_DIR_DEFAULT,
    *,
    date_resolver: Callable[[Path], date | None] | None = None,
    now: date | None = None,
    sla_days: int | None = None,
    grandfather_date: date = ADR_SLA_GRANDFATHER_DATE,
) -> list[ProposedADR]:
    """Return one ``ProposedADR`` per `Status: proposed` ADR, oldest first.

    ``over_sla`` is True iff the ADR was first committed on/after
    ``grandfather_date`` AND its age exceeds ``sla_days`` (ADR 0047) AND it
    carries no in-place resolution. ADRs first committed earlier carry
    ``grandfathered=True`` and are never flagged. Uncommitted files (no
    first-commit date) get ``age_days=None`` and ``over_sla=False``.

    ``resolved_in_place`` is True when the ADR appended a `## Resolution` H2
    section — ADR 0047 decision #2's sanctioned in-place resolution. Such an
    ADR is reported (Status still `proposed`) but never flagged ``over_sla``,
    so an append-resolved ADR is no longer a false OVER_SLA signal.

    ``date_resolver`` defaults to a git lookup; inject a stub for testing.
    ``sla_days`` defaults to ``THRESHOLDS["ADR_PROPOSED_SLA_DAYS"]``.
    """
    resolver = date_resolver or _git_first_commit_date
    today = now or datetime.now(timezone.utc).date()
    sla = THRESHOLDS["ADR_PROPOSED_SLA_DAYS"] if sla_days is None else sla_days

    records: list[ProposedADR] = []
    p = Path(adr_dir)
    if not p.is_dir():
        return records
    for entry in sorted(p.iterdir()):
        if not entry.is_file():
            continue
        m = ADR_FILENAME_RE.match(entry.name)
        if not m:
            continue
        status = parse_adr_status(entry)
        if status is None or not status.startswith("proposed"):
            continue
        resolved_in_place = adr_has_resolution_section(entry)
        first_commit = resolver(entry)
        if first_commit is None:
            age_days: int | None = None
            grandfathered = False
            over_sla = False
        else:
            # Floor at 0: a commit author-dated ahead of `today` (KST/+09:00
            # vs the runner's UTC clock) would otherwise yield a negative age.
            age_days = max(0, (today - first_commit).days)
            grandfathered = first_commit < grandfather_date
            over_sla = (not grandfathered) and (not resolved_in_place) and age_days > sla
        records.append(
            ProposedADR(
                number=int(m.group(1)),
                filename=entry.name,
                status=status,
                first_commit=first_commit,
                age_days=age_days,
                grandfathered=grandfathered,
                over_sla=over_sla,
                resolved_in_place=resolved_in_place,
            )
        )
    # Oldest first; uncommitted (age None) sort last.
    records.sort(key=lambda r: (r.age_days is None, -(r.age_days or 0)))
    return records


# ---------------------------------------------------------------------------
# Failure-rate ceiling ratchet enforcement (ADR 0062, issue #1150).
#
# ADR 0062 documents a "monotone-ratchet" contract: the failure-rate ceilings
# in tests/test_failure_rate_regression.py may only ratchet DOWN as fixes land
# — never up without an explicit [ALLOW_REGRESSION] justification in the PR
# body. But the in-test guard (test_ceilings_are_monotone_sane) only asserts
# ceiling >= the *current committed rate*; it never compares against the base
# branch, so a PR could RAISE a ceiling (loosening the gate) with every test
# still green. The ratchet was operator-discipline-only.
#
# These pure helpers + the check_branch_and_issue.py --check-ceiling-ratchet CI
# mode close that hole: diff the committed ceilings against the base branch and
# FAIL when any ceiling loosened (raised, or a gated category removed) unless
# the PR body carries [ALLOW_REGRESSION: <category> ...]. Parsing is AST-based
# (no import) so it works on a base-branch source string fetched via the GitHub
# contents API — importing it would pull in eval.scorers.failure_classifier.
# ---------------------------------------------------------------------------

# Flat-dict key for the scalar CEILING_TOTAL_FAILURE_RATE. Not one of the ADR
# 0075 FAILURE_CATEGORIES, so it cannot collide with a real category key.
TOTAL_FAILURE_RATE_KEY = "total_failure_rate"

_CEILING_DICT_NAME = "CEILING_RATE_BY_CATEGORY"
_CEILING_TOTAL_NAME = "CEILING_TOTAL_FAILURE_RATE"

# An [ALLOW_REGRESSION: <category> <old>→<new> reason] token. Only the leading
# category name is captured; old→new/reason are free-form (the token's job is
# to force acknowledgment, per ADR 0062, not to be machine-validated).
ALLOW_REGRESSION_RE = re.compile(r"\[ALLOW_REGRESSION:\s*([A-Za-z_][A-Za-z0-9_]*)")


def parse_failure_rate_ceilings(source: str) -> dict[str, float]:
    """Extract the ratchet ceilings from a test_failure_rate_regression.py source.

    Returns a flat ``{category: ceiling}`` dict with the scalar
    ``CEILING_TOTAL_FAILURE_RATE`` stored under ``TOTAL_FAILURE_RATE_KEY``.
    AST-based (``ast.literal_eval`` on the assignment values) so it parses a
    base-branch string fetched via ``git show`` / the GitHub contents API,
    which would fail to *import* (it pulls in eval.scorers.failure_classifier).

    Raises ``ValueError`` if either expected assignment is absent or is not a
    plain literal — a refactor that hides the ceilings from this parser must
    fail loudly rather than silently disable the ratchet gate.
    """
    tree = ast.parse(source)
    ceilings: dict[str, float] = {}
    found_dict = False
    found_total = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if _CEILING_DICT_NAME in names:
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                raise ValueError(f"{_CEILING_DICT_NAME} is not a dict literal")
            for k, v in value.items():
                ceilings[str(k)] = float(v)
            found_dict = True
        elif _CEILING_TOTAL_NAME in names:
            ceilings[TOTAL_FAILURE_RATE_KEY] = float(ast.literal_eval(node.value))
            found_total = True
    if not found_dict:
        raise ValueError(f"{_CEILING_DICT_NAME} assignment not found")
    if not found_total:
        raise ValueError(f"{_CEILING_TOTAL_NAME} assignment not found")
    return ceilings


def parse_allow_regression_categories(pr_body: str) -> set[str]:
    """Return the category names named in ``[ALLOW_REGRESSION: <category> ...]``.

    Empty set for an empty/None body or no tokens.
    """
    if not pr_body:
        return set()
    return {m.group(1) for m in ALLOW_REGRESSION_RE.finditer(pr_body)}


def ceiling_ratchet_violations(
    base: dict[str, float],
    head: dict[str, float],
    allowed: set[str],
    *,
    epsilon: float = 1e-9,
) -> list[str]:
    """Return one message per unjustified ceiling *loosening*; empty = clean.

    A loosening is either a RAISED ceiling (``head > base``) or a REMOVED gated
    category (present in ``base``, absent in ``head`` — drops the gate, strictly
    more permissive than any value). Each must be justified by an
    ``[ALLOW_REGRESSION: <category> ...]`` token (i.e. ``category in allowed``);
    otherwise it is a violation. New categories (absent in ``base``) and
    lowered/equal ceilings never violate — that is the monotone ratchet.
    """
    violations: list[str] = []
    for category, base_ceiling in sorted(base.items()):
        if category in head:
            head_ceiling = head[category]
            if head_ceiling > base_ceiling + epsilon and category not in allowed:
                violations.append(
                    f"{category}: ceiling raised {base_ceiling} → {head_ceiling} "
                    f"without [ALLOW_REGRESSION: {category} ...] in the PR body"
                )
        elif category not in allowed:
            violations.append(
                f"{category}: gated ceiling removed ({base_ceiling} → absent) "
                f"without [ALLOW_REGRESSION: {category} ...] in the PR body"
            )
    return violations


def _cmd_next_adr_number(adr_dir: str) -> int:
    sys.stdout.write(f"{next_adr_number(adr_dir):04d}\n")
    return 0


def _cmd_lint_adr_consequences(adr_path: str, repo_root: str) -> int:
    errors = lint_adr_verification(adr_path, repo_root)
    if not errors:
        return 0
    sys.stderr.write(f"\n❌ ADR Verification lint failed for {adr_path}:\n\n")
    for err in errors:
        sys.stderr.write(f"     - {err}\n")
    sys.stderr.write(
        "\n   Add a `## Verification` section with at least one machine-checkable\n"
        "   marker (see docs/adr/_template.md for the format). Existing ADRs are\n"
        "   grandfathered; this lint applies to newly added ADR files (issue #793).\n\n"
    )
    return 1


def _cmd_check_adr_readme_parity(
    adr_paths: list[str],
    readme_staged: bool,
    readme_path: str,
) -> int:
    """Hook-side parity check (issue #803).

    When ``readme_staged`` is true, the README content is read from the
    git index (``git show :docs/adr/README.md``) — that is the version
    the upcoming commit will publish. Otherwise the working-tree file
    at ``readme_path`` is read (useful for ad-hoc CLI calls and tests).
    """
    if readme_staged:
        import subprocess

        try:
            readme_text = subprocess.check_output(
                ["git", "show", f":{readme_path}"],
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(
                f"\n❌ Could not read staged {readme_path} via "
                f"`git show :{readme_path}`: {exc}\n"
                "   Is docs/adr/README.md present in the index?\n\n"
            )
            return 1
    else:
        try:
            readme_text = Path(readme_path).read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(
                f"\n❌ Could not read {readme_path}: {exc}\n\n"
            )
            return 1

    missing = adr_readme_parity_violations(adr_paths, readme_text)
    if not missing:
        return 0

    sys.stderr.write(
        "\n❌ ADR ↔ README index parity check failed (issue #803):\n\n"
    )
    for name in missing:
        sys.stderr.write(f"     - {name} has no row in docs/adr/README.md\n")
    sys.stderr.write(
        "\n   Add a row of the form\n"
        "       | [NNNN](./NNNN-slug.md) | proposed | one-line title |\n"
        "   under the Index section of docs/adr/README.md, stage it in\n"
        "   the same commit, then re-commit.\n\n"
        "   Why this hook fires at commit time:\n"
        "     - The CI gate `test_no_unlinked_adr_files_on_disk` is the\n"
        "       canonical check, but it only runs after push — a missing\n"
        "       row reds main on merge and cascades a red Pytest gate\n"
        "       across every open PR until a fix-up PR lands.\n"
        "     - Issues #730 / #732 / #750 are the recurrence trail.\n\n"
        "   Bypass with --no-verify only mid-merge; open a follow-up to\n"
        "   add the missing row.\n\n"
    )
    return 1


def _cmd_check_adr_readme_status(adr_dir: str, readme_path: str) -> int:
    """Working-tree status-parity check (issue #1181).

    Reads the working-tree README at ``readme_path`` and every ADR file in
    ``adr_dir``, then reports rows whose index Status cell disagrees with the
    ADR file's Status header. Unlike --check-adr-readme-parity there is no
    --readme-staged mode: the canonical gate is the pytest
    (tests/test_governance.py); the pre-commit hook calls this on the working
    tree (mirroring the markdown-deadlink hook), and the CI pytest backstops
    the committed state.
    """
    try:
        readme_text = Path(readme_path).read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"\n❌ Could not read {readme_path}: {exc}\n\n")
        return 1
    violations = adr_readme_status_violations(adr_dir, readme_text)
    if not violations:
        return 0
    sys.stderr.write(
        "\n❌ ADR ↔ README index Status parity check failed (issue #1181):\n\n"
    )
    for v in violations:
        sys.stderr.write(f"     - {v}\n")
    sys.stderr.write(
        "\n   Update the Status cell in the main index table of\n"
        f"   {readme_path} to match the ADR file's `- **Status**:` header\n"
        "   (leading lifecycle word: proposed / accepted / superseded /\n"
        "   deprecated), or fix the ADR file header. This complements the\n"
        "   filename-parity check (--check-adr-readme-parity): a row can\n"
        "   exist yet carry a stale status after a proposed->accepted flip.\n\n"
    )
    return 1


def _cmd_check_adr_crossref(adr_dir: str) -> int:
    """Working-tree ADR↔ADR supersede cross-ref integrity check (issue #1077).

    Scans every ADR file in ``adr_dir`` and reports broken supersede
    cross-refs (R1 status/back-pointer drift, R2 dangling target, R3 missing
    reciprocal back-pointer). The canonical gate is the pytest
    (tests/test_governance.py); the pre-commit hook calls this on the working
    tree (mirroring --check-adr-readme-status / the deadlink guard).
    """
    violations = adr_supersede_crossref_violations(adr_dir)
    if not violations:
        return 0
    sys.stderr.write(
        "\n❌ ADR ↔ ADR supersede cross-ref check failed (issue #1077):\n\n"
    )
    for v in violations:
        sys.stderr.write(f"     - {v}\n")
    sys.stderr.write(
        "\n   When an ADR supersedes another, BOTH files must stay in sync:\n"
        "     - the superseded ADR's Status block contains 'superseded' and a\n"
        "       `Superseded by [ADR NNNN]` pointer to the superseder, and\n"
        "     - if the superseder uses a `**Supersedes**` field, its target\n"
        "       carries the matching back-pointer.\n"
        "   This complements the README parity checks (membership / count /\n"
        "   status); it compares ADR files against each other, not the index.\n\n"
        "   Bypass with --no-verify only mid-merge; open a follow-up to sync.\n\n"
    )
    return 1


def _cmd_check_adr_collision(adr_dir: str) -> int:
    dups = find_duplicate_adr_numbers(adr_dir)
    if not dups:
        return 0
    sys.stderr.write(
        "\n❌ ADR number collision detected in "
        f"{adr_dir}:\n\n"
    )
    for num, names in sorted(dups.items()):
        sys.stderr.write(f"     ADR {num:04d}:\n")
        for name in names:
            sys.stderr.write(f"       - {name}\n")
    next_n = next_adr_number(adr_dir)
    sys.stderr.write(
        "\n   Resolve by renumbering one of the colliding files to the\n"
        f"   next available number (suggested: {next_n:04d}). Then update\n"
        "   the body, related ADRs, and docs/adr/README.md Index entry.\n\n"
        "   Use:\n"
        "       python scripts/_governance.py --next-adr-number\n\n"
        "   This collision is exactly the failure mode CLAUDE.md\n"
        "   `Reserve ADR numbers up front` warned about. Issue #757\n"
        "   added this hook so the rule survives without manual\n"
        "   discipline.\n\n"
    )
    return 1


def _cmd_proposed_adr_age(adr_dir: str) -> int:
    records = proposed_adr_age(adr_dir)
    if not records:
        sys.stdout.write("(no proposed-status ADRs)\n")
        return 0
    for r in records:
        fc = r.first_commit.isoformat() if r.first_commit else "uncommitted"
        age = "?" if r.age_days is None else str(r.age_days)
        flag = (
            "resolved_in_place" if r.resolved_in_place
            else "OVER_SLA" if r.over_sla
            else "grandfathered" if r.grandfathered
            else "ok"
        )
        sys.stdout.write(f"{r.number:04d}\t{age}\t{flag}\t{fc}\t{r.filename}\n")
    n_over = sum(1 for r in records if r.over_sla)
    n_resolved = sum(1 for r in records if r.resolved_in_place)
    sla = THRESHOLDS["ADR_PROPOSED_SLA_DAYS"]
    resolved_note = (
        f" {n_resolved} resolved in place (## Resolution appended, ADR 0047)."
        if n_resolved else ""
    )
    sys.stderr.write(
        f"\n{len(records)} proposed ADR(s); {n_over} over the {sla}-day SLA "
        f"(ADR 0047).{resolved_note} Reporting only — resolve via the "
        "adr-lifecycle-manager skill (promote / supersede / deprecate).\n"
    )
    return 0


def find_private_keys(obj: object) -> dict[str, int]:
    """Recursively count occurrences of each PHASE4_PRIVATE_KEYS member used
    as a dict key anywhere in ``obj`` (a parsed JSON value). Exact-key match,
    so safe siblings like ``query_type`` / ``agency_match`` / ``has_*`` never
    trip it. Returns ``{key: count}`` for the forbidden keys actually found.
    """
    found: dict[str, int] = {}

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PHASE4_PRIVATE_KEYS:
                    found[key] = found.get(key, 0) + 1
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return found


def phase4_artifact_paths(repo_root: str = ".") -> list[str]:
    """git-tracked ``*.json`` files under reports/retrieval/phase4*/ (the
    committable Phase 4 artifacts). Empty when none are tracked or git is
    unavailable.
    """
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "-C", repo_root, "ls-files", PHASE4_ARTIFACT_GLOB],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return []
    return [p for p in out.splitlines() if p.endswith(".json")]


def scan_phase4_artifacts_for_private_fields(
    repo_root: str = ".",
) -> list[tuple[str, dict[str, int]]]:
    """Scan every git-tracked Phase 4 JSON artifact for PHASE4_PRIVATE_KEYS.
    Returns ``[(relpath, {key: count}), ...]`` for files carrying at least one
    forbidden key. A clean repo returns ``[]``.
    """
    import json

    violations: list[tuple[str, dict[str, int]]] = []
    for rel in phase4_artifact_paths(repo_root):
        try:
            data = json.loads((Path(repo_root) / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        found = find_private_keys(data)
        if found:
            violations.append((rel, found))
    return violations


def _cmd_check_phase4_privacy(repo_root: str) -> int:
    violations = scan_phase4_artifacts_for_private_fields(repo_root)
    if not violations:
        return 0
    # Print key NAMES + counts only — never the private values themselves.
    sys.stderr.write(
        "\n❌ Phase 4 eval artifact privacy gate: committed artifact(s) carry "
        "private real-eval fields.\n\n"
        "   The committable boundary is qid + categories + metric values only "
        "(ADR 0005 private-local + ADR 0065). These git-tracked files contain "
        "forbidden key(s):\n\n"
    )
    for rel, found in violations:
        detail = ", ".join(f"{k}×{n}" for k, n in sorted(found.items()))
        sys.stderr.write(f"     - {rel}: {detail}\n")
    sys.stderr.write(
        "\n   Fix: regenerate with the sanitized scripts "
        "(phase4_query_metadata_coverage.py drops sample_queries; "
        "phase4_realistic_metadata_ablation.py persists has_* presence "
        "booleans, not labels), or `git rm --cached` the file. Raw labels / "
        "query text must stay local (gitignored).\n\n"
    )
    return 1


def find_eval_private_text(obj: object) -> dict[str, int]:
    """Structurally scan a parsed JSON value for the two private-text
    signatures a committable eval artifact must never carry:

    * ``hangul`` — count of Korean codepoints in any string key OR value.
    * ``colon_keys`` — count of dict keys containing ``:`` (un-stripped
      retry-reason payloads embed agency names / 공고번호 doc-ids there).

    Returns ``{signature: count}`` for signatures actually present (empty
    dict when clean). No name list is consulted — the check is purely
    structural, so it can live in committed source without re-leaking.
    """
    found: dict[str, int] = {}

    def _bump(sig: str, n: int = 1) -> None:
        if n:
            found[sig] = found.get(sig, 0) + n

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str):
                    _bump("hangul", len(_EVAL_PRIVACY_HANGUL_RE.findall(key)))
                    if ":" in key:
                        _bump("colon_keys")
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, str):
            _bump("hangul", len(_EVAL_PRIVACY_HANGUL_RE.findall(node)))

    _walk(obj)
    return found


def eval_privacy_artifact_paths(repo_root: str = ".") -> list[str]:
    """git-tracked ``*.json`` under the EVAL_PRIVACY_ARTIFACT_GLOBS prefixes
    (committable eval-data artifacts). Empty when none tracked / git absent.
    """
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "-C", repo_root, "ls-files", *EVAL_PRIVACY_ARTIFACT_GLOBS],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return []
    return [p for p in out.splitlines() if p.endswith(".json")]


def scan_eval_artifacts_for_private_text(
    repo_root: str = ".",
) -> list[tuple[str, dict[str, int]]]:
    """Scan every git-tracked eval-data JSON for private-text signatures.
    Returns ``[(relpath, {signature: count}), ...]`` for offending files; a
    clean repo returns ``[]``.
    """
    import json

    violations: list[tuple[str, dict[str, int]]] = []
    for rel in eval_privacy_artifact_paths(repo_root):
        try:
            data = json.loads((Path(repo_root) / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        found = find_eval_private_text(data)
        if found:
            violations.append((rel, found))
    return violations


def _git_check_ignored(repo_root: str, rel_path: str) -> bool:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "check-ignore", "-q", "--", rel_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def private_real_eval_gitignore_violations(repo_root: str = ".") -> dict[str, list[str]]:
    """Return private real-eval path ignore drift.

    ``missing_ignored`` entries are local/private paths that must be ignored.
    ``unexpectedly_ignored`` entries are redacted aggregate paths that must be
    committable after privacy checks.
    """
    missing_ignored = [
        rel
        for rel in PRIVATE_REAL_EVAL_REQUIRED_IGNORES
        if not _git_check_ignored(repo_root, rel)
    ]
    unexpectedly_ignored = [
        rel
        for rel in PRIVATE_REAL_EVAL_REDACTED_SUMMARIES
        if _git_check_ignored(repo_root, rel)
    ]
    out: dict[str, list[str]] = {}
    if missing_ignored:
        out["missing_ignored"] = missing_ignored
    if unexpectedly_ignored:
        out["unexpectedly_ignored"] = unexpectedly_ignored
    return out


def find_redacted_summary_forbidden_fields(obj: object) -> dict[str, int]:
    """Scan a redacted summary candidate for forbidden raw/private keys.

    This is intentionally exact-key based for the requested contract:
    ``question`` is forbidden, while aggregate names such as
    ``question_count`` remain valid.
    """
    found: dict[str, int] = {}

    def _bump(sig: str, n: int = 1) -> None:
        found[sig] = found.get(sig, 0) + n

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key).lower()
                if key_text in PRIVATE_REDACTED_FORBIDDEN_KEYS:
                    _bump(key_text)
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, str):
            if _ABSOLUTE_LOCAL_PATH_RE.search(node):
                _bump("absolute_path_value")

    _walk(obj)
    return found


def redacted_summary_artifact_paths(repo_root: str = ".") -> list[str]:
    """Return tracked or present redacted private summary JSON paths."""
    import subprocess

    paths: set[str] = set()
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_root, "ls-files", *PRIVATE_REAL_EVAL_REDACTED_SUMMARIES],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        paths.update(p for p in out.splitlines() if p.endswith(".json"))
    except (subprocess.CalledProcessError, OSError):
        pass
    for rel in PRIVATE_REAL_EVAL_REDACTED_SUMMARIES:
        if (Path(repo_root) / rel).is_file():
            paths.add(rel)
    return sorted(paths)


def scan_redacted_summaries_for_forbidden_fields(
    repo_root: str = ".",
) -> list[tuple[str, dict[str, int]]]:
    import json

    violations: list[tuple[str, dict[str, int]]] = []
    for rel in redacted_summary_artifact_paths(repo_root):
        try:
            data = json.loads((Path(repo_root) / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        found = find_redacted_summary_forbidden_fields(data)
        if found:
            violations.append((rel, found))
    return violations


def _cmd_check_eval_privacy(repo_root: str) -> int:
    violations = scan_eval_artifacts_for_private_text(repo_root)
    ignore_violations = private_real_eval_gitignore_violations(repo_root)
    redacted_violations = scan_redacted_summaries_for_forbidden_fields(repo_root)
    if not violations and not ignore_violations and not redacted_violations:
        return 0
    # Print signature names + counts only — never the offending text itself.
    if violations:
        sys.stderr.write(
            "\n❌ Eval artifact privacy gate: committed eval-data JSON carries "
            "private text.\n\n"
            "   Committable eval artifacts must hold qid + categories + metric "
            "values only (ADR 0005 private-local + ADR 0065). These git-tracked "
            "files break that boundary:\n\n"
        )
        for rel, found in violations:
            detail = ", ".join(f"{k}×{n}" for k, n in sorted(found.items()))
            sys.stderr.write(f"     - {rel}: {detail}\n")
        sys.stderr.write(
            "\n   `hangul` = Korean text (agency/사업명) in a qid or value; "
            "`colon_keys` = un-stripped retry-reason payload "
            "(`missing_comparison_*:<agency-or-docid>`).\n"
            "   Fix: regenerate with the sanitized generators — ablation runners "
            "write `anon_qid(qid)`, run_real_eval_delta strips retry-reason "
            "payloads, eda_real100 anonymizes every agency rank — or migrate the "
            "tracked file in place. Raw labels / query text stay local "
            "(gitignored).\n\n"
        )
    if ignore_violations:
        sys.stderr.write(
            "\n❌ Private real-eval gitignore gate: local private paths are not "
            "covered correctly.\n\n"
        )
        for rel in ignore_violations.get("missing_ignored", []):
            sys.stderr.write(f"     - must be ignored: {rel}\n")
        for rel in ignore_violations.get("unexpectedly_ignored", []):
            sys.stderr.write(f"     - redacted summary should be committable after checks: {rel}\n")
        sys.stderr.write("\n")
    if redacted_violations:
        sys.stderr.write(
            "\n❌ Redacted private real-eval summary gate: forbidden raw/private "
            "fields are present.\n\n"
        )
        for rel, found in redacted_violations:
            detail = ", ".join(f"{k}×{n}" for k, n in sorted(found.items()))
            sys.stderr.write(f"     - {rel}: {detail}\n")
        sys.stderr.write(
            "\n   Redacted summaries may include aggregate counts/metrics only. "
            "Raw question, answer, support_text, document_text, raw_text, "
            "file_path, and absolute_path fields stay local.\n\n"
        )
    return 1


def _cmd_is_load_bearing(path: str) -> int:
    return 0 if is_load_bearing(path) else 1


def _cmd_any_match() -> int:
    first_hit: str | None = None
    for line in sys.stdin:
        candidate = line.strip()
        if not candidate:
            continue
        if is_load_bearing(candidate):
            first_hit = candidate
            break
    if first_hit is None:
        return 1
    sys.stdout.write(first_hit + "\n")
    return 0


def _cmd_list() -> int:
    sys.stdout.write("\n".join(LOAD_BEARING_PATHS) + "\n")
    return 0


def _cmd_threshold(key: str) -> int:
    val = THRESHOLDS.get(key)
    if val is None:
        sys.stderr.write(
            f"unknown threshold key: {key!r}; available: "
            f"{sorted(THRESHOLDS)}\n"
        )
        return 1
    sys.stdout.write(f"{val}\n")
    return 0


def _cmd_emit_fire(
    outcome: str,
    hook: str,
    category: str,
    path: str,
    extra: str,
    log_path: str,
) -> int:
    """CLI entrypoint for `--emit-fire` — wraps emit_hook_fire()."""
    try:
        emit_hook_fire(
            outcome, hook, category, path, extra, log_path=log_path
        )
    except ValueError as exc:
        sys.stderr.write(f"emit-fire: {exc}\n")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Load-bearing paths + numeric thresholds SSoT "
                    "(CLAUDE.md, PR #69 / #747 / #745 lessons).",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--is-load-bearing", metavar="PATH",
        help="Exit 0 if PATH is load-bearing, 1 otherwise.",
    )
    g.add_argument(
        "--any-match", action="store_true",
        help="Read newline-delimited paths from stdin; exit 0 if any "
             "match (printing the first match to stdout), else 1.",
    )
    g.add_argument(
        "--list", action="store_true",
        help="Print the canonical load-bearing list, one per line.",
    )
    g.add_argument(
        "--threshold", metavar="KEY",
        help="Print the numeric THRESHOLDS[KEY] to stdout (exit 0). "
             "Exit 1 if KEY is unknown.",
    )
    g.add_argument(
        "--next-adr-number", action="store_true",
        help="Print the next available ADR number (filesystem-only; "
             "still cross-check `gh pr list --search ADR --state open`).",
    )
    g.add_argument(
        "--check-adr-collision", action="store_true",
        help="Scan docs/adr/ for two files sharing the same NNNN prefix; "
             "exit 1 with details if any collision is found.",
    )
    g.add_argument(
        "--lint-adr-consequences", metavar="ADR_PATH",
        help="Lint a single ADR's `## Verification` section + verifies-key "
             "markers (issue #793); exit 1 with details if missing/broken.",
    )
    g.add_argument(
        "--check-adr-readme-parity",
        nargs="+",
        metavar="ADR_PATH",
        help="Check that each ADR path has a matching row in "
             "docs/adr/README.md (issue #803). Used by the pre-commit hook "
             "to shift-left the test_no_unlinked_adr_files_on_disk CI gate.",
    )
    g.add_argument(
        "--check-adr-readme-status", action="store_true",
        help="Check each ADR file's Status header matches its row's Status "
             "cell in the docs/adr/README.md MAIN index table (leading "
             "lifecycle word, case-insensitive); exit 1 with details on "
             "drift. Complements --check-adr-readme-parity (membership) by "
             "catching a stale index status after a proposed->accepted flip "
             "(issue #1181). Reuses --readme-path / --adr-dir.",
    )
    g.add_argument(
        "--check-adr-crossref", action="store_true",
        help="Check ADR↔ADR supersede cross-ref integrity (issue #1077): a "
             "Superseded-by pointer implies a 'superseded' Status (R1), every "
             "supersede target file must exist (R2), and a structured "
             "`**Supersedes**` field must be reciprocated by the target's "
             "`Superseded by` back-pointer (R3). Compares ADR files against "
             "each other, not the README index. Reuses --adr-dir.",
    )
    g.add_argument(
        "--emit-fire", action="store_true",
        help="Append a v2-5field event to .claude/.hook-fires.log "
             "(ADR 0060). Requires --outcome and --hook. Optional: "
             "--category --path --extra --fire-log.",
    )
    g.add_argument(
        "--check-phase4-privacy", action="store_true",
        help="Scan git-tracked reports/retrieval/phase4*/*.json for private "
             "real-eval fields (raw query text, agency/project labels) that "
             "break the ADR 0005 / ADR 0065 committable boundary; exit 1 with "
             "the offending files + forbidden keys if any are found.",
    )
    g.add_argument(
        "--check-eval-privacy", action="store_true",
        help="Structurally scan git-tracked reports/retrieval/ + "
             "reports/real100/ JSON for private text (Hangul anywhere, or "
             "colon-bearing dict keys) that breaks the ADR 0005 / ADR 0065 "
             "committable boundary; also verify private real-eval local paths "
             "are gitignored and redacted private summaries omit forbidden raw "
             "keys; exit 1 with offending files + signature counts (never the "
             "text) if any are found. Uses no name list.",
    )
    g.add_argument(
        "--proposed-adr-age", action="store_true",
        help="Report each proposed-status ADR's age + 30-day SLA flag "
             "(ADR 0047). Tab-separated columns: NNNN, age_days, flag "
             "(resolved_in_place/OVER_SLA/grandfathered/ok), first_commit, "
             "filename. `resolved_in_place` = a `## Resolution` H2 was "
             "appended (0047 in-place resolution) so it is not flagged. "
             "Reporting only; exit 0.",
    )
    p.add_argument(
        "--outcome",
        help="Outcome enum for --emit-fire. "
             f"One of {sorted(KNOWN_OUTCOMES)}.",
    )
    p.add_argument(
        "--hook",
        help="Hook id for --emit-fire. "
             f"One of {sorted(KNOWN_HOOKS)}.",
    )
    p.add_argument(
        "--category", default="",
        help="Sub-category for --emit-fire (optional).",
    )
    p.add_argument(
        "--path", default="",
        help="Affected file/branch path for --emit-fire (optional).",
    )
    p.add_argument(
        "--extra", default="",
        help="Free-form extra metadata for --emit-fire (optional).",
    )
    p.add_argument(
        "--fire-log", default=".claude/.hook-fires.log",
        help="Override fire-log path (default: .claude/.hook-fires.log). "
             "Used by tests; production hooks should not set this.",
    )
    p.add_argument(
        "--readme-staged", action="store_true",
        help="When set with --check-adr-readme-parity, read README content "
             "from the git index (`git show :<readme-path>`) instead of the "
             "working tree. Used by the pre-commit hook so the check sees "
             "exactly what the upcoming commit will publish.",
    )
    p.add_argument(
        "--readme-path", default="docs/adr/README.md",
        help="README path for --check-adr-readme-parity / "
             "--check-adr-readme-status (default: docs/adr/README.md).",
    )
    p.add_argument(
        "--adr-dir", default=ADR_DIR_DEFAULT,
        help=f"ADR directory (default: {ADR_DIR_DEFAULT}). "
             "Only used by --next-adr-number / --check-adr-collision / "
             "--check-adr-readme-status / --proposed-adr-age.",
    )
    p.add_argument(
        "--repo-root", default=".",
        help="Repo root for verifies-key marker resolution + the Phase 4 "
             "artifact scan (default: current directory). Used by "
             "--lint-adr-consequences, --check-phase4-privacy, and "
             "--check-eval-privacy.",
    )
    args = p.parse_args()

    if args.is_load_bearing is not None:
        return _cmd_is_load_bearing(args.is_load_bearing)
    if args.any_match:
        return _cmd_any_match()
    if args.list:
        return _cmd_list()
    if args.threshold is not None:
        return _cmd_threshold(args.threshold)
    if args.next_adr_number:
        return _cmd_next_adr_number(args.adr_dir)
    if args.check_adr_collision:
        return _cmd_check_adr_collision(args.adr_dir)
    if args.lint_adr_consequences is not None:
        return _cmd_lint_adr_consequences(args.lint_adr_consequences, args.repo_root)
    if args.check_adr_readme_parity is not None:
        return _cmd_check_adr_readme_parity(
            args.check_adr_readme_parity,
            readme_staged=args.readme_staged,
            readme_path=args.readme_path,
        )
    if args.check_adr_readme_status:
        return _cmd_check_adr_readme_status(args.adr_dir, args.readme_path)
    if args.check_adr_crossref:
        return _cmd_check_adr_crossref(args.adr_dir)
    if args.emit_fire:
        if not args.outcome or not args.hook:
            sys.stderr.write(
                "--emit-fire requires --outcome and --hook\n"
            )
            return 2
        return _cmd_emit_fire(
            args.outcome, args.hook, args.category,
            args.path, args.extra, args.fire_log,
        )
    if args.proposed_adr_age:
        return _cmd_proposed_adr_age(args.adr_dir)
    if args.check_phase4_privacy:
        return _cmd_check_phase4_privacy(args.repo_root)
    if args.check_eval_privacy:
        return _cmd_check_eval_privacy(args.repo_root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
