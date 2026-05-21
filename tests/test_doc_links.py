"""Regression tests for the markdown dead-link gate (issue #1060).

`scripts/check_doc_links.py` is the SSoT for cross-reference integrity.
The recurring failure (commits 627a63b / 9754f69 / da80073: "repair
cross-references after batch reorg") is a file MOVE that breaks an inbound
link from a file the commit never touched. ``test_repo_has_no_broken_doc_links_today``
is the canonical CI gate — it runs inside the full pytest suite (pr-eval.yml
full checkout), so a regression reds here before merge. The pre-commit hook
and ``make check-doc-links`` are the shift-left conveniences.

These tests pin the pure helpers (extraction, normalization, resolution,
forward-ADR tolerance) so a refactor cannot silently weaken the gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import check_doc_links as cdl  # noqa: E402

CLI = ROOT_DIR / "scripts" / "check_doc_links.py"


# ---- normalize_target: what is skipped vs checked --------------------------


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/x",
        "http://example.com",
        "mailto:a@b.com",
        "tel:+123",
        "//cdn.example.com/x.js",  # protocol-relative
        "#a-same-file-anchor",
        "/adr/0001-foo/",          # site-absolute (Jekyll site root)
        "../adr/0001-foo/",        # directory-style permalink (trailing slash)
        "../adr/0001-foo",         # permalink (no recognized extension)
    ],
)
def test_normalize_target_skips_non_filesystem(href: str) -> None:
    assert cdl.normalize_target(href) is None


@pytest.mark.parametrize(
    "href,expected",
    [
        ("../foo.md", "../foo.md"),
        ("./img.png", "./img.png"),
        ("../foo.md#section", "../foo.md"),          # fragment dropped
        ("../../rag_core.py:120", "../../rag_core.py"),   # line number
        ("../../rag_core.py:120-130", "../../rag_core.py"),
        ('../foo.md "Title text"', "../foo.md"),     # link title
        ("<../foo.md>", "../foo.md"),                # angle brackets
    ],
)
def test_normalize_target_strips_and_keeps(href: str, expected: str) -> None:
    assert cdl.normalize_target(href) == expected


# ---- strip_code_spans + extract_links --------------------------------------


def test_strip_code_spans_removes_fenced_and_inline() -> None:
    text = (
        "real [keep](keep.md)\n"
        "```python\n"
        "fenced [drop](drop.md)\n"
        "```\n"
        "~~~\n"
        "tilde [drop2](drop2.md)\n"
        "~~~\n"
        "inline `code [drop3](drop3.md)` tail\n"
    )
    stripped = cdl.strip_code_spans(text)
    links = cdl.extract_links(stripped)
    assert "keep.md" in links
    assert "drop.md" not in links
    assert "drop2.md" not in links
    assert "drop3.md" not in links


def test_extract_links_handles_images_ignores_reference_style() -> None:
    text = "![alt](pic.png) and [t](a.md) and [refstyle][1]\n\n[1]: http://x\n"
    links = cdl.extract_links(text)
    assert "pic.png" in links     # image src is checked too
    assert "a.md" in links
    # reference-style `[t][1]` has no inline `(...)`, so it is not extracted
    assert all("refstyle" not in lk for lk in links)


# ---- find_broken_links (tmp tree) ------------------------------------------


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_find_broken_links_flags_missing_passes_existing(tmp_path: Path) -> None:
    _write(tmp_path / "target.md", "# target\n")
    _write(
        tmp_path / "docs" / "src.md",
        "[ok](../target.md) and [bad](../nope.md)\n",
    )
    broken = cdl.find_broken_links(["docs/src.md"], tmp_path)
    assert len(broken) == 1
    src, href, resolved = broken[0]
    assert src == "docs/src.md"
    assert href == "../nope.md"
    assert resolved == "nope.md"


def test_find_broken_links_resolves_relative_to_source_dir(tmp_path: Path) -> None:
    # A file two levels deep linking repo-root code needs ../../ — the exact
    # off-by-one that issue #1060's recurrence is about.
    _write(tmp_path / "rag_core.py", "x = 1\n")
    _write(tmp_path / "docs" / "sub" / "a.md", "[wrong](../rag_core.py)\n")
    _write(tmp_path / "docs" / "sub" / "b.md", "[right](../../rag_core.py)\n")
    broken = cdl.find_broken_links(["docs/sub/a.md", "docs/sub/b.md"], tmp_path)
    assert [(s, h) for s, h, _ in broken] == [("docs/sub/a.md", "../rag_core.py")]


# ---- find_broken_adr_refs (forward-reference tolerance) --------------------


def _adr_tree(tmp_path: Path, numbers: list[int]) -> None:
    for n in numbers:
        _write(tmp_path / "docs" / "adr" / f"{n:04d}-slug.md", f"# ADR {n:04d}\n")


def test_adr_refs_existing_ok_missing_below_max_flagged(tmp_path: Path) -> None:
    _adr_tree(tmp_path, [1, 3])  # max = 3, gap at 2
    _write(
        tmp_path / "docs" / "note.md",
        "see ADR 0001 (ok) and ADR 0002 (gap) here\n",
    )
    dead = cdl.find_broken_adr_refs(["docs/note.md"], tmp_path)
    assert dead == [("docs/note.md", "0002")]


def test_adr_refs_forward_reference_tolerated_by_default(tmp_path: Path) -> None:
    _adr_tree(tmp_path, [1, 3])  # max = 3
    _write(tmp_path / "docs" / "note.md", "planned ADR 0060 pointer\n")
    assert cdl.find_broken_adr_refs(["docs/note.md"], tmp_path) == []
    # ...but flagged when forward tolerance is off.
    strict = cdl.find_broken_adr_refs(
        ["docs/note.md"], tmp_path, allow_forward=False
    )
    assert strict == [("docs/note.md", "0060")]


# ---- fragment anchors: slugify_heading (GitHub github-slugger rules) --------


@pytest.mark.parametrize(
    "heading,slug",
    [
        # The incident: a Korean-ized heading produces a Korean slug, so the
        # old English #anchor no longer resolves (issue #1152).
        ("## 데모 비디오 녹화", "데모-비디오-녹화"),
        # em-dash (U+2014) is dropped; the spaces around it survive → "--".
        (
            "## 핵심 기술 기여 — comparison-aware balanced top-k",
            "핵심-기술-기여--comparison-aware-balanced-top-k",
        ),
        # "&" dropped, surrounding spaces survive → double hyphen.
        ("Milestones & 이슈 lifecycle", "milestones--이슈-lifecycle"),
        # parentheses + the period in "4.12" are dropped.
        ("### C5 인용 불일치(약한 근거) 빈도 4.12", "c5-인용-불일치약한-근거-빈도-412"),
        # backticks dropped; underscore is KEPT (not in the strip set).
        ("## Hard caps (`react_loop` 강제)", "hard-caps-react_loop-강제"),
        # a trailing run of `#` (closed ATX heading) is stripped.
        ("## Title ##", "title"),
        # already-extracted text (no leading `#`) is accepted too.
        ("already text only", "already-text-only"),
    ],
)
def test_slugify_heading_matches_github(heading: str, slug: str) -> None:
    assert cdl.slugify_heading(heading) == slug


# ---- fragment anchors: collect_anchors -------------------------------------


def test_collect_anchors_dedup_explicit_and_skips() -> None:
    text = (
        "---\n"
        "title: front matter\n"
        "## Heading in front matter is ignored\n"
        "---\n"
        "# Top\n"
        '<a id="Stable-Anchor"></a>\n'
        "## Result\n"
        "## Result\n"  # duplicate → result, result-1 (GitHub -N suffixing)
        '<a name="named"></a>\n'
        "Custom heading {#custom-id}\n"
        "```\n"
        "## fenced heading ignored\n"
        "```\n"
        "<!--\n"
        "## commented heading ignored\n"
        "-->\n"
    )
    anchors = cdl.collect_anchors(text)
    assert "top" in anchors
    assert "result" in anchors and "result-1" in anchors  # duplicate suffix
    assert "stable-anchor" in anchors  # <a id> harvested + lowercased
    assert "named" in anchors  # <a name> harvested
    assert "custom-id" in anchors  # kramdown {#id} harvested
    # Headings in front matter / fenced code / HTML comments emit no anchor.
    assert "heading-in-front-matter-is-ignored" not in anchors
    assert "fenced-heading-ignored" not in anchors
    assert "commented-heading-ignored" not in anchors


# ---- fragment anchors: split_fragment --------------------------------------


@pytest.mark.parametrize(
    "href",
    [
        "../foo.md",  # no fragment at all
        "https://x.com#frag",  # external
        "/site/abs.md#frag",  # site-absolute
        "../code.py#L10",  # non-markdown target (anchors not enumerable)
        "../dir/#frag",  # directory-style permalink
        "../foo.md#",  # empty fragment
    ],
)
def test_split_fragment_skips(href: str) -> None:
    assert cdl.split_fragment(href) is None


@pytest.mark.parametrize(
    "href,expected",
    [
        ("#same-file", ("", "same-file")),
        ("../foo.md#section", ("../foo.md", "section")),
        ("../foo.md:120#section", ("../foo.md", "section")),  # path:line dropped
        ("<../foo.md#section>", ("../foo.md", "section")),  # angle brackets
        ('../foo.md#section "Title"', ("../foo.md", "section")),  # link title
    ],
)
def test_split_fragment_parses(href: str, expected: tuple[str, str]) -> None:
    assert cdl.split_fragment(href) == expected


# ---- fragment anchors: find_broken_fragments (tmp tree) --------------------


def test_find_broken_fragments_incident_korean_heading(tmp_path: Path) -> None:
    # Exactly the #1152 regression: heading translated, inbound link still
    # points at the dropped English slug.
    _write(tmp_path / "target.md", "# 데모 비디오 녹화\n")
    _write(
        tmp_path / "docs" / "src.md",
        "[walkthrough](../target.md#recording-the-demo-video)\n",
    )
    broken = cdl.find_broken_fragments(["docs/src.md", "target.md"], tmp_path)
    assert broken == [
        (
            "docs/src.md",
            "../target.md#recording-the-demo-video",
            "recording-the-demo-video",
        )
    ]


def test_find_broken_fragments_stable_anchor_fixes_it(tmp_path: Path) -> None:
    # The recommended fix: a stable <a id> before the heading keeps the old
    # English anchor alive alongside the Korean title.
    _write(
        tmp_path / "target.md",
        '<a id="recording-the-demo-video"></a>\n\n# 데모 비디오 녹화\n',
    )
    _write(
        tmp_path / "docs" / "src.md",
        "[walkthrough](../target.md#recording-the-demo-video)\n",
    )
    assert cdl.find_broken_fragments(["docs/src.md", "target.md"], tmp_path) == []


def test_find_broken_fragments_same_file(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "[up](#stable) and [bad](#missing)\n\n## Stable\n")
    broken = cdl.find_broken_fragments(["doc.md"], tmp_path)
    assert broken == [("doc.md", "#missing", "missing")]


def test_find_broken_fragments_valid_anchor_and_no_false_positives(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "target.md", "# 아키텍처 요약\n")
    _write(tmp_path / "code.py", "x = 1\n")
    _write(
        tmp_path / "docs" / "src.md",
        "[ok](../target.md#아키텍처-요약)\n"  # valid Korean anchor
        "[ext](https://x.com#frag)\n"  # external — skipped
        "[code](../code.py#L1)\n"  # non-md target — skipped
        "[gone](../nope.md#frag)\n"  # missing FILE — find_broken_links' job
        "[dir](../somedir/#frag)\n",  # directory permalink — skipped
    )
    assert cdl.find_broken_fragments(["docs/src.md"], tmp_path) == []


# ---- CLI wrapper -----------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_passes_on_clean_tree(tmp_path: Path) -> None:
    _write(tmp_path / "target.md", "# t\n")
    _write(tmp_path / "docs" / "src.md", "[ok](../target.md)\n")
    result = _run_cli(
        "--check-links", "--repo-root", str(tmp_path), "--paths", "docs/src.md"
    )
    assert result.returncode == 0, result.stderr
    assert "no broken" in result.stdout


def test_cli_fails_with_actionable_message(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "src.md", "[bad](../missing.md)\n")
    result = _run_cli(
        "--check-links", "--repo-root", str(tmp_path), "--paths", "docs/src.md"
    )
    assert result.returncode == 1
    # Losing the issue ref or the actionable `../` hint is a docs regression.
    assert "issue #1060" in result.stderr
    assert "missing.md" in result.stderr


def test_cli_check_fragments_reds_on_broken_anchor(tmp_path: Path) -> None:
    _write(tmp_path / "target.md", "# 데모 비디오 녹화\n")
    _write(
        tmp_path / "docs" / "src.md",
        "[x](../target.md#recording-the-demo-video)\n",
    )
    result = _run_cli(
        "--check-fragments", "--repo-root", str(tmp_path),
        "--paths", "docs/src.md", "target.md",
    )
    assert result.returncode == 1
    # Losing the issue ref or the offending fragment is a regression.
    assert "issue #1152" in result.stderr
    assert "recording-the-demo-video" in result.stderr


def test_cli_check_all_includes_fragment_check(tmp_path: Path) -> None:
    # --check-all must run fragments too, else the pre-commit hook + Makefile
    # silently stop catching #1152-style breakage.
    _write(tmp_path / "target.md", "# 한국어 제목\n")
    _write(tmp_path / "docs" / "src.md", "[x](../target.md#english-anchor)\n")
    result = _run_cli(
        "--check-all", "--repo-root", str(tmp_path),
        "--paths", "docs/src.md", "target.md",
    )
    assert result.returncode == 1
    assert "fragment" in result.stderr.lower()


# ---- real-repo sentinels (the canonical CI gate) ---------------------------


def test_repo_has_no_broken_doc_links_today() -> None:
    files = cdl.tracked_markdown_files(ROOT_DIR)
    broken = cdl.find_broken_links(files, ROOT_DIR)
    assert broken == [], "Broken doc links on this tree:\n  - " + "\n  - ".join(
        f"{src}: [{href}] -> {resolved}" for src, href, resolved in broken
    )


def test_repo_has_no_dead_adr_refs_today() -> None:
    files = cdl.tracked_markdown_files(ROOT_DIR)
    dead = cdl.find_broken_adr_refs(files, ROOT_DIR)
    assert dead == [], "Dead prose ADR references on this tree:\n  - " + "\n  - ".join(
        f"{src}: ADR {num}" for src, num in dead
    )


def test_repo_has_no_broken_fragments_today() -> None:
    """The sentinel that would have caught #1112's Korean-ization regression:
    every inbound `#anchor` must resolve to a heading slug / explicit anchor in
    its target `.md`. Near-zero-false-positive by construction — only `.md`
    targets that exist are checked; missing files are find_broken_links' job.
    """
    files = cdl.tracked_markdown_files(ROOT_DIR)
    broken = cdl.find_broken_fragments(files, ROOT_DIR)
    assert broken == [], "Broken #fragment anchors on this tree:\n  - " + "\n  - ".join(
        f"{src}: [{href}] -> #{frag}" for src, href, frag in broken
    )


# ---- argparse mutex sanity -------------------------------------------------


def test_cli_modes_are_mutually_exclusive() -> None:
    """--check-links / --check-adr-refs / --check-all share one mutex group so
    the hook + CI + Makefile cannot diverge on which mode 'wins'.
    """
    result = _run_cli("--check-links", "--check-adr-refs")
    assert result.returncode != 0
    assert "not allowed with" in result.stderr or "argument" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
