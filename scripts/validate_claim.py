#!/usr/bin/env python3
"""Validate improvement claims in a PR body against paired bootstrap CI.

PR-body convention introduced by ADR 0055:

    Claim: <metric>=<+X.Xpp>
    Claim: accuracy=+4.0pp
    Claim: groundedness=-2.5pp     # negative claims also validated

Each ``Claim:`` line is grepped, the per-case ``<metric>`` arrays are pulled
from base / candidate ``eval_summary.json`` (same files compare_eval.py
consumes in pr-eval.yml), paired by ``case_id``, ``None`` pairs are dropped
(ADR 0054 conditional-on-substantive-answer semantics — quality metrics are
``None`` on unanswerable+abstained+no-evidence path), then
``eval.bootstrap.paired_bootstrap_ci`` (PR #950) computes the CI.

A claim PASSES iff ALL four:

    1. CI excludes 0 (lo and hi same sign)
    2. effective sample size (post-None-skip) >= ``--min-sample``
    3. sign(claim) == sign(mean_diff)
    4. |claim| <= |upper-CI bound when claim>0|  OR  |claim| <= |lower-CI bound when claim<0|
       (i.e. claim does not exceed the optimistic edge of the CI)

ALLOW_OVERCLAIM is intentionally NOT introduced — statistical honesty is not
escaped per ADR 0055 §Consequences.

CLI:

    python3 scripts/validate_claim.py \\
        --pr-body /tmp/pr-body.txt \\
        --baseline base/reports/eval_summary.json \\
        --candidate pr/reports/eval_summary.json \\
        --min-sample 200 [--alpha 0.05]

Exit code 0 if all claims pass; non-zero (and a per-claim failure report on
stderr) if any claim fails. If no ``Claim:`` line is present, exits 0 with a
"no claims" stdout line — CI step uses ``if: contains(pr.body, 'Claim:')`` to
skip in that case but the script tolerates the no-op invocation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.bootstrap import DEFAULT_ALPHA, paired_bootstrap_ci  # noqa: E402

# Regex: ``Claim:`` must start a line (multi-line mode). Metric is an identifier;
# sign is mandatory; value is decimal; unit is ``pp`` (percentage points).
# Anchored to ``$`` (line end) so trailing comments require a separator first.
CLAIM_PATTERN = re.compile(
    r"^Claim:\s+(?P<metric>\w+)\s*=\s*(?P<sign>[+-])(?P<value>[\d.]+)pp\s*$",
    re.MULTILINE,
)

# Code-fence detection: skip Claim: lines inside ```...``` blocks to avoid
# accidentally validating example/illustrative claims in docs PR bodies.
FENCE_PATTERN = re.compile(r"^```", re.MULTILINE)


def parse_claims(pr_body: str) -> list[dict[str, Any]]:
    """Return list of {metric, sign, value, line_no} for each Claim: line
    OUTSIDE code fences. Empty list if none found.
    """
    # Build set of line indices inside any fenced block (toggle on each ```).
    fenced: set[int] = set()
    in_fence = False
    for idx, line in enumerate(pr_body.splitlines()):
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            fenced.add(idx)

    claims: list[dict[str, Any]] = []
    for match in CLAIM_PATTERN.finditer(pr_body):
        # Compute the line number of this match (0-indexed).
        line_no = pr_body.count("\n", 0, match.start())
        if line_no in fenced:
            continue
        claims.append(
            {
                "metric": match.group("metric"),
                "sign": match.group("sign"),
                "value": float(match.group("value")),
                "line_no": line_no + 1,  # 1-indexed for human reporting
            }
        )
    return claims


def _load_case_results(path: Path) -> list[dict[str, Any]]:
    """Load ``case_results`` from an ``eval_summary.json``-shape file. Aggregate
    files (e.g. ``baseline.aggregate.json``) strip ``case_results``; this fn
    raises if the field is missing — caller must point to the per-case file.
    """
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    cr = payload.get("case_results")
    if cr is None:
        raise ValueError(
            f"{path} has no 'case_results' — pass an eval_summary.json (full schema), "
            f"not a *.aggregate.json (per-ADR-0005 the aggregate strips per-case data)."
        )
    return cr


def paired_metric_arrays(
    baseline_cr: list[dict[str, Any]],
    candidate_cr: list[dict[str, Any]],
    metric: str,
) -> tuple[list[float], list[float], int]:
    """Pair baseline and candidate case_results by ``case_id``, drop pairs
    where EITHER side is ``None`` for ``metric`` (ADR 0054 substantive-only
    semantics), return (baseline_values, candidate_values, effective_n).
    """
    base_by_id = {str(c.get("case_id") or c.get("id")): c for c in baseline_cr}
    cand_by_id = {str(c.get("case_id") or c.get("id")): c for c in candidate_cr}
    common_ids = sorted(set(base_by_id.keys()) & set(cand_by_id.keys()))
    a: list[float] = []
    b: list[float] = []
    for cid in common_ids:
        bv = base_by_id[cid].get(metric)
        cv = cand_by_id[cid].get(metric)
        if bv is None or cv is None:
            continue
        a.append(float(bv))
        b.append(float(cv))
    return a, b, len(a)


def validate_one_claim(
    claim: dict[str, Any],
    baseline_cr: list[dict[str, Any]],
    candidate_cr: list[dict[str, Any]],
    *,
    min_sample: int,
    alpha: float,
) -> tuple[bool, str]:
    """Return (passed, message). Message describes the outcome."""
    metric = claim["metric"]
    sign = claim["sign"]
    value_pp = claim["value"]  # in percentage points
    claim_signed = value_pp if sign == "+" else -value_pp

    a, b, n = paired_metric_arrays(baseline_cr, candidate_cr, metric)
    if n == 0:
        return False, (
            f"metric={metric!r}: no paired non-None cases — metric absent from "
            f"case_results or all pairs filtered (ADR 0054)."
        )
    if n < min_sample:
        return False, (
            f"metric={metric!r}: effective n={n} < min_sample={min_sample}. "
            f"Claim cannot be validated at this sample size."
        )

    # paired_bootstrap_ci computes ``values_a - values_b``. Pass (candidate, baseline)
    # so mean_diff = candidate - baseline → positive = improvement (matches Claim: sign).
    ci = paired_bootstrap_ci(b, a, alpha=alpha)
    if ci is None:
        return False, f"metric={metric!r}: paired_bootstrap_ci returned None unexpectedly (n={n})."

    # mean_diff is candidate - baseline expressed as a fraction. Convert to pp.
    mean_diff_pp = ci["mean_diff"] * 100.0
    ci_lo_pp = ci["ci_lo"] * 100.0
    ci_hi_pp = ci["ci_hi"] * 100.0

    # Check 1: CI excludes 0
    if ci_lo_pp <= 0 <= ci_hi_pp:
        return False, (
            f"metric={metric!r}: CI=({ci_lo_pp:+.3f}pp, {ci_hi_pp:+.3f}pp) crosses 0 "
            f"(n={n}). Improvement claim ({sign}{value_pp}pp) is not statistically "
            f"distinguishable from no change."
        )

    # Check 2: sign(claim) == sign(mean_diff)
    if (claim_signed > 0) != (mean_diff_pp > 0):
        return False, (
            f"metric={metric!r}: claim sign={sign} but observed mean_diff="
            f"{mean_diff_pp:+.3f}pp (n={n}). Direction mismatch."
        )

    # Check 3: |claim| <= optimistic CI edge
    # For positive claim, optimistic edge = ci_hi_pp (larger improvement).
    # For negative claim, optimistic edge = ci_lo_pp (more negative).
    optimistic_edge = ci_hi_pp if claim_signed > 0 else ci_lo_pp
    if abs(claim_signed) > abs(optimistic_edge):
        return False, (
            f"metric={metric!r}: claim |{sign}{value_pp}pp| exceeds optimistic CI edge "
            f"|{optimistic_edge:+.3f}pp| (n={n}, CI=({ci_lo_pp:+.3f}, {ci_hi_pp:+.3f})). "
            f"Over-claim — adjust to within CI or remove."
        )

    return True, (
        f"metric={metric!r}: PASS — claim {sign}{value_pp}pp consistent with "
        f"mean_diff={mean_diff_pp:+.3f}pp CI=({ci_lo_pp:+.3f}, {ci_hi_pp:+.3f}) n={n}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr-body", type=Path, required=True, help="Path to file containing PR body text.")
    parser.add_argument("--baseline", type=Path, required=True, help="Path to baseline eval_summary.json (full schema).")
    parser.add_argument("--candidate", type=Path, required=True, help="Path to candidate eval_summary.json.")
    parser.add_argument("--min-sample", type=int, default=200, help="Minimum effective sample size (post-None-skip).")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA, help="Significance level for CI (default 0.05 → 95%% CI).")
    args = parser.parse_args(argv)

    pr_body = args.pr_body.read_text(encoding="utf-8")
    claims = parse_claims(pr_body)
    if not claims:
        print("no Claim: lines found in PR body — skip")
        return 0

    print(f"found {len(claims)} claim(s) in PR body:")
    for c in claims:
        print(f"  line {c['line_no']}: {c['metric']}={c['sign']}{c['value']}pp")

    baseline_cr = _load_case_results(args.baseline)
    candidate_cr = _load_case_results(args.candidate)

    failures = 0
    for c in claims:
        passed, msg = validate_one_claim(
            c, baseline_cr, candidate_cr, min_sample=args.min_sample, alpha=args.alpha
        )
        stream = sys.stdout if passed else sys.stderr
        prefix = "PASS" if passed else "FAIL"
        print(f"  [{prefix}] {msg}", file=stream)
        if not passed:
            failures += 1

    if failures:
        print(f"\n{failures}/{len(claims)} claim(s) failed validation.", file=sys.stderr)
        return 1
    print(f"\nall {len(claims)} claim(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
