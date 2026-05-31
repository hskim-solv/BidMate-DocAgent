"""Single source of truth for stripping ship-lane secrets from runner subprocess
environments (ADR 0090 env-isolation). The staging self-ship lane (_staging_ship.py)
is a SEPARATE process; runner children (claude/codex write+read lanes, omc) must never
inherit BIDMATE_SHIP_* (merge token + manifest dir + cap store + kill switch). PATH/HOME/
auth vars are preserved. Deny-by-prefix."""
from __future__ import annotations

SHIP_SECRET_ENV_PREFIX = "BIDMATE_SHIP_"


def strip_ship_secret_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of *env* with every BIDMATE_SHIP_* key removed."""
    return {k: v for k, v in env.items() if not k.startswith(SHIP_SECRET_ENV_PREFIX)}
