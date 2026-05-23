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
  - Checked: inline `[text](path)` links to a real file; prose
    `ADR NNNN` references to a real `docs/adr/NNNN-*.md`; and `#fragment`
    anchors — both same-file `[x](#frag)` and cross-file `[x](other.md#frag)`
    — against the target `.md`'s heading slugs (GitHub `github-slugger`
    rules) plus explicit `<a id=…>`/`<a name=…>`/`{#id}` anchors. Fragment
    validation was added after issue #1152: Korean-izing a heading changes
    its auto-generated slug, silently breaking inbound `#old-english-anchor`
    links that a file-existence-only check cannot see.
  - NOT checked: external URLs (network dependency), site-absolute `/...`,
    the EXISTENCE of directory-style Jekyll permalinks (the docs render via
    `permalink: pretty`, so `[x](../foo/)` is a valid page link that has no
    filesystem target), and `#fragment`s on non-`.md` targets (e.g. a
    `foo.py#L10` GitHub line anchor — we only enumerate markdown anchors).
  - Partially checked: a `#fragment` on a directory-style permalink. The page
    has no filesystem target for the existence check, but `permalink: pretty`
    maps `[x](../foo/#frag)` to the backing `docs/foo.md`, so the anchor IS
    validated against that file's slugs when it exists (issue #1406 closed the
    blind spot where a translated heading could break such a link unseen).

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


# ---------------------------------------------------------------------------
# Fragment-anchor validation (issue #1152)
# ---------------------------------------------------------------------------

# GitHub's heading→anchor algorithm (the `github-slugger` package its markdown
# renderer uses): lowercase, drop this fixed punctuation set, then turn every
# whitespace char into a hyphen. The two unicode ranges (general + supplemental
# punctuation) drop the em-/en-dash etc. Hyphen `-` and underscore `_` are
# DELIBERATELY absent from the set — GitHub keeps them in slugs.
_SLUG_STRIP_RE = re.compile(
    "[\\u2000-\\u206f\\u2e00-\\u2e7f"          # general + supplemental punctuation
    "\\\\'!\"#$%&()*+,./:;<=>?@\\[\\]^`{|}~]"  # ASCII punctuation (keeps - and _)
)

# ATX heading line: 1–6 leading `#` then a space. Captures the text, dropping
# an optional trailing run of `#`. Setext (`===`/`---` underline) headings are
# not handled — the repo uses ATX exclusively and `---` collides with both the
# YAML front-matter delimiter and a thematic break.
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")

# Inline link inside a heading, reduced to its visible text for slugging:
# `## see [foo](x.md)` → GitHub slugs the rendered text "see foo".
_HEADING_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# Explicit anchors that GitHub/Jekyll honor in addition to heading slugs.
# `{#id}` is kramdown-only (GitHub ignores it) but is treated as VALID anyway:
# an extra anchor can only suppress a false positive, never create one.
_HTML_ANCHOR_RE = re.compile(
    r"""<a\s+(?:id|name)\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_KRAMDOWN_ANCHOR_RE = re.compile(r"\{#([\w-]+)\}")

# Only markdown targets have an enumerable anchor set.
_MD_TARGET_RE = re.compile(r"\.(?:md|markdown)$", re.IGNORECASE)


def slugify_heading(text: str) -> str:
    """Return the GitHub anchor slug for a heading.

    Mirrors `github-slugger`. Accepts either a raw heading line (`## Title`)
    or already-extracted heading text (`Title`); a leading `#{1,6} ` run is
    stripped when present. Inline links are reduced to their visible text
    before slugging.
    """
    m = _HEADING_RE.match(text)
    if m:
        text = m.group(1)
    text = _HEADING_LINK_RE.sub(r"\1", text)
    s = _SLUG_STRIP_RE.sub("", text.strip().lower())
    return re.sub(r"\s", "-", s)


def _iter_heading_lines(text: str):
    """Yield ATX heading lines, skipping regions that produce no GitHub anchor:
    leading YAML front-matter, fenced code blocks, and HTML comment blocks.
    """
    lines = text.splitlines()
    n = len(lines)
    i = 0
    # Leading YAML front-matter: only when the very first line is exactly `---`.
    if n and lines[0].strip() == "---":
        i = 1
        while i < n and lines[i].strip() != "---":
            i += 1
        i += 1  # consume the closing `---`
    in_fence = False
    fence_char = ""
    in_comment = False
    while i < n:
        line = lines[i]
        i += 1
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        fence = re.match(r"\s*(`{3,}|~{3,})", line)
        if not in_fence and fence:
            in_fence = True
            fence_char = fence.group(1)[0]
            continue
        if in_fence:
            if fence and fence.group(1)[0] == fence_char:
                in_fence = False
            continue
        stripped = line.strip()
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        if _HEADING_RE.match(line):
            yield line


def collect_anchors(text: str) -> set[str]:
    """Return the set of valid lowercase fragment targets in a markdown doc:
    every heading's slug (with GitHub's per-document `-1`/`-2`… duplicate
    suffixing) plus explicit `<a id=…>`/`<a name=…>`/`{#id}` anchors.
    """
    anchors: set[str] = set()
    for m in _HTML_ANCHOR_RE.finditer(text):
        anchors.add(m.group(1).strip().lower())
    for m in _KRAMDOWN_ANCHOR_RE.finditer(text):
        anchors.add(m.group(1).strip().lower())
    counts: dict[str, int] = {}
    for line in _iter_heading_lines(text):
        slug = slugify_heading(line)
        seen = counts.get(slug, 0)
        anchors.add(slug if seen == 0 else f"{slug}-{seen}")
        counts[slug] = seen + 1
    return anchors


def split_fragment(raw: str) -> tuple[str, str] | None:
    """Parse an inline href into ``(path_without_fragment, fragment)`` when the
    link carries a checkable `#fragment`, else None.

    Returns ``("", frag)`` for a same-file `#frag` link. Returns None for:
    links with no `#`, external/protocol-relative/site-absolute links, an
    empty fragment, and cross-file links whose target is a non-markdown file
    with a recognized extension (`foo.py#L10`, `img.png#x` — only markdown
    anchors are enumerable). A direct `.md`/`.markdown` target and a
    directory-style Jekyll permalink (extensionless / trailing-slash, e.g.
    `../engineering-governance/#frag`) are BOTH kept: the permalink's
    `<path>/` → `<path>.md` resolution is deferred to `find_broken_fragments`,
    which validates the anchor only when a backing markdown file exists.
    Mirrors `normalize_target`'s angle-bracket and trailing-``"title"``
    stripping, but — unlike it — KEEPS the fragment, which is the whole point.
    """
    t = raw.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    t = re.sub(r"""\s+["'].*$""", "", t).strip()
    if "#" not in t:
        return None
    if _EXTERNAL_RE.match(t) or t.startswith("//") or t.startswith("/"):
        return None
    path_part, frag = t.split("#", 1)
    frag = frag.strip()
    if not frag:
        return None
    if path_part == "":
        return ("", frag)
    path_part = re.sub(r":\d+(?:-\d+)?$", "", path_part)  # drop `path:line`
    final_segment = path_part.rstrip("/").rsplit("/", 1)[-1]
    if _MD_TARGET_RE.search(final_segment):
        return (path_part, frag)  # direct markdown target
    if _KNOWN_EXT_RE.search(final_segment):
        return None  # non-md file (.py/.png/…): no enumerable anchor set
    # Extensionless / trailing-slash → Jekyll `permalink: pretty` directory
    # permalink (docs/_config.yml). Keep it; find_broken_fragments resolves
    # `<path>/` → `<path>.md` and only checks the anchor when that file exists.
    return (path_part, frag)


def _resolve_fragment_target(
    src_dir: str, path_part: str, root: Path
) -> str | None:
    """Resolve a fragment link's path (``#`` already stripped) to an existing
    markdown file relative to its source dir, or None.

    A direct `.md`/`.markdown` target resolves to itself when present. An
    extensionless / trailing-slash target is a Jekyll `permalink: pretty`
    directory permalink (docs/_config.yml): it maps to the sibling
    `<path>.md`, then `<path>/index.md`. Returns None when no markdown file
    backs the link — a missing `.md` is `find_broken_links`' job, and an
    unresolvable permalink has no anchor set to check, so staying silent keeps
    false positives at zero.
    """
    base = os.path.normpath(os.path.join(src_dir, path_part))
    if _MD_TARGET_RE.search(base):
        return base if (root / base).exists() else None
    for cand in (f"{base}.md", os.path.join(base, "index.md")):
        if (root / cand).exists():
            return cand
    return None


def find_broken_fragments(
    md_files: list[str],
    repo_root: str | Path = ".",
) -> list[tuple[str, str, str]]:
    """Return ``[(source, raw_href, fragment), ...]`` for links whose `#anchor`
    has no matching heading slug / explicit anchor in the target markdown file.

    A missing TARGET FILE is intentionally NOT reported here — that is
    `find_broken_links`' job; this check stays silent so a single broken link
    does not double-report. Anchor sets are computed once per target file.
    """
    root = Path(repo_root)
    anchor_cache: dict[str, set[str] | None] = {}

    def anchors_for(relpath: str) -> set[str] | None:
        if relpath not in anchor_cache:
            try:
                body = (root / relpath).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                anchor_cache[relpath] = None
            else:
                anchor_cache[relpath] = collect_anchors(body)
        return anchor_cache[relpath]

    broken: list[tuple[str, str, str]] = []
    for src in md_files:
        try:
            text = (root / src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        src_dir = os.path.dirname(src)
        for href in extract_links(strip_code_spans(text)):
            parsed = split_fragment(href)
            if parsed is None:
                continue
            path_part, frag = parsed
            if path_part == "":
                target = src
            else:
                resolved = _resolve_fragment_target(src_dir, path_part, root)
                if resolved is None:
                    continue  # missing file / unresolvable permalink → not our report
                target = resolved
            anchors = anchors_for(target)
            if anchors is None:
                continue
            if frag.lower() not in anchors:
                broken.append((src, href, frag))
    return broken


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


def _report_broken_fragments(broken: list[tuple[str, str, str]]) -> None:
    _err(
        f"\n❌ Markdown fragment-anchor check failed (issue #1152): "
        f"{len(broken)} link(s) point to a #anchor that does not exist.\n"
    )
    for src, href, frag in broken:
        _err(f"     {src}\n         [{href}]  →  no heading/anchor '#{frag}'\n")
    _err(
        "\n   The target file exists but has no heading whose GitHub slug is\n"
        "   this #fragment (and no explicit <a id=…>/<a name=…>/{#id} anchor).\n"
        "   The usual cause is a renamed/translated heading whose old\n"
        "   #english-anchor is still linked (issue #1152). Fix: point the\n"
        "   #fragment at the new slug, or add a stable `<a id=\"old-anchor\">"
        "</a>`\n"
        "   on its own line before the heading to keep external links alive.\n"
        "   Run locally: make check-doc-links\n\n"
    )


def _run(
    check_links: bool,
    check_adr: bool,
    check_fragments: bool,
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
    if check_fragments:
        bad_frags = find_broken_fragments(md_files, repo_root)
        if bad_frags:
            _report_broken_fragments(bad_frags)
            rc = 1
    if rc == 0:
        scopes = [
            name
            for name, on in (
                ("links", check_links),
                ("ADR refs", check_adr),
                ("fragments", check_fragments),
            )
            if on
        ]
        scope = (
            " + ".join(scopes[:-1]) + " + " + scopes[-1]
            if len(scopes) > 1
            else scopes[0]
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
        "--check-fragments", action="store_true",
        help="Check `#anchor` fragments resolve to a heading slug / explicit "
             "anchor in the target `.md` (issue #1152).",
    )
    g.add_argument(
        "--check-all", action="store_true",
        help="Run all checks (used by the pre-commit hook + Makefile).",
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
    check_fragments = args.check_fragments or args.check_all
    return _run(
        check_links,
        check_adr,
        check_fragments,
        args.paths,
        args.repo_root,
        allow_forward=not args.no_allow_forward_adr,
    )


if __name__ == "__main__":
    sys.exit(main())
