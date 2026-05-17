#!/usr/bin/env python3
"""LLM-assisted real-eval hardcase generator (issue #935, ADR 0052 prep).

Phase 1 Step 3 — `reports/real100/baseline.aggregate.json` `num_predictions=21`
is sub-noise-floor for a 100-doc corpus. ADR 0044 trajectory (n≥30/50) is
incremental; this script enables direct **n=200 hardcase expansion**
(100 docs × 2 cases/doc) so distinguishing power for real-eval ablations
recovers in a single jump.

**Hardcase-only policy** — every generated case must carry at least one
of the 5 hardcase enum tags. Plain fact-lookup queries
("사업기간이 얼마인가요?") are forbidden by both stub and Anthropic
prompts so the generated set fights retrieval, not recites.

  - ``distractor_heavy``  similar phrasing scattered across multiple
                           sections → distractor pressure
  - ``ambiguous_query``   homonyms / abbreviations / context-dependent
                           → disambiguation pressure
  - ``multi_hop``         2+ sections cross-reference required
  - ``no_answer``         document does not contain the answer →
                           abstention contract (``answerable: false``)
  - ``long_context``      tail-of-document / table / appendix only

**Scope discipline** (ADR 0005 boundary). Default backend is ``stub`` so
the script runs offline in CI and reviewer sandboxes; the Anthropic
backend is opt-in via ``BIDMATE_HARDCASE_BACKEND=anthropic`` +
``BIDMATE_HARDCASE_API_KEY`` / ``BIDMATE_HARDCASE_MODEL`` env vars.

**Consumer 0 at landing time** (PR-A per approved plan). The generated
YAML is written to stdout or ``--output <path>``; no eval config is
modified in this PR. Local workflow (separate, no PR) reviews + appends
into the gitignored ``eval/real_config.local.yaml``. ADR 0052 + baseline
regen at n=200 lands in PR-B.

Output schema matches ``eval/run_eval.py:load_config`` case-loader so a
generated YAML drops straight into ``eval/real_config.local.yaml``::

    - id: real_<agency>_<descriptor>
      query_type: single_doc | comparison | follow_up | abstention
      query: <Korean query string>
      expected_doc_ids: [<doc_id>]
      expected_terms: [<answer-substring>, ...]
      expected_citation_terms: [<citation-substring>, ...]
      answerable: true | false
      hardcase_categories: [<one or more of the 5 enums>]
      generation_notes: <one-line rationale>
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT / "data" / "raw"

HARDCASE_ENUMS = (
    "distractor_heavy",
    "ambiguous_query",
    "multi_hop",
    "no_answer",
    "long_context",
)

VALID_QUERY_TYPES = ("single_doc", "comparison", "follow_up", "abstention")

DEFAULT_K = 2
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 17


# -----------------------------------------------------------------------------
# Stub backend — deterministic, offline. Mirrors expected Anthropic response
# shape so unit tests can lock the schema contract without an SDK call.
# -----------------------------------------------------------------------------


_STUB_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "query_suffix": "사업 평가위원회 정족수 미달 시 처리 절차는?",
        "hardcase_categories": ["distractor_heavy", "multi_hop"],
        "query_type": "single_doc",
        "answerable": True,
        "expected_terms": ["위원회", "정족수"],
        "expected_citation_terms": ["위원회"],
        "notes": (
            "distractor — '정족수' 관련 키워드가 거버넌스/검수/품질 섹션에 "
            "분산 출현, multi-hop cross-ref 필요."
        ),
    },
    {
        "query_suffix": "사업의 약칭 변경 시 승인 절차는?",
        "hardcase_categories": ["ambiguous_query"],
        "query_type": "single_doc",
        "answerable": True,
        "expected_terms": ["약칭", "승인"],
        "expected_citation_terms": ["약칭"],
        "notes": "ambiguous — '약칭/별칭' 동의어 disambiguation 강제.",
    },
    {
        "query_suffix": "외부 자문단 검토 보고서와 운영 위원회 의사결정의 정합성 평가 결과는?",
        "hardcase_categories": ["multi_hop"],
        "query_type": "single_doc",
        "answerable": True,
        "expected_terms": ["자문단", "위원회"],
        "expected_citation_terms": ["자문단"],
        "notes": "multi-hop — 자문단 보고와 위원회 의사결정 두 섹션 cross-ref.",
    },
    {
        "query_suffix": "우주선 추진계 검수 절차는?",
        "hardcase_categories": ["no_answer"],
        "query_type": "abstention",
        "answerable": False,
        "expected_terms": [],
        "expected_citation_terms": [],
        "notes": (
            "no_answer — 우주선 추진계는 RFP 도메인 외; 본 문서의 모든 섹션을 "
            "훑어도 관련 키워드 부재 (abstention 강제)."
        ),
    },
    {
        "query_suffix": "부속서에 정의된 변경 이력 갱신 주기는?",
        "hardcase_categories": ["long_context"],
        "query_type": "single_doc",
        "answerable": True,
        "expected_terms": ["부속서", "이력"],
        "expected_citation_terms": ["부속서"],
        "notes": (
            "long_context — 부속서/변경이력 섹션은 문서 후반부; 본문 "
            "키워드만으로는 retrieve 어려움."
        ),
    },
)


def _stub_backend(doc: dict[str, Any], k: int, seed: int) -> list[dict[str, Any]]:
    """Deterministic templates seeded by ``(doc_id, seed)``.

    Cycles through the 5-enum templates so the canonical contract
    (every enum represented at least once when ``k=5``) is preserved
    for tests.
    """
    rng = random.Random(f"{doc.get('doc_id', '')}-{seed}")
    agency = str(doc.get("agency") or "기관")
    doc_id = str(doc.get("doc_id") or "")
    templates = list(_STUB_TEMPLATES)
    rng.shuffle(templates)
    cases: list[dict[str, Any]] = []
    for i, tmpl in enumerate(templates[:k] or templates):
        category_slug = tmpl["hardcase_categories"][0]
        case = {
            "id": f"real_{_slugify(agency)}_{category_slug}_{i + 1}",
            "query_type": tmpl["query_type"],
            "query": f"{agency} {tmpl['query_suffix']}",
            "expected_doc_ids": [doc_id] if tmpl["answerable"] and doc_id else [],
            "expected_terms": list(tmpl["expected_terms"]),
            "expected_citation_terms": list(tmpl["expected_citation_terms"]),
            "answerable": tmpl["answerable"],
            "hardcase_categories": list(tmpl["hardcase_categories"]),
            "generation_notes": tmpl["notes"],
        }
        cases.append(case)
        if len(cases) >= k:
            break
    return cases


# -----------------------------------------------------------------------------
# Anthropic backend — opt-in. Lazy import so stub path has no SDK dep.
# Mirrors scripts/generate_finetune_pairs.py env convention.
# -----------------------------------------------------------------------------


HARDCASE_INSTRUCTION = """다음 RFP 문서를 기반으로 **하드케이스 평가 쿼리 {k}개** 를 생성하세요.

절대 다음 같은 평범한 쿼리는 생성하지 마세요:
- 단순 fact lookup ("사업기간이 얼마인가요?")
- 문서 첫 페이지에 명시된 정보 그대로 묻기

반드시 다음 5 hardcase 카테고리 중 하나 이상에 해당해야 합니다:
- distractor_heavy: 비슷한 표현이 여러 섹션에 분산 — distractor 강제
- ambiguous_query: 동음이의 / 약자 / 맥락 의존 — disambiguation 강제
- multi_hop: 2+ 섹션 cross-reference 필요
- no_answer: 문서에 답이 없음 (abstention 강제, expected `answerable: false`)
- long_context: 문서 후반부 / 표 / 부록에서만 답 가능

출력은 순수 JSON 배열로만 (markdown fence 금지, 설명 prose 금지). 각 원소 schema:
{{
  "id": "real_<agency>_<descriptor>",
  "query_type": "<single_doc|comparison|follow_up|abstention>",
  "query": "<한국어 질의>",
  "expected_doc_ids": ["<doc_id>"],
  "expected_terms": ["<정답에 포함되어야 할 string>"],
  "expected_citation_terms": ["<citation 에 포함되어야 할 string>"],
  "answerable": true,
  "hardcase_categories": ["<위 5 enum 중 하나>"],
  "generation_notes": "<왜 이게 hardcase 인지 1줄 — no_answer 의 경우 'doc 에 답이 없다고 판단한 근거' 명시>"
}}

answerable=false 인 case 는 expected_terms 와 expected_citation_terms 모두 빈 배열 [].

문서 정보:
- 기관: {agency}
- 사업: {project}
- doc_id: {doc_id}

섹션 요약 (heading + 200자):
{section_summary}
"""


def _anthropic_backend(
    doc: dict[str, Any], k: int, seed: int
) -> list[dict[str, Any]]:  # pragma: no cover - network
    """Anthropic Claude backend (opt-in, env-gated)."""
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "anthropic backend requires the anthropic SDK. "
            "Install with `pip install anthropic` or use "
            "BIDMATE_HARDCASE_BACKEND=stub."
        ) from exc

    api_key = os.environ.get("BIDMATE_HARDCASE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BIDMATE_HARDCASE_API_KEY not set — cannot use anthropic backend. "
            "Set the env or use BIDMATE_HARDCASE_BACKEND=stub."
        )
    model = os.environ.get("BIDMATE_HARDCASE_MODEL", DEFAULT_MODEL)
    temperature = float(os.environ.get("BIDMATE_HARDCASE_TEMP", DEFAULT_TEMPERATURE))

    sections = doc.get("sections") or []
    section_summary = "\n".join(
        f"- {str(s.get('heading') or '')}: {str(s.get('text') or '')[:200]}"
        for s in sections[:15]
    )

    prompt = HARDCASE_INSTRUCTION.format(
        k=k,
        agency=doc.get("agency", ""),
        project=doc.get("project", ""),
        doc_id=doc.get("doc_id", ""),
        section_summary=section_summary,
    )

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text if response.content else "[]"
    try:
        cases = json.loads(raw)
    except json.JSONDecodeError:
        cases = yaml.safe_load(raw)
    if not isinstance(cases, list):
        raise ValueError(
            f"anthropic backend returned non-list: {type(cases).__name__} (raw={raw[:200]!r})"
        )
    return [c for c in cases if isinstance(c, dict)][:k]


_BACKENDS: dict[str, Callable[[dict[str, Any], int, int], list[dict[str, Any]]]] = {
    "stub": _stub_backend,
    "anthropic": _anthropic_backend,
}


# -----------------------------------------------------------------------------
# Doc loading + case normalization
# -----------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """ASCII-safe lowercase slug for case ids (Korean → underscore-bridged)."""
    safe = "".join(c if c.isascii() and (c.isalnum() or c == "_") else "_" for c in text.lower())
    parts = [p for p in safe.split("_") if p]
    return "_".join(parts)[:40] or "doc"


def load_doc(raw_dir: Path, doc_id: str) -> dict[str, Any]:
    """Load a single RFP doc JSON by ``doc_id`` (matches both the JSON's
    ``doc_id`` field and the bare filename stem for convenience)."""
    for path in sorted(raw_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if str(doc.get("doc_id") or "") == doc_id or path.stem == doc_id:
            return doc
    raise FileNotFoundError(f"doc_id={doc_id!r} not found under {raw_dir}")


def list_doc_ids(raw_dir: Path) -> list[str]:
    """Enumerate doc_ids under ``raw_dir`` (JSON ``doc_id`` field or stem)."""
    ids: list[str] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ids.append(str(doc.get("doc_id") or path.stem))
    return ids


def _normalize_case(case: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw backend output into the run_eval loader's schema.

    Enforces the abstention contract: ``answerable=false`` strips
    ``expected_terms`` and ``expected_citation_terms`` so a regression
    can't sneak a positive-evidence assertion into a no_answer case.
    """
    if not isinstance(case, dict):
        raise ValueError(f"Case must be a mapping: {case!r}")
    doc_id = str(doc.get("doc_id") or "")
    answerable = bool(case.get("answerable", True))

    expected_doc_ids = case.get("expected_doc_ids") or ([doc_id] if answerable and doc_id else [])
    expected_terms = list(case.get("expected_terms") or [])
    expected_citation_terms = list(case.get("expected_citation_terms") or [])
    if not answerable:
        expected_terms = []
        expected_citation_terms = []

    categories = case.get("hardcase_categories") or []
    if isinstance(categories, str):
        categories = [categories]

    query_type = str(case.get("query_type") or "single_doc")
    if query_type not in VALID_QUERY_TYPES:
        query_type = "single_doc"

    raw_id = str(case.get("id") or "").strip()
    if not raw_id:
        slug = categories[0] if categories else "misc"
        raw_id = f"real_{_slugify(str(doc.get('agency') or 'unknown'))}_{slug}"
    if not raw_id.startswith("real_"):
        raw_id = "real_" + raw_id

    return {
        "id": raw_id,
        "query_type": query_type,
        "query": str(case.get("query") or ""),
        "expected_doc_ids": list(expected_doc_ids),
        "expected_terms": expected_terms,
        "expected_citation_terms": expected_citation_terms,
        "answerable": answerable,
        "hardcase_categories": list(categories),
        "generation_notes": str(case.get("generation_notes") or ""),
    }


def generate_cases(
    doc: dict[str, Any], k: int, backend: str, seed: int
) -> list[dict[str, Any]]:
    """Run the chosen backend and normalize each case for the eval loader."""
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown backend {backend!r}; expected one of {sorted(_BACKENDS)}"
        )
    raw_cases = _BACKENDS[backend](doc, k, seed)
    return [_normalize_case(c, doc) for c in raw_cases]


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "LLM-assisted hardcase eval query generator (issue #935, ADR 0052 prep). "
            "Hardcase-only policy — every case carries at least one of the 5 "
            f"hardcase enums: {', '.join(HARDCASE_ENUMS)}. "
            "Output schema matches eval/run_eval.py case-loader."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Env (anthropic backend only):\n"
            "  BIDMATE_HARDCASE_BACKEND  stub|anthropic (default: stub)\n"
            "  BIDMATE_HARDCASE_API_KEY  Anthropic API key (required for anthropic)\n"
            f"  BIDMATE_HARDCASE_MODEL    Anthropic model id (default: {DEFAULT_MODEL})\n"
            f"  BIDMATE_HARDCASE_TEMP     sampling temperature (default: {DEFAULT_TEMPERATURE})\n"
        ),
    )
    parser.add_argument("--doc-id", help="Single doc_id to generate cases for.")
    parser.add_argument(
        "--batch", type=int, help="Sample N docs from --raw-dir and generate for each."
    )
    parser.add_argument(
        "--k", type=int, default=DEFAULT_K, help=f"Cases per doc (default: {DEFAULT_K})."
    )
    parser.add_argument(
        "--raw-dir",
        default=str(DEFAULT_RAW_DIR),
        help="Directory containing RFP doc JSONs.",
    )
    parser.add_argument("--output", help="Write YAML output to path (default: stdout).")
    parser.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_HARDCASE_BACKEND", "stub"),
        choices=sorted(_BACKENDS),
        help="Generation backend (default: $BIDMATE_HARDCASE_BACKEND or 'stub').",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="Seed for stub backend determinism."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_dir = Path(args.raw_dir)

    if not args.doc_id and not args.batch:
        print("error: either --doc-id or --batch is required.", file=sys.stderr)
        return 2

    if args.doc_id:
        doc_ids = [args.doc_id]
    else:
        all_ids = list_doc_ids(raw_dir)
        if not all_ids:
            print(f"error: no doc JSONs under {raw_dir}", file=sys.stderr)
            return 2
        rng = random.Random(args.seed)
        doc_ids = rng.sample(all_ids, min(args.batch, len(all_ids)))

    all_cases: list[dict[str, Any]] = []
    for doc_id in doc_ids:
        try:
            doc = load_doc(raw_dir, doc_id)
        except FileNotFoundError as exc:
            print(f"Skipping: {exc}", file=sys.stderr)
            continue
        all_cases.extend(generate_cases(doc, args.k, args.backend, args.seed))

    payload = {"cases": all_cases}
    yaml_str = yaml.safe_dump(
        payload, allow_unicode=True, sort_keys=False, default_flow_style=False
    )

    if args.output:
        Path(args.output).write_text(yaml_str, encoding="utf-8")
        print(
            f"Wrote {len(all_cases)} cases to {args.output} (backend={args.backend})",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(yaml_str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
