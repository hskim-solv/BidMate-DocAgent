"""Atomic ledger/lease write regression (issue #1766, ADR 0094 PR-A1).

``agent_loop._atomic_write_text`` is the crash-atomic substrate brick for
ledger / lease writes: it writes to a temp file in the same directory, holds an
exclusive flock during the write on POSIX, then ``os.replace`` (atomic rename)
into place. The senior contract this guards:

* **Byte-identity (ADR 0001 gate)** — the on-disk bytes MUST equal what
  ``path.write_text(content, encoding="utf-8")`` produces. Only the write
  *path* changes, never the output.
* **No partial files** — a crash/exception mid-write (here: ``os.replace``
  raising) leaves the prior bytes intact and drops no temp artifact.
* **No torn reads under contention** — concurrent writers race on the same
  path but a reader always sees one complete payload (last-writer-wins is
  fine; a torn/partial file is the bug).

We pin payloads explicitly so the test is deterministic across machines and
needs no external model / network.
"""
from __future__ import annotations

import concurrent.futures
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import agent_loop


def test_atomic_write_temp_then_replace_roundtrips_identical(tmp_path: Path) -> None:
    """_atomic_write_text output is byte-identical to write_text(...)."""
    content = json.dumps({"b": 2, "a": 1, "nested": [1, 2, 3]}, indent=2, sort_keys=True) + "\n"
    target = tmp_path / "ledger.json"
    reference = tmp_path / "ledger_reference.json"

    agent_loop._atomic_write_text(target, content)
    reference.write_text(content, encoding="utf-8")

    assert target.read_text(encoding="utf-8") == content
    # The byte-identity proof vs the plain write_text path it replaces.
    assert target.read_bytes() == reference.read_bytes()


def test_atomic_write_no_partial_file_on_failure(monkeypatch, tmp_path: Path) -> None:
    """An os.replace failure re-raises, preserves OLD bytes, leaves no temp."""
    target = tmp_path / "leases.json"
    old_bytes = (json.dumps({"schema_version": 1, "leases": []}, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target.write_bytes(old_bytes)

    def _boom(src, dst):  # noqa: ANN001 - signature mirrors os.replace
        raise OSError("simulated crash between fsync and rename")

    monkeypatch.setattr(agent_loop.os, "replace", _boom)

    new_content = json.dumps({"schema_version": 1, "leases": [{"lease_id": "x"}]}, indent=2, sort_keys=True) + "\n"
    with pytest.raises(OSError):
        agent_loop._atomic_write_text(target, new_content)

    # Target untouched (old bytes survive) and the temp file was cleaned up.
    assert target.read_bytes() == old_bytes
    assert list(target.parent.glob(".leases.json.*")) == []


def test_atomic_write_leaves_no_temp_artifacts(tmp_path: Path) -> None:
    """A successful _write_active_leases drops no .<name>.* temp artifact."""
    path = tmp_path / "active" / "leases.json"
    now = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
    leases = [
        {
            "lease_id": "lease-1",
            "status": "active",
            "lease_type": "write",
            "owner_session": "implementer",
            "branch": "chore/issue-1766-atomic-ledger-write",
            "worktree": ".",
            "expires_at": "2026-06-02T13:00:00Z",
        }
    ]

    result_path = agent_loop._write_active_leases(path, leases=leases, now=now)

    assert result_path == path
    assert list(path.parent.glob(".leases.json.*")) == []
    # Content is well-formed JSON.
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == 1
    assert parsed["leases"][0]["lease_id"] == "lease-1"


def test_write_active_leases_content_unchanged_after_retrofit(tmp_path: Path) -> None:
    """_write_active_leases bytes equal the pre-retrofit json.dumps(...) form.

    This pins the exact on-disk bytes the function produced before the atomic
    swap, recomputed from the same payload-building logic, proving the retrofit
    is output-preserving (ADR 0094 PR-A1 / ADR 0001 byte-identical gate).
    """
    path = tmp_path / "active" / "leases.json"
    now = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
    leases = [
        {
            "lease_id": "lease-1",
            "status": "active",
            "lease_type": "write",
            "owner_session": "implementer",
            "active_agent": None,
            "branch": "chore/issue-1766-atomic-ledger-write",
            "worktree": ".",
            "last_heartbeat": "2026-06-02T12:00:00Z",
            "lease_expires_at": "2026-06-02T13:00:00Z",
        },
        {
            "lease_id": "lease-2",
            "status": "recovery-needed",
            "lease_type": "read",
            "owner_session": "reviewer",
            "branch": "chore/issue-1766-atomic-ledger-write",
            "worktree": ".",
            "expires_at": "2026-06-02T11:00:00Z",
        },
    ]

    # Mirror the exact payload-building logic in _write_active_leases so the
    # expected bytes are derived the same way the production code derives them.
    expected_payload = {
        "schema_version": 1,
        "generated_at": agent_loop._isoformat(now),
        "leases": [agent_loop._sanitize_json_value(item) for item in leases],
    }
    expected_bytes = (
        json.dumps(expected_payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    agent_loop._write_active_leases(path, leases=leases, now=now)

    assert path.read_bytes() == expected_bytes


def test_atomic_write_concurrent_writers_yield_complete_file(tmp_path: Path) -> None:
    """N threads write distinct payloads to ONE path; reader sees no torn file.

    Last-writer-wins is acceptable; the guarantee is that the final file is a
    complete, parseable payload equal to exactly one candidate — never a
    half-written / interleaved blob.
    """
    target = tmp_path / "active" / "leases.json"
    n = 16
    candidates = [
        json.dumps(
            {"schema_version": 1, "writer": i, "leases": [{"lease_id": f"lease-{i}"}]},
            indent=2,
            sort_keys=True,
        )
        + "\n"
        for i in range(n)
    ]

    def _run(content: str) -> None:
        agent_loop._atomic_write_text(target, content)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_run, candidates[i]) for i in range(n)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    final = target.read_text(encoding="utf-8")
    # Parses cleanly (never torn) ...
    parsed = json.loads(final)
    assert parsed["schema_version"] == 1
    # ... and is exactly one of the full candidate payloads.
    assert final in candidates
    # No temp artifacts survive the race.
    assert list(target.parent.glob(".leases.json.*")) == []
