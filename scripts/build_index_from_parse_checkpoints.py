#!/usr/bin/env python3
"""Build an index from private parse checkpoints without reparsing source files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.scorers.chunk_health import compute_chunk_health  # noqa: E402
from rag_core import (  # noqa: E402
    EMBEDDINGS_FILENAME,
    INDEX_FILENAME,
    build_index_payload_from_documents,
    write_index,
)
from rag_embedding import DEFAULT_EMBEDDING_MODEL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument(
        "--embedding_backend",
        default="sentence-transformers",
        choices=["auto", "sentence-transformers", "hashing", "openai"],
    )
    parser.add_argument("--chunking_strategy", default="section", choices=["auto", "section", "fixed", "contextual"])
    parser.add_argument("--force", action="store_true", help="Rebuild even when a matching checkpoint index already exists.")
    return parser.parse_args()


def _load_documents(checkpoint_dir: Path) -> list[dict]:
    if not checkpoint_dir.is_dir():
        raise ValueError(f"--checkpoint_dir must be a directory: {checkpoint_dir}")
    documents: list[dict] = []
    for path in sorted(checkpoint_dir.glob("row_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        document = payload.get("document")
        if isinstance(document, dict):
            documents.append(document)
    if not documents:
        raise ValueError(f"no checkpoint documents found in {checkpoint_dir}")
    return documents


def _checkpoint_signature(checkpoint_dir: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(checkpoint_dir.glob("row_*.json")):
        file_count += 1
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "version": 1,
        "file_count": file_count,
        "sha256": digest.hexdigest(),
    }


def _existing_index_matches(
    *,
    output_dir: Path,
    checkpoint_dir: Path,
    signature: dict[str, Any],
    model: str,
    embedding_backend: str,
    chunking_strategy: str,
) -> tuple[bool, str]:
    index_path = output_dir / INDEX_FILENAME
    embeddings_path = output_dir / EMBEDDINGS_FILENAME
    if not index_path.exists() or not embeddings_path.exists():
        return False, "missing index or embeddings sidecar"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "existing index is unreadable"

    build = payload.get("build") if isinstance(payload.get("build"), dict) else {}
    embedding = payload.get("embedding") if isinstance(payload.get("embedding"), dict) else {}
    chunking = build.get("chunking") if isinstance(build.get("chunking"), dict) else {}
    checkpoint_source = build.get("checkpoint_source") if isinstance(build.get("checkpoint_source"), dict) else {}

    if checkpoint_source.get("signature") != signature:
        return False, "checkpoint signature changed"
    if build.get("source_dir") != str(checkpoint_dir):
        return False, "checkpoint source directory changed"
    if embedding.get("model") != model:
        return False, "embedding model changed"
    if embedding_backend != "auto" and embedding.get("backend") != embedding_backend:
        return False, "embedding backend changed"
    if chunking.get("requested_strategy") != chunking_strategy:
        return False, "chunking strategy changed"
    return True, "matching checkpoint index already exists"


def main() -> int:
    args = parse_args()
    try:
        documents = _load_documents(args.checkpoint_dir)
        signature = _checkpoint_signature(args.checkpoint_dir)
        print(
            "[CONFIG] checkpoint index build:",
            f"checkpoints={len(list(args.checkpoint_dir.glob('row_*.json')))}",
            f"documents={len(documents)}",
            f"embedding={args.embedding_backend}",
            f"model={args.model}",
            f"chunking={args.chunking_strategy}",
            flush=True,
        )
        if not args.force:
            reusable, reason = _existing_index_matches(
                output_dir=args.output_dir,
                checkpoint_dir=args.checkpoint_dir,
                signature=signature,
                model=args.model,
                embedding_backend=args.embedding_backend,
                chunking_strategy=args.chunking_strategy,
            )
            if reusable:
                print(f"[OK] checkpoint index reuse: {reason}", flush=True)
                return 0
            print(f"[INFO] checkpoint index rebuild required: {reason}", flush=True)
        payload = build_index_payload_from_documents(
            documents,
            source_dir=str(args.checkpoint_dir),
            model_name=args.model,
            embedding_backend=args.embedding_backend,
            chunking_strategy=args.chunking_strategy,
            message="Index built from private page-aware parse checkpoints.",
        )
        payload.setdefault("build", {})["checkpoint_source"] = {
            "checkpoint_dir": str(args.checkpoint_dir),
            "signature": signature,
        }
        payload.setdefault("build", {})["chunk_health"] = compute_chunk_health(payload.get("chunks") or [])
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = write_index(payload, args.output_dir)
    except Exception as exc:
        print(f"[ERROR] checkpoint index build failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[OK] checkpoint index written:",
        f"{out_path}",
        f"(+ {EMBEDDINGS_FILENAME})",
        f"docs={payload['build']['num_documents']}",
        f"chunks={payload['build']['num_chunks']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
