#!/usr/bin/env python3
"""Interactive review CLI for case proposer candidates (ADR 0029).

Reads ``reports/proposed/proposed_cases.local.yaml`` (gitignored,
written by ``eval/case_proposer.py``), walks each candidate, and
records the human reviewer's decision into
``reports/proposed/reviewed_cases.local.yaml`` (also gitignored).

Decision input:

    a / accept   — keep as-is, ``approved: true``
    e / edit     — open ``$EDITOR`` on the case yaml; result becomes
                   the new case body. ``approved: true``,
                   ``review_meta.edited: true``.
    r / reject   — keep yaml but ``approved: false``. Useful audit
                   trail; aggregate metrics in PR4 use this.
    s / skip     — leave undecided; reviewer revisits later.
    q / quit     — stop walking, write whatever was decided.
    ? / help     — show this list again.

The reviewed yaml schema mirrors the proposed schema with two
additions:

    - <8-field case body + source + proposer_meta>
      approved: true | false
      review_meta:
        reviewed_at: "<ISO8601Z>"
        edited: true | false

Per ADR 0005, neither the proposed nor the reviewed yaml ever
crosses the commit boundary — both are written to
``reports/proposed/*.local.yaml`` which is gitignored. Only the
``proposer.aggregate.json`` summary (PR4) is committable.

The review walk is testable: the ``walk_review_session`` function
takes injected ``prompt_fn`` and ``edit_fn`` callables so a unit
test can simulate keystrokes and edits without a TTY or editor.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.case_proposer import (  # noqa: E402
    DEFAULT_PROPOSED_PATH,
    DEFAULT_REVIEWED_PATH,
    write_proposed_yaml,
)

REVIEW_PROMPT = (
    "  [a]ccept  [e]dit  [r]eject  [s]kip  [q]uit  [?]help > "
)
REVIEW_HELP = (
    "    a / accept  — approve as-is\n"
    "    e / edit    — open $EDITOR; result replaces the case body\n"
    "    r / reject  — record approved=false\n"
    "    s / skip    — defer (no decision recorded)\n"
    "    q / quit    — write current results and exit\n"
    "    ? / help    — show this help\n"
)


def _utcnow_iso_z() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_case_preview(case: dict[str, Any]) -> str:
    """One-screen preview of a case for the reviewer."""
    meta = case.get("proposer_meta", {})
    return (
        f"  id:                {case.get('id')}\n"
        f"  query_type:        {case.get('query_type')}\n"
        f"  seed_doc_id:       {meta.get('seed_doc_id')}\n"
        f"  backend / model:   {meta.get('backend')} / {meta.get('model')}\n"
        f"  query:             {case.get('query')}\n"
        f"  expected_doc_ids:  {case.get('expected_doc_ids')}\n"
        f"  expected_terms:    {case.get('expected_terms')}\n"
        f"  claim_targets:     {case.get('expected_claim_targets')}\n"
        f"  answerable:        {case.get('answerable')}"
    )


def _open_editor_on_case(case: dict[str, Any]) -> dict[str, Any]:
    """Spawn $EDITOR on a temp yaml file containing the case; return the
    edited dict back. Falls back to ``vi`` if ``$EDITOR`` is unset.
    """
    editor = os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", delete=False
    ) as fh:
        yaml.safe_dump(case, fh, allow_unicode=True, sort_keys=False)
        tmp_path = Path(fh.name)
    try:
        subprocess.run([editor, str(tmp_path)], check=True)
        edited = yaml.safe_load(tmp_path.read_text(encoding="utf-8"))
        if not isinstance(edited, dict):
            raise ValueError("edited file did not parse to a dict")
        return edited
    finally:
        tmp_path.unlink(missing_ok=True)


def _annotate_reviewed(
    case: dict[str, Any], *, approved: bool, edited: bool, now_iso: str
) -> dict[str, Any]:
    return {
        **case,
        "approved": approved,
        "review_meta": {"reviewed_at": now_iso, "edited": edited},
    }


def walk_review_session(
    proposed: list[dict[str, Any]],
    *,
    prompt_fn: Callable[[str], str],
    edit_fn: Callable[[dict[str, Any]], dict[str, Any]] = _open_editor_on_case,
    now_iso_fn: Callable[[], str] = _utcnow_iso_z,
    write_fn: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> list[dict[str, Any]]:
    """Walk a list of proposed cases interactively, return reviewed list.

    Pure-ish: side effects (stdout, editor) are injected so tests can
    simulate the entire flow with deterministic callables. Returns the
    in-order list of reviewed cases (``approved`` field set on each).
    """
    reviewed: list[dict[str, Any]] = []
    for i, case in enumerate(proposed, start=1):
        write_fn(f"\n=== Case {i}/{len(proposed)} ===")
        write_fn(_format_case_preview(case))
        while True:
            choice = prompt_fn(REVIEW_PROMPT).strip().lower()
            if choice in ("a", "accept"):
                reviewed.append(
                    _annotate_reviewed(
                        case, approved=True, edited=False, now_iso=now_iso_fn()
                    )
                )
                break
            if choice in ("e", "edit"):
                try:
                    edited_case = edit_fn(case)
                except Exception as exc:  # noqa: BLE001 - user-facing surface
                    write_fn(f"  edit failed: {exc}; please try again")
                    continue
                reviewed.append(
                    _annotate_reviewed(
                        edited_case,
                        approved=True,
                        edited=True,
                        now_iso=now_iso_fn(),
                    )
                )
                break
            if choice in ("r", "reject"):
                reviewed.append(
                    _annotate_reviewed(
                        case, approved=False, edited=False, now_iso=now_iso_fn()
                    )
                )
                break
            if choice in ("s", "skip"):
                break
            if choice in ("q", "quit"):
                return reviewed
            if choice in ("?", "help"):
                write_fn(REVIEW_HELP)
                continue
            write_fn(f"  unknown choice: {choice!r}; press ? for help")
    return reviewed


# -----------------------------------------------------------------------------
# YAML I/O
# -----------------------------------------------------------------------------


def read_proposed_yaml(path: Path) -> list[dict[str, Any]]:
    """Load proposed-cases yaml. Tolerant of empty / missing files."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = data.get("proposed_cases")
    if not cases:
        return []
    return list(cases)


def write_reviewed_yaml(reviewed: list[dict[str, Any]], path: Path) -> None:
    """Write reviewed cases. Uses the proposer's deterministic writer
    so reviewer-edited cases keep schema-stable ordering, then
    appends the ``approved`` + ``review_meta`` fields per case.

    The writer below intentionally uses ``yaml.safe_dump`` rather than
    the proposer's hand-rolled emitter — reviewed yaml is consumed
    only by ``case_proposer_promote.py`` (which uses PyYAML) and
    never crosses the commit boundary, so block-style + alphabetic
    ordering is fine here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"reviewed_cases": reviewed}
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="case_proposer_review",
        description=(
            "Interactive review of proposed cases (ADR 0029). Reads "
            "proposed yaml, writes reviewed yaml with `approved` per case."
        ),
    )
    p.add_argument(
        "--proposed",
        type=Path,
        default=DEFAULT_PROPOSED_PATH,
        help=f"Input proposed yaml (default: {DEFAULT_PROPOSED_PATH}).",
    )
    p.add_argument(
        "--reviewed",
        type=Path,
        default=DEFAULT_REVIEWED_PATH,
        help=f"Output reviewed yaml (default: {DEFAULT_REVIEWED_PATH}).",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    proposed = read_proposed_yaml(args.proposed)
    if not proposed:
        print(
            f"case_proposer_review: no proposed cases found at {args.proposed}",
            file=sys.stderr,
        )
        return 0
    print(
        f"case_proposer_review: walking {len(proposed)} proposed case(s)\n"
        f"  proposed:  {args.proposed}\n"
        f"  reviewed:  {args.reviewed}",
        file=sys.stderr,
    )
    reviewed = walk_review_session(proposed, prompt_fn=input)
    write_reviewed_yaml(reviewed, args.reviewed)
    n_approved = sum(1 for c in reviewed if c.get("approved"))
    print(
        f"case_proposer_review: wrote {len(reviewed)} reviewed case(s) "
        f"({n_approved} approved) to {args.reviewed}",
        file=sys.stderr,
    )
    return 0


# Re-export for the promote step (PR2's case_proposer_promote.py).
__all__ = [
    "REVIEW_HELP",
    "REVIEW_PROMPT",
    "main",
    "read_proposed_yaml",
    "walk_review_session",
    "write_reviewed_yaml",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
