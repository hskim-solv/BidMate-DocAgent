#!/usr/bin/env python3
"""External-LLM cross-rating of self-review 5-axis verdicts (ADR 0060).

Reads a self-review ``stats.json`` (from
``scripts/claude-hooks/_self_review.py --quarter <Qx-YYYY> --emit-stats``),
assigns ``✓`` / ``△`` / ``✗`` per collaboration axis via either a
deterministic stub (SKILL.md rubric thresholds) or an external LLM
(``openai_compatible``), then computes inter-rater agreement against the
operator's own verdicts (parsed from ``docs/self-review/Qx-YYYY.md``) using
``eval/judges/judge_agreement.compute_agreement``.

The point (ADR 0060): the self-review rubric is currently graded by the same
LLM that writes the report — a self-referential cycle with no external
anchor. An independent rater (stub = deterministic, or a different LLM)
breaks that cycle. Low agreement (Cohen's κ < 0.6, ADR 0016 "substantial")
is a signal that the rubric itself, not the operator, is unreliable.

No new dependency: ``openai`` is opt-in (``requirements-dev.txt``); the stub
backend is stdlib-only and zero-cost. Verdict vocabulary maps onto the
existing ``JUDGE_STATUSES`` (ADR 0006):

    ✓ → supported, △ → partial, ✗ → insufficient

Exit codes:
    0  cross-rating emitted successfully
    1  invalid input (missing/unreadable stats or operator file)
    2  backend / judge error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judges.judge_common import (  # noqa: E402
    build_openai_client,
    call_openai_json,
    get_judge_model,
)
from eval.judges.judge_agreement import compute_agreement  # noqa: E402


# Verdict ↔ JUDGE_STATUSES mapping (ADR 0060). Lets us reuse the existing
# judge_agreement.cohens_kappa / compute_agreement (LABELS = the same 3
# statuses) with only a label translation.
VERDICT_TO_STATUS: dict[str, str] = {
    "✓": "supported",
    "△": "partial",
    "✗": "insufficient",
}
STATUS_TO_VERDICT: dict[str, str] = {v: k for k, v in VERDICT_TO_STATUS.items()}
VALID_VERDICTS: tuple[str, ...] = tuple(VERDICT_TO_STATUS)

# The 5 collaboration axes, collapsed from SKILL.md's 7 rows (#4-A/#4-B and
# #5-A/#5-B are combined here) so they line up 1:1 with the operator's
# committed docs/self-review/Qx-YYYY.md table for agreement.
AXES: tuple[tuple[str, str], ...] = (
    ("axis_1_context_efficiency", "컨텍스트 효율"),
    ("axis_2_agent_delegation", "Agent 위임 패턴"),
    ("axis_3_governance_roi", "거버넌스 자동화 ROI"),
    ("axis_4_cycle_time", "사이클 타임"),
    ("axis_5_memory_hygiene", "메모리 위생"),
)
AXIS_KEYS: tuple[str, ...] = tuple(k for k, _ in AXES)


def extract_signals(stats: dict[str, Any]) -> dict[str, Any]:
    """Pull the per-axis raw signals out of a stats dict (metadata-only).

    Mirrors the signal paths in SKILL.md lines 127-135. Returns a compact
    dict safe to embed in an LLM prompt — counts and rates only, never any
    body text (honours the metadata-only contract the collector guarantees).
    """
    sessions = stats.get("sessions", {})
    s_count = max(int(sessions.get("count", 0) or 0), 1)
    tool_dist = sessions.get("tool_call_distribution", {})
    agent_dels = sessions.get("agent_delegations", {})
    gov = stats.get("governance_hooks", {})
    axis_2 = stats.get("axis_2_plan_subagent_skip_rate", {})
    axis_4 = stats.get("axis_4_cycle_time", {})
    axis_5 = (stats.get("axis_5_memory_hygiene", {}) or {}).get(
        "content_freshness", {}
    )
    return {
        "axis_1": {
            "explore_calls": int(agent_dels.get("Explore", 0) or 0),
            "read_per_session": int(tool_dist.get("Read", 0) or 0) / s_count,
        },
        "axis_2": {
            "skip_rate": axis_2.get("skip_rate"),
            "prs_evaluated": int(axis_2.get("prs_evaluated", 0) or 0),
        },
        "axis_3": {
            "fires": int(gov.get("pretooluse_loadbearing_fires", 0) or 0),
            "distinct_actions": len(gov.get("fires_by_action", {}) or {}),
        },
        "axis_4": {
            "adr_lag_days_mean": (axis_4.get("adr_lag_days", {}) or {}).get("mean"),
            "pr_turnaround_hours_mean": (
                axis_4.get("pr_turnaround_hours", {}) or {}
            ).get("mean"),
        },
        "axis_5": {"content_fresh_rate": axis_5.get("fresh_rate")},
        "evidence_age_days": stats.get("evidence_age_days"),
    }


def _band(value: float | None, good: float, bad: float) -> str:
    """Three-band classifier: ≤good → ✓, ≤bad → △, else ✗; None → △."""
    if value is None:
        return "△"
    if value <= good:
        return "✓"
    if value <= bad:
        return "△"
    return "✗"


def _guard_downgrade(verdict: str, evidence_age_days: float | None) -> str:
    """ADR 0060 time-separation guard: evidence_age < 1.0 day downgrades ✓→△.

    Q2-2026's evidence (ADR 0038, hook-fires.log) was produced the *same
    day* the review was written. A ✓ that rests on same-day evidence cannot
    be confirmed, so it is forced to △.
    """
    if (
        evidence_age_days is not None
        and evidence_age_days < 1.0
        and verdict == "✓"
    ):
        return "△"
    return verdict


def stub_verdicts(stats: dict[str, Any]) -> dict[str, str]:
    """Deterministic verdicts straight from SKILL.md thresholds (ADR 0060).

    This is the stub backend — it absorbs what was the standalone
    "deterministic scorer". Three self-pass guards are baked in:

    - ``evidence_age_days < 1.0`` → any ✓ downgraded to △ (time separation)
    - axis #3 ``fires == 0`` → ✗ (silence is infra-dead, not a pass)
    - axis #2 ``prs_evaluated < 10`` → △ (sample too small to grade)
    """
    sig = extract_signals(stats)
    ev_age = sig["evidence_age_days"]
    out: dict[str, str] = {}

    # axis #1 — context efficiency (Explore ≥2 AND Read/session ≤10)
    a1 = sig["axis_1"]
    e_ok = a1["explore_calls"] >= 2
    r_ok = a1["read_per_session"] <= 10
    out["axis_1_context_efficiency"] = (
        "✓" if (e_ok and r_ok) else ("△" if (e_ok or r_ok) else "✗")
    )

    # axis #2 — agent delegation (sample-size guard first)
    a2 = sig["axis_2"]
    if a2["prs_evaluated"] < 10:
        out["axis_2_agent_delegation"] = "△"
    elif a2["skip_rate"] is None:
        out["axis_2_agent_delegation"] = "△"
    elif a2["skip_rate"] <= 0.2:
        out["axis_2_agent_delegation"] = "✓"
    elif a2["skip_rate"] <= 0.5:
        out["axis_2_agent_delegation"] = "△"
    else:
        out["axis_2_agent_delegation"] = "✗"

    # axis #3 — governance ROI (silence guard: fires=0 → ✗, never a pass)
    a3 = sig["axis_3"]
    if a3["fires"] == 0:
        out["axis_3_governance_roi"] = "✗"
    elif a3["distinct_actions"] >= 2:
        out["axis_3_governance_roi"] = "✓"
    else:
        out["axis_3_governance_roi"] = "△"

    # axis #4 — cycle time (combine 4-A ADR lag + 4-B PR turnaround)
    a4 = sig["axis_4"]
    v4a = _band(a4["adr_lag_days_mean"], 5, 10)
    v4b = _band(a4["pr_turnaround_hours_mean"], 48, 120)
    out["axis_4_cycle_time"] = (
        "✓"
        if (v4a == "✓" and v4b == "✓")
        else ("✗" if ("✗" in (v4a, v4b)) else "△")
    )

    # axis #5 — memory hygiene (5-B content freshness only). 5-A index
    # hygiene needs fires_by_reason["memory-lines"], but the collector emits
    # fires_by_action (action key, not reason) — a known SKILL.md↔collector
    # mismatch documented in ADR 0060 Context. 5-A is deferred until the
    # collector emits fires_by_action_reason; axis_5 grades on 5-B alone.
    fr = sig["axis_5"]["content_fresh_rate"]
    if fr is None:
        out["axis_5_memory_hygiene"] = "✗"
    elif fr >= 0.5:
        out["axis_5_memory_hygiene"] = "✓"
    elif fr >= 0.2:
        out["axis_5_memory_hygiene"] = "△"
    else:
        out["axis_5_memory_hygiene"] = "✗"

    return {k: _guard_downgrade(v, ev_age) for k, v in out.items()}


def _build_prompt(stats: dict[str, Any]) -> str:
    """Compose the external-LLM scoring prompt (metadata-only signals)."""
    signals = extract_signals(stats)
    return (
        "You are an independent rater scoring a Claude Code collaboration "
        'quarter on 5 axes. Assign exactly one verdict per axis: "✓" '
        '(good), "△" (partial), "✗" (poor).\n\n'
        "Rubric thresholds:\n"
        "1. context_efficiency: ✓ if explore_calls ≥2 AND read_per_session "
        "≤10; △ if exactly one holds; ✗ if neither.\n"
        "2. agent_delegation: ✓ if skip_rate ≤0.2; △ if 0.2–0.5; ✗ if >0.5. "
        "If prs_evaluated <10, return △ (insufficient sample).\n"
        "3. governance_roi: ✓ if fires >0 AND distinct_actions ≥2; △ if "
        "fires >0 with 1 action; ✗ if fires=0.\n"
        "4. cycle_time: ✓ if adr_lag_days_mean ≤5 AND pr_turnaround_hours_mean "
        "≤48; ✗ if adr_lag >10 or pr_turnaround >120; △ otherwise (null=△).\n"
        "5. memory_hygiene: ✓ if content_fresh_rate ≥0.5; △ if 0.2–0.5; ✗ if "
        "<0.2 or null.\n\n"
        "If evidence_age_days <1.0, downgrade any ✓ to △ (evidence and review "
        "produced the same day — cannot be independently confirmed).\n\n"
        f"Raw signals:\n{json.dumps(signals, indent=2, ensure_ascii=False)}\n\n"
        "Return a JSON object with exactly these keys: "
        "axis_1_context_efficiency, axis_2_agent_delegation, "
        "axis_3_governance_roi, axis_4_cycle_time, axis_5_memory_hygiene. "
        'Each value must be one of "✓", "△", "✗".'
    )


def openai_verdicts(stats: dict[str, Any]) -> dict[str, str]:
    """External-LLM verdicts via the existing openai_compatible judge infra.

    Reuses build_openai_client + call_openai_json (ADR 0006/0012). Raises
    RuntimeError on a missing env var (fast fail) or a malformed response.
    """
    client = build_openai_client()
    model = get_judge_model()
    result = call_openai_json(client, model, _build_prompt(stats))
    if not isinstance(result, dict):
        raise RuntimeError("judge returned non-JSON content")
    out: dict[str, str] = {}
    for key in AXIS_KEYS:
        verdict = result.get(key)
        if verdict not in VALID_VERDICTS:
            raise RuntimeError(
                f"judge returned invalid verdict for {key}: {verdict!r}"
            )
        out[key] = verdict
    return out


def judge_self_review(
    stats: dict[str, Any],
    operator_verdicts: dict[str, str] | None = None,
    *,
    backend: str = "stub",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Cross-rate the 5 collaboration axes; return ``(local, aggregate)``.

    local: per-axis ``{judge_verdict, operator_verdict}`` (committable —
        verdicts only, no body text).
    aggregate: ``{backend, judge_verdicts}`` plus, when operator_verdicts is
        supplied, an ``agreement`` block from compute_agreement (n,
        cohens_kappa, spearman_rho, confusion, passes).
    """
    if backend == "stub":
        judge = stub_verdicts(stats)
    elif backend == "openai_compatible":
        judge = openai_verdicts(stats)
    else:
        raise ValueError(
            f"unknown backend: {backend!r} (expected stub|openai_compatible)"
        )

    local = {
        key: {
            "axis": label,
            "judge_verdict": judge.get(key),
            "operator_verdict": (operator_verdicts or {}).get(key),
        }
        for key, label in AXES
    }
    aggregate: dict[str, Any] = {"backend": backend, "judge_verdicts": judge}
    if operator_verdicts:
        rows = [
            (
                key,
                VERDICT_TO_STATUS[judge[key]],
                VERDICT_TO_STATUS[operator_verdicts[key]],
            )
            for key in AXIS_KEYS
            if key in judge and operator_verdicts.get(key) in VERDICT_TO_STATUS
        ]
        aggregate["agreement"] = compute_agreement(rows)
    return local, aggregate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ADR 0060 self-review external judge")
    p.add_argument(
        "--stats", required=True, type=Path,
        help="stats.json from _self_review.py --quarter <Qx-YYYY> --emit-stats",
    )
    p.add_argument(
        "--operator-verdicts", type=Path,
        help='JSON {axis_key: "✓"|"△"|"✗"} — operator''s own committed verdicts',
    )
    p.add_argument(
        "--backend", default="stub", choices=["stub", "openai_compatible"],
        help="stub (deterministic, zero-cost) or openai_compatible (external LLM)",
    )
    p.add_argument(
        "--output", type=Path,
        help="write the (local, aggregate) JSON here (default: stdout)",
    )
    args = p.parse_args(argv)

    try:
        stats = json.loads(args.stats.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"self_review_judge: cannot read stats: {exc}\n")
        return 1
    operator: dict[str, str] | None = None
    if args.operator_verdicts:
        try:
            operator = json.loads(
                args.operator_verdicts.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                f"self_review_judge: cannot read operator verdicts: {exc}\n"
            )
            return 1

    try:
        local, aggregate = judge_self_review(
            stats, operator, backend=args.backend
        )
    except (RuntimeError, ValueError) as exc:
        sys.stderr.write(f"self_review_judge: {exc}\n")
        return 2

    payload = {"local": local, "aggregate": aggregate}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        sys.stdout.write(f"self_review_judge: written to {args.output}\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
