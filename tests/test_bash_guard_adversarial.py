"""Adversarial parsing tests for pretooluse-bash-guard.sh (issue #1045).

거버넌스 비판 보고서 (2026-05-19) #5 해소:

bash-guard 의 `gh pr merge --delete-branch` / `gh pr create` 검출이
`shlex.split()` + `re.split()` 기반. 다음과 같은 우회가 가능 추정:

  - quote whole cmd:    `'gh pr merge' --delete-branch`
  - eval wrapper:       `eval 'gh pr merge --delete-branch'`
  - partial quote:      `gh "pr" merge --delete-branch`
  - env var:            `$CMD --delete-branch`

이 테스트가 어느 케이스가 catch / 어느 케이스가 fail-open 인지 명시.
"우회 가능하다" → "이 종류는 막을 수 없다" 로 정직한 contract.

PR4 outcome telemetry 의 `false_negative` outcome 카테고리가 future 에
adversarial 우회를 기록할 자리 마련.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PARSE_PATH = REPO_ROOT / "scripts" / "claude-hooks" / "_bash_guard_parse.py"


def _load_parse():
    spec = importlib.util.spec_from_file_location("_bgp", PARSE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def bgp():
    return _load_parse()


# ---------------------------------------------------------------------------
# detect_gh_subcommand — normal cases (must catch)
# ---------------------------------------------------------------------------


def test_normal_gh_pr_merge(bgp):
    assert bgp.detect_gh_subcommand("gh pr merge 493 --delete-branch") == "merge"


def test_normal_gh_pr_create(bgp):
    assert bgp.detect_gh_subcommand("gh pr create --title foo") == "create"


def test_normal_gh_pr_merge_no_args(bgp):
    assert bgp.detect_gh_subcommand("gh pr merge") == "merge"


def test_chained_with_and(bgp):
    """foo && gh pr merge ... → must catch (split on '&')."""
    assert bgp.detect_gh_subcommand("foo && gh pr merge --delete-branch") == "merge"


def test_chained_with_semicolon(bgp):
    assert bgp.detect_gh_subcommand("ls; gh pr create") == "create"


def test_chained_with_pipe(bgp):
    """`foo | gh pr merge` doesn't make semantic sense but parsing splits on |."""
    assert bgp.detect_gh_subcommand("echo x | gh pr merge") == "merge"


def test_subshell_open_paren(bgp):
    """`(gh pr merge ...)` → strips leading `(`, catches."""
    assert bgp.detect_gh_subcommand("(gh pr merge --delete-branch)") == "merge"


def test_partial_quote_inside_command(bgp):
    """`gh \"pr\" merge` → shlex unquotes \"pr\" → tokens[1] == 'pr' → catches."""
    assert bgp.detect_gh_subcommand('gh "pr" merge --delete-branch') == "merge"


def test_partial_quote_subcommand(bgp):
    """`gh pr \"merge\"` → same — shlex unquotes."""
    assert bgp.detect_gh_subcommand('gh pr "merge" --delete-branch') == "merge"


# ---------------------------------------------------------------------------
# detect_gh_subcommand — adversarial cases (documented false-negatives)
#
# These are the "fail-open" cases. The hook will NOT catch them. Tests pin
# the surface so any future parsing improvement can shrink it deliberately.
# ---------------------------------------------------------------------------


def test_false_negative_quote_whole_command(bgp):
    """`'gh pr merge' --delete-branch` → first token = 'gh pr merge' literal,
    tokens[1] = '--delete-branch'. shlex unquotes the whole thing as ONE
    token. NOT caught."""
    assert bgp.detect_gh_subcommand("'gh pr merge' --delete-branch") == ""


def test_false_negative_eval_wrapper(bgp):
    """`eval 'gh pr merge --delete-branch'` → tokens[0] = 'eval'. NOT caught.
    The hook can't see through `eval`."""
    assert bgp.detect_gh_subcommand("eval 'gh pr merge --delete-branch'") == ""


def test_false_negative_env_var(bgp):
    """`$CMD --delete-branch` → tokens[0] = '$CMD' (shlex doesn't interpolate).
    NOT caught."""
    assert bgp.detect_gh_subcommand("$CMD --delete-branch") == ""


def test_false_negative_command_substitution(bgp):
    """`$(echo gh pr merge) --delete-branch` → tokens[0] = '$(echo' literal.
    NOT caught — shlex doesn't evaluate command substitution."""
    assert bgp.detect_gh_subcommand("$(echo gh pr merge) --delete-branch") == ""


def test_false_negative_alias_indirection(bgp):
    """If the user aliased `pr-merge` to `gh pr merge`, calling `pr-merge`
    isn't caught — only literal `gh pr <sub>` matches."""
    assert bgp.detect_gh_subcommand("pr-merge --delete-branch") == ""


def test_unrelated_command(bgp):
    assert bgp.detect_gh_subcommand("ls -la") == ""
    assert bgp.detect_gh_subcommand("git status") == ""
    assert bgp.detect_gh_subcommand("") == ""


# ---------------------------------------------------------------------------
# has_explicit_base_flag — bypass detection
# ---------------------------------------------------------------------------


def test_has_base_explicit_long(bgp):
    assert bgp.has_explicit_base_flag("gh pr create --base main")


def test_has_base_explicit_equals(bgp):
    assert bgp.has_explicit_base_flag("gh pr create --base=foo")


def test_has_base_other_branch(bgp):
    assert bgp.has_explicit_base_flag("gh pr create --title x --base feature/foo")


def test_no_base_means_implicit_main(bgp):
    assert not bgp.has_explicit_base_flag("gh pr create --title foo --body bar")


def test_has_base_doesnt_match_gh_merge(bgp):
    """`gh pr merge --base ...` doesn't exist as a real flag, but if a user
    typed it, we should NOT treat it as a create-bypass."""
    assert not bgp.has_explicit_base_flag("gh pr merge --base foo")


def test_has_base_substring_doesnt_match(bgp):
    """`--basenum=3` shouldn't match `--base`."""
    assert not bgp.has_explicit_base_flag("gh pr create --basenum=3")


# ---------------------------------------------------------------------------
# CLI interface (used by the bash hook)
# ---------------------------------------------------------------------------


def test_cli_detect_gh_stdout(tmp_path, bgp):
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, str(PARSE_PATH), "--detect-gh",
         "gh pr merge 1 --delete-branch"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "merge"


def test_cli_has_base_exit_codes(bgp):
    import subprocess, sys
    # 0 when --base present
    r = subprocess.run(
        [sys.executable, str(PARSE_PATH), "--has-base",
         "gh pr create --base main"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0

    # 1 when no --base
    r = subprocess.run(
        [sys.executable, str(PARSE_PATH), "--has-base", "gh pr create"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
