"""Mode-agnostic helpers shared by retrieval-eval ablation runners.

Use cases (≥2 as required by absolute rule #3):

* ``scripts/phase2_chunking_ablation.py`` — chunking strategy ablation
  (issue #951, PR #952).
* ``scripts/phase3_mode_ablation.py`` — retrieval mode ablation
  (issue #954, planned PR-D after this PR-C).

The functions here only touch per-case score dicts and category lists;
they hold no knowledge of chunking, retrieval backend, RRF, or any
runtime module. ``eval.bootstrap.paired_bootstrap_ci`` (PR #950) is the
only repo-internal dependency.
"""
from __future__ import annotations

import hashlib
import re
import statistics
from collections import defaultdict
from typing import Any

from eval.bootstrap import paired_bootstrap_ci

# Hangul (가-힣) + Jamo blocks. Real-eval case ids embed agency / project /
# topic names in Korean; fixture smoke ids are opaque ASCII ("q1", "a"). Any
# Hangul in a committable eval artifact is, by the ADR 0005 private-local +
# ADR 0065 boundary ("qid + categories + metric values only"), a private leak.
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏ꥠ-꥿]")


def contains_hangul(text: str) -> bool:
    """True when ``text`` carries any Korean syllable/Jamo codepoint."""
    return bool(_HANGUL_RE.search(text))


def anon_qid(qid: str) -> str:
    """Map a possibly-identifying case id to an opaque, deterministic token.

    Real-eval qids embed agency/topic names (Korean), so emitting them into a
    committable ``raw_results.json`` leaks private RFP metadata. Fixture smoke CI
    qids are already opaque ASCII and stay readable. Only Hangul-bearing ids
    are hashed (``real_<sha1(qid)[:10]>``), so the transform is a pure,
    index-free function that can re-derive the same token from the private
    eval config at re-aggregation time (see the runners' ``cases_by_qid``).
    """
    s = str(qid)
    if not contains_hangul(s):
        return s
    return "real_" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


def categories_from_case(case: dict[str, Any]) -> list[str]:
    """Source-of-truth for category bucketing: ``hardcase_categories``.

    A case can carry multiple tags (e.g. ``[multi_hop, distractor_heavy]``);
    it then contributes one row to each tag's bucket. The paired CIs of
    different categories therefore share cases — overlap is intentional
    and called out in the report notes. Untagged cases collapse to
    ``["uncategorized"]`` so they still appear in a bucket.
    """
    raw = case.get("hardcase_categories") or []
    if not raw:
        return ["uncategorized"]
    return [str(c) for c in raw]


def _drop_paired_nones(
    a: list[Any], b: list[Any]
) -> tuple[list[float], list[float]]:
    out_a: list[float] = []
    out_b: list[float] = []
    for x, y in zip(a, b):
        if x is None or y is None:
            continue
        out_a.append(float(x))
        out_b.append(float(y))
    return out_a, out_b


def _seed_averaged_paired_ci(
    a: list[float], b: list[float], seeds: list[int]
) -> dict[str, float | int] | None:
    """Average ``mean_diff/ci_lo/ci_hi`` across bootstrap seeds. The
    sample size ``n`` and number of resamples are seed-invariant.
    """
    cis = [paired_bootstrap_ci(a, b, seed=seed) for seed in seeds]
    cis = [ci for ci in cis if ci is not None]
    if not cis:
        return None
    return {
        "mean_diff": float(statistics.mean(ci["mean_diff"] for ci in cis)),
        "ci_lo": float(statistics.mean(ci["ci_lo"] for ci in cis)),
        "ci_hi": float(statistics.mean(ci["ci_hi"] for ci in cis)),
        "n": int(cis[0]["n"]),
        "num_resamples_per_seed": int(cis[0]["num_resamples"]),
        "seeds": list(seeds),
    }


def _category_split(rows: list[dict[str, Any]], metric: str) -> dict[str, list[Any]]:
    """Split rows by ``categories`` (list, ``hardcase_categories``-derived).

    ``overall`` contains every row once; per-category buckets contain a
    row once per tag it carries. Multi-tag cases appear in multiple
    buckets, so per-category n values overlap and per-category paired
    CIs are not independent (see report notes).

    Falls back to the legacy single-string ``category`` field for rows
    that pre-date the ``categories`` schema, so old ``raw_results.json``
    files remain re-aggregateable.
    """
    out: dict[str, list[Any]] = defaultdict(list)
    out["overall"] = [row.get(metric) for row in rows]
    for row in rows:
        tags = row.get("categories") or [row.get("category") or "uncategorized"]
        for tag in tags:
            out[tag].append(row.get(metric))
    return dict(out)


def compute_deltas(
    current_rows: list[dict[str, Any]],
    other_rows: list[dict[str, Any]],
    metric: str,
    seeds: list[int],
) -> dict[str, dict[str, Any] | None]:
    """For each category, paired CI of (other - current) with seed averaging.
    Returns ``{category: ci_dict_or_none}`` for overall + each category.
    """
    by_cat_current = _category_split(current_rows, metric)
    by_cat_other = _category_split(other_rows, metric)
    out: dict[str, dict[str, Any] | None] = {}
    for category, current_vals in by_cat_current.items():
        other_vals = by_cat_other.get(category, [])
        if len(current_vals) != len(other_vals):
            out[category] = None
            continue
        a_clean, b_clean = _drop_paired_nones(other_vals, current_vals)
        if not a_clean:
            out[category] = None
            continue
        ci = _seed_averaged_paired_ci(a_clean, b_clean, seeds)
        if ci is not None:
            ci["mean_current"] = float(statistics.mean(b_clean))
            ci["mean_other"] = float(statistics.mean(a_clean))
        out[category] = ci
    return out


def _fmt_ci(ci: dict[str, Any] | None, digits: int = 3) -> str:
    if ci is None:
        return "N/A"
    md = ci["mean_diff"]
    lo = ci["ci_lo"]
    hi = ci["ci_hi"]
    significance = "**유의하지 않음**" if lo <= 0 <= hi else "유의함"
    return f"{md:+.{digits}f} ({lo:+.{digits}f}, {hi:+.{digits}f}) {significance}"


def _fmt_mean(rows: list[dict[str, Any]], metric: str, category: str | None) -> str:
    def row_matches(row: dict[str, Any]) -> bool:
        if category is None:
            return True
        tags = row.get("categories") or [row.get("category") or "uncategorized"]
        return category in tags

    vals = [
        row.get(metric)
        for row in rows
        if row.get(metric) is not None and row_matches(row)
    ]
    if not vals:
        return "—"
    return f"{statistics.mean(vals):.3f} (n={len(vals)})"


__all__ = [
    "contains_hangul",
    "anon_qid",
    "categories_from_case",
    "_drop_paired_nones",
    "_seed_averaged_paired_ci",
    "_category_split",
    "compute_deltas",
    "_fmt_ci",
    "_fmt_mean",
]
