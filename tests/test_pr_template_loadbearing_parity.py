"""Regression: PR template's load-bearing textual mirror ↔ LOAD_BEARING_PATHS.

거버넌스 비판 보고서 (2026-05-19) #2 부분 정정 후속 (issue #1041).

원안: "Load-bearing 리스트 3중 hardcode". 재조사로 다음 확정:
- ``scripts/_governance.py:LOAD_BEARING_PATHS`` = canonical
- ``.github/pull_request_template.md`` §2 영향 파일 안내 = **진짜 textual mirror**
- ``scripts/claude-hooks/stop-ship.sh`` private-path exclusion = **의미 다름**
  (data/files/, eval/*.local.yaml, reports/real*/ 같은 commit 자체를 막을 path)

이 회귀 테스트는 PR template 의 mirror 만 검증 — 진짜 drift 가능 surface.

(이전엔 §2 + §5b 두 mirror 를 검증했으나, §5b 섹션은 ADR 0084 로 PR
template 에서 제거됨 — 이제 §2 영향 파일 안내 한 곳만 검증한다.)

drift 발생 시 fail message 가 어디를 update 할지 명시.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"

# The textual mirror site the parity check must enforce. Substring matched
# against each section's header line (markdown ``##``/``###``).
SECTION_2 = "2. 영향 파일"


def _load_governance():
    spec = importlib.util.spec_from_file_location(
        "_governance_mod", REPO_ROOT / "scripts" / "_governance.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _split_into_blocks(text: str) -> dict[str, str]:
    """Split markdown into header→block text, keyed by the header line.

    A block runs from its ``##``/``###`` header until the next header. Text
    before the first header is dropped (front-matter comment).
    """
    blocks: dict[str, str] = {}
    header: str | None = None
    buf: list[str] = []
    for line in text.splitlines(keepends=True):
        if re.match(r"^#{2,4}\s", line):
            if header is not None:
                blocks[header] = "".join(buf)
            header = line.strip()
            buf = [line]
        else:
            buf.append(line)
    if header is not None:
        blocks[header] = "".join(buf)
    return blocks


def _find_block(blocks: dict[str, str], header_substr: str) -> str:
    """Return the block whose header contains ``header_substr`` (exactly one)."""
    matches = [body for hdr, body in blocks.items() if header_substr in hdr]
    assert len(matches) == 1, (
        f"expected exactly one section header containing {header_substr!r}, "
        f"found {len(matches)}: {[h for h in blocks if header_substr in h]}"
    )
    return matches[0]


def _missing_per_section(template_text: str, paths) -> list[tuple[str, str]]:
    """Return (path, section_label) for each path absent from §2.

    §2 is the only textual mirror of LOAD_BEARING_PATHS in the template since
    the §5b section was removed (ADR 0084).
    """
    blocks = _split_into_blocks(template_text)
    sec2 = _find_block(blocks, SECTION_2)
    problems: list[tuple[str, str]] = []
    for path in paths:
        # Strip trailing "/" so "eval/" matches "eval/" or "eval" in prose.
        needle = path.rstrip("/")
        if needle not in sec2:
            problems.append((path, "§2 영향 파일"))
    return problems


def test_pr_template_mentions_all_loadbearing_paths():
    """Each LOAD_BEARING_PATHS entry must appear in the §2 mirror site."""
    gov = _load_governance()
    template_text = PR_TEMPLATE.read_text(encoding="utf-8")

    problems = _missing_per_section(template_text, gov.LOAD_BEARING_PATHS)

    assert not problems, (
        "PR template (.github/pull_request_template.md) is missing "
        "LOAD_BEARING_PATHS entries from the §2 mirror section:\n"
        + "\n".join(f"  - {p}  (missing from {sec})" for p, sec in problems)
        + "\n\nDrift detected — each load-bearing path must appear in "
        "§2 영향 파일 안내. "
        "Single source of truth: scripts/_governance.py:LOAD_BEARING_PATHS."
    )


def test_per_section_check_catches_missing_path():
    """A path absent from §2 must be reported as drift.

    The doctored template lists ``rag_core.py`` in §2 but omits ``api/`` —
    only the missing one is flagged.
    """
    doctored = (
        "## 2. 영향 파일\n"
        "<!-- rag_core.py -->\n"
        "## 3. 리스크\n"
        "<!-- x -->\n"
        "## 6. 하위 호환\n"
    )
    problems = _missing_per_section(doctored, ["api/", "rag_core.py"])
    assert ("api/", "§2 영향 파일") in problems
    assert ("rag_core.py", "§2 영향 파일") not in problems


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
        "Stale mentions create misleading load-bearing expectations."
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
