"""Render a self-contained HTML dashboard for the agent-loop multi-session state.

Supersedes the built-in `agent_loop.py dashboard-html` which wraps markdown in
<pre> and has no multi-session visibility.

This board is information-architecture-first: it reads the loop's *core control
state* (auto_loop_state: cycle progress, ship on/off, next task), the decision
*distribution* and *trend* (events.jsonl), worker health (codex_runner_state),
and the waiting queue (backlog_handoff_queue) — not just a flat dump of rows.

CLI:
    python3 scripts/render_agent_loop_board.py
    python3 scripts/render_agent_loop_board.py --state-dir reports/agent_loop/active
    python3 scripts/render_agent_loop_board.py --out /tmp/board.html --no-refresh

Output: self-contained HTML (inline CSS + minimal inline JS, CDN mermaid with
offline graceful degradation).

Data boundary (ADR 0005): reads only from --state-dir (gitignored private). The
output HTML path must also stay gitignored (already covered by reports/agent_loop/).
Free-text payloads (codex stdout/stderr/prompt/last_message/command, auto_loop
cycle reports, backlog plan/hydrated_plan) are intentionally NOT surfaced — only
structural metadata (id / role / status / decision / counts / titles).
"""
from __future__ import annotations

import argparse
import datetime as _dt
from datetime import timezone as _tz
import html as _html
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = REPO_ROOT / "reports" / "agent_loop" / "active"
DEFAULT_OUT = REPO_ROOT / "reports" / "agent_loop" / "loop_board.html"

SEVERITY_TONE = {
    "high": "danger",
    "medium": "warn",
    "low": "ok",
    "": "neutral",
}

DECISION_TONE = {
    "blocked": "danger",
    "error": "danger",
    "limit-reached": "warn",
    "planned": "accent",
    "running": "accent",
    "completed": "ok",
    "applied": "ok",
    "proposed": "accent",
}

STATUS_TONE = {
    "passed": "ok",
    "blocked": "danger",
    "error": "danger",
    "pending": "neutral",
    "ready": "ok",
    "idle": "neutral",
    "stale": "warn",
    "active": "ok",
    "expired": "neutral",
    "planned": "accent",
    "running": "accent",
    "proposed": "accent",
    "completed": "ok",
    "backlog": "neutral",
    "recovery-needed": "danger",
}


# ---------------------------------------------------------------------------
# HTML primitives (no external deps)
# ---------------------------------------------------------------------------

def esc(v: object) -> str:
    """Escape for HTML element content (and attributes — quote=True)."""
    return _html.escape(str(v), quote=True)


def badge(label: object, *, tone: str = "neutral") -> str:
    return f'<span class="badge {esc(tone)}">{esc(label)}</span>'


def panel(title: str, body: str, *, extra_class: str = "", sub: str = "") -> str:
    cls = f"panel {extra_class}".strip()
    sub_html = f'<span class="panel-sub">{esc(sub)}</span>' if sub else ""
    return (
        f'<section class="{esc(cls)}">'
        f"<h2>{esc(title)}{sub_html}</h2>{body}</section>"
    )


def detail_row(summary: str, body: str) -> str:
    return f"<details><summary>{summary}</summary><div class='detail-body'>{body}</div></details>"


# ---------------------------------------------------------------------------
# Repo-relative path helper
# ---------------------------------------------------------------------------

def repo_rel(path: str) -> str:
    """Return path relative to REPO_ROOT, or unchanged if outside."""
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return path


# ---------------------------------------------------------------------------
# Data loading (graceful on missing / empty files)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_obj(path: Path) -> dict:
    """Load a JSON file that must be a dict object.

    Returns an empty dict when the file is missing, unreadable, or
    contains a non-dict JSON value (e.g. a list). This keeps callers
    type-safe: they always receive a dict and can call .get() freely.
    """
    data = _load_json(path)
    if isinstance(data, dict):
        return data
    return {}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if raw:
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        lines.append(obj)
                except Exception:
                    pass
    except Exception:
        pass
    return lines


# ---------------------------------------------------------------------------
# Type-defensive accessors (all .get() results are Any → narrow explicitly)
# ---------------------------------------------------------------------------

def _as_list(value: object) -> list[Any]:
    """Return value if it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict[str, Any]:
    """Return value if it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def _dict_items(value: object) -> list[tuple[str, Any]]:
    """Return .items() of a dict-typed value, else empty list."""
    if isinstance(value, dict):
        return list(value.items())
    return []


# Run-artifact directories whose *contents* are model free-text (stdout/stderr/
# last_message/prompt) and per-task scratch worktrees/branches. An operator
# command or an event blocker/warning may legitimately reference a path under
# one of these; we mask the token so the dashboard never surfaces even the
# filesystem layout of redacted run artifacts (ADR 0005 minimisation). Matches
# both `codex_runs/...` paths and `agent/<task>/codex-scratch` branch tokens.
_RUN_ARTIFACT_PATH_RE = re.compile(
    r"\S*(?:codex_runs|patch_runs|codex[-_]scratch)\S*",
    re.IGNORECASE,
)


def _sanitize_text(text: str) -> str:
    """Mask run-artifact / scratch path tokens inside an operator-facing string.

    Used for `next_command` (a fixed agent_loop.py invocation) and for event
    blocker/warning lines (diagnostic, surfaced by the original board) — both
    are operator-facing, but any argument that points into a codex run-artifact
    dir or a per-task scratch worktree/branch is replaced with a sentinel before
    escaping so the path layout of redacted artifacts is never exposed.
    """
    return _RUN_ARTIFACT_PATH_RE.sub("[redacted-run-artifact-path]", text)


# ---------------------------------------------------------------------------
# Quota extraction from quota_explanation string
# ---------------------------------------------------------------------------

_QUOTA_RE = re.compile(
    r"claude=(\d+)%.*?codex=(\d+)%",
    re.IGNORECASE,
)


def _parse_quota(explanation: str) -> tuple[int | None, int | None]:
    """Return (claude_pct, codex_pct) from quota_explanation string."""
    m = _QUOTA_RE.search(explanation)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


# ---------------------------------------------------------------------------
# Time-series bucketing for events (stdlib only)
# ---------------------------------------------------------------------------

def _bucket_key(ts: str) -> str:
    """Return a YYYY-MM-DD bucket key from an ISO8601 timestamp string.

    Falls back to the leading 10-char slice when fromisoformat cannot parse;
    returns "?" when the value is unusable. stdlib only.
    """
    if not isinstance(ts, str) or len(ts) < 10:
        return "?"
    raw = ts[:10]
    try:
        # Accept trailing 'Z' which fromisoformat rejects on older runtimes.
        norm = ts.replace("Z", "+00:00")
        return _dt.datetime.fromisoformat(norm).strftime("%Y-%m-%d")
    except Exception:
        return raw


def build_activity_buckets(
    events: list[dict],
) -> tuple[list[str], dict[str, Counter[str]], int]:
    """Bucket events by date; per bucket count decisions.

    Returns (sorted_bucket_keys, {bucket: Counter[decision]}, max_total).
    """
    buckets: dict[str, Counter[str]] = {}
    for ev in events:
        key = _bucket_key(str(ev.get("ts", "")))
        decision = str(ev.get("decision", "") or "none")
        buckets.setdefault(key, Counter())[decision] += 1
    keys = sorted(buckets.keys())
    max_total = max((sum(c.values()) for c in buckets.values()), default=0)
    return keys, buckets, max_total


def decision_distribution(events: list[dict]) -> Counter[str]:
    """Count decision values across all events."""
    c: Counter[str] = Counter()
    for ev in events:
        d = str(ev.get("decision", "") or "none")
        c[d] += 1
    return c


# ---------------------------------------------------------------------------
# KPI helpers (zero-division guarded)
# ---------------------------------------------------------------------------

def _pct(numer: int, denom: int) -> int:
    """Integer percentage with a zero-division guard."""
    if denom <= 0:
        return 0
    return round(numer / denom * 100)


def _kpi_tone(pct: int, *, good_high: bool = True, hi: int = 60, lo: int = 30) -> str:
    """Map a percentage to a tone. good_high=False inverts (low pct is good)."""
    if not good_high:
        if pct >= hi:
            return "danger"
        if pct >= lo:
            return "warn"
        return "ok"
    if pct >= hi:
        return "ok"
    if pct >= lo:
        return "warn"
    return "danger"


# ---------------------------------------------------------------------------
# 1. Console bar (rendered inline in render(); helper builds the chips)
# ---------------------------------------------------------------------------

def build_console_chips(auto: dict, runner: dict) -> str:
    """Build the live status chip strip for the console bar."""
    infinite = bool(auto.get("infinite_mode", False))
    decision = str(auto.get("decision", "—") or "—")
    ship = bool(auto.get("execute_ship", False))
    runner_on = bool(auto.get("execute_runner", False))
    model = str(auto.get("codex_model", "—") or "—")
    sandbox = str(runner.get("sandbox", "—") or "—")

    mode_tone = "accent" if infinite else "neutral"
    mode_label = "INFINITE" if infinite else "BOUNDED"
    d_tone = DECISION_TONE.get(decision, "neutral")
    ship_tone = "ok" if ship else "warn"
    ship_label = "SHIP ON" if ship else "SHIP OFF"
    runner_tone = "ok" if runner_on else "neutral"
    runner_label = "RUNNER ON" if runner_on else "RUNNER OFF"

    chips = [
        ("MODE", mode_label, mode_tone),
        ("DECISION", decision, d_tone),
        ("SHIP", ship_label, ship_tone),
        ("RUNNER", runner_label, runner_tone),
        ("SANDBOX", sandbox, "accent" if sandbox == "read-only" else "warn"),
        ("MODEL", model, "neutral"),
    ]
    out = []
    for label, value, tone in chips:
        out.append(
            f'<span class="chip {esc(tone)}">'
            f'<span class="chip-k">{esc(label)}</span>'
            f'<span class="chip-v">{esc(value)}</span></span>'
        )
    return f'<div class="console-chips">{"".join(out)}</div>'


# ---------------------------------------------------------------------------
# 2. Mission status — top KPI strip
# ---------------------------------------------------------------------------

def render_mission_status(
    auto: dict, runner: dict, registry: dict, events: list[dict]
) -> str:
    """Section 2: at-a-glance KPI strip — the loop's health in one row."""
    completed_ids = _as_list(auto.get("completed_task_ids"))
    deferred_ids = _as_list(auto.get("deferred_task_ids"))
    target = auto.get("target_completed_count", 0)
    target_n = target if isinstance(target, int) else 0
    completed_n = len(completed_ids)

    # decision blocked rate
    dist = decision_distribution(events)
    total_ev = sum(dist.values())
    blocked_n = dist.get("blocked", 0)
    blocked_rate = _pct(blocked_n, total_ev)

    # sessions stale
    sessions = _as_list(registry.get("sessions"))
    stale_n = sum(1 for s in sessions if _as_dict(s).get("status") == "stale")
    total_sessions = len(sessions)
    stale_rate = _pct(stale_n, total_sessions)

    next_task = auto.get("next_task_id")
    next_label = str(next_task) if next_task else "—"

    max_iter = auto.get("max_iterations", "—")
    max_att = auto.get("max_attempts", "—")
    auth = str(runner.get("auth_status", "—") or "—")

    # completion ratio tone
    comp_tone = "ok" if (target_n and completed_n >= target_n) else "warn"

    cards = [
        _kpi_card(
            "COMPLETED", f"{completed_n}/{target_n}",
            f"{len(deferred_ids)} deferred", comp_tone,
        ),
        _kpi_card(
            "BLOCKED RATE", f"{blocked_rate}%",
            f"{blocked_n} of {total_ev} events",
            _kpi_tone(blocked_rate, good_high=False),
        ),
        _kpi_card(
            "SESSIONS STALE", f"{stale_n}/{total_sessions}",
            f"{stale_rate}% of pool",
            _kpi_tone(stale_rate, good_high=False),
        ),
        _kpi_card(
            "NEXT TASK", next_label,
            "queue exhausted" if not next_task else "queued", "neutral",
        ),
        _kpi_card(
            "ITER LIMIT", f"{esc(max_iter)}",
            f"max attempts {esc(max_att)}", "neutral",
        ),
        _kpi_card(
            "CODEX AUTH", "OK" if "Logged in" in auth else "CHECK",
            auth, "ok" if "Logged in" in auth else "warn",
        ),
    ]
    grid = f'<div class="kpi-strip">{"".join(cards)}</div>'
    return panel("Mission Status", grid, extra_class="status-panel")


def _kpi_card(label: str, value: str, sub: str, tone: str) -> str:
    return (
        f'<article class="kpi {esc(tone)}">'
        f'<span class="kpi-label">{esc(label)}</span>'
        f'<strong class="kpi-val">{value}</strong>'
        f'<span class="kpi-sub">{esc(sub)}</span></article>'
    )


# ---------------------------------------------------------------------------
# 3a. Activity trend — stacked mini bar chart by date bucket (pure CSS)
# ---------------------------------------------------------------------------

def render_activity_trend(events: list[dict]) -> str:
    """Section 3a: per-date stacked decision bars (CSS, no SVG)."""
    if not events:
        return panel(
            "Activity Trend",
            "<p class='empty'>데이터 없음 (events.jsonl 없거나 비어 있음)</p>",
        )

    keys, buckets, max_total = build_activity_buckets(events)
    if not keys or max_total <= 0:
        return panel("Activity Trend", "<p class='empty'>버킷 데이터 없음</p>")

    # stable decision order for stacking (danger-heavy at bottom)
    order = ["blocked", "error", "limit-reached", "planned",
             "running", "applied", "completed", "none"]

    cols = []
    for key in keys:
        counter = buckets[key]
        total = sum(counter.values())
        # height proportion against the busiest bucket
        col_h = round(total / max_total * 100)
        seen = list(counter.keys())
        ordered = [d for d in order if d in counter] + [
            d for d in seen if d not in order
        ]
        segs = []
        for d in ordered:
            n = counter[d]
            seg_h = round(n / total * 100) if total else 0
            tone = DECISION_TONE.get(d, "neutral")
            segs.append(
                f'<span class="trend-seg {esc(tone)}" '
                f'style="height:{seg_h}%" '
                f'title="{esc(d)}: {esc(n)}"></span>'
            )
        cols.append(
            f'<div class="trend-col">'
            f'<div class="trend-bar" style="height:{col_h}%">'
            f'{"".join(reversed(segs))}</div>'
            f'<span class="trend-total">{esc(total)}</span>'
            f'<span class="trend-xlabel">{esc(key[5:])}</span>'
            f"</div>"
        )

    chart = (
        f'<div class="trend-chart" role="img" '
        f'aria-label="events per day by decision">{"".join(cols)}</div>'
    )
    legend = _decision_legend(["blocked", "completed", "applied",
                               "planned", "running", "limit-reached"])
    sub = f"{len(events)} events · {keys[0]} → {keys[-1]}"
    return panel("Activity Trend", chart + legend, sub=sub)


def _decision_legend(decisions: list[str]) -> str:
    items = []
    for d in decisions:
        tone = DECISION_TONE.get(d, "neutral")
        items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch {esc(tone)}"></span>{esc(d)}</span>'
        )
    return f'<div class="legend">{"".join(items)}</div>'


# ---------------------------------------------------------------------------
# 3b. Decision mix — horizontal distribution bars
# ---------------------------------------------------------------------------

def render_decision_mix(events: list[dict]) -> str:
    """Section 3b: decision distribution as horizontal proportion bars."""
    if not events:
        return panel(
            "Decision Mix", "<p class='empty'>데이터 없음</p>"
        )
    dist = decision_distribution(events)
    if not dist:
        return panel("Decision Mix", "<p class='empty'>decision 없음</p>")

    total = sum(dist.values())
    rows = []
    for decision, cnt in dist.most_common():
        tone = DECISION_TONE.get(decision, "neutral")
        pct = _pct(cnt, total)
        rows.append(
            f'<div class="mix-row">'
            f'<span class="mix-name {esc(tone)}">{esc(decision)}</span>'
            f'<div class="mix-track">'
            f'<div class="mix-fill {esc(tone)}" style="width:{pct}%"></div>'
            f"</div>"
            f'<span class="mix-count">{esc(cnt)}</span>'
            f'<span class="mix-pct">{pct}%</span>'
            f"</div>"
        )
    body = f'<div class="mix-list">{"".join(rows)}</div>'
    sub = f"{total} decisions"
    return panel("Decision Mix", body, sub=sub)


# ---------------------------------------------------------------------------
# 4. Cycles timeline — per-iteration loop progress (auto_loop_state.cycles)
# ---------------------------------------------------------------------------

def render_cycles_timeline(auto: dict) -> str:
    """Section 4: vertical timeline of the auto-loop's cycles."""
    cycles = _as_list(auto.get("cycles"))
    if not cycles:
        return panel(
            "Cycles Timeline",
            "<p class='empty'>데이터 없음 (auto_loop_state.cycles 비어 있음)</p>",
        )

    items = []
    for raw in cycles:
        c = _as_dict(raw)
        iteration = c.get("iteration", "—")
        task_id = str(c.get("task_id", "—") or "—")
        title = str(c.get("title", "") or "")
        gate_tier = str(c.get("gate_tier", "") or "")
        repair_status = str(c.get("repair_status", "") or "")
        completion = str(c.get("completion_decision", "") or "")
        first_agent = str(c.get("repair_first_agent", "") or "")
        fallback_agent = str(c.get("repair_fallback_agent", "") or "")
        completed = bool(c.get("completed", False))

        r_tone = STATUS_TONE.get(repair_status, "neutral")
        node_tone = "ok" if completed else r_tone
        dot_pulse = " pulse" if completed else ""

        # agent relay chip (structural only — no free-text)
        relay = ""
        if first_agent:
            relay = f'<span class="relay">{esc(first_agent)}'
            if fallback_agent and fallback_agent != first_agent:
                relay += f' <span class="relay-arrow">&rarr;</span> {esc(fallback_agent)}'
            relay += "</span>"

        # escalation advisory → details, but ONLY structural fields (tools/attempts).
        # The free-text `guidance` is intentionally excluded (ADR 0005 minimisation).
        adv = _as_dict(c.get("escalation_advisory"))
        adv_html = ""
        if adv:
            tools = _as_list(adv.get("tools"))
            attempts = _as_list(adv.get("attempts"))
            trigger = str(adv.get("trigger", "") or "")
            tool_badges = " ".join(
                badge(str(t), tone="accent") for t in tools
            )
            att_badges = " ".join(
                badge(str(a), tone="neutral") for a in attempts
            )
            inner = (
                f"<p><strong>Escalation tools:</strong> {tool_badges}</p>"
                f"<p><strong>Attempts:</strong> {att_badges}</p>"
            )
            if trigger:
                inner += f"<p><strong>Trigger:</strong> {esc(trigger)}</p>"
            adv_html = detail_row("&#9656; escalation advisory", inner)

        meta = (
            f"{badge(repair_status or '—', tone=r_tone)} "
            f"{badge(gate_tier or '—', tone='neutral')} "
            f"{badge(completion or '—', tone=DECISION_TONE.get(completion, 'neutral'))}"
        )

        items.append(
            f'<li class="cycle-item {esc(node_tone)}">'
            f'<span class="cycle-node {esc(node_tone)}{dot_pulse}">'
            f'<span class="cycle-iter">{esc(iteration)}</span></span>'
            f'<div class="cycle-body">'
            f'<div class="cycle-head">'
            f'<code class="cycle-task">{esc(task_id)}</code>'
            f"{relay}</div>"
            f'<p class="cycle-title">{esc(title)}</p>'
            f'<div class="cycle-meta">{meta}</div>'
            f"{adv_html}"
            f"</div></li>"
        )

    blocked = sum(
        1 for c in cycles if _as_dict(c).get("repair_status") == "blocked"
    )
    done = sum(
        1 for c in cycles if _as_dict(c).get("completed") is True
    )
    sub = f"{len(cycles)} iterations · {done} completed · {blocked} blocked"
    return panel(
        "Cycles Timeline",
        f'<ul class="cycle-timeline">{"".join(items)}</ul>',
        sub=sub,
    )


# ---------------------------------------------------------------------------
# 5. Agent topology — session grid (structural) + mermaid map
# ---------------------------------------------------------------------------

def render_session_grid(registry: dict) -> str:
    """Section 5a: session cards from session_registry.json."""
    sessions = _as_list(registry.get("sessions"))
    topology = str(registry.get("topology", "") or "")

    if not sessions:
        return (
            "<p class='empty'>데이터 없음 "
            "(session_registry.json 없거나 sessions[]가 비어 있음)</p>"
        )

    cards = []
    for raw in sessions:
        s = _as_dict(raw)
        role = str(s.get("role", "—") or "—")
        sid = str(s.get("session_id", "—") or "—")
        status = str(s.get("status", "—") or "—")
        tone = STATUS_TONE.get(status, "neutral")
        hb_state = str(s.get("heartbeat_state", "") or "")
        ship_gate = str(s.get("ship_gate", "") or "")
        task_id = str(s.get("task_id", "—") or "—")
        is_lease_owner = bool(s.get("write_lease_owner", False))
        next_cmd = str(s.get("next_command", "") or "")

        lanes_html = ""
        for lane_name, lane_raw in _dict_items(s.get("lanes")):
            lane_info = _as_dict(lane_raw)
            lane_status = str(lane_info.get("status", "—") or "—")
            wu = lane_info.get("wu_spent_rolling", 0)
            lt = STATUS_TONE.get(lane_status, "neutral")
            lanes_html += (
                f"<span class='lane-pill {esc(lt)}'>"
                f"{esc(lane_name)}: {esc(lane_status)} "
                f"<em>wu={esc(wu)}</em></span> "
            )

        lease_badge = badge("lease-owner", tone="accent") if is_lease_owner else ""
        hb_badge = badge(f"hb:{hb_state}", tone="warn") if hb_state == "stale" else ""
        dot_pulse = " pulse" if tone in {"ok", "accent"} else ""

        body = (
            f'<div class="session-meta">'
            f"{badge(status, tone=tone)} {badge(ship_gate or '—', tone='neutral')} "
            f"{lease_badge} {hb_badge}</div>"
            f'<div class="session-lanes">{lanes_html}</div>'
            f'<div class="session-detail">task: <code>{esc(task_id)}</code></div>'
        )
        # next_command is an operator-facing fixed command (a documented
        # agent_loop.py invocation), not model free-text → safe to surface,
        # but any run-artifact path argument is masked first (ADR 0005).
        if next_cmd:
            body += (
                f"<details><summary>&#9656; next_command</summary>"
                f"<code class='cmd-block'>{esc(_sanitize_text(next_cmd))}</code></details>"
            )

        cards.append(
            f'<article class="session-card {esc(tone)}">'
            f'<header><span class="role-wrap"><span class="dot {esc(tone)}{dot_pulse}"></span>'
            f'<strong>{esc(role)}</strong></span>'
            f'<span class="sid">{esc(sid)}</span></header>'
            f"{body}</article>"
        )

    topo_badge = (
        f"<p class='topo-line'>TOPOLOGY {badge(topology, tone='accent')}</p>"
        if topology else ""
    )
    return topo_badge + f'<div class="session-grid">{"".join(cards)}</div>'


def render_topology_mermaid(registry: dict) -> str:
    """Section 5b: expanded-eight topology via Mermaid flowchart."""
    sessions = _as_list(registry.get("sessions"))

    nodes: list[tuple[str, str, str]] = []
    for raw in sessions:
        s = _as_dict(raw)
        sid = str(s.get("session_id", "unknown") or "unknown")
        role = str(s.get("role", sid) or sid)
        status = str(s.get("status", "") or "")
        tone = STATUS_TONE.get(status, "neutral")
        node_id = re.sub(r"[^a-zA-Z0-9_]", "_", sid)
        label = f"{role}\\n[{sid}]\\nstatus={status}"
        nodes.append((node_id, label, tone))

    edges = [
        ("orchestrator", "planner_triage"),
        ("orchestrator", "experiment_scout"),
        ("orchestrator", "implementer"),
        ("orchestrator", "reviewer"),
        ("orchestrator", "deep_reviewer"),
        ("orchestrator", "ci_regression_auditor"),
        ("orchestrator", "eval_claim_privacy_auditor"),
        ("implementer", "reviewer"),
        ("reviewer", "ci_regression_auditor"),
        ("reviewer", "eval_claim_privacy_auditor"),
    ]

    node_defs = "\n    ".join(
        f'{nid}["{esc_mermaid(label)}"]' for nid, label, _ in nodes
    )
    class_defs = ""
    for nid, _, tone in nodes:
        if tone in {"ok", "danger", "warn", "accent"}:
            class_defs += f"\n    class {nid} {tone};"
    edge_defs = "\n    ".join(f"{a} --> {b}" for a, b in edges)

    diagram = f"""flowchart TB
    {node_defs}
    {edge_defs}
    classDef ok fill:#0e2820,stroke:#2ee6a6,color:#2ee6a6
    classDef danger fill:#2a1213,stroke:#ff5d5d,color:#ff5d5d
    classDef warn fill:#2a2210,stroke:#ffb627,color:#ffb627
    classDef accent fill:#0c2330,stroke:#34c8ff,color:#34c8ff
    {class_defs}"""

    return f"""
<div class="mermaid-wrap">
  <div class="mermaid" id="mermaid-topology">{esc(diagram)}</div>
  <div class="mermaid-offline" id="mermaid-offline" style="display:none">
    <p class="empty">(mermaid 오프라인 — CDN 로드 실패)</p>
    <pre>{esc(diagram)}</pre>
  </div>
</div>
"""


def render_topology_section(registry: dict) -> str:
    """Combine the session grid + mermaid map under one panel."""
    topology = str(registry.get("topology", "") or "")
    sessions = _as_list(registry.get("sessions"))
    grid = render_session_grid(registry)
    mermaid = render_topology_mermaid(registry) if sessions else ""
    sub = f"{len(sessions)} nodes · {topology}" if topology else f"{len(sessions)} nodes"
    body = grid
    if mermaid:
        body += (
            "<details class='topo-map-wrap' open>"
            "<summary>&#9656; topology map</summary>"
            f"{mermaid}</details>"
        )
    return panel("Agent Topology", body, sub=sub)


def esc_mermaid(text: str) -> str:
    """Strip newlines and quotes for Mermaid label strings."""
    return text.replace('"', "'").replace("\n", " ")


# ---------------------------------------------------------------------------
# 6a. Workers — codex_runner session health (structural metadata only)
# ---------------------------------------------------------------------------

def render_workers(runner: dict) -> str:
    """Section 6a: codex runner worker health.

    Surfaces ONLY structural metadata (role/status/ship_gate/task_id/pid).
    The free-text payload paths (stdout/stderr/prompt/last_message/command)
    are intentionally NOT rendered — ADR 0005 minimisation.
    """
    sessions = _as_list(runner.get("sessions"))
    if not sessions:
        return (
            "<p class='empty'>데이터 없음 "
            "(codex_runner_state.json 없거나 sessions[]가 비어 있음)</p>"
        )

    auth = str(runner.get("auth_status", "—") or "—")
    sandbox = str(runner.get("sandbox", "—") or "—")
    decision = str(runner.get("decision", "—") or "—")
    d_tone = DECISION_TONE.get(decision, "neutral")

    head = (
        f"<div class='worker-summary'>"
        f"{badge('auth: ' + auth, tone='ok' if 'Logged in' in auth else 'warn')} "
        f"{badge('sandbox: ' + sandbox, tone='accent')} "
        f"{badge('decision: ' + decision, tone=d_tone)}</div>"
    )

    rows = []
    for raw in sessions:
        s = _as_dict(raw)
        role = str(s.get("role", "—") or "—")
        sid = str(s.get("session_id", "—") or "—")
        status = str(s.get("status", "—") or "—")
        tone = STATUS_TONE.get(status, "neutral")
        ship_gate = str(s.get("ship_gate", "—") or "—")
        task_id = str(s.get("task_id", "—") or "—")
        pid = s.get("pid")
        pid_label = str(pid) if pid not in (None, "") else "—"
        rows.append(
            f"<tr>"
            f"<td><strong>{esc(role)}</strong><br><span class='sid'>{esc(sid)}</span></td>"
            f"<td>{badge(status, tone=tone)}</td>"
            f"<td>{badge(ship_gate, tone='neutral')}</td>"
            f"<td><code>{esc(task_id)}</code></td>"
            f"<td><code>{esc(pid_label)}</code></td>"
            f"</tr>"
        )

    table = (
        "<table class='worker-table'>"
        "<thead><tr><th>role</th><th>status</th><th>ship_gate</th>"
        "<th>task_id</th><th>pid</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return head + table


# ---------------------------------------------------------------------------
# 6b. Queue — backlog_handoff_queue waiting tasks (validation defects)
# ---------------------------------------------------------------------------

def render_queue(backlog: dict) -> str:
    """Section 6b: backlog handoff queue with validation-defect counts.

    Surfaces ONLY structural metadata (task_id/title/status + defect counts).
    The free-text payload fields (plan/hydrated_plan/next_action) are
    intentionally NOT rendered — ADR 0005 minimisation.
    """
    tasks = _as_list(backlog.get("tasks"))
    if not tasks:
        return (
            "<p class='empty'>데이터 없음 "
            "(backlog_handoff_queue.json 없거나 tasks[]가 비어 있음)</p>"
        )

    rows = []
    defect_total = 0
    for raw in tasks:
        t = _as_dict(raw)
        task_id = str(t.get("task_id", "—") or "—")
        title = str(t.get("title", "") or "")
        status = str(t.get("status", "—") or "—")
        s_tone = STATUS_TONE.get(status, "neutral")
        missing = _as_list(t.get("missing_fields"))
        invalid = _as_list(t.get("invalid_fields"))
        n_missing = len(missing)
        n_invalid = len(invalid)
        n_defect = n_missing + n_invalid
        if n_defect:
            defect_total += 1

        defect_badges = ""
        if n_missing:
            defect_badges += badge(f"{n_missing} missing", tone="warn") + " "
        if n_invalid:
            defect_badges += badge(f"{n_invalid} invalid", tone="danger")
        if not defect_badges:
            defect_badges = badge("clean", tone="ok")

        row_cls = " has-defect" if n_defect else ""
        rows.append(
            f"<tr class='queue-row{row_cls}'>"
            f"<td><code>{esc(task_id)}</code></td>"
            f"<td class='queue-title'>{esc(title)}</td>"
            f"<td>{badge(status, tone=s_tone)}</td>"
            f"<td>{defect_badges}</td>"
            f"</tr>"
        )

    table = (
        "<table class='queue-table'>"
        "<thead><tr><th>task_id</th><th>title</th><th>status</th>"
        "<th>validation</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    sub = f"{len(tasks)} waiting · {defect_total} with defects"
    head = f"<p class='queue-sub'>{esc(sub)}</p>"
    return head + table


def render_workers_queue(runner: dict, backlog: dict) -> str:
    """Section 6: two-column workers + queue."""
    workers = render_workers(runner)
    queue = render_queue(backlog)
    n_workers = len(_as_list(runner.get("sessions")))
    n_queue = len(_as_list(backlog.get("tasks")))
    body = (
        '<div class="two-col">'
        '<div class="col">'
        f'<h3 class="col-h">Workers <span class="col-n">codex · {n_workers}</span></h3>'
        f"{workers}</div>"
        '<div class="col">'
        f'<h3 class="col-h">Queue <span class="col-n">backlog · {n_queue}</span></h3>'
        f"{queue}</div>"
        "</div>"
    )
    return panel("Workers & Queue", body)


# ---------------------------------------------------------------------------
# 7a. Top blockers — aggregated frequency (events.jsonl)
# ---------------------------------------------------------------------------

def render_blockers_summary(events: list[dict]) -> str:
    """Section 7a: aggregated blockers/warnings with frequency counts."""
    if not events:
        return "<p class='empty'>데이터 없음</p>"

    blocker_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    for ev in events:
        for b in _as_list(ev.get("blockers")):
            blocker_counts[_sanitize_text(str(b))] += 1
        for w in _as_list(ev.get("warnings")):
            warning_counts[_sanitize_text(str(w))] += 1

    if not blocker_counts and not warning_counts:
        return "<p class='ok-note'>이벤트에서 blockers/warnings 없음</p>"

    rows = []
    for msg, cnt in blocker_counts.most_common(8):
        rows.append(
            f"<tr><td>{badge('blocker', tone='danger')}</td>"
            f"<td>{esc(msg)}</td>"
            f"<td><strong>{esc(cnt)}</strong></td></tr>"
        )
    for msg, cnt in warning_counts.most_common(8):
        rows.append(
            f"<tr><td>{badge('warning', tone='warn')}</td>"
            f"<td>{esc(msg)}</td>"
            f"<td><strong>{esc(cnt)}</strong></td></tr>"
        )

    table = (
        "<table>"
        "<thead><tr><th>Type</th><th>Message</th><th>Count</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return table


# ---------------------------------------------------------------------------
# 7b. Agent mix (agent_mix.json) — ratio bar + quota gauge
# ---------------------------------------------------------------------------

def render_agent_mix(mix: dict) -> str:
    """Section 7b: agent_mix ratio bar and quota gauge."""
    if not mix:
        return "<p class='empty'>데이터 없음 (agent_mix.json 없음)</p>"

    policy = _as_dict(mix.get("policy")) or _as_dict(mix.get("agent_mix"))
    target = _as_dict(policy.get("target"))
    claude_t_raw = target.get("claude", 9)
    codex_t_raw = target.get("codex", 1)
    claude_t = claude_t_raw if isinstance(claude_t_raw, int) else 9
    codex_t = codex_t_raw if isinstance(codex_t_raw, int) else 1
    total = claude_t + codex_t or 1
    claude_pct_target = round(claude_t / total * 100)
    codex_pct_target = 100 - claude_pct_target

    quota_exp = str(policy.get("quota_explanation", "") or "")
    claude_quota, codex_quota = _parse_quota(quota_exp)

    rolling = _as_dict(mix.get("rolling"))
    r_claude = rolling.get("claude", 0)
    r_codex = rolling.get("codex", 0)

    window = _as_dict(policy.get("window"))
    win_size = window.get("size", "?")
    win_type = str(window.get("type", "") or "")

    mode = str(mix.get("mode", "") or "")
    gate_policy = str(mix.get("gate_policy", "") or "")

    ratio_bar = f"""
<div class="ratio-label">
  Target: <strong>claude {esc(claude_t)} : codex {esc(codex_t)}</strong>
</div>
<div class="ratio-bar-wrap">
  <div class="ratio-bar">
    <div class="ratio-segment claude" style="width:{esc(claude_pct_target)}%">
      claude {esc(claude_pct_target)}%
    </div>
    <div class="ratio-segment codex" style="width:{esc(codex_pct_target)}%">
      codex {esc(codex_pct_target)}%
    </div>
  </div>
</div>
"""

    gauge_html = ""
    if claude_quota is not None:
        gauge_html += _quota_gauge("claude quota used", claude_quota)
    if codex_quota is not None:
        gauge_html += _quota_gauge("codex quota used", codex_quota, danger_threshold=90)

    rolling_html = f"""
<div class="mix-meta">
  Window: <strong>{esc(win_size)} {esc(win_type)}</strong> &nbsp;|&nbsp;
  claude used: <strong>{esc(r_claude)}</strong> &nbsp;|&nbsp;
  codex used: <strong>{esc(r_codex)}</strong>
</div>
<div class="mix-meta">
  Mode: {badge(mode or '—', tone='accent')} &nbsp;|&nbsp;
  Gate policy: {badge(gate_policy or '—', tone='neutral')}
</div>
"""
    return ratio_bar + gauge_html + rolling_html


def _quota_gauge(label: str, pct: int, danger_threshold: int = 80) -> str:
    tone = "danger" if pct >= danger_threshold else ("warn" if pct >= 60 else "ok")
    bar_color = f"var(--{tone})"
    return f"""
<div class="gauge-row">
  <span class="gauge-label">{esc(label)}</span>
  <div class="gauge-wrap">
    <div class="gauge-fill" style="width:{min(pct,100)}%;background:{bar_color}"></div>
  </div>
  <span class="gauge-val">{esc(pct)}%</span>
</div>
"""


def render_blockers_mix(events: list[dict], mix: dict) -> str:
    """Section 7: two-column top blockers + agent mix."""
    blockers = render_blockers_summary(events)
    agent_mix = render_agent_mix(mix)
    body = (
        '<div class="two-col">'
        '<div class="col">'
        '<h3 class="col-h">Top Blockers <span class="col-n">aggregate</span></h3>'
        f"{blockers}</div>"
        '<div class="col">'
        '<h3 class="col-h">Agent Mix <span class="col-n">claude : codex</span></h3>'
        f"{agent_mix}</div>"
        "</div>"
    )
    return panel("Blockers & Agent Mix", body)


# ---------------------------------------------------------------------------
# 8. Event log — interactive client-side filter + search
# ---------------------------------------------------------------------------

def render_event_log(events: list[dict]) -> str:
    """Section 8: events with client-side event/decision filter + text search."""
    if not events:
        return panel(
            "Event Log",
            "<p class='empty'>데이터 없음 (events.jsonl 없거나 비어 있음)</p>",
        )

    event_types = sorted({str(ev.get("event", "")) for ev in events if ev.get("event")})
    decisions = sorted(
        {str(ev.get("decision", "")) for ev in events if ev.get("decision")}
    )

    # Filter UI controls
    ev_opts = "".join(
        f'<option value="{esc(t)}">{esc(t)}</option>' for t in event_types
    )
    dec_opts = "".join(
        f'<option value="{esc(d)}">{esc(d)}</option>' for d in decisions
    )
    controls = (
        '<div class="log-controls">'
        '<label class="ctl">EVENT '
        f'<select id="filter-event" aria-label="filter by event type">'
        f'<option value="">all</option>{ev_opts}</select></label>'
        '<label class="ctl">DECISION '
        f'<select id="filter-decision" aria-label="filter by decision">'
        f'<option value="">all</option>{dec_opts}</select></label>'
        '<label class="ctl ctl-search">SEARCH '
        '<input id="filter-search" type="search" '
        'placeholder="task / blocker / field…" '
        'aria-label="search event text"></label>'
        '<span id="log-count" class="log-count"></span>'
        "</div>"
    )

    rows_html = []
    for ev in reversed(events):
        ts = str(ev.get("ts", "—") or "—")
        event_type = str(ev.get("event", "—") or "—")
        decision = str(ev.get("decision", "") or "")
        task_id = str(ev.get("task_id", "") or "")
        blockers = _as_list(ev.get("blockers"))
        warnings = _as_list(ev.get("warnings"))

        d_tone = DECISION_TONE.get(decision, "neutral")
        decision_badge = badge(decision, tone=d_tone) if decision else ""
        task_badge = f"<code>{esc(task_id)}</code>" if task_id else ""

        counts = ""
        if blockers:
            counts += f" {badge(f'{len(blockers)} blockers', tone='danger')}"
        if warnings:
            counts += f" {badge(f'{len(warnings)} warnings', tone='warn')}"

        # blockers/warnings are diagnostic (operator-facing); surfaced as in the
        # original board but with run-artifact/scratch path tokens masked.
        san_blockers = [_sanitize_text(str(b)) for b in blockers]
        san_warnings = [_sanitize_text(str(w)) for w in warnings]
        detail_items = ""
        if san_blockers:
            b_list = "".join(f"<li class='blocker-item'>{esc(b)}</li>" for b in san_blockers)
            detail_items += f"<p><strong>Blockers:</strong></p><ul>{b_list}</ul>"
        if san_warnings:
            w_list = "".join(f"<li class='warning-item'>{esc(w)}</li>" for w in san_warnings)
            detail_items += f"<p><strong>Warnings:</strong></p><ul>{w_list}</ul>"

        # Extra structural fields only (branch, issue, mode, sandbox, verdict…).
        # Known free-text keys are excluded; values are short structural tokens.
        skip = {
            "ts", "event", "decision", "task_id", "blockers", "warnings",
            "guidance", "prompt", "last_message", "command", "stdout", "stderr",
        }
        extra_fields = [
            (k, v) for k, v in ev.items()
            if k not in skip and not isinstance(v, (list, dict))
        ]
        if extra_fields:
            ef_items = "".join(
                f"<li><code>{esc(k)}</code>: {esc(v)}</li>"
                for k, v in extra_fields
            )
            detail_items += f"<p><strong>Fields:</strong></p><ul>{ef_items}</ul>"

        # searchable text blob (lowercased server-side; JS matches against it).
        # Uses the sanitized blocker/warning text so masked tokens are not
        # searchable either.
        search_blob = " ".join(
            [ts, event_type, decision, task_id]
            + san_blockers
            + san_warnings
            + [f"{k}:{v}" for k, v in extra_fields]
        ).lower()

        row_attrs = (
            f'class="ev-row {esc(d_tone)}" '
            f'data-event="{esc(event_type)}" '
            f'data-decision="{esc(decision)}" '
            f'data-search="{esc(search_blob)}"'
        )
        row_body = (
            f"<td><code>{esc(ts)}</code></td>"
            f"<td>{badge(event_type, tone='neutral')}</td>"
            f"<td>{decision_badge}</td>"
            f"<td>{task_badge}</td>"
            f"<td>{counts}</td>"
        )

        if detail_items:
            row_detail = (
                f'<tr class="detail-row" data-detail="1"><td colspan="5">'
                f"{detail_row('상세 펼치기 ▼', detail_items)}"
                f"</td></tr>"
            )
        else:
            row_detail = ""

        rows_html.append(f"<tr {row_attrs}>{row_body}</tr>{row_detail}")

    table = (
        "<table class='ev-table'>"
        "<thead><tr>"
        "<th>ts</th><th>event</th><th>decision</th>"
        "<th>task_id</th><th>counts</th>"
        "</tr></thead>"
        f"<tbody id='ev-tbody'>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return panel(
        "Event Log", controls + table, sub=f"{len(events)} events"
    )


# ---------------------------------------------------------------------------
# 9. Collapsed detail — leases (+ raw)
# ---------------------------------------------------------------------------

def render_leases(leases_data: dict) -> str:
    """Section 9: leases table (collapsed by default in render())."""
    leases = _as_list(leases_data.get("leases"))
    if not leases:
        return "<p class='empty'>데이터 없음</p>"

    rows = []
    for raw in leases:
        lease = _as_dict(raw)
        lease_id = str(lease.get("lease_id", "—") or "—")
        status = str(lease.get("status", "—") or "—")
        tone = STATUS_TONE.get(status, "neutral")
        task_id = str(lease.get("task_id", "—") or "—")
        owner_role = str(lease.get("owner_role", "—") or "—")
        expires_at = str(lease.get("expires_at", "—") or "—")
        active_agent = str(lease.get("active_agent") or "—")
        rows.append(
            f"<tr>"
            f"<td><code>{esc(lease_id[:40])}</code></td>"
            f"<td>{badge(status, tone=tone)}</td>"
            f"<td><code>{esc(task_id)}</code></td>"
            f"<td>{esc(owner_role)}</td>"
            f"<td>{esc(active_agent)}</td>"
            f"<td><code>{esc(expires_at)}</code></td>"
            f"</tr>"
        )

    table = (
        "<table>"
        "<thead><tr><th>lease_id</th><th>status</th><th>task_id</th>"
        "<th>owner_role</th><th>active_agent</th><th>expires_at</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return table


def render_detail_drawer(leases_data: dict, loop: dict) -> str:
    """Section 9: collapsed drawer with leases + gate detail."""
    leases_html = render_leases(leases_data)
    n_leases = len(_as_list(leases_data.get("leases")))

    # Gate detail (from loop_state.json) preserved here in collapsed form.
    gate_info = _as_dict(loop.get("gate"))
    gate_html = ""
    if gate_info:
        gate_name = str(gate_info.get("gate", "—") or "—")
        severity = str(gate_info.get("severity", "") or "")
        tone = SEVERITY_TONE.get(severity, "neutral")
        signals = _as_list(gate_info.get("signals"))
        next_cmd = str(gate_info.get("next_safe_command", "") or "")
        sig_list = "".join(
            f'<li><span class="dot {esc(tone)}"></span>{esc(s)}</li>'
            for s in signals
        )
        gate_html = (
            f"<p>{badge('gate: ' + gate_name, tone=tone)} "
            f"{badge('severity: ' + (severity or '—'), tone=tone)}</p>"
        )
        if sig_list:
            gate_html += f"<ul class='signal-list'>{sig_list}</ul>"
        if next_cmd:
            gate_html += (
                f"<p class='next-cmd'><strong>Next safe command:</strong> "
                f"<code>{esc(next_cmd)}</code></p>"
            )

    inner = ""
    if gate_html:
        inner += (
            "<details open><summary>&#9656; Gate detail</summary>"
            f"<div class='detail-body'>{gate_html}</div></details>"
        )
    inner += (
        f"<details><summary>&#9656; Leases ({n_leases})</summary>"
        f"<div class='detail-body'>{leases_html}</div></details>"
    )
    return panel("Detail", inner, extra_class="drawer-panel")


# ---------------------------------------------------------------------------
# CSS + JS
# ---------------------------------------------------------------------------

CSS = """
:root {
  color-scheme: dark;
  --bg: #070b11;
  --panel: #0d141e;
  --panel-2: #111a26;
  --line: #1d2836;
  --line-bright: #2b3b4e;
  --text: #cfd8e3;
  --muted: #6b7a8d;
  --ok: #2ee6a6;
  --warn: #ffb627;
  --danger: #ff5d5d;
  --accent: #34c8ff;
  --neutral: #6b7a8d;
  --font-display: "Oxanium", ui-monospace, monospace;
  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  --font-body: "IBM Plex Sans", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--text);
  font: 14px/1.55 var(--font-body);
  background:
    radial-gradient(120% 80% at 50% -10%, rgba(52,200,255,.10), transparent 55%),
    radial-gradient(80% 60% at 100% 0%, rgba(46,230,166,.05), transparent 60%),
    repeating-linear-gradient(0deg, transparent 0 39px, rgba(43,59,78,.20) 39px 40px),
    repeating-linear-gradient(90deg, transparent 0 39px, rgba(43,59,78,.20) 39px 40px),
    var(--bg);
  background-attachment: fixed;
  -webkit-font-smoothing: antialiased;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: repeating-linear-gradient(0deg, rgba(0,0,0,.18) 0 1px, transparent 1px 3px);
  opacity: .35;
  mix-blend-mode: overlay;
}
main { max-width: 1320px; margin: 0 auto; padding: 0 18px 72px; position: relative; z-index: 1; }
h1, h2, h3, p { margin: 0; }
h1 {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--text);
  text-shadow: 0 0 18px rgba(52,200,255,.30);
}
h1 .accent-glyph { color: var(--accent); }
h2 {
  font-family: var(--font-display);
  font-size: 13px;
  margin-bottom: 14px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: .22em;
  font-weight: 600;
  display: flex;
  align-items: baseline;
  gap: 9px;
}
h2::before {
  content: "\\25C2";
  color: var(--accent);
  font-size: 11px;
  text-shadow: 0 0 8px rgba(52,200,255,.7);
  align-self: center;
}
.panel-sub {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .08em;
  color: var(--muted);
  text-transform: none;
  opacity: .85;
}
.subtitle { color: var(--muted); margin-top: 0; font-size: 12px; font-family: var(--font-mono); letter-spacing: .02em; }

/* Mission-control top status bar */
.console-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 20px 4px 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--line-bright);
}
.console-id { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.console-status {
  display: flex;
  align-items: center;
  gap: 18px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
}
.console-status .stat { display: flex; align-items: center; gap: 7px; letter-spacing: .04em; }
.console-status .stat b { color: var(--text); font-weight: 600; }
.live {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .18em;
  color: var(--ok);
  text-shadow: 0 0 10px rgba(46,230,166,.5);
}

/* Console chip strip */
.console-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
  margin-top: 4px;
  padding: 12px 0 2px;
  border-top: 1px dashed var(--line);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line-bright);
  border-radius: 3px;
  padding: 5px 10px;
  background: rgba(255,255,255,.015);
  font-family: var(--font-mono);
}
.chip .chip-k { font-size: 9px; letter-spacing: .14em; color: var(--muted); text-transform: uppercase; font-family: var(--font-display); font-weight: 600; }
.chip .chip-v { font-size: 12px; font-weight: 600; color: var(--text); letter-spacing: .02em; }
.chip.ok { border-color: rgba(46,230,166,.4); box-shadow: 0 0 12px -4px rgba(46,230,166,.5); }
.chip.ok .chip-v { color: var(--ok); }
.chip.warn { border-color: rgba(255,182,39,.4); }
.chip.warn .chip-v { color: var(--warn); }
.chip.danger { border-color: rgba(255,93,93,.45); box-shadow: 0 0 12px -4px rgba(255,93,93,.5); }
.chip.danger .chip-v { color: var(--danger); }
.chip.accent { border-color: rgba(52,200,255,.4); box-shadow: 0 0 12px -4px rgba(52,200,255,.45); }
.chip.accent .chip-v { color: var(--accent); }

/* Status dots */
.dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: var(--neutral);
  box-shadow: 0 0 0 0 rgba(107,122,141,.5);
  flex-shrink: 0;
}
.dot.pulse { animation: pulse 2.1s ease-out infinite; }
.dot.ok { background: var(--ok); box-shadow: 0 0 8px rgba(46,230,166,.7); }
.dot.ok.pulse { animation-name: pulse-ok; }
.dot.warn { background: var(--warn); box-shadow: 0 0 8px rgba(255,182,39,.7); }
.dot.danger { background: var(--danger); box-shadow: 0 0 8px rgba(255,93,93,.7); }
.dot.danger.pulse { animation-name: pulse-danger; }
.dot.accent { background: var(--accent); box-shadow: 0 0 8px rgba(52,200,255,.7); }

/* Panels with corner brackets */
.panel {
  position: relative;
  background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 20px 22px;
  margin-bottom: 18px;
  box-shadow: 0 18px 40px -28px rgba(0,0,0,.9), inset 0 1px 0 rgba(255,255,255,.02);
  opacity: 0;
  transform: translateY(14px);
  animation: reveal .55s cubic-bezier(.2,.7,.3,1) forwards;
  animation-delay: calc(var(--i, 0) * 80ms + 100ms);
}
/* staggered top-to-bottom reveal cascade */
main > .panel:nth-of-type(1) { --i: 0; }
main > .panel:nth-of-type(2) { --i: 1; }
main > .panel:nth-of-type(3) { --i: 2; }
main > .panel:nth-of-type(4) { --i: 3; }
main > .panel:nth-of-type(5) { --i: 4; }
main > .panel:nth-of-type(6) { --i: 5; }
main > .panel:nth-of-type(7) { --i: 6; }
main > .panel:nth-of-type(n+8) { --i: 7; }
.panel::before, .panel::after {
  content: "";
  position: absolute;
  width: 14px; height: 14px;
  border: 1px solid var(--accent);
  opacity: .55;
  pointer-events: none;
}
.panel::before { top: -1px; left: -1px; border-right: 0; border-bottom: 0; }
.panel::after { bottom: -1px; right: -1px; border-left: 0; border-top: 0; }

/* Two-column grid for the 3 / 6 / 7 sections */
.grid-2 {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 18px;
  align-items: start;
}
.grid-2 > .panel { margin-bottom: 0; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
.col { min-width: 0; }
.col-h {
  font-family: var(--font-display);
  font-size: 12px;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--text);
  margin-bottom: 10px;
  display: flex; align-items: baseline; gap: 8px;
  padding-bottom: 7px;
  border-bottom: 1px solid var(--line);
}
.col-n { font-family: var(--font-mono); font-size: 10px; color: var(--muted); letter-spacing: .06em; }

/* KPI strip */
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}
.kpi {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 13px 14px;
  border-top: 2px solid var(--neutral);
  display: flex; flex-direction: column; gap: 5px;
  overflow: hidden;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.kpi:hover { transform: translateY(-2px); box-shadow: 0 10px 24px -16px rgba(0,0,0,.8); }
.kpi-label { font-size: 9px; text-transform: uppercase; letter-spacing: .13em; color: var(--muted); font-family: var(--font-display); font-weight: 600; }
.kpi-val { font-size: 26px; font-family: var(--font-display); font-weight: 800; line-height: 1; letter-spacing: .01em; color: var(--text); }
.kpi-sub { font-size: 10px; color: var(--muted); font-family: var(--font-mono); word-break: break-word; line-height: 1.4; }
.kpi.ok { border-top-color: var(--ok); }
.kpi.ok .kpi-val { color: var(--ok); text-shadow: 0 0 14px rgba(46,230,166,.4); }
.kpi.warn { border-top-color: var(--warn); }
.kpi.warn .kpi-val { color: var(--warn); text-shadow: 0 0 14px rgba(255,182,39,.4); }
.kpi.danger { border-top-color: var(--danger); }
.kpi.danger .kpi-val { color: var(--danger); text-shadow: 0 0 14px rgba(255,93,93,.4); }
.kpi.accent { border-top-color: var(--accent); }
.kpi.accent .kpi-val { color: var(--accent); }

/* Badge */
.badge {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line-bright);
  border-radius: 3px;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .07em;
  text-transform: uppercase;
  font-family: var(--font-mono);
  white-space: nowrap;
  background: rgba(255,255,255,.02);
  color: var(--muted);
}
.badge.ok { background: rgba(46,230,166,.10); color: var(--ok); border-color: rgba(46,230,166,.40); box-shadow: 0 0 10px -2px rgba(46,230,166,.35); }
.badge.warn { background: rgba(255,182,39,.10); color: var(--warn); border-color: rgba(255,182,39,.40); }
.badge.danger { background: rgba(255,93,93,.12); color: var(--danger); border-color: rgba(255,93,93,.45); box-shadow: 0 0 10px -2px rgba(255,93,93,.40); }
.badge.accent { background: rgba(52,200,255,.10); color: var(--accent); border-color: rgba(52,200,255,.40); box-shadow: 0 0 10px -2px rgba(52,200,255,.35); }
.badge.neutral { background: rgba(107,122,141,.10); color: var(--muted); border-color: var(--line-bright); }

/* Activity trend chart */
.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  height: 180px;
  padding: 6px 4px 0;
  border-bottom: 1px solid var(--line);
}
.trend-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  gap: 6px;
}
.trend-bar {
  width: 100%;
  max-width: 64px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  border-radius: 3px 3px 0 0;
  overflow: hidden;
  border: 1px solid var(--line-bright);
  border-bottom: none;
  background: #060a0f;
  min-height: 3px;
  animation: grow-y .8s cubic-bezier(.2,.7,.3,1) both;
  animation-delay: 360ms;
  transform-origin: bottom;
}
.trend-seg { display: block; width: 100%; }
.trend-seg.ok { background: linear-gradient(180deg, #43f0b6, var(--ok)); }
.trend-seg.warn { background: linear-gradient(180deg, #ffc857, var(--warn)); }
.trend-seg.danger { background: linear-gradient(180deg, #ff7575, var(--danger)); }
.trend-seg.accent { background: linear-gradient(180deg, #5ad6ff, var(--accent)); }
.trend-seg.neutral { background: var(--neutral); }
.trend-total { font-size: 12px; font-weight: 700; font-family: var(--font-mono); color: var(--text); }
.trend-xlabel { font-size: 10px; color: var(--muted); font-family: var(--font-mono); letter-spacing: .02em; white-space: nowrap; }

.legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 14px; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-family: var(--font-mono); color: var(--muted); }
.legend-swatch { width: 11px; height: 11px; border-radius: 2px; flex-shrink: 0; }
.legend-swatch.ok { background: var(--ok); }
.legend-swatch.warn { background: var(--warn); }
.legend-swatch.danger { background: var(--danger); }
.legend-swatch.accent { background: var(--accent); }
.legend-swatch.neutral { background: var(--neutral); }

/* Decision mix */
.mix-list { display: flex; flex-direction: column; gap: 11px; }
.mix-row { display: grid; grid-template-columns: 110px 1fr 42px 44px; align-items: center; gap: 10px; }
.mix-name { font-size: 12px; font-family: var(--font-mono); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.mix-name.ok { color: var(--ok); }
.mix-name.warn { color: var(--warn); }
.mix-name.danger { color: var(--danger); }
.mix-name.accent { color: var(--accent); }
.mix-track { background: #060a0f; border: 1px solid var(--line); border-radius: 3px; height: 18px; overflow: hidden; }
.mix-fill { height: 100%; border-radius: 2px; animation: grow-x 1s cubic-bezier(.2,.7,.3,1) both; animation-delay: 400ms; filter: saturate(1.1); }
.mix-fill.ok { background: linear-gradient(90deg, var(--ok), #43f0b6); box-shadow: 0 0 14px -2px rgba(46,230,166,.5); }
.mix-fill.warn { background: linear-gradient(90deg, var(--warn), #ffc857); }
.mix-fill.danger { background: linear-gradient(90deg, var(--danger), #ff7575); box-shadow: 0 0 14px -2px rgba(255,93,93,.5); }
.mix-fill.accent { background: linear-gradient(90deg, var(--accent), #5ad6ff); }
.mix-fill.neutral { background: var(--neutral); }
.mix-count { font-size: 13px; font-weight: 700; font-family: var(--font-mono); color: var(--text); text-align: right; }
.mix-pct { font-size: 11px; font-family: var(--font-mono); color: var(--muted); text-align: right; }

/* Cycles timeline */
.cycle-timeline { list-style: none; padding: 0; margin: 0; position: relative; }
.cycle-timeline::before {
  content: ""; position: absolute; left: 15px; top: 6px; bottom: 6px;
  width: 2px; background: linear-gradient(180deg, var(--line-bright), var(--line)); opacity: .8;
}
.cycle-item { position: relative; display: flex; gap: 16px; padding: 0 0 18px 0; }
.cycle-item:last-child { padding-bottom: 0; }
.cycle-node {
  position: relative; z-index: 1; flex-shrink: 0;
  width: 32px; height: 32px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--panel); border: 2px solid var(--neutral);
  font-family: var(--font-display); font-weight: 800; font-size: 13px; color: var(--text);
}
.cycle-node.ok { border-color: var(--ok); color: var(--ok); box-shadow: 0 0 12px -2px rgba(46,230,166,.6); }
.cycle-node.danger { border-color: var(--danger); color: var(--danger); box-shadow: 0 0 12px -2px rgba(255,93,93,.6); }
.cycle-node.warn { border-color: var(--warn); color: var(--warn); }
.cycle-node.accent { border-color: var(--accent); color: var(--accent); }
.cycle-node.pulse::after {
  content: ""; position: absolute; inset: -2px; border-radius: 50%;
  border: 2px solid currentColor; animation: ring 2.1s ease-out infinite;
}
.cycle-body {
  flex: 1; min-width: 0;
  background: var(--panel); border: 1px solid var(--line); border-left: 3px solid var(--neutral);
  border-radius: 3px; padding: 11px 14px;
  transition: border-color .18s, transform .18s;
}
.cycle-item.ok .cycle-body { border-left-color: var(--ok); }
.cycle-item.danger .cycle-body { border-left-color: var(--danger); }
.cycle-item.warn .cycle-body { border-left-color: var(--warn); }
.cycle-body:hover { transform: translateX(2px); border-color: var(--line-bright); }
.cycle-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 5px; }
.cycle-task { color: var(--accent); font-size: 13px; font-weight: 600; }
.relay { font-family: var(--font-mono); font-size: 11px; color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
.relay-arrow { color: var(--accent); }
.cycle-title { font-size: 13px; color: var(--text); font-family: var(--font-body); margin-bottom: 9px; line-height: 1.45; }
.cycle-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.cycle-body details { margin-top: 9px; }

/* Session grid */
.session-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 12px;
}
.topo-line { margin-bottom: 12px; font-family: var(--font-mono); font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 8px; }
.session-card {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 14px 15px;
  border-left: 3px solid var(--neutral);
  transition: border-color .18s, transform .18s, box-shadow .18s;
}
.session-card:hover { transform: translateY(-2px); border-color: var(--line-bright); box-shadow: 0 12px 26px -18px rgba(0,0,0,.85); }
.session-card.ok { border-left-color: var(--ok); }
.session-card.warn { border-left-color: var(--warn); }
.session-card.danger { border-left-color: var(--danger); }
.session-card.accent { border-left-color: var(--accent); }
.session-card header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }
.session-card header .role-wrap { display: flex; align-items: center; gap: 8px; min-width: 0; }
.session-card header strong { font-family: var(--font-display); font-size: 14px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.sid { font-size: 10px; color: var(--muted); font-family: var(--font-mono); white-space: nowrap; }
.session-meta { margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 5px; }
.session-lanes { margin-bottom: 8px; }
.lane-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(255,255,255,.03);
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 3px 7px;
  margin: 2px 3px 2px 0;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--muted);
}
.lane-pill em { font-style: normal; color: var(--text); opacity: .8; }
.lane-pill.ok { border-color: rgba(46,230,166,.35); color: var(--ok); }
.lane-pill.warn { border-color: rgba(255,182,39,.35); color: var(--warn); }
.lane-pill.danger { border-color: rgba(255,93,93,.40); color: var(--danger); }
.lane-pill.accent { border-color: rgba(52,200,255,.35); color: var(--accent); }
.session-detail { font-size: 11px; color: var(--muted); margin-bottom: 6px; font-family: var(--font-mono); }
.session-card details { margin-top: 8px; }
.session-card summary { font-size: 11px; cursor: pointer; color: var(--accent); font-family: var(--font-display); letter-spacing: .08em; text-transform: uppercase; }
.cmd-block { display: block; font-size: 11px; background: #060a0f; border: 1px solid var(--line); border-radius: 3px; padding: 8px 9px; margin-top: 6px; word-break: break-all; white-space: pre-wrap; color: var(--ok); font-family: var(--font-mono); }
.topo-map-wrap { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 12px; }
.topo-map-wrap > summary { font-size: 11px; cursor: pointer; color: var(--accent); font-family: var(--font-display); letter-spacing: .1em; text-transform: uppercase; padding: 4px 0; }

/* Worker / queue tables share the table base; small tweaks */
.worker-summary { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
.worker-table td:first-child strong { font-family: var(--font-display); letter-spacing: .03em; font-size: 12px; }
.queue-sub { font-family: var(--font-mono); font-size: 11px; color: var(--muted); margin-bottom: 10px; }
.queue-title { color: var(--text); font-family: var(--font-body); }
.queue-row.has-defect td:first-child { border-left: 2px solid var(--warn); }
.queue-row.has-defect:hover td { background: rgba(255,182,39,.06); }

/* Ratio bar */
.ratio-label { margin-bottom: 8px; font-size: 13px; font-family: var(--font-mono); color: var(--muted); }
.ratio-label strong { color: var(--text); font-weight: 600; }
.ratio-bar-wrap { margin-bottom: 16px; }
.ratio-bar { display: flex; height: 28px; border-radius: 3px; overflow: hidden; border: 1px solid var(--line-bright); background: #060a0f; }
.ratio-segment {
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: #051018;
  font-family: var(--font-display); letter-spacing: .08em; text-transform: uppercase;
  white-space: nowrap; overflow: hidden;
  animation: grow-x .9s cubic-bezier(.2,.7,.3,1) both;
  animation-delay: 380ms;
}
.ratio-segment.claude { background: linear-gradient(90deg, var(--accent), #5ad6ff); box-shadow: 0 0 18px rgba(52,200,255,.5) inset; }
.ratio-segment.codex { background: linear-gradient(90deg, #46586b, #6b7a8d); color: #0a0f16; }

/* Quota gauge */
.gauge-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.gauge-label { font-size: 11px; width: 140px; flex-shrink: 0; font-family: var(--font-display); letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.gauge-wrap { flex: 1; background: #060a0f; border: 1px solid var(--line); border-radius: 3px; height: 16px; overflow: hidden; position: relative; }
.gauge-fill { height: 100%; border-radius: 2px; filter: brightness(1.05) saturate(1.1); box-shadow: 0 0 14px -2px rgba(255,255,255,.25); animation: grow-x 1s cubic-bezier(.2,.7,.3,1) both; animation-delay: 420ms; }
.gauge-val { font-size: 13px; font-weight: 700; width: 44px; text-align: right; font-family: var(--font-mono); color: var(--text); }
.mix-meta { font-size: 12px; margin-bottom: 8px; font-family: var(--font-mono); color: var(--muted); display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.mix-meta strong { color: var(--text); font-weight: 600; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: var(--font-mono); }
th, td { text-align: left; border-top: 1px solid var(--line); padding: 9px 8px; vertical-align: top; }
tbody tr { transition: background .14s; }
tbody tr:hover td { background: rgba(52,200,255,.045); }
thead th { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .14em; border-top: none; font-family: var(--font-display); font-weight: 600; }
td code, .session-detail code { color: var(--accent); }

/* Event log controls */
.log-controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
  margin-bottom: 14px; padding: 12px 14px;
  background: #060a0f; border: 1px solid var(--line); border-radius: 3px;
}
.ctl { display: inline-flex; align-items: center; gap: 8px; font-family: var(--font-display); font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
.ctl-search { flex: 1; min-width: 180px; }
.log-controls select, .log-controls input {
  background: var(--panel); color: var(--text);
  border: 1px solid var(--line-bright); border-radius: 3px;
  padding: 6px 9px; font-family: var(--font-mono); font-size: 12px;
  letter-spacing: 0; text-transform: none; font-weight: 400;
}
.log-controls input { width: 100%; }
.log-controls select:focus, .log-controls input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 1px rgba(52,200,255,.4); }
.log-count { margin-left: auto; font-family: var(--font-mono); font-size: 11px; color: var(--muted); letter-spacing: .04em; text-transform: none; }
.log-count b { color: var(--accent); }

.ev-table { table-layout: fixed; }
.ev-table td:nth-child(1) { width: 168px; }
.ev-table td:nth-child(2) { width: 158px; }
.ev-table td:nth-child(3) { width: 104px; }
.ev-table td:nth-child(4) { width: 120px; }
.ev-table td:nth-child(5) { }
.ev-row td { border-left: 2px solid transparent; }
.ev-row.danger td:first-child { border-left-color: var(--danger); }
.ev-row.danger:hover td { background: rgba(255,93,93,.07); }
.ev-row.warn td:first-child { border-left-color: var(--warn); }
.ev-row.warn:hover td { background: rgba(255,182,39,.06); }
.ev-row.ok td:first-child { border-left-color: var(--ok); }
.ev-row.accent td:first-child { border-left-color: var(--accent); }
.ev-row.is-hidden, .detail-row.is-hidden { display: none; }
.detail-row td { padding: 0; border-top: none; border-left: 2px solid var(--line-bright); }
.detail-body { padding: 10px 14px 12px; background: #060a0f; font-size: 12px; font-family: var(--font-body); line-height: 1.6; }
.detail-body code { font-family: var(--font-mono); }
details summary { cursor: pointer; color: var(--accent); font-size: 11px; padding: 7px 0; font-family: var(--font-display); letter-spacing: .06em; }
.blocker-item { color: var(--danger); }
.warning-item { color: var(--warn); }

/* Mermaid */
.mermaid-wrap { overflow: auto; padding: 6px 0; }
.mermaid svg { max-width: 100%; }
.mermaid-offline pre { background: #060a0f; border: 1px solid var(--line); border-radius: 3px; padding: 12px; color: var(--ok); font-family: var(--font-mono); font-size: 12px; overflow: auto; }

/* Drawer */
.drawer-panel summary { font-family: var(--font-display); letter-spacing: .1em; text-transform: uppercase; font-size: 11px; }

/* Misc */
.signal-list { list-style: none; padding: 0; margin: 10px 0 0; }
.signal-list li { padding: 5px 0; font-size: 12px; font-family: var(--font-body); color: var(--text); display: flex; align-items: center; gap: 8px; }
.next-cmd { margin-top: 12px; font-size: 12px; font-family: var(--font-body); color: var(--muted); }
.next-cmd strong { color: var(--text); font-family: var(--font-display); letter-spacing: .06em; text-transform: uppercase; font-size: 11px; }
.ok-note { color: var(--ok); font-family: var(--font-mono); font-size: 12px; }
.empty { color: var(--muted); font-style: italic; font-family: var(--font-mono); font-size: 12px; }
code { background: rgba(52,200,255,.07); border: 1px solid var(--line); border-radius: 3px; padding: 1px 5px; font-family: var(--font-mono); font-size: .92em; color: var(--text); }
footer { margin-top: 36px; font-size: 11px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; font-family: var(--font-mono); letter-spacing: .02em; }

/* Motion keyframes */
@keyframes reveal { to { opacity: 1; transform: translateY(0); } }
@keyframes grow-x { from { width: 0 !important; } }
@keyframes grow-y { from { transform: scaleY(0); } }
@keyframes ring {
  0% { opacity: .7; transform: scale(1); }
  70% { opacity: 0; transform: scale(1.7); }
  100% { opacity: 0; transform: scale(1.7); }
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(107,122,141,.5); }
  70% { box-shadow: 0 0 0 7px rgba(107,122,141,0); }
  100% { box-shadow: 0 0 0 0 rgba(107,122,141,0); }
}
@keyframes pulse-ok {
  0% { box-shadow: 0 0 0 0 rgba(46,230,166,.55); }
  70% { box-shadow: 0 0 0 8px rgba(46,230,166,0); }
  100% { box-shadow: 0 0 0 0 rgba(46,230,166,0); }
}
@keyframes pulse-danger {
  0% { box-shadow: 0 0 0 0 rgba(255,93,93,.6); }
  70% { box-shadow: 0 0 0 8px rgba(255,93,93,0); }
  100% { box-shadow: 0 0 0 0 rgba(255,93,93,0); }
}

@media (max-width: 980px) {
  .grid-2 { grid-template-columns: 1fr; }
  .kpi-strip { grid-template-columns: repeat(3, 1fr); }
  .two-col { grid-template-columns: 1fr; gap: 24px; }
}
@media (max-width: 720px) {
  .kpi-strip { grid-template-columns: 1fr 1fr; }
  .session-grid { grid-template-columns: 1fr; }
  .console-bar { flex-direction: column; align-items: flex-start; }
  .mix-row { grid-template-columns: 84px 1fr 36px 38px; }
}
@media (prefers-reduced-motion: reduce) {
  .panel, .ratio-segment, .gauge-fill, .mix-fill, .trend-bar { animation: none !important; opacity: 1 !important; transform: none !important; }
  .dot.pulse, .cycle-node.pulse::after { animation: none !important; }
  body { background-attachment: scroll; }
}
"""

MERMAID_JS = """
(function() {
  var cdn = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
  var el = document.getElementById('mermaid-topology');
  var offline = document.getElementById('mermaid-offline');
  if (!el) return;
  var s = document.createElement('script');
  s.src = cdn;
  s.onload = function() {
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'base',
        fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
        themeVariables: {
          background: '#0d141e',
          primaryColor: '#111a26',
          primaryTextColor: '#cfd8e3',
          primaryBorderColor: '#2b3b4e',
          lineColor: '#34c8ff',
          mainBkg: '#111a26',
          nodeBorder: '#2b3b4e',
          nodeTextColor: '#cfd8e3',
          edgeLabelBackground: '#0d141e',
          clusterBkg: '#0d141e',
          clusterBorder: '#1d2836',
          titleColor: '#cfd8e3'
        }
      });
      mermaid.run({ nodes: [el] });
    } catch(e) {
      if (offline) { offline.style.display=''; el.style.display='none'; }
    }
  };
  s.onerror = function() {
    if (offline) { offline.style.display=''; el.style.display='none'; }
  };
  document.head.appendChild(s);
})();
"""

# Client-side event-log filter + search. Pure inline JS, no deps.
LOG_FILTER_JS = """
(function() {
  var tbody = document.getElementById('ev-tbody');
  var fEvent = document.getElementById('filter-event');
  var fDecision = document.getElementById('filter-decision');
  var fSearch = document.getElementById('filter-search');
  var counter = document.getElementById('log-count');
  if (!tbody) return;
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr.ev-row'));
  function apply() {
    var ev = fEvent ? fEvent.value : '';
    var dec = fDecision ? fDecision.value : '';
    var q = fSearch ? fSearch.value.trim().toLowerCase() : '';
    var shown = 0;
    rows.forEach(function(row) {
      var okEvent = !ev || row.getAttribute('data-event') === ev;
      var okDec = !dec || row.getAttribute('data-decision') === dec;
      var okSearch = !q || (row.getAttribute('data-search') || '').indexOf(q) !== -1;
      var visible = okEvent && okDec && okSearch;
      row.classList.toggle('is-hidden', !visible);
      // sibling detail-row follows the visibility of its data row
      var next = row.nextElementSibling;
      if (next && next.classList.contains('detail-row')) {
        next.classList.toggle('is-hidden', !visible);
      }
      if (visible) shown++;
    });
    if (counter) {
      counter.innerHTML = 'showing <b>' + shown + '</b> / ' + rows.length;
    }
  }
  if (fEvent) fEvent.addEventListener('change', apply);
  if (fDecision) fDecision.addEventListener('change', apply);
  if (fSearch) fSearch.addEventListener('input', apply);
  apply();
})();
"""


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render(state_dir: Path, out: Path, *, auto_refresh: bool = True) -> None:
    now_str = _dt.datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    loop = _load_obj(state_dir / "loop_state.json")
    registry = _load_obj(state_dir / "session_registry.json")
    mix = _load_obj(state_dir / "agent_mix.json")
    leases_data = _load_obj(state_dir / "leases.json")
    events = _load_jsonl(state_dir / "events.jsonl")
    # Newly-read sources (previously ignored by the board).
    auto = _load_obj(state_dir / "auto_loop_state.json")
    runner = _load_obj(state_dir / "codex_runner_state.json")
    backlog = _load_obj(state_dir / "backlog_handoff_queue.json")

    generated_at = (
        str(auto.get("generated_at") or "")
        or str(registry.get("generated_at") or "")
        or str(mix.get("generated_at") or "")
        or now_str
    )

    refresh_meta = (
        '<meta http-equiv="refresh" content="15">' if auto_refresh else ""
    )

    # IA order (top→bottom priority):
    # 2 status · 3 trend|mix · 4 cycles · 5 topology · 6 workers|queue ·
    # 7 blockers|mix · 8 event log · 9 drawer
    body_sections = "\n".join([
        render_mission_status(auto, runner, registry, events),
        (
            '<div class="grid-2">'
            f"{render_activity_trend(events)}"
            f"{render_decision_mix(events)}"
            "</div>"
        ),
        render_cycles_timeline(auto),
        render_topology_section(registry),
        render_workers_queue(runner, backlog),
        render_blockers_mix(events, mix),
        render_event_log(events),
        render_detail_drawer(leases_data, loop),
    ])

    state_rel = repo_rel(str(state_dir))
    out_rel = repo_rel(str(out))

    live_indicator = (
        '<span class="live"><span class="dot ok pulse"></span>LIVE</span>'
        if auto_refresh
        else '<span class="live" style="color:var(--muted)"><span class="dot"></span>STATIC</span>'
    )
    refresh_stat = (
        '<span class="stat">REFRESH <b>15s</b></span>'
        if auto_refresh
        else '<span class="stat">REFRESH <b>off</b></span>'
    )

    console_chips = build_console_chips(auto, runner)

    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>AGENT LOOP // MISSION CONTROL</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=Oxanium:wght@500;600;700;800&display=swap">
  <style>{CSS}</style>
</head>
<body>
<main>
  <header class="console-bar">
    <div class="console-id">
      <h1>AGENT&#8202;<span class="accent-glyph">/</span>&#8202;LOOP <span class="accent-glyph">&#9656;</span> MISSION CONTROL</h1>
      <p class="subtitle">8-session autonomous agent pool &middot; claude + codex &middot; continuous loop telemetry</p>
    </div>
    <div class="console-status">
      <span class="stat">STATE <b><code>{esc(state_rel)}</code></b></span>
      <span class="stat">SYNC <b>{esc(generated_at)}</b></span>
      <span class="stat">RENDER <b>{esc(now_str)}</b></span>
      {refresh_stat}
      {live_indicator}
    </div>
    {console_chips}
  </header>

  {body_sections}

  <footer>
    GENERATED BY <code>scripts/render_agent_loop_board.py</code>
    &mdash; OUTPUT <code>{esc(out_rel)}</code>
    &mdash; DATA BOUNDARY: ADR 0005 (private, gitignored, structural metadata only)
  </footer>
</main>
<script>{MERMAID_JS}</script>
<script>{LOG_FILTER_JS}</script>
</body>
</html>
"""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[OK] wrote {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render agent-loop multi-session HTML dashboard."
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help="Path to agent_loop active state directory "
        f"(default: {DEFAULT_STATE_DIR})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output HTML path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Disable <meta http-equiv=refresh content=15>",
    )
    args = parser.parse_args(argv)

    render(args.state_dir, args.out, auto_refresh=not args.no_refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
