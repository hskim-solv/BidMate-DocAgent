#!/usr/bin/env python3
"""Detect dead markdown cross-references (relative links + prose ADR refs).

Single source of truth for the link-integrity regexes + resolution rules.
Called from three places:

- `.githooks/pre-commit` (local, shift-left) → `--check-all`
  Fires a *whole-tree* scan whenever any `.md` is staged, because the
  recurring failure is a file MOVE that breaks an inbound link from a
  file the commit never touched (see issue #1060 / commits 627a63b,
  9754f69, da80073). A staged-only scan structurally cannot catch that.
- `tests/test_doc_links.py::test_repo_has_no_broken_doc_links_today` →
  the real-repo sentinel that `pr-eval.yml` runs as part of the full
  pytest suite. That sentinel IS the canonical CI hard-fail gate; the
  hook + Makefile target are the shift-left conveniences.
- `Makefile` `check-doc-links` target → `--check-all` (local ergonomics,
  chained into `governance-check`).

Scope (deliberately narrow to keep false positives near zero):
  - Sources: all tracked `*.md` EXCEPT under `.claude/` (agent/skill
    definitions legitimately carry placeholder/example links).
  - Targets: any repo path, resolved relative to the SOURCE file's dir.
  - Checked: inline `[text](path)` links to a real file, and prose
    `ADR NNNN` references to a real `docs/adr/NNNN-*.md`.
  - NOT checked: external URLs (network dependency), same-file `#anchor`
    fragments (anchor validation deferred — the recurrence is file-level),
    site-absolute `/...` and directory-style Jekyll permalinks (the docs
    render via `permalink: pretty`, so `[x](../foo/)` is a valid page link
    that has no filesystem target).

Zero runtime dependencies (Python stdlib + `git ls-files`).

Exit codes:
    0  ok (no broken links / refs)
    1  broken link(s) or dead ADR ref(s) found (printed to stderr)
    2  internal / usage error
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from _governance import existing_adr_numbers


# Inline link: `[text](href)`. `[^\]]*` keeps it cheap and also matches the
# `[alt](src)` portion of an image `![alt](src)`, so broken image refs are
# caught too. Reference-style links (`[text][ref]`) are intentionally NOT
# matched — a tree-wide grep confirmed zero `[ref]: url` definitions exist.
INLINE_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Prose ADR reference, e.g. "ADR 0007" / "ADR-0007". Exactly four digits with
# a trailing word boundary so "ADR 00444" (5 digits) does not match a prefix.
ADR_PROSE_RE = re.compile(r"\bADR[\s\-]+(\d{4})\b")

# Hrefs we never existence-check (external / non-filesystem).
_EXTERNAL_RE = re.compile(r"^(?:https?:|mailto:|tel:|ftp:)", re.IGNORECASE)

# A link is treated as a real filesystem target only when its final path
# segment carries one of these extensions. Everything else (no extension,
# trailing slash) is a directory-style Jekyll permalink — skipped. This is
# the single most important false-positive guard for this repo (ADR 0007-
# style `[ADR 7](../adr/0007-issue-linked-branch-naming/)` page links).
# `.html` is deliberately excluded: it is the rendered-output extension and
# `[x](architecture-deep-dive.html)` has no source file of that name.
_KNOWN_EXT_RE = re.compile(
    r"\.(?:md|markdown|py|ya?ml|json|jsonl|toml|cfg|ini|txt|sh|bash|zsh|"
    r"png|jpe?g|gif|svg|webp|ico|pdf|csv|tsv|mmd|lock|cff|mk|env)$",
    re.IGNORECASE,
)

# Tracked-file source set excludes these prefixes (see module docstring).
_EXCLUDED_SOURCE_PREFIXES = (".claude/",)


def _err(msg: str) -> None:
    sys.stderr.write(msg)
    if not msg.endswith("\n"):
        sys.stderr.write("\n")


def tracked_markdown_files(repo_root: str | Path = ".") -> list[str]:
    """Return repo-relative tracked `*.md` paths, minus excluded prefixes.

    Uses `git ls-files` so untracked scratch files and vendored trees are
    never scanned. Returns an empty list if git is unavailable (the caller
    treats that as "nothing to check" rather than an error — the canonical
    enforcement is the pytest gate, which always runs inside the repo).
    """
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "*.md", "*.markdown"],
            cwd=str(repo_root),
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    files = [line for line in out.splitlines() if line.strip()]
    return [
        f for f in files
        if not f.startswith(_EXCLUDED_SOURCE_PREFIXES)
    ]


def strip_code_spans(text: str) -> str:
    """Drop fenced code blocks + inline code so example links inside them
    are not mistaken for real cross-references.

    Fenced blocks are matched line-by-line (more robust than a single regex
    against ragged indentation): a line whose first non-space content is
    ``` or ~~~ opens a fence; the next same-type marker closes it. Inline
    `code` spans are then blanked.
    """
    out: list[str] = []
    in_fence = False
    fence_char = ""
    for line in text.splitlines():
        m = re.match(r"\s*(`{3,}|~{3,})", line)
        if not in_fence:
            if m:
                in_fence = True
                fence_char = m.group(1)[0]
                continue
            out.append(line)
        else:
            if m and m.group(1)[0] == fence_char:
                in_fence = False
            continue
    joined = "\n".join(out)
    return re.sub(r"`[^`\n]*`", "", joined)


def extract_links(text: str) -> list[str]:
    """Return the raw hrefs of every inline `[text](href)` link in `text`.

    Pass code-stripped text (see `strip_code_spans`) to avoid example links.
    """
    return [m.group(1) for m in INLINE_LINK_RE.finditer(text)]


def normalize_target(raw: str) -> str | None:
    """Normalize a raw href to a filesystem-checkable relative path.

    Returns None when the link should be skipped (external URL, same-file
    anchor, site-absolute path, or directory-style permalink). Otherwise
    returns the path with angle brackets, a trailing ``"title"``, a
    ``#fragment`` and a ``:linenumber`` suffix removed.
    """
    t = raw.strip()
    if not t:
        return None
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    # Strip a trailing markdown link title:  path "Title"  /  path 'Title'
    t = re.sub(r"""\s+["'].*$""", "", t).strip()
    if not t:
        return None
    if (
        _EXTERNAL_RE.match(t)
        or t.startswith("//")   # protocol-relative
        or t.startswith("#")    # same-file anchor (deferred)
        or t.startswith("/")    # site-absolute (Jekyll site root)
    ):
        return None
    t = t.split("#", 1)[0]               # drop URL fragment
    t = re.sub(r":\d+(?:-\d+)?$", "", t)  # drop `path:line` / `path:line-line`
    if not t:
        return None
    final_segment = t.rstrip("/").rsplit("/", 1)[-1]
    if not _KNOWN_EXT_RE.search(final_segment):
        return None  # directory-style permalink — no filesystem target
    return t


def find_broken_links(
    md_files: list[str],
    repo_root: str | Path = ".",
) -> list[tuple[str, str, str]]:
    """Return ``[(source, raw_href, resolved_relpath), ...]`` for links whose
    target file does not exist.

    Each target is resolved relative to its SOURCE file's directory (standard
    markdown semantics), then normalized to a repo-relative path for both the
    existence check and the error message. `md_files` are repo-relative.
    """
    root = Path(repo_root)
    broken: list[tuple[str, str, str]] = []
    for src in md_files:
        try:
            text = (root / src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        src_dir = os.path.dirname(src)
        for href in extract_links(strip_code_spans(text)):
            target = normalize_target(href)
            if target is None:
                continue
            rel = os.path.normpath(os.path.join(src_dir, target))
            if not (root / rel).exists():
                broken.append((src, href, rel))
    return broken


def find_broken_adr_refs(
    md_files: list[str],
    repo_root: str | Path = ".",
    adr_dir: str | Path | None = None,
    allow_forward: bool = True,
) -> list[tuple[str, str]]:
    """Return ``[(source, "NNNN"), ...]`` for prose ``ADR NNNN`` references
    that have no matching `docs/adr/NNNN-*.md` file.

    Reuses `_governance.existing_adr_numbers` (the SSoT for "which ADR numbers
    exist"). When `allow_forward` is true, a reference whose number exceeds the
    current max ADR is treated as a *planned* ADR pointer and skipped — the
    repo legitimately carries forward-references (e.g. ADR 0060/0061/0062 named
    before their files land). A reference at-or-below the max that has no file
    is a genuine dead ref (a typo, or a number that was never created).
    Deduplicated per (source, number).
    """
    root = Path(repo_root)
    if adr_dir is None:
        adr_dir = root / "docs" / "adr"
    existing = existing_adr_numbers(adr_dir)
    max_existing = max(existing) if existing else 0
    broken: list[tuple[str, str]] = []
    for src in md_files:
        try:
            text = (root / src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen: set[int] = set()
        for m in ADR_PROSE_RE.finditer(strip_code_spans(text)):
            num = int(m.group(1))
            if num in existing or num in seen:
                continue
            if allow_forward and num > max_existing:
                continue
            seen.add(num)
            broken.append((src, f"{num:04d}"))
    return broken


# ---------------------------------------------------------------------------
# CLI wrappers
# ---------------------------------------------------------------------------


def _report_broken_links(broken: list[tuple[str, str, str]]) -> None:
    _err(
        f"\n❌ Markdown dead-link check failed (issue #1060): "
        f"{len(broken)} broken internal link(s).\n"
    )
    for src, href, rel in broken:
        _err(f"     {src}\n         [{href}]  →  {rel}  (missing)\n")
    _err(
        "\n   Fix the relative path — the common cause is `../` depth "
        "(a file in\n"
        "   docs/<sub>/ linking code at the repo root needs `../../`, not "
        "`../`), or\n"
        "   a target that was moved/renamed. External URLs and Jekyll "
        "permalinks\n"
        "   (`[x](../foo/)`, no extension) are not checked.\n"
        "   Run locally: make check-doc-links\n\n"
    )


def _report_broken_adr_refs(broken: list[tuple[str, str]]) -> None:
    _err(
        f"\n❌ Dead ADR-reference check failed (issue #1060): "
        f"{len(broken)} prose `ADR NNNN` reference(s) with no file.\n"
    )
    for src, num in broken:
        _err(f"     {src}\n         ADR {num}  →  docs/adr/{num}-*.md  (missing)\n")
    _err(
        "\n   Either create the ADR file, fix the number, or — if it is a\n"
        "   genuinely planned future ADR — note that forward references are\n"
        "   tolerated only when the number exceeds the current max ADR.\n\n"
    )


def _run(
    check_links: bool,
    check_adr: bool,
    paths: list[str] | None,
    repo_root: str | Path,
    allow_forward: bool,
) -> int:
    md_files = paths if paths else tracked_markdown_files(repo_root)
    rc = 0
    if check_links:
        broken = find_broken_links(md_files, repo_root)
        if broken:
            _report_broken_links(broken)
            rc = 1
    if check_adr:
        dead = find_broken_adr_refs(md_files, repo_root, allow_forward=allow_forward)
        if dead:
            _report_broken_adr_refs(dead)
            rc = 1
    if rc == 0:
        scope = "links + ADR refs" if (check_links and check_adr) else (
            "links" if check_links else "ADR refs"
        )
        sys.stdout.write(
            f"OK: {len(md_files)} markdown file(s) scanned; no broken {scope}.\n"
        )
    return rc


def main() -> int:
    p = argparse.ArgumentParser(
        description="Detect dead markdown cross-references (issue #1060).",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--check-links", action="store_true",
        help="Check relative inline links resolve to a real file.",
    )
    g.add_argument(
        "--check-adr-refs", action="store_true",
        help="Check prose `ADR NNNN` references resolve to a real ADR file.",
    )
    g.add_argument(
        "--check-all", action="store_true",
        help="Run both checks (used by the pre-commit hook + Makefile).",
    )
    p.add_argument(
        "--paths", nargs="*", default=None, metavar="MD_FILE",
        help="Explicit markdown files to scan (default: all tracked `*.md` "
             "via `git ls-files`, excluding .claude/). Mainly for tests.",
    )
    p.add_argument(
        "--repo-root", default=".",
        help="Repo root for resolution + `git ls-files` (default: cwd).",
    )
    p.add_argument(
        "--no-allow-forward-adr", action="store_true",
        help="Treat a forward ADR reference (number > current max) as a "
             "violation instead of a tolerated planned-ADR pointer.",
    )
    args = p.parse_args()

    check_links = args.check_links or args.check_all
    check_adr = args.check_adr_refs or args.check_all
    return _run(
        check_links,
        check_adr,
        args.paths,
        args.repo_root,
        allow_forward=not args.no_allow_forward_adr,
    )


if __name__ == "__main__":
    sys.exit(main())
