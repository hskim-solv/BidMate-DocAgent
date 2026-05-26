#!/usr/bin/env python3
"""Render a local HTML board for ADR navigation.

Reads ``docs/adr/README.md`` only and emits a local, ignored HTML map. This is
presentation tooling: it never edits ADR files, reserves numbers, or changes
decision status.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.html_report import render_document, render_status_card, render_table

DEFAULT_ADR_README = ROOT / "docs" / "adr" / "README.md"
DEFAULT_OUT_HTML = ROOT / "reports" / "adr_decision_map.html"

ADR_ROW_RE = re.compile(
    r"^\| \[(?P<number>\d{4})\]\((?P<link>\./[^)]+\.md)\) \| "
    r"(?P<status>.*?) \| (?P<title>.*) \|$"
)


@dataclass(frozen=True)
class AdrEntry:
    number: int
    link: str
    status: str
    title: str
    area: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\|", "|")).strip()


def _status_family(status: str) -> str:
    lowered = status.lower()
    if "superseded" in lowered:
        return "superseded"
    if "deprecated" in lowered:
        return "deprecated"
    if "accepted" in lowered:
        return "accepted"
    if "proposed" in lowered:
        return "proposed"
    return "other"


def _area_for(entry_text: str) -> str:
    text = entry_text.lower()
    if any(key in text for key in ("eval", "real", "benchmark", "metric", "judge")):
        return "eval / measurement"
    if any(key in text for key in ("retrieval", "embedding", "rerank", "bm25", "chunk")):
        return "retrieval"
    if any(key in text for key in ("hwp", "pdf", "parser", "ingestion", "page")):
        return "ingestion"
    if any(key in text for key in ("agent", "langgraph", "workflow", "codex")):
        return "agent workflow"
    if any(key in text for key in ("governance", "branch", "pr", "hook")):
        return "governance"
    if any(key in text for key in ("answer", "citation", "verifier", "evidence")):
        return "answer / evidence"
    if any(key in text for key in ("security", "injection", "pii")):
        return "security"
    return "foundation / other"


def parse_adr_index(markdown: str) -> list[AdrEntry]:
    entries: list[AdrEntry] = []
    for line in markdown.splitlines():
        match = ADR_ROW_RE.match(line)
        if not match:
            continue
        status = _clean(match.group("status"))
        title = _clean(match.group("title"))
        link = _clean(match.group("link"))
        entries.append(
            AdrEntry(
                number=int(match.group("number")),
                link=link,
                status=status,
                title=title,
                area=_area_for(f"{link} {status} {title}"),
            )
        )
    return entries


def build_board(entries: Iterable[AdrEntry]) -> dict[str, object]:
    ordered = sorted(entries, key=lambda item: item.number)
    status_counts = Counter(_status_family(item.status) for item in ordered)
    area_counts = Counter(item.area for item in ordered)
    proposed = [item for item in ordered if _status_family(item.status) == "proposed"]
    superseded = [item for item in ordered if _status_family(item.status) == "superseded"]
    accepted = [item for item in ordered if _status_family(item.status) == "accepted"]
    return {
        "total": len(ordered),
        "latest": ordered[-1].number if ordered else None,
        "status_counts": dict(sorted(status_counts.items())),
        "area_counts": dict(area_counts.most_common()),
        "recent": list(reversed(ordered[-12:])),
        "proposed": proposed,
        "superseded": superseded,
        "accepted_count": len(accepted),
    }


def _entry_rows(entries: Iterable[AdrEntry]) -> list[list[object]]:
    return [
        [
            f"{entry.number:04d}",
            entry.status,
            entry.area,
            entry.title,
            entry.link,
        ]
        for entry in entries
    ]


def render_html(board: dict[str, object]) -> str:
    status_counts = board.get("status_counts")
    if not isinstance(status_counts, dict):
        status_counts = {}
    area_counts = board.get("area_counts")
    if not isinstance(area_counts, dict):
        area_counts = {}
    recent = board.get("recent")
    proposed = board.get("proposed")
    superseded = board.get("superseded")
    recent_entries = [item for item in recent if isinstance(item, AdrEntry)] if isinstance(recent, list) else []
    proposed_entries = [item for item in proposed if isinstance(item, AdrEntry)] if isinstance(proposed, list) else []
    superseded_entries = [item for item in superseded if isinstance(item, AdrEntry)] if isinstance(superseded, list) else []

    total = board.get("total", 0)
    latest = board.get("latest")
    cards = [
        render_status_card("Total ADRs", total, detail="indexed decisions", tone="accent"),
        render_status_card("Latest ADR", f"{latest:04d}" if isinstance(latest, int) else "-", tone="neutral"),
        render_status_card("Accepted", status_counts.get("accepted", 0), tone="ok"),
        render_status_card("Proposed", status_counts.get("proposed", 0), tone="warn"),
    ]
    status_rows = [[key, value] for key, value in sorted(status_counts.items())]
    area_rows = [[key, value] for key, value in area_counts.items()]

    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            '<section class="panel"><h2>Status Mix</h2>'
            + render_table(["Status", "Count"], status_rows)
            + "</section>",
            '<section class="panel"><h2>Decision Areas</h2>'
            '<p class="note">Keyword-based map for navigation only; ADR files remain the source of truth.</p>'
            + render_table(["Area", "Count"], area_rows)
            + "</section>",
            '<section class="panel"><h2>Recent ADRs</h2>'
            + render_table(
                ["ADR", "Status", "Area", "Title", "Link"],
                _entry_rows(recent_entries),
            )
            + "</section>",
            '<section class="panel"><h2>Open Proposed Decisions</h2>'
            + render_table(
                ["ADR", "Status", "Area", "Title", "Link"],
                _entry_rows(proposed_entries),
                empty_message="No proposed ADRs",
            )
            + "</section>",
            '<section class="panel"><h2>Superseded / Retired Decisions</h2>'
            + render_table(
                ["ADR", "Status", "Area", "Title", "Link"],
                _entry_rows(superseded_entries),
                empty_message="No superseded ADRs",
            )
            + "</section>",
        ]
    )
    return render_document(
        title="ADR Decision Map",
        subtitle=(
            "Local human-readable navigation view generated from docs/adr/README.md. "
            "This page does not reserve ADR numbers or change decision status."
        ),
        body=body,
        footer=(
            "Local workflow artifact. ADR markdown files and docs/adr/README.md "
            "remain the source of truth."
        ),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adr-readme", type=Path, default=DEFAULT_ADR_README)
    parser.add_argument("--out-html", type=Path, default=DEFAULT_OUT_HTML)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.adr_readme.exists():
        print(f"ADR README not found: {args.adr_readme}", file=sys.stderr)
        return 1
    entries = parse_adr_index(args.adr_readme.read_text(encoding="utf-8"))
    board = build_board(entries)
    args.out_html.parent.mkdir(parents=True, exist_ok=True)
    args.out_html.write_text(render_html(board), encoding="utf-8")
    print(f"[OK] Wrote {args.out_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
