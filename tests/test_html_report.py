from scripts.html_report import (
    html_text,
    render_badge,
    render_document,
    render_status_card,
    render_table,
)


def test_html_text_escapes_element_and_attribute_characters() -> None:
    assert html_text("<tag attr='x'>&\"") == "&lt;tag attr=&#x27;x&#x27;&gt;&amp;&quot;"


def test_badge_escapes_label_and_falls_back_to_neutral_tone() -> None:
    html = render_badge("<script>alert('x')</script>", tone="unexpected")

    assert 'class="badge neutral"' in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "<script>" not in html


def test_status_card_escapes_fields_and_preserves_known_tone() -> None:
    html = render_status_card("A&B", "<5", detail="'quoted'", tone="danger")

    assert 'class="status-card danger"' in html
    assert "A&amp;B" in html
    assert "&lt;5" in html
    assert "&#x27;quoted&#x27;" in html


def test_status_card_omits_empty_detail_element() -> None:
    html = render_status_card("Total", "0", detail="")

    assert "<small>" not in html
    assert "</small>" not in html
    assert "<strong>0</strong></article>" in html


def test_table_escapes_headers_rows_and_empty_message() -> None:
    empty = render_table(["A&B", "C"], [], empty_message="<none>")
    rows = render_table(["A"], [["<cell>"]])

    assert 'colspan="2"' in empty
    assert "A&amp;B" in empty
    assert "&lt;none&gt;" in empty
    assert "&lt;cell&gt;" in rows
    assert "<cell>" not in rows


def test_document_escapes_shell_fields_and_embeds_prebuilt_body() -> None:
    body = '<section class="panel"><p>prebuilt body</p></section>'
    html = render_document(title="<Title>", subtitle="A&B", body=body, footer="'footer'")

    assert "<title>&lt;Title&gt;</title>" in html
    assert "<h1>&lt;Title&gt;</h1>" in html
    assert "A&amp;B" in html
    assert body in html
    assert "&#x27;footer&#x27;" in html
