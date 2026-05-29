#!/usr/bin/env python3
"""Pure-function parsers extracted from pretooluse-bash-guard.sh.

거버넌스 비판 보고서 (2026-05-19) #5 후속 (issue #1045).

The bash-guard hook needs to inspect a Claude-issued `Bash` command and decide:
  (a) Is it a `gh pr merge` or `gh pr create` invocation?
  (b) If `create`, did the user pass `--base <branch>` explicitly?

Both questions are answered by `shlex.split()` plus `re.split()` on shell
separators. The logic lived inline as one-shot `python3 -c '...'` blocks
inside the bash hook, making it impossible to unit-test against adversarial
shell quoting (#5 in the governance critique). This module pulls the logic
into named pure functions so `tests/test_bash_guard_adversarial.py` can
nail down the false-negative surface.

Contract:
- All functions are deterministic, no I/O, no environment lookup.
- Tokenization is shlex-first (finding F3): each line is fed through a
  `shlex.shlex` lexer with `punctuation_chars=True`, then the token stream
  is split on separator tokens (`;`, `&`, `&&`, `|`, `||`). This respects
  quoting, so a quoted separator inside a command — `gh pr create --title
  "a; b"` — no longer splits that command mid-segment (the old
  `re.split` before shlex did). Newlines are pre-split (a multi-line
  command is multiple statements); a line whose quoting is malformed
  (shlex `ValueError`) falls back to the legacy regex-split-per-segment
  salvage so a `gh` command in a *separable* segment is still caught.
- Documented false-negatives (see tests): single-quoted whole command,
  `eval`-wrapped invocations, env-var interpolation, command substitution.
  These reflect shlex's inherent limits — fixing them requires a real
  shell parser (not on the roadmap; see issue #1045 for the trade-off).

CLI form (for the bash hook to consume without an inline python block):

    python3 _bash_guard_parse.py --detect-gh "$cmd"      # echoes "merge", "create", ""
    python3 _bash_guard_parse.py --has-base "$cmd"       # exit 0 iff EVERY create has --base, else 1
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from typing import Literal

GhSubcommand = Literal["merge", "create", ""]

# Separator *tokens* emitted by the punctuation_chars lexer (runs of these
# chars are grouped into a single token, e.g. "&&", "||").
_SEPARATOR_TOKENS = frozenset({";", "&", "&&", "|", "||"})
# Legacy regex separators, used only by the malformed-quote fallback.
_SHELL_SEPARATOR_RE = re.compile(r"[;&|]")


def _split_token_stream(tokens: list[str]) -> list[list[str]]:
    """Group a shlex token list into segments on separator tokens.

    Drops bare grouping-paren tokens (`(`, `)`, `((`) so a subshell opener
    (`(gh pr merge ...)`) still yields `["gh", "pr", "merge", ...]`.
    """
    out: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in _SEPARATOR_TOKENS:
            if current:
                out.append(current)
                current = []
        elif tok and all(ch in "()" for ch in tok):
            continue  # grouping paren run — not a command word
        else:
            current.append(tok)
    if current:
        out.append(current)
    return out


def _segments(cmd: str) -> list[list[str]]:
    """Tokenize shlex-first, then split on separators (finding F3).

    Each line is lexed by `shlex.shlex(..., punctuation_chars=True)` so a
    quoted separator inside an argument does not split the command. Lines
    are processed independently (a newline separates statements). A line
    whose quoting is malformed (shlex `ValueError`) falls back to the
    legacy regex-split-per-segment salvage so a `gh` command sitting in a
    *separable* segment is still caught rather than lost wholesale.
    """
    out: list[list[str]] = []
    for line in cmd.split("\n"):
        if not line.strip():
            continue
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            out.extend(_fallback_segments(line))
            continue
        out.extend(_split_token_stream(tokens))
    return out


def _fallback_segments(line: str) -> list[list[str]]:
    """Legacy salvage for a line with malformed quoting.

    The whole-line lexer raised `ValueError` (unbalanced quote). Split on
    raw separators and shlex each piece — pieces that are themselves still
    malformed are dropped (fail-open), but a clean `gh` segment after a
    bad one is recovered.
    """
    out: list[list[str]] = []
    for part in _SHELL_SEPARATOR_RE.split(line):
        part = part.strip().lstrip("(")
        if not part:
            continue
        try:
            tokens = shlex.split(part)
        except ValueError:
            continue
        if tokens:
            out.append(tokens)
    return out


def detect_gh_subcommand(cmd: str) -> GhSubcommand:
    """Return ``"merge"``, ``"create"``, or ``""``.

    Matches when a segment is structured as ``gh pr <merge|create> [...]``
    after shell-separator splitting. The first match wins.
    """
    for tokens in _segments(cmd):
        if (
            len(tokens) >= 3
            and tokens[0] == "gh"
            and tokens[1] == "pr"
            and tokens[2] in ("merge", "create")
        ):
            return tokens[2]  # type: ignore[return-value]
    return ""


def detect_git_push_delete(cmd: str) -> list[str]:
    """Return the branch names a ``git push`` segment deletes on a remote.

    Recognizes every spelling of a remote-branch delete::

        git push origin --delete BR        git push --delete origin BR
        git push origin -d BR              git push -d origin BR
        git push origin :BR                (colon refspec, empty source side)

    Returns ``[]`` when no segment is a delete-push. Any leading ``:`` or
    ``refs/heads/`` is stripped. Multiple deletes in one push
    (``git push origin --delete BR1 BR2``) yield multiple entries.

    The worktree-safe post-merge flow (issue #1283) deletes the remote head
    branch this way instead of ``gh pr merge --delete-branch`` (whose local
    checkout-to-default step aborts when ``main`` is checked out in another
    worktree). The deletion still auto-closes any PR that bases on the
    branch, so the bash-guard reuses this to extend its stacked-dependent
    guard to the push form. Same shlex false-negative surface as the sibling
    parsers (single-quoted whole command, eval-wrap, env-var, command subst).
    """
    targets: list[str] = []
    for tokens in _segments(cmd):
        if len(tokens) < 3 or tokens[0] != "git" or tokens[1] != "push":
            continue
        rest = tokens[2:]
        has_delete_flag = any(t in ("--delete", "-d") for t in rest)
        # First positional is the remote; remaining positionals are refspecs.
        positionals = [t for t in rest if not t.startswith("-")]
        refspecs = positionals[1:]
        for refspec in refspecs:
            if has_delete_flag:
                branch = refspec.lstrip(":")
            elif refspec.startswith(":"):
                branch = refspec[1:]  # colon-refspec delete (empty source)
            else:
                continue  # ordinary push of this refspec — not a delete
            branch = branch[len("refs/heads/"):] if branch.startswith("refs/heads/") else branch
            if branch:
                targets.append(branch)
    return targets


def _segment_has_base(tokens: list[str]) -> bool:
    return any(t == "--base" or t.startswith("--base=") for t in tokens[3:])


def all_create_segments_have_base(cmd: str) -> bool:
    """Return True iff there is ≥1 ``gh pr create`` segment and *every* one
    of them carries ``--base`` / ``--base=…``.

    The bash-guard's `gh pr create` branch uses this as a bypass:
    `--base main` is the documented escape for "flatten this onto main on
    purpose." The check must be per-segment (finding F2) — the old
    any-segment form let a compound like
    ``gh pr create --title bad && gh pr create --base main`` bypass the
    guard, slipping the base-less (stack-collapsing) create through. We
    only bypass when *no* base-less create remains.
    """
    creates = [
        tokens
        for tokens in _segments(cmd)
        if len(tokens) >= 3
        and tokens[0] == "gh"
        and tokens[1] == "pr"
        and tokens[2] == "create"
    ]
    return bool(creates) and all(_segment_has_base(t) for t in creates)


def get_create_flag_value(cmd: str, flag: str) -> str:
    """Return the value of `flag` in the first `gh pr create` segment ('' if absent).

    Handles both `--flag VALUE` and `--flag=VALUE`. Same shlex-based
    false-negative surface as the sibling parsers — a value built with
    command substitution / heredoc (`--body "$(cat <<EOF…)"`) is NOT
    statically extractable and returns '' (callers treat that as "skip",
    fail-open). Originally added for the §5b soft-warn (issue #1097); that
    bash-guard call site was removed when the §5b gate was deprecated (ADR
    0084), but the parser and its CLI remain as a general flag extractor.
    """
    for tokens in _segments(cmd):
        if (
            len(tokens) >= 3
            and tokens[0] == "gh"
            and tokens[1] == "pr"
            and tokens[2] == "create"
        ):
            rest = tokens[3:]
            for i, t in enumerate(rest):
                if t == flag and i + 1 < len(rest):
                    return rest[i + 1]
                if t.startswith(flag + "="):
                    return t.split("=", 1)[1]
    return ""


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--detect-gh", metavar="CMD")
    g.add_argument("--has-base", metavar="CMD")
    g.add_argument(
        "--get-body", metavar="CMD",
        help="Echo the value of --body in a `gh pr create` segment ('' if absent).",
    )
    g.add_argument(
        "--get-body-file", metavar="CMD",
        help="Echo the value of --body-file in a `gh pr create` segment ('' if absent).",
    )
    g.add_argument(
        "--detect-push-delete", metavar="CMD",
        help="Echo the branch names a `git push` segment deletes, one per line ('' if none).",
    )
    args = p.parse_args(argv)
    if args.detect_gh is not None:
        sys.stdout.write(detect_gh_subcommand(args.detect_gh) + "\n")
        return 0
    if args.has_base is not None:
        return 0 if all_create_segments_have_base(args.has_base) else 1
    if args.get_body is not None:
        sys.stdout.write(get_create_flag_value(args.get_body, "--body") + "\n")
        return 0
    if args.get_body_file is not None:
        sys.stdout.write(get_create_flag_value(args.get_body_file, "--body-file") + "\n")
        return 0
    if args.detect_push_delete is not None:
        sys.stdout.write("\n".join(detect_git_push_delete(args.detect_push_delete)) + "\n")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
