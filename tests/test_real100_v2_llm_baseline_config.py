from __future__ import annotations

from scripts.make_real100_v2_llm_baseline_config import build_config


def test_build_config_adds_stub_control_and_llm_primary() -> None:
    source = {
        "mode": "rag",
        "primary_run": "full",
        "ablation_runs": [
            {
                "name": "naive_baseline",
                "pipeline": "naive_baseline",
                "vector_store_backend": "memory",
            },
            {"name": "full", "pipeline": "agentic_full"},
        ],
        "cases": [{"id": "c1", "query_type": "single_doc", "query": "q"}],
    }

    derived = build_config(source)

    assert derived["primary_run"] == "naive_baseline_llm"
    runs = derived["ablation_runs"]
    assert [run["name"] for run in runs] == ["naive_stub_control", "naive_baseline_llm"]
    assert all(run["pipeline"] == "naive_baseline" for run in runs)
    assert all(run["vector_store_backend"] == "chroma" for run in runs)
    assert all(run["retrieval_backend"] == "dense" for run in runs)
    assert runs[0]["prompt_profile"] == "minimal_grounded_extractive"
    assert runs[1]["prompt_profile"] == "llm_synthesis"
    assert source["ablation_runs"][0]["vector_store_backend"] == "memory"


def test_build_config_falls_back_when_naive_row_is_missing() -> None:
    source = {
        "mode": "rag",
        "primary_run": "full",
        "ablation_runs": [{"name": "full", "pipeline": "agentic_full"}],
        "cases": [{"id": "c1"}],
    }

    derived = build_config(source)

    runs = derived["ablation_runs"]
    assert [run["name"] for run in runs] == ["naive_stub_control", "naive_baseline_llm"]
    assert all(run["pipeline"] == "naive_baseline" for run in runs)
    assert all(run["retrieval_mode"] == "flat" for run in runs)
    assert all(run["query_expansion"] == "identity" for run in runs)
    assert all(run["vector_store_backend"] == "chroma" for run in runs)


def test_build_config_uses_independent_run_copies() -> None:
    source = {
        "cases": [{"id": "c1"}],
        "ablation_runs": [
            {
                "name": "naive_baseline",
                "pipeline": "naive_baseline",
                "metadata": {"owner": "source"},
            }
        ],
    }

    derived = build_config(source)
    stub, llm = derived["ablation_runs"]
    stub["metadata"]["owner"] = "stub"

    assert llm["metadata"]["owner"] == "source"
    assert source["ablation_runs"][0]["metadata"]["owner"] == "source"
