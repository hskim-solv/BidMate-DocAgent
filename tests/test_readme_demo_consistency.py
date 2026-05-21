"""Hero-asset consistency gate.

The README front-page hero code block and its terminal replay
(``docs/assets/demo.cast`` → ``docs/assets/demo.gif``) must cite the *same*
evidence. PR #1117 refreshed the README hero to the current hybrid run
(``chunk-056`` / ``chunk-094``) but left ``demo.cast`` on the stale 2-doc-corpus
output (``chunk-001``, ``latency_ms=5.79``), so the code block a reviewer reads
and the replay they click diverged — the exact drift this gate pins.

The chunk-id set equality is the load-bearing invariant: it is what the README
calls reproducible ("``make ask`` 복붙 시 동일 claim·citation 재현"). Latency is
deliberately *not* pinned — the README discloses it as a machine-variable
single-run wall-clock, not a reported metric.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
README = ROOT_DIR / "README.md"
CAST = ROOT_DIR / "docs" / "assets" / "demo.cast"
GIF = ROOT_DIR / "docs" / "assets" / "demo.gif"

HERO_HEADER = "### 5초 비주얼 훅"
CHUNK_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*::chunk-\d+")


def _hero_block() -> str:
    """The fenced code block under the hero header (the front-page replay)."""
    text = README.read_text(encoding="utf-8")
    start = text.find(HERO_HEADER)
    assert start != -1, f"README hero header missing: {HERO_HEADER!r}"
    fence = text.find("```", start)
    assert fence != -1, "no opening code fence after README hero header"
    body_start = text.find("\n", fence) + 1
    end = text.find("```", body_start)
    assert end != -1, "no closing code fence for README hero block"
    return text[body_start:end]


def _cast_text() -> str:
    """Concatenated stdout of every asciicast 'o' (output) event."""
    chunks: list[str] = []
    for line in CAST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue  # the version-2 header object on line 1
        event = json.loads(line)
        if len(event) >= 3 and event[1] == "o":
            chunks.append(event[2])
    return "".join(chunks)


def test_hero_and_cast_cite_same_chunks() -> None:
    hero = set(CHUNK_ID_RE.findall(_hero_block()))
    cast = set(CHUNK_ID_RE.findall(_cast_text()))
    assert hero, "no chunk ids found in README hero block — extraction broke"
    assert cast, "no chunk ids found in demo.cast — extraction broke"
    assert hero == cast, (
        "README hero ↔ demo.cast chunk-id drift — regenerate the cast/gif "
        "from the same `make ask` run:\n"
        f"  README only: {sorted(hero - cast)}\n"
        f"  cast only:   {sorted(cast - hero)}"
    )


def test_hero_and_cast_share_command_and_backend() -> None:
    hero, cast = _hero_block(), _cast_text()
    assert "make ask" in hero and "make ask" in cast, "hero command drifted"
    # ADR 0058: agentic_full defaults to hybrid; both surfaces must say so.
    assert "hybrid" in hero and "hybrid" in cast, "retrieval backend drifted"


def test_cast_has_no_stale_markers() -> None:
    cast = _cast_text()
    # The literal PR #1117 drift fingerprint: 2-doc-corpus latency + chunk.
    assert "5.79" not in cast, "stale latency_ms=5.79 — demo.cast not regenerated"
    assert "chunk-001" not in cast, "stale chunk-001 citation — demo.cast not regenerated"


def test_hero_assets_present_and_nonempty() -> None:
    assert CAST.is_file() and CAST.stat().st_size > 0, "demo.cast missing/empty"
    assert GIF.is_file() and GIF.stat().st_size > 0, "demo.gif missing/empty"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
