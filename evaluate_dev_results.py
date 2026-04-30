#!/usr/bin/env python3
"""
Keyword-based evaluator for dev_queries_v1-style result CSVs.

Usage:
  python evaluate_dev_results.py \
      --results eval_results_template_filled.csv \
      --out-prefix outputs/dev_eval_run1

Input CSV must contain at least:
- qid
- question_type
- target_doc_ids
- gold_answer
- must_include
- acceptable_aliases
- should_abstain
- system_answer
- predicted_doc_ids (optional but recommended)
- latency_ms (optional)
- retry_count (optional)

This evaluator is intentionally lightweight.
It is good for baseline-to-baseline comparison, not final human judgment.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import List, Set

import pandas as pd


ABSTAIN_PATTERNS = [
    "확인되지 않는다",
    "확인되지 않",
    "명시적으로 확인되지",
    "명시돼 있지 않",
    "명시되어 있지 않",
    "문서에 없다",
    "찾을 수 없다",
    "없다",
    "알 수 없다",
    "not found",
    "not specified",
    "not mentioned",
    "cannot confirm",
]


def normalize_text(text: str) -> str:
    text = "" if text is None else str(text)
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def split_pipe_values(value: str) -> List[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split("|")]
    return [p for p in parts if p]


def parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = normalize_text(value)
    return text in {"true", "1", "y", "yes"}


def has_abstention_signal(answer: str) -> bool:
    ans = normalize_text(answer)
    return any(pat in ans for pat in ABSTAIN_PATTERNS)


def contains_any(answer: str, candidates: List[str]) -> bool:
    ans = normalize_text(answer)
    return any(normalize_text(c) in ans for c in candidates if normalize_text(c))


def count_matches(answer: str, candidates: List[str]) -> int:
    ans = normalize_text(answer)
    seen: Set[str] = set()
    count = 0
    for cand in candidates:
        norm = normalize_text(cand)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if norm in ans:
            count += 1
    return count


def safe_float(value):
    try:
        if value == "" or pd.isna(value):
            return math.nan
        return float(value)
    except Exception:
        return math.nan


def safe_int(value):
    try:
        if value == "" or pd.isna(value):
            return 0
        return int(float(value))
    except Exception:
        return 0


def evaluate_row(row: pd.Series) -> dict:
    qid = row.get("qid", "")
    qtype = row.get("question_type", "")
    system_answer = "" if pd.isna(row.get("system_answer", "")) else str(row.get("system_answer", ""))
    gold_answer = "" if pd.isna(row.get("gold_answer", "")) else str(row.get("gold_answer", ""))
    must_include = split_pipe_values(row.get("must_include", ""))
    aliases = split_pipe_values(row.get("acceptable_aliases", ""))
    should_abstain = parse_bool(row.get("should_abstain", False))

    target_doc_ids = set(split_pipe_values(row.get("target_doc_ids", "")))
    predicted_doc_ids = set(split_pipe_values(row.get("predicted_doc_ids", "")))

    answer_nonempty = int(bool(normalize_text(system_answer)))

    must_total = len(must_include)
    must_hit = count_matches(system_answer, must_include)
    alias_hit = int(contains_any(system_answer, aliases)) if aliases else 0

    if must_total > 0:
        must_recall = must_hit / must_total
    else:
        must_recall = 1.0 if answer_nonempty else 0.0

    abstain_detected = int(has_abstention_signal(system_answer))
    abstention_correct = int((should_abstain and abstain_detected) or ((not should_abstain) and (not abstain_detected)))

    doc_overlap = len(target_doc_ids & predicted_doc_ids)
    doc_hit = int(doc_overlap > 0) if target_doc_ids else 0

    if predicted_doc_ids:
        citation_precision = doc_overlap / max(1, len(predicted_doc_ids))
        citation_recall = doc_overlap / max(1, len(target_doc_ids))
    else:
        citation_precision = math.nan
        citation_recall = 0.0 if target_doc_ids else math.nan

    # Lightweight answer correctness heuristic:
    # - abstention questions: abstention must be correct
    # - non-abstention: either >=50% must-include coverage OR alias hit
    if should_abstain:
        answer_pass = abstention_correct
    else:
        answer_pass = int((must_recall >= 0.5) or alias_hit == 1)

    grounded_pass = int(doc_hit == 1 and answer_pass == 1) if predicted_doc_ids else int(answer_pass == 1)

    return {
        "qid": qid,
        "question_type": qtype,
        "answer_nonempty": answer_nonempty,
        "must_include_total": must_total,
        "must_include_hit": must_hit,
        "must_include_recall": round(must_recall, 4),
        "alias_hit": alias_hit,
        "abstain_detected": abstain_detected,
        "abstention_correct": abstention_correct,
        "target_doc_count": len(target_doc_ids),
        "predicted_doc_count": len(predicted_doc_ids),
        "doc_hit": doc_hit,
        "citation_precision": round(citation_precision, 4) if not math.isnan(citation_precision) else math.nan,
        "citation_recall": round(citation_recall, 4) if not math.isnan(citation_recall) else math.nan,
        "answer_pass": answer_pass,
        "grounded_pass": grounded_pass,
        "latency_ms": safe_float(row.get("latency_ms", "")),
        "retry_count": safe_int(row.get("retry_count", "")),
    }


def summarise(per_q: pd.DataFrame) -> dict:
    summary = {
        "n_questions": int(len(per_q)),
        "by_type": {},
        "overall": {},
    }

    def block(df: pd.DataFrame) -> dict:
        out = {
            "n": int(len(df)),
            "answer_pass_rate": round(float(df["answer_pass"].mean()), 4) if len(df) else None,
            "grounded_pass_rate": round(float(df["grounded_pass"].mean()), 4) if len(df) else None,
            "must_include_recall_mean": round(float(df["must_include_recall"].mean()), 4) if len(df) else None,
            "abstention_correct_rate": round(float(df["abstention_correct"].mean()), 4) if len(df) else None,
            "doc_hit_rate": round(float(df["doc_hit"].mean()), 4) if len(df) else None,
            "citation_precision_mean": round(float(df["citation_precision"].dropna().mean()), 4) if df["citation_precision"].notna().any() else None,
            "citation_recall_mean": round(float(df["citation_recall"].dropna().mean()), 4) if df["citation_recall"].notna().any() else None,
            "latency_ms_mean": round(float(df["latency_ms"].dropna().mean()), 2) if df["latency_ms"].notna().any() else None,
            "retry_count_mean": round(float(df["retry_count"].mean()), 4) if len(df) else None,
        }
        return out

    summary["overall"] = block(per_q)
    for qtype, sub in per_q.groupby("question_type"):
        summary["by_type"][qtype] = block(sub)

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, help="Filled results CSV path")
    parser.add_argument("--out-prefix", required=True, help="Output prefix, e.g. outputs/dev_eval_run1")
    args = parser.parse_args()

    results_path = Path(args.results)
    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(results_path)
    required = ["qid", "question_type", "target_doc_ids", "gold_answer", "must_include", "acceptable_aliases", "should_abstain", "system_answer"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {missing}")

    per_q_rows = []
    for _, row in df.iterrows():
        merged = row.to_dict()
        merged.update(evaluate_row(row))
        per_q_rows.append(merged)

    per_q = pd.DataFrame(per_q_rows)
    summary = summarise(per_q)

    per_q_path = out_prefix.with_name(out_prefix.name + "_per_question.csv")
    summary_path = out_prefix.with_name(out_prefix.name + "_summary.json")
    markdown_path = out_prefix.with_name(out_prefix.name + "_summary.md")

    per_q.to_csv(per_q_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    lines.append(f"# Evaluation summary: {out_prefix.name}")
    lines.append("")
    ov = summary["overall"]
    lines.append("## Overall")
    lines.append("")
    for key, value in ov.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## By question type")
    lines.append("")
    for qtype, block in summary["by_type"].items():
        lines.append(f"### {qtype}")
        lines.append("")
        for key, value in block.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote: {per_q_path}")
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {markdown_path}")


if __name__ == "__main__":
    main()
