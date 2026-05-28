"""Quota-aware agent-mix rebalancing (issue #1656).

Reads remaining weekly quota for the Claude and Codex providers from
``agentcat snapshot --json`` (1st priority) or a local config file
(``reports/agent_loop/active/quota_config.json``, fallback). Then rebalances
the static ``claude=5,codex=5`` target so both providers burn down their
weekly allowance at the same rate ("drain both before reset" policy).

When neither signal is available, the original target is returned untouched
— the new behaviour is opt-in via signal availability, not via a flag.

This module is intentionally pure-functional: ``read_quota_signals`` does
I/O via an injectable runner; ``compute_dynamic_target`` is deterministic.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ACTIVE_LANE_AGENTS = ("claude", "codex")

# Quota IDs surfaced by agentcat 0.x for the 7-day window. Verified empirically
# 2026-05-28 with /Users/hskim/.local/bin/agentcat 0.x — these are the only
# weekly entries today; if agentcat renames them, falls through to config.
_AGENTCAT_WEEKLY_IDS: dict[str, tuple[str, ...]] = {
    "claude": ("claude:seven_day",),
    "codex": ("codex:7d",),
}

_DOW_INDEX = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


@dataclass(frozen=True)
class QuotaState:
    """Snapshot of one provider's weekly quota.

    ``remaining_pct`` is in [0.0, 100.0]. ``reset_at`` is the next weekly reset
    in UTC. ``source`` records where the signal came from so the report can
    explain the rebalance to a human reviewer.
    """

    remaining_pct: float
    reset_at: datetime
    source: str  # "agentcat" | "config"

    def remaining_hours(self, now: datetime) -> float:
        delta = self.reset_at - now
        hours = delta.total_seconds() / 3600.0
        return hours if hours > 0 else 0.0


def _snapshot_runner_default(executable: str) -> str:
    """Default subprocess runner — invokes ``agentcat snapshot --json``."""
    try:
        completed = subprocess.run(
            [executable, "snapshot", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout or ""


def _coerce_remaining_pct(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value < 0 or value > 100:
            return None
        return value
    return None


def _coerce_reset_at(raw: object) -> datetime | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _parse_agentcat_payload(payload: object) -> dict[str, QuotaState | None]:
    """Pick the weekly quota entry per provider from agentcat snapshot output."""
    result: dict[str, QuotaState | None] = {agent: None for agent in ACTIVE_LANE_AGENTS}
    if not isinstance(payload, dict):
        return result
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return result
    for agent, weekly_ids in _AGENTCAT_WEEKLY_IDS.items():
        provider = providers.get(agent)
        if not isinstance(provider, dict):
            continue
        limits = provider.get("limits")
        if not isinstance(limits, dict):
            continue
        quotas = limits.get("quotas")
        if not isinstance(quotas, list):
            continue
        weekly_entry: dict | None = None
        for quota in quotas:
            if not isinstance(quota, dict):
                continue
            if str(quota.get("id") or "") in weekly_ids:
                weekly_entry = quota
                break
        if weekly_entry is None:
            continue
        remaining_pct = _coerce_remaining_pct(weekly_entry.get("remainingPercent"))
        reset_at_raw = weekly_entry.get("resetAt")
        if reset_at_raw is None:
            reset_at_raw = limits.get("weeklyResetAt")
        reset_at = _coerce_reset_at(reset_at_raw)
        if remaining_pct is None or reset_at is None:
            continue
        result[agent] = QuotaState(
            remaining_pct=remaining_pct,
            reset_at=reset_at,
            source="agentcat",
        )
    return result


def _next_weekly_reset(*, reset_dow: int, reset_hour_utc: int, now: datetime) -> datetime:
    """Compute the next UTC weekly reset >= ``now`` for the given day-of-week + hour."""
    reset_dow = max(0, min(6, reset_dow))
    reset_hour_utc = max(0, min(23, reset_hour_utc))
    candidate = now.astimezone(timezone.utc).replace(
        hour=reset_hour_utc, minute=0, second=0, microsecond=0
    )
    delta_days = (reset_dow - candidate.weekday()) % 7
    candidate = candidate + timedelta(days=delta_days)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate


def _read_config_signals(
    config_path: Path,
    *,
    now: datetime,
) -> dict[str, QuotaState | None]:
    """Parse the local ``quota_config.json`` fallback file."""
    result: dict[str, QuotaState | None] = {agent: None for agent in ACTIVE_LANE_AGENTS}
    if not config_path.exists():
        return result
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if not isinstance(payload, dict):
        return result
    for agent in ACTIVE_LANE_AGENTS:
        entry = payload.get(agent)
        if not isinstance(entry, dict):
            continue
        weekly_limit = entry.get("weekly_limit_units")
        used = entry.get("used_this_week_units")
        if not isinstance(weekly_limit, (int, float)) or not isinstance(used, (int, float)):
            continue
        if weekly_limit <= 0:
            continue
        remaining_pct = max(0.0, min(100.0, (1.0 - float(used) / float(weekly_limit)) * 100.0))
        dow_raw = str(entry.get("reset_dow") or "mon").strip().lower()
        reset_dow = _DOW_INDEX.get(dow_raw)
        hour_raw = entry.get("reset_hour_utc", 0)
        try:
            reset_hour_utc = int(hour_raw)
        except (TypeError, ValueError):
            reset_hour_utc = 0
        if reset_dow is None:
            continue
        reset_at = _next_weekly_reset(
            reset_dow=reset_dow,
            reset_hour_utc=reset_hour_utc,
            now=now,
        )
        result[agent] = QuotaState(
            remaining_pct=remaining_pct,
            reset_at=reset_at,
            source="config",
        )
    return result


def read_quota_signals(
    *,
    config_path: Path,
    now: datetime,
    agentcat_executable: str = "agentcat",
    snapshot_runner: Callable[[str], str] | None = None,
) -> dict[str, QuotaState | None]:
    """Read per-provider weekly quota signals.

    Priority: agentcat snapshot --json (when the binary exists and returns the
    expected fields), then the local config file. Missing signals stay
    ``None`` and ``compute_dynamic_target`` falls back to the default mix.

    ``snapshot_runner`` is injectable so tests don't need to spawn the real
    agentcat binary.
    """
    result: dict[str, QuotaState | None] = {agent: None for agent in ACTIVE_LANE_AGENTS}

    runner = snapshot_runner if snapshot_runner is not None else _snapshot_runner_default
    resolved_executable = shutil.which(agentcat_executable) or agentcat_executable
    snapshot_text = ""
    try:
        snapshot_text = runner(resolved_executable) or ""
    except Exception:  # pragma: no cover - runner errors are non-fatal
        snapshot_text = ""
    if snapshot_text:
        try:
            payload = json.loads(snapshot_text)
        except (json.JSONDecodeError, ValueError):
            payload = None
        if payload is not None:
            result.update({k: v for k, v in _parse_agentcat_payload(payload).items() if v is not None})

    if any(result[agent] is None for agent in ACTIVE_LANE_AGENTS):
        config_signals = _read_config_signals(config_path, now=now)
        for agent in ACTIVE_LANE_AGENTS:
            if result[agent] is None and config_signals.get(agent) is not None:
                result[agent] = config_signals[agent]

    return result


def compute_dynamic_target(
    default_target: dict[str, int],
    signals: dict[str, QuotaState | None],
    *,
    now: datetime,
) -> tuple[dict[str, int], str]:
    """Rebalance the mix target so both providers burn down evenly before reset.

    Returns ``(target_map, explanation)``. ``target_map`` always sums to the
    same total as ``default_target`` and reserves at least 1 to each lane that
    started non-zero in the default. ``explanation`` is a single-line string
    suitable for the agent_mix_report.md observability row.
    """
    agents = list(ACTIVE_LANE_AGENTS)
    default = {a: int(default_target.get(a, 0)) for a in agents}
    total = sum(max(0, default[a]) for a in agents)
    if total <= 0:
        return dict(default), "Quota signals: ignored (default target is zero)"

    known: dict[str, QuotaState] = {}
    for agent in agents:
        candidate = signals.get(agent)
        if isinstance(candidate, QuotaState):
            known[agent] = candidate
    if not known:
        return dict(default), "Quota signals: none available — using default target"

    if len(known) == 1:
        known_agent, state = next(iter(known.items()))
        other_agent = next(a for a in agents if a != known_agent)
        # Compare remaining_pct to the "flat burn" expected at this point in
        # the week. Slack > +5pp → known lane has cushion → tilt to it.
        # Slack < -5pp → known lane is running thin → tilt away.
        hours_left = state.remaining_hours(now)
        tilt = 0
        if hours_left > 0:
            expected_pct = (hours_left / 168.0) * 100.0
            slack = state.remaining_pct - expected_pct
            if slack > 5.0:
                tilt = +1
            elif slack < -5.0:
                tilt = -1
        if tilt != 0 and default[other_agent] - tilt >= 1 and default[known_agent] + tilt >= 1:
            adjusted = dict(default)
            adjusted[known_agent] += tilt
            adjusted[other_agent] -= tilt
            return (
                adjusted,
                _format_explanation(signals, adjusted, partial_agent=known_agent),
            )
        return dict(default), _format_explanation(signals, default, partial_agent=known_agent)

    # Both providers known — compute burn-rate weighted shares.
    burn_rates: dict[str, float] = {}
    for agent, state in known.items():
        hours_left = state.remaining_hours(now)
        if hours_left <= 0:
            burn_rates[agent] = 0.0
        else:
            burn_rates[agent] = max(0.0, state.remaining_pct / hours_left)

    burn_total = sum(burn_rates.values())
    if burn_total <= 0:
        return dict(default), _format_explanation(signals, default)

    raw_weights = {a: (burn_rates.get(a, 0.0) / burn_total) * total for a in agents}
    # Round to integers while preserving the total and a min of 1 per lane.
    floored = {a: max(1, int(round(raw_weights.get(a, 0.0)))) for a in agents}
    drift = total - sum(floored.values())
    while drift != 0:
        if drift > 0:
            candidates = sorted(
                agents, key=lambda a: raw_weights.get(a, 0.0) - floored[a], reverse=True
            )
            if not candidates:
                break
            floored[candidates[0]] += 1
            drift -= 1
        else:
            candidates = [a for a in agents if floored[a] > 1]
            if not candidates:
                break
            candidates.sort(key=lambda a: raw_weights.get(a, 0.0) - floored[a])
            floored[candidates[0]] -= 1
            drift += 1

    return floored, _format_explanation(signals, floored)


def _format_explanation(
    signals: dict[str, QuotaState | None],
    effective: dict[str, int],
    *,
    partial_agent: str | None = None,
) -> str:
    """Render the one-line observability hint for agent_mix_report.md."""
    parts: list[str] = []
    for agent in ACTIVE_LANE_AGENTS:
        state = signals.get(agent)
        if isinstance(state, QuotaState):
            reset_iso = state.reset_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
            parts.append(
                f"{agent}={state.remaining_pct:.0f}% (source={state.source}, resets {reset_iso})"
            )
        else:
            parts.append(f"{agent}=unknown")
    effective_str = ",".join(f"{k}={v}" for k, v in sorted(effective.items()))
    suffix = ""
    if partial_agent is not None:
        suffix = " (partial: only one signal known)"
    return f"Quota signals: {' / '.join(parts)} → effective={effective_str}{suffix}"


def quota_config_default_path(repo_root: Path) -> Path:
    """Runtime config path — gitignored (user-local, may contain plan info)."""
    return repo_root / "reports" / "agent_loop" / "active" / "quota_config.json"


def quota_config_example_path(repo_root: Path) -> Path:
    """Tracked example template — under scripts/ so it lands in the repo."""
    return repo_root / "scripts" / "agent_loop_quota.example.json"


def apply_quota_aware_target(
    agent_mix_policy: dict[str, object],
    *,
    now: datetime,
    repo_root: Path,
    snapshot_runner: Callable[[str], str] | None = None,
    agentcat_executable: str | None = None,
) -> tuple[dict[str, object], str]:
    """Wrap an ``agent_mix`` policy dict with quota-aware target rebalancing.

    Returns the updated policy dict (target may have been replaced) and the
    human-readable explanation string. ``agent_mix_policy['quota_explanation']``
    is set so downstream reporters can surface it.
    """
    target_raw = agent_mix_policy.get("target")
    if not isinstance(target_raw, dict):
        return agent_mix_policy, "Quota signals: no target in policy"
    default_target = {k: int(v) for k, v in target_raw.items() if isinstance(v, (int, float))}

    if os.environ.get("BIDMATE_AGENT_LOOP_QUOTA_OFF", "").strip().lower() in {"1", "true", "yes", "on"}:
        explanation = "Quota signals: disabled via BIDMATE_AGENT_LOOP_QUOTA_OFF"
        agent_mix_policy = dict(agent_mix_policy)
        agent_mix_policy["quota_explanation"] = explanation
        return agent_mix_policy, explanation

    executable = agentcat_executable or os.environ.get("BIDMATE_AGENTCAT", "agentcat")
    config_path = quota_config_default_path(repo_root)
    signals = read_quota_signals(
        config_path=config_path,
        now=now,
        agentcat_executable=executable,
        snapshot_runner=snapshot_runner,
    )
    new_target, explanation = compute_dynamic_target(default_target, signals, now=now)

    if new_target == default_target:
        agent_mix_policy = dict(agent_mix_policy)
        agent_mix_policy["quota_explanation"] = explanation
        return agent_mix_policy, explanation

    agent_mix_policy = dict(agent_mix_policy)
    agent_mix_policy["target"] = new_target
    agent_mix_policy["quota_explanation"] = explanation
    return agent_mix_policy, explanation
