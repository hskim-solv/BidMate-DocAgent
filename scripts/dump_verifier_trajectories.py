#!/usr/bin/env python3
"""Phase 1 Step 2.5 — verifier over-abstention trajectory dump.

Selects 5-10 cases where the production ``full`` pipeline (verifier_retry=True)
abstained or returned a wrong answer while ``no_verifier_retry`` (same retrieval,
verifier off) returned a correct one. Re-runs both variants with the env-gated
verbose trace enrichment, then emits:

- ``reports/phase1_step2_5_trajectories.jsonl`` — one record per ``<case, variant>``
- ``reports/phase1_step2_5_failure_modes.md`` — inductive 1-pager scaffold
  (axis tally hand-filled after reading)

Reuses ``eval.run_eval.evaluate_run`` + ``ablation_runs(config)`` so preset
construction stays single-source-of-truth. Off-by-default ``BIDMATE_TRACE_VERBOSE``
env var means standard ``make smoke`` traces are untouched — see
``reports/phase1_step2_5_report.md`` for ADR 0001 invariant rationale.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import (  # noqa: E402  (path insert needed)
    ablation_runs,
    evaluate_run,
    load_config,
    load_index,
    safe_path_part,
)


def select_candidates(jsonl_path: Path) -> list[dict[str, object]]:
    """Return per-case_id rows where full∈{abstain or wrong} ∧ no_verifier_retry=correct.

    Sort key: (1.0 - no_verifier_retry.accuracy, case_id) so highest-impact cases
    (counterfactual correct) bubble to the top, then alphabetic for determinism.
    """
    by_case: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        by_case[r["case_id"]][r["variant"]] = r
    out: list[dict[str, object]] = []
    for cid in sorted(by_case):
        vs = by_case[cid]
        f = vs.get("full")
        n = vs.get("no_verifier_retry")
        if not f or not n:
            continue
        fa = float(f.get("accuracy") or 0)
        na = float(n.get("accuracy") or 0)
        if (f.get("abstained") or fa < 1.0) and na >= 1.0:
            verdict = "over_abstain" if f.get("abstained") else "wrong_from_partial"
            out.append(
                {
                    "case_id": cid,
                    "full_accuracy": fa,
                    "no_verifier_accuracy": na,
                    "full_abstained": bool(f.get("abstained")),
                    "query_type": f.get("query_type"),
                    "verdict": verdict,
                }
            )
    out.sort(key=lambda r: (1.0 - float(r["no_verifier_accuracy"]), str(r["case_id"])))
    return out


def load_trace(trace_dir: Path, run_name: str, case_id: str) -> dict | None:
    path = trace_dir / safe_path_part(run_name) / f"{safe_path_part(case_id)}.trace.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def project_record(case: dict, candidate: dict, trace: dict | None) -> dict:
    """Project the trace JSON + candidate metadata into one JSONL record."""
    trace = trace or {}
    planner = ((trace.get("trace") or {}).get("planner")) or {}
    diag = trace.get("diagnostics_subset") or {}
    answer = trace.get("answer") or {}
    return {
        "case_id": case.get("id"),
        "query": case.get("query"),
        "query_type": candidate.get("query_type"),
        "answerable": case.get("answerable"),
        "gold": {
            "expected_doc_ids": case.get("expected_doc_ids") or [],
            "expected_terms": case.get("expected_terms") or [],
            "expected_claim_targets": case.get("expected_claim_targets") or [],
        },
        "variant": trace.get("run"),
        "stage_sequence": planner.get("stage_sequence"),
        "attempts": planner.get("attempts") or [],
        "retry_count": diag.get("retry_count"),
        "verification_topics": diag.get("verification_topics"),
        "verification_reasons": diag.get("verification_reasons"),
        "final_relaxation_reason": diag.get("final_relaxation_reason"),
        "final_evidence": trace.get("evidence") or [],
        "answer_status": trace.get("answer_status") or answer.get("status"),
        "answer_text": trace.get("answer_text") or "",
        "abstained": (trace.get("answer_status") == "insufficient"),
        "claim_count": len(answer.get("claims") or []),
        "verdict": candidate.get("verdict"),
        "counter_no_verifier_accuracy": candidate.get("no_verifier_accuracy"),
    }


def render_md(jsonl_path: Path, output_md: Path, candidates: list[dict]) -> None:
    """Render an inductive 1-pager. Axis tally is *not* pre-filled — the reader
    fills it after reading the cases. Hard cap ≤ 100 lines of body."""
    records = [json.loads(l) for l in jsonl_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_case: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for r in records:
        by_case[r["case_id"]][r["variant"]] = r
    selected = list(by_case.keys())

    lines: list[str] = []
    lines.append("# Phase 1 Step 2.5 — Verifier over-abstention failure modes")
    lines.append("")
    lines.append(f"Cases selected: **{len(selected)}** (cap from `--max_cases`).")
    lines.append(
        "Selection predicate: `full∈{abstain or wrong} ∧ no_verifier_retry.accuracy=1.0`, "
        "sourced from `reports/distinguishing_power_v1.jsonl`."
    )
    lines.append("")
    lines.append("## Per-case trajectories")
    lines.append("")
    for cid in selected:
        full = by_case[cid].get("full") or {}
        nv = by_case[cid].get("no_verifier_retry") or {}
        verdict = full.get("verdict") or "?"
        lines.append(f"### {cid}  · verdict={verdict}")
        lines.append(f"- **Query**: `{full.get('query', '')}`")
        gold = full.get("gold") or {}
        lines.append(
            f"- **Gold**: docs={gold.get('expected_doc_ids') or []} "
            f"terms={gold.get('expected_terms') or []}"
        )
        lines.append(
            f"- **`full` verification_topics**: {full.get('verification_topics') or []}"
        )
        lines.append(
            f"- **`full` stage_sequence**: {full.get('stage_sequence') or []} · "
            f"retry_count={full.get('retry_count')} · final_relaxation_reason="
            f"`{full.get('final_relaxation_reason')}`"
        )
        attempts = full.get("attempts") or []
        for idx, a in enumerate(attempts):
            lines.append(
                f"  - attempt[{idx}] stage={a.get('stage')} top_k={a.get('top_k')} "
                f"verified={a.get('verified')} reasons={a.get('verification_reasons')}"
            )
        full_chunks = [
            f"{e.get('doc_id')}::{(e.get('chunk_id') or '').split('::')[-1]}"
            for e in (full.get("final_evidence") or [])
        ]
        nv_chunks = [
            f"{e.get('doc_id')}::{(e.get('chunk_id') or '').split('::')[-1]}"
            for e in (nv.get("final_evidence") or [])
        ]
        overlap = sorted(set(full_chunks) & set(nv_chunks))
        lines.append(f"- **`full` final_evidence chunks**: {full_chunks or '[]'}")
        lines.append(f"- **`no_verifier_retry` final_evidence chunks**: {nv_chunks or '[]'}")
        lines.append(
            f"- **Overlap**: {overlap or '[]'} → "
            f"{'same chunks, different verdict' if overlap else 'disjoint pools'}"
        )
        lines.append(
            f"- **`full` answer_status**: {full.get('answer_status')} · "
            f"abstained={full.get('abstained')} · claims={full.get('claim_count')}"
        )
        lines.append(
            f"- **`no_verifier_retry` answer_status**: {nv.get('answer_status')} · "
            f"abstained={nv.get('abstained')} · claims={nv.get('claim_count')}"
        )
        lines.append(
            f"- **`full` answer_text preview**: "
            f"`{(full.get('answer_text') or '').strip()[:160]}`"
        )
        lines.append(
            f"- **`no_verifier_retry` answer_text preview**: "
            f"`{(nv.get('answer_text') or '').strip()[:160]}`"
        )
        lines.append("")
    lines.append("## Inductive axis tally  *(hand-fill after reading)*")
    lines.append("")
    lines.append("| axis (post-hoc) | count | case_ids |")
    lines.append("|---|---:|---|")
    lines.append("| _(fill in)_ | | |")
    lines.append("")
    lines.append(
        "Candidate axes to *consider but not fix*: topic_term_mismatch · "
        "metadata_evidence_label_miss · partial_grounding_threshold_too_strict · "
        "retry_query_drift · answer_status_voting_quirk."
    )
    lines.append("")
    lines.append("## Phase 2 hand-off")
    lines.append("")
    lines.append(
        "Oracle verifier design must consume: ground-truth `answerable` + "
        "`gold.expected_doc_ids` (oracle reference); `full.final_evidence` (what was "
        "rejected); `full.verification_topics` + `verification_reasons` (the rejection "
        "axis); `no_verifier_retry.final_evidence` (counterfactual proving "
        "retrievability). Axis tally above is the prior on which oracle-policy levers "
        "to expose first."
    )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--distinguishing_jsonl", default="reports/distinguishing_power_v1.jsonl")
    p.add_argument("--config", default="eval/config.yaml")
    p.add_argument("--index_dir", default="data/index")
    p.add_argument("--trace_dir", default="reports/traces_step2_5")
    p.add_argument("--output_jsonl", default="reports/phase1_step2_5_trajectories.jsonl")
    # Auto-rendered template only; the canonical hand-filled 1-pager lives at
    # ``reports/phase1_step2_5_failure_modes.md`` and is NOT overwritten by
    # this script (the hand-filled axis tally + Phase 2 hand-off would be
    # lost on re-run). Diff template vs hand-filled to verify case bodies
    # stay in sync if the underlying JSONL changes.
    p.add_argument("--output_md", default="reports/phase1_step2_5_failure_modes_template.md")
    p.add_argument("--max_cases", type=int, default=10)
    p.add_argument(
        "--variants",
        nargs="+",
        default=("full", "no_verifier_retry"),
        help="Ablation preset names to dump trajectories for (both required).",
    )
    args = p.parse_args()

    distinguishing = Path(args.distinguishing_jsonl)
    if not distinguishing.exists():
        print(f"[ERROR] {distinguishing} not found.", file=sys.stderr)
        return 2

    candidates = select_candidates(distinguishing)
    if not candidates:
        print("[ERROR] No candidates matched the over-abstention predicate.", file=sys.stderr)
        return 3
    candidates = candidates[: args.max_cases]
    print(f"[info] selected {len(candidates)} candidate cases:", file=sys.stderr)
    for c in candidates:
        print(
            f"  - {c['case_id']}  verdict={c['verdict']}  "
            f"full_acc={c['full_accuracy']}  nv_acc={c['no_verifier_accuracy']}",
            file=sys.stderr,
        )
    candidate_ids = {c["case_id"]: c for c in candidates}

    config = load_config(Path(args.config))
    index = load_index(Path(args.index_dir))
    runs = ablation_runs(config)
    run_by_name = {r["name"]: r for r in runs}
    missing_runs = [v for v in args.variants if v not in run_by_name]
    if missing_runs:
        print(f"[ERROR] variants not in config: {missing_runs}", file=sys.stderr)
        return 4

    cases = [c for c in (config.get("cases") or []) if c.get("id") in candidate_ids]
    missing_cases = candidate_ids.keys() - {c.get("id") for c in cases}
    if missing_cases:
        print(f"[ERROR] candidate cases missing from config: {missing_cases}", file=sys.stderr)
        return 5

    # Force verbose trace enrichment for this process; off elsewhere.
    os.environ["BIDMATE_TRACE_VERBOSE"] = "1"
    trace_root = Path(args.trace_dir)
    trace_root.mkdir(parents=True, exist_ok=True)

    for variant in args.variants:
        rc = run_by_name[variant]
        print(f"[info] running variant={variant} over {len(cases)} cases...", file=sys.stderr)
        evaluate_run(index, cases, rc, trace_dir=trace_root)

    out_path = Path(args.output_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    case_by_id = {c["id"]: c for c in cases}
    for cand in candidates:
        case = case_by_id[cand["case_id"]]
        for variant in args.variants:
            trace = load_trace(trace_root, variant, cand["case_id"])
            if trace is None:
                print(f"[warn] trace missing for {variant}/{cand['case_id']}", file=sys.stderr)
                continue
            records.append(project_record(case, cand, trace))
    with out_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[info] wrote {len(records)} records → {out_path}", file=sys.stderr)

    render_md(out_path, Path(args.output_md), candidates)
    print(f"[info] wrote 1-pager → {args.output_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
