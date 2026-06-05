from __future__ import annotations

import pytest

from scripts import private_data_quality_audit_utils as utils


def test_hash_ref_is_deterministic_namespaced_redaction():
    first = utils.hash_ref("doc-7", namespace="doc")
    assert first == utils.hash_ref("doc-7", namespace="doc")
    assert first.startswith("redacted_")
    assert first != utils.hash_ref("doc-7", namespace="question")
    assert "doc-7" not in first


def test_token_overlap_helpers_use_ascii_and_korean_terms():
    left = "AI 사업 요구사항 2026"
    right = "사업 요구사항 검토 2026"
    assert utils.tokens(left) == {"ai", "사업", "요구사항", "2026"}
    assert utils.jaccard(left, right) == pytest.approx(3 / 5)
    assert utils.containment("사업 2026 누락", right) == pytest.approx(2 / 3)


def test_percentile_interpolates_and_handles_empty_input():
    assert utils.percentile([], 0.5) is None
    assert utils.percentile([10], 0.9) == 10.0
    assert utils.percentile([10, 20, 30, 40], 0.25) == pytest.approx(17.5)
    assert utils.percentile([10, 20, 30, 40], 0.5) == pytest.approx(25.0)


def test_page_metadata_present_uses_metadata_and_region_fields():
    assert utils.page_metadata_present({"page": "", "metadata": {"page_span": [2, 3]}})
    assert utils.page_metadata_present({"regions": [{"page_number": ""}, {"page_number": 4}]})
    assert not utils.page_metadata_present({"page": "", "metadata": {"pages": []}, "regions": []})


def test_public_safety_flags_forbidden_keys_and_absolute_paths():
    hits = utils.forbidden_output_hits(
        {"safe": [{"doc_id": "PRIVATE-DOC"}], "note": "/Users/hskim/private/file.hwp"}
    )
    assert hits == {"absolute_path_value": 1, "doc_id": 1}
    with pytest.raises(utils.AuditPrivacyError, match="doc_idx1"):
        utils.assert_public_safe({"doc_id": "PRIVATE-DOC"})
