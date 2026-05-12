"""Shared I/O, git, and metric helpers for scripts/.

Internal to scripts/; imported by sibling scripts via the scripts-dir-on-path
pattern (matching scripts/_eval_delta.py):

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _utils import ...
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def rel_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT_DIR))
    except ValueError:
        return str(resolved)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML must be a mapping: {path}")
    return data


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_output(args: list[str], default: str = "unknown") -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT_DIR,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return default
    return result.stdout.strip() or default


def git_dirty() -> bool:
    status = git_output(["status", "--porcelain", "--untracked-files=no"], default="")
    return bool(status.strip())


def build_provenance() -> dict[str, object]:
    """Provenance block for the current git HEAD.

    Shared by the synthetic history writer
    (``scripts/write_synthetic_history.py``) and the real-data baseline
    writer (``scripts/write_real_eval_baseline.py``). Format is
    intentionally narrow: 12-char SHA, dirty flag, ISO-8601 UTC
    timestamp.

    The dirty flag intentionally includes untracked files
    (``git status --porcelain`` without ``--untracked-files=no``) so a
    snapshot taken from a workspace with stray files is flagged as
    not-clean — stricter than the ``git_dirty()`` helper used by the
    leaderboard/render side.
    """
    sha = git_output(["rev-parse", "HEAD"], default="")[:12] or "unknown"
    dirty = git_output(["status", "--porcelain"], default="") != ""
    return {
        "git_commit": sha,
        "git_dirty": bool(dirty),
        "generated_at": utc_now(),
    }


def make_run_id(provenance: dict[str, object]) -> str:
    """Build ``YYYYMMDDTHHMMSSZ_<sha12>`` run id from a provenance block."""
    ts = (
        str(provenance.get("generated_at"))
        .replace("-", "")
        .replace(":", "")
        .split(".")[0]  # drop fractional seconds
    )
    if not ts.endswith("Z"):
        ts += "Z"
    sha = str(provenance.get("git_commit") or "unknown")[:12]
    return f"{ts}_{sha}"


def fmt_rate(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


def fmt_cell(value: Any) -> str:
    """Format a cell value for a markdown history table.

    Conventions shared by the real-data history renderer
    (``scripts/render_real_eval_history.py``) and the synthetic
    leaderboard (``scripts/leaderboard.py``):

    - ``None`` renders as ``"—"`` (em dash), not ``"None"`` — missing
      metrics on older snapshots should look intentional, not broken.
    - ``float`` renders with 3 decimals — the precision both eval
      surfaces are calibrated to.
    - Other values fall through to ``str(value)``.

    Note: ``fmt_rate`` (also in this module) uses a different
    convention (``"N/A"`` instead of ``"—"``) and is consumed by the
    README ablation table renderer. Keep both — they target different
    audiences (in-repo history tables vs README headline metrics).
    """
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_history_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    empty_message: str = "",
    trailing_newline: bool = False,
) -> str:
    """Render aggregate-history rows as a GitHub markdown table.

    Shared kernel for ``render_real_eval_history.render_table()`` and
    ``leaderboard._render_table_only()``. Conventions:

    - ``columns`` is a list of ``(row_key, header_label)`` tuples.
    - The ``"commit"`` column gets backtick-wrapped (``" `abc123`"``);
      empty commit renders as ``"—"``.
    - Every other column flows through :func:`fmt_cell`.
    - ``empty_message`` is returned verbatim when ``rows`` is empty —
      callers want different "no data" prose.
    - ``trailing_newline=True`` appends ``"\\n"`` after the last row;
      matches ``leaderboard._render_table_only`` (which embeds the
      table under a ``## Tabular view`` section that expects a final
      newline). Default ``False`` matches ``render_real_eval_history``
      (which feeds the table into a marker-spliced block).
    """
    if not rows:
        return empty_message
    header = "| " + " | ".join(label for _, label in columns) + " |"
    sep = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [header, sep]
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key)
            if key == "commit":
                cells.append(f"`{value}`" if value else "—")
            else:
                cells.append(fmt_cell(value))
        lines.append("| " + " | ".join(cells) + " |")
    result = "\n".join(lines)
    if trailing_newline:
        result += "\n"
    return result


_METRIC_SNAPSHOT_KEYS_PRE = (
    "num_predictions",
    "accuracy",
    "groundedness",
    "citation_precision",
    "citation_page_precision",
    "citation_region_precision",
    "citation_grounding",
    "answer_format_compliance",
    "abstention",
    "retry",
    "latency",
    "retry_cost",
    "retry_reason_counts",
    "citation_grounding_error_counts",
)


def metric_snapshot(
    summary: dict[str, Any] | None,
    *,
    include_query_type: bool = True,
) -> dict[str, Any]:
    """Slice the canonical aggregate metric keys out of an eval summary.

    With ``include_query_type=True`` matches the ``run_benchmark`` shape
    (used for per-run snapshots inside the run manifest).
    With ``include_query_type=False`` matches the ``summarize_benchmark`` shape
    (used for the committed registry entries that drop the per-query-type slice).
    """
    summary = summary or {}
    keys: list[str] = list(_METRIC_SNAPSHOT_KEYS_PRE)
    if include_query_type:
        keys.append("by_query_type")
    keys.append("by_hardcase_category")
    return {key: summary.get(key) for key in keys if key in summary}
