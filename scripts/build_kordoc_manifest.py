#!/usr/bin/env python3
"""Write a kordoc cache ``manifest.json`` for a pre-extracted ``.md`` cache.

Issue #1278: ``ingestion._kordoc_convert_batch`` only bypasses the npx
subprocess when the cache directory carries a manifest proving each
``<stem>.md`` came from the current source bytes. A committed cache (e.g.
``data/files_kordoc``) predating that gate has no manifest, so its bypass is
refused until re-primed here.

For every ``<stem>.md`` in ``--cache-dir`` this finds the matching source file
in ``--source-dir`` (by NFC-normalized stem) and records its sha256 + size.
The manifest carries the global ``kordoc_spec`` (from ``.kordoc-version``) and
``postprocess_version`` so a kordoc/postprocess upgrade also invalidates the
cache. Only digests/relpaths/versions are written — never source text — so the
manifest stays inside the ADR 0005 data boundary.

Usage::

    python3 scripts/build_kordoc_manifest.py \
        --source-dir data/files --cache-dir data/files_kordoc
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ingestion import (  # noqa: E402 — sys.path bootstrap above
    _KORDOC_MANIFEST_FILENAME,
    _KORDOC_MANIFEST_SCHEMA_VERSION,
    _KORDOC_POSTPROCESS_VERSION,
    _read_kordoc_version_spec,
    sha256_file,
)


def _index_sources_by_stem(source_dir: Path) -> dict[str, Path]:
    """Map NFC-normalized stem → source path for every file in ``source_dir``."""
    by_stem: dict[str, Path] = {}
    for path in sorted(source_dir.iterdir()):
        if not path.is_file():
            continue
        stem = unicodedata.normalize("NFC", path.stem)
        by_stem.setdefault(stem, path)
    return by_stem


def build_manifest(source_dir: Path, cache_dir: Path) -> dict:
    """Build the manifest dict for ``cache_dir`` against ``source_dir``.

    Each ``<stem>.md`` in the cache is matched to a source by NFC stem. A
    cached ``.md`` with no surviving source (the stale/wrong-source case the
    integrity gate guards against) is skipped with a warning, so it stays
    out of the manifest and its bypass keeps being refused at runtime.
    """
    sources_by_stem = _index_sources_by_stem(source_dir)
    entries: dict[str, dict] = {}
    skipped: list[str] = []

    for md_path in sorted(cache_dir.glob("*.md")):
        stem = unicodedata.normalize("NFC", md_path.stem)
        source_path = sources_by_stem.get(stem)
        if source_path is None:
            skipped.append(md_path.name)
            continue
        entries[stem] = {
            "source_relpath": source_path.name,
            "source_sha256": sha256_file(source_path),
            "source_size": source_path.stat().st_size,
        }

    if skipped:
        print(
            f"[warn] {len(skipped)} cached .md had no matching source "
            f"(skipped, bypass stays refused): {', '.join(skipped[:10])}"
            + (" ..." if len(skipped) > 10 else ""),
            file=sys.stderr,
        )

    return {
        "schema_version": _KORDOC_MANIFEST_SCHEMA_VERSION,
        "kordoc_spec": _read_kordoc_version_spec(),
        "postprocess_version": _KORDOC_POSTPROCESS_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a kordoc cache manifest.json (issue #1278).",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/files"),
        help="Directory of original HWP/PDF source files.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/files_kordoc"),
        help="Directory of pre-extracted <stem>.md kordoc output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source_dir.is_dir():
        print(f"[error] source dir not found: {args.source_dir}", file=sys.stderr)
        return 2
    if not args.cache_dir.is_dir():
        print(f"[error] cache dir not found: {args.cache_dir}", file=sys.stderr)
        return 2

    manifest = build_manifest(args.source_dir, args.cache_dir)
    manifest_path = args.cache_dir / _KORDOC_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[ok] wrote {manifest_path} ({len(manifest['entries'])} entries, "
        f"spec={manifest['kordoc_spec']}, pp_version={manifest['postprocess_version']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
