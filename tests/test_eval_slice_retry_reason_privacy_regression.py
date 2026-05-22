"""Regression guard for nested retry_reason_counts anonymization (issue #1286).

#1211 (closes #1204) stripped the private payload after the first ``:`` from
the **top-level** ``retry_reason_counts`` (``missing_comparison_entity:<agency>``
/ ``missing_comparison_doc:<공고번호>``), but the per-slice copies inside
``by_format`` / ``by_hardcase_category`` / ``by_metadata_field`` /
``by_query_type`` were left unanonymized. Two compounding bugs leaked them:

1. ``by_format`` / ``by_hardcase_category`` / ``by_metadata_field`` were listed
   in ``SAFE_TOPLEVEL_KEYS``, so the main loop raw-passed the whole slice
   (``else: out[key] = value``). The dedicated fail-closed extractors only
   *overwrite* that passthrough when they find ≥1 whitelisted bucket — so a
   slice carrying only private bucket names (``multi_hop`` etc.) kept its raw
   nested ``retry_reason_counts`` with Korean agency names.
2. ``retry_reason_counts`` was absent from ``SAFE_SLICE_METRICS``, so even a
   whitelisted bucket dropped the (useful) retry-reason taxonomy entirely.

The fix removes the three keys from ``SAFE_TOPLEVEL_KEYS`` (so only the
fail-closed extractors emit them) and adds ``retry_reason_counts`` to
``SAFE_SLICE_METRICS`` with the same ``:``-split collapse the top level uses,
via the shared :func:`_collapse_retry_reason_counts` helper.
"""
from __future__ import annotations

import json
import re
import unittest
from typing import Any

from scripts.run_real_eval_delta import (
    SAFE_SLICE_METRICS,
    SAFE_TOPLEVEL_KEYS,
    _collapse_retry_reason_counts,
    extract_aggregate,
)

# A private agency name + a 공고번호-style doc id, used as colon payloads.
_AGENCY = "한국전자통신연구원"
_DOC_ID = "20240419765-0.0"


def _all_strings(obj: Any) -> list[str]:
    """Every dict key and string value reachable in ``obj``."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_all_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_all_strings(item))
    elif isinstance(obj, str):
        out.append(obj)
    return out


class TestCollapseHelper(unittest.TestCase):
    def test_strips_colon_payload_and_sums_collisions(self) -> None:
        collapsed = _collapse_retry_reason_counts(
            {
                "topic_not_grounded": 3,
                f"missing_comparison_entity:{_AGENCY}": 1,
                "missing_comparison_entity:서울시청": 2,
                f"missing_comparison_doc:{_DOC_ID}": 4,
            }
        )
        # Colliding enum prefixes are summed; payload dropped.
        self.assertEqual(
            collapsed,
            {
                "topic_not_grounded": 3,
                "missing_comparison_entity": 3,
                "missing_comparison_doc": 4,
            },
        )


class TestSliceRetryReasonAnonymization(unittest.TestCase):
    def _summary(self, **slices: Any) -> dict[str, Any]:
        base: dict[str, Any] = {"num_predictions": 3, "accuracy": 1.0}
        base.update(slices)
        return base

    def test_top_level_keys_no_longer_route_slices_through_passthrough(self) -> None:
        # The structural fix: these three are handled exclusively by their
        # dedicated fail-closed extractors, never the main-loop passthrough.
        for key in ("by_format", "by_hardcase_category", "by_metadata_field"):
            self.assertNotIn(key, SAFE_TOPLEVEL_KEYS)
        self.assertIn("retry_reason_counts", SAFE_SLICE_METRICS)

    def test_whitelisted_bucket_keeps_anonymized_retry_reasons(self) -> None:
        summary = self._summary(
            by_format={
                "hwp": {
                    "num_predictions": 2,
                    "accuracy": 1.0,
                    "retry_reason_counts": {
                        "topic_not_grounded": 3,
                        f"missing_comparison_entity:{_AGENCY}": 1,
                    },
                }
            }
        )
        out = extract_aggregate(summary)
        rrc = out["by_format"]["hwp"]["retry_reason_counts"]
        # Taxonomy total preserved; identifying payload gone.
        self.assertEqual(rrc, {"topic_not_grounded": 3, "missing_comparison_entity": 1})

    def test_non_whitelisted_bucket_dropped_not_passed_through(self) -> None:
        # The documented #1286 leak: a slice with ONLY private bucket names
        # used to survive the raw passthrough with nested Korean payloads.
        summary = self._summary(
            by_hardcase_category={
                "multi_hop": {
                    "num_predictions": 1,
                    "accuracy": 0.0,
                    "retry_reason_counts": {f"missing_comparison_entity:{_AGENCY}": 1},
                }
            }
        )
        out = extract_aggregate(summary)
        # No whitelisted bucket -> the key is absent entirely (fail-closed).
        self.assertNotIn("by_hardcase_category", out)

    def test_by_query_type_slice_anonymized(self) -> None:
        summary = self._summary(
            by_query_type={
                "comparison": {
                    "num_predictions": 4,
                    "accuracy": 0.75,
                    "retry_reason_counts": {f"missing_comparison_doc:{_DOC_ID}": 2},
                }
            }
        )
        out = extract_aggregate(summary)
        rrc = out["by_query_type"]["comparison"]["retry_reason_counts"]
        self.assertEqual(rrc, {"missing_comparison_doc": 2})

    def test_no_hangul_or_colon_keys_anywhere(self) -> None:
        # End-to-end: feed every slice a colon+Hangul payload and assert the
        # committable aggregate carries neither signature (mirrors the
        # structural gate in test_eval_artifact_privacy_regression.py).
        leaky = {
            "num_predictions": 1,
            "accuracy": 1.0,
            "retry_reason_counts": {f"missing_comparison_entity:{_AGENCY}": 1},
        }
        summary = self._summary(
            by_format={"hwp": dict(leaky), "private_pdf_csv_text": dict(leaky)},
            by_hardcase_category={"table_heavy": dict(leaky), "multi_hop": dict(leaky)},
            by_metadata_field={"agency": dict(leaky), "발주처": dict(leaky)},
            by_query_type={"comparison": dict(leaky)},
        )
        out = extract_aggregate(summary)
        serialized = json.dumps(out, ensure_ascii=False)
        self.assertEqual(re.findall(r"[가-힣]", serialized), [])
        # No dict key may contain a colon.
        for s in _all_strings(out):
            self.assertNotIn(":", s)


if __name__ == "__main__":
    unittest.main()
