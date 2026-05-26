"""Private real-data runner for the Naive RAG baseline.

This module adds only a local/private evaluation workflow. It does not change
retrieval, reranking, chunking, prompts, verifier behavior, or answer policy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.naive_rag.run_eval import run_from_config  # noqa: E402


REQUIRED_CONFIG_KEYS = (
    "benchmark_type",
    "not_ci_smoke",
    "is_private_data",
    "documents_dir",
    "data_list_path",
    "gold_evidence_path",
    "index_dir",
    "output_dir",
    "top_k",
    "metrics",
    "latency_scope",
    "answer_metric_mode",
    "redaction_policy",
)
DEFAULT_MINIMUMS = {
    "min_documents": 50,
    "min_questions": 13,
    "min_answerable_questions": 10,
    "min_unanswerable_questions": 3,
}
FORBIDDEN_REDACTED_KEYS = {
    "question",
    "questions_path",
    "answer",
    "answer_text",
    "claims",
    "citations",
    "gold_evidence",
    "retrieved_chunks",
    "text",
    "text_preview",
    "doc_id",
    "chunk_id",
    "file",
    "file_name",
    "filename",
    "path",
    "config_path",
    "index_dir",
    "output_dir",
}
SAFE_RETRIEVAL_METRIC_KEYS = {"recall_at_5", "recall_at_10", "mrr_at_5", "ndcg_at_5"}
SAFE_ANSWER_METRIC_KEYS = {
    "faithfulness",
    "answer_relevancy",
    "citation_accuracy",
    "hallucination_flag",
    "unanswerable_detection_flag",
}
SAFE_METRIC_VALUE_KEYS = {"mean", "n", "missing"}
PREFERRED_SEMANTIC_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
ENV_DEFAULT_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
SAFE_FAILURE_COUNT_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
SAFE_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?$")
SAFE_COMPARISON_ROW_KEYS = {
    "workflow",
    "embedding_backend",
    "model",
    "num_questions",
    "recall_at_5",
    "recall_at_10",
    "mrr_at_5",
    "ndcg_at_5",
    "citation_accuracy",
    "answer_relevancy",
    "faithfulness",
    "unanswerable_detection_flag",
    "mean_wall_clock_ms_per_question",
    "total_wall_clock_ms",
}
ABSOLUTE_PATH_VALUE_RE = re.compile(r"(^|[\s:])(?:/Users/|/private/|/home/|[A-Za-z]:[\\/])")
PRIVATE_PATH_MARKERS = (
    "data/private/",
    "data/files/",
    "data/files_kordoc/",
    "data/index/real",
    "experiments/private_runs/",
    "reports/real",
)


class PrivateRealEvalError(ValueError):
    """Raised when local-only private eval validation fails."""


def _expand_env_defaults(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    env = environ if environ is not None else os.environ
    if isinstance(value, dict):
        return {key: _expand_env_defaults(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_defaults(item, env) for item in value]
    if not isinstance(value, str):
        return value

    def repl(match: re.Match[str]) -> str:
        env_key = match.group(1)
        default = match.group(2) or ""
        return env.get(env_key) or default

    return ENV_DEFAULT_RE.sub(repl, value)


def repo_path(value: str | Path, root: Path = ROOT_DIR) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def rel_or_abs(path: Path, root: Path = ROOT_DIR) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def load_private_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PrivateRealEvalError(f"Config must be a mapping: {path}")
    return _expand_env_defaults(payload)


def validate_template_schema(config: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    errors: list[str] = []
    if missing:
        errors.append("missing required config keys: " + ", ".join(missing))
    if config.get("benchmark_type") != "private_real_eval":
        errors.append("benchmark_type must be private_real_eval")
    if config.get("not_ci_smoke") is not True:
        errors.append("not_ci_smoke must be true")
    if config.get("is_private_data") is not True:
        errors.append("is_private_data must be true")
    try:
        top_k = int(config.get("top_k"))
    except (TypeError, ValueError):
        top_k = 0
    if top_k < 10:
        errors.append("top_k must be >= 10 for the Naive RAG contract")
    metrics = config.get("metrics")
    if not isinstance(metrics, Mapping):
        errors.append("metrics must be a mapping")
    else:
        for group in ("retrieval", "citation", "answer_control"):
            if not isinstance(metrics.get(group), list) or not metrics.get(group):
                errors.append(f"metrics.{group} must be a non-empty list")
    redaction = config.get("redaction_policy")
    if not isinstance(redaction, Mapping):
        errors.append("redaction_policy must be a mapping")
    if errors:
        raise PrivateRealEvalError("Private real-eval config is invalid:\n- " + "\n- ".join(errors))


def _minimum_error(label: str, *, count: int, required: int) -> str:
    return f"minimum_not_met: {label} count={count} required={required}"


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PrivateRealEvalError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
        if not isinstance(payload, dict):
            raise PrivateRealEvalError(f"JSONL row must be an object at {path}:{lineno}")
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _count_documents(documents_dir: Path) -> int:
    if not documents_dir.is_dir():
        return 0
    search_dir = documents_dir.resolve() if documents_dir.is_symlink() else documents_dir
    count = 0
    for path in search_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative_parts = path.relative_to(search_dir).parts
        except ValueError:
            relative_parts = (path.name,)
        if any(part.startswith(".") for part in relative_parts):
            continue
        count += 1
    return count


def _index_counts(index_dir: Path) -> tuple[int | None, int | None]:
    index_json = index_dir / "index.json"
    if not index_json.is_file():
        return None, None
    try:
        payload = json.loads(index_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    build = payload.get("build") if isinstance(payload, dict) else {}
    if not isinstance(build, dict):
        build = {}
    docs = build.get("num_documents")
    chunks = build.get("num_chunks")
    if docs is None and isinstance(payload, dict):
        docs = len(payload.get("documents") or [])
    if chunks is None and isinstance(payload, dict):
        chunks = len(payload.get("chunks") or [])
    try:
        doc_count = int(docs) if docs is not None else None
    except (TypeError, ValueError):
        doc_count = None
    try:
        chunk_count = int(chunks) if chunks is not None else None
    except (TypeError, ValueError):
        chunk_count = None
    return doc_count, chunk_count


def _index_embedding_summary(index_dir: Path) -> dict[str, Any]:
    index_json = index_dir / "index.json"
    if not index_json.is_file():
        return {}
    try:
        payload = json.loads(index_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    embedding = payload.get("embedding") if isinstance(payload, dict) else {}
    if not isinstance(embedding, Mapping):
        return {}
    build = payload.get("build") if isinstance(payload.get("build"), Mapping) else {}
    summary: dict[str, Any] = {}
    backend = str(embedding.get("backend") or "").strip()
    if backend and not ABSOLUTE_PATH_VALUE_RE.search(backend):
        summary["embedding_backend"] = backend
    model = _safe_model_id(embedding.get("model"))
    if model:
        summary["model"] = model
    try:
        dimension = int(embedding.get("dimension"))
    except (TypeError, ValueError):
        dimension = 0
    if dimension > 0:
        summary["embedding_dimension"] = dimension
    try:
        chunk_count = int(build.get("num_chunks"))
    except (TypeError, ValueError):
        chunks = payload.get("chunks") if isinstance(payload.get("chunks"), list) else []
        chunk_count = len(chunks) if chunks else 0
    if chunk_count > 0:
        summary["chunk_count"] = chunk_count
    generated_at = _safe_generated_at(payload, build, index_json)
    if generated_at:
        summary["generated_at"] = generated_at
    return summary


def _safe_model_id(value: Any) -> str | None:
    model = str(value or "").strip()
    if not model:
        return None
    if (
        ABSOLUTE_PATH_VALUE_RE.search(model)
        or any(marker in model for marker in PRIVATE_PATH_MARKERS)
        or "\\" in model
        or "://" in model
        or model.startswith((".", "~"))
    ):
        return None
    if not SAFE_MODEL_ID_RE.fullmatch(model):
        return None
    return model


def _safe_generated_at(
    payload: Mapping[str, Any],
    build: Mapping[str, Any],
    index_json: Path,
) -> str | None:
    for value in (payload.get("generated_at"), build.get("generated_at")):
        generated_at = str(value or "").strip()
        if generated_at and not ABSOLUTE_PATH_VALUE_RE.search(generated_at):
            return generated_at
    try:
        return dt.datetime.fromtimestamp(index_json.stat().st_mtime, dt.timezone.utc).isoformat()
    except OSError:
        return None


def _is_inside_repo(path: Path, root: Path = ROOT_DIR) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def git_ignores_path(path: Path, root: Path = ROOT_DIR) -> bool:
    """Return true when git ignores the path or the path is outside the repo."""
    if not _is_inside_repo(path, root):
        return True
    candidates = [path, path / ".private_real_eval_probe"]
    for candidate in candidates:
        rel = rel_or_abs(candidate, root)
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", rel],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
    return False


def _gold_items(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = row.get("gold_evidence")
    if evidence is None:
        direct = {
            key: row.get(key)
            for key in ("doc_id", "chunk_id", "page_span", "support_claim", "required_terms")
            if row.get(key) is not None
        }
        evidence = [direct] if direct else []
    if not isinstance(evidence, list):
        raise PrivateRealEvalError(
            f"gold_evidence must be a list for question_id={row.get('question_id')}"
        )
    cleaned: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise PrivateRealEvalError(
                f"gold_evidence item must be an object for question_id={row.get('question_id')}"
            )
        cleaned.append(dict(item))
    return cleaned


def _parse_answerable(row: Mapping[str, Any]) -> bool:
    value = row.get("answerable", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise PrivateRealEvalError(
        "answerable must be a boolean or explicit 'true'/'false' string "
        f"for question_id={row.get('question_id')}"
    )


def _questions_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            raise PrivateRealEvalError("Every question/gold row must include question_id")
        if qid in by_id:
            continue
        question = str(row.get("question") or "").strip()
        if not question:
            raise PrivateRealEvalError(f"Question row missing question text: {qid}")
        by_id[qid] = {
            "question_id": qid,
            "question": question,
            "answerable": _parse_answerable(row),
            "query_type": row.get("query_type"),
            "expected_answer": row.get("expected_answer"),
            "expected_terms": row.get("expected_terms") or [],
        }
    return list(by_id.values())


def _gold_by_question(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_question: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            raise PrivateRealEvalError("Every gold evidence row must include question_id")
        by_question.setdefault(qid, []).extend(_gold_items(row))
    return by_question


def _minimums(config: Mapping[str, Any]) -> dict[str, int]:
    raw = config.get("minimums") if isinstance(config.get("minimums"), Mapping) else {}
    result = dict(DEFAULT_MINIMUMS)
    for key in result:
        if key in raw:
            result[key] = max(int(raw[key]), DEFAULT_MINIMUMS[key])
    return result


def validate_private_inputs(
    config: Mapping[str, Any],
    *,
    root: Path = ROOT_DIR,
) -> dict[str, Any]:
    validate_template_schema(config)
    documents_dir = repo_path(str(config["documents_dir"]), root)
    data_list_path = repo_path(str(config["data_list_path"]), root)
    gold_evidence_path = repo_path(str(config["gold_evidence_path"]), root)
    questions_path = repo_path(str(config.get("questions_path") or gold_evidence_path), root)
    index_dir = repo_path(str(config["index_dir"]), root)
    output_dir = repo_path(str(config["output_dir"]), root)
    index_build = (
        config.get("index_build") if isinstance(config.get("index_build"), Mapping) else {}
    )
    build_mode = str(index_build.get("mode") or "build_if_missing")
    can_build_index = build_mode in {"build_if_missing", "rebuild"}

    errors: list[str] = []
    if not documents_dir.is_dir():
        errors.append("missing_required_input: documents_dir")
    if not data_list_path.is_file():
        errors.append("missing_required_input: data_list_path")
    if not gold_evidence_path.is_file():
        errors.append("missing_required_input: gold_evidence_path")
    if config.get("questions_path") and not questions_path.is_file():
        errors.append("missing_required_input: questions_path")
    private_input_paths = {
        "documents_dir": documents_dir,
        "data_list_path": data_list_path,
        "gold_evidence_path": gold_evidence_path,
        "questions_path": questions_path,
    }
    for name, private_path in private_input_paths.items():
        if not git_ignores_path(private_path, root):
            errors.append(f"private_path_not_gitignored: {name}")
    if not git_ignores_path(output_dir, root):
        errors.append("private_path_not_gitignored: output_dir")
    if not git_ignores_path(index_dir, root):
        errors.append("private_path_not_gitignored: index_dir")
    if not (index_dir / "index.json").is_file() and not can_build_index:
        errors.append(f"missing_private_index: index_dir mode={build_mode}")

    document_count = _count_documents(documents_dir)
    questions: list[dict[str, Any]] = []
    gold_by_qid: dict[str, list[dict[str, Any]]] = {}
    if documents_dir.is_dir():
        min_docs = _minimums(config)["min_documents"]
        if document_count < min_docs:
            errors.append(_minimum_error("documents", count=document_count, required=min_docs))
    if gold_evidence_path.is_file() and (
        questions_path.is_file() or not config.get("questions_path")
    ):
        try:
            gold_rows = _jsonl_rows(gold_evidence_path)
        except PrivateRealEvalError:
            gold_rows = []
            errors.append("invalid_jsonl: gold_evidence_path")
        try:
            question_rows = (
                _jsonl_rows(questions_path) if config.get("questions_path") else gold_rows
            )
        except PrivateRealEvalError:
            question_rows = []
            errors.append("invalid_jsonl: questions_path")
        try:
            questions = _questions_from_rows(question_rows)
        except PrivateRealEvalError:
            questions = []
            errors.append("invalid_question_rows: questions_path")
        try:
            gold_by_qid = _gold_by_question(gold_rows)
        except PrivateRealEvalError:
            gold_by_qid = {}
            errors.append("invalid_gold_evidence_rows: gold_evidence_path")
        if questions:
            mins = _minimums(config)
            answerable = [q for q in questions if q.get("answerable", True)]
            unanswerable = [q for q in questions if not q.get("answerable", True)]
            if len(questions) < mins["min_questions"]:
                errors.append(
                    _minimum_error("questions", count=len(questions), required=mins["min_questions"])
                )
            if len(answerable) < mins["min_answerable_questions"]:
                errors.append(
                    _minimum_error(
                        "answerable_questions",
                        count=len(answerable),
                        required=mins["min_answerable_questions"],
                    )
                )
            if len(unanswerable) < mins["min_unanswerable_questions"]:
                errors.append(
                    _minimum_error(
                        "unanswerable_questions",
                        count=len(unanswerable),
                        required=mins["min_unanswerable_questions"],
                    )
                )
            missing_gold = [
                q
                for q in answerable
                if not any(
                    str(item.get("chunk_id") or "").strip()
                    for item in gold_by_qid.get(str(q["question_id"]), [])
                )
            ]
            if missing_gold:
                errors.append(
                    "missing_explicit_gold_chunk_id: "
                    f"answerable_questions count={len(missing_gold)}"
                )
            unanswerable_with_gold = [
                q for q in unanswerable if gold_by_qid.get(str(q["question_id"]))
            ]
            if unanswerable_with_gold:
                errors.append(
                    "unanswerable_gold_evidence_not_empty: "
                    f"questions count={len(unanswerable_with_gold)}"
                )

    index_docs, index_chunks = _index_counts(index_dir)
    if errors:
        raise PrivateRealEvalError("Private real-eval validation failed:\n- " + "\n- ".join(errors))
    return {
        "documents_dir": documents_dir,
        "data_list_path": data_list_path,
        "questions_path": questions_path,
        "gold_evidence_path": gold_evidence_path,
        "index_dir": index_dir,
        "output_dir": output_dir,
        "document_count": document_count,
        "question_count": len(questions),
        "answerable_count": sum(1 for q in questions if q.get("answerable", True)),
        "unanswerable_count": sum(1 for q in questions if not q.get("answerable", True)),
        "index_exists": (index_dir / "index.json").is_file(),
        "index_document_count": index_docs,
        "index_chunk_count": index_chunks,
        "build_mode": build_mode,
    }


def build_index_command(
    config: Mapping[str, Any], validation: Mapping[str, Any]
) -> list[str] | None:
    index_dir = Path(validation["index_dir"])
    index_build = (
        config.get("index_build") if isinstance(config.get("index_build"), Mapping) else {}
    )
    mode = str(index_build.get("mode") or "build_if_missing")
    if (index_dir / "index.json").is_file() and mode != "rebuild":
        return None
    if mode == "load_only":
        raise PrivateRealEvalError(f"index_build.mode=load_only but index is missing: {index_dir}")

    command = [
        sys.executable,
        "scripts/build_index.py",
        "--metadata_csv",
        rel_or_abs(Path(validation["data_list_path"])),
        "--files_dir",
        rel_or_abs(Path(validation["documents_dir"])),
        "--output_dir",
        rel_or_abs(index_dir),
        "--embedding_backend",
        str(index_build.get("embedding_backend") or "auto"),
        "--ingestion_mode",
        str(index_build.get("ingestion_mode") or "csv-text"),
        "--chunking_strategy",
        str(index_build.get("chunking_strategy") or "fixed"),
    ]
    for key, flag in (
        ("model", "--model"),
        ("hwp_loader", "--hwp_loader"),
        ("pdf_loader", "--pdf_loader"),
        ("hwp_pdf_artifact_dir", "--hwp_pdf_artifact_dir"),
    ):
        value = str(index_build.get(key) or "").strip()
        if value:
            command.extend([flag, value])
    return command


def build_or_load_private_index(
    config: Mapping[str, Any], validation: Mapping[str, Any]
) -> list[str] | None:
    command = build_index_command(config, validation)
    if command is None:
        print("[OK] Loading existing private index")
        return None
    print("[INFO] Building private index for Naive RAG eval")
    result = subprocess.run(command, cwd=ROOT_DIR, check=False, text=True)
    if result.returncode != 0:
        raise PrivateRealEvalError("private index build failed: " + " ".join(command))
    return command


def _private_questions_path(
    config: Mapping[str, Any], validation: Mapping[str, Any], run_dir: Path
) -> Path:
    if config.get("questions_path"):
        return Path(validation["questions_path"])
    rows = _jsonl_rows(Path(validation["gold_evidence_path"]))
    questions = _questions_from_rows(rows)
    generated = run_dir / "_inputs" / "questions.generated.jsonl"
    _write_jsonl(generated, questions)
    return generated


def write_contract_config(
    config: Mapping[str, Any],
    validation: Mapping[str, Any],
    *,
    run_id: str,
) -> Path:
    output_dir = Path(validation["output_dir"])
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    questions_path = _private_questions_path(config, validation, run_dir)
    pipeline = config.get("pipeline") if isinstance(config.get("pipeline"), Mapping) else {}
    top_k = int(config["top_k"])
    contract = {
        "schema_version": 1,
        "name": "private_real_eval_naive_baseline",
        "description": "Generated local-only config for private real-data Naive RAG eval.",
        "index_dir": str(Path(validation["index_dir"])),
        "questions_path": str(questions_path),
        "gold_evidence_path": str(Path(validation["gold_evidence_path"])),
        "output_root": str(output_dir),
        "pipeline": {
            "name": "naive_baseline",
            "top_k": top_k,
            "retrieval_mode": str(pipeline.get("retrieval_mode", "flat")),
            "retrieval_backend": "dense",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "query_expansion": "identity",
            "prompt_profile": str(pipeline.get("prompt_profile") or "minimal_grounded_extractive"),
            "bm25_tokenizer": str(pipeline.get("bm25_tokenizer") or "regex"),
            "bm25_backend": str(pipeline.get("bm25_backend") or "okapi"),
        },
        "metrics": {
            "retrieval": list((config.get("metrics") or {}).get("retrieval") or []),
            "answer": [
                *list((config.get("metrics") or {}).get("citation") or []),
                *list((config.get("metrics") or {}).get("answer_control") or []),
            ],
        },
    }
    path = run_dir / "_inputs" / "contract.naive_baseline.generated.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(contract, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def default_run_id() -> str:
    return "private_real_eval_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_metric_block(block: Any, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(block, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key, value in block.items():
        key_text = str(key)
        if key_text not in allowed_keys:
            continue
        if isinstance(value, Mapping):
            safe[key_text] = {
                str(metric_key): metric_value
                for metric_key, metric_value in value.items()
                if str(metric_key) in SAFE_METRIC_VALUE_KEYS
                and isinstance(metric_value, (int, float, type(None)))
            }
        elif isinstance(value, (int, float, type(None))):
            safe[key_text] = value
    return safe


def _safe_count_block(block: Any) -> dict[str, int | float]:
    if not isinstance(block, Mapping):
        return {}
    safe: dict[str, int | float] = {}
    for key, value in block.items():
        key_text = str(key)
        if not SAFE_FAILURE_COUNT_KEY_RE.fullmatch(key_text):
            continue
        if key_text in FORBIDDEN_REDACTED_KEYS:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            safe[key_text] = value
    return safe


def _metric_mean(summary: Mapping[str, Any], metric: str) -> int | float | None:
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), Mapping) else {}
    for group_name in ("retrieval", "citation_and_answer_control"):
        group = metrics.get(group_name) if isinstance(metrics.get(group_name), Mapping) else {}
        block = group.get(metric) if isinstance(group.get(metric), Mapping) else {}
        mean = block.get("mean")
        if isinstance(mean, bool):
            return None
        if isinstance(mean, (int, float)):
            return mean
    return None


def _workflow_label(summary: Mapping[str, Any]) -> str:
    provenance = (
        summary.get("index_provenance")
        if isinstance(summary.get("index_provenance"), Mapping)
        else {}
    )
    backend = str(provenance.get("embedding_backend") or "")
    model = str(provenance.get("model") or "")
    if backend == "hashing":
        return "hashing workflow-validation run"
    if backend == "sentence-transformers" and model == PREFERRED_SEMANTIC_MODEL:
        return "semantic dense baseline run"
    if backend == "sentence-transformers":
        return "semantic dense baseline run"
    return "private dense baseline run"


def _comparison_row(summary: Mapping[str, Any]) -> dict[str, Any]:
    provenance = (
        summary.get("index_provenance")
        if isinstance(summary.get("index_provenance"), Mapping)
        else {}
    )
    dataset = summary.get("dataset") if isinstance(summary.get("dataset"), Mapping) else {}
    latency = (
        summary.get("latency_summary")
        if isinstance(summary.get("latency_summary"), Mapping)
        else {}
    )
    row: dict[str, Any] = {
        "workflow": _workflow_label(summary),
        "embedding_backend": provenance.get("embedding_backend"),
        "model": provenance.get("model"),
        "num_questions": dataset.get("num_questions"),
    }
    for metric in (
        "recall_at_5",
        "recall_at_10",
        "mrr_at_5",
        "ndcg_at_5",
        "citation_accuracy",
        "answer_relevancy",
        "faithfulness",
        "unanswerable_detection_flag",
    ):
        row[metric] = _metric_mean(summary, metric)
    for key in ("mean_wall_clock_ms_per_question", "total_wall_clock_ms"):
        value = latency.get(key)
        row[key] = value if isinstance(value, (int, float, type(None))) else None
    return row


def _safe_existing_comparison_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    safe: dict[str, Any] = {}
    for key, value in row.items():
        key_text = str(key)
        if key_text not in SAFE_COMPARISON_ROW_KEYS:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            if ABSOLUTE_PATH_VALUE_RE.search(value) or any(
                marker in value for marker in PRIVATE_PATH_MARKERS
            ):
                continue
            safe[key_text] = value
        elif isinstance(value, (int, float, type(None))):
            safe[key_text] = value
    if safe.get("workflow"):
        return safe
    return None


def _build_comparison_table(
    current_summary: Mapping[str, Any],
    previous_summary: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if previous_summary:
        previous_rows = previous_summary.get("comparison_table")
        if isinstance(previous_rows, list):
            for row in previous_rows:
                safe = _safe_existing_comparison_row(row)
                if safe and safe.get("workflow") == "hashing workflow-validation run":
                    rows.append(safe)
        previous_row = _comparison_row(previous_summary)
        if previous_row.get("workflow") == "hashing workflow-validation run":
            rows.append(previous_row)

    current_row = _comparison_row(current_summary)
    rows.append(current_row)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for row in rows:
        key = (row.get("workflow"), row.get("embedding_backend"), row.get("model"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _claim_readiness(summary: Mapping[str, Any]) -> dict[str, Any]:
    provenance = (
        summary.get("index_provenance")
        if isinstance(summary.get("index_provenance"), Mapping)
        else {}
    )
    dataset = summary.get("dataset") if isinstance(summary.get("dataset"), Mapping) else {}
    backend = provenance.get("embedding_backend")
    model = provenance.get("model")
    question_count = dataset.get("num_questions")
    if (
        backend == "sentence-transformers"
        and model == PREFERRED_SEMANTIC_MODEL
        and question_count == 217
    ):
        return {
            "status": "claim-ready",
            "scope": (
                "aggregate semantic dense Naive RAG baseline on the private "
                "217-question set"
            ),
            "caveat": "answer proxy metrics and local wall-clock latency remain caveated",
        }
    if backend == "hashing":
        return {
            "status": "workflow-validation-only",
            "scope": "hashing index validates the workflow but is not a semantic dense baseline",
            "caveat": "do not use this row for semantic retrieval quality claims",
        }
    return {
        "status": "provisional",
        "scope": "private aggregate measurement",
        "caveat": "semantic model provenance or expected question count is incomplete",
    }


def build_redacted_summary(
    metrics_payload: Mapping[str, Any],
    validation: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    elapsed_ms: float,
    comparison_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = (
        metrics_payload.get("dataset")
        if isinstance(metrics_payload.get("dataset"), Mapping)
        else {}
    )
    question_count = int(dataset.get("num_questions") or validation.get("question_count") or 0)
    index_docs, index_chunks = _index_counts(Path(validation["index_dir"]))
    payload = {
        "schema_version": 1,
        "benchmark_type": "private_real_eval",
        "system": "Naive Dense RAG",
        "not_ci_smoke": True,
        "is_private_data": True,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dataset": {
            "num_documents": index_docs or validation.get("document_count"),
            "num_chunks": index_chunks,
            "num_questions": question_count,
            "answerable_count": dataset.get("answerable_count")
            or validation.get("answerable_count"),
            "unanswerable_count": dataset.get("unanswerable_count")
            or validation.get("unanswerable_count"),
        },
        "pipeline": {
            "name": "naive_baseline",
            "top_k": int(config["top_k"]),
            "retrieval_backend": "dense",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "query_expansion": "identity",
        },
        "index_provenance": _index_embedding_summary(Path(validation["index_dir"])),
        "metrics": {
            "retrieval": _safe_metric_block(
                metrics_payload.get("retrieval_metrics"),
                SAFE_RETRIEVAL_METRIC_KEYS,
            ),
            "citation_and_answer_control": _safe_metric_block(
                metrics_payload.get("answer_metrics"),
                SAFE_ANSWER_METRIC_KEYS,
            ),
        },
        "failure_type_counts": _safe_count_block(metrics_payload.get("failure_counts")),
        "latency_summary": {
            "scope": str(config.get("latency_scope") or "private_runner_wall_clock"),
            "total_wall_clock_ms": round(float(elapsed_ms), 3),
            "mean_wall_clock_ms_per_question": (
                round(float(elapsed_ms) / question_count, 3) if question_count else None
            ),
        },
        "redaction_policy": {
            "summary_only": True,
            "raw_questions_excluded": True,
            "raw_answers_excluded": True,
            "document_text_excluded": True,
            "document_names_excluded": True,
            "private_paths_excluded": True,
        },
        "known_limitations": [
            "Private aggregate only; raw cases and traces remain local.",
            "Answer metrics are deterministic contract checks, not an LLM judge.",
            "Latency is runner wall-clock unless a narrower local profiler is added.",
            "This run does not improve retrieval, reranking, prompts, chunking, or verification.",
        ],
    }
    payload["claim_readiness"] = _claim_readiness(payload)
    payload["comparison_table"] = _build_comparison_table(payload, comparison_summary)
    assert_redacted_summary_safe(payload)
    return payload


def assert_redacted_summary_safe(payload: Mapping[str, Any]) -> None:
    violations: list[str] = []

    def walk(value: Any, trail: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key)
                if key_text in FORBIDDEN_REDACTED_KEYS:
                    violations.append(f"{trail}.{key_text}".strip("."))
                if ABSOLUTE_PATH_VALUE_RE.search(key_text):
                    violations.append(f"{trail}.{key_text}".strip("."))
                if any(marker in key_text for marker in PRIVATE_PATH_MARKERS):
                    violations.append(f"{trail}.{key_text}".strip("."))
                walk(item, f"{trail}.{key_text}".strip("."))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{trail}[{index}]")
        elif isinstance(value, str):
            if ABSOLUTE_PATH_VALUE_RE.search(value) or any(
                marker in value for marker in PRIVATE_PATH_MARKERS
            ):
                violations.append(trail)

    walk(payload, "")
    if violations:
        raise PrivateRealEvalError(
            "redacted summary includes forbidden private fields: " + ", ".join(violations)
        )


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_existing_redacted_summary(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        assert_redacted_summary_safe(payload)
    except PrivateRealEvalError:
        return None
    return payload


def write_private_run_metadata(
    run_dir: Path,
    validation: Mapping[str, Any],
    *,
    build_command: Sequence[str] | None,
    elapsed_ms: float,
) -> None:
    payload = {
        "schema_version": 1,
        "benchmark_type": "private_real_eval",
        "local_only": True,
        "validation": {
            "document_count": validation.get("document_count"),
            "question_count": validation.get("question_count"),
            "answerable_count": validation.get("answerable_count"),
            "unanswerable_count": validation.get("unanswerable_count"),
            "index_exists_before_run": validation.get("index_exists"),
        },
        "index_build_command": list(build_command) if build_command else None,
        "elapsed_ms": round(float(elapsed_ms), 3),
    }
    write_json(run_dir / "private_real_eval_run.json", payload)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local/private real-data eval for the Naive RAG baseline."
    )
    parser.add_argument(
        "--config",
        default="configs/eval/private_real_eval.local.yaml",
        help="Local private config copied from configs/eval/private_real_eval.template.yaml.",
    )
    parser.add_argument("--run-id", default=None, help="Optional deterministic run id.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate local private inputs without building/running.",
    )
    parser.add_argument(
        "--redacted-summary-path",
        default=None,
        help="Optional safe aggregate summary path. Defaults to <output_dir>/<run_id>/redacted_summary.json.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = repo_path(args.config)
    try:
        config = load_private_config(config_path)
        validation = validate_private_inputs(config)
        print(
            "[OK] Private real-eval inputs validated: "
            f"{validation['document_count']} docs, "
            f"{validation['question_count']} questions "
            f"({validation['answerable_count']} answerable, "
            f"{validation['unanswerable_count']} unanswerable)"
        )
        if args.validate_only:
            return 0
        build_command = build_or_load_private_index(config, validation)
        run_id = args.run_id or str(config.get("run_id") or "").strip() or default_run_id()
        contract_path = write_contract_config(config, validation, run_id=run_id)
        started = time.perf_counter()
        run_dir = run_from_config(
            contract_path,
            output_root_override=Path(validation["output_dir"]),
            run_id_override=run_id,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metrics_path = run_dir / "metrics.json"
        metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        write_private_run_metadata(
            run_dir, validation, build_command=build_command, elapsed_ms=elapsed_ms
        )
        summary_path = (
            repo_path(args.redacted_summary_path)
            if args.redacted_summary_path
            else run_dir / "redacted_summary.json"
        )
        comparison_summary = load_existing_redacted_summary(summary_path)
        redacted_summary = build_redacted_summary(
            metrics_payload,
            validation,
            config,
            elapsed_ms=elapsed_ms,
            comparison_summary=comparison_summary,
        )
        write_json(summary_path, redacted_summary)
    except Exception as exc:
        print(f"[ERROR] Private real-eval failed: {exc}", file=sys.stderr)
        return 2

    print(f"[OK] Private Naive RAG eval artifacts written: {rel_or_abs(run_dir)}")
    print(f"[OK] Redacted summary written: {rel_or_abs(summary_path)}")
    print("[INFO] No RAG performance improvement was implemented by this runner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
