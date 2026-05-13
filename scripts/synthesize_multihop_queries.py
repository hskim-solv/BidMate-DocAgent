#!/usr/bin/env python3
"""Multi-hop cross-section query synthesizer for ADR 0033.

Generates multi-hop eval queries from seed RFP documents using an LLM,
then applies the `multihop_valid` quality filter to retain only queries
that are *not* answerable from a single contiguous chunk.

Output: newline-delimited JSON (one query per line) compatible with
`eval/dev_queries_v1.jsonl` schema. Committed artifact goes to
`eval/dev_queries_multihop_v1.jsonl`.

Three query types (ADR 0033 §"Query synthesis strategy"):

1. cross_section_within_doc   — answer requires combining ≥2 sections
                                of the same RFP document.
2. cross_document_comparison  — answer requires comparing the same field
                                across ≥2 RFP documents.
3. multi_step_conditional     — answer follows a chain of references
                                within one or more documents.

Backends (env var: BIDMATE_SYNTHESIZER_BACKEND):
  stub (default) — generates deterministic placeholder queries from the
                   existing data/raw fixtures; no API calls. Output is
                   valid schema but NOT real multi-hop content — run
                   with `openai_compatible` to produce the final dataset.
  openai_compatible — generic OpenAI-compatible endpoint.
                      Reads BIDMATE_JUDGE_API_KEY / BIDMATE_JUDGE_MODEL /
                      BIDMATE_JUDGE_BASE_URL (shared with llm_judge.py).

Usage:

    # Stub run (CI-safe, produces placeholder JSONL):
    python scripts/synthesize_multihop_queries.py \\
        --out eval/dev_queries_multihop_v1.jsonl \\
        --n 50

    # Live run (requires LLM API key):
    BIDMATE_SYNTHESIZER_BACKEND=openai_compatible \\
    BIDMATE_JUDGE_API_KEY=... \\
    BIDMATE_JUDGE_MODEL=claude-sonnet-4-5 \\
    python scripts/synthesize_multihop_queries.py \\
        --out eval/dev_queries_multihop_v1.jsonl \\
        --n 50

    # Or via Makefile:
    make synthesize-multihop

The synthesizer does NOT modify eval/config.yaml — the multihop slice
lives in the separate eval/multihop_config.yaml (additive, ADR 0001).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]

MULTIHOP_VALID_PROMPT = """\
You are a quality-filter judge for multi-hop RAG evaluation queries.

A query is `multihop_valid: true` if and only if:
- The correct answer CANNOT be extracted from any single contiguous
  text chunk (≤ 400 tokens).
- The retrieval system must surface ≥ 2 non-contiguous evidence spans
  and the answer builder must synthesize across them.

Evaluate the following query against the provided answer:

Query: {query}
Answer: {answer}
Document IDs referenced: {doc_ids}

Respond with JSON: {{"multihop_valid": true|false, "reason": "<≤100 chars>"}}
"""

QUERY_TYPES = [
    "cross_section_within_doc",
    "cross_document_comparison",
    "multi_step_conditional",
]


def _stub_queries(n: int) -> list[dict]:
    """Return deterministic placeholder queries from existing fixtures.

    These are schema-valid but NOT real multi-hop content. Replace by
    running with openai_compatible backend.
    """
    templates = [
        {
            "question_type": "cross_section_within_doc",
            "query": ("입찰 참여 기준 금액이 충족될 경우 보증금 납부 방식은?"),
            "target_doc_ids": ["D01"],
            "gold_answer": (
                "[STUB — requires real LLM synthesis] "
                "보증금 납부 방식은 §입찰 조건과 §계약 보증금의 조합으로 결정됩니다."
            ),
            "must_include": ["보증금", "납부"],
            "multihop_valid": True,
            "multihop_type": "cross_section_within_doc",
        },
        {
            "question_type": "cross_document_comparison",
            "query": "사업 A와 사업 B의 계약 기간을 비교하면?",
            "target_doc_ids": ["D01", "D02"],
            "gold_answer": (
                "[STUB — requires real LLM synthesis] "
                "사업 A의 계약 기간은 90일, 사업 B는 180일입니다."
            ),
            "must_include": ["계약 기간"],
            "multihop_valid": True,
            "multihop_type": "cross_document_comparison",
        },
        {
            "question_type": "multi_step_conditional",
            "query": "우선협상대상자 선정 조건이 충족될 때 최종 계약 체결 기한은?",
            "target_doc_ids": ["D01"],
            "gold_answer": (
                "[STUB — requires real LLM synthesis] "
                "우선협상대상자 요건(§3)과 계약 체결 기한(§7)을 연계해야 합니다."
            ),
            "must_include": ["우선협상대상자", "계약 체결"],
            "multihop_valid": True,
            "multihop_type": "multi_step_conditional",
        },
    ]
    result = []
    for i in range(n):
        tmpl = templates[i % len(templates)]
        q = dict(tmpl)
        qid = f"MH{(i + 1):03d}"
        q["qid"] = qid
        q["should_abstain"] = False
        q["parent_qid"] = None
        q["acceptable_aliases"] = []
        q["notes"] = f"stub — replace with LLM-synthesized query (make synthesize-multihop)"
        result.append(q)
    return result


def _live_queries(n: int) -> list[dict]:
    """Generate real multi-hop queries via OpenAI-compatible LLM API.

    Reads BIDMATE_JUDGE_API_KEY, BIDMATE_JUDGE_MODEL, BIDMATE_JUDGE_BASE_URL.
    Falls back to anthropic claude-sonnet-4-5 if BASE_URL is unset.
    """
    try:
        from openai import OpenAI
    except ImportError:
        sys.stderr.write(
            "synthesize_multihop: openai package required for live backend.\n"
            "  pip install openai\n"
        )
        sys.exit(1)

    api_key = os.environ.get("BIDMATE_JUDGE_API_KEY", "")
    model = os.environ.get("BIDMATE_JUDGE_MODEL", "claude-sonnet-4-6")
    base_url = os.environ.get("BIDMATE_JUDGE_BASE_URL", None)

    if not api_key:
        sys.stderr.write(
            "synthesize_multihop: BIDMATE_JUDGE_API_KEY not set.\n"
        )
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    raw_dir = ROOT / "data" / "raw"
    seed_texts: list[str] = []
    seed_doc_ids: list[str] = []
    for idx, f in enumerate(sorted(raw_dir.glob("*.txt"))[:5]):
        try:
            text = f.read_text()[:2000]
            seed_texts.append(text)
            seed_doc_ids.append(f"D{idx+1:02d}")
        except OSError:
            continue

    if not seed_texts:
        sys.stderr.write("synthesize_multihop: no seed .txt files found in data/raw/.\n")
        sys.exit(1)

    results: list[dict] = []
    per_type = max(1, n // len(QUERY_TYPES))
    qid_counter = 1

    for qtype in QUERY_TYPES:
        seed = seed_texts[0] if qtype != "cross_document_comparison" else "\n---\n".join(seed_texts[:2])
        docs = seed_doc_ids[:1] if qtype != "cross_document_comparison" else seed_doc_ids[:2]

        synthesis_prompt = (
            f"You are generating multi-hop RFP evaluation queries of type '{qtype}'.\n"
            f"Based on the following RFP excerpt, generate {per_type} distinct queries "
            f"that CANNOT be answered from a single chunk — they require synthesizing "
            f"information from multiple sections or documents.\n\n"
            f"RFP text:\n{seed}\n\n"
            f"Return a JSON array of objects with keys: "
            f"query (string), gold_answer (string), must_include (list[str])"
        )

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": synthesis_prompt}],
                max_tokens=2000,
                temperature=0.7,
            )
            raw = resp.choices[0].message.content or "[]"
            start = raw.find("[")
            end = raw.rfind("]") + 1
            queries = json.loads(raw[start:end]) if start >= 0 else []
        except Exception as e:
            sys.stderr.write(f"synthesize_multihop: synthesis failed for {qtype}: {e}\n")
            queries = []

        for q in queries[:per_type]:
            query_text = q.get("query", "")
            answer = q.get("gold_answer", "")

            # LLM-judge quality filter (multihop_valid rubric)
            filter_prompt = MULTIHOP_VALID_PROMPT.format(
                query=query_text, answer=answer, doc_ids=docs
            )
            try:
                freq = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": filter_prompt}],
                    max_tokens=200,
                    temperature=0.0,
                )
                filter_raw = freq.choices[0].message.content or "{}"
                start = filter_raw.find("{")
                end = filter_raw.rfind("}") + 1
                filter_result = json.loads(filter_raw[start:end])
                valid = bool(filter_result.get("multihop_valid", False))
            except Exception:
                valid = False

            if not valid:
                continue

            results.append({
                "qid": f"MH{qid_counter:03d}",
                "question_type": qtype,
                "target_doc_ids": docs,
                "target_projects": [],
                "question": query_text,
                "gold_answer": answer,
                "must_include": q.get("must_include", []),
                "acceptable_aliases": [],
                "should_abstain": False,
                "parent_qid": None,
                "multihop_type": qtype,
                "multihop_valid": True,
                "notes": "",
            })
            qid_counter += 1
            if len(results) >= n:
                break

        if len(results) >= n:
            break

    return results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="Output .jsonl path")
    p.add_argument("--n", type=int, default=50, help="Target query count")
    args = p.parse_args()

    backend = os.environ.get("BIDMATE_SYNTHESIZER_BACKEND", "stub")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if backend == "stub":
        sys.stderr.write(
            "synthesize_multihop: stub backend — placeholder queries only.\n"
            "  Run with BIDMATE_SYNTHESIZER_BACKEND=openai_compatible for real synthesis.\n"
        )
        queries = _stub_queries(args.n)
    elif backend == "openai_compatible":
        sys.stderr.write(f"synthesize_multihop: live synthesis (n={args.n})...\n")
        queries = _live_queries(args.n)
    else:
        sys.stderr.write(f"synthesize_multihop: unknown backend '{backend}'\n")
        return 1

    with out.open("w") as fh:
        for q in queries:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")

    sys.stderr.write(f"synthesize_multihop: wrote {len(queries)} queries → {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
