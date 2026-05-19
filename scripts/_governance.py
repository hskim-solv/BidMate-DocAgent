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
import re
import sys
from pathlib import Path


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
        "--emit-fire", action="store_true",
        help="Append a v2-5field event to .claude/.hook-fires.log "
             "(ADR 0060). Requires --outcome and --hook. Optional: "
             "--category --path --extra --fire-log.",
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
        help="README path for --check-adr-readme-parity "
             "(default: docs/adr/README.md).",
    )
    p.add_argument(
        "--adr-dir", default=ADR_DIR_DEFAULT,
        help=f"ADR directory (default: {ADR_DIR_DEFAULT}). "
             "Only used by --next-adr-number / --check-adr-collision.",
    )
    p.add_argument(
        "--repo-root", default=".",
        help="Repo root for verifies-key marker resolution "
             "(default: current directory). Only used by --lint-adr-consequences.",
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
    return 2


if __name__ == "__main__":
    sys.exit(main())
