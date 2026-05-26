"""Effective-config provenance banner (issue #1212).

실행 시점에 "지금 이 run 이 실제로 어떤 backend/모드로 도는가" 를 한 눈에
보여준다. 최근 두 measurement artifact 가 모두 *실행 시점에 설정이 안 보임*
갭에서 나왔다:

1. CSV-fallback ingestion (#1129/#1133) — ``ingestion_report`` 를 사후에
   까봐야 폴백 여부를 알 수 있었다.
2. hashing 임베딩 — ``make real-eval`` 기본 ``EMBEDDING_BACKEND=hashing``
   (= feature-hashing BoW, 의미 0) 인데 실행 시점에 드러나지 않아 retrieval
   수치가 silently 오염됐다.

이 모듈은 두 진입점 (``scripts/build_index.py``, ``eval/run_eval.py``) 이
공유하는 단일 출처다. **READ-ONLY**: 어떤 retrieval/answer surface 도 바꾸지
않는다 — 순수 관측 출력. degraded(의미-맹목/폴백) 경로는 ``[WARN: ...]`` 로
강조한다.

opt-out: ``--no-config-banner`` CLI flag 또는 ``BIDMATE_NO_CONFIG_BANNER=1``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

OPT_OUT_ENV = "BIDMATE_NO_CONFIG_BANNER"

OK = "ok"
WARN = "warn"
INFO = "info"

# (label, value, status, note|None)
Row = tuple[str, str, str, "str | None"]

_TRUTHY = {"1", "true", "yes", "on"}


def banner_disabled(cli_flag: bool = False) -> bool:
    """True 면 banner 를 출력하지 않는다 (CLI flag 또는 env opt-out)."""
    if cli_flag:
        return True
    return os.environ.get(OPT_OUT_ENV, "").strip().lower() in _TRUTHY


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    return val or default


def render(title: str, rows: Iterable[Row], stream: Any = None) -> None:
    """``[CONFIG]`` banner 를 ``stream`` (기본 stderr) 에 출력한다.

    레포 관례 (``[OK]``/``[INFO]``/``[WARN]`` 접두사) 와 align. degraded row 는
    ``[WARN: ...]``, info row 는 ``[note]`` suffix 를 단다. stdout 을 오염시키지
    않도록 기본 stream 은 stderr.
    """
    if stream is None:
        stream = sys.stderr
    rows = list(rows)
    label_w = max((len(r[0]) for r in rows), default=0)
    print(f"[CONFIG] effective config · {title}", file=stream)
    for label, value, status, note in rows:
        line = f"  {label.ljust(label_w)} : {value}"
        if status == WARN:
            line += f"   [WARN: {note}]" if note else "   [WARN]"
        elif status == INFO and note:
            line += f"   [{note}]"
        print(line, file=stream)
    stream.flush()


def _embedding_row_from_backend(backend: str, model: str) -> Row:
    backend = (backend or "?").strip()
    model = (model or "?").strip()
    value = f"{backend} ({model})"
    if backend == "hashing":
        return ("embedding", value, WARN,
                "feature-hashing BoW — 의미 검색 무력, term-overlap only")
    if backend in {"openai"}:
        return ("embedding", value, INFO, "외부 API (BIDMATE_OPENAI_API_KEY)")
    return ("embedding", value, OK, None)


def _resolve_kordoc_cache(files_dir: str | None) -> str:
    """``ingestion._resolve_kordoc_cache_dir`` 와 같은 규칙을 관측용으로 재현.

    env (``BIDMATE_KORDOC_CACHE_DIR``) 우선, 없으면 sibling
    ``<files_dir>_kordoc`` 자동탐지 (#1133). import 부작용을 피하려고 여기서
    독립 구현 — 어차피 출력 전용.
    """
    env = _env("BIDMATE_KORDOC_CACHE_DIR")
    if env:
        return f"{env} (env)" if Path(env).is_dir() else f"{env} (env, MISSING)"
    if files_dir:
        parent = Path(files_dir)
        sibling = parent.with_name(parent.name + "_kordoc")
        if sibling.is_dir():
            return f"{sibling} (sibling)"
    return "(none — npx 변환 또는 csv_text 폴백)"


def build_index_rows(args: Any) -> list[Row]:
    """``scripts/build_index.py`` 문맥의 effective-config rows.

    ingestion (loader/mode/citation artifact) + embedding + chunking 축.
    """
    rows: list[Row] = [_embedding_row_from_backend(
        getattr(args, "embedding_backend", "?"), getattr(args, "model", "?"))]

    using_csv = bool(getattr(args, "metadata_csv", None))
    if using_csv:
        # loader 우선순위: build_index 가 args 를 env 로 승격하므로 env 가 진실.
        hwp = _env("BIDMATE_HWP_LOADER") or getattr(args, "hwp_loader", None) or "pdf_pymupdf4llm"
        pdf = _env("BIDMATE_PDF_LOADER") or getattr(args, "pdf_loader", None) or "pdf_pymupdf4llm"
        if hwp == "csv_text":
            rows.append(("hwp_loader", hwp, WARN, "CSV-text 폴백 — 본문 아닌 메타/표지만"))
        elif hwp == "kordoc":
            rows.append(("hwp_loader", hwp, WARN, "legacy parser — page citation 비정규"))
        else:
            rows.append(("hwp_loader", hwp, OK, None))
        if pdf == "csv_text":
            rows.append(("pdf_loader", pdf, WARN, "CSV-text 폴백 — 본문 아닌 표지/TOC만"))
        elif pdf == "kordoc":
            rows.append(("pdf_loader", pdf, WARN, "legacy parser — page citation 비정규"))
        else:
            rows.append(("pdf_loader", pdf, OK, None))
        rows.append((
            "citation_basis",
            "hwp=LibreOffice converted PDF, pdf=source PDF",
            INFO,
            None,
        ))
        rows.append((
            "hwp_pdf_artifacts",
            str(getattr(args, "hwp_pdf_artifact_dir", None) or _env("BIDMATE_HWP_PDF_ARTIFACT_DIR") or "(unset)"),
            INFO,
            None,
        ))
        if hwp == "kordoc" or pdf == "kordoc":
            rows.append(("kordoc_cache", _resolve_kordoc_cache(getattr(args, "files_dir", None)), INFO, None))
        rows.append(("ingestion_mode", str(getattr(args, "ingestion_mode", "csv-text")), OK, None))

    rows.append(("chunking", str(getattr(args, "chunking_strategy", "fixed")), OK, None))
    if _env("BIDMATE_INGEST_REDACT_PII").lower() in _TRUTHY:
        rows.append(("pii_redaction", "on", INFO, "BIDMATE_INGEST_REDACT_PII"))
    return rows


def _text_source_summary(index_dir: str | Path | None) -> str | None:
    """``<index_dir>/ingestion_report.json`` 의 text_source_counts 요약.

    구조는 ``{filetype: {source: count}}`` (예 ``{"hwp": {"kordoc": 96}}``).
    flatten 해서 ``hwp.kordoc:96, pdf.kordoc:4`` 형태로 돌려준다. 파일/필드
    없으면 None.
    """
    if index_dir is None:
        return None
    report = Path(index_dir) / "ingestion_report.json"
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    counts = (((data.get("summary") or {}).get("text_source_counts")) or {})
    if not isinstance(counts, dict) or not counts:
        return None
    pairs: list[tuple[str, int]] = []
    for ftype, sources in counts.items():
        if isinstance(sources, dict):
            for source, n in sources.items():
                pairs.append((f"{ftype}.{source}", int(n)))
        else:  # flat {source: count} fallback shape
            pairs.append((str(ftype), int(sources)))
    if not pairs:
        return None
    return ", ".join(f"{k}:{v}" for k, v in sorted(pairs, key=lambda kv: -kv[1]))


def eval_rows(index: Any, config: dict[str, Any], index_dir: str | Path | None) -> list[Row]:
    """``eval/run_eval.py`` 문맥의 effective-config rows.

    index 의 embedding/text_source (artifact 두 건 직격) + retrieval/synthesis/
    planner/vector_store 축.
    """
    rows: list[Row] = []

    emb = (index.get("embedding") or {}) if isinstance(index, dict) else {}
    rows.append(_label_as(
        _embedding_row_from_backend(str(emb.get("backend", "?")), str(emb.get("model", "?"))),
        "index.embedding"))

    text_src = _text_source_summary(index_dir)
    if text_src is not None:
        lowered = text_src.lower()
        if "hwp.data_list_csv_text" in lowered or "hwp.kordoc" in lowered:
            rows.append(("index.text_source", text_src, WARN,
                         "HWP citation-ready parser 아님"))
        elif "csv" in lowered:
            rows.append(("index.text_source", text_src, WARN,
                         "CSV 폴백 본문 — chunk/term-level 수치 무효"))
        else:
            rows.append(("index.text_source", text_src, OK, None))

    rows.append(("vector_store", _env("BIDMATE_INDEX_BACKEND", "memory"), OK, None))

    backends = sorted({
        str(r.get("retrieval_backend", "dense"))
        for r in _iter_run_configs(config)
    })
    rows.append(("retrieval", ", ".join(backends) or "dense", OK, None))

    synth = _env("BIDMATE_SYNTHESIS_BACKEND", "stub")
    if synth == "stub":
        rows.append(("synthesis", synth, INFO, "deterministic, LLM 0"))
    else:
        model = _env("BIDMATE_SYNTHESIS_MODEL")
        rows.append(("synthesis", f"{synth} ({model})" if model else synth, INFO, "외부 LLM"))

    rows.append(("rerank", _env("BIDMATE_RERANK_BACKEND", "stub"), OK, None))
    rows.append(("planner", _env("BIDMATE_PLANNER_BACKEND", "static"), OK, None))
    rows.append(("query_expansion", _env("BIDMATE_QUERY_EXPANSION_BACKEND", "identity"), OK, None))
    if _env("BIDMATE_TRACE_FULL").lower() in _TRUTHY:
        rows.append(("trace", "full", INFO, "BIDMATE_TRACE_FULL — synthesis prompt 캡처"))
    return rows


def _label_as(row: Row, label: str) -> Row:
    _, value, status, note = row
    return (label, value, status, note)


def _iter_run_configs(config: dict[str, Any]) -> Iterable[dict[str, Any]]:
    runs = config.get("ablation_runs")
    if isinstance(runs, list) and runs:
        for r in runs:
            if isinstance(r, dict):
                yield r
        return
    yield config


def emit_build_banner(args: Any, stream: Any = None) -> None:
    """build_index.py 진입점용 — opt-out 체크 후 banner 출력."""
    if banner_disabled(getattr(args, "no_config_banner", False)):
        return
    render("build (build_index.py)", build_index_rows(args), stream=stream)


def emit_eval_banner(index: Any, config: dict[str, Any], index_dir: str | Path | None,
                     cli_flag: bool = False, stream: Any = None) -> None:
    """run_eval.py 진입점용 — opt-out 체크 후 banner 출력."""
    if banner_disabled(cli_flag):
        return
    render("eval (run_eval.py)", eval_rows(index, config, index_dir), stream=stream)


__all__ = [
    "OPT_OUT_ENV",
    "banner_disabled",
    "render",
    "build_index_rows",
    "eval_rows",
    "emit_build_banner",
    "emit_eval_banner",
]
