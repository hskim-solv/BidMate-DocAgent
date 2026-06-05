import pytest

import bidmate_data_boundary as boundary


def test_public_fixture_surface_allows_external_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(boundary.DATA_SURFACE_ENV, " Public-Fixture ")
    monkeypatch.delenv(boundary.EGRESS_PROFILE_ENV, raising=False)

    assert boundary.resolve_data_surface() == "public-fixture"
    assert boundary.is_public_surface()
    assert boundary.external_egress_allowed()
    boundary.assert_external_payload_allowed(channel="metadata")


def test_approved_private_egress_profile_allows_when_surface_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(boundary.DATA_SURFACE_ENV, raising=False)
    monkeypatch.setenv(boundary.EGRESS_PROFILE_ENV, " customer-managed-cloud ")

    assert boundary.resolve_egress_profile() == "customer-managed-cloud"
    assert boundary.external_egress_allowed()


def test_redacted_external_profile_still_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(boundary.DATA_SURFACE_ENV, raising=False)
    monkeypatch.setenv(boundary.EGRESS_PROFILE_ENV, "redacted_external_api")

    assert boundary.resolve_egress_profile() == "redacted_external_api"
    assert not boundary.external_egress_allowed()


def test_unattested_external_payload_fails_closed_with_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(boundary.DATA_SURFACE_ENV, "private_local")
    monkeypatch.setenv(boundary.EGRESS_PROFILE_ENV, "connected_no_egress")

    with pytest.raises(boundary.ExternalPayloadBlocked) as excinfo:
        boundary.assert_external_payload_allowed(channel="reranker:paid-api")

    message = str(excinfo.value)
    assert "reranker:paid-api" in message
    assert "BIDMATE_DATA_SURFACE=private_local" in message
    assert "BIDMATE_EGRESS_PROFILE=connected_no_egress" in message
