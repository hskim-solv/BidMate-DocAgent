from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILENAMES = {"mode_specs.json", "metadata_specs.json", "chunking_specs.json"}


def _tracked_retrieval_specs() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "reports/retrieval"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        REPO_ROOT / line
        for line in result.stdout.splitlines()
        if Path(line).name in SPEC_FILENAMES
    ]


def _spec_objects(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            if isinstance(value, dict):
                yield from _spec_objects(value)
            elif isinstance(value, list):
                for item in value:
                    yield from _spec_objects(item)
    elif isinstance(payload, list):
        for item in payload:
            yield from _spec_objects(item)


def test_private_real100_reports_do_not_commit_low_chunk_specs() -> None:
    offenders: list[str] = []
    for spec_path in _tracked_retrieval_specs():
        if not spec_path.exists():
            continue
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
        for spec in _spec_objects(payload):
            docs = spec.get("num_documents")
            chunks = spec.get("num_chunks")
            if docs is None or chunks is None:
                continue
            if int(docs) >= 50 and 0 < int(chunks) <= 1000:
                rel = spec_path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}: {docs} documents, {chunks} chunks")

    assert offenders == [], (
        "tracked private real100 retrieval reports must not include <=1000-chunk "
        "CSV-fallback artifacts:\n" + "\n".join(offenders)
    )
