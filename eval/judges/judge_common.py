"""Shared utilities for BidMate-DocAgent LLM-judge surfaces.

Extracted from the three judge surface files per ADR 0012 *Alternatives*:

    *"If a third judge surface appears, revisit and extract
    eval/judge_common.py."*

Three surfaces now exist:

* ``scripts/llm_judge.py``   — Gate 1: real-data (ADR 0006)
* ``eval/synthetic_judge.py`` — Gate 2: synthetic stub-default (ADR 0012)
* ``eval/llm_judge.py``       — Gate 3: RAGAS enrichment (ADR 0014)

All three import from here. Nothing outside the judge surfaces should
import this module — it is an implementation helper, not part of the
pipeline contract.

Shared items
------------
:data:`JUDGE_STATUSES`
    Three-value status vocabulary shared by Gate 1 and Gate 2.
:data:`EVIDENCE_BOUNDARY`
    Re-exported from ``rag_core`` so surface files need only one import.
:func:`clamp_score`
    Clamp a numeric value to ``[0.0, 1.0]``.
:func:`extract_summary`
    Pull the answer-summary string from an eval_summary case dict.
:func:`build_evidence_block`
    Build the evidence block string used in every judge prompt.
:func:`build_openai_client`
    Construct an OpenAI-compatible client from env vars (lazy SDK import).
:func:`get_judge_model`
    Read and validate ``BIDMATE_JUDGE_MODEL`` from the environment.
:func:`call_openai_json`
    Call an OpenAI-compatible endpoint and return a parsed JSON dict.
:func:`normalize_status_verdict`
    Normalise a raw backend payload into the Gate 1/2 verdict schema.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from rag_core import EVIDENCE_BOUNDARY, neutralize_instruction_patterns

if TYPE_CHECKING:  # pragma: no cover
    pass  # kept for future type-only imports

__all__ = [
    "JUDGE_STATUSES",
    "EVIDENCE_BOUNDARY",
    "clamp_score",
    "extract_summary",
    "build_evidence_block",
    "build_openai_client",
    "get_judge_model",
    "call_openai_json",
    "normalize_status_verdict",
]

# Three-value status vocabulary shared by Gate 1 (scripts/llm_judge.py) and
# Gate 2 (eval/synthetic_judge.py).  Gate 3 uses continuous RAGAS metrics
# instead and does not import this constant.
JUDGE_STATUSES: tuple[str, ...] = ("supported", "partial", "insufficient")


# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------


def clamp_score(value: Any) -> float:
    """Clamp *value* to ``[0.0, 1.0]``; return ``0.0`` on parse failure.

    Handles ``None``, non-numeric strings, ``float("nan")``, and values
    outside the unit interval uniformly so callers do not need to guard.
    """
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score != score:  # NaN check without importing math
        return 0.0
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Case-dict helpers
# ---------------------------------------------------------------------------


def extract_summary(case: dict[str, Any]) -> str:
    """Extract the answer-summary string from an eval_summary case dict.

    Handles both the ADR 0003 structured answer dict (``answer.summary``)
    and the older flat string form (``answer`` or ``answer_text``).
    """
    answer = case.get("answer")
    if isinstance(answer, dict):
        return str(answer.get("summary") or "")
    return str(answer or case.get("answer_text") or "")


def build_evidence_block(
    case: dict[str, Any],
    *,
    max_chunks: int = 3,
    max_chars: int = 600,
) -> str:
    """Build the evidence block string used in judge prompts.

    Applies :func:`~rag_core.neutralize_instruction_patterns` to each
    chunk (ADR 0008 evidence-side injection defence) and joins with
    :data:`EVIDENCE_BOUNDARY`.  Returns the literal string
    ``"(no evidence)"`` when the case has no evidence items.

    Args:
        case: One entry from ``eval_summary.json["case_results"]``.
        max_chunks: Maximum number of evidence chunks to include.
        max_chars: Maximum characters per chunk before injection defence.
    """
    evidence_items = case.get("evidence") or []
    lines: list[str] = []
    for i, item in enumerate(evidence_items[:max_chunks], start=1):
        raw = (item.get("text") if isinstance(item, dict) else "") or ""
        lines.append(f"[{i}] {neutralize_instruction_patterns(raw[:max_chars])}")
    return EVIDENCE_BOUNDARY.join(lines) or "(no evidence)"


# ---------------------------------------------------------------------------
# OpenAI-compatible backend helpers
# ---------------------------------------------------------------------------


def build_openai_client() -> Any:  # returns openai.OpenAI at runtime
    """Construct an OpenAI-compatible client from environment variables.

    Lazily imports the ``openai`` SDK so stub-only test paths carry no
    SDK dependency.

    Environment variables
    ~~~~~~~~~~~~~~~~~~~~~
    ``BIDMATE_JUDGE_API_KEY``
        Required.  The API key for the judge endpoint.
    ``BIDMATE_JUDGE_MODEL``
        Required.  Validated here for fast failure rather than at call
        time — avoids a wasted network round-trip on a missing model name.
    ``BIDMATE_JUDGE_BASE_URL``
        Optional.  Custom base URL (e.g. ``https://api.anthropic.com/v1``
        for Anthropic-Compat, or a local vLLM/llama.cpp server).

    Raises:
        RuntimeError: SDK not installed, or a required env var is absent.
    """
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "openai_compatible backend requires the openai SDK. "
            "Install with `pip install openai` or use the stub backend."
        ) from exc

    api_key = os.environ.get("BIDMATE_JUDGE_API_KEY")
    if not api_key:
        raise RuntimeError("BIDMATE_JUDGE_API_KEY is not set.")
    model = os.environ.get("BIDMATE_JUDGE_MODEL")
    if not model:
        raise RuntimeError("BIDMATE_JUDGE_MODEL is not set.")
    base_url = os.environ.get("BIDMATE_JUDGE_BASE_URL") or None
    return OpenAI(api_key=api_key, base_url=base_url)


def get_judge_model() -> str:
    """Read and validate ``BIDMATE_JUDGE_MODEL`` from the environment.

    Returns the model name.  Raises :class:`RuntimeError` when not set
    so callers get a clear message rather than a ``None`` passed to the
    SDK.
    """
    model = os.environ.get("BIDMATE_JUDGE_MODEL")
    if not model:
        raise RuntimeError("BIDMATE_JUDGE_MODEL is not set.")
    return model


def call_openai_json(
    client: Any,
    model: str,
    prompt: str,
) -> dict[str, Any] | None:
    """Call an OpenAI-compatible endpoint and return a parsed JSON dict.

    Uses ``temperature=0.0`` and ``response_format={"type": "json_object"}``
    for deterministic, structured output.

    Args:
        client: An ``openai.OpenAI`` instance (from :func:`build_openai_client`).
        model: Model identifier string (e.g. ``"claude-sonnet-4-5"``).
        prompt: The full judge prompt string.

    Returns:
        Parsed JSON dict on success (may be empty ``{}`` if the model
        returned ``{}``) or ``None`` when the model returned non-JSON
        content.  Callers must check for ``None`` to distinguish a
        JSON-decode failure from a legitimately empty-object response —
        treating ``{}`` as a fallback input to :func:`normalize_status_verdict`
        allows the verifier's own status to be used, which is the desired
        graceful-degradation behaviour (ADR 0004 / PR #218).
    """
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Status-verdict normalisation (Gate 1 + Gate 2)
# ---------------------------------------------------------------------------


def normalize_status_verdict(
    payload: dict[str, Any],
    fallback_status: str,
) -> dict[str, Any]:
    """Normalise a raw backend payload into the Gate 1/2 verdict schema.

    Used by :mod:`scripts.llm_judge` (Gate 1, real-data) and
    :mod:`eval.synthetic_judge` (Gate 2, synthetic stub-default).
    Gate 3 (:mod:`eval.llm_judge`) uses continuous RAGAS metrics and
    does **not** call this function.

    Args:
        payload: Parsed JSON dict from the backend.
        fallback_status: The verifier's own status string, used when the
            model returns an unrecognised or missing ``judge_status``.

    Returns:
        Dict with guaranteed keys ``judge_status``, ``judge_grounded``,
        ``judge_reason_short``.  When *payload* includes ``faithfulness``
        or ``answer_relevance`` (Gate 2 extension), those values are
        clamped and forwarded.
    """
    status = str(payload.get("judge_status") or "").strip().lower()
    if status not in JUDGE_STATUSES:
        status = (
            fallback_status if fallback_status in JUDGE_STATUSES else "insufficient"
        )
    grounded = bool(payload.get("judge_grounded", False))
    reason = str(payload.get("judge_reason_short") or "")[:200]
    out: dict[str, Any] = {
        "judge_status": status,
        "judge_grounded": grounded,
        "judge_reason_short": reason,
    }
    # Gate 2 (synthetic_judge) appends RAGAS 2-metric scores to the same
    # verdict dict.  Forward them when present so this helper is usable
    # by both gates without a separate normalisation step.
    for key in ("faithfulness", "answer_relevance"):
        if key in payload:
            out[key] = clamp_score(payload[key])
    return out
