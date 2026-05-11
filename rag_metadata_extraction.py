"""LLM-driven RFP metadata extraction (issue #180, ADR 0017).

Adds an *additive* extraction path that asks Claude (or an OpenAI-
compatible endpoint) to read the raw body text and return a strict
JSON metadata payload via tool / function calling. The regex /
``ingestion.normalize_metadata`` baseline stays the deterministic
default per ADR 0001; this module is opt-in and never replaces it.

Backends (``BIDMATE_METADATA_BACKEND``):

* ``regex`` — deterministic regex / CSV-column passthrough. The
  ADR 0001 invariant; the default if nothing is set.
* ``stub`` — also deterministic, also offline. Delegates to
  ``regex`` so the stub-matches-baseline contract is a unit test.
  Used by default test fixtures and by users without an API key.
* ``anthropic_tool_use`` — Claude API with the
  ``extract_rfp_metadata`` tool. Requires ``ANTHROPIC_API_KEY``.
  ``BIDMATE_METADATA_MODEL`` overrides the model id.
* ``openai_function_call`` — generic OpenAI-compatible endpoint
  (vLLM / llama.cpp / OpenAI / Solar / ...). Reads
  ``BIDMATE_METADATA_API_KEY``, ``BIDMATE_METADATA_MODEL``,
  ``BIDMATE_METADATA_BASE_URL``.

``extract_rfp_metadata`` never raises out to the pipeline — on any
backend exception it returns the regex baseline so metadata is
never silently lost.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any


METADATA_SCHEMA_VERSION = 1
ENV_BACKEND = "BIDMATE_METADATA_BACKEND"
ENV_MODEL = "BIDMATE_METADATA_MODEL"
ENV_API_KEY = "BIDMATE_METADATA_API_KEY"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_BASE_URL = "BIDMATE_METADATA_BASE_URL"
ENV_MAX_TOKENS = "BIDMATE_METADATA_MAX_TOKENS"

DEFAULT_BACKEND = "regex"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024
TEXT_CHAR_LIMIT = 8000  # truncate body text before sending to an LLM


FIELD_NAMES: tuple[str, ...] = (
    "agency",
    "project_name",
    "budget_amount",
    "budget_currency",
    "deadline_iso",
    "submission_date_iso",
    "contact_email",
    "contact_name",
)


@dataclass
class MetadataExtraction:
    """Eight-field schema produced by every backend (issue #180)."""

    agency: str | None = None
    project_name: str | None = None
    budget_amount: float | None = None
    budget_currency: str | None = None
    deadline_iso: str | None = None  # YYYY-MM-DD
    submission_date_iso: str | None = None  # YYYY-MM-DD
    contact_email: str | None = None
    contact_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


TOOL_DEFINITION: dict[str, Any] = {
    "name": "extract_rfp_metadata",
    "description": (
        "Extract structured metadata from a Korean RFP "
        "(Request-For-Proposal) document body. Fill only the fields "
        "the document explicitly states; omit (do not invent) any "
        "field the document does not state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agency": {
                "type": "string",
                "description": "Issuing agency / 발주 기관 short name (한글 가능).",
            },
            "project_name": {
                "type": "string",
                "description": "Project title / 사업명.",
            },
            "budget_amount": {
                "type": "number",
                "description": (
                    "Budget amount as a number — no currency suffix, "
                    "no commas, no '원' or '만원' marker."
                ),
            },
            "budget_currency": {
                "type": "string",
                "description": "ISO 4217 currency code (KRW, USD, ...).",
            },
            "deadline_iso": {
                "type": "string",
                "description": "Application/bid deadline in ISO date (YYYY-MM-DD).",
            },
            "submission_date_iso": {
                "type": "string",
                "description": "Required submission date in ISO date (YYYY-MM-DD).",
            },
            "contact_email": {
                "type": "string",
                "description": "Primary contact email address.",
            },
            "contact_name": {
                "type": "string",
                "description": "Primary contact person (한글 또는 영문).",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}


SYSTEM_PROMPT = (
    "You extract structured metadata from a Korean RFP "
    "(Request-For-Proposal) document. Be conservative: fill a field "
    "only when the document text explicitly states the value. Omit "
    "any field the document does not state — do not infer, guess, or "
    "carry information across fields. Always call extract_rfp_metadata."
)


def _resolve_backend() -> str:
    return os.environ.get(ENV_BACKEND, DEFAULT_BACKEND).strip().lower()


def extract_rfp_metadata(
    document: dict[str, Any],
    *,
    backend: str | None = None,
) -> MetadataExtraction:
    """Extract metadata from one ``document`` payload.

    The document is expected in the same shape ``ingestion.py``
    produces (``{"sections": [{"text": "..."}], "metadata": {...},
    "agency": "...", "project": "...", ...}``). The selected backend
    is invoked with the joined section text; on any failure (missing
    SDK, missing API key, malformed response, network error) the
    fallback is the regex baseline so the pipeline never loses
    metadata.
    """
    chosen = backend or _resolve_backend()
    if chosen not in _BACKENDS:
        raise ValueError(
            f"Unknown metadata backend {chosen!r}; "
            f"expected one of {sorted(_BACKENDS)}"
        )
    try:
        return _BACKENDS[chosen](document)
    except Exception:  # pragma: no cover - defensive fallback
        # Strictly additive: an LLM failure must not delete the
        # CSV/regex metadata the rest of the pipeline already has.
        return _regex_backend(document)


def _join_text(document: dict[str, Any]) -> str:
    sections = document.get("sections") or []
    parts: list[str] = []
    for sec in sections:
        text = (sec.get("text") if isinstance(sec, dict) else "") or ""
        if text:
            parts.append(text)
    joined = "\n\n".join(parts)
    return joined[:TEXT_CHAR_LIMIT]


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _extract_email(text: str) -> str | None:
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else None


def _iso_date(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    match = _ISO_DATE_RE.match(s)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    s = str(value).strip()
    return s or None


def _regex_backend(document: dict[str, Any]) -> MetadataExtraction:
    """Regex / CSV-passthrough baseline — the ADR 0001 invariant."""
    metadata = (
        document.get("metadata")
        if isinstance(document.get("metadata"), dict)
        else {}
    )
    text = _join_text(document)
    budget = _coerce_float(metadata.get("budget"))
    return MetadataExtraction(
        agency=_clean_str(document.get("agency") or metadata.get("agency")),
        project_name=_clean_str(
            document.get("project") or metadata.get("project")
        ),
        budget_amount=budget,
        # Currency is implicit in the CSV (Korean RFPs are KRW); only
        # surface it when we actually have an amount.
        budget_currency="KRW" if budget is not None else None,
        deadline_iso=_iso_date(metadata.get("bid_deadline_at")),
        submission_date_iso=_iso_date(metadata.get("bid_start_at")),
        contact_email=_extract_email(text),
        contact_name=None,  # regex stays conservative on contact name
    )


def _stub_backend(document: dict[str, Any]) -> MetadataExtraction:
    """Deterministic stub — returns the regex baseline output.

    The stub-matches-baseline invariant is a unit test: stub-mode
    runs produce zero LLM cost AND zero schema drift, so downstream
    consumers (eval ablation rows, dashboards) stay stable when the
    LLM path is not enabled.
    """
    return _regex_backend(document)


def _anthropic_tool_use_backend(  # pragma: no cover - network
    document: dict[str, Any],
) -> MetadataExtraction:
    try:
        import anthropic  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "anthropic_tool_use backend requires the anthropic SDK. "
            "Install with `pip install anthropic` or use "
            "BIDMATE_METADATA_BACKEND=stub."
        ) from exc

    api_key = os.environ.get(ENV_ANTHROPIC_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_ANTHROPIC_KEY} is not set.")

    model = os.environ.get(ENV_MODEL) or DEFAULT_ANTHROPIC_MODEL
    max_tokens = int(os.environ.get(ENV_MAX_TOKENS) or DEFAULT_MAX_TOKENS)

    text = _join_text(document)
    # Cache the system prompt + tool definition together — both are
    # stable across queries, so a single cache breakpoint covers them.
    cached_tool = dict(TOOL_DEFINITION)
    cached_tool["cache_control"] = {"type": "ephemeral"}

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[cached_tool],
        tool_choice={"type": "tool", "name": TOOL_DEFINITION["name"]},
        messages=[{"role": "user", "content": text}],
    )
    payload = _extract_anthropic_tool_payload(response)
    return _payload_to_extraction(payload)


def _openai_function_call_backend(  # pragma: no cover - network
    document: dict[str, Any],
) -> MetadataExtraction:
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "openai_function_call backend requires the openai SDK. "
            "Install with `pip install openai` or use "
            "BIDMATE_METADATA_BACKEND=stub."
        ) from exc

    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_API_KEY} is not set.")
    model = os.environ.get(ENV_MODEL)
    if not model:
        raise RuntimeError(f"{ENV_MODEL} is not set.")
    base_url = os.environ.get(ENV_BASE_URL) or None
    max_tokens = int(os.environ.get(ENV_MAX_TOKENS) or DEFAULT_MAX_TOKENS)

    text = _join_text(document)
    client = OpenAI(api_key=api_key, base_url=base_url)
    function_def = {
        "name": TOOL_DEFINITION["name"],
        "description": TOOL_DEFINITION["description"],
        "parameters": TOOL_DEFINITION["input_schema"],
    }
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        tools=[{"type": "function", "function": function_def}],
        tool_choice={
            "type": "function",
            "function": {"name": function_def["name"]},
        },
    )
    payload: dict[str, Any] = {}
    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        if getattr(call.function, "name", None) == function_def["name"]:
            args = getattr(call.function, "arguments", None) or "{}"
            try:
                payload = json.loads(args)
            except json.JSONDecodeError:
                payload = {}
            break
    return _payload_to_extraction(payload)


def _extract_anthropic_tool_payload(response: Any) -> dict[str, Any]:
    for block in getattr(response, "content", None) or []:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == TOOL_DEFINITION["name"]
        ):
            payload = getattr(block, "input", None) or {}
            if isinstance(payload, dict):
                return payload
    return {}


def _payload_to_extraction(payload: dict[str, Any]) -> MetadataExtraction:
    """Coerce arbitrary tool-call JSON into the typed dataclass."""
    return MetadataExtraction(
        agency=_clean_str(payload.get("agency")),
        project_name=_clean_str(payload.get("project_name")),
        budget_amount=_coerce_float(payload.get("budget_amount")),
        budget_currency=_clean_str(payload.get("budget_currency")),
        deadline_iso=_iso_date(payload.get("deadline_iso")),
        submission_date_iso=_iso_date(payload.get("submission_date_iso")),
        contact_email=_clean_str(payload.get("contact_email")),
        contact_name=_clean_str(payload.get("contact_name")),
    )


_BACKENDS: dict[str, Any] = {
    "regex": _regex_backend,
    "stub": _stub_backend,
    "anthropic_tool_use": _anthropic_tool_use_backend,
    "openai_function_call": _openai_function_call_backend,
}


__all__ = [
    "METADATA_SCHEMA_VERSION",
    "DEFAULT_BACKEND",
    "ENV_BACKEND",
    "FIELD_NAMES",
    "MetadataExtraction",
    "TOOL_DEFINITION",
    "extract_rfp_metadata",
]
