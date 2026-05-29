"""Tests for issue #1656 — quota-aware agent-mix rebalancing.

Covers the agentcat-payload parser, the config-file fallback, the burn-rate
target rebalancer, and the integration helper that mutates the policy dict.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import agent_loop_quota as quota  # noqa: E402


def _now_utc() -> datetime:
    return datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIDMATE_AGENT_LOOP_QUOTA_OFF", raising=False)
    monkeypatch.delenv("BIDMATE_AGENTCAT", raising=False)


# ---------- _parse_agentcat_payload ---------------------------------------


def test_parse_agentcat_payload_extracts_weekly_signals() -> None:
    now = _now_utc()
    reset_claude = now + timedelta(days=5)
    reset_codex = now + timedelta(days=4)
    payload = {
        "providers": {
            "claude": {
                "limits": {
                    "weeklyResetAt": _epoch(reset_claude),
                    "quotas": [
                        {"id": "claude:five_hour", "remainingPercent": 99.0, "resetAt": _epoch(now + timedelta(hours=4))},
                        {"id": "claude:seven_day", "remainingPercent": 71.0, "resetAt": _epoch(reset_claude)},
                    ],
                }
            },
            "codex": {
                "limits": {
                    "weeklyResetAt": _epoch(reset_codex),
                    "quotas": [
                        {"id": "codex:5h", "remainingPercent": 95.0, "resetAt": _epoch(now + timedelta(hours=5))},
                        {"id": "codex:7d", "remainingPercent": 42.0, "resetAt": _epoch(reset_codex)},
                    ],
                }
            },
        }
    }
    out = quota._parse_agentcat_payload(payload)
    assert isinstance(out["claude"], quota.QuotaState)
    assert isinstance(out["codex"], quota.QuotaState)
    assert out["claude"].remaining_pct == 71.0
    assert out["claude"].source == "agentcat"
    assert out["codex"].remaining_pct == 42.0
    # Reset time matches the 7-day entry, not the 5-hour entry.
    assert out["claude"].reset_at == reset_claude
    assert out["codex"].reset_at == reset_codex


def test_parse_agentcat_payload_uses_weeklyResetAt_when_quota_resetAt_missing() -> None:
    now = _now_utc()
    weekly_reset = now + timedelta(days=3)
    payload = {
        "providers": {
            "claude": {
                "limits": {
                    "weeklyResetAt": _epoch(weekly_reset),
                    "quotas": [
                        {"id": "claude:seven_day", "remainingPercent": 50.0, "resetAt": None},
                    ],
                }
            }
        }
    }
    out = quota._parse_agentcat_payload(payload)
    assert isinstance(out["claude"], quota.QuotaState)
    assert out["claude"].reset_at == weekly_reset


def test_parse_agentcat_payload_skips_missing_provider() -> None:
    payload = {"providers": {"claude": None}}
    out = quota._parse_agentcat_payload(payload)
    assert out["claude"] is None
    assert out["codex"] is None


def test_parse_agentcat_payload_skips_when_pct_invalid() -> None:
    payload = {
        "providers": {
            "claude": {
                "limits": {
                    "weeklyResetAt": _epoch(_now_utc() + timedelta(days=5)),
                    "quotas": [{"id": "claude:seven_day", "remainingPercent": None, "resetAt": None}],
                }
            }
        }
    }
    out = quota._parse_agentcat_payload(payload)
    assert out["claude"] is None


def test_parse_agentcat_payload_handles_non_dict() -> None:
    assert quota._parse_agentcat_payload([]) == {"claude": None, "codex": None}
    assert quota._parse_agentcat_payload("nope") == {"claude": None, "codex": None}


# ---------- _read_config_signals -------------------------------------------


def test_read_config_signals_computes_pct_from_limit_minus_used(tmp_path: Path) -> None:
    config = tmp_path / "quota_config.json"
    config.write_text(
        json.dumps(
            {
                "claude": {
                    "weekly_limit_units": 1000,
                    "used_this_week_units": 250,
                    "reset_dow": "mon",
                    "reset_hour_utc": 0,
                },
                "codex": {
                    "weekly_limit_units": 500,
                    "used_this_week_units": 400,
                    "reset_dow": "mon",
                    "reset_hour_utc": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    now = _now_utc()  # 2026-05-28 = Thursday 12:00 UTC
    out = quota._read_config_signals(config, now=now)
    assert isinstance(out["claude"], quota.QuotaState)
    assert out["claude"].remaining_pct == pytest.approx(75.0)
    assert out["claude"].source == "config"
    # Next Monday 00:00 UTC after a Thursday is 4 days away.
    expected_reset = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert out["claude"].reset_at == expected_reset
    assert out["codex"].remaining_pct == pytest.approx(20.0)


def test_read_config_signals_missing_file_returns_none(tmp_path: Path) -> None:
    out = quota._read_config_signals(tmp_path / "missing.json", now=_now_utc())
    assert out == {"claude": None, "codex": None}


def test_read_config_signals_malformed_skips(tmp_path: Path) -> None:
    config = tmp_path / "broken.json"
    config.write_text("{not json", encoding="utf-8")
    out = quota._read_config_signals(config, now=_now_utc())
    assert out == {"claude": None, "codex": None}


def test_read_config_signals_zero_limit_skips(tmp_path: Path) -> None:
    config = tmp_path / "zero.json"
    config.write_text(
        json.dumps({"claude": {"weekly_limit_units": 0, "used_this_week_units": 0, "reset_dow": "mon"}}),
        encoding="utf-8",
    )
    out = quota._read_config_signals(config, now=_now_utc())
    assert out["claude"] is None


# ---------- read_quota_signals (priority order) ---------------------------


def test_read_quota_signals_agentcat_wins(tmp_path: Path) -> None:
    config = tmp_path / "quota_config.json"
    config.write_text(
        json.dumps(
            {
                "claude": {
                    "weekly_limit_units": 100,
                    "used_this_week_units": 50,
                    "reset_dow": "mon",
                    "reset_hour_utc": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    now = _now_utc()
    snapshot = json.dumps(
        {
            "providers": {
                "claude": {
                    "limits": {
                        "weeklyResetAt": _epoch(now + timedelta(days=2)),
                        "quotas": [
                            {"id": "claude:seven_day", "remainingPercent": 88.0, "resetAt": _epoch(now + timedelta(days=2))}
                        ],
                    }
                }
            }
        }
    )
    out = quota.read_quota_signals(
        config_path=config,
        now=now,
        snapshot_runner=lambda exe: snapshot,
    )
    assert out["claude"].source == "agentcat"
    assert out["claude"].remaining_pct == 88.0  # agentcat, not config (50%)


def test_read_quota_signals_config_fills_gaps(tmp_path: Path) -> None:
    config = tmp_path / "quota_config.json"
    config.write_text(
        json.dumps(
            {
                "codex": {
                    "weekly_limit_units": 1000,
                    "used_this_week_units": 300,
                    "reset_dow": "mon",
                    "reset_hour_utc": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    now = _now_utc()
    snapshot = json.dumps(
        {
            "providers": {
                "claude": {
                    "limits": {
                        "weeklyResetAt": _epoch(now + timedelta(days=4)),
                        "quotas": [
                            {"id": "claude:seven_day", "remainingPercent": 60.0, "resetAt": _epoch(now + timedelta(days=4))}
                        ],
                    }
                }
            }
        }
    )
    out = quota.read_quota_signals(
        config_path=config,
        now=now,
        snapshot_runner=lambda exe: snapshot,
    )
    assert out["claude"].source == "agentcat"
    assert out["codex"].source == "config"
    assert out["codex"].remaining_pct == pytest.approx(70.0)


def test_read_quota_signals_both_unknown(tmp_path: Path) -> None:
    out = quota.read_quota_signals(
        config_path=tmp_path / "absent.json",
        now=_now_utc(),
        snapshot_runner=lambda exe: "",
    )
    assert out == {"claude": None, "codex": None}


def test_read_quota_signals_handles_runner_exception(tmp_path: Path) -> None:
    def boom(_exe: str) -> str:
        raise RuntimeError("agentcat crashed")

    out = quota.read_quota_signals(
        config_path=tmp_path / "absent.json",
        now=_now_utc(),
        snapshot_runner=boom,
    )
    assert out == {"claude": None, "codex": None}


# ---------- compute_dynamic_target -----------------------------------------


def test_compute_dynamic_target_default_when_no_signals() -> None:
    default = {"claude": 5, "codex": 5}
    new_target, explanation = quota.compute_dynamic_target(
        default,
        {"claude": None, "codex": None},
        now=_now_utc(),
    )
    assert new_target == default
    assert "none available" in explanation.lower() or "default" in explanation.lower()


def test_compute_dynamic_target_balances_when_one_provider_has_more_slack() -> None:
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(
            remaining_pct=90.0,
            reset_at=now + timedelta(hours=140),
            source="agentcat",
        ),
        "codex": quota.QuotaState(
            remaining_pct=40.0,
            reset_at=now + timedelta(hours=120),
            source="agentcat",
        ),
    }
    new_target, explanation = quota.compute_dynamic_target(
        {"claude": 5, "codex": 5}, signals, now=now
    )
    assert sum(new_target.values()) == 10
    assert new_target["claude"] > new_target["codex"]
    assert "effective=" in explanation
    assert "claude=" in explanation
    assert "codex=" in explanation


def test_compute_dynamic_target_preserves_min_one_per_lane() -> None:
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(remaining_pct=99.0, reset_at=now + timedelta(hours=160), source="agentcat"),
        "codex": quota.QuotaState(remaining_pct=1.0, reset_at=now + timedelta(hours=160), source="agentcat"),
    }
    new_target, _ = quota.compute_dynamic_target(
        {"claude": 5, "codex": 5}, signals, now=now
    )
    assert new_target["codex"] >= 1
    assert new_target["claude"] >= 1
    assert sum(new_target.values()) == 10


def test_compute_dynamic_target_partial_tilts_when_one_has_slack() -> None:
    """Claude at 95% but only 60h until reset — way more cushion than flat burn → tilt to claude."""
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(
            remaining_pct=95.0,
            reset_at=now + timedelta(hours=60),
            source="agentcat",
        ),
        "codex": None,
    }
    new_target, explanation = quota.compute_dynamic_target(
        {"claude": 5, "codex": 5}, signals, now=now
    )
    assert new_target["claude"] == 6
    assert new_target["codex"] == 4
    assert "partial" in explanation


def test_compute_dynamic_target_partial_reverses_when_one_depleted() -> None:
    """Claude at 10% with 160h to go — way under flat-burn cushion → tilt away from claude."""
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(
            remaining_pct=10.0,
            reset_at=now + timedelta(hours=160),
            source="agentcat",
        ),
        "codex": None,
    }
    new_target, _ = quota.compute_dynamic_target(
        {"claude": 5, "codex": 5}, signals, now=now
    )
    assert new_target["claude"] == 4
    assert new_target["codex"] == 6


def test_compute_dynamic_target_partial_no_tilt_when_on_flat_burn() -> None:
    """Claude at 95% with 160h left (~expected) → no tilt, default 5:5 preserved."""
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(
            remaining_pct=95.0,
            reset_at=now + timedelta(hours=160),
            source="agentcat",
        ),
        "codex": None,
    }
    new_target, _ = quota.compute_dynamic_target(
        {"claude": 5, "codex": 5}, signals, now=now
    )
    assert new_target == {"claude": 5, "codex": 5}


def test_compute_dynamic_target_zero_default_unchanged() -> None:
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(remaining_pct=50.0, reset_at=now + timedelta(hours=100), source="agentcat"),
        "codex": quota.QuotaState(remaining_pct=50.0, reset_at=now + timedelta(hours=100), source="agentcat"),
    }
    new_target, _ = quota.compute_dynamic_target({"claude": 0, "codex": 0}, signals, now=now)
    assert new_target == {"claude": 0, "codex": 0}


def test_compute_dynamic_target_zero_hours_left_falls_back() -> None:
    now = _now_utc()
    signals = {
        "claude": quota.QuotaState(remaining_pct=50.0, reset_at=now - timedelta(hours=1), source="agentcat"),
        "codex": quota.QuotaState(remaining_pct=50.0, reset_at=now - timedelta(hours=2), source="agentcat"),
    }
    new_target, _ = quota.compute_dynamic_target({"claude": 5, "codex": 5}, signals, now=now)
    assert new_target == {"claude": 5, "codex": 5}


def test_read_config_signals_accepts_exact_reset_at(tmp_path: Path) -> None:
    now = _now_utc()
    config = tmp_path / "quota_config.json"
    config.write_text(
        json.dumps(
            {
                "claude": {
                    "weekly_limit_units": 100,
                    "used_this_week_units": 0,
                    "reset_at": "2026-06-04T23:52:59Z",
                    "reset_dow": "mon",
                    "reset_hour_utc": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    signals = quota._read_config_signals(config, now=now)

    assert isinstance(signals["claude"], quota.QuotaState)
    assert signals["claude"].remaining_pct == 100.0
    assert signals["claude"].reset_at == datetime(2026, 6, 4, 23, 52, 59, tzinfo=timezone.utc)


def test_read_config_signals_rolls_past_exact_reset_at_forward(tmp_path: Path) -> None:
    now = datetime(2026, 6, 5, 1, 0, tzinfo=timezone.utc)
    config = tmp_path / "quota_config.json"
    config.write_text(
        json.dumps(
            {
                "claude": {
                    "weekly_limit_units": 100,
                    "used_this_week_units": 0,
                    "reset_at": "2026-06-04T23:52:59Z",
                }
            }
        ),
        encoding="utf-8",
    )

    signals = quota._read_config_signals(config, now=now)

    assert signals["claude"].reset_at == datetime(2026, 6, 11, 23, 52, 59, tzinfo=timezone.utc)


# ---------- apply_quota_aware_target ---------------------------------------


def test_apply_quota_aware_target_writes_explanation_field(tmp_path: Path) -> None:
    policy = {"target": {"claude": 5, "codex": 5}}
    snapshot = json.dumps(
        {
            "providers": {
                "claude": {
                    "limits": {
                        "weeklyResetAt": _epoch(_now_utc() + timedelta(days=5)),
                        "quotas": [
                            {
                                "id": "claude:seven_day",
                                "remainingPercent": 70.0,
                                "resetAt": _epoch(_now_utc() + timedelta(days=5)),
                            }
                        ],
                    }
                }
            }
        }
    )
    new_policy, explanation = quota.apply_quota_aware_target(
        policy,
        now=_now_utc(),
        repo_root=tmp_path,
        snapshot_runner=lambda exe: snapshot,
    )
    assert "quota_explanation" in new_policy
    assert new_policy["quota_explanation"] == explanation
    assert "claude=" in explanation
    # Codex was unknown — partial-signal path.
    assert "partial" in explanation


def test_apply_quota_aware_target_off_env_disables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIDMATE_AGENT_LOOP_QUOTA_OFF", "1")
    policy = {"target": {"claude": 5, "codex": 5}}
    new_policy, explanation = quota.apply_quota_aware_target(
        policy,
        now=_now_utc(),
        repo_root=tmp_path,
        snapshot_runner=lambda exe: "should-not-be-called",
    )
    assert new_policy["target"] == {"claude": 5, "codex": 5}
    assert "disabled" in explanation


def test_apply_quota_aware_target_keeps_target_when_no_signals(tmp_path: Path) -> None:
    policy = {"target": {"claude": 5, "codex": 5}, "window": {"size": 20}}
    new_policy, _ = quota.apply_quota_aware_target(
        policy,
        now=_now_utc(),
        repo_root=tmp_path,
        snapshot_runner=lambda exe: "",
    )
    assert new_policy["target"] == {"claude": 5, "codex": 5}
    # quota_explanation still attached for observability.
    assert "quota_explanation" in new_policy


# ---------- _next_weekly_reset ---------------------------------------------


def test_next_weekly_reset_advances_to_following_monday_midnight() -> None:
    # 2026-05-28 is a Thursday.
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    nxt = quota._next_weekly_reset(reset_dow=0, reset_hour_utc=0, now=now)
    assert nxt == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


def test_next_weekly_reset_handles_same_day_after_hour() -> None:
    # Thursday at 13:00 UTC, reset is Thursday at 09:00 UTC → next week.
    now = datetime(2026, 5, 28, 13, 0, tzinfo=timezone.utc)
    nxt = quota._next_weekly_reset(reset_dow=3, reset_hour_utc=9, now=now)
    assert nxt == datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)


def test_next_weekly_reset_handles_same_day_before_hour() -> None:
    # Thursday at 08:00 UTC, reset is Thursday at 09:00 UTC → same day.
    now = datetime(2026, 5, 28, 8, 0, tzinfo=timezone.utc)
    nxt = quota._next_weekly_reset(reset_dow=3, reset_hour_utc=9, now=now)
    assert nxt == datetime(2026, 5, 28, 9, 0, tzinfo=timezone.utc)
