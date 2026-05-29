#!/usr/bin/env python3
"""Create a local-small LLM synthesis baseline config for real100_v2.

The source private config stays local. This helper writes a derived local
config containing two rows:

* ``naive_stub_control``: deterministic Chroma+dense retrieval control.
* ``naive_baseline_llm``: the same retrieval surface with
  ``prompt_profile=llm_synthesis`` for local OpenAI-compatible synthesis.

No case text is printed. The output path should stay in an ignored local report
directory.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a derived real100_v2 local LLM baseline config."
    )
    parser.add_argument("--config", required=True, help="Source private real100_v2 YAML config.")
    parser.add_argument("--output", required=True, help="Derived local YAML config to write.")
    return parser.parse_args()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise ValueError(f"config must include non-empty cases: {path}")
    return payload


def _base_naive_row(config: dict[str, Any]) -> dict[str, Any]:
    runs = config.get("ablation_runs")
    if isinstance(runs, list):
        for row in runs:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            pipeline = str(row.get("pipeline") or "")
            if name == "naive_baseline" or pipeline == "naive_baseline":
                return deepcopy(row)
    return {"name": "naive_baseline", "pipeline": "naive_baseline"}


def _force_naive_retrieval(row: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(row)
    updated.update(
        {
            "pipeline": "naive_baseline",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "retrieval_mode": "flat",
            "retrieval_backend": "dense",
            "query_expansion": "identity",
            "vector_store_backend": "chroma",
        }
    )
    return updated


def build_config(config: dict[str, Any]) -> dict[str, Any]:
    base = _force_naive_retrieval(_base_naive_row(config))
    stub = deepcopy(base)
    stub.update(
        {
            "name": "naive_stub_control",
            "prompt_profile": "minimal_grounded_extractive",
        }
    )
    llm = deepcopy(base)
    llm.update(
        {
            "name": "naive_baseline_llm",
            "prompt_profile": "llm_synthesis",
        }
    )

    derived = deepcopy(config)
    derived["primary_run"] = "naive_baseline_llm"
    derived["ablation_runs"] = [stub, llm]
    derived["description"] = (
        "Local-only real100_v2 Chroma naive baseline with deterministic stub "
        "control plus loopback local-small LLM synthesis row."
    )
    return derived


def main() -> int:
    args = parse_args()
    source = Path(args.config)
    output = Path(args.output)
    derived = build_config(_load_yaml(source))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(derived, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"[OK] wrote local LLM baseline config: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
