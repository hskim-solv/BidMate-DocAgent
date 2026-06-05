"""Contract/regression tests for scripts/check_doc_links.py (issue #2004).

The 645-line docs cross-reference / fragment-anchor / ADR-ref governance gate
(Makefile ``check-doc-links``) shipped with ZERO tests despite its anchor
validation being fixed three times — #1104 (gate + 101-link cleanup), #1174
(#fragment anchors + i18n repair), f66a170c (Jekyll directory permalinks).

These lock the pure-parser contracts so a future regression fails loudly:
github-slugger mirroring (Korean / accented slugs — this repo's docs are
largely Korean), fragment parsing, Jekyll ``permalink: pretty`` handling, and
ADR forward-reference tolerance. Behavior is UNCHANGED — each expected value
was confirmed against the live function (which matches github-slugger).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_doc_links import (  # noqa: E402
    collect_anchors,
    extract_links,
    find_broken_adr_refs,
    find_broken_fragments,
    find_broken_links,
    normalize_target,
    slugify_heading,
    split_fragment,
    strip_code_spans,
)


# ---------------------------------------------------------------------------
# slugify_heading — the github-slugger mirror (the part most exposed to i18n
# regression: a whitelist re would silently strip Korean/accented headings).
# ---------------------------------------------------------------------------


def test_slug_basic_lowercase_hyphenated():
    assert slugify_heading("## Hello World") == "hello-world"


def test_slug_strips_marker_and_trailing_hashes():
    assert slugify_heading("### Title ###") == "title"
    # Already-extracted heading text (no leading ``#``) is accepted too.
    assert slugify_heading("Title") == "title"


def test_slug_korean_preserved():
    # GitHub keeps unicode word chars; Korean headings must round-trip.
    assert slugify_heading("## 한국어 제목") == "한국어-제목"


def test_slug_accented_preserved():
    assert slugify_heading("## Café déjà vu") == "café-déjà-vu"


def test_slug_punctuation_dropped():
    assert slugify_heading("## Foo: Bar! (baz)") == "foo-bar-baz"


def test_slug_hyphen_and_underscore_kept():
    # Deliberately absent from the strip set — GitHub keeps them.
    assert slugify_heading("## a_b-c") == "a_b-c"


def test_slug_each_whitespace_becomes_a_hyphen():
    # Two spaces → two hyphens (matches github-slugger's per-char replace).
    assert slugify_heading("## a  b") == "a--b"


def test_slug_inline_link_reduced_to_visible_text():
    assert slugify_heading("## see [foo](x.md) here") == "see-foo-here"


# ---------------------------------------------------------------------------
# collect_anchors — heading slugs (+ GitHub -1/-2 duplicate suffixing) plus
# explicit HTML / kramdown anchors; code/YAML/comment regions skipped.
# ---------------------------------------------------------------------------


def test_anchors_duplicate_headings_get_numeric_suffix():
    assert collect_anchors("## Foo\n\n## Foo\n\n## Foo") == {"foo", "foo-1", "foo-2"}


def test_anchors_html_id_and_name():
    assert collect_anchors('<a id="custom"></a>\n## Title') == {"custom", "title"}
    assert "n1" in collect_anchors('<a name="N1"></a>\n# H')


def test_anchors_kramdown_explicit_id():
    assert "myid" in collect_anchors("## Heading {#myid}")


def test_anchors_skip_fenced_code_headings():
    # A "## heading" inside a code fence produces no GitHub anchor.
    text = "## Real\n\n```\n## Fake In Code\n```\n"
    anchors = collect_anchors(text)
    assert "real" in anchors
    assert "fake-in-code" not in anchors


def test_anchors_skip_yaml_front_matter():
    text = "---\ntitle: Not A Heading\n---\n\n## Real\n"
    assert collect_anchors(text) == {"real"}


def test_anchors_skip_html_comment_block():
    text = "<!--\n## Commented Out\n-->\n## Real\n"
    anchors = collect_anchors(text)
    assert "real" in anchors
    assert "commented-out" not in anchors


# ---------------------------------------------------------------------------
# split_fragment — parse an href into (path, fragment) when checkable, else None
# ---------------------------------------------------------------------------


def test_fragment_same_file():
    assert split_fragment("#frag") == ("", "frag")


def test_fragment_markdown_target():
    assert split_fragment("foo.md#bar") == ("foo.md", "bar")


def test_fragment_non_markdown_extension_is_none():
    # foo.py#L10 has no enumerable anchor set → not checkable here.
    assert split_fragment("foo.py#L10") is None


def test_fragment_external_is_none():
    assert split_fragment("https://example.com#x") is None
    assert split_fragment("/site-absolute#x") is None


def test_fragment_empty_after_hash_is_none():
    assert split_fragment("foo.md#") is None


def test_fragment_jekyll_permalink_kept():
    # Extensionless / trailing-slash target is kept for deferred resolution.
    assert split_fragment("../guide/#frag") == ("../guide/", "frag")


def test_fragment_strips_path_line_suffix():
    assert split_fragment("foo.md:10#bar") == ("foo.md", "bar")


def test_fragment_angle_brackets_and_title_stripped():
    assert split_fragment("<foo.md#bar>") == ("foo.md", "bar")
    assert split_fragment('foo.md#bar "Title"') == ("foo.md", "bar")


# ---------------------------------------------------------------------------
# normalize_target — href → filesystem-checkable path, or None to skip
# ---------------------------------------------------------------------------


def test_normalize_plain_markdown():
    assert normalize_target("foo.md") == "foo.md"


def test_normalize_strips_fragment():
    assert normalize_target("foo.md#frag") == "foo.md"


def test_normalize_same_file_anchor_is_none():
    assert normalize_target("#frag") is None


def test_normalize_external_is_none():
    assert normalize_target("https://example.com") is None
    assert normalize_target("//proto-relative") is None


def test_normalize_directory_permalink_is_none():
    # No known extension on the final segment → Jekyll permalink, skipped.
    assert normalize_target("../guide/") is None


def test_normalize_html_is_none():
    # .html is rendered-output, not a source file.
    assert normalize_target("architecture.html") is None


def test_normalize_angle_brackets_and_title_stripped():
    assert normalize_target("<foo.md>") == "foo.md"
    assert normalize_target('foo.md "Title"') == "foo.md"


def test_normalize_strips_line_suffix():
    assert normalize_target("foo.py:10") == "foo.py"
    assert normalize_target("foo.py:10-20") == "foo.py"


# ---------------------------------------------------------------------------
# strip_code_spans / extract_links — keep example links out of the link set
# ---------------------------------------------------------------------------


def test_strip_fenced_code_block():
    text = "before\n```\n[x](evil.md)\n```\nafter"
    out = strip_code_spans(text)
    assert "evil.md" not in out
    assert "before" in out and "after" in out


def test_strip_tilde_fence():
    text = "a\n~~~\n[y](y.md)\n~~~\nb"
    assert "y.md" not in strip_code_spans(text)


def test_strip_inline_code():
    assert "x.md" not in strip_code_spans("see `[x](x.md)` here")


def test_extract_basic_and_image_links():
    assert extract_links("[foo](bar.md)") == ["bar.md"]
    # ![alt](src) — the (src) portion is matched, so broken images are caught.
    assert extract_links("![alt](img.png)") == ["img.png"]


# ---------------------------------------------------------------------------
# find_broken_links / find_broken_fragments — filesystem-resolved (tmp_path)
# ---------------------------------------------------------------------------


def test_broken_link_missing_target_reported(tmp_path):
    (tmp_path / "doc.md").write_text("[x](missing.md)", encoding="utf-8")
    broken = find_broken_links(["doc.md"], repo_root=tmp_path)
    assert len(broken) == 1 and broken[0][0] == "doc.md"


def test_broken_link_existing_target_ok(tmp_path):
    (tmp_path / "doc.md").write_text("[x](other.md)", encoding="utf-8")
    (tmp_path / "other.md").write_text("# Other", encoding="utf-8")
    assert find_broken_links(["doc.md"], repo_root=tmp_path) == []


def test_broken_fragment_bad_anchor_reported(tmp_path):
    (tmp_path / "doc.md").write_text("[x](target.md#nope)", encoding="utf-8")
    (tmp_path / "target.md").write_text("# Real Heading", encoding="utf-8")
    broken = find_broken_fragments(["doc.md"], repo_root=tmp_path)
    assert len(broken) == 1 and broken[0][2] == "nope"


def test_good_fragment_anchor_ok(tmp_path):
    (tmp_path / "doc.md").write_text("[x](target.md#real-heading)", encoding="utf-8")
    (tmp_path / "target.md").write_text("# Real Heading", encoding="utf-8")
    assert find_broken_fragments(["doc.md"], repo_root=tmp_path) == []


def test_same_file_fragment_resolves_against_self(tmp_path):
    (tmp_path / "doc.md").write_text("# Top\n\n[jump](#top)", encoding="utf-8")
    assert find_broken_fragments(["doc.md"], repo_root=tmp_path) == []


def test_missing_fragment_target_file_not_double_reported(tmp_path):
    # A missing TARGET file is find_broken_links' job; find_broken_fragments
    # stays silent so one broken link is not reported twice.
    (tmp_path / "doc.md").write_text("[x](gone.md#frag)", encoding="utf-8")
    assert find_broken_fragments(["doc.md"], repo_root=tmp_path) == []


# ---------------------------------------------------------------------------
# find_broken_adr_refs — ADR prose refs vs docs/adr/NNNN-*.md, forward-tolerant
# ---------------------------------------------------------------------------


def _make_adr_dir(tmp_path, numbers):
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    for n in numbers:
        (adr / f"{n:04d}-example.md").write_text("# ADR", encoding="utf-8")
    return adr


def test_adr_ref_existing_is_ok(tmp_path):
    adr = _make_adr_dir(tmp_path, [1, 7])
    (tmp_path / "doc.md").write_text("See ADR 0007 for details.", encoding="utf-8")
    assert find_broken_adr_refs(["doc.md"], repo_root=tmp_path, adr_dir=adr) == []


def test_adr_ref_dead_below_max_is_broken(tmp_path):
    adr = _make_adr_dir(tmp_path, [1, 7])
    (tmp_path / "doc.md").write_text("See ADR 0005 (never created).", encoding="utf-8")
    assert find_broken_adr_refs(["doc.md"], repo_root=tmp_path, adr_dir=adr) == [
        ("doc.md", "0005")
    ]


def test_adr_ref_forward_skipped_by_default(tmp_path):
    adr = _make_adr_dir(tmp_path, [1, 7])
    (tmp_path / "doc.md").write_text("Planned ADR 0099.", encoding="utf-8")
    # 99 > max(7) → planned forward-ref, tolerated.
    assert find_broken_adr_refs(["doc.md"], repo_root=tmp_path, adr_dir=adr) == []


def test_adr_ref_forward_flagged_when_disallowed(tmp_path):
    adr = _make_adr_dir(tmp_path, [1, 7])
    (tmp_path / "doc.md").write_text("Planned ADR 0099.", encoding="utf-8")
    assert find_broken_adr_refs(
        ["doc.md"], repo_root=tmp_path, adr_dir=adr, allow_forward=False
    ) == [("doc.md", "0099")]


def test_adr_ref_in_code_span_ignored(tmp_path):
    adr = _make_adr_dir(tmp_path, [1, 7])
    (tmp_path / "doc.md").write_text("`ADR 0005` is an example.", encoding="utf-8")
    # Code-span stripped before scanning → not a live ref.
    assert find_broken_adr_refs(["doc.md"], repo_root=tmp_path, adr_dir=adr) == []


def test_adr_ref_deduplicated_per_source(tmp_path):
    adr = _make_adr_dir(tmp_path, [1, 7])
    (tmp_path / "doc.md").write_text("ADR 0005 and again ADR 0005.", encoding="utf-8")
    assert find_broken_adr_refs(["doc.md"], repo_root=tmp_path, adr_dir=adr) == [
        ("doc.md", "0005")
    ]
