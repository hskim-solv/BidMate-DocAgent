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
# all_create_segments_have_base — bypass detection (finding F2: per-segment)
# ---------------------------------------------------------------------------


def test_has_base_explicit_long(bgp):
    assert bgp.all_create_segments_have_base("gh pr create --base main")


def test_has_base_explicit_equals(bgp):
    assert bgp.all_create_segments_have_base("gh pr create --base=foo")


def test_has_base_other_branch(bgp):
    assert bgp.all_create_segments_have_base("gh pr create --title x --base feature/foo")


def test_no_base_means_implicit_main(bgp):
    assert not bgp.all_create_segments_have_base("gh pr create --title foo --body bar")


def test_has_base_doesnt_match_gh_merge(bgp):
    """`gh pr merge --base ...` doesn't exist as a real flag, but if a user
    typed it, we should NOT treat it as a create-bypass (0 create segments)."""
    assert not bgp.all_create_segments_have_base("gh pr merge --base foo")


def test_has_base_substring_doesnt_match(bgp):
    """`--basenum=3` shouldn't match `--base`."""
    assert not bgp.all_create_segments_have_base("gh pr create --basenum=3")


def test_f2_compound_one_baseless_create_does_not_bypass(bgp):
    """Finding F2: a compound where ONE create has --base must NOT bypass —
    the base-less create would still collapse the stack. The any-segment
    form returned True here (bug); the per-segment form returns False."""
    cmd = "gh pr create --title bad && gh pr create --base main --title ok"
    assert not bgp.all_create_segments_have_base(cmd)


def test_f2_compound_all_creates_have_base_bypasses(bgp):
    """Two creates, both with --base → safe to bypass."""
    cmd = "gh pr create --base x --title a && gh pr create --base y --title b"
    assert bgp.all_create_segments_have_base(cmd)


def test_f2_baseless_first_then_base(bgp):
    """Order-independent: base-less first segment still blocks the bypass."""
    cmd = "gh pr create --base main && gh pr create --title oops"
    assert not bgp.all_create_segments_have_base(cmd)


# ---------------------------------------------------------------------------
# F3: shlex-first segmentation — quoted separators no longer break parsing
# ---------------------------------------------------------------------------


def test_f3_quoted_semicolon_in_title(bgp):
    """A `;` inside a quoted --title must not split the create segment."""
    assert bgp.detect_gh_subcommand('gh pr create --title "a; b"') == "create"


def test_f3_quoted_ampersand_in_title(bgp):
    assert bgp.detect_gh_subcommand('gh pr create --title "a && b"') == "create"


def test_f3_quoted_pipe_in_body(bgp):
    assert bgp.detect_gh_subcommand('gh pr create --body "x | y"') == "create"


def test_f3_quoted_separator_preserves_base_check(bgp):
    """A base-less create with a quoted separator is still seen as base-less
    (previously the whole segment was dropped → silently 'no create')."""
    assert not bgp.all_create_segments_have_base('gh pr create --title "a; b"')


def test_f3_quoted_separator_get_body(bgp):
    assert bgp.get_create_flag_value(
        'gh pr create --body "fixes a; b"', "--body"
    ) == "fixes a; b"


def test_f3_real_merge_after_quoted_separator(bgp):
    """`echo "...&&..." ; gh pr merge` — the real merge in its own segment
    is still caught despite the quoted `&&`."""
    assert bgp.detect_gh_subcommand(
        'echo "a && b" ; gh pr merge 5 --delete-branch'
    ) == "merge"


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


# ---------------------------------------------------------------------------
# get_create_flag_value — general `gh pr create` flag extractor (originally
# added for §5b body extraction, issue #1097; the bash-guard call site was
# removed with the §5b gate per ADR 0084, but the parser is still tested).
# ---------------------------------------------------------------------------


def test_get_body_simple(bgp):
    assert bgp.get_create_flag_value("gh pr create --title T --body hello", "--body") == "hello"


def test_get_body_equals_form(bgp):
    assert bgp.get_create_flag_value("gh pr create --body=hello", "--body") == "hello"


def test_get_body_file(bgp):
    assert bgp.get_create_flag_value(
        "gh pr create --body-file /tmp/b.md", "--body-file"
    ) == "/tmp/b.md"


def test_get_body_quoted_multiword(bgp):
    assert bgp.get_create_flag_value(
        'gh pr create --body "hello world"', "--body"
    ) == "hello world"


def test_get_body_absent_returns_empty(bgp):
    assert bgp.get_create_flag_value("gh pr create --title T", "--body") == ""


def test_get_body_only_on_create_segment(bgp):
    """`--body` on a non-create gh segment must not match."""
    assert bgp.get_create_flag_value("gh pr merge --body x", "--body") == ""


def test_get_body_compound_command(bgp):
    assert bgp.get_create_flag_value(
        "echo start && gh pr create --body hi", "--body"
    ) == "hi"


def test_get_body_does_not_confuse_body_file(bgp):
    """`--body` must not pick up `--body-file`'s value (and vice versa)."""
    cmd = "gh pr create --body-file /tmp/x --body inline"
    assert bgp.get_create_flag_value(cmd, "--body") == "inline"
    assert bgp.get_create_flag_value(cmd, "--body-file") == "/tmp/x"


def test_cli_get_body_stdout(bgp):
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, str(PARSE_PATH), "--get-body", "gh pr create --body hello"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "hello"


def test_cli_get_body_file_stdout(bgp):
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, str(PARSE_PATH), "--get-body-file",
         "gh pr create --body-file /tmp/b.md"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "/tmp/b.md"


# ---------------------------------------------------------------------------
# F1: bash-guard fails CLOSED when the parser crashes — but only for a
# command that DIRECTLY starts with a guarded `gh pr merge|create`
# (anchored). A command that merely contains the literal (e.g. inside an
# echo/quote) must fall OPEN, because a transient parser failure was
# observed to over-block such benign commands.
#
# Drives the real pretooluse-bash-guard.sh against a deliberately broken
# parser stub (exits non-zero) in a throwaway REPO_ROOT layout.
# ---------------------------------------------------------------------------

HOOK_PATH = REPO_ROOT / "scripts" / "claude-hooks" / "pretooluse-bash-guard.sh"


def _run_hook_with_broken_parser(tmp_path, command: str):
    import json, shutil, subprocess

    ch = tmp_path / "scripts" / "claude-hooks"
    ch.mkdir(parents=True)
    shutil.copy(HOOK_PATH, ch / "pretooluse-bash-guard.sh")
    (ch / "pretooluse-bash-guard.sh").chmod(0o755)
    # Parser crash: exit non-zero, no stdout.
    (ch / "_bash_guard_parse.py").write_text("import sys\nsys.exit(1)\n")
    # Tolerated emit-fire stub (always succeeds, prints nothing).
    (tmp_path / "scripts" / "_governance.py").write_text("import sys\nsys.exit(0)\n")

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        ["bash", str(ch / "pretooluse-bash-guard.sh")],
        input=payload, capture_output=True, text=True,
    )


def test_f1_parser_crash_blocks_direct_gh_pr_merge(tmp_path):
    """Parser crash + command STARTING with `gh pr merge` → refuse (exit 2)."""
    r = _run_hook_with_broken_parser(tmp_path, "gh pr merge 5 --delete-branch")
    assert r.returncode == 2
    assert "parser failed" in r.stderr.lower()


def test_f1_parser_crash_blocks_direct_gh_pr_create(tmp_path):
    r = _run_hook_with_broken_parser(tmp_path, "gh pr create --title x")
    assert r.returncode == 2


def test_f1_parser_crash_blocks_after_leading_separator(tmp_path):
    """A single leading subshell-open / separator is still anchored."""
    r = _run_hook_with_broken_parser(tmp_path, "(gh pr merge --delete-branch)")
    assert r.returncode == 2


def test_f1_parser_crash_falls_open_for_non_gh(tmp_path):
    """Parser crash but not a gh pr command → must fall OPEN (exit 0)."""
    r = _run_hook_with_broken_parser(tmp_path, "ls -la")
    assert r.returncode == 0


def test_f1_parser_crash_falls_open_when_literal_only_embedded(tmp_path):
    """The observed over-block: a benign command that merely *contains*
    `gh pr create` inside a quote/echo must NOT be blocked on parser crash
    (anchored check misses it) — exit 0."""
    cmd = "echo 'see: gh pr create --base main' >> notes.txt"
    r = _run_hook_with_broken_parser(tmp_path, cmd)
    assert r.returncode == 0


def test_f1_parser_crash_chained_gh_falls_open(tmp_path):
    """A chained (non-leading) `&& gh pr merge` falls open on crash —
    acceptable per the fail-open philosophy (one slipped merge is
    recoverable; over-blocking is not)."""
    r = _run_hook_with_broken_parser(tmp_path, "make build && gh pr merge --delete-branch")
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# detect_git_push_delete — worktree-safe post-merge remote delete (issue #1283)
# ---------------------------------------------------------------------------


def test_push_delete_flag_after_remote(bgp):
    assert bgp.detect_git_push_delete("git push origin --delete feat/issue-1-x") == ["feat/issue-1-x"]


def test_push_delete_flag_before_remote(bgp):
    assert bgp.detect_git_push_delete("git push --delete origin feat/B") == ["feat/B"]


def test_push_delete_short_flag(bgp):
    assert bgp.detect_git_push_delete("git push origin -d feat/B") == ["feat/B"]
    assert bgp.detect_git_push_delete("git push -d origin feat/B") == ["feat/B"]


def test_push_delete_colon_refspec(bgp):
    assert bgp.detect_git_push_delete("git push origin :feat/B") == ["feat/B"]


def test_push_delete_refs_heads_prefix_stripped(bgp):
    assert bgp.detect_git_push_delete(
        "git push origin --delete refs/heads/feat/B"
    ) == ["feat/B"]


def test_push_delete_multiple_targets(bgp):
    assert bgp.detect_git_push_delete(
        "git push origin --delete feat/A feat/B"
    ) == ["feat/A", "feat/B"]


def test_ordinary_push_is_not_a_delete(bgp):
    assert bgp.detect_git_push_delete("git push origin feat/B") == []
    assert bgp.detect_git_push_delete("git push -u origin feat/B") == []
    assert bgp.detect_git_push_delete("git push origin HEAD:main") == []


def test_push_delete_in_compound_command(bgp):
    assert bgp.detect_git_push_delete(
        "gh pr merge 5 --squash && git push origin --delete feat/B"
    ) == ["feat/B"]


def test_non_push_command_is_empty(bgp):
    assert bgp.detect_git_push_delete("gh pr merge 5 --delete-branch") == []
    assert bgp.detect_git_push_delete("rm -rf --delete origin x") == []


def test_cli_detect_push_delete_stdout(bgp):
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, str(PARSE_PATH), "--detect-push-delete",
         "git push origin --delete feat/B"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "feat/B"
