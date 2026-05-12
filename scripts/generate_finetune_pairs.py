#!/usr/bin/env python3
"""Generate query-chunk pairs for embedding LoRA fine-tuning (issue #179).

Pipeline:

  1. Load raw docs from ``data/raw/``.
  2. Re-chunk them with a smaller ``max_chars`` (default 240) to expand
     the prod 9-chunk default index into ~25 sub-chunks without
     touching prod chunking.
  3. For each sub-chunk, generate ``queries_per_chunk`` paraphrased
     Korean queries via a pluggable backend (``stub`` deterministic,
     or ``anthropic`` for real training data).
  4. Mine BM25 hard negatives over the sub-chunk corpus (rank window
     clamped to corpus size to absorb small-corpus reality).
  5. Apply a contamination guard against every query that appears in
     the eval surfaces (``eval/dev_queries_v1.jsonl``,
     ``eval/config.yaml`` cases + ``prior_turns``,
     ``eval/multiturn_scenarios_v1.jsonl``). Loud-fail if rejection
     rate > 5%.
  6. Split train/val deterministically by stable hash on the query.
  7. Write JSONL.

Output schema (one row per query):

    {"query": "...",
     "positive_chunk_id": "...",
     "positive_text": "...",
     "positive_doc_id": "...",
     "negatives": [{"chunk_id": "...", "text": "...", "bm25_rank": N},
                   ...],
     "split": "train" | "val"}

**Scope discipline.** Default backend is ``stub`` so the script runs
offline in CI and reviewer sandboxes (ADR 0005 boundary). Operators
regenerating training pairs set ``BIDMATE_PAIRGEN_BACKEND=anthropic``
plus ``BIDMATE_PAIRGEN_API_KEY`` / ``BIDMATE_PAIRGEN_MODEL``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from rag_core import (  # noqa: E402
    build_chunks,
    get_or_build_bm25,
    load_raw_documents,
    tokenize,
)

DEFAULT_INPUT_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT = ROOT / "data" / "training" / "embedding_pairs.jsonl"
DEFAULT_MAX_CHARS = 240
DEFAULT_QUERIES_PER_CHUNK = 200
DEFAULT_NEG_PER_POS = 3
DEFAULT_HARD_NEG_RANK_WINDOW = (3, 15)
DEFAULT_VAL_FRAC = 0.10
DEFAULT_SEED = 17
PARTICLE_RE = re.compile(r"(은|는|이|가|을|를|의|에|로|으로|에서|와|과|도|만)\b")
WHITESPACE_RE = re.compile(r"\s+")
CONTAMINATION_JACCARD_THRESHOLD = 0.70


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


_STUB_TEMPLATES = (
    "{agency}의 {term}는 무엇인가?",
    "{agency} {heading}에 대해 알려줘.",
    "{title}에서 {term}는 어떻게 명시되어 있는가?",
    "{heading}의 {term} 요구사항을 요약해줘.",
    "{agency}의 {term} 관련 내용은?",
)


def _stub_backend(chunk: dict[str, Any], k: int, seed: int) -> list[str]:
    """Deterministic templates seeded by ``(chunk_id, seed)``.

    Produces exactly ``k`` queries byte-stably. Templates cycle; once
    the (template × token) cross-product is exhausted, a "(변형 N)"
    suffix differentiates further duplicates so the JSONL stays
    byte-unique even at large ``k``. Real training data should use
    the ``anthropic`` backend; ``stub`` is for plumbing tests and the
    offline CI surface.
    """
    heading = str(chunk.get("section") or chunk.get("heading") or "")
    title = str(chunk.get("title") or "")
    agency = str(chunk.get("agency") or "기관")
    text_tokens = [t for t in tokenize(chunk.get("text", "")) if len(t) >= 2][:8]
    if not text_tokens:
        text_tokens = [heading or "내용"]

    queries: list[str] = []
    n_templates = len(_STUB_TEMPLATES)
    cycle_size = n_templates * max(1, len(text_tokens))
    for i in range(k):
        tmpl = _STUB_TEMPLATES[i % n_templates]
        term = text_tokens[(i // n_templates) % len(text_tokens)]
        q = tmpl.format(agency=agency, title=title, heading=heading or term, term=term)
        cycle_idx = i // cycle_size
        if cycle_idx > 0:
            q = f"{q} (변형 {cycle_idx})"
        queries.append(q)
    return queries


def _anthropic_backend(  # pragma: no cover - network
    chunk: dict[str, Any], k: int, seed: int
) -> list[str]:
    """Anthropic Claude backend.

    Imported lazily so the stub path has no SDK dependency. Uses the
    same env-var convention as ``scripts/llm_judge.py``:
    ``BIDMATE_PAIRGEN_API_KEY`` and ``BIDMATE_PAIRGEN_MODEL``.
    """
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "anthropic backend requires the anthropic SDK. "
            "Install with `pip install anthropic` or use "
            "BIDMATE_PAIRGEN_BACKEND=stub."
        ) from exc

    api_key = os.environ.get("BIDMATE_PAIRGEN_API_KEY")
    if not api_key:
        raise RuntimeError("BIDMATE_PAIRGEN_API_KEY is not set.")
    model = os.environ.get("BIDMATE_PAIRGEN_MODEL", "claude-sonnet-4-6")

    client = Anthropic(api_key=api_key)
    prompt = (
        "다음 RFP 본문에서 답할 수 있는 한국어 질의 {k}개를 생성하세요. "
        "각 질의는 한 줄, 번호 없이, 다양한 표현으로. JSON 배열로만 응답.\n\n"
        "기관: {agency}\n사업: {project}\n섹션: {heading}\n본문:\n{text}\n"
    ).format(
        k=k,
        agency=chunk.get("agency", ""),
        project=chunk.get("project", ""),
        heading=chunk.get("section", ""),
        text=chunk.get("text", "")[:1500],
    )
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.content[0].text if response.content else "[]"
    try:
        queries = json.loads(content)
    except json.JSONDecodeError:
        queries = [line.strip("-•0123456789. ") for line in content.splitlines() if line.strip()]
    return [str(q).strip() for q in queries if str(q).strip()][:k]


_BACKENDS: dict[str, Callable[[dict[str, Any], int, int], list[str]]] = {
    "stub": _stub_backend,
    "anthropic": _anthropic_backend,
}


# -----------------------------------------------------------------------------
# Contamination guard
# -----------------------------------------------------------------------------


def _normalize_for_contamination(query: str) -> str:
    q = query.strip().lower()
    q = PARTICLE_RE.sub("", q)
    q = WHITESPACE_RE.sub(" ", q)
    return q.strip()


def _trigrams(text: str) -> set[str]:
    chars = re.sub(r"\s+", "", text)
    if len(chars) < 3:
        return {chars} if chars else set()
    return {chars[i : i + 3] for i in range(len(chars) - 2)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_eval_queries() -> list[str]:
    """Collect every query string from the public eval surfaces.

    The training pairs MUST NOT contain any of these (test-set leakage
    would invalidate the lift measured by ``naive_baseline_finetuned``).
    """
    queries: list[str] = []

    dev_path = ROOT / "eval" / "dev_queries_v1.jsonl"
    if dev_path.exists():
        for line in dev_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            q = rec.get("question") or rec.get("query")
            if q:
                queries.append(str(q))

    multi_path = ROOT / "eval" / "multiturn_scenarios_v1.jsonl"
    if multi_path.exists():
        for line in multi_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            q = rec.get("question") or rec.get("query")
            if q:
                queries.append(str(q))

    cfg_path = ROOT / "eval" / "config.yaml"
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        for case in cfg.get("cases") or []:
            q = case.get("query")
            if q:
                queries.append(str(q))
            for turn in case.get("prior_turns") or []:
                tq = turn.get("query")
                if tq:
                    queries.append(str(tq))

    return queries


@dataclasses.dataclass(frozen=True)
class ContaminationGuard:
    exact_set: frozenset[str]
    trigram_sets: tuple[frozenset[str], ...]
    jaccard_threshold: float = CONTAMINATION_JACCARD_THRESHOLD

    @classmethod
    def from_eval_queries(cls, eval_queries: list[str]) -> "ContaminationGuard":
        normalized = [_normalize_for_contamination(q) for q in eval_queries]
        normalized = [n for n in normalized if n]
        trigrams = tuple(frozenset(_trigrams(n)) for n in normalized)
        return cls(exact_set=frozenset(normalized), trigram_sets=trigrams)

    def is_contaminated(self, query: str) -> bool:
        norm = _normalize_for_contamination(query)
        if not norm:
            return True  # empty queries are useless; treat as contamination
        if norm in self.exact_set:
            return True
        q_trigrams = frozenset(_trigrams(norm))
        if not q_trigrams:
            return False
        for eval_trigrams in self.trigram_sets:
            if _jaccard(q_trigrams, eval_trigrams) >= self.jaccard_threshold:
                return True
        return False


# -----------------------------------------------------------------------------
# Sub-chunking + BM25 mining
# -----------------------------------------------------------------------------


def build_subchunks(input_dir: Path, max_chars: int) -> list[dict[str, Any]]:
    """Re-chunk raw docs at a smaller ``max_chars`` for training data.

    Reuses prod chunking (``rag_core.build_chunks``) so the schema
    matches the production index — no parallel chunker to maintain.
    """
    docs = load_raw_documents(input_dir)
    return build_chunks(docs, max_chars=max_chars, overlap_sentences=1)


def mine_hard_negatives(
    positive: dict[str, Any],
    query: str,
    subchunks: list[dict[str, Any]],
    bm25_index: dict[str, Any],
    rank_window: tuple[int, int],
    neg_per_pos: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """BM25 hard-neg mining over the sub-chunk corpus.

    Drops same-``doc_id`` chunks (likely false negatives) then samples
    from the configured rank window. Window is clamped to the
    available corpus so this stays robust on small fixtures.
    """
    bm25, chunk_ids = get_or_build_bm25(bm25_index)
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scores = bm25.get_scores(query_tokens)
    ranked = sorted(zip(chunk_ids, scores), key=lambda kv: kv[1], reverse=True)

    by_id = {c["chunk_id"]: c for c in subchunks}
    positive_doc_id = positive["doc_id"]
    candidates: list[tuple[str, float, int]] = []
    for rank, (cid, score) in enumerate(ranked):
        chunk = by_id.get(cid)
        if chunk is None or chunk["doc_id"] == positive_doc_id:
            continue
        candidates.append((cid, float(score), rank))

    lo, hi = rank_window
    lo = max(0, lo)
    hi = max(lo + 1, hi)
    in_window = [(cid, score, rank) for cid, score, rank in candidates if lo <= rank <= hi]

    pool = in_window if len(in_window) >= neg_per_pos else candidates
    if not pool:
        return []

    sampled = rng.sample(pool, k=min(neg_per_pos, len(pool)))
    negs: list[dict[str, Any]] = []
    for cid, _score, rank in sampled:
        chunk = by_id[cid]
        negs.append(
            {
                "chunk_id": cid,
                "text": chunk["text"],
                "bm25_rank": rank,
            }
        )
    return negs


# -----------------------------------------------------------------------------
# Pipeline
# -----------------------------------------------------------------------------


def _split_for_query(query: str, val_frac: float) -> str:
    """Deterministic train/val assignment by stable hash."""
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_frac else "train"


def generate_pairs(
    *,
    input_dir: Path,
    output: Path,
    backend: str,
    queries_per_chunk: int,
    neg_per_pos: int,
    hard_neg_rank_window: tuple[int, int],
    val_frac: float,
    seed: int,
    max_chars: int,
    fail_threshold: float = 0.05,
) -> dict[str, Any]:
    """End-to-end pipeline. Returns an aggregate stats dict."""
    if backend not in _BACKENDS:
        raise ValueError(f"Unknown backend {backend!r}; choose one of {sorted(_BACKENDS)}.")
    backend_fn = _BACKENDS[backend]

    subchunks = build_subchunks(input_dir, max_chars=max_chars)
    if not subchunks:
        raise RuntimeError(f"No sub-chunks produced from {input_dir}.")

    bm25_index: dict[str, Any] = {"chunks": subchunks}
    guard = ContaminationGuard.from_eval_queries(load_eval_queries())

    output.parent.mkdir(parents=True, exist_ok=True)
    total_generated = 0
    total_rejected = 0
    per_doc_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    rng_master = random.Random(seed)

    with output.open("w", encoding="utf-8") as fh:
        for chunk in subchunks:
            cid = chunk["chunk_id"]
            chunk_rng = random.Random(f"{cid}:{seed}")
            queries = backend_fn(chunk, queries_per_chunk, seed)
            for q in queries:
                total_generated += 1
                if guard.is_contaminated(q):
                    total_rejected += 1
                    continue
                negs = mine_hard_negatives(
                    chunk,
                    q,
                    subchunks,
                    bm25_index,
                    hard_neg_rank_window,
                    neg_per_pos,
                    chunk_rng,
                )
                split = _split_for_query(q, val_frac)
                row = {
                    "query": q,
                    "positive_chunk_id": cid,
                    "positive_text": chunk["text"],
                    "positive_doc_id": chunk["doc_id"],
                    "negatives": negs,
                    "split": split,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                per_doc_counts[chunk["doc_id"]] += 1
                split_counts[split] += 1

    _ = rng_master  # reserved for future cross-chunk randomization
    rejection_rate = (total_rejected / total_generated) if total_generated else 0.0
    if rejection_rate > fail_threshold:
        raise RuntimeError(
            f"Contamination rejection rate {rejection_rate:.1%} exceeds "
            f"threshold {fail_threshold:.0%}. The prompt template is "
            f"likely leaking eval phrasing — inspect rejected queries."
        )

    return {
        "subchunks": len(subchunks),
        "queries_generated": total_generated,
        "queries_rejected": total_rejected,
        "rejection_rate": rejection_rate,
        "pairs_written": total_generated - total_rejected,
        "per_doc": dict(per_doc_counts),
        "splits": dict(split_counts),
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _parse_rank_window(value: str) -> tuple[int, int]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("rank window must be 'lo,hi'.")
    lo, hi = int(parts[0]), int(parts[1])
    if lo < 0 or hi <= lo:
        raise argparse.ArgumentTypeError("rank window requires 0 <= lo < hi.")
    return lo, hi


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input_dir", default=str(DEFAULT_INPUT_DIR))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    ap.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_PAIRGEN_BACKEND", "stub"),
        choices=sorted(_BACKENDS),
    )
    ap.add_argument("--queries_per_chunk", type=int, default=DEFAULT_QUERIES_PER_CHUNK)
    ap.add_argument("--neg_per_pos", type=int, default=DEFAULT_NEG_PER_POS)
    ap.add_argument(
        "--hard_neg_rank_window",
        type=_parse_rank_window,
        default=DEFAULT_HARD_NEG_RANK_WINDOW,
        help="Comma-separated lo,hi rank window for BM25 hard-neg sampling.",
    )
    ap.add_argument("--val_frac", type=float, default=DEFAULT_VAL_FRAC)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--max_chars", type=int, default=DEFAULT_MAX_CHARS)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stats = generate_pairs(
        input_dir=Path(args.input_dir),
        output=Path(args.output),
        backend=args.backend,
        queries_per_chunk=args.queries_per_chunk,
        neg_per_pos=args.neg_per_pos,
        hard_neg_rank_window=args.hard_neg_rank_window,
        val_frac=args.val_frac,
        seed=args.seed,
        max_chars=args.max_chars,
    )
    print(f"[OK] Wrote pairs: {args.output}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
