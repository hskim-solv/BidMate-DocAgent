#!/usr/bin/env python3
"""Resolve and check local/private paths for the opt-in real eval.

The private real-eval surface is intentionally local-only: configs, source
documents, caches, indexes, and generated reports must not be committed. This
module keeps the path dependency graph explicit so worktrees can point at an
external private root without hard-coding repo-relative paths.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
PRIVATE_REAL_MIN_DOCS = 50
LOW_CHUNK_REAL_MAX = 1000


@dataclass(frozen=True)
class PathEntry:
    name: str
    path: str
    category: str
    referenced_by: str
    required_before_run: bool
    can_regenerate: bool
    recommended_env_config_key: str
    source: str
    exists: bool
    status: str
    message: str
    num_documents: int | None = None
    num_chunks: int | None = None


def _arg_value(args: argparse.Namespace | None, key: str) -> str | None:
    if args is None:
        return None
    value = getattr(args, key, None)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _root_from(
    args: argparse.Namespace | None,
    environ: Mapping[str, str],
    repo_root: Path,
) -> tuple[Path, str]:
    cli = _arg_value(args, "root")
    if cli:
        return _resolve_path(cli, repo_root), "cli"
    env = environ.get("REAL_EVAL_ROOT")
    if env:
        return _resolve_path(env, repo_root), "env:REAL_EVAL_ROOT"
    return repo_root, "default"


def _resolve_path(value: str | Path, base: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return base / path


_ENV_DEFAULT_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_defaults(value: Any, environ: Mapping[str, str]) -> Any:
    if not isinstance(value, str):
        return value

    def repl(match: re.Match[str]) -> str:
        env_key = match.group(1)
        default = match.group(2) or ""
        return environ.get(env_key) or default

    return _ENV_DEFAULT_RE.sub(repl, value)


def _read_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{config_path} must contain a YAML mapping")
    return payload


def _config_value(config: Mapping[str, Any], keys: Sequence[str]) -> Any:
    cursor: Any = config
    for key in keys:
        if not isinstance(cursor, Mapping):
            return None
        cursor = cursor.get(key)
    return cursor


def _choose_path(
    *,
    args: argparse.Namespace | None,
    arg_name: str,
    environ: Mapping[str, str],
    env_name: str,
    config: Mapping[str, Any],
    config_keys: Sequence[str],
    default: str,
    base: Path,
) -> tuple[Path, str]:
    cli = _arg_value(args, arg_name)
    if cli:
        return _resolve_path(cli, base), "cli"
    env = environ.get(env_name)
    if env:
        return _resolve_path(env, base), f"env:{env_name}"
    cfg = _expand_env_defaults(_config_value(config, config_keys), environ)
    if cfg:
        return _resolve_path(str(cfg), base), "config:" + ".".join(config_keys)
    return _resolve_path(default, base), "default"


def _index_counts(index_dir: Path) -> tuple[int | None, int | None, str | None]:
    index_json = index_dir / "index.json"
    if not index_json.exists():
        return None, None, None
    try:
        payload = json.loads(index_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"index metadata unreadable: {exc}"
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
        docs_int = int(docs) if docs is not None else None
    except (TypeError, ValueError):
        docs_int = None
    try:
        chunks_int = int(chunks) if chunks is not None else None
    except (TypeError, ValueError):
        chunks_int = None
    return docs_int, chunks_int, None


def _entry_status(
    *,
    name: str,
    path: Path,
    kind: str,
    required_before_run: bool,
    can_regenerate: bool,
    category: str,
) -> tuple[bool, str, str, int | None, int | None]:
    exists = path.is_file() if kind == "file" else path.is_dir()
    num_docs: int | None = None
    num_chunks: int | None = None
    if name == "index_dir" and path.exists():
        num_docs, num_chunks, count_error = _index_counts(path)
        if count_error:
            return exists, "warn", count_error, num_docs, num_chunks
        if (
            num_docs is not None
            and num_chunks is not None
            and num_docs >= PRIVATE_REAL_MIN_DOCS
            and 0 < num_chunks <= LOW_CHUNK_REAL_MAX
        ):
            return (
                exists,
                "invalid",
                "stale/invalid CSV-fallback index; rebuild from kordoc cache/source",
                num_docs,
                num_chunks,
            )
    if exists:
        if name == "index_dir" and num_docs is not None and num_chunks is not None:
            return exists, "ok", f"index metadata: {num_docs} docs, {num_chunks} chunks", num_docs, num_chunks
        return exists, "ok", "present", num_docs, num_chunks
    if required_before_run:
        return exists, "missing-required", "required input is missing", num_docs, num_chunks
    if category == "output artifact":
        return exists, "creatable", "will be created during the run", num_docs, num_chunks
    if can_regenerate:
        return exists, "regenerable-missing", "missing; will be regenerated when source inputs exist", num_docs, num_chunks
    return exists, "optional-missing", "optional input is not configured/present", num_docs, num_chunks


def _make_entry(
    *,
    name: str,
    path: Path,
    category: str,
    referenced_by: str,
    required_before_run: bool,
    can_regenerate: bool,
    recommended_env_config_key: str,
    source: str,
    kind: str,
) -> PathEntry:
    exists, status, message, num_docs, num_chunks = _entry_status(
        name=name,
        path=path,
        kind=kind,
        required_before_run=required_before_run,
        can_regenerate=can_regenerate,
        category=category,
    )
    return PathEntry(
        name=name,
        path=str(path),
        category=category,
        referenced_by=referenced_by,
        required_before_run=required_before_run,
        can_regenerate=can_regenerate,
        recommended_env_config_key=recommended_env_config_key,
        source=source,
        exists=exists,
        status=status,
        message=message,
        num_documents=num_docs,
        num_chunks=num_chunks,
    )


def resolve_entries(
    args: argparse.Namespace | None = None,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> list[PathEntry]:
    env = environ if environ is not None else os.environ
    root = repo_root or ROOT_DIR
    real_root, root_source = _root_from(args, env, root)

    config_cli = _arg_value(args, "config")
    if config_cli:
        config_path = _resolve_path(config_cli, real_root)
        config_source = "cli"
    elif env.get("REAL_EVAL_CONFIG"):
        config_path = _resolve_path(env["REAL_EVAL_CONFIG"], real_root)
        config_source = "env:REAL_EVAL_CONFIG"
    else:
        config_path = real_root / "eval" / "real_config.local.yaml"
        config_source = "default"

    config = _read_config(config_path)
    real_eval_config = config.get("real_eval") if isinstance(config.get("real_eval"), Mapping) else {}

    data_list, data_list_source = _choose_path(
        args=args,
        arg_name="data_list",
        environ=env,
        env_name="REAL_EVAL_DATA_LIST",
        config=real_eval_config,
        config_keys=("data_list",),
        default="data/data_list.csv",
        base=real_root,
    )
    data_dir, data_dir_source = _choose_path(
        args=args,
        arg_name="data_dir",
        environ=env,
        env_name="REAL_EVAL_DATA_DIR",
        config=real_eval_config,
        config_keys=("document_dirs", "default"),
        default="data/files",
        base=real_root,
    )
    kordoc_data_dir, kordoc_source = _choose_path(
        args=args,
        arg_name="kordoc_data_dir",
        environ=env,
        env_name="REAL_EVAL_KORDOC_DATA_DIR",
        config=real_eval_config,
        config_keys=("document_dirs", "kordoc"),
        default="data/files_kordoc",
        base=real_root,
    )
    cache_dir, cache_source = _choose_path(
        args=args,
        arg_name="cache_dir",
        environ=env,
        env_name="REAL_EVAL_CACHE_DIR",
        config=real_eval_config,
        config_keys=("cache", "root"),
        default=".cache/real_eval",
        base=real_root,
    )
    index_dir, index_source = _choose_path(
        args=args,
        arg_name="index_dir",
        environ=env,
        env_name="REAL_EVAL_INDEX_DIR",
        config=real_eval_config,
        config_keys=("index", "root"),
        default="data/index/real100",
        base=real_root,
    )
    report_dir, report_source = _choose_path(
        args=args,
        arg_name="report_dir",
        environ=env,
        env_name="REAL_EVAL_REPORT_DIR",
        config=real_eval_config,
        config_keys=("reports", "output_dir"),
        default="reports/real100",
        base=real_root,
    )
    baseline_value = _arg_value(args, "baseline_summary")
    if baseline_value:
        baseline_path = _resolve_path(baseline_value, real_root)
        baseline_source = "cli"
    elif env.get("REAL_EVAL_BASELINE_SUMMARY"):
        baseline_path = _resolve_path(env["REAL_EVAL_BASELINE_SUMMARY"], real_root)
        baseline_source = "env:REAL_EVAL_BASELINE_SUMMARY"
    else:
        cfg = _expand_env_defaults(
            _config_value(real_eval_config, ("reports", "baseline_summary")),
            env,
        )
        if cfg:
            baseline_path = _resolve_path(str(cfg), real_root)
            baseline_source = "config:reports.baseline_summary"
        else:
            baseline_path = report_dir / "baseline.aggregate.json"
            baseline_source = "default"

    entries = [
        _make_entry(
            name="real_eval_root",
            path=real_root,
            category="context root",
            referenced_by="scripts/real_eval_paths.py",
            required_before_run=False,
            can_regenerate=False,
            recommended_env_config_key="REAL_EVAL_ROOT",
            source=root_source,
            kind="dir",
        ),
        _make_entry(
            name="config",
            path=config_path,
            category="required input",
            referenced_by="eval/run_eval.py --config, scripts/smoke_real.sh",
            required_before_run=True,
            can_regenerate=False,
            recommended_env_config_key="REAL_EVAL_CONFIG",
            source=config_source,
            kind="file",
        ),
        _make_entry(
            name="data_list",
            path=data_list,
            category="required input",
            referenced_by="scripts/validate_data_list.py, scripts/build_index.py",
            required_before_run=True,
            can_regenerate=False,
            recommended_env_config_key="REAL_EVAL_DATA_LIST or real_eval.data_list",
            source=data_list_source,
            kind="file",
        ),
        _make_entry(
            name="data_dir",
            path=data_dir,
            category="required input",
            referenced_by="scripts/validate_data_list.py --files_dir, scripts/build_index.py --files_dir",
            required_before_run=True,
            can_regenerate=False,
            recommended_env_config_key="REAL_EVAL_DATA_DIR or real_eval.document_dirs.default",
            source=data_dir_source,
            kind="dir",
        ),
        _make_entry(
            name="kordoc_data_dir",
            path=kordoc_data_dir,
            category="regenerable cache",
            referenced_by="BIDMATE_KORDOC_CACHE_DIR, scripts/build_kordoc_manifest.py",
            required_before_run=False,
            can_regenerate=True,
            recommended_env_config_key="REAL_EVAL_KORDOC_DATA_DIR or real_eval.document_dirs.kordoc",
            source=kordoc_source,
            kind="dir",
        ),
        _make_entry(
            name="cache_dir",
            path=cache_dir,
            category="regenerable cache",
            referenced_by="OCR/parsed/layout/embedding cache root",
            required_before_run=False,
            can_regenerate=True,
            recommended_env_config_key="REAL_EVAL_CACHE_DIR or real_eval.cache.root",
            source=cache_source,
            kind="dir",
        ),
        _make_entry(
            name="index_dir",
            path=index_dir,
            category="regenerable cache",
            referenced_by="app.py --input_dir, eval/run_eval.py --index_dir",
            required_before_run=False,
            can_regenerate=True,
            recommended_env_config_key="REAL_EVAL_INDEX_DIR or real_eval.index.root",
            source=index_source,
            kind="dir",
        ),
        _make_entry(
            name="report_dir",
            path=report_dir,
            category="output artifact",
            referenced_by="eval/run_eval.py --output_dir, scripts/run_real_eval_delta.py",
            required_before_run=False,
            can_regenerate=True,
            recommended_env_config_key="REAL_EVAL_REPORT_DIR or real_eval.reports.output_dir",
            source=report_source,
            kind="dir",
        ),
        _make_entry(
            name="eval_summary",
            path=report_dir / "eval_summary.json",
            category="output artifact",
            referenced_by="make real-eval, scripts/run_real_eval_delta.py --head",
            required_before_run=False,
            can_regenerate=True,
            recommended_env_config_key="REAL_EVAL_REPORT_DIR/eval_summary.json",
            source="derived:report_dir",
            kind="file",
        ),
        _make_entry(
            name="baseline_summary",
            path=baseline_path,
            category="optional input",
            referenced_by="scripts/run_real_eval_delta.py --base",
            required_before_run=False,
            can_regenerate=False,
            recommended_env_config_key="REAL_EVAL_BASELINE_SUMMARY or real_eval.reports.baseline_summary",
            source=baseline_source,
            kind="file",
        ),
    ]
    return entries


def missing_required(entries: Sequence[PathEntry]) -> list[PathEntry]:
    return [e for e in entries if e.required_before_run and not e.exists]


def _table(entries: Sequence[PathEntry]) -> str:
    headers = [
        "name",
        "category",
        "status",
        "source",
        "path",
        "message",
    ]
    rows = [
        [e.name, e.category, e.status, e.source, e.path, e.message]
        for e in entries
    ]
    widths = [
        max(len(str(row[i])) for row in ([headers] + rows))
        for i in range(len(headers))
    ]
    lines = [
        " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))),
        " | ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in rows:
        lines.append(" | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def _shell(entries: Sequence[PathEntry]) -> str:
    by_name = {e.name: e for e in entries}
    mapping = {
        "REAL_EVAL_RESOLVED_ROOT": "real_eval_root",
        "REAL_EVAL_RESOLVED_CONFIG": "config",
        "REAL_EVAL_RESOLVED_DATA_LIST": "data_list",
        "REAL_EVAL_RESOLVED_DATA_DIR": "data_dir",
        "REAL_EVAL_RESOLVED_KORDOC_DATA_DIR": "kordoc_data_dir",
        "REAL_EVAL_RESOLVED_CACHE_DIR": "cache_dir",
        "REAL_EVAL_RESOLVED_INDEX_DIR": "index_dir",
        "REAL_EVAL_RESOLVED_REPORT_DIR": "report_dir",
        "REAL_EVAL_RESOLVED_EVAL_SUMMARY": "eval_summary",
        "REAL_EVAL_RESOLVED_BASELINE_SUMMARY": "baseline_summary",
    }
    lines = []
    for env_key, entry_key in mapping.items():
        lines.append(f"{env_key}={shlex.quote(by_name[entry_key].path)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    for name in ("check", "inventory"):
        sp = sub.add_parser(name)
        sp.add_argument("--root")
        sp.add_argument("--config")
        sp.add_argument("--data-list")
        sp.add_argument("--data-dir")
        sp.add_argument("--kordoc-data-dir")
        sp.add_argument("--cache-dir")
        sp.add_argument("--index-dir")
        sp.add_argument("--report-dir")
        sp.add_argument("--baseline-summary")
        if name == "inventory":
            sp.add_argument("--format", choices=["table", "json", "shell"], default="table")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "inventory"
        args.format = "table"

    try:
        entries = resolve_entries(args)
    except Exception as exc:
        print(f"[ERROR] real-eval path resolution failed: {exc}", file=sys.stderr)
        return 2

    if args.command == "inventory":
        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2))
        elif fmt == "shell":
            print(_shell(entries))
        else:
            print(_table(entries))
        return 0

    print(_table(entries), flush=True)
    missing = missing_required(entries)
    if missing:
        print("\nMissing required private real-eval inputs:", file=sys.stderr)
        for entry in missing:
            print(
                f"- {entry.name}: {entry.path} "
                f"(set {entry.recommended_env_config_key})",
                file=sys.stderr,
            )
        print(
            "\nCreate/copy private inputs outside git, or point REAL_EVAL_ROOT / "
            "REAL_EVAL_* env vars at the private eval root.",
            file=sys.stderr,
        )
        return 1
    invalid = [e for e in entries if e.status == "invalid"]
    if invalid:
        print("\nWarnings:", file=sys.stderr)
        for entry in invalid:
            suffix = ""
            if entry.num_documents is not None and entry.num_chunks is not None:
                suffix = f" ({entry.num_documents} docs, {entry.num_chunks} chunks)"
            print(f"- {entry.name}: {entry.message}{suffix}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
