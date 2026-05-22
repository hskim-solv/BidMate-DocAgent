"""Phase 1 gold schema validator (issue #1291).

Validates ``eval/multihop_sub_queries.local.yaml`` if present. The file is an
ADR 0005 real-100 derivative (gitignored), so when absent the tests SKIP rather
than fail — CI never sees the gold, and the boundary is preserved.

Schema rules:
  - id is unique and matches a real-100 case id (when real_config is present)
  - sub_queries is a list[str] of 1-5 non-empty items
    (length==1 allowed for anaphora-resolved follow_up gold; length==0 only
     tolerated on UNREVIEWED abstention skeletons, which the eval rejects anyway)
  - reviewed entries carry reviewed_by + reviewed_at
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "multihop_sub_queries.local.yaml"
REAL_CONFIG = ROOT / "eval" / "real_config.local.yaml"


def _load_gold():
    if not GOLD.exists():
        pytest.skip("gold absent (ADR 0005 derivative, gitignored)")
    data = yaml.safe_load(GOLD.read_text())
    assert isinstance(data, list) and data, "gold must be a non-empty list"
    return data


def test_ids_unique():
    gold = _load_gold()
    ids = [g["id"] for g in gold]
    assert len(ids) == len(set(ids)), "duplicate ids in gold"


def test_sub_queries_shape():
    gold = _load_gold()
    for g in gold:
        sq = g.get("sub_queries")
        assert isinstance(sq, list), f"{g['id']}: sub_queries not a list"
        for x in sq:
            assert isinstance(x, str) and x.strip(), f"{g['id']}: empty/non-str sub-query"
        # reviewed entries must satisfy length 1-5 (0 = unfilled, rejected by eval)
        if g.get("reviewed_by"):
            assert 1 <= len(sq) <= 5, f"{g['id']}: reviewed gold length {len(sq)} not in 1..5"


def test_reviewed_entries_have_audit_fields():
    gold = _load_gold()
    for g in gold:
        if g.get("reviewed_by"):
            assert g.get("reviewed_at"), f"{g['id']}: reviewed_by set but reviewed_at missing"


def test_ids_exist_in_real_config():
    gold = _load_gold()
    if not REAL_CONFIG.exists():
        pytest.skip("real_config.local.yaml absent (lives in main repo, gitignored)")
    cfg = yaml.safe_load(REAL_CONFIG.read_text())
    real_ids = {c["id"] for c in cfg.get("cases", [])}
    for g in gold:
        assert g["id"] in real_ids, f"{g['id']} not a real-100 case id"
