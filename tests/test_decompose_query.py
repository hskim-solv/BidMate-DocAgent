"""decompose_query + Phase 2 helper unit tests (issue #1291).

Anthropic is faked via sys.modules (decompose_query imports it lazily) so the
V0-V4 routing, parse paths, and temperature selection are exercised without
network. Phase 2 helpers (reject_unreviewed gold, degenerate F1 branches) are
tested directly — the embedding-backed F1 path is covered by the live run.
"""
from __future__ import annotations

import sys
import types

import pytest

from rag_query import decompose_query


class _Block:
    def __init__(self, type, text=None, input=None):
        self.type = type
        self.text = text
        self.input = input


class _Usage:
    input_tokens = 11
    output_tokens = 7


class _Resp:
    def __init__(self, content):
        self.content = content
        self.usage = _Usage()


def _install_fake_anthropic(monkeypatch, content):
    """Install a fake ``anthropic`` whose create() returns ``content`` and
    records the kwargs it was called with (for temperature/tool assertions)."""
    captured: dict = {}

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp(content)

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return captured


@pytest.fixture
def variants_file(tmp_path):
    p = tmp_path / "v.local.txt"
    p.write_text(
        "===V1===\nnaive {query}\n"
        "===V2===\nfewshot {query}\n"
        "===V3===\ntooluse {query}\n"
        "===V4===\ncot {query}\n"
    )
    return p


def test_v0_passthrough_no_llm(variants_file, monkeypatch):
    # even with a broken anthropic, v0 must return [] without calling it
    monkeypatch.setitem(sys.modules, "anthropic", None)
    r = decompose_query("q", variant="v0", seed=17, prompt_profile_path=variants_file)
    assert r["sub_queries"] == []
    assert r["cost_usd"] is None
    assert r["parse_error"] is None


def test_v1_parses_json_array(variants_file, monkeypatch):
    cap = _install_fake_anthropic(monkeypatch, [_Block("text", text='["가","나"]')])
    r = decompose_query("q", variant="v1", seed=17, prompt_profile_path=variants_file)
    assert r["sub_queries"] == ["가", "나"]
    assert cap["temperature"] == 0.7
    assert r["tokens_in"] == 11 and r["tokens_out"] == 7


def test_v2_strips_markdown_fence(variants_file, monkeypatch):
    _install_fake_anthropic(monkeypatch, [_Block("text", text='```json\n["가","나","다"]\n```')])
    r = decompose_query("q", variant="v2", seed=42, prompt_profile_path=variants_file)
    assert r["sub_queries"] == ["가", "나", "다"]


def test_v3_tool_use_temp_zero(variants_file, monkeypatch):
    cap = _install_fake_anthropic(
        monkeypatch, [_Block("tool_use", input={"sub_queries": ["가", "나"]})])
    r = decompose_query("q", variant="v3", seed=17, prompt_profile_path=variants_file)
    assert r["sub_queries"] == ["가", "나"]
    assert cap["temperature"] == 0.0
    assert cap["tool_choice"]["name"] == "emit_sub_queries"


def test_v3_empty_tool_output_parse_error(variants_file, monkeypatch):
    _install_fake_anthropic(monkeypatch, [_Block("tool_use", input={"sub_queries": []})])
    r = decompose_query("q", variant="v3", seed=17, prompt_profile_path=variants_file)
    assert r["sub_queries"] == []
    assert r["parse_error"]


def test_v4_extracts_sub_queries_tag(variants_file, monkeypatch):
    text = "<reasoning>think</reasoning><sub_queries>[\"가\",\"나\"]</sub_queries>"
    _install_fake_anthropic(monkeypatch, [_Block("text", text=text)])
    r = decompose_query("q", variant="v4", seed=123, prompt_profile_path=variants_file)
    assert r["sub_queries"] == ["가", "나"]


def test_unknown_variant_parse_error(variants_file, monkeypatch):
    _install_fake_anthropic(monkeypatch, [_Block("text", text="x")])
    r = decompose_query("q", variant="v9", seed=17, prompt_profile_path=variants_file)
    assert r["sub_queries"] == []
    assert "no prompt block" in (r["parse_error"] or "")


def test_cap_five_subqueries(variants_file, monkeypatch):
    _install_fake_anthropic(
        monkeypatch, [_Block("text", text='["1","2","3","4","5","6","7"]')])
    r = decompose_query("q", variant="v1", seed=17, prompt_profile_path=variants_file)
    assert len(r["sub_queries"]) == 5


# --- Phase 2 helpers ---

def test_load_reviewed_gold_rejects_unreviewed(tmp_path):
    import yaml

    from eval.planner_phase2 import load_reviewed_gold

    p = tmp_path / "g.local.yaml"
    p.write_text(yaml.dump([
        {"id": "a", "sub_queries": ["x", "y"], "reviewed_by": "hskim"},
        {"id": "b", "sub_queries": ["z"], "reviewed_by": None},
    ], allow_unicode=True))
    kept, excluded = load_reviewed_gold(p)
    assert set(kept) == {"a"} and excluded == 1
    kept2, excluded2 = load_reviewed_gold(p, allow_unreviewed=True)
    assert set(kept2) == {"a", "b"} and excluded2 == 0


def test_f1_degenerate_branches():
    from eval.planner_phase2 import f1_coverage_spuriousness as f

    both_empty = f([], [], threshold=0.85, model_name="x")
    assert both_empty["f1"] == 1.0
    pred_empty = f([], ["g"], threshold=0.85, model_name="x")
    assert pred_empty["f1"] == 0.0 and pred_empty["coverage"] == 0.0
    gold_empty = f(["p"], [], threshold=0.85, model_name="x")
    assert gold_empty["f1"] == 0.0 and gold_empty["spuriousness"] == 1.0


def test_classify_tier_thresholds():
    from eval.planner_phase1_cross_model import classify_tier

    assert classify_tier(0.0)[0] == "high"
    assert classify_tier(0.2)[0] == "medium"
    assert classify_tier(0.99)[0] == "low"
