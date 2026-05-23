"""Regression guard for the structural eval-artifact privacy gate (#1204).

``scripts/_governance.py --check-eval-privacy`` enforces that committable
eval-data JSON under ``reports/retrieval/`` and ``reports/real100/`` carries
only the ADR 0005 / ADR 0065 boundary fields (qid + categories + metric
values). The check is purely STRUCTURAL — it consults no list of real agency
names (that would re-leak them in committed source) — and flags two private
signatures:

* ``hangul`` — Korean text anywhere in a key or value. Real-eval qids used to
  embed 발주기관/사업명 (``real_<agency>_<topic>``); the ablation runners now
  write ``anon_qid(qid)`` (``real_<hex>``), eda_real100 anonymizes every
  agency rank, so no Hangul should survive.
* ``colon_keys`` — dict keys containing ``:``. ``retry_reason_counts`` maps
  embedded private payloads after a colon (``missing_comparison_entity:<agency>``
  / ``missing_comparison_doc:<공고번호>``); run_real_eval_delta now strips them
  to the enum prefix.

This complements the key-name ``--check-phase4-privacy`` gate, which only
covers a fixed forbidden-key set under ``reports/retrieval/phase4*``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts._governance import (
    EVAL_PRIVACY_ARTIFACT_GLOBS,
    eval_privacy_artifact_paths,
    find_eval_private_text,
    scan_eval_artifacts_for_private_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_globs_cover_both_eval_data_surfaces() -> None:
    # Retrieval ablations + real100 aggregates both leaked private text and
    # both sit outside the pre-commit ^reports/real[^/]*/ path block.
    assert "reports/retrieval" in EVAL_PRIVACY_ARTIFACT_GLOBS
    assert "reports/real100" in EVAL_PRIVACY_ARTIFACT_GLOBS
    # Self-review agreement holds public Korean axis labels — intentionally
    # NOT in scope, or the gate would false-positive on legitimate prose.
    assert "reports/self_review_agreement" not in EVAL_PRIVACY_ARTIFACT_GLOBS


def test_find_eval_private_text_flags_hangul_in_qid_and_value() -> None:
    payload = {
        "no_metadata": {
            "per_case": [
                {"qid": "real_한국전자통신연구원_예산", "chunk_recall@10": 0.5},
                {"qid": "real_abc1234567", "chunk_recall@10": 0.0},
            ]
        },
        "axis1": {"agency": {"top": [{"rank": 1, "name": "고양도시관리공사"}]}},
    }
    found = find_eval_private_text(payload)
    # 한국전자통신연구원(9)+예산(2) in the qid (11) + 고양도시관리공사(8) in the
    # agency name = 19 Hangul codepoints.
    assert found["hangul"] == 19
    assert "colon_keys" not in found


def test_find_eval_private_text_flags_colon_keys() -> None:
    payload = {
        "retry_reason_counts": {
            "topic_not_grounded": 3,
            "missing_comparison_doc:20240419765-0.0": 1,
        }
    }
    found = find_eval_private_text(payload)
    assert found["colon_keys"] == 1
    # The ASCII doc-id payload carries no Hangul, so colon_keys is the only
    # signature — proving the structural check catches non-Hangul leaks too.
    assert "hangul" not in found


def test_find_eval_private_text_ignores_clean_artifact() -> None:
    clean = {
        "no_metadata": {
            "per_case": [
                {
                    "qid": "real_abc1234567",
                    "query_type": "single_doc",
                    "categories": ["multi_hop"],
                    "chunk_recall@10": 0.5,
                    "mrr": 0.25,
                },
            ],
            "retry_reason_counts": {
                "topic_not_grounded": 2,
                "missing_comparison_entity": 1,
            },
        },
        "agency": {"top": [{"rank": 1, "name": "agency_01", "count": 9}]},
    }
    assert find_eval_private_text(clean) == {}


def test_tracked_eval_artifacts_are_clean() -> None:
    # The real regression guard: no committed eval-data JSON may carry private
    # text. Fails on the pre-fix tree (qids with agency names, colon-payload
    # retry keys, raw eda top names).
    violations = scan_eval_artifacts_for_private_text(str(REPO_ROOT))
    assert violations == [], "eval artifacts leak private text: " + "; ".join(
        f"{rel}: {sorted(found)}" for rel, found in violations
    )


def test_tracked_artifacts_parse_as_json() -> None:
    # The scanner silently skips unparseable files; assert the tracked set is
    # actually valid JSON so a corrupt artifact can't hide a leak.
    for rel in eval_privacy_artifact_paths(str(REPO_ROOT)):
        json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


_HANGUL_RE = re.compile(r"[가-힣]")


def test_eda_md_agency_table_has_no_raw_agency_names() -> None:
    # eda_real100.py anonymizes every agency rank to ``agency_NN`` (#1204), but
    # the rendered ``eda.md`` is a ``*.json``-excluded artifact the structural
    # gate never scans — so a stale committed render can re-leak the top-N
    # 발주기관 names (the #1387 live leak: #1211 fixed the generator + the JSON
    # but never regenerated eda.md). The .md elsewhere carries legitimate
    # Korean prose (header policy line, 사업명/사업 요약 row labels), so this
    # guard is scoped to the agency-distribution table rows only: the agency
    # column there must be an ``agency_NN`` label or the anonymized tail marker
    # — never a raw Hangul name.
    eda = REPO_ROOT / "reports" / "real100" / "eda.md"
    if not eda.exists():
        return
    in_table = False
    offenders: list[str] = []
    for line in eda.read_text(encoding="utf-8").splitlines():
        if line.startswith("### Agency distribution"):
            in_table = True
            continue
        if in_table:
            if line.startswith("#"):  # next section ends the table
                break
            if not line.startswith("|"):
                continue
            if _HANGUL_RE.search(line):
                offenders.append(line.strip())
    assert offenders == [], (
        "eda.md agency-distribution table leaks raw agency names "
        "(must be agency_NN labels): " + "; ".join(offenders)
    )
