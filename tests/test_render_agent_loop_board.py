"""Regression guard for the agent-loop ``make 시작`` mission-control HTML board.

Covers four behaviours the renderer must hold (tests assert the renderer's
*actual* behaviour — a regression guard plus the staleness banner added here):

1. ``render()`` builds a self-contained, network-free HTML page from a synthetic
   ``--state-dir`` of ledger JSON/JSONL files (the same filenames the renderer
   loads in ``render()``).
2. ADR 0005 boundary — run-artifact / scratch *paths* surfaced via the operator
   strings that the board *does* render (session ``next_command`` and event
   ``blockers``/``warnings``) are masked to ``[redacted-run-artifact-path]`` by
   ``_sanitize_text`` / ``_RUN_ARTIFACT_PATH_RE``; the raw path never appears.
3. ADR 0005 boundary — model *free-text* payload fields the board deliberately
   never surfaces (codex ``last_message``/``stdout``/``stderr``/``prompt``/
   ``command``, cycle escalation ``guidance``, backlog ``plan``) do not leak into
   the rendered HTML; only structural metadata is exposed.
4. the top staleness banner aggregates already-computed ledger enum fields
   (session ``heartbeat_state``/``status``, lease ``status``) into at-a-glance
   counts, surfacing only counts and enum labels (ADR 0005).
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.render_agent_loop_board import (
    _RUN_ARTIFACT_PATH_RE,
    _sanitize_text,
    main,
    render,
    render_blockers_summary,
    render_event_log,
    render_staleness_banner,
)

# The sentinel ``_sanitize_text`` substitutes for a matched run-artifact path.
REDACT_MARKER = "[redacted-run-artifact-path]"


# ---------------------------------------------------------------------------
# Synthetic ledger fixtures (NEVER copy the private reports/agent_loop/active
# ledgers — every value below is fabricated). Each helper returns the in-memory
# object; ``_write_state_dir`` serialises them under a tmp_path state dir using
# the exact filenames render() loads.
# ---------------------------------------------------------------------------

# A fabricated run-artifact path + scratch branch token. Both must match
# ``_RUN_ARTIFACT_PATH_RE`` (codex_runs / patch_runs / codex[-_]scratch).
RAW_RUN_ARTIFACT_PATH = "reports/agent_loop/codex_runs/T-9999/stdout.log"
RAW_SCRATCH_BRANCH = "agent/T-9999/codex-scratch"

# Fabricated model free-text payloads that the board must NOT surface.
SECRET_LAST_MESSAGE = "FREETEXT_codex_last_message_should_never_render_42"
SECRET_STDOUT = "FREETEXT_codex_stdout_should_never_render_42"
SECRET_STDERR = "FREETEXT_codex_stderr_should_never_render_42"
SECRET_PROMPT = "FREETEXT_codex_prompt_should_never_render_42"
SECRET_COMMAND = "FREETEXT_codex_command_should_never_render_42"
SECRET_GUIDANCE = "FREETEXT_escalation_guidance_should_never_render_42"
SECRET_PLAN = "FREETEXT_backlog_plan_should_never_render_42"
SECRET_EVENT_GUIDANCE = "FREETEXT_event_guidance_should_never_render_42"


def _auto_loop_state() -> dict[str, object]:
    """auto_loop_state.json — control state + cycles (free-text guidance buried)."""
    return {
        "generated_at": "2026-06-03T00:00:00Z",
        "infinite_mode": False,
        "decision": "running",
        "execute_ship": True,
        "execute_runner": True,
        "codex_model": "gpt-5.4-codex",
        "completed_task_ids": ["T-1001"],
        "deferred_task_ids": ["T-1002"],
        "target_completed_count": 2,
        "next_task_id": "T-1003",
        "max_iterations": 8,
        "max_attempts": 3,
        "cycles": [
            {
                "iteration": 1,
                "task_id": "T-1001",
                "title": "structural cycle title",
                "gate_tier": "tier-1",
                "repair_status": "passed",
                "completion_decision": "completed",
                "repair_first_agent": "implementer",
                "repair_fallback_agent": "reviewer",
                "completed": True,
                "escalation_advisory": {
                    "tools": ["pytest", "ruff"],
                    "attempts": [1, 2],
                    "trigger": "gate-fail",
                    # Free-text guidance — must NOT be surfaced (ADR 0005).
                    "guidance": SECRET_GUIDANCE,
                },
            }
        ],
    }


def _session_registry() -> dict[str, object]:
    """session_registry.json — sessions[] + topology; next_command carries paths."""
    return {
        "generated_at": "2026-06-03T00:00:00Z",
        "topology": "expanded-eight",
        "sessions": [
            {
                "role": "orchestrator",
                "session_id": "sess-orch",
                "status": "active",
                "heartbeat_state": "fresh",
                "ship_gate": "auto-pass",
                "task_id": "T-1001",
                "write_lease_owner": True,
                # next_command IS rendered, but run-artifact path args are masked.
                "next_command": (
                    f"python3 agent_loop.py run --log {RAW_RUN_ARTIFACT_PATH} "
                    f"--branch {RAW_SCRATCH_BRANCH}"
                ),
                "lanes": {
                    "impl": {"status": "active", "wu_spent_rolling": 3},
                },
            },
            {
                "role": "reviewer",
                "session_id": "sess-rev",
                "status": "stale",
                "heartbeat_state": "stale",
                "ship_gate": "pending",
                "task_id": "T-1003",
                "write_lease_owner": False,
                "lanes": {},
            },
        ],
    }


def _codex_runner_state() -> dict[str, object]:
    """codex_runner_state.json — worker health; free-text payload fields buried."""
    return {
        "generated_at": "2026-06-03T00:00:00Z",
        "auth_status": "Logged in",
        "sandbox": "read-only",
        "decision": "running",
        "sessions": [
            {
                "role": "implementer",
                "session_id": "codex-impl",
                "status": "running",
                "ship_gate": "auto-pass",
                "task_id": "T-1001",
                "pid": 4242,
                # Model free-text payloads — must NOT be surfaced (ADR 0005).
                "last_message": SECRET_LAST_MESSAGE,
                "stdout": SECRET_STDOUT,
                "stderr": SECRET_STDERR,
                "prompt": SECRET_PROMPT,
                "command": SECRET_COMMAND,
            }
        ],
    }


def _backlog_handoff_queue() -> dict[str, object]:
    """backlog_handoff_queue.json — waiting tasks; plan/hydrated_plan are free-text."""
    return {
        "generated_at": "2026-06-03T00:00:00Z",
        "tasks": [
            {
                "task_id": "T-1003",
                "title": "structural backlog title",
                "status": "backlog",
                "missing_fields": ["owner_role"],
                "invalid_fields": [],
                # Free-text plan fields — must NOT be surfaced (ADR 0005).
                "plan": SECRET_PLAN,
                "hydrated_plan": SECRET_PLAN,
            }
        ],
    }


def _events() -> list[dict[str, object]]:
    """events.jsonl rows — blockers/warnings ARE rendered (masked); guidance/prompt
    /command/stdout/stderr are deliberately skipped free-text fields."""
    return [
        {
            "ts": "2026-06-03T00:00:01Z",
            "event": "cycle",
            "decision": "completed",
            "task_id": "T-1001",
            "branch": "chore/issue-1001",
            "blockers": [],
            "warnings": [],
        },
        {
            "ts": "2026-06-03T00:00:02Z",
            "event": "cycle",
            "decision": "blocked",
            "task_id": "T-1003",
            # blocker text mentions a run-artifact path → must be masked, but the
            # surrounding diagnostic text is still surfaced.
            "blockers": [f"gate failed reading {RAW_RUN_ARTIFACT_PATH}"],
            "warnings": [f"scratch dir {RAW_SCRATCH_BRANCH} left behind"],
            # Structural scalar field NOT in the skip set: render_event_log
            # surfaces it via the extra_fields path. Its value embeds a
            # run-artifact path → _sanitize_text must mask it there too
            # (Low-2 defense-in-depth, ADR 0005).
            "scratch_log": RAW_RUN_ARTIFACT_PATH,
            # Free-text fields the event log explicitly skips (ADR 0005).
            "guidance": SECRET_EVENT_GUIDANCE,
            "prompt": SECRET_PROMPT,
            "command": SECRET_COMMAND,
            "stdout": SECRET_STDOUT,
            "stderr": SECRET_STDERR,
            "last_message": SECRET_LAST_MESSAGE,
        },
    ]


def _agent_mix() -> dict[str, object]:
    return {
        "generated_at": "2026-06-03T00:00:00Z",
        "mode": "hybrid",
        "gate_policy": "tiered",
        "policy": {
            "target": {"claude": 9, "codex": 1},
            "quota_explanation": "claude=40% codex=10% within window",
            "window": {"size": 20, "type": "rolling"},
        },
        "rolling": {"claude": 8, "codex": 2},
    }


def _leases() -> dict[str, object]:
    return {
        "leases": [
            {
                "lease_id": "lease-aaaa",
                "status": "active",
                "task_id": "T-1001",
                "owner_role": "orchestrator",
                "active_agent": "implementer",
                "expires_at": "2026-06-03T01:00:00Z",
            }
        ]
    }


def _loop_state() -> dict[str, object]:
    return {
        "gate": {
            "gate": "auto-pass",
            "severity": "low",
            "signals": ["clean-2pass"],
            "next_safe_command": "make ship-arm",
        }
    }


# The complete set of fabricated free-text secrets that must never render.
_FREE_TEXT_SECRETS = (
    SECRET_LAST_MESSAGE,
    SECRET_STDOUT,
    SECRET_STDERR,
    SECRET_PROMPT,
    SECRET_COMMAND,
    SECRET_GUIDANCE,
    SECRET_PLAN,
    SECRET_EVENT_GUIDANCE,
)


def _write_state_dir(root: Path) -> Path:
    """Serialise the synthetic ledgers under ``root/active`` and return that dir."""
    state_dir = root / "active"
    state_dir.mkdir(parents=True, exist_ok=True)

    (state_dir / "auto_loop_state.json").write_text(
        json.dumps(_auto_loop_state()), encoding="utf-8"
    )
    (state_dir / "session_registry.json").write_text(
        json.dumps(_session_registry()), encoding="utf-8"
    )
    (state_dir / "codex_runner_state.json").write_text(
        json.dumps(_codex_runner_state()), encoding="utf-8"
    )
    (state_dir / "backlog_handoff_queue.json").write_text(
        json.dumps(_backlog_handoff_queue()), encoding="utf-8"
    )
    (state_dir / "agent_mix.json").write_text(
        json.dumps(_agent_mix()), encoding="utf-8"
    )
    (state_dir / "leases.json").write_text(
        json.dumps(_leases()), encoding="utf-8"
    )
    (state_dir / "loop_state.json").write_text(
        json.dumps(_loop_state()), encoding="utf-8"
    )
    (state_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(ev) for ev in _events()) + "\n", encoding="utf-8"
    )
    return state_dir


def _render_to_html(tmp_path: Path, *, auto_refresh: bool = True) -> str:
    """Run render() against the synthetic state dir and return the written HTML."""
    state_dir = _write_state_dir(tmp_path)
    out = tmp_path / "loop_board.html"
    render(state_dir, out, auto_refresh=auto_refresh)
    return out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Render basics — self-contained, network-free HTML with the core structure.
# ---------------------------------------------------------------------------

def test_render_writes_self_contained_html_with_core_sections(tmp_path: Path) -> None:
    html = _render_to_html(tmp_path)

    # Document shell + inline (not externally fetched) CSS/JS.
    assert "<!doctype html>" in html
    assert "<html lang=\"ko\">" in html
    assert "AGENT" in html and "MISSION CONTROL" in html
    assert "<style>" in html  # CSS is inlined, not a <link rel=stylesheet> to it

    # Major sections the IA order renders top-to-bottom.
    assert "Mission Status" in html
    assert "Activity Trend" in html
    assert "Decision Mix" in html
    assert "Cycles Timeline" in html
    assert "Agent Topology" in html
    assert "Workers &amp; Queue" in html
    assert "Blockers &amp; Agent Mix" in html
    assert "Event Log" in html
    assert "Detail" in html

    # Structural fixture metadata is surfaced (roles / task ids / topology).
    assert "orchestrator" in html
    assert "T-1001" in html
    assert "expanded-eight" in html


def test_render_is_network_free_no_remote_data_fetch(tmp_path: Path) -> None:
    # The only allowed external references are the optional CDN font + mermaid
    # script (graceful offline degradation). No fixture/ledger data is fetched
    # from the network: render() only reads the local state_dir.
    state_dir = _write_state_dir(tmp_path)
    out = tmp_path / "board.html"

    # render() returns None and writes the file; a successful write with the
    # state dir as the sole input proves no network round-trip is required.
    result = render(state_dir, out, auto_refresh=False)
    assert result is None
    assert out.exists()

    html = out.read_text(encoding="utf-8")
    # --no-refresh path: no auto-refresh meta tag, static indicator instead.
    assert "http-equiv=\"refresh\"" not in html
    assert "STATIC" in html


def test_cli_main_writes_html_file(tmp_path: Path) -> None:
    state_dir = _write_state_dir(tmp_path)
    out = tmp_path / "cli_board.html"

    rc = main(
        ["--state-dir", str(state_dir), "--out", str(out), "--no-refresh"]
    )

    assert rc == 0
    assert out.exists()
    assert "MISSION CONTROL" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. Boundary guard — run-artifact / scratch paths are masked.
# ---------------------------------------------------------------------------

def test_sanitize_text_masks_run_artifact_and_scratch_paths() -> None:
    # Unit-level guard on the masking primitive the board relies on.
    assert _RUN_ARTIFACT_PATH_RE.search(RAW_RUN_ARTIFACT_PATH) is not None
    assert _RUN_ARTIFACT_PATH_RE.search(RAW_SCRATCH_BRANCH) is not None

    masked = _sanitize_text(f"cmd --log {RAW_RUN_ARTIFACT_PATH} ok")
    assert RAW_RUN_ARTIFACT_PATH not in masked
    assert REDACT_MARKER in masked


def test_rendered_html_masks_run_artifact_paths(tmp_path: Path) -> None:
    html = _render_to_html(tmp_path)

    # The raw run-artifact path / scratch branch token (injected via session
    # next_command AND event blockers/warnings) must never reach the HTML.
    assert RAW_RUN_ARTIFACT_PATH not in html
    assert RAW_SCRATCH_BRANCH not in html
    # The codex_runs / codex-scratch tokens themselves must be gone too.
    assert "codex_runs" not in html
    assert "codex-scratch" not in html
    # The redaction sentinel proves masking ran (not mere omission of the panel).
    assert REDACT_MARKER in html


# ---------------------------------------------------------------------------
# 3. Boundary guard — free-text payload fields never leak.
# ---------------------------------------------------------------------------

def test_rendered_html_does_not_expose_free_text_payloads(tmp_path: Path) -> None:
    html = _render_to_html(tmp_path)

    # None of the fabricated model free-text payloads (codex last_message/stdout/
    # stderr/prompt/command, cycle escalation guidance, backlog plan, event
    # guidance) may appear — only structural metadata is exposed (ADR 0005).
    for secret in _FREE_TEXT_SECRETS:
        assert secret not in html, f"free-text payload leaked into board: {secret}"


def test_structural_metadata_still_surfaced_alongside_redaction(tmp_path: Path) -> None:
    # Guard against an over-broad fix that would redact structural fields too:
    # the blocked event's *diagnostic* text and structural ids must remain even
    # though the embedded run-artifact path within them is masked.
    html = _render_to_html(tmp_path)

    assert "gate failed reading" in html  # blocker diagnostic text retained
    assert "scratch dir" in html  # warning diagnostic text retained
    assert "T-1003" in html  # task id from the blocked event/backlog
    assert "implementer" in html  # worker role still rendered

    # The blocked event's diagnostic blocker/warning text is rendered in TWO
    # independent sections (the event log AND the aggregated blockers summary).
    # The full-page assertions above pass as long as *either* section renders
    # the text, so they cannot catch an over-redaction regression isolated to
    # one section. Verify each section's fragment independently so a break in
    # exactly one section fails this guard.
    events = _events()
    event_log = render_event_log(events)
    blockers_summary = render_blockers_summary(events)

    for section_name, fragment in (
        ("event_log", event_log),
        ("blockers_summary", blockers_summary),
    ):
        # Diagnostic text + structural id survive in this section …
        assert "gate failed reading" in fragment, (
            f"{section_name} dropped the blocker diagnostic text"
        )
        assert "scratch dir" in fragment, (
            f"{section_name} dropped the warning diagnostic text"
        )
        # … and the embedded run-artifact/scratch path is masked here, not in
        # the *other* section: each section must carry its own redaction marker
        # and must never leak the raw path token.
        assert RAW_RUN_ARTIFACT_PATH not in fragment, (
            f"{section_name} leaked the raw run-artifact path"
        )
        assert RAW_SCRATCH_BRANCH not in fragment, (
            f"{section_name} leaked the raw scratch branch token"
        )
        assert REDACT_MARKER in fragment, (
            f"{section_name} did not mask the embedded path (no redact marker)"
        )

    # Low-2 (extra_fields scalar masking): the event fixture includes a structural
    # scalar field ``scratch_log: RAW_RUN_ARTIFACT_PATH`` that is NOT in the skip
    # set and not a list/dict, so render_event_log surfaces it via the extra_fields
    # path (display cell + data-search blob). _sanitize_text must mask it there too.
    # Verify: raw token absent from the event_log fragment (covers both the <li>
    # display cell and the data-search="" searchable blob).
    assert RAW_RUN_ARTIFACT_PATH not in event_log, (
        "extra_fields scalar value leaked raw run-artifact path in event_log "
        "(display cell or data-search blob — Low-2 regression)"
    )
    assert "codex_runs" not in event_log, (
        "extra_fields scalar value leaked 'codex_runs' token in event_log "
        "(Low-2 regression)"
    )


# ---------------------------------------------------------------------------
# 4. Staleness banner — aggregate session/lease health at a glance.
# ---------------------------------------------------------------------------

def test_staleness_banner_aggregates_session_lease_counts(tmp_path: Path) -> None:
    # Counts already-computed ledger enum fields (heartbeat_state/status, lease
    # status) — deterministic (no now() recomputation), ADR 0005 (counts/enums
    # only). Fixture: 2 sessions (1 active/fresh-hb, 1 stale/stale-hb) + 1 lease.
    reg = _session_registry()
    leases = _leases()

    banner = render_staleness_banner(reg, leases)
    assert "sessions 2" in banner
    assert "hb-stale 1/2" in banner      # reviewer heartbeat_state == "stale"
    assert "status-stale 1" in banner    # reviewer status == "stale"
    assert "leases 1" in banner
    assert "STALENESS" in banner         # warn headline when any stale present

    # Surfaced at the top of the full render.
    html = _render_to_html(tmp_path)
    assert "session / lease at a glance" in html

    # ADR 0005: the banner emits no free-text secret.
    for secret in _FREE_TEXT_SECRETS:
        assert secret not in banner, f"banner leaked free-text: {secret}"


def test_staleness_banner_healthy_when_no_stale() -> None:
    # All-fresh sessions and no expired lease → ✓ HEALTHY, no warn count chips.
    healthy = {
        "sessions": [
            {"role": "orchestrator", "session_id": "s1",
             "status": "active", "heartbeat_state": "fresh"},
        ],
    }
    banner = render_staleness_banner(healthy, {"leases": []})
    assert "HEALTHY" in banner
    assert "sessions 1" in banner
    assert "hb-stale" not in banner
    assert "status-stale" not in banner
    assert "expired-lease" not in banner


def test_staleness_banner_empty_when_no_data() -> None:
    # No sessions and no leases → banner renders nothing (empty string).
    assert render_staleness_banner({}, {}) == ""
