#!/usr/bin/env python3
"""Fail-closed verdict logic for the ADR 0100 operator-skill eval surface.

This module is repo-agnostic and stdlib-only on purpose: the verdict decision is
the load-bearing correctness contract of the surface, so it is kept fully
unit-testable with no subprocess, numpy, RAG, eval, or api imports.  The BidMate
adapter (``adapters/bidmate/oracle_bidmate.py``) is the only place that runs real
gates / external reviewers and it feeds *already-sanitized* booleans into the
functions here.

Two independent privacy gates guard the ACCEPTED tier, and BOTH default to
fail-closed — a missing, private, or same-family reviewer can never yield
``ACCEPTED``:

1. **Public-attestation egress gate.** Acceptance requires a cross-family
   reviewer to actually see the candidate payload (issue + patch).  That payload
   is private by default (ADR 0005), so it may only leave the boundary when the
   operator has explicitly opted into public attestation.  When
   ``public_attestation`` is False, ``decide_verdict`` can climb no higher than
   ``NECESSARY_GATE_ONLY`` regardless of what reviewer object is passed in — the
   egress never happened, so there is nothing valid to accept on.

2. **Cross-family validity gate (ADR 0064).** Even with egress open, a reviewer
   from the *same* model family as the candidate is a self-judge and is
   neutralized: its verdict is discarded and the tier caps at
   ``NECESSARY_GATE_ONLY``.  Only a genuinely cross-family reviewer's
   ``accepted`` flag can move the tier to ``ACCEPTED`` (or, if it rejects, to
   ``REJECTED_BY_REVIEWER``).

The hard-gate and necessary-gate checks run *before* either privacy gate, so a
build failure / secret leak / destructive change is rejected outright and a
candidate that fails the hidden test / pytest / regression gates is rejected
before acceptance is ever considered.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class HardGate(enum.Enum):
    """Categorical non-recoverable failures that reject a candidate outright."""

    BUILD_FAILURE = "build_failure"
    SECRET_LEAK = "secret_leak"
    DESTRUCTIVE = "destructive"
    UNRELATED_REWRITE = "unrelated_rewrite"
    INSTRUCTION_VIOLATION = "instruction_violation"
    UNAUTHORIZED_MIGRATION = "unauthorized_migration"


class VerdictTier(enum.Enum):
    """Ordered outcome tiers for a single candidate run.

    ``ACCEPTED`` is the only tier that counts as a solved task (see
    ``is_accepted``).  ``NECESSARY_GATE_ONLY`` means the candidate passed every
    objective necessary gate but could not earn acceptance because the
    cross-family reviewer was unavailable, egress was closed, or the reviewer was
    same-family — it is a fail-closed cap, not a success.
    """

    ACCEPTED = "accepted"
    REJECTED_BY_REVIEWER = "rejected_by_reviewer"
    NECESSARY_GATE_ONLY = "necessary_gate_only"
    REJECTED_NECESSARY_GATE = "rejected_necessary_gate"
    REJECTED_HARD_GATE = "rejected_hard_gate"


@dataclass(frozen=True)
class GateResults:
    """Objective, already-evaluated gate outcomes for one candidate run.

    Only booleans / categorical hard-gate members are carried here; raw command
    output (stdout/stderr, diffs) is deliberately *not* part of this structure so
    it can never reach a committed report.
    """

    hidden_test_gate: bool
    pytest_pass: bool
    regression_pass: bool
    hard_gates: tuple[HardGate, ...] = ()


@dataclass(frozen=True)
class ReviewerVerdict:
    """A cross-family reviewer's sanitized verdict.

    ``reason_code`` is a SHORT enum-like token (for example ``ok``,
    ``contract_violation``, ``missing_test``), NEVER free-form reviewer prose.
    Keeping it a token is what lets the verdict travel into an aggregate report
    without smuggling raw review text past the ADR 0005 boundary.
    """

    accepted: bool
    reviewer_family: str
    reason_code: str


def _normalize_family(family: object) -> str:
    """Canonicalize a model-family label for the self-judge comparison.

    Family labels are expected to be short canonical tokens (``codex``,
    ``claude``).  This collapses cosmetic variants — surrounding whitespace and
    letter case — so that ``'Codex'``, ``' codex '`` and ``'codex'`` all compare
    equal.

    The canonical token is derived with the UNBOUND base ``str`` methods
    (``str.lower(str.strip(family))``), NOT ``str(family)`` or
    ``family.strip().lower()``.  A ``str`` *subclass* can override ``__str__`` /
    ``strip`` / ``lower`` to return a spoofed value — e.g. a ``SpoofStr('codex')``
    whose ``__str__`` returns ``'claude'`` — which would make a same-family label
    read as cross-family and slip past the self-judge gate.  The unbound base
    methods operate on the real character buffer and ignore any subclass override,
    so the real value (``'codex'``) is always used.  Non-``str`` input (already
    rejected upstream by ``_is_valid_family``) normalizes to ``''`` defensively.
    Alias / substring and unicode-homoglyph matching are intentionally OUT OF
    SCOPE: only exact post-normalization equality counts (labels are trusted
    canonical tokens, not attacker free-text).
    """

    if not isinstance(family, str):
        return ""
    return str.lower(str.strip(family))


def _is_same_family(reviewer_family: object, candidate_family: object) -> bool:
    """True iff the two family labels are the same after normalization."""

    return _normalize_family(reviewer_family) == _normalize_family(candidate_family)


def _is_valid_family(family: object) -> bool:
    """True iff ``family`` is a usable canonical family label.

    Family labels are TRUSTED internal tokens set by the harness / adapter (never
    candidate-controlled free text), so this is a robustness guard against a
    MISCONFIGURED caller, not an adversarial-input filter.  A valid label must be a
    ``str`` that is non-empty after stripping.  A non-``str`` label is rejected
    rather than ``str()``-coerced, because coercing e.g. ``b'codex'`` yields the
    repr ``"b'codex'"`` which would spuriously read as cross-family and bypass the
    same-family self-judge gate.  Unicode-homoglyph / alias matching is out of
    scope (labels are canonical tokens, not attacker text).
    """

    # Unbound base ``str.strip`` so a subclass that overrides ``strip`` cannot
    # spoof emptiness; see _normalize_family for the full rationale.
    return isinstance(family, str) and str.strip(family) != ""


def decide_verdict(
    gates: GateResults,
    reviewer: "ReviewerVerdict | None",
    *,
    candidate_family: str,
    public_attestation: bool,
) -> VerdictTier:
    """Map gate + reviewer state to a verdict tier with a fixed, fail-closed order.

    The decision table is evaluated top to bottom; the first matching rule wins:

    1. any hard gate  -> ``REJECTED_HARD_GATE``
    2. any necessary gate not strictly ``True`` -> ``REJECTED_NECESSARY_GATE``
    3. necessary gates all pass; acceptance needs a VALID cross-family reviewer:
       a. egress not strictly opened (``public_attestation is not True``)
          -> ``NECESSARY_GATE_ONLY``
       b. reviewer is ``None`` (unavailable/skipped)  -> ``NECESSARY_GATE_ONLY``
       c. same-family reviewer (ADR 0064 self-judge)  -> ``NECESSARY_GATE_ONLY``
       d. cross-family reviewer did not strictly accept -> ``REJECTED_BY_REVIEWER``
       e. cross-family reviewer strictly accepted -> ``ACCEPTED``

    Every gate that could OPEN the path to ``ACCEPTED`` is checked with a strict
    ``is True`` (or an explicit family match), never Python truthiness.  This is
    deliberate: the gate / attestation / accepted fields are *typed* as booleans,
    but a malformed caller that passes a truthy non-bool (e.g. the string
    ``"false"``) must not be able to slip past a necessary or privacy gate.
    Truthiness here would be fail-OPEN; ``is True`` keeps every opener fail-closed.
    """

    # Any TRUTHY hard_gates value rejects outright — a real ``(HardGate.…,)`` tuple,
    # or even a malformed truthy value (fail closed). Only a FALSY value (the
    # default ``()``, or None / 0 / False) means "no hard gate detected", which is
    # the clean common case and correctly falls through to the gates below.
    if gates.hard_gates:
        return VerdictTier.REJECTED_HARD_GATE
    necessary_gates_pass = (
        gates.hidden_test_gate is True
        and gates.pytest_pass is True
        and gates.regression_pass is True
    )
    if not necessary_gates_pass:
        return VerdictTier.REJECTED_NECESSARY_GATE
    # Necessary gates all pass — now the two fail-closed privacy gates. Each
    # opener requires a STRICT True / explicit cross-family match so a non-bool
    # or cosmetic-variant value can never fail open into ``ACCEPTED``.
    if public_attestation is not True:
        # Egress gate closed unless strictly opted into: the payload may not
        # leave the boundary, so no cross-family reviewer could have seen it and
        # acceptance is barred.
        return VerdictTier.NECESSARY_GATE_ONLY
    if reviewer is None:
        # Reviewer unavailable/skipped — fail closed, never accept on absence.
        return VerdictTier.NECESSARY_GATE_ONLY
    if not (_is_valid_family(reviewer.reviewer_family) and _is_valid_family(candidate_family)):
        # A valid cross-family reviewer needs BOTH labels to be usable canonical
        # strings. A non-str label (e.g. bytes ``b'codex'``, whose ``str()`` is the
        # repr ``"b'codex'"``) or an empty/whitespace label cannot establish
        # cross-family validity, so fail closed rather than let it read as
        # "different" and slip past the same-family self-judge gate.
        return VerdictTier.NECESSARY_GATE_ONLY
    if _is_same_family(reviewer.reviewer_family, candidate_family):
        # Same-family self-judge is invalid (ADR 0064): neutralize the verdict.
        # The comparison is case/whitespace-insensitive so a cosmetic variant
        # such as 'Codex' cannot bypass a 'codex' candidate's self-judge gate.
        return VerdictTier.NECESSARY_GATE_ONLY
    if reviewer.accepted is True:
        return VerdictTier.ACCEPTED
    # Reviewer present and cross-family but did not strictly accept (an explicit
    # rejection, or a malformed non-True ``accepted`` flag) — fail closed to a
    # reviewer rejection rather than letting a truthy non-bool reach ACCEPTED.
    return VerdictTier.REJECTED_BY_REVIEWER


def is_accepted(tier: VerdictTier) -> bool:
    """True iff ``tier`` is the single success tier (``ACCEPTED``)."""

    return tier is VerdictTier.ACCEPTED
