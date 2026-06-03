from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from eval.naive_rag import private_real_eval as pre


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_private_real_eval_template_schema() -> None:
    config = yaml.safe_load(
        (REPO_ROOT / "configs" / "eval" / "private_real_eval.template.yaml").read_text(
            encoding="utf-8"
        )
    )

    pre.validate_template_schema(config)

    assert config["benchmark_type"] == "private_real_eval"
    assert config["not_ci_smoke"] is True
    assert config["is_private_data"] is True
    assert int(config["top_k"]) >= 10
    assert "retrieval" in config["metrics"]
    assert "answer_control" in config["metrics"]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    candidate = REPO_ROOT / path
    for parent in [candidate, *candidate.parents]:
        try:
            rel = parent.relative_to(REPO_ROOT)
        except ValueError:
            break
        if str(rel) == ".":
            break
        if parent.is_symlink():
            return _is_ignored(str(rel))
    return False


def _write_min_private_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    docs_dir = tmp_path / "files"
    docs_dir.mkdir()
    for index in range(50):
        (docs_dir / f"private-{index:02d}.pdf").write_text("placeholder", encoding="utf-8")
    data_list = tmp_path / "data_list.csv"
    data_list.write_text("placeholder\n", encoding="utf-8")
    gold = tmp_path / "gold_evidence.jsonl"
    gold.write_text(
        "\n".join(
            json.dumps(
                {
                    "question_id": f"q{index}",
                    "question": "private question",
                    "answerable": index < 10,
                    "gold_evidence": [{"chunk_id": f"c{index}"}] if index < 10 else [],
                },
                ensure_ascii=False,
            )
            for index in range(13)
        )
        + "\n",
        encoding="utf-8",
    )
    return docs_dir, data_list, gold


def _write_private_eval_config(
    path: Path,
    *,
    docs_dir: Path,
    data_list: Path,
    gold: Path,
    index_dir: Path,
    output_dir: Path,
) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "benchmark_type": "private_real_eval",
                "not_ci_smoke": True,
                "is_private_data": True,
                "documents_dir": str(docs_dir),
                "data_list_path": str(data_list),
                "gold_evidence_path": str(gold),
                "questions_path": str(gold),
                "index_dir": str(index_dir),
                "output_dir": str(output_dir),
                "top_k": 10,
                "metrics": {
                    "retrieval": ["recall_at_5"],
                    "citation": ["citation_accuracy"],
                    "answer_control": ["unanswerable_detection_flag"],
                },
                "latency_scope": "private_runner_wall_clock",
                "answer_metric_mode": "deterministic_contract_v1",
                "redaction_policy": {"summary_only": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_private_local_configs_and_data_paths_are_gitignored() -> None:
    ignored_paths = [
        "configs/eval/private_real_eval.local.yaml",
        "eval/real_config.local.yaml",
        "data/private/files/private.pdf",
        "data/private/data_list.csv",
        "data/private/gold_evidence.jsonl",
        "data/private/index/index.json",
        "data/files/private.pdf",
        "data/files_kordoc/private.json",
        "data/data_list.csv",
        "data/index/private-real/index.json",
        "data/index/real221/index.json",
        "experiments/private_runs/run/metrics.json",
        "reports/real100/eval_summary.json",
        "reports/real221/eval_summary.json",
    ]

    missing = [path for path in ignored_paths if not _is_ignored(path)]

    assert missing == []


def test_private_runner_fails_clearly_when_private_files_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "private_real_eval.local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark_type": "private_real_eval",
                "not_ci_smoke": True,
                "is_private_data": True,
                "documents_dir": "data/private/missing/files",
                "data_list_path": "data/private/missing/data_list.csv",
                "gold_evidence_path": "data/private/missing/gold_evidence.jsonl",
                "index_dir": "data/private/missing/index",
                "output_dir": "experiments/private_runs/missing",
                "top_k": 10,
                "metrics": {
                    "retrieval": ["recall_at_5"],
                    "citation": ["citation_accuracy"],
                    "answer_control": ["unanswerable_detection_flag"],
                },
                "latency_scope": "private_runner_wall_clock",
                "answer_metric_mode": "deterministic_contract_v1",
                "redaction_policy": {"summary_only": True},
                "minimums": {
                    "min_documents": 1,
                    "min_questions": 1,
                    "min_answerable_questions": 1,
                    "min_unanswerable_questions": 0,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            "-m",
            "eval.naive_rag.private_real_eval",
            "--config",
            str(config_path),
            "--validate-only",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Private real-eval validation failed" in result.stderr
    assert "missing_required_input: documents_dir" in result.stderr
    assert "missing_required_input: data_list_path" in result.stderr
    assert "missing_required_input: gold_evidence_path" in result.stderr
    assert str(REPO_ROOT) not in result.stderr
    assert "data/private" not in result.stderr


def test_private_runner_requires_private_inputs_to_be_gitignored() -> None:
    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": "docs",
        "data_list_path": "docs/not_ignored_data_list.csv",
        "gold_evidence_path": "docs/not_ignored_gold_evidence.jsonl",
        "questions_path": "docs/not_ignored_gold_evidence.jsonl",
        "index_dir": "data/private/index",
        "output_dir": "experiments/private_runs/not_ignored_guard",
        "top_k": 10,
        "metrics": {
            "retrieval": ["recall_at_5"],
            "citation": ["citation_accuracy"],
            "answer_control": ["unanswerable_detection_flag"],
        },
        "latency_scope": "private_runner_wall_clock",
        "answer_metric_mode": "deterministic_contract_v1",
        "redaction_policy": {"summary_only": True},
        "minimums": {
            "min_documents": 1,
            "min_questions": 1,
            "min_answerable_questions": 1,
            "min_unanswerable_questions": 0,
        },
    }

    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_private_inputs(config)

    message = str(exc_info.value)
    assert "private_path_not_gitignored: documents_dir" in message
    assert "private_path_not_gitignored: data_list_path" in message
    assert "private_path_not_gitignored: gold_evidence_path" in message
    assert "private_path_not_gitignored: questions_path" in message
    assert str(REPO_ROOT) not in message


def test_private_runner_rejects_legacy_real100_result_surfaces(tmp_path: Path) -> None:
    docs_dir = tmp_path / "files"
    docs_dir.mkdir()
    for index in range(50):
        (docs_dir / f"private-{index:02d}.pdf").write_text("placeholder", encoding="utf-8")
    data_list = tmp_path / "data_list.csv"
    data_list.write_text("placeholder\n", encoding="utf-8")
    gold = tmp_path / "gold_evidence.jsonl"
    gold.write_text(
        "\n".join(
            json.dumps(
                {
                    "question_id": f"q{index}",
                    "question": "private question",
                    "answerable": index < 10,
                    "gold_evidence": [{"chunk_id": f"c{index}"}] if index < 10 else [],
                },
                ensure_ascii=False,
            )
            for index in range(13)
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": str(docs_dir),
        "data_list_path": str(data_list),
        "gold_evidence_path": str(gold),
        "questions_path": str(gold),
        "index_dir": "data/index/real100",
        "output_dir": "reports/real100",
        "top_k": 10,
        "metrics": {
            "retrieval": ["recall_at_5"],
            "citation": ["citation_accuracy"],
            "answer_control": ["unanswerable_detection_flag"],
        },
        "latency_scope": "private_runner_wall_clock",
        "answer_metric_mode": "deterministic_contract_v1",
        "redaction_policy": {"summary_only": True},
        "minimums": {
            "min_documents": 1,
            "min_questions": 1,
            "min_answerable_questions": 1,
            "min_unanswerable_questions": 0,
        },
    }

    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_private_inputs(config)

    message = str(exc_info.value)
    assert "legacy_real100_path: index_dir" in message
    assert "legacy_real100_path: output_dir" in message
    assert "data/index/real100" not in message
    assert "reports/real100" not in message
    for legacy_path in (
        "data/index/Real100",
        "data/index/real100_minilm",
        "reports/REAL100",
        "reports/real100_m3",
        "outputs/real100_kordoc",
    ):
        assert pre.is_legacy_real100_result_path(Path(legacy_path))
    for current_path in (
        "data/index/REAL100_V2",
        "data/index/real100_v2",
        "reports/real100_v2_chroma",
        "outputs/real100_v2_check",
    ):
        assert not pre.is_legacy_real100_result_path(Path(current_path))


def test_redacted_summary_path_rejects_legacy_real100_surfaces(tmp_path: Path) -> None:
    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_redacted_summary_path(Path("reports/real100/summary.json"))

    assert str(exc_info.value) == "legacy_real100_path: redacted_summary_path"
    pre.validate_redacted_summary_path(Path("reports/real100_v2_chroma/summary.json"))
    redacted_aggregate = tmp_path / "reports" / "private_real_eval_candidate.redacted.json"
    assert not pre.git_ignores_path(redacted_aggregate, root=tmp_path)
    pre.validate_redacted_summary_path(redacted_aggregate, root=tmp_path)
    pre.validate_redacted_summary_path(Path("reports/private_real_eval_summary.redacted.json"))
    with pytest.raises(pre.PrivateRealEvalError) as tracked_exc:
        pre.validate_redacted_summary_path(Path("README.md"))
    assert str(tracked_exc.value) == "redacted_summary_path_not_allowed"


def test_private_runner_rejects_legacy_hwp_pdf_artifact_dir(tmp_path: Path) -> None:
    docs_dir, data_list, gold = _write_min_private_inputs(tmp_path)
    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": str(docs_dir),
        "data_list_path": str(data_list),
        "gold_evidence_path": str(gold),
        "questions_path": str(gold),
        "index_dir": str(tmp_path / "index"),
        "output_dir": str(tmp_path / "runs"),
        "top_k": 10,
        "metrics": {
            "retrieval": ["recall_at_5"],
            "citation": ["citation_accuracy"],
            "answer_control": ["unanswerable_detection_flag"],
        },
        "latency_scope": "private_runner_wall_clock",
        "answer_metric_mode": "deterministic_contract_v1",
        "redaction_policy": {"summary_only": True},
        "index_build": {"hwp_pdf_artifact_dir": "data/index/real100/hwp_pdf_artifacts"},
    }

    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_private_inputs(config)

    message = str(exc_info.value)
    assert "legacy_real100_path: hwp_pdf_artifact_dir" in message
    assert "data/index/real100/hwp_pdf_artifacts" not in message


def test_legacy_path_match_uses_unresolved_symlink_spelling(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    current_target = tmp_path / "external" / "real100_v2_chroma"
    current_target.mkdir(parents=True)
    legacy_link = reports_dir / "real100"
    legacy_link.symlink_to(current_target, target_is_directory=True)

    assert legacy_link.resolve() == current_target
    assert pre.is_legacy_real100_result_path(legacy_link, root=tmp_path)


def test_legacy_path_match_uses_resolved_symlink_target(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    legacy_target = reports_dir / "real100"
    legacy_target.mkdir()
    current_link = reports_dir / "current"
    current_link.symlink_to(legacy_target, target_is_directory=True)

    assert current_link.resolve() == legacy_target
    assert pre.is_legacy_real100_result_path(current_link, root=tmp_path)


def test_legacy_path_match_preserves_external_resolved_target(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True)
    external_target = tmp_path / "external" / "reports" / "REAL100"
    external_target.mkdir(parents=True)
    current_link = reports_dir / "current"
    current_link.symlink_to(external_target, target_is_directory=True)

    assert current_link.resolve() == external_target
    assert pre.is_legacy_real100_result_path(current_link, root=repo_root)


def test_private_runner_pins_guarded_paths_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs_dir, data_list, gold = _write_min_private_inputs(tmp_path)
    safe_output = tmp_path / "safe" / "reports" / "real100_v2_chroma"
    safe_index = tmp_path / "safe" / "index" / "real100_v2"
    safe_summary_dir = tmp_path / "safe" / "summaries" / "real100_v2"
    legacy_output = tmp_path / "legacy" / "reports" / "real100"
    legacy_index = tmp_path / "legacy" / "data" / "index" / "real100"
    legacy_summary_dir = tmp_path / "legacy" / "summaries"
    for path in (
        safe_output,
        safe_index,
        safe_summary_dir,
        legacy_output,
        legacy_index,
        legacy_summary_dir,
    ):
        path.mkdir(parents=True)
    output_link = tmp_path / "output-current"
    index_link = tmp_path / "index-current"
    summary_link = tmp_path / "summary-current"
    output_link.symlink_to(safe_output, target_is_directory=True)
    index_link.symlink_to(safe_index, target_is_directory=True)
    summary_link.symlink_to(safe_summary_dir, target_is_directory=True)
    config_path = tmp_path / "private_real_eval.local.yaml"
    _write_private_eval_config(
        config_path,
        docs_dir=docs_dir,
        data_list=data_list,
        gold=gold,
        index_dir=index_link,
        output_dir=output_link,
    )

    def fake_build_or_load(
        _config: dict[str, object], validation: dict[str, object]
    ) -> None:
        assert Path(validation["output_dir"]) == safe_output.resolve()
        assert Path(validation["index_dir"]) == safe_index.resolve()
        output_link.unlink()
        output_link.symlink_to(legacy_output, target_is_directory=True)
        index_link.unlink()
        index_link.symlink_to(legacy_index, target_is_directory=True)
        summary_link.unlink()
        summary_link.symlink_to(legacy_summary_dir, target_is_directory=True)
        return None

    def fake_run_from_config(
        _contract_path: Path,
        *,
        output_root_override: Path,
        run_id_override: str,
    ) -> Path:
        assert output_root_override == safe_output.resolve()
        run_dir = output_root_override / run_id_override
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "dataset": {
                        "num_questions": 13,
                        "answerable_count": 10,
                        "unanswerable_count": 3,
                    },
                    "retrieval_metrics": {"recall_at_5": {"mean": 1.0, "n": 13}},
                    "answer_metrics": {"citation_accuracy": {"mean": 1.0, "n": 10}},
                }
            ),
            encoding="utf-8",
        )
        return run_dir

    monkeypatch.setattr(pre, "build_or_load_private_index", fake_build_or_load)
    monkeypatch.setattr(pre, "run_from_config", fake_run_from_config)

    result = pre.main(
        [
            "--config",
            str(config_path),
            "--run-id",
            "stable-run",
            "--redacted-summary-path",
            str(summary_link / "summary.json"),
        ]
    )

    assert result == 0
    assert (safe_output / "stable-run" / "_inputs" / "contract.naive_baseline.generated.yaml").is_file()
    assert (safe_output / "stable-run" / "metrics.json").is_file()
    assert (safe_summary_dir / "summary.json").is_file()
    assert not (legacy_output / "stable-run").exists()
    assert not (legacy_summary_dir / "summary.json").exists()


def test_private_runner_rechecks_absent_guarded_dir_before_first_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_dir, data_list, gold = _write_min_private_inputs(tmp_path)
    output_dir = tmp_path / "runs"
    index_dir = tmp_path / "index"
    legacy_output = tmp_path / "legacy" / "reports" / "real100"
    legacy_output.mkdir(parents=True)
    config_path = tmp_path / "private_real_eval.local.yaml"
    _write_private_eval_config(
        config_path,
        docs_dir=docs_dir,
        data_list=data_list,
        gold=gold,
        index_dir=index_dir,
        output_dir=output_dir,
    )

    def fake_build_or_load(
        _config: dict[str, object], _validation: dict[str, object]
    ) -> None:
        shutil.rmtree(output_dir)
        output_dir.symlink_to(legacy_output, target_is_directory=True)
        return None

    def fail_run_from_config(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("run_from_config must not run after output_dir retargeting")

    monkeypatch.setattr(pre, "build_or_load_private_index", fake_build_or_load)
    monkeypatch.setattr(pre, "run_from_config", fail_run_from_config)

    result = pre.main(
        [
            "--config",
            str(config_path),
            "--run-id",
            "stable-run",
            "--redacted-summary-path",
            str(tmp_path / "safe-summary" / "summary.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "legacy_real100_path: output_dir" in captured.err
    assert not (legacy_output / "stable-run").exists()


def test_private_runner_rejects_unsafe_run_id_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_dir, data_list, gold = _write_min_private_inputs(tmp_path)
    output_dir = tmp_path / "runs"
    index_dir = tmp_path / "index"
    config_path = tmp_path / "private_real_eval.local.yaml"
    _write_private_eval_config(
        config_path,
        docs_dir=docs_dir,
        data_list=data_list,
        gold=gold,
        index_dir=index_dir,
        output_dir=output_dir,
    )

    def fail_build_or_load(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("build_or_load_private_index must not run for invalid run_id")

    def fail_run_from_config(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("run_from_config must not run for invalid run_id")

    monkeypatch.setattr(pre, "build_or_load_private_index", fail_build_or_load)
    monkeypatch.setattr(pre, "run_from_config", fail_run_from_config)

    result = pre.main(
        [
            "--config",
            str(config_path),
            "--run-id",
            "../real100",
            "--redacted-summary-path",
            str(tmp_path / "safe-summary" / "summary.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "invalid_run_id" in captured.err
    assert not output_dir.exists()
    assert not index_dir.exists()
    assert not (tmp_path / "safe-summary").exists()


def test_validate_only_rejects_legacy_redacted_summary_path_before_run(tmp_path: Path) -> None:
    docs_dir = tmp_path / "files"
    docs_dir.mkdir()
    for index in range(50):
        (docs_dir / f"private-{index:02d}.pdf").write_text("placeholder", encoding="utf-8")
    data_list = tmp_path / "data_list.csv"
    data_list.write_text("placeholder\n", encoding="utf-8")
    gold = tmp_path / "gold_evidence.jsonl"
    gold.write_text(
        "\n".join(
            json.dumps(
                {
                    "question_id": f"q{index}",
                    "question": "private question",
                    "answerable": index < 10,
                    "gold_evidence": [{"chunk_id": f"c{index}"}] if index < 10 else [],
                },
                ensure_ascii=False,
            )
            for index in range(13)
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "private_real_eval.local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark_type": "private_real_eval",
                "not_ci_smoke": True,
                "is_private_data": True,
                "documents_dir": str(docs_dir),
                "data_list_path": str(data_list),
                "gold_evidence_path": str(gold),
                "questions_path": str(gold),
                "index_dir": str(tmp_path / "index"),
                "output_dir": str(tmp_path / "runs"),
                "top_k": 10,
                "metrics": {
                    "retrieval": ["recall_at_5"],
                    "citation": ["citation_accuracy"],
                    "answer_control": ["unanswerable_detection_flag"],
                },
                "latency_scope": "private_runner_wall_clock",
                "answer_metric_mode": "deterministic_contract_v1",
                "redaction_policy": {"summary_only": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            "-m",
            "eval.naive_rag.private_real_eval",
            "--config",
            str(config_path),
            "--validate-only",
            "--redacted-summary-path",
            "reports/real100/summary.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "legacy_real100_path: redacted_summary_path" in result.stderr
    assert "reports/real100/summary.json" not in result.stderr
    assert not (tmp_path / "runs").exists()


def test_private_runner_reports_label_gaps_without_private_ids(tmp_path: Path) -> None:
    docs_dir = tmp_path / "files"
    docs_dir.mkdir()
    (docs_dir / "private.pdf").write_text("placeholder", encoding="utf-8")
    data_list = tmp_path / "data_list.csv"
    data_list.write_text("placeholder\n", encoding="utf-8")
    gold = tmp_path / "gold_evidence.jsonl"
    gold.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "PRIVATE-QID-001",
                        "question": "PRIVATE RAW QUESTION",
                        "answerable": True,
                        "gold_evidence": [],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "question_id": "PRIVATE-QID-002",
                        "question": "PRIVATE RAW UNANSWERABLE",
                        "answerable": False,
                        "gold_evidence": [
                            {"doc_id": "PRIVATE-DOC", "chunk_id": "PRIVATE-CHUNK"}
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "benchmark_type": "private_real_eval",
        "not_ci_smoke": True,
        "is_private_data": True,
        "documents_dir": str(docs_dir),
        "data_list_path": str(data_list),
        "gold_evidence_path": str(gold),
        "questions_path": str(gold),
        "index_dir": str(tmp_path / "index"),
        "output_dir": str(tmp_path / "runs"),
        "top_k": 10,
        "metrics": {
            "retrieval": ["recall_at_5"],
            "citation": ["citation_accuracy"],
            "answer_control": ["unanswerable_detection_flag"],
        },
        "latency_scope": "private_runner_wall_clock",
        "answer_metric_mode": "deterministic_contract_v1",
        "redaction_policy": {"summary_only": True},
        "minimums": {
            "min_documents": 1,
            "min_questions": 1,
            "min_answerable_questions": 1,
            "min_unanswerable_questions": 0,
        },
    }

    with pytest.raises(pre.PrivateRealEvalError) as exc_info:
        pre.validate_private_inputs(config)

    message = str(exc_info.value)
    assert "missing_explicit_gold_chunk_id: answerable_questions count=1" in message
    assert "unanswerable_gold_evidence_not_empty: questions count=1" in message
    assert "PRIVATE-QID" not in message
    assert "PRIVATE-DOC" not in message
    assert "PRIVATE-CHUNK" not in message
    assert "PRIVATE RAW" not in message


def test_answerable_strings_are_parsed_strictly() -> None:
    questions = pre._questions_from_rows(
        [
            {"question_id": "q1", "question": "Answerable?", "answerable": "true"},
            {"question_id": "q2", "question": "Unanswerable?", "answerable": "false"},
        ]
    )

    assert [question["answerable"] for question in questions] == [True, False]

    with pytest.raises(pre.PrivateRealEvalError, match="answerable must be a boolean"):
        pre._questions_from_rows(
            [{"question_id": "q3", "question": "Ambiguous?", "answerable": "no"}]
        )


def test_document_count_follows_private_symlink_layout(tmp_path: Path) -> None:
    source = tmp_path / "source-files"
    source.mkdir()
    (source / "one.pdf").write_text("placeholder", encoding="utf-8")
    linked = tmp_path / "data" / "private" / "files"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(source, target_is_directory=True)

    assert pre._count_documents(linked) == 1


def test_redacted_summary_excludes_private_raw_fields() -> None:
    metrics_payload = {
        "dataset": {
            "num_questions": 2,
            "answerable_count": 1,
            "unanswerable_count": 1,
            "questions_path": "data/private/gold_evidence.jsonl",
        },
        "retrieval_metrics": {"recall_at_5": {"mean": 0.5, "n": 1, "missing": 0}},
        "answer_metrics": {
            "citation_accuracy": {"mean": 0.5, "n": 1, "missing": 0},
            "answer_text": "PRIVATE RAW ANSWER",
        },
        "failure_counts": {
            "retrieval_failure.gold_evidence_not_in_top_k": 1,
            "path": 1,
            "/Users/example/private/file.pdf": 1,
            "unsafe": "data/private/file.pdf",
        },
        "case_results": [
            {
                "question": "PRIVATE RAW QUESTION",
                "answer": "PRIVATE RAW ANSWER",
                "retrieved_chunks": [{"text_preview": "PRIVATE DOC TEXT"}],
            }
        ],
    }
    validation = {
        "document_count": 3,
        "question_count": 2,
        "answerable_count": 1,
        "unanswerable_count": 1,
        "index_dir": REPO_ROOT / "does-not-exist",
    }
    config = {"top_k": 10, "latency_scope": "private_runner_wall_clock"}

    summary = pre.build_redacted_summary(metrics_payload, validation, config, elapsed_ms=123.4)
    rendered = json.dumps(summary, ensure_ascii=False)

    assert "PRIVATE RAW QUESTION" not in rendered
    assert "PRIVATE RAW ANSWER" not in rendered
    assert "PRIVATE DOC TEXT" not in rendered
    assert "questions_path" not in rendered
    assert "answer_text" not in rendered
    assert "retrieved_chunks" not in rendered
    assert "/Users/example" not in rendered
    assert "data/private" not in rendered
    assert '"path"' not in rendered
    assert "retrieval_failure.gold_evidence_not_in_top_k" in rendered
    assert summary["index_provenance"] == {}


def test_redacted_summary_rejects_path_like_values() -> None:
    with pytest.raises(pre.PrivateRealEvalError, match="forbidden private fields"):
        pre.assert_redacted_summary_safe({"safe_key": "/Users/example/private/file.pdf"})


def test_index_embedding_summary_is_aggregate_only(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "index.json").write_text(
        json.dumps(
            {
                "embedding": {
                    "backend": "hashing",
                    "dimension": 384,
                    "model": "/Users/example/private/model",
                },
                "build": {
                    "num_chunks": 26,
                    "generated_at": "2026-05-24T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )

    assert pre._index_embedding_summary(index_dir) == {
        "embedding_backend": "hashing",
        "embedding_dimension": 384,
        "chunk_count": 26,
        "generated_at": "2026-05-24T00:00:00+00:00",
    }


def test_redacted_summary_includes_semantic_provenance_and_comparison(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "index.json").write_text(
        json.dumps(
            {
                "embedding": {
                    "backend": "sentence-transformers",
                    "model": pre.PREFERRED_SEMANTIC_MODEL,
                    "dimension": 384,
                },
                "build": {
                    "num_documents": 100,
                    "num_chunks": 26376,
                    "generated_at": "2026-05-24T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )
    metrics_payload = {
        "dataset": {"num_questions": 217, "answerable_count": 114, "unanswerable_count": 103},
        "retrieval_metrics": {
            "recall_at_5": {"mean": 0.1, "n": 114, "missing": 103},
            "recall_at_10": {"mean": 0.2, "n": 114, "missing": 103},
            "mrr_at_5": {"mean": 0.3, "n": 114, "missing": 103},
            "ndcg_at_5": {"mean": 0.4, "n": 114, "missing": 103},
        },
        "answer_metrics": {
            "citation_accuracy": {"mean": 0.5, "n": 114, "missing": 103},
            "answer_relevancy": {"mean": 0.6, "n": 114, "missing": 103},
            "faithfulness": {"mean": 0.7, "n": 114, "missing": 103},
            "unanswerable_detection_flag": {"mean": 0.8, "n": 103, "missing": 114},
        },
        "failure_counts": {"retrieval_failure.gold_evidence_not_in_top_k": 1},
    }
    validation = {
        "document_count": 100,
        "question_count": 217,
        "answerable_count": 114,
        "unanswerable_count": 103,
        "index_dir": index_dir,
    }
    config = {"top_k": 10, "latency_scope": "private_runner_wall_clock"}
    hashing_summary = {
        "benchmark_type": "private_real_eval",
        "dataset": {"num_questions": 217},
        "index_provenance": {
            "embedding_backend": "hashing",
            "model": "local-hashing-bow",
            "embedding_dimension": 384,
            "chunk_count": 26376,
            "generated_at": "2026-05-23T00:00:00+00:00",
        },
        "metrics": {"retrieval": {"recall_at_5": {"mean": 0.05}}},
        "latency_summary": {"mean_wall_clock_ms_per_question": 621.58},
    }

    summary = pre.build_redacted_summary(
        metrics_payload,
        validation,
        config,
        elapsed_ms=2000.0,
        comparison_summary=hashing_summary,
    )

    assert summary["index_provenance"] == {
        "embedding_backend": "sentence-transformers",
        "model": pre.PREFERRED_SEMANTIC_MODEL,
        "embedding_dimension": 384,
        "chunk_count": 26376,
        "generated_at": "2026-05-24T00:00:00+00:00",
    }
    assert summary["claim_readiness"]["status"] == "claim-ready"
    assert [row["workflow"] for row in summary["comparison_table"]] == [
        "hashing workflow-validation run",
        "semantic dense baseline run",
    ]
    rendered = json.dumps(summary, ensure_ascii=False)
    assert "doc_id" not in rendered
    assert "chunk_id" not in rendered


def test_public_smoke_and_synthetic_configs_remain_unaffected() -> None:
    public_contract = yaml.safe_load(
        (REPO_ROOT / "configs" / "eval" / "rag_quality_v1.yaml").read_text(encoding="utf-8")
    )
    smoke_config = yaml.safe_load((REPO_ROOT / "eval" / "config.yaml").read_text(encoding="utf-8"))
    registry = json.loads((REPO_ROOT / "benchmarks" / "registry.json").read_text(encoding="utf-8"))

    assert public_contract["name"] == "rag_quality_v1"
    assert public_contract["pipeline"]["name"] == "naive_baseline"
    assert public_contract["pipeline"]["retrieval_backend"] == "dense"
    assert any(run.get("name") == "naive_baseline" for run in smoke_config["ablation_runs"])
    assert "private_real_eval" not in json.dumps(registry)
