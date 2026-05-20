"""Regression: PR template's load-bearing textual mirror ↔ LOAD_BEARING_PATHS.

거버넌스 비판 보고서 (2026-05-19) #2 부분 정정 후속 (issue #1041).

원안: "Load-bearing 리스트 3중 hardcode". 재조사로 다음 확정:
- ``scripts/_governance.py:LOAD_BEARING_PATHS`` = canonical (5b 강제 대상)
- ``.github/pull_request_template.md`` 라인 21, 48 = **진짜 textual mirror**
- ``scripts/claude-hooks/stop-ship.sh:201-203`` = **private path exclusion** —
  load-bearing 과 의미 다름. 별도 surface (data/files/, eval/*.local.yaml,
  reports/real*/ 같은 commit 자체를 막을 path)

이 회귀 테스트는 PR template 의 mirror 만 검증 — 진짜 drift 가능 surface.

drift 발생 시 fail message 가 어디를 update 할지 명시.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"


def _load_governance():
    spec = importlib.util.spec_from_file_location(
        "_governance_mod", REPO_ROOT / "scripts" / "_governance.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_pr_template_mentions_all_loadbearing_paths():
    """Each LOAD_BEARING_PATHS entry must appear at least once in PR template.

    Two textual mirror sites currently exist (§2 영향 파일 안내 + §5b 강제
    안내). If LOAD_BEARING_PATHS grows, both sites must be updated.
    """
    gov = _load_governance()
    template_text = PR_TEMPLATE.read_text(encoding="utf-8")

    missing: list[str] = []
    for path in gov.LOAD_BEARING_PATHS:
        # Strip trailing "/" so "eval/" and "docs/adr/" match e.g. "eval/" or "docs/adr/" in prose.
        needle = path.rstrip("/")
        if needle not in template_text:
            missing.append(path)

    assert not missing, (
        "PR template (.github/pull_request_template.md) is missing the following "
        "LOAD_BEARING_PATHS entries:\n"
        + "\n".join(f"  - {p}" for p in missing)
        + "\n\nDrift detected — update the two textual mirror sites in PR template "
        "(§2 영향 파일 안내 + §5b 강제 안내) to include these paths. "
        "Single source of truth: scripts/_governance.py:LOAD_BEARING_PATHS."
    )


def test_pr_template_does_not_silently_remove_paths():
    """Detect the inverse drift: paths mentioned in PR template but removed
    from LOAD_BEARING_PATHS — the stale text is a misleading promise.

    Heuristic: each rag_*.py path mentioned in PR template should exist in
    LOAD_BEARING_PATHS (since PR template only enumerates them as
    load-bearing). False positives are unlikely because the prose explicitly
    lists them under "load-bearing 으로 표시".
    """
    gov = _load_governance()
    template_text = PR_TEMPLATE.read_text(encoding="utf-8")
    canonical = set(p.rstrip("/") for p in gov.LOAD_BEARING_PATHS)

    # Naive scan for rag_*.py / ingestion.py / visual_ingestion.py / scripts/build_index.py
    # mentioned in template. Skip false-positive sources (the file paths
    # exist nowhere else in PR template's prose context).
    rag_pattern_names = [
        "rag_core.py", "rag_retrieval.py", "rag_verifier.py",
        "rag_answer.py", "rag_query.py",
        "ingestion.py", "visual_ingestion.py",
        "scripts/build_index.py",
    ]
    stale: list[str] = []
    for name in rag_pattern_names:
        if name in template_text and name not in canonical:
            stale.append(name)

    assert not stale, (
        "PR template mentions the following paths but they're no longer in "
        "LOAD_BEARING_PATHS:\n"
        + "\n".join(f"  - {p}" for p in stale)
        + "\n\nIf they were intentionally removed, update PR template prose too. "
        "Stale mentions create misleading 5b expectations."
    )


def test_loadbearing_paths_has_minimum_invariants():
    """Sanity: the canonical list has the 11 entries CLAUDE.md documents.

    If you intentionally add/remove a load-bearing path, update CLAUDE.md
    `## 저장소 맵` and the count here together.
    """
    gov = _load_governance()
    assert len(gov.LOAD_BEARING_PATHS) >= 11, (
        f"LOAD_BEARING_PATHS shrunk below documented minimum (11): "
        f"now {len(gov.LOAD_BEARING_PATHS)}. Confirm CLAUDE.md '## 저장소 맵' "
        f"is also updated."
    )
    # Spot-check entries that CLAUDE.md explicitly enumerates.
    canonical = set(p.rstrip("/") for p in gov.LOAD_BEARING_PATHS)
    must_have = {
        "rag_core.py", "rag_retrieval.py", "rag_verifier.py",
        "rag_answer.py", "rag_query.py",
        "ingestion.py", "visual_ingestion.py",
        "eval", "api", "docs/adr", "scripts/build_index.py",
    }
    missing = must_have - canonical
    assert not missing, (
        f"LOAD_BEARING_PATHS missing CLAUDE.md-documented entries: {missing}"
    )
