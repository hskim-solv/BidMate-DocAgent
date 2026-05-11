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


def fmt_rate(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


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
