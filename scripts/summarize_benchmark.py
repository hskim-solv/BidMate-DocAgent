#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATASET_PRIVACY_KEYS = (
    "type",
    "privacy",
    "corpus_size",
    "anonymized",
    "comparison_group",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update the committed benchmark registry and human-readable docs from a run manifest."
    )
    parser.add_argument("--manifest", required=True, help="Path to artifacts/benchmarks/<run_id>/run_manifest.json")
    parser.add_argument("--registry", default="benchmarks/registry.json")
    parser.add_argument("--docs", default="docs/ablation-results.md")
    parser.add_argument("--check", action="store_true", help="Fail if registry/docs are not up-to-date")
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def fmt_rate(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


def fmt_latency(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("p95"), (int, float)):
        return f"{value['p95']:.1f}ms"
    return "N/A"


def fmt_delta(primary: Any, baseline: Any) -> str:
    if not isinstance(primary, (int, float)) or not isinstance(baseline, (int, float)):
        return "N/A"
    delta = primary - baseline
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f}"


def metric_block(summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = summary or {}
    keys = [
        "num_predictions",
        "accuracy",
        "groundedness",
        "citation_precision",
        "citation_page_precision",
        "citation_region_precision",
        "citation_grounding",
        "answer_format_compliance",
        "abstention",
        "retry",
        "latency",
        "retry_cost",
        "retry_reason_counts",
        "citation_grounding_error_counts",
        "by_hardcase_category",
    ]
    return {key: summary.get(key) for key in keys if key in summary}


def dataset_privacy_metadata(dataset: dict[str, Any] | None) -> dict[str, Any]:
    dataset = dataset or {}
    return {key: dataset.get(key) for key in DATASET_PRIVACY_KEYS if key in dataset}


def registry_entry(manifest: dict[str, Any]) -> dict[str, Any]:
    metrics_by_run = manifest.get("metrics", {}).get("runs") or {}
    flags_by_run = manifest.get("ablation_flags") or {}
    baseline_run = str(manifest.get("ablation_suite", {}).get("baseline_run") or "")
    primary_run = str(manifest.get("ablation_suite", {}).get("primary_run") or "")
    baseline = metric_block(metrics_by_run.get(baseline_run))
    primary = metric_block(metrics_by_run.get(primary_run))
    runs = []
    for name in sorted(metrics_by_run):
        runs.append(
            {
                "name": name,
                "flags": flags_by_run.get(name) or {},
                "metrics": metric_block(metrics_by_run.get(name)),
            }
        )
    dataset = manifest.get("suite", {}).get("dataset", {}) or {}
    entry = {
        "run_id": manifest["run_id"],
        "generated_at": manifest.get("generated_at"),
        "git_commit": manifest.get("git_commit"),
        "git_dirty": bool(manifest.get("git_dirty")),
        "suite_id": manifest.get("suite", {}).get("id"),
        "dataset_id": dataset.get("id"),
        "ablation_suite_id": manifest.get("ablation_suite", {}).get("id"),
        "baseline_run": baseline_run,
        "primary_run": primary_run,
        "baseline_metrics": baseline,
        "primary_metrics": primary,
        "delta": {
            "accuracy": delta_value(primary.get("accuracy"), baseline.get("accuracy")),
            "groundedness": delta_value(primary.get("groundedness"), baseline.get("groundedness")),
            "citation_precision": delta_value(
                primary.get("citation_precision"), baseline.get("citation_precision")
            ),
            "citation_page_precision": delta_value(
                primary.get("citation_page_precision"), baseline.get("citation_page_precision")
            ),
            "citation_region_precision": delta_value(
                primary.get("citation_region_precision"), baseline.get("citation_region_precision")
            ),
            "citation_grounding": delta_value(
                primary.get("citation_grounding"), baseline.get("citation_grounding")
            ),
            "answer_format_compliance": delta_value(
                primary.get("answer_format_compliance"),
                baseline.get("answer_format_compliance"),
            ),
            "abstention": delta_value(primary.get("abstention"), baseline.get("abstention")),
            "retry": delta_value(primary.get("retry"), baseline.get("retry")),
            "latency_p95": delta_value(
                (primary.get("latency") or {}).get("p95"),
                (baseline.get("latency") or {}).get("p95"),
            ),
        },
        "artifact_manifest": manifest.get("artifacts", {}).get("run_manifest"),
        "runs": runs,
    }
    privacy_metadata = dataset_privacy_metadata(dataset)
    if privacy_metadata:
        entry["dataset"] = privacy_metadata
    return entry


def delta_value(primary: Any, baseline: Any) -> float | None:
    if isinstance(primary, (int, float)) and isinstance(baseline, (int, float)):
        return primary - baseline
    return None


def updated_registry(current: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    registry = copy.deepcopy(current)
    registry.setdefault("schema_version", 1)
    registry.setdefault(
        "description",
        "Curated aggregate benchmark registry. Raw artifacts stay under artifacts/benchmarks/.",
    )
    entries = [item for item in registry.get("entries", []) if item.get("run_id") != entry["run_id"]]
    entries.append(entry)
    entries.sort(key=lambda item: str(item.get("generated_at") or item.get("run_id") or ""))
    registry["entries"] = entries
    return registry


def render_docs(registry: dict[str, Any]) -> str:
    entries = registry.get("entries") or []
    if not entries:
        return "# Ablation Results\n\nNo benchmark runs have been summarized yet.\n"
    latest = entries[-1]
    baseline_name = latest.get("baseline_run")
    primary_name = latest.get("primary_run")
    baseline = latest.get("baseline_metrics") or {}
    primary = latest.get("primary_metrics") or {}

    lines = [
        "# Ablation Results",
        "",
        "이 문서는 커밋 가능한 집계 지표만 남긴다. 원시 예측, 진단 로그, 지연시간 샘플, 오류 예시는 `artifacts/benchmarks/` 아래에 생성되며 Git에 커밋하지 않는다.",
        "",
        "## Latest Run",
        "",
        f"- Run ID: `{latest.get('run_id')}`",
        f"- Suite: `{latest.get('suite_id')}` / Dataset: `{latest.get('dataset_id')}`",
        f"- Git commit: `{latest.get('git_commit')}`",
        f"- Baseline: `{baseline_name}`",
        f"- Primary: `{primary_name}`",
        f"- Local manifest: `{latest.get('artifact_manifest')}`",
        "",
        "## Baseline To Primary",
        "",
        "| Metric | Baseline | Primary | Delta |",
        "|---|---:|---:|---:|",
        table_row("Accuracy", baseline, primary, "accuracy"),
        table_row("Groundedness", baseline, primary, "groundedness"),
        table_row("Citation Precision", baseline, primary, "citation_precision"),
        table_row("Citation Page Precision", baseline, primary, "citation_page_precision"),
        table_row("Citation Region Precision", baseline, primary, "citation_region_precision"),
        table_row("Citation Grounding", baseline, primary, "citation_grounding"),
        table_row("Format Compliance", baseline, primary, "answer_format_compliance"),
        table_row("Abstention", baseline, primary, "abstention"),
        table_row("Retry Rate", baseline, primary, "retry"),
        "| Latency p95 | {baseline} | {primary} | {delta} |".format(
            baseline=fmt_latency(baseline.get("latency")),
            primary=fmt_latency(primary.get("latency")),
            delta=fmt_delta(
                (primary.get("latency") or {}).get("p95"),
                (baseline.get("latency") or {}).get("p95"),
            ),
        ),
        "",
        "## Ablation Table",
        "",
        "| Run | Pipeline | Top-k | Metadata-first | Rerank | Verifier/Retry | Retrieval | Prompt | Accuracy | Groundedness | Citation | Citation Grounding | Format | Abstention | Retry | Latency p95 |",
        "|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in latest.get("runs") or []:
        flags = run.get("flags") or {}
        metrics = run.get("metrics") or {}
        lines.append(
            "| {name} | {pipeline} | {top_k} | {metadata_first} | {rerank} | {verifier_retry} | {retrieval_mode} | {prompt} | {accuracy} | {groundedness} | {citation} | {citation_grounding} | {format} | {abstention} | {retry} | {latency} |".format(
                name=run.get("name"),
                pipeline=flags.get("pipeline", ""),
                top_k=fmt_top_k(flags.get("top_k")),
                metadata_first=flag(flags.get("metadata_first")),
                rerank=flag(flags.get("rerank")),
                verifier_retry=flag(flags.get("verifier_retry")),
                retrieval_mode=flags.get("retrieval_mode", "flat"),
                prompt=flags.get("prompt_profile", ""),
                accuracy=fmt_rate(metrics.get("accuracy")),
                groundedness=fmt_rate(metrics.get("groundedness")),
                citation=fmt_rate(metrics.get("citation_precision")),
                citation_grounding=fmt_rate(metrics.get("citation_grounding")),
                format=fmt_rate(metrics.get("answer_format_compliance")),
                abstention=fmt_rate(metrics.get("abstention")),
                retry=fmt_rate(metrics.get("retry")),
                latency=fmt_latency(metrics.get("latency")),
            )
        )

    hardcase_metrics = (primary.get("by_hardcase_category") or {})
    if hardcase_metrics:
        lines.extend(
            [
                "",
                "## Hard-case Slices",
                "",
                "| Category | Cases | Accuracy | Groundedness | Citation | Citation Grounding | Format | Abstention | Retry |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for category in sorted(hardcase_metrics):
            metrics = hardcase_metrics[category] or {}
            lines.append(
                "| {category} | {cases} | {accuracy} | {groundedness} | {citation} | {citation_grounding} | {format} | {abstention} | {retry} |".format(
                    category=category,
                    cases=metrics.get("num_predictions", "N/A"),
                    accuracy=fmt_rate(metrics.get("accuracy")),
                    groundedness=fmt_rate(metrics.get("groundedness")),
                    citation=fmt_rate(metrics.get("citation_precision")),
                    citation_grounding=fmt_rate(metrics.get("citation_grounding")),
                    format=fmt_rate(metrics.get("answer_format_compliance")),
                    abstention=fmt_rate(metrics.get("abstention")),
                    retry=fmt_rate(metrics.get("retry")),
                )
            )

    comparison_rows = public_private_comparison_rows(entries)
    if comparison_rows:
        lines.extend(
            [
                "",
                "## Public vs Private Aggregate",
                "",
                "이 표는 공개 synthetic 결과와 익명 private aggregate를 함께 볼 때만 생성된다. private row는 원문, 파일명, 기관명, 질의 본문, 개별 답변, 실행 추적 없이 집계 지표만 사용한다.",
                "",
                "| Metric | Public primary | Private primary | Delta |",
                "|---|---:|---:|---:|",
            ]
        )
        lines.extend(comparison_rows)

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- `{baseline_name}`는 fixed chunk + dense top-k만 쓰는 naive control baseline이다.",
            f"- `{primary_name}`는 비교 대상 primary run이다.",
            "- latency와 retry는 품질 지표와 함께 본다. retry가 늘어도 groundedness, citation, abstention 개선이 동반되는지 확인한다.",
            "- 현재 수치는 공개 synthetic RFP 평가셋 기준의 2차 가공 집계이며, 원본 RFP 문서나 raw example output은 포함하지 않는다.",
            "",
            "## Next Actions",
            "",
            "- 평가셋을 늘릴 때는 suite YAML을 추가하고 registry에는 집계 지표만 편입한다.",
            "- private RFP 기반 실험은 local artifact로만 보관하고 문서에는 익명화된 집계 결과만 남긴다.",
            "- citation 검증과 latency/retry 비용 분석은 별도 ablation axis로 분리해 누적한다.",
        ]
    )
    return "\n".join(lines) + "\n"


def public_private_comparison_rows(entries: list[dict[str, Any]]) -> list[str]:
    private_entry = latest_entry(entries, is_private=True)
    public_entry = matching_public_entry(entries, private_entry)
    if not public_entry or not private_entry:
        return []

    public_metrics = public_entry.get("primary_metrics") or {}
    private_metrics = private_entry.get("primary_metrics") or {}
    rows = [
        comparison_row("Cases", public_metrics, private_metrics, "num_predictions", formatter=fmt_count),
        comparison_row("Accuracy", public_metrics, private_metrics, "accuracy"),
        comparison_row("Groundedness", public_metrics, private_metrics, "groundedness"),
        comparison_row("Citation Precision", public_metrics, private_metrics, "citation_precision"),
        comparison_row("Citation Grounding", public_metrics, private_metrics, "citation_grounding"),
        comparison_row("Format Compliance", public_metrics, private_metrics, "answer_format_compliance"),
        comparison_row("Abstention", public_metrics, private_metrics, "abstention"),
        comparison_row("Retry Rate", public_metrics, private_metrics, "retry"),
        "| Latency p95 | {public} | {private} | {delta} |".format(
            public=fmt_latency(public_metrics.get("latency")),
            private=fmt_latency(private_metrics.get("latency")),
            delta=fmt_delta(
                (private_metrics.get("latency") or {}).get("p95"),
                (public_metrics.get("latency") or {}).get("p95"),
            ),
        ),
    ]
    return rows


def matching_public_entry(entries: list[dict[str, Any]], private_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    public_entries = [entry for entry in entries if not entry_is_private(entry)]
    if not public_entries:
        return None
    comparison_group = str((private_entry.get("dataset") or {}).get("comparison_group") or "") if private_entry else ""
    if comparison_group:
        matched = [
            entry
            for entry in public_entries
            if entry.get("suite_id") == comparison_group or entry.get("dataset_id") == comparison_group
        ]
        if matched:
            return sorted(matched, key=lambda item: str(item.get("generated_at") or item.get("run_id") or ""))[-1]
    return sorted(public_entries, key=lambda item: str(item.get("generated_at") or item.get("run_id") or ""))[-1]


def latest_entry(entries: list[dict[str, Any]], *, is_private: bool) -> dict[str, Any] | None:
    candidates = [entry for entry in entries if entry_is_private(entry) is is_private]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("generated_at") or item.get("run_id") or ""))[-1]


def entry_is_private(entry: dict[str, Any]) -> bool:
    dataset = entry.get("dataset") or {}
    dataset_type = str(dataset.get("type") or "")
    privacy = str(dataset.get("privacy") or "")
    return bool(dataset.get("anonymized")) or "private" in dataset_type or "private" in privacy


def comparison_row(
    label: str,
    public_metrics: dict[str, Any],
    private_metrics: dict[str, Any],
    key: str,
    *,
    formatter: Any = fmt_rate,
) -> str:
    return "| {label} | {public} | {private} | {delta} |".format(
        label=label,
        public=formatter(public_metrics.get(key)),
        private=formatter(private_metrics.get(key)),
        delta=fmt_delta(private_metrics.get(key), public_metrics.get(key)),
    )


def fmt_count(value: Any) -> str:
    return str(value) if isinstance(value, int) else "N/A"


def table_row(label: str, baseline: dict[str, Any], primary: dict[str, Any], key: str) -> str:
    return "| {label} | {baseline} | {primary} | {delta} |".format(
        label=label,
        baseline=fmt_rate(baseline.get(key)),
        primary=fmt_rate(primary.get(key)),
        delta=fmt_delta(primary.get(key), baseline.get(key)),
    )


def fmt_top_k(value: Any) -> str:
    return str(value) if isinstance(value, int) else "auto"


def flag(value: Any) -> str:
    return "on" if bool(value) else "off"


def main() -> int:
    args = parse_args()
    manifest = load_json(repo_path(args.manifest))
    registry_path = repo_path(args.registry)
    docs_path = repo_path(args.docs)

    current_registry = (
        load_json(registry_path)
        if registry_path.exists()
        else {"schema_version": 1, "description": "", "entries": []}
    )
    next_registry = updated_registry(current_registry, registry_entry(manifest))
    next_registry_text = stable_json(next_registry)
    next_docs_text = render_docs(next_registry)

    if args.check:
        registry_ok = registry_path.exists() and registry_path.read_text(encoding="utf-8") == next_registry_text
        docs_ok = docs_path.exists() and docs_path.read_text(encoding="utf-8") == next_docs_text
        if not registry_ok or not docs_ok:
            print("[FAIL] Benchmark registry/docs are out of date. Run scripts/summarize_benchmark.py")
            return 1
        print("[OK] Benchmark registry/docs are up-to-date")
        return 0

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(next_registry_text, encoding="utf-8")
    docs_path.write_text(next_docs_text, encoding="utf-8")
    print(f"[OK] Updated benchmark registry: {display_path(registry_path)}")
    print(f"[OK] Updated ablation docs: {display_path(docs_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
