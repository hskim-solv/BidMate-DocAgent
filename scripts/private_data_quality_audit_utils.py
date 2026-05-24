#!/usr/bin/env python3
"""Shared helpers for local-only private data quality audit scripts."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]

FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "question",
        "answer",
        "answer_text",
        "gold_evidence",
        "retrieved_chunks",
        "text",
        "text_preview",
        "doc_id",
        "chunk_id",
        "file_name",
        "filename",
        "file_path",
        "source_path",
        "path",
        "absolute_path",
        "support_text",
        "raw_text",
        "document_text",
    }
)
ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(^|[\s'\"])/(Users|home|private|var|tmp|Volumes)/[^\s'\"]+"
)
TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]{2,}")


class AuditPrivacyError(ValueError):
    """Raised when an audit output would cross the private-data boundary."""


def repo_path(value: str | Path, root: Path = ROOT_DIR) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else root / candidate


def rel_to_repo(path: Path, root: Path = ROOT_DIR) -> str | None:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return None


def gitignored_or_outside_repo(path: Path, root: Path = ROOT_DIR) -> bool:
    rel = rel_to_repo(path, root)
    if rel is None:
        return True
    candidates = [rel]
    if not rel.endswith("/"):
        candidates.append(rel + "/")
        candidates.append(rel + "/.private-data-quality-audit-probe")
    for candidate in candidates:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", candidate],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode == 0:
            return True
    return False


def require_safe_out_dir(out_dir: Path, root: Path = ROOT_DIR) -> None:
    if not gitignored_or_outside_repo(out_dir, root):
        raise AuditPrivacyError(
            "--out-dir must be outside the repo or under a gitignored local-only directory"
        )


def hash_ref(value: Any, *, namespace: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = "<missing>"
    digest = hashlib.sha256(f"{namespace}\x00{raw}".encode("utf-8")).hexdigest()[:16]
    return f"redacted_{digest}"


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def tokens(value: Any) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(str(value or ""))}


def jaccard(left: Any, right: Any) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def containment(needle: Any, haystack: Any) -> float:
    needle_tokens = tokens(needle)
    haystack_tokens = tokens(haystack)
    if not needle_tokens:
        return 0.0
    return len(needle_tokens & haystack_tokens) / len(needle_tokens)


def percentile(values: list[int | float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def page_metadata_present(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for node in (item, metadata):
        for key in ("page", "page_number", "page_span", "page_start", "page_end", "pages"):
            value = node.get(key)
            if value not in (None, "", []):
                return True
    regions = item.get("regions")
    if isinstance(regions, list):
        return any(
            isinstance(region, dict) and region.get("page_number") not in (None, "")
            for region in regions
        )
    return False


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL row must be an object at line {lineno}")
        rows.append(payload)
    return rows


def forbidden_output_hits(obj: Any, *, include_values: bool = True) -> dict[str, int]:
    found: dict[str, int] = {}

    def bump(key: str) -> None:
        found[key] = found.get(key, 0) + 1

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key).lower()
                if key_text in FORBIDDEN_PUBLIC_KEYS:
                    bump(key_text)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif include_values and isinstance(node, str):
            if ABSOLUTE_LOCAL_PATH_RE.search(node):
                bump("absolute_path_value")

    walk(obj)
    return found


def assert_public_safe(obj: Any) -> None:
    hits = forbidden_output_hits(obj)
    if hits:
        detail = ", ".join(f"{key}x{count}" for key, count in sorted(hits.items()))
        raise AuditPrivacyError(f"audit output contains forbidden private fields: {detail}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    assert_public_safe(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    lines: list[str] = []
    for row in rows:
        assert_public_safe(row)
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    path.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")
