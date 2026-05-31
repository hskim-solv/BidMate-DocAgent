"""Regression tests for the staging self-ship free-text data-boundary guard.

ADR 0088 §5 / ADR 0005: PR bodies, commit messages, and external notification
payloads must never carry raw private RFP content. The #1144 incident was a
*free-text* leak (raw per-case values inside an artifact that looked aggregate),
which the JSON-structural scanners in _governance.py do not catch. These tests
pin the new free-text scanner.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import _ship_payload_guard as guard  # noqa: E402


# --- raw content must be blocked (default mode, PR body / commit) -------------

def test_1144_korean_chunk_prose_blocked():
    """#1144 free-text path: raw Korean RFP chunk prose embedded in a PR body."""
    pr_body = (
        "Implemented retrieval fix. Example evidence chunk:\n"
        "본 사업의 계약기간은 착수일로부터 12개월이며 과업 범위는 시스템 구축 및 유지보수를 포함한다."
    )
    assert guard.is_raw_payload(pr_body) is True
    with pytest.raises(guard.RawPayloadViolation):
        guard.assert_no_raw_payload(pr_body)


def test_doc_chunk_id_blocked():
    text = "see doc_id: rfp_2024_0312 chunk_id=7 for the matched passage"
    assert guard.is_raw_payload(text) is True


def test_forbidden_key_fragment_blocked():
    text = '{"question": "사업기간?", "answer": "12개월"} leaked into the body'
    assert guard.is_raw_payload(text) is True


def test_per_case_qa_structure_blocked():
    text = "질문: 예산은 얼마인가\n답변: 5억원\n근거: 3.2절"
    assert guard.is_raw_payload(text) is True


def test_absolute_local_path_blocked():
    text = "indexed from /Users/hskim/data/private/real100_v2/doc_0007.hwp"
    assert guard.is_raw_payload(text) is True


# --- honest limitation: short English raw with no identifiers may slip the ----
# --- heuristic, which is exactly why the notification path uses aggregate-only.

def test_english_raw_caught_when_it_carries_an_identifier():
    """English raw WITH a doc/chunk id or path is caught."""
    text = "matched passage from document_id=RFP-991: scope of work covers maintenance"
    assert guard.is_raw_payload(text) is True


def test_english_prose_without_identifiers_is_a_known_gap_on_pr_body():
    """Documented limitation: plain English prose with no id/path is NOT caught by
    the PR-body heuristic. The authoritative backstop for this gap is the
    aggregate-only notification path (see test below), not this heuristic."""
    text = "the scope of work covers system construction and maintenance services"
    # default (PR-body) mode does not flag it — this is the acknowledged gap
    assert guard.is_raw_payload(text) is False
    # but the notification path (aggregate-only) DOES fail closed on it
    assert guard.is_raw_payload(text, allow_aggregate_only=True) is True


# --- aggregate / 2차가공 must be allowed --------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "5 PRs merged, revert 1, main CI green",
        "recall@k=0.82 citation_grounding=0.91 latency p99=1200ms",
        "T4 cap=5 merges=3; halted=false",
        "insufficient 12% / partial 30% / supported 58%",
        "100 docs, 221 cases, HEAD abc123 run ok",
    ],
)
def test_aggregate_allowed_both_modes(text):
    assert guard.is_raw_payload(text) is False
    assert guard.is_raw_payload(text, allow_aggregate_only=True) is False


# --- aggregate-only mode fails closed on anything non-numeric -----------------

def test_aggregate_only_blocks_korean_prose():
    assert guard.is_raw_payload("오늘 5건 머지 완료, 회귀 없음", allow_aggregate_only=True) is True


def test_aggregate_only_blocks_doc_id_even_with_numbers():
    text = "merged 3 PRs; doc_id: rfp_77"
    assert guard.is_raw_payload(text, allow_aggregate_only=True) is True


def test_aggregate_only_blocks_absolute_path():
    text = "wrote 5 files to /Users/hskim/outputs/run.json"
    assert guard.is_raw_payload(text, allow_aggregate_only=True) is True


def test_none_is_noop():
    guard.assert_no_raw_payload(None)
    guard.assert_no_raw_payload(None, allow_aggregate_only=True)
