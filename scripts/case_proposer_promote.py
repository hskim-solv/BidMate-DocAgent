#!/usr/bin/env python3
"""Idempotent promote of reviewed cases into the active eval config
(ADR 0029).

Reads ``reports/proposed/reviewed_cases.local.yaml`` (gitignored,
written by ``scripts/case_proposer_review.py``), filters down to
``approved: true``, strips proposer/review metadata, and appends each
new case to ``eval/real_config.local.yaml``'s ``cases:`` list. Cases
whose ``id`` already exists in the active config are skipped — so
running ``make case-promote`` twice in a row is a no-op for the
second invocation. This is the "two-stage human gate" in ADR 0029:
``case-review`` is the first explicit gate, ``case-promote`` is the
second.

PyYAML is used for round-trip on the active config. Comments in
``real_config.local.yaml`` are NOT preserved — that is an intentional
trade-off avoiding a ruamel.yaml dependency. Reviewers who keep
heavy comments in the active config should review the diff after
``make case-promote`` and re-add as needed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.case_proposer import DEFAULT_REVIEWED_PATH  # noqa: E402

DEFAULT_REAL_CONFIG_PATH = ROOT / "eval" / "real_config.local.yaml"

# Fields produced by the proposer / review step that must NOT appear
# in the active eval config (ADR 0029 §Decision: "active config stays
# a byte-equal subset of the existing 8-field schema").
PROPOSER_META_FIELDS = ("source", "proposer_meta", "approved", "review_meta")


def _strip_meta(case: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in case.items() if k not in PROPOSER_META_FIELDS}


def read_reviewed_yaml(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("reviewed_cases") or [])


def read_real_config(path: Path) -> dict[str, Any]:
    """Load active eval config. Empty if file missing."""
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_real_config(config: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def promote_cases(
    reviewed: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    """Append approved-and-new reviewed cases to the config in-place.

    Returns (new_config, n_appended, n_skipped). ``n_skipped`` covers
    both "id already in config.cases" (idempotency) and
    "approved=false" (rejected) — the caller logs the distinction.
    """
    if "cases" not in config or not isinstance(config["cases"], list):
        config = {**config, "cases": []}
    existing_ids = {str(c.get("id") or "") for c in config["cases"]}
    appended: list[dict[str, Any]] = []
    n_skipped = 0
    for case in reviewed:
        if not case.get("approved"):
            n_skipped += 1
            continue
        case_id = str(case.get("id") or "")
        if not case_id or case_id in existing_ids:
            n_skipped += 1
            continue
        appended.append(_strip_meta(case))
        existing_ids.add(case_id)
    config["cases"].extend(appended)
    return config, len(appended), n_skipped


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="case_proposer_promote",
        description=(
            "Idempotently append approved reviewed cases to the active "
            "real-eval config (ADR 0029 second-stage human gate)."
        ),
    )
    p.add_argument(
        "--reviewed",
        type=Path,
        default=DEFAULT_REVIEWED_PATH,
        help=f"Reviewed yaml input (default: {DEFAULT_REVIEWED_PATH}).",
    )
    p.add_argument(
        "--real-config",
        type=Path,
        default=DEFAULT_REAL_CONFIG_PATH,
        help=(
            f"Active real-eval config to update "
            f"(default: {DEFAULT_REAL_CONFIG_PATH}). Must exist; "
            "copy eval/real_config.example.yaml first if not."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without writing to --real-config.",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    reviewed = read_reviewed_yaml(args.reviewed)
    if not reviewed:
        print(
            f"case_proposer_promote: no reviewed cases at {args.reviewed}",
            file=sys.stderr,
        )
        return 0
    if not args.real_config.exists():
        print(
            f"case_proposer_promote: {args.real_config} not found. Copy "
            "eval/real_config.example.yaml first.",
            file=sys.stderr,
        )
        return 2
    config = read_real_config(args.real_config)
    new_config, n_appended, n_skipped = promote_cases(reviewed, config)
    if args.dry_run:
        print(
            f"case_proposer_promote (dry-run): would append {n_appended} "
            f"case(s), skip {n_skipped}",
            file=sys.stderr,
        )
        return 0
    write_real_config(new_config, args.real_config)
    print(
        f"case_proposer_promote: appended {n_appended} case(s), "
        f"skipped {n_skipped} (rejected or already-present id) "
        f"-> {args.real_config}",
        file=sys.stderr,
    )
    return 0


__all__ = [
    "DEFAULT_REAL_CONFIG_PATH",
    "PROPOSER_META_FIELDS",
    "main",
    "promote_cases",
    "read_real_config",
    "read_reviewed_yaml",
    "write_real_config",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
