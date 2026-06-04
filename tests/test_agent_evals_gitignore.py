"""Privacy guard for the agent-evals/ aggregate-only data boundary (ADR 0005, ADR 0100).

The operator-skill eval surface (`agent-evals/`) runs paired playbook trials whose
per-run artifacts — run-logs, captured PR diffs, reviewer inputs — carry raw issue/PR
text that ADR 0005 forbids committing. PR1 established the path layer and PR2 extends it with content scanning
with three complementary checks:

1. ``.gitignore`` is **deny-by-default**: everything under ``agent-evals/`` is ignored, then
   PR2 unignores only the exact scanner-backed code/task/playbook/split/aggregate-report
   surface. Raw run logs, captured patches, reviewer inputs, worktrees, unexpected names, and
   non-aggregate reports remain denied.
2. An **index-aware guard** (``test_no_tracked_file_outside_committable_allowlist``):
   ``.gitignore`` is only advisory (``git add -f`` and already-tracked files bypass it),
   so the authoritative enforcement is that NO *tracked* file under ``agent-evals/`` falls
   outside the exact committable allowlist.
3. A **local pre-commit mirror** (``test_precommit_hook_enforces_agent_evals_boundary``):
   ``.githooks/pre-commit`` must carry the same deny-by-default rule and invoke
   ``agent-evals/core/report.py --check-staged`` so a force-added raw artifact is rejected at
   commit time locally, not only in CI (mirrors the hook's existing ADR 0005 path-block
   convention).

``git check-ignore --no-index --quiet <path>`` exits 0 when a path is ignored by pattern,
1 when not — ``--no-index`` evaluates the patterns regardless of tracking state, so the
pattern tests cannot be masked by a path happening to be tracked.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Raw / per-run artifacts that MUST be denied (ignored) — including unanticipated names.
DENIED = [
    "agent-evals/runs/T-1/seed-0/run-log.json",
    "agent-evals/runs/T-1/seed-0/captured.diff",
    "agent-evals/captures/pr-1844.patch",
    "agent-evals/reviewer-inputs/T-1.json",
    "agent-evals/worktrees/T-1/anything.txt",
    "agent-evals/tasks/T-1/raw-issue.json",
    "agent-evals/tasks/T-1/raw/task.yaml",        # nested task.yaml (only tasks/*/task.yaml allowed)
    "agent-evals/runs/T-1/secret.env",            # unanticipated extension → denied
    "agent-evals/some_unexpected_artifact.log",   # unanticipated top-level → denied
    "agent-evals/runs/T-1/__init__.py",           # __init__.py in a raw tree → still denied
    "agent-evals/worktrees/T-1/__init__.py",      # (no global __init__.py exception)
    "agent-evals/reports/2026-01-01-run.run.json",
    "agent-evals/reports/2026-01-01-raw-dump.json",
    "agent-evals/reports/2026-smoke-run-log.json",        # "smoke" in name but not allowed
    "agent-evals/reports/2026-smoke-captured-diff.json",
    "agent-evals/reports/raw-v0-vs-v1.json",
    # Unanticipated shallow .py files are denied too — exact module allowlists close the
    # "shallow code path could be a raw sink" bypass (no generalizable .py pattern to match).
    # PR3 widened the allowlist to oracle/runner/oracle_bidmate by EXACT name only, so an
    # arbitrary shallow .py (raw_dump.py) must still be denied:
    "agent-evals/core/raw_dump.py",
    "agent-evals/adapters/bidmate/raw_dump.py",
    "agent-evals/core/runs/2026/raw_dump.py",
    "agent-evals/adapters/bidmate/worktrees/wt1/dump.py",
]

# PR2 committable surface: exact scanner-backed files only.
ALLOWED = [
    "agent-evals/README.md",
    "agent-evals/core/__init__.py",
    "agent-evals/core/schema.py",
    "agent-evals/core/metrics.py",
    "agent-evals/core/report.py",
    "agent-evals/core/oracle.py",
    "agent-evals/adapters/bidmate/__init__.py",
    "agent-evals/adapters/bidmate/task_mining.py",
    "agent-evals/adapters/bidmate/runner.py",
    "agent-evals/adapters/bidmate/oracle_bidmate.py",
    "agent-evals/playbooks/v0_naive.md",
    "agent-evals/playbooks/v1_spec_first.md",
    "agent-evals/splits.yaml",
    "agent-evals/tasks/T-smoke-001/task.yaml",
    "agent-evals/reports/smoke.aggregate.json",
]

# Exact committable allowlist (regex over POSIX rel-paths) for the index-aware guard.
# Mirrors the PR2 `.gitignore`: exact files plus task.yaml / aggregate-report path shapes.
#
# `\Z` (NOT `$`): Python's `$` also matches just before a trailing newline, so
# `^agent-evals/README\.md$` would wrongly accept a tracked path literally named
# `agent-evals/README.md\n`. `\Z` anchors at the true end of string, so a newline-suffixed
# filename fails the allowlist and is flagged (Codex pre-commit review, issue #1844). Pairs
# with `git ls-files -z` framing below so such a path arrives as one record, not a clean split.
COMMITTABLE_RE = [
    re.compile(r"^agent-evals/README\.md\Z"),
    re.compile(r"^agent-evals/core/__init__\.py\Z"),
    re.compile(r"^agent-evals/core/(schema|metrics|report|oracle)\.py\Z"),
    re.compile(r"^agent-evals/adapters/bidmate/__init__\.py\Z"),
    re.compile(r"^agent-evals/adapters/bidmate/(task_mining|runner|oracle_bidmate)\.py\Z"),
    re.compile(r"^agent-evals/playbooks/v(0_naive|1_spec_first)\.md\Z"),
    re.compile(r"^agent-evals/splits\.yaml\Z"),
    re.compile(r"^agent-evals/tasks/[^/]+/task\.yaml\Z"),
    re.compile(r"^agent-evals/reports/[^/]+\.aggregate\.json\Z"),
]


def _is_ignored(rel_path: str) -> bool:
    """True iff git ignores ``rel_path`` by pattern (``git check-ignore`` exit 0).

    Uses ``--no-index`` so tracking state cannot mask the pattern, and fails loudly (not
    skip) if ``git check-ignore`` itself breaks (rc outside {0, 1}): a broken guard check
    must block, never silently pass the privacy boundary.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), (
        f"git check-ignore failed for {rel_path} (rc={result.returncode}); "
        f"stdout={result.stdout!r} stderr={result.stderr!r} — the agent-evals/ privacy "
        "guard could not be verified; treat as failure, not skip."
    )
    return result.returncode == 0


@pytest.mark.parametrize("rel_path", DENIED)
def test_raw_agent_eval_artifacts_are_gitignored(rel_path: str) -> None:
    assert _is_ignored(rel_path), (
        f"{rel_path} is NOT gitignored — a raw per-run/report artifact could be committed, "
        "violating the agent-evals/ aggregate-only boundary (ADR 0005, ADR 0100)."
    )


@pytest.mark.parametrize("rel_path", ALLOWED)
def test_public_agent_eval_artifacts_are_committable(rel_path: str) -> None:
    assert not _is_ignored(rel_path), (
        f"{rel_path} IS gitignored but should be committable in PR2 "
        "(scanner-backed agent-evals surface)."
    )


def _extract_bash_array(hook_text: str, name: str) -> str:
    """Body between ``NAME=(`` and the next line that is exactly ``)``.

    Only a line whose stripped content is ``)`` closes the array, so a ``)`` inside a
    comment (the hook has several, e.g. ``# scripts/eda_real100.py).``) cannot truncate it.
    """
    start = hook_text.index(f"{name}=(")
    body_start = hook_text.index("\n", start) + 1
    out = []
    for line in hook_text[body_start:].splitlines():
        if line.strip() == ")":
            break
        out.append(line)
    return "\n".join(out)


def test_precommit_hook_enforces_agent_evals_boundary() -> None:
    """Local pre-commit mirror: `.githooks/pre-commit` must deny every agent-evals/ path,
    allow only the PR2 scanner-backed surface, and invoke the content scanner so a
    force-added (`git add -f`) raw artifact is rejected at commit time locally — not only by
    the CI index guard. Mirrors the hook's documented
    "BLOCKED_PATTERNS must mirror .gitignore's ADR 0005 boundary" convention.
    """
    hook = (REPO_ROOT / ".githooks" / "pre-commit").read_text()
    blocked = _extract_bash_array(hook, "BLOCKED_PATTERNS")
    allowed = _extract_bash_array(hook, "ALLOWED_PATTERNS")
    assert "'^agent-evals/'" in blocked, (
        "pre-commit BLOCKED_PATTERNS must deny all agent-evals/ paths (force-add guard "
        "mirroring the .gitignore deny-by-default rule)."
    )
    assert r"'^agent-evals/README\.md$'" in allowed, (
        "pre-commit ALLOWED_PATTERNS must permit agent-evals/README.md."
    )
    assert r"'^agent-evals/core/(schema|metrics|report|oracle)\.py$'" in allowed, (
        "pre-commit ALLOWED_PATTERNS must permit exact core modules (PR2 schema/metrics/report "
        "plus PR3 oracle)."
    )
    assert r"'^agent-evals/adapters/bidmate/(task_mining|runner|oracle_bidmate)\.py$'" in allowed, (
        "pre-commit ALLOWED_PATTERNS must permit exact bidmate adapter modules (PR2 task_mining "
        "plus PR3 runner/oracle_bidmate)."
    )
    assert r"'^agent-evals/reports/[^/]+\.aggregate\.json$'" in allowed, (
        "pre-commit ALLOWED_PATTERNS must permit aggregate reports only."
    )
    assert "agent-evals/core/report.py --check-staged" in hook, (
        "pre-commit must run the PR2 content scanner before path allowlisting."
    )
    # Raw-sink trees must NOT leak into the local allowlist.
    assert "agent-evals/runs" not in allowed
    assert "agent-evals/worktrees" not in allowed
    assert "agent-evals/captures" not in allowed


def test_precommit_hook_enumerates_staged_files_nul_safely() -> None:
    """The hook must enumerate staged files NUL-delimited (`git diff --cached -z` +
    `read -r -d ''`), not newline-delimited. A staged path with an embedded newline or
    control character would otherwise split into multiple tokens and slip past the
    agent-evals/ exact allowlist block (Codex pre-commit review, issue #1844). NUL framing is
    robust regardless of `core.quotePath`; `read -r -d ''` stays bash-3.2 compatible.
    """
    hook = (REPO_ROOT / ".githooks" / "pre-commit").read_text()
    assert "git diff --cached -z --name-only --diff-filter=ACMR" in hook, (
        "pre-commit must list staged files with `-z` (NUL-delimited) so newline-bearing "
        "paths cannot evade the agent-evals/ exact allowlist boundary."
    )
    assert "while IFS= read -r -d '' file" in hook, (
        "pre-commit must parse the staged-file list with `read -r -d ''` (NUL records)."
    )
    assert "done < <(git diff --cached -z --name-only" in hook, (
        "the boundary loop must source its file list from the NUL-delimited diff via "
        "process substitution."
    )
    # The old newline-splitting here-string form must be gone.
    assert 'done <<< "$staged"' not in hook, (
        "the newline-delimited `done <<< \"$staged\"` boundary loop must be replaced by the "
        "NUL-safe process-substitution loop."
    )


def test_no_tracked_file_outside_committable_allowlist() -> None:
    """Index-aware guard: `.gitignore` is advisory (`git add -f` / already-tracked files
    bypass it), so the authoritative privacy enforcement is that every *tracked* file under
    `agent-evals/` matches the exact committable allowlist. A raw artifact that was
    force-added would be caught here even though the gitignore pattern test passes.
    """
    # `-z`: NUL-delimited output. Without it, git C-quotes control-char paths under
    # core.quotePath, and `splitlines()` would split a path literally named
    # `agent-evals/README.md\n` into a clean `agent-evals/README.md` token that matches the
    # allowlist — a tracked newline-suffixed raw artifact would then evade this guard. NUL
    # framing surfaces such a path as one record (Codex pre-commit review, issue #1844).
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "agent-evals/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git ls-files failed: {result.stderr!r}"
    tracked = [rec for rec in result.stdout.split("\0") if rec]
    violations = [p for p in tracked if not any(rx.match(p) for rx in COMMITTABLE_RE)]
    assert not violations, (
        "Tracked agent-evals/ file(s) outside the committable allowlist — raw data may "
        f"have been force-added (ADR 0005 / ADR 0100 violation): {violations}"
    )


@pytest.mark.parametrize(
    "evasive",
    [
        "agent-evals/README.md\n",   # trailing newline — Python `$` would wrongly accept this
        "agent-evals/README.md\r",
        "agent-evals/README.md\n\n",
        "agent-evals/RE\nADME.md",   # embedded newline mid-path
        " agent-evals/README.md",    # leading space
        "agent-evals/README.md ",    # trailing space
    ],
)
def test_committable_regex_rejects_control_char_readme_variants(evasive: str) -> None:
    """The committable allowlist regex must reject any control-char/whitespace variant of the
    README path, so a tracked file named (e.g.) `agent-evals/README.md\\n` cannot masquerade
    as the exact README exception. This is why `COMMITTABLE_RE` uses `\\Z` (not `$`) and why the
    index guard reads `git ls-files -z` — together they ensure such a path is surfaced as one
    record and fails the allowlist (Codex pre-commit review, issue #1844).
    """
    assert not any(rx.match(evasive) for rx in COMMITTABLE_RE)
    # Sanity: the exact path still matches.
    assert any(rx.match("agent-evals/README.md") for rx in COMMITTABLE_RE)
