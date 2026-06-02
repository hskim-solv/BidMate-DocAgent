"""LedgerState single-serialized-writer regression (issue #1773, ADR 0094 PR-A2).

``agent_loop.LedgerState`` is the substrate brick that moves the bounded-loop
ledger facts (completed / deferred / cycles / blockers / consecutive_blockers)
behind ONE in-process ``threading.Lock`` so every mutation is serialized. The
senior contract this guards:

* **Byte-identity (ADR 0001 gate)** — ``persist(path, payload)`` writes on-disk
  bytes identical to ``json.dumps(_sanitize_json_value(payload), indent=2,
  sort_keys=True) + "\\n"`` and drops no temp artifact, so at X=1 (one writer)
  the ``auto_loop_state.json`` payload is the same byte sequence as the
  pre-refactor inline ``_atomic_write_text`` call it replaced.
* **Snapshot contract** — ``snapshot()`` emits exactly the 4 ledger keys
  (``completed_task_ids`` / ``deferred_task_ids`` / ``cycles`` / ``blockers``),
  blockers deduped *at snapshot only* (the raw ``_blockers`` keeps duplicates),
  and ``consecutive_blockers`` is never serialized (transient guard).
* **Coupled completion** — ``record_completed`` performs three coupled mutations
  under one lock: guarded completed-append + deferred filter-remove + consecutive
  reset.
* **Lost-update-free under contention** — N threads recording disjoint task ids
  all land (no last-writer-wins / lost update), and the same id from many threads
  appears exactly once. This is THE property PR-A2 guarantees before the X
  task-pool (PR-E) is enabled.

Payloads are pinned explicitly so the tests are deterministic across machines
and need no external model / network.
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
from pathlib import Path
from typing import cast

from scripts import agent_loop


def test_persist_bytes_identical_and_no_temp_artifact(tmp_path: Path) -> None:
    """LedgerState.persist output == json.dumps(...sort_keys) and leaves no temp.

    Pins the exact on-disk bytes against the same serialization expression the
    production checkpoint/terminal writes use, proving the LedgerState.persist
    swap is output-preserving (ADR 0094 PR-A2 / ADR 0001 byte-identical gate).
    """
    path = tmp_path / "active" / ".auto_loop_state.json"
    # A payload shaped like the loop's checkpoint/terminal state (unsorted keys on
    # purpose: sort_keys=True makes construction order irrelevant to the bytes).
    payload = {
        "schema_version": 1,
        "decision": "running",
        "completed_task_ids": ["T-2026-0002", "T-2026-0001"],
        "deferred_task_ids": ["T-2026-0003"],
        "next_task_id": None,
        "cycles": [{"iteration": 1, "task_id": "T-2026-0001", "completed": True}],
        "blockers": ["b1", "b2"],
        "warnings": ["max-iterations resolved to 1 (cli)"],
    }
    expected_bytes = (
        json.dumps(agent_loop._sanitize_json_value(payload), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    ledger = agent_loop.LedgerState()
    ledger.persist(path, payload)

    assert path.read_bytes() == expected_bytes
    # No .<name>.* temp artifact survives the atomic temp+replace write.
    assert list(path.parent.glob(".auto_loop_state.json.*")) == []


def test_snapshot_contract_dedupes_blockers_only_at_snapshot() -> None:
    """snapshot() emits the 4 ledger keys; blockers deduped at snapshot only."""
    ledger = agent_loop.LedgerState()
    ledger.record_completed("T-2026-0001")
    ledger.record_completed("T-2026-0001")  # guard: no duplicate
    ledger.record_completed("T-2026-0002")
    ledger.record_deferred("T-2026-0003")
    ledger.record_deferred("T-2026-0003")  # guard: no duplicate
    ledger.extend_blockers(["b1", "b1", "b2"])

    snap = ledger.snapshot()

    # Exactly the 4 ledger keys — consecutive_blockers is never serialized.
    assert set(snap) == {"completed_task_ids", "deferred_task_ids", "cycles", "blockers"}
    # completed keeps insertion order and the guard collapsed the duplicate.
    assert snap["completed_task_ids"] == ["T-2026-0001", "T-2026-0002"]
    # deferred guard collapsed the duplicate; the deferred id was never completed.
    assert snap["deferred_task_ids"] == ["T-2026-0003"]
    # blockers deduped AT SNAPSHOT ...
    assert snap["blockers"] == ["b1", "b2"]
    # ... while the live raw list still holds the duplicate (dedupe-at-snapshot).
    assert ledger.blockers == ["b1", "b1", "b2"]
    # snapshot returns copies: mutating it must not leak into ledger state.
    cast("list[str]", snap["completed_task_ids"]).append("T-9999-9999")
    assert ledger.completed == ["T-2026-0001", "T-2026-0002"]


def test_record_completed_is_three_coupled_mutations() -> None:
    """record_completed: completed-append + deferred-remove + consecutive reset."""
    ledger = agent_loop.LedgerState(deferred=["T-2026-1001"])
    assert ledger.bump_consecutive_blocker() == 1
    assert ledger.bump_consecutive_blocker() == 2
    assert ledger.consecutive_blockers == 2

    ledger.record_completed("T-2026-1001")

    # 1) completed-append (guarded).
    assert ledger.completed == ["T-2026-1001"]
    # 2) deferred filter-remove — the now-completed id is gone.
    assert ledger.deferred == []
    # 3) consecutive_blockers reset to zero on completion.
    assert ledger.consecutive_blockers == 0


def test_append_cycle_holds_dict_by_reference() -> None:
    """append_cycle stores the cycle dict BY REFERENCE: in-place mutations made
    AFTER the append (the loop marks completion on the same dict it appended) are
    visible to snapshot(). A defensive copy here would silently drop them."""
    ledger = agent_loop.LedgerState()
    cycle: dict[str, object] = {"iteration": 1, "task_id": "T-2026-0001"}
    ledger.append_cycle(cycle)
    # The loop mutates the SAME dict after appending it (e.g. records the outcome).
    cycle["completed"] = True
    cycle["stop_reason"] = None

    snap = ledger.snapshot()
    cycles = cast("list[dict[str, object]]", snap["cycles"])
    assert cycles == [
        {"iteration": 1, "task_id": "T-2026-0001", "completed": True, "stop_reason": None}
    ]


def test_record_completed_lost_update_free_under_contention() -> None:
    """64 threads record disjoint ids -> all land (no lost update / last-writer-wins).

    This is THE property PR-A2 guarantees: before the lock, the unlocked
    snapshot+rewrite ledger dropped concurrent updates. Under the lock every
    disjoint completion is preserved.
    """
    n = 64
    ledger = agent_loop.LedgerState()
    ids = [f"T-2026-{i:04d}" for i in range(n)]
    barrier = threading.Barrier(n)

    def _run(task_id: str) -> None:
        barrier.wait()  # maximize overlap on the write path
        ledger.record_completed(task_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_run, task_id) for task_id in ids]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    snap = ledger.snapshot()
    # Every disjoint id landed exactly once — nothing lost to a racing rewrite.
    assert len(cast("list[str]", snap["completed_task_ids"])) == n
    assert set(cast("list[str]", snap["completed_task_ids"])) == set(ids)

    # Same id from many threads must appear exactly once (the in-set guard holds
    # under the lock — without it, concurrent "not in" checks would double-append).
    ledger2 = agent_loop.LedgerState()
    barrier2 = threading.Barrier(n)

    def _run_same() -> None:
        barrier2.wait()
        ledger2.record_completed("T-2026-7777")

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_run_same) for _ in range(n)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert ledger2.snapshot()["completed_task_ids"] == ["T-2026-7777"]


def test_lock_serializes_snapshot_never_torn(tmp_path: Path) -> None:
    """Interleaved writers + concurrent snapshots -> every snapshot is serializable.

    A reader (snapshot) must never observe a half-applied mutation (a torn dict
    that json.dumps cannot serialize or that mixes states). The lock guarantees
    each snapshot is a consistent, JSON-dumpable view.
    """
    ledger = agent_loop.LedgerState()
    writers = 24
    snapshotters = 24
    barrier = threading.Barrier(writers + snapshotters)
    errors: list[BaseException] = []
    err_lock = threading.Lock()

    def _writer(i: int) -> None:
        barrier.wait()
        try:
            ledger.record_deferred(f"T-2026-{i:04d}")
            ledger.append_cycle({"iteration": i, "task_id": f"T-2026-{i:04d}"})
            ledger.extend_blockers([f"blk-{i}"])
            ledger.record_completed(f"T-2026-{i:04d}")
        except BaseException as exc:  # noqa: BLE001 - surface any thread failure
            with err_lock:
                errors.append(exc)

    def _snapshotter() -> None:
        barrier.wait()
        try:
            for _ in range(50):
                snap = ledger.snapshot()
                # Must be json-dumpable every time (never a torn / partial dict).
                json.dumps(agent_loop._sanitize_json_value(snap), sort_keys=True)
                assert set(snap) == {
                    "completed_task_ids",
                    "deferred_task_ids",
                    "cycles",
                    "blockers",
                }
        except BaseException as exc:  # noqa: BLE001
            with err_lock:
                errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=writers + snapshotters) as ex:
        futures = [ex.submit(_writer, i) for i in range(writers)]
        futures += [ex.submit(_snapshotter) for _ in range(snapshotters)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert errors == []
    # Final state is consistent and persists byte-identically.
    final = ledger.snapshot()
    assert len(cast("list[str]", final["completed_task_ids"])) == writers
    out = tmp_path / "active" / ".auto_loop_state.json"
    ledger.persist(out, final)
    assert json.loads(out.read_text(encoding="utf-8"))["completed_task_ids"]
