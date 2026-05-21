#!/usr/bin/env python3
"""External-LLM cross-rating of self-review 5-axis verdicts (ADR 0064).

Reads a self-review ``stats.json`` (from
``scripts/claude-hooks/_self_review.py --quarter <Qx-YYYY> --emit-stats``),
assigns ``✓`` / ``△`` / ``✗`` per collaboration axis via either a
deterministic stub (SKILL.md rubric thresholds) or an external LLM
(``openai_compatible``), then computes inter-rater agreement against the
operator's own verdicts (parsed from ``docs/self-review/Qx-YYYY.md``) using
``eval/judges/judge_agreement.compute_agreement``.

The point (ADR 0064): the self-review rubric is currently graded by the same
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
from collections import Counter
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


# Verdict ↔ JUDGE_STATUSES mapping (ADR 0064). Lets us reuse the existing
# judge_agreement.cohens_kappa / compute_agreement (LABELS = the same 3
# statuses) with only a label translation.
VERDICT_TO_STATUS: dict[str, str] = {
    "✓": "supported",
    "△": "partial",
    "✗": "insufficient",
}
STATUS_TO_VERDICT: dict[str, str] = {v: k for k, v in VERDICT_TO_STATUS.items()}
VALID_VERDICTS: tuple[str, ...] = tuple(VERDICT_TO_STATUS)

# Ordinal rank (✓ > △ > ✗) for distance-weighted Cohen's κ, matching
# judge_agreement._LABEL_RANK. The unweighted κ that compute_agreement returns
# penalises ✓↔△ (adjacent) and ✓↔✗ (opposite) equally — too harsh for an
# ordinal scale, so the agreement block also reports linear- and quadratic-
# weighted κ, which are less extreme when disagreements are mostly adjacent
# (ADR 0064 Verification).
STATUS_RANK: dict[str, int] = {"supported": 2, "partial": 1, "insufficient": 0}

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
        "axis_5": {
            "content_fresh_rate": axis_5.get("fresh_rate"),
            # 5-A index hygiene. ``None`` when the collector did not emit the
            # field (old data) → grade on 5-B alone; a dict (even all-zero)
            # means the collector measured it → SKILL.md count=0 → △ applies.
            "memory_lines": gov.get("memory_lines"),
        },
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
    """ADR 0064 time-separation guard: same-day/unknown evidence downgrades ✓→△.

    Q2-2026's evidence (ADR 0038, hook-fires.log) was produced the *same
    day* the review was written. A ✓ that rests on same-day evidence cannot
    be confirmed, so it is forced to △. ``None`` — the collector emitted no
    datable evidence age — is treated the same way (conservative): a missing
    freshness signal can only ever lower a verdict, never falsely promote one.
    """
    if verdict == "✓" and (
        evidence_age_days is None or evidence_age_days < 1.0
    ):
        return "△"
    return verdict


def stub_verdicts(stats: dict[str, Any]) -> dict[str, str]:
    """Deterministic verdicts straight from SKILL.md thresholds (ADR 0064).

    This is the stub backend — it absorbs what was the standalone
    "deterministic scorer". Three self-pass guards are baked in:

    - ``evidence_age_days < 1.0`` (or ``None``/unmeasured) → ✓ downgraded to △
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

    # axis #5 — memory hygiene = 5-A index hygiene + 5-B content freshness,
    # combined by the SKILL.md dual-sub-signal rule (both ✓ → ✓; any ✗ → ✗;
    # else △). 5-A reads governance_hooks.memory_lines, emitted by the
    # collector as the count of `memory-lines` category fires split by action.
    a5 = sig["axis_5"]

    # 5-B content freshness band.
    fr = a5["content_fresh_rate"]
    if fr is None:
        v5b = "✗"
    elif fr >= 0.5:
        v5b = "✓"
    elif fr >= 0.2:
        v5b = "△"
    else:
        v5b = "✗"

    # 5-A index hygiene. ``None`` = collector did not emit the field (old
    # data) → fall back to 5-B alone (backward-compatible). Otherwise grade:
    # count=0 → △ (측정 부재); blocked≥1 → ✗ (edit refused = index exploded);
    # blocked=0 + aware≤2 → ✓; blocked=0 + aware≥3 → △.
    ml = a5["memory_lines"]
    if ml is None:
        out["axis_5_memory_hygiene"] = v5b
    else:
        aware = int(ml.get("aware", 0) or 0)
        blocked = int(ml.get("blocked", 0) or 0)
        if aware + blocked == 0:
            v5a = "△"
        elif blocked >= 1:
            v5a = "✗"
        elif aware <= 2:
            v5a = "✓"
        else:
            v5a = "△"
        # dual-sub-signal combine
        if v5a == "✓" and v5b == "✓":
            out["axis_5_memory_hygiene"] = "✓"
        elif "✗" in (v5a, v5b):
            out["axis_5_memory_hygiene"] = "✗"
        else:
            out["axis_5_memory_hygiene"] = "△"

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
        "5. memory_hygiene = 5-A index hygiene + 5-B content freshness, "
        "combined (both ✓ → ✓; any ✗ → ✗; else △). "
        "5-B: ✓ if content_fresh_rate ≥0.5; △ if 0.2–0.5; ✗ if <0.2 or null. "
        "5-A from memory_lines {aware, blocked}: if the field is null grade on "
        "5-B alone; else count=aware+blocked=0 → △ (not measured), blocked ≥1 "
        "→ ✗ (index-edit refused), blocked=0 and aware ≤2 → ✓, blocked=0 and "
        "aware ≥3 → △.\n\n"
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


def _weighted_kappa(
    judge_statuses: list[str], human_statuses: list[str], *, mode: str
) -> float:
    """Distance-weighted Cohen's κ over the ordinal STATUS_RANK scale.

    ``mode`` is ``"linear"`` (disagreement weight |i-j|/(k-1)) or
    ``"quadratic"`` ((i-j)²/(k-1)²), k=3. Adjacent disagreements (✓↔△) cost
    less than opposite ones (✓↔✗) — unlike the unweighted κ. Returns NaN when
    the expected disagreement is zero (no marginal spread).
    """
    n = len(judge_statuses)
    if n == 0:
        return float("nan")
    jr = [STATUS_RANK[s] for s in judge_statuses]
    hr = [STATUS_RANK[s] for s in human_statuses]
    cats = (0, 1, 2)

    def weight(i: int, j: int) -> float:
        dist = abs(i - j)
        return dist / 2.0 if mode == "linear" else (dist * dist) / 4.0

    cj, ch = Counter(jr), Counter(hr)
    observed: dict[tuple[int, int], int] = {}
    for a, b in zip(jr, hr):
        observed[(a, b)] = observed.get((a, b), 0) + 1
    num = sum(weight(i, j) * observed.get((i, j), 0) for i in cats for j in cats)
    den = sum(weight(i, j) * cj[i] * ch[j] / n for i in cats for j in cats)
    if num == 0:
        # All observations on the diagonal → perfect agreement. Mirrors
        # cohens_kappa's observed>=1.0 special case (avoids 0/0 when there
        # is no marginal spread, e.g. both raters all-✓).
        return 1.0
    if den == 0:
        return float("nan")
    return 1.0 - num / den


def _validate_operator_verdicts(operator_verdicts: object) -> None:
    """Reject an operator verdict file that isn't exactly the 5 valid axes.

    ADR 0064's agreement gate is only meaningful when every axis is rated by
    *both* raters. A file missing an axis (or with a typo'd / out-of-vocab
    value) used to silently shrink the row set; a single surviving diagonal
    row (n=1) then hit ``compute_agreement``'s perfect-agreement special case
    (κ=1.0, passes=True) — defeating the external-anchor purpose. Validate at
    this boundary (the operator JSON is an external input) so one parse
    mistake fails loudly instead of passing the gate with axes unverified.
    """
    if not isinstance(operator_verdicts, dict):
        raise ValueError(
            "operator verdicts must be a JSON object, got "
            f"{type(operator_verdicts).__name__}"
        )
    keys = set(operator_verdicts)
    expected = set(AXIS_KEYS)
    if keys != expected:
        raise ValueError(
            "operator verdicts must cover exactly the 5 axes "
            f"(missing={sorted(expected - keys)}, extra={sorted(keys - expected)})"
        )
    bad = {
        k: v for k, v in operator_verdicts.items() if v not in VERDICT_TO_STATUS
    }
    if bad:
        raise ValueError(
            "operator verdicts have invalid values (must be one of "
            f"{VALID_VERDICTS}): {bad}"
        )


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
        cohens_kappa, spearman_rho, confusion, passes) augmented with
        weighted_kappa_linear / weighted_kappa_quadratic (ordinal).
    """
    # Validate the operator JSON *before* dispatching the backend so an
    # invalid file fails fast (no wasted openai call) — and so a parse
    # mistake can never reach the agreement gate (see _validate_operator_verdicts).
    if operator_verdicts is not None:
        _validate_operator_verdicts(operator_verdicts)

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
    if operator_verdicts is not None:
        # operator_verdicts is validated to span exactly AXIS_KEYS with
        # in-vocab values, and the backend always emits all 5 axes, so rows
        # span all 5 — n == len(AXIS_KEYS), never a silently truncated set.
        rows = [
            (
                key,
                VERDICT_TO_STATUS[judge[key]],
                VERDICT_TO_STATUS[operator_verdicts[key]],
            )
            for key in AXIS_KEYS
        ]
        agreement = compute_agreement(rows)
        # Augment the (unweighted) compute_agreement output with ordinal
        # distance-weighted κ. The `passes` gate stays on the unweighted κ
        # (ADR 0016 convention); weighted κ is reported for honesty on the
        # ordinal ✓>△>✗ scale (ADR 0064 Verification).
        judge_statuses = [r[1] for r in rows]
        human_statuses = [r[2] for r in rows]
        agreement["weighted_kappa_linear"] = _weighted_kappa(
            judge_statuses, human_statuses, mode="linear"
        )
        agreement["weighted_kappa_quadratic"] = _weighted_kappa(
            judge_statuses, human_statuses, mode="quadratic"
        )
        aggregate["agreement"] = agreement
    return local, aggregate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ADR 0064 self-review external judge")
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
