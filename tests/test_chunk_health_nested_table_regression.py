"""Regression: nested-table-loss tracking in ``chunk_health`` (issue #902).

Pins the three additive fields kordoc (ADR 0049) leaves visible when a nested
HWP table cannot be reconstructed in markdown. Without this metric, a future
loader regression that flattens *more* tables would only show up as a vague
chunk-length shift in ``ingestion_report.json`` — this test pins the marker
shape and report contract so triage points directly at the offending docs.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers.chunk_health import (  # noqa: E402
    _NESTED_TABLE_RE,
    _NESTED_TABLE_SAMPLE_LIMIT,
    compute_chunk_health,
)


def _hwp_chunk(text: str, doc_id: str = "doc-1", section: str = "본문") -> dict:
    return {
        "text": text,
        "doc_id": doc_id,
        "metadata": {"file_format": "hwp"},
        "section": section,
    }


class TestNestedTableMarkerRegex(unittest.TestCase):
    def test_matches_kordoc_marker_format(self):
        # The exact shape kordoc emits in markdown: ``[중첩 테이블 #N]``.
        # Real samples observed in data/files_kordoc/인천광역시_*.md and
        # data/files_kordoc/서울특별시교육청_*.md.
        sample = "사업개요\n[중첩 테이블 #1]\n일자리업무시스템"
        matches = _NESTED_TABLE_RE.findall(sample)
        self.assertEqual(matches, ["1"])

    def test_does_not_match_plain_text(self):
        # Bracketed numbers that look similar but aren't the marker shape
        # must not be matched — false positives would inflate the metric.
        self.assertEqual(_NESTED_TABLE_RE.findall("[표 #1]"), [])
        self.assertEqual(_NESTED_TABLE_RE.findall("[중첩 표 #1]"), [])
        self.assertEqual(_NESTED_TABLE_RE.findall("중첩 테이블 #1"), [])

    def test_captures_multi_digit_ids(self):
        sample = "[중첩 테이블 #45]"
        self.assertEqual(_NESTED_TABLE_RE.findall(sample), ["45"])


class TestComputeChunkHealthNestedTable(unittest.TestCase):
    def test_zero_when_no_markers_present(self):
        chunks = [
            _hwp_chunk("이 사업은 RFP 입찰 대상입니다."),
            _hwp_chunk("예산은 5억 원입니다."),
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["nested_table_loss_count"], 0)
        self.assertEqual(result["nested_table_loss_files"], 0)
        self.assertEqual(result["nested_table_loss_samples"], [])

    def test_counts_markers_across_files(self):
        chunks = [
            _hwp_chunk("[중첩 테이블 #1]\n조직도", doc_id="doc-a"),
            _hwp_chunk("[중첩 테이블 #2]\n단계별 워크플로", doc_id="doc-a"),
            _hwp_chunk("normal narrative", doc_id="doc-b"),
            _hwp_chunk("[중첩 테이블 #1]\n사업범위", doc_id="doc-c"),
        ]
        result = compute_chunk_health(chunks)
        # 3 markers total across 2 distinct docs (doc-a contributes 2, doc-c 1)
        self.assertEqual(result["nested_table_loss_count"], 3)
        self.assertEqual(result["nested_table_loss_files"], 2)

    def test_sample_payload_shape(self):
        chunks = [
            _hwp_chunk(
                "[중첩 테이블 #5]\n일자리업무시스템 (이용자) 시,군,구 담당",
                doc_id="인천광역시_일자리플랫폼",
            ),
        ]
        result = compute_chunk_health(chunks)
        samples = result["nested_table_loss_samples"]
        self.assertEqual(len(samples), 1)
        sample = samples[0]
        self.assertEqual(set(sample.keys()), {"doc_id", "marker_id", "adjacent_text"})
        self.assertEqual(sample["doc_id"], "인천광역시_일자리플랫폼")
        self.assertEqual(sample["marker_id"], "5")
        # Adjacent text is the slice immediately AFTER the closing bracket,
        # capped at 80 chars. Confirms triage payload points at what the
        # nested table was flattened into.
        self.assertTrue(sample["adjacent_text"].startswith("\n일자리업무시스템"))
        self.assertLessEqual(len(sample["adjacent_text"]), 80)

    def test_sample_limit_caps_payload_size(self):
        # ``_NESTED_TABLE_SAMPLE_LIMIT`` markers + 5 extra. The extras must
        # be counted (count = 25) but not appear in the samples list (capped
        # at 20). Keeps the JSON sidecar bounded on pathological corpora.
        marker_count = _NESTED_TABLE_SAMPLE_LIMIT + 5
        chunks = [
            _hwp_chunk(f"[중첩 테이블 #{i}]\nfollow {i}", doc_id=f"doc-{i}")
            for i in range(marker_count)
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["nested_table_loss_count"], marker_count)
        self.assertEqual(len(result["nested_table_loss_samples"]), _NESTED_TABLE_SAMPLE_LIMIT)
        # First N preserved deterministically (insertion order) — important
        # so re-running the same index produces the same report.
        first_ids = [s["marker_id"] for s in result["nested_table_loss_samples"]]
        self.assertEqual(first_ids, [str(i) for i in range(_NESTED_TABLE_SAMPLE_LIMIT)])

    def test_multiple_markers_in_one_chunk_all_counted(self):
        # Chunk-boundary heuristics sometimes pack 2-3 markers into one chunk
        # (e.g. consecutive nested tables in an organigram section). All
        # occurrences inside a chunk must be counted, not just the first.
        chunk = _hwp_chunk(
            "[중첩 테이블 #1]\nA\n[중첩 테이블 #2]\nB\n[중첩 테이블 #3]\nC",
            doc_id="doc-multi",
        )
        result = compute_chunk_health([chunk])
        self.assertEqual(result["nested_table_loss_count"], 3)
        self.assertEqual(result["nested_table_loss_files"], 1)
        marker_ids = [s["marker_id"] for s in result["nested_table_loss_samples"]]
        self.assertEqual(marker_ids, ["1", "2", "3"])

    def test_missing_doc_id_does_not_inflate_files(self):
        # If a synthetic / test chunk omits ``doc_id``, the marker still
        # counts toward the total but the file count must not be inflated
        # by an empty key.
        chunks = [
            {
                "text": "[중첩 테이블 #1]\nno doc id",
                "metadata": {"file_format": "hwp"},
                "section": "본문",
            },
            _hwp_chunk("[중첩 테이블 #2]\nwith doc id", doc_id="doc-x"),
        ]
        result = compute_chunk_health(chunks)
        self.assertEqual(result["nested_table_loss_count"], 2)
        # Only ``doc-x`` is a real doc_id; the empty-string chunk is excluded.
        self.assertEqual(result["nested_table_loss_files"], 1)


if __name__ == "__main__":
    unittest.main()
