#!/usr/bin/env python3
"""Paired metric primitives for operator-skill eval reports.

ADR 0100 forbids treating the surface as an absolute leaderboard.  The only
primitive here is paired delta: compare two playbooks on the same task set and
report the directional difference plus win/loss/tie counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


# Minimum paired sample size below which a paired delta is reported as a
# directional point estimate only — no bootstrap CI band. ADR 0100 forbids
# absolute leaderboard claims; a CI on n<10 paired tasks would imply a precision
# the surface does not have, so the report attaches an ``underpowered`` flag and
# omits the band instead.
N_MIN_DEFAULT = 10


def underpowered(n: int, *, n_min: int = N_MIN_DEFAULT) -> bool:
    """True iff ``n`` paired samples are below the CI-reporting floor ``n_min``."""

    return n < n_min


@dataclass(frozen=True)
class PairedDelta:
    metric: str
    baseline: str
    candidate: str
    n: int
    baseline_mean: float
    candidate_mean: float
    delta: float
    wins: int
    losses: int
    ties: int

    def to_mapping(self) -> dict[str, int | float | str]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "n": self.n,
            "baseline_mean": self.baseline_mean,
            "candidate_mean": self.candidate_mean,
            "delta": self.delta,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
        }


def paired_delta(
    rows: Iterable[Mapping[str, float | int | bool]],
    *,
    baseline_key: str,
    candidate_key: str,
    metric: str,
    baseline_name: str = "v0_naive",
    candidate_name: str = "v1_spec_first",
) -> PairedDelta:
    """Return same-task candidate-minus-baseline delta.

    Values are coerced to floats; booleans become 0.0/1.0.  Empty inputs are an
    error because a paired delta with ``n=0`` is indistinguishable from an inert
    report surface.
    """

    baseline_values: list[float] = []
    candidate_values: list[float] = []
    wins = losses = ties = 0

    for row in rows:
        if baseline_key not in row or candidate_key not in row:
            missing = sorted({baseline_key, candidate_key} - set(row))
            raise ValueError(f"row missing paired key(s): {missing}")
        base = float(row[baseline_key])
        cand = float(row[candidate_key])
        baseline_values.append(base)
        candidate_values.append(cand)
        if cand > base:
            wins += 1
        elif cand < base:
            losses += 1
        else:
            ties += 1

    n = len(baseline_values)
    if n == 0:
        raise ValueError("paired_delta requires at least one paired row")

    baseline_mean = sum(baseline_values) / n
    candidate_mean = sum(candidate_values) / n
    return PairedDelta(
        metric=metric,
        baseline=baseline_name,
        candidate=candidate_name,
        n=n,
        baseline_mean=round(baseline_mean, 6),
        candidate_mean=round(candidate_mean, 6),
        delta=round(candidate_mean - baseline_mean, 6),
        wins=wins,
        losses=losses,
        ties=ties,
    )
