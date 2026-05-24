"""CLI runner for the Naive RAG Evaluation Contract."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.naive_rag.metrics import (  # noqa: E402
    ANSWER_METRIC_KEYS,
    RETRIEVAL_METRIC_KEYS,
    contains_terms,
    retrieval_metrics,
    summarize_case_metrics,
    unique_ids,
)
from eval.naive_rag.taxonomy import ALL_FAILURE_TYPES, classify_failure, count_failures  # noqa: E402
from eval.scorers._shared import answer_citations, answer_to_text  # noqa: E402
from rag_core import load_index, run_rag_query  # noqa: E402


REQUIRED_OUTPUTS = (
    "metrics.json",
    "retrieved_chunks.jsonl",
    "answers.jsonl",
    "failure_cases.jsonl",
    "summary.md",
)


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL row must be an object at {path}:{lineno}")
        rows.append(payload)
    return rows


def load_contract_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    pipeline = payload.get("pipeline")
    if not isinstance(pipeline, dict):
        raise ValueError("Config must include pipeline mapping")
    required = {
        "name": "naive_baseline",
        "retrieval_backend": "dense",
        "metadata_first": False,
        "rerank": False,
        "verifier_retry": False,
        "query_expansion": "identity",
    }
    for key, expected in required.items():
        actual = pipeline.get(key)
        if actual != expected:
            raise ValueError(f"Naive RAG contract requires pipeline.{key}={expected!r}, got {actual!r}")
    if int(pipeline.get("top_k") or 0) < 10:
        raise ValueError("Naive RAG contract requires pipeline.top_k >= 10")
    return payload


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions = _jsonl_rows(path)
    seen: set[str] = set()
    for row in questions:
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            raise ValueError(f"Question row missing question_id: {row}")
        if qid in seen:
            raise ValueError(f"Duplicate question_id: {qid}")
        if not str(row.get("question") or "").strip():
            raise ValueError(f"Question row missing question text: {qid}")
        row["question_id"] = qid
        row["answerable"] = bool(row.get("answerable", True))
        seen.add(qid)
    answerable = sum(1 for row in questions if row["answerable"])
    unanswerable = sum(1 for row in questions if not row["answerable"])
    if answerable < 10:
        raise ValueError(f"Naive contract requires at least 10 answerable questions, got {answerable}")
    if unanswerable < 3:
        raise ValueError(f"Naive contract requires at least 3 unanswerable questions, got {unanswerable}")
    return questions


def load_gold_evidence(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_question: dict[str, list[dict[str, Any]]] = {}
    for row in _jsonl_rows(path):
        qid = str(row.get("question_id") or "").strip()
        if not qid:
            raise ValueError(f"Gold evidence row missing question_id: {row}")
        evidence = row.get("gold_evidence")
        if evidence is None:
            evidence = [row]
        if not isinstance(evidence, list):
            raise ValueError(f"gold_evidence must be a list for {qid}")
        cleaned: list[dict[str, Any]] = []
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError(f"gold_evidence item must be an object for {qid}")
            cleaned.append(dict(item))
        by_question.setdefault(qid, []).extend(cleaned)
    return by_question


def _compact_retrieved_chunks(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = prediction.get("diagnostics") or {}
    raw = diagnostics.get("retrieved_chunks") or []
    rows: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for rank, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            rows.append(
                {
                    "rank": int(item.get("rank") or rank),
                    "chunk_id": chunk_id,
                    "doc_id": str(item.get("doc_id") or ""),
                    "score": item.get("score"),
                    "score_parts": item.get("score_parts") if isinstance(item.get("score_parts"), dict) else {},
                    "section": str(item.get("section") or ""),
                    "page_span": item.get("page_span"),
                    "text_preview": str(item.get("text_preview") or "")[:300],
                }
            )
    if rows:
        return rows
    return [
        {
            "rank": rank,
            "chunk_id": str(chunk_id),
            "doc_id": "",
            "score": None,
            "score_parts": {},
            "section": "",
            "page_span": None,
            "text_preview": "",
        }
        for rank, chunk_id in enumerate(diagnostics.get("retrieved_chunk_ids") or [], start=1)
        if chunk_id
    ]


def _answer_status(prediction: dict[str, Any]) -> str:
    answer = prediction.get("answer")
    if isinstance(answer, dict) and answer.get("status"):
        return str(answer["status"])
    diagnostics = prediction.get("diagnostics") or {}
    return str(diagnostics.get("answer_status") or "")


def answer_metrics_for_case(
    question: dict[str, Any],
    prediction: dict[str, Any],
    gold_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
) -> dict[str, float | int | None]:
    answerable = bool(question.get("answerable", True))
    citations = answer_citations(prediction)
    cited_chunk_ids = unique_ids([str(citation.get("chunk_id") or "") for citation in citations])
    answer_text = answer_to_text(prediction)
    status = _answer_status(prediction)

    if answerable:
        term_coverage = contains_terms(answer_text, [str(term) for term in question.get("expected_terms") or []])
        if cited_chunk_ids:
            citation_chunk_accuracy: float | None = (
                sum(1 for chunk_id in cited_chunk_ids if chunk_id in set(gold_chunk_ids))
                / len(cited_chunk_ids)
            )
            rule_based_groundedness: float | None = (
                1.0 if set(cited_chunk_ids).issubset(set(retrieved_chunk_ids)) else 0.0
            )
        else:
            citation_chunk_accuracy = 0.0
            rule_based_groundedness = 0.0
        generator_hallucination = (
            1 if status == "supported" and cited_chunk_ids and citation_chunk_accuracy == 0.0 else 0
        )
        unsupported_answer = (
            1
            if status == "supported"
            and (not cited_chunk_ids or citation_chunk_accuracy == 0.0 or rule_based_groundedness == 0.0)
            else 0
        )
        failed_abstention = None
        unanswerable_detection = None
    else:
        term_coverage = None
        citation_chunk_accuracy = None
        rule_based_groundedness = None
        unanswerable_detected = status == "insufficient" or bool(
            (prediction.get("diagnostics") or {}).get("abstained")
        )
        unanswerable_detection = 1 if unanswerable_detected else 0
        failed_abstention = 0 if unanswerable_detected else 1
        unsupported_answer = failed_abstention
        generator_hallucination = None

    return {
        "rule_based_groundedness": rule_based_groundedness,
        "term_coverage_accuracy": term_coverage,
        "citation_chunk_accuracy": citation_chunk_accuracy,
        "generator_hallucination_flag": generator_hallucination,
        "failed_abstention_flag": failed_abstention,
        "unsupported_answer_flag": unsupported_answer,
        "unanswerable_detection_flag": unanswerable_detection,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _summary_markdown(metrics: dict[str, Any]) -> str:
    retrieval = metrics["retrieval_metrics"]
    answer = metrics["answer_metrics"]
    lines = [
        "# Naive RAG Smoke/Regression Evaluation Summary",
        "",
        "> Warning: this public fixture contract is for CI smoke/regression only, not RAG performance benchmarking.",
        "",
        f"- Run ID: `{metrics['run_id']}`",
        f"- Questions: {metrics['dataset']['num_questions']} "
        f"({metrics['dataset']['answerable_count']} answerable, "
        f"{metrics['dataset']['unanswerable_count']} unanswerable)",
        f"- Output directory: `{metrics['output_dir']}`",
        "",
        "## Retrieval Metrics",
        "",
        "| metric | mean | n | missing |",
        "|---|---:|---:|---:|",
    ]
    for key in RETRIEVAL_METRIC_KEYS:
        block = retrieval[key]
        mean = "null" if block["mean"] is None else f"{block['mean']:.4f}"
        lines.append(f"| `{key}` | {mean} | {block['n']} | {block['missing']} |")
    lines.extend(["", "## Answer Metrics", "", "| metric | mean | n | missing |", "|---|---:|---:|---:|"])
    for key in ANSWER_METRIC_KEYS:
        block = answer[key]
        mean = "null" if block["mean"] is None else f"{block['mean']:.4f}"
        lines.append(f"| `{key}` | {mean} | {block['n']} | {block['missing']} |")
    lines.extend(
        [
            "",
            "## Contract Boundary",
            "",
            "This run uses dense top-k retrieval only. Reranking, hybrid BM25+dense search, "
            "metadata filtering, query rewriting, self-correction, agentic retrieval, VLM "
            "grounding, and citation verification are intentionally out of scope.",
            "",
            "Answer metrics are rule-based smoke signals: `rule_based_groundedness` is not "
            "semantic Faithfulness, and `term_coverage_accuracy` is not semantic Answer Relevancy.",
            "",
        ]
    )
    return "\n".join(lines)


def run_from_config(
    config_path: Path,
    *,
    output_root_override: Path | None = None,
    run_id_override: str | None = None,
) -> Path:
    config_path = _repo_path(config_path)
    config = load_contract_config(config_path)
    questions_path = _repo_path(config["questions_path"])
    gold_path = _repo_path(config["gold_evidence_path"])
    index_dir = _repo_path(config.get("index_dir", "data/index"))
    output_root = output_root_override or _repo_path(config.get("output_root", "experiments/runs"))
    run_id = run_id_override or str(config.get("run_id") or "").strip()
    if not run_id:
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = load_questions(questions_path)
    gold_by_question = load_gold_evidence(gold_path)
    index = load_index(index_dir)
    pipeline = config["pipeline"]

    retrieved_rows: list[dict[str, Any]] = []
    answer_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    retrieval_case_metrics: list[dict[str, Any]] = []
    answer_case_metrics: list[dict[str, Any]] = []
    primary_failures: list[str | None] = []

    for question in questions:
        qid = str(question["question_id"])
        prediction = run_rag_query(
            index,
            str(question["question"]),
            pipeline=str(pipeline["name"]),
            top_k=int(pipeline["top_k"]),
            metadata_first=False,
            rerank=False,
            rerank_cross_encoder=False,
            verifier_retry=False,
            retrieval_mode=str(pipeline.get("retrieval_mode", "flat")),
            retrieval_backend="dense",
            prompt_profile=str(pipeline.get("prompt_profile") or ""),
            bm25_tokenizer=str(pipeline.get("bm25_tokenizer", "regex")),
            bm25_backend=str(pipeline.get("bm25_backend", "okapi")),
            _skip_graph=True,
        )
        retrieved_chunks = _compact_retrieved_chunks(prediction)
        retrieved_chunk_ids = unique_ids([str(item["chunk_id"]) for item in retrieved_chunks])
        gold_evidence = gold_by_question.get(qid, [])
        gold_chunk_ids = unique_ids([str(item.get("chunk_id") or "") for item in gold_evidence])
        retrieval_metric = retrieval_metrics(retrieved_chunk_ids, gold_chunk_ids)
        answer_metric = answer_metrics_for_case(
            question,
            prediction,
            gold_chunk_ids,
            retrieved_chunk_ids,
        )
        citations = answer_citations(prediction)
        cited_chunk_ids = unique_ids([str(citation.get("chunk_id") or "") for citation in citations])
        primary_failure, all_failures = classify_failure(
            question=question,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=retrieved_chunk_ids,
            cited_chunk_ids=cited_chunk_ids,
            retrieval_metrics=retrieval_metric,
            answer_metrics=answer_metric,
        )

        retrieval_case_metrics.append(retrieval_metric)
        answer_case_metrics.append(answer_metric)
        primary_failures.append(primary_failure)

        retrieved_row = {
            "run_id": run_id,
            "question_id": qid,
            "question": question["question"],
            "answerable": bool(question.get("answerable", True)),
            "gold_chunk_ids": gold_chunk_ids,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_chunks": retrieved_chunks,
            "retrieval_metrics": retrieval_metric,
        }
        answer_row = {
            "run_id": run_id,
            "question_id": qid,
            "question": question["question"],
            "answerable": bool(question.get("answerable", True)),
            "answer_status": _answer_status(prediction),
            "answer_text": answer_to_text(prediction),
            "claims": (prediction.get("answer") or {}).get("claims") if isinstance(prediction.get("answer"), dict) else [],
            "citations": citations,
            "gold_evidence": gold_evidence,
            "retrieval_metrics": retrieval_metric,
            "answer_metrics": answer_metric,
        }
        retrieved_rows.append(retrieved_row)
        answer_rows.append(answer_row)

        if primary_failure:
            failure_rows.append(
                {
                    "run_id": run_id,
                    "question_id": qid,
                    "question": question["question"],
                    "failure_type": primary_failure,
                    "additional_failure_types": all_failures[1:],
                    "metrics": {
                        "retrieval": retrieval_metric,
                        "answer": answer_metric,
                    },
                    "gold_evidence": gold_evidence,
                    "retrieved_chunks": retrieved_chunks,
                    "answer": {
                        "status": _answer_status(prediction),
                        "text": answer_to_text(prediction),
                        "citations": citations,
                    },
                }
            )

    artifact_paths = {name: output_dir / name for name in REQUIRED_OUTPUTS}
    _write_jsonl(artifact_paths["retrieved_chunks.jsonl"], retrieved_rows)
    _write_jsonl(artifact_paths["answers.jsonl"], answer_rows)
    _write_jsonl(artifact_paths["failure_cases.jsonl"], failure_rows)

    dataset = {
        "questions_path": _relative(questions_path),
        "gold_evidence_path": _relative(gold_path),
        "num_questions": len(questions),
        "answerable_count": sum(1 for row in questions if row.get("answerable", True)),
        "unanswerable_count": sum(1 for row in questions if not row.get("answerable", True)),
    }
    metrics_payload: dict[str, Any] = {
        "schema_version": 1,
        "contract": "naive_rag_quality_v1",
        "evaluation_type": "public_fixture_smoke_regression",
        "valid_for_performance_claims": False,
        "run_id": run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config_path": _relative(config_path),
        "output_dir": _relative(output_dir),
        "index_dir": _relative(index_dir),
        "pipeline": {
            "name": pipeline["name"],
            "top_k": int(pipeline["top_k"]),
            "retrieval_backend": "dense",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "query_expansion": "identity",
        },
        "dataset": dataset,
        "retrieval_metrics": summarize_case_metrics(retrieval_case_metrics, RETRIEVAL_METRIC_KEYS),
        "answer_metrics": summarize_case_metrics(answer_case_metrics, ANSWER_METRIC_KEYS),
        "failure_counts": count_failures(primary_failures),
        "failure_taxonomy": list(ALL_FAILURE_TYPES),
        "artifact_paths": {name: _relative(path) for name, path in artifact_paths.items()},
    }
    artifact_paths["metrics.json"].write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifact_paths["summary.md"].write_text(_summary_markdown(metrics_payload), encoding="utf-8")
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Naive RAG Evaluation Contract.")
    parser.add_argument("--config", required=True, help="Path to configs/eval/rag_quality_v1.yaml")
    parser.add_argument("--run-id", default=None, help="Optional deterministic run id override.")
    parser.add_argument("--output-root", default=None, help="Optional output root override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output_dir = run_from_config(
            Path(args.config),
            output_root_override=Path(args.output_root) if args.output_root else None,
            run_id_override=args.run_id,
        )
    except Exception as exc:
        print(f"[ERROR] Naive RAG eval failed: {exc}", file=sys.stderr)
        return 2
    print(f"[OK] Naive RAG eval artifacts written: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
