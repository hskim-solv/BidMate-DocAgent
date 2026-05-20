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
