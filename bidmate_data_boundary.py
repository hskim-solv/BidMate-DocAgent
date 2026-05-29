"""External-payload data-boundary guard (ADR 0061 ③ / ADR 0005).

ADR 0061 permits opt-in external/paid API backends. The outbound payload
boundary is controlled by two explicit attestations:

* ``BIDMATE_DATA_SURFACE`` — public fixture data is always allowed.
* ``BIDMATE_EGRESS_PROFILE`` — private/local data may use external API
  channels only when the operator explicitly attests an approved egress
  scenario.

This module is the central choke point. Every external backend calls
:func:`assert_external_payload_allowed` before any SDK import or network
I/O. The guard is **fail-closed** — unset, ``air_gapped``,
``connected_no_egress``, or any unrecognized value blocks the call; the
backend then falls back to its offline path (regex baseline / deterministic
synthesis), so the guard never breaks the pipeline.

Deliberate non-goals (why this is an attestation, not content inspection):

* There is no runtime provenance signal in the codebase — the public /
  private boundary is file-convention only (``*.example.yaml`` + the
  ``.gitignore`` rules, ADR 0005), so a document / evidence chunk does not
  carry a trustworthy "I came from a private corpus" tag at the egress
  point.
* Content classification ("does this text look private?") is unreliable
  and would false-positive on public fixture data.

The env attestation is therefore an explicit, auditable opt-in. It closes
the *accidental*-leak path (enabling an external backend without
considering the data boundary) and creates a single choke point; it does
not defend against an operator deliberately mis-attesting the surface.
Provenance-tagged enforcement threaded from ingestion is possible future
hardening (would need its own ADR).

Leaf utility: no imports from rag_core / ingestion / api, no SDKs, no model
loading. The only side input is the environment variable.
"""

from __future__ import annotations

import os

DATA_SURFACE_ENV = "BIDMATE_DATA_SURFACE"
EGRESS_PROFILE_ENV = "BIDMATE_EGRESS_PROFILE"

# Strict allowlist: only these attested surfaces permit external egress.
# Everything else — unset, "private", "local", "private_local", or any
# unrecognized token — fails closed. Hyphen and underscore spellings of the
# compound form are both accepted so callers need not memorize one.
PUBLIC_SURFACES: frozenset[str] = frozenset(
    {"public", "public_fixture", "public-fixture"}
)

# Private/local RFP payloads may be sent through any external API channel only
# with explicit operational attestation. This is intentionally channel-wide:
# synthesis, metadata extraction, embeddings, reranking, query rewrite, and
# planning can all carry raw document/query/evidence text. ``redacted_external_api``
# is intentionally not included here because current backends send payload text,
# not a proven-redacted payload.
EXTERNAL_EGRESS_ALLOWED_PROFILES: frozenset[str] = frozenset(
    {
        "approved_external_api",
        "approved-external-api",
        "customer_managed_cloud",
        "customer-managed-cloud",
    }
)


class ExternalPayloadBlocked(RuntimeError):
    """Raised when an external backend would send a non-public payload.

    Subclasses :class:`RuntimeError` so the existing ``except Exception``
    fallbacks in the backends (regex baseline in
    ``rag_metadata_extraction.extract_rfp_metadata``; deterministic answer
    in ``rag_synthesis.synthesize_answer``) catch it — the guard fails
    closed *and* the pipeline keeps its offline result.
    """


def resolve_data_surface() -> str:
    """Return the normalized declared data surface (``""`` when unset)."""
    return os.environ.get(DATA_SURFACE_ENV, "").strip().lower()


def is_public_surface() -> bool:
    """True only when the surface is explicitly attested public fixture."""
    return resolve_data_surface() in PUBLIC_SURFACES


def resolve_egress_profile() -> str:
    """Return the normalized declared deployment/egress profile."""
    return os.environ.get(EGRESS_PROFILE_ENV, "").strip().lower()


def external_egress_allowed() -> bool:
    """True when public data or an approved channel-wide egress profile is set."""
    return is_public_surface() or resolve_egress_profile() in EXTERNAL_EGRESS_ALLOWED_PROFILES


def assert_external_payload_allowed(*, channel: str) -> None:
    """Fail closed unless the data surface/profile permits external egress.

    Call this at the very top of every external backend — before any SDK
    import or network call — so a blocked surface never reaches the vendor.
    ``channel`` labels the egress site (e.g.
    ``"metadata_extraction:anthropic_tool_use"``) for the error message.

    Raises:
        ExternalPayloadBlocked: when neither the public data surface nor an
            approved egress profile is attested.
    """
    if external_egress_allowed():
        return
    declared = resolve_data_surface() or "<unset>"
    profile = resolve_egress_profile() or "<unset>"
    raise ExternalPayloadBlocked(
        f"external egress blocked for channel={channel!r}: "
        f"{DATA_SURFACE_ENV}={declared}, {EGRESS_PROFILE_ENV}={profile}. "
            f"Set {DATA_SURFACE_ENV}=public_fixture for public fixtures, or set "
            f"{EGRESS_PROFILE_ENV}=approved_external_api / customer_managed_cloud "
        "only when private/local RFP external API egress is explicitly approved "
        "for every enabled channel in this run."
    )


__all__ = [
    "DATA_SURFACE_ENV",
    "EGRESS_PROFILE_ENV",
    "EXTERNAL_EGRESS_ALLOWED_PROFILES",
    "PUBLIC_SURFACES",
    "ExternalPayloadBlocked",
    "assert_external_payload_allowed",
    "external_egress_allowed",
    "is_public_surface",
    "resolve_data_surface",
    "resolve_egress_profile",
]
