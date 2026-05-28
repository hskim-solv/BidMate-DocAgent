"""Deep-copy an index dict without crashing on the Chroma SWIG native handle.

After #1635 made Chroma the canonical baseline backend, `load_index()`'s
return dict carries `_vector_store` = `chromadb.PersistentClient`, whose
internal `builtins.Bindings` cannot be pickled by `copy.deepcopy`. Tests
that previously used `copy.deepcopy(index)` for per-run isolation now hit
`TypeError: cannot pickle 'builtins.Bindings' object`.

The store handle is read-only on the test path (search only, no writes), so
sharing one handle between original and clone is safe. Only the mutable
Python state (chunks, documents, metadata, _vector_store_backend label)
needs isolation.
"""
from __future__ import annotations

import copy
from typing import Any

_SHARED_HANDLE_KEYS: tuple[str, ...] = ("_vector_store",)
_SHARED_LABEL_KEYS: tuple[str, ...] = ("_vector_store_backend",)


def deepcopy_index_safe(index: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of `index` with the native vector-store handle shared.

    The original `index` is not mutated.
    """
    extracted: dict[str, Any] = {}
    skeleton: dict[str, Any] = {}
    shared = _SHARED_HANDLE_KEYS + _SHARED_LABEL_KEYS
    for key, value in index.items():
        if key in shared:
            extracted[key] = value
        else:
            skeleton[key] = value
    cloned = copy.deepcopy(skeleton)
    cloned.update(extracted)
    return cloned
