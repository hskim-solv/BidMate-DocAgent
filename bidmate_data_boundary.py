"""External-payload data-boundary guard (ADR 0061 ③ / ADR 0005).

ADR 0061 permits opt-in external/paid API backends, but its condition ③
restricts the *outbound* payload to explicitly public fixture data — private
real-eval data and private RFP bodies stay off the wire (ADR 0005,
which can only be relaxed by a superseding ADR). Until now that was a
*policy* with no code enforcement: the ``anthropic`` / ``openai`` backends
in ``rag_metadata_extraction`` and ``rag_synthesis`` joined the full
document / evidence text and sent it to the vendor with no surface check.

This module is the central choke point. Every external backend calls
:func:`assert_external_payload_allowed` before any SDK import or network
I/O. The data surface is declared by the ``BIDMATE_DATA_SURFACE`` env var
and the guard is **fail-closed** — egress is permitted only when the
surface is explicitly attested public fixture. Unset, ``private`` /
``local``, or any unrecognized value blocks the call; the backend then
falls back to its offline path (regex baseline / deterministic synthesis),
so the guard never breaks the pipeline.

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

# Strict allowlist: only these attested surfaces permit external egress.
# Everything else — unset, "private", "local", "private_local", or any
# unrecognized token — fails closed. Hyphen and underscore spellings of the
# compound form are both accepted so callers need not memorize one.
PUBLIC_SURFACES: frozenset[str] = frozenset(
    {"public", "public_fixture", "public-fixture"}
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


def assert_external_payload_allowed(*, channel: str) -> None:
    """Fail closed unless the data surface is attested public fixture.

    Call this at the very top of every external backend — before any SDK
    import or network call — so a blocked surface never reaches the vendor.
    ``channel`` labels the egress site (e.g.
    ``"metadata_extraction:anthropic_tool_use"``) for the error message.

    Raises:
        ExternalPayloadBlocked: when ``BIDMATE_DATA_SURFACE`` is not one of
            :data:`PUBLIC_SURFACES`.
    """
    if is_public_surface():
        return
    declared = resolve_data_surface() or "<unset>"
    raise ExternalPayloadBlocked(
        f"external egress blocked for channel={channel!r}: "
        f"{DATA_SURFACE_ENV}={declared} is not an attested public fixture "
        f"surface (ADR 0061 ③ / ADR 0005). Set {DATA_SURFACE_ENV}="
        "public_fixture only when the corpus is the committed public fixture; "
        "private/local RFP data must not be sent to external APIs."
    )


__all__ = [
    "DATA_SURFACE_ENV",
    "PUBLIC_SURFACES",
    "ExternalPayloadBlocked",
    "assert_external_payload_allowed",
    "is_public_surface",
    "resolve_data_surface",
]
