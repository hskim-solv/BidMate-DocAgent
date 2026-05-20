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
- Both functions are deterministic, no I/O, no environment lookup.
- They tokenize per `re.split(r"[;&|\\n]", cmd)` (so `foo && gh pr merge`
  still gets caught), strip an opening `(`, and feed each segment through
  `shlex.split`. ParseError → segment skipped (fail-open).
- Documented false-negatives (see tests): single-quoted whole command,
  `eval`-wrapped invocations, env-var interpolation, command substitution.
  These reflect shlex's inherent limits — fixing them requires a real
  shell parser (not on the roadmap; see issue #1045 for the trade-off).

CLI form (for the bash hook to consume without an inline python block):

    python3 _bash_guard_parse.py --detect-gh "$cmd"      # echoes "merge", "create", ""
    python3 _bash_guard_parse.py --has-base "$cmd"       # exit 0 if --base seen, else 1
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from typing import Literal

GhSubcommand = Literal["merge", "create", ""]

_SHELL_SEPARATOR_RE = re.compile(r"[;&|\n]")


def _segments(cmd: str) -> list[list[str]]:
    """Split on shell separators, shlex each segment, drop unparseable parts.

    Strips one leading `(` per segment to handle subshell openers
    (`(gh pr merge ...)`). Returns the list of token lists.
    """
    out: list[list[str]] = []
    for part in _SHELL_SEPARATOR_RE.split(cmd):
        part = part.strip().lstrip("(")
        if not part:
            continue
        try:
            tokens = shlex.split(part)
        except ValueError:
            # Malformed quoting → skip this segment (fail-open).
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


def has_explicit_base_flag(cmd: str) -> bool:
    """Return True if any ``gh pr create`` segment has ``--base`` or ``--base=…``.

    The bash-guard's `gh pr create` branch uses `--base` as a documented
    bypass (`gh pr create --base main` = "flatten this onto main on purpose").
    This function answers "did the user explicitly say where to point this
    PR?" without evaluating the branch ref itself.
    """
    for tokens in _segments(cmd):
        if (
            len(tokens) >= 3
            and tokens[0] == "gh"
            and tokens[1] == "pr"
            and tokens[2] == "create"
        ):
            if any(
                t == "--base" or t.startswith("--base=")
                for t in tokens[3:]
            ):
                return True
    return False


def get_create_flag_value(cmd: str, flag: str) -> str:
    """Return the value of `flag` in the first `gh pr create` segment ('' if absent).

    Handles both `--flag VALUE` and `--flag=VALUE`. Same shlex-based
    false-negative surface as the sibling parsers — a body built with
    command substitution / heredoc (`--body "$(cat <<EOF…)"`) is NOT
    statically extractable and returns '' (the caller treats that as
    "skip", fail-open). Used by the §5b soft-warn (issue #1097).
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
    args = p.parse_args(argv)
    if args.detect_gh is not None:
        sys.stdout.write(detect_gh_subcommand(args.detect_gh) + "\n")
        return 0
    if args.has_base is not None:
        return 0 if has_explicit_base_flag(args.has_base) else 1
    if args.get_body is not None:
        sys.stdout.write(get_create_flag_value(args.get_body, "--body") + "\n")
        return 0
    if args.get_body_file is not None:
        sys.stdout.write(get_create_flag_value(args.get_body_file, "--body-file") + "\n")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
