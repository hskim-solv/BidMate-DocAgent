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
ADR_FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")


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
    return 2


if __name__ == "__main__":
    sys.exit(main())
