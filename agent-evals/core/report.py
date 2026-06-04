#!/usr/bin/env python3
"""Content scanner and aggregate-report serializer for ADR 0100 agent-evals.

The scanner is intentionally conservative for committed data artifacts and
lighter for implementation files.  It enforces three layers:

* exact path allowlist for the PR2 surface;
* data-artifact key/value checks that block raw issue, PR, RFP, filename, path,
  query, answer, and evidence sinks;
* implementation import guard so the repo-neutral core does not grow a BidMate
  RAG back-edge.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


SCHEMA_VERSION = 1
SURFACE = "agent-evals-pr2"

# Data-artifact string scalars (JSON values, YAML scalars) are capped well above
# every legitimate aggregate note but far below a raw issue/PR/RFP excerpt, so an
# oversized value cannot smuggle private prose under an otherwise-innocuous key.
_MAX_DATA_STRING_LEN = 512

_ALLOWED_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^agent-evals/README\.md\Z"),
    re.compile(r"^agent-evals/core/__init__\.py\Z"),
    re.compile(r"^agent-evals/core/(schema|metrics|report)\.py\Z"),
    re.compile(r"^agent-evals/adapters/bidmate/__init__\.py\Z"),
    re.compile(r"^agent-evals/adapters/bidmate/task_mining\.py\Z"),
    re.compile(r"^agent-evals/playbooks/v(0_naive|1_spec_first)\.md\Z"),
    re.compile(r"^agent-evals/splits\.yaml\Z"),
    re.compile(r"^agent-evals/tasks/[A-Za-z0-9_.-]+/task\.yaml\Z"),
    re.compile(r"^agent-evals/reports/[A-Za-z0-9_.-]+\.aggregate\.json\Z"),
)

_CODE_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^agent-evals/core/.*\.py\Z"),
    re.compile(r"^agent-evals/adapters/bidmate/.*\.py\Z"),
)

# Recursive blocklist: these key names are forbidden at *any* depth, so a raw
# sink nested under an allowed top-level object (e.g. metrics.pr_title) or wrapped
# in a sequence cannot leak past the positive top-level allowlists below. The
# title/summary/description/excerpt/comment family has no legitimate use anywhere
# in the aggregate-only artifacts and is the raw-prose path cross-family review
# flagged (issue_title / pr_title / rfp_excerpt).
_FORBIDDEN_DATA_KEYS = frozenset(
    {
        "answer",
        "body",
        "captured_diff",
        "chunk_id",
        "chunk_text",
        "comment",
        "comments",
        "description",
        "doc_id",
        "document_id",
        "document_text",
        "evidence",
        "excerpt",
        "file_name",
        "filename",
        "issue_title",
        "local_path",
        "path",
        "patch",
        "pr_body",
        "pr_title",
        "query",
        "raw_body",
        "raw_diff",
        "raw_issue_body",
        "raw_pr_body",
        "reviewer_input",
        "rfp_body",
        "rfp_excerpt",
        "run_log",
        "summary",
        "text",
        "title",
    }
)

_FORBIDDEN_KEY_RE = re.compile(
    r"(?im)^\s*[\"']?(?:"
    + "|".join(re.escape(key) for key in sorted(_FORBIDDEN_DATA_KEYS))
    + r")[\"']?\s*[:=]"
)

_FORBIDDEN_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("absolute local path", re.compile(r"(?:/Users/|/Volumes/|/private/|/var/folders/|[A-Za-z]:\\)")),
    ("raw diff marker", re.compile(r"(?m)^(?:diff --git|@@ |--- a/|\+\+\+ b/)")),
    ("raw log marker", re.compile(r"(?i)\b(?:run-log|captured\.diff|reviewer-input|raw-dump)\b")),
    ("rfp text marker", re.compile(r"(?i)\b(?:raw rfp|rfp body|document text|chunk text)\b")),
)

_FORBIDDEN_IMPORT_PREFIXES = (
    "rag_core",
    "rag_answer",
    "rag_query",
    "rag_retrieval",
    "rag_verifier",
    "rag_vector_store",
    "ingestion",
    "visual_ingestion",
    "eval.",
    "api.",
)

# Positive top-level key schemas for committable structured data artifacts.
# The forbidden-key denylist above is a blocklist; these allowlists make the
# committable artifacts fail closed on *unknown* top-level keys so a non-forbidden
# raw sink (issue_title, pr_title, rfp_excerpt, ...) cannot ride in on a
# force-added file. Kept inline rather than imported from schema.py so the
# pre-commit boundary stays dependency-free; drift is guarded by a test that
# asserts equality with schema.ALLOWED_TASK_KEYS / schema.ALLOWED_REPORT_KEYS.
_ALLOWED_TASK_KEYS = frozenset(
    {
        "task_id",
        "source",
        "category",
        "train_hint",
        "acceptance",
        "hidden_test_gate",
        "aggregate_only_notes",
    }
)
_ALLOWED_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "surface",
        "report_id",
        "generated_by",
        "task_count",
        "playbooks",
        "metrics",
        "scanner",
        "notes",
    }
)
_ALLOWED_SPLIT_KEYS = frozenset(
    {
        "schema_version",
        "surface",
        "freshness_exclusion_days",
        "assignment",
        "notes",
    }
)

# Keys permitted inside the *nested* objects of a committable artifact. Enforcing
# the allowlist recursively (not just at the top level) is what closes the
# whack-a-mole: a raw sink nested under an allowed object (metrics.issue_body,
# scanner.pr_title, ...) fails closed regardless of whether the sink name was
# ever added to the denylist. Covers PairedDelta metric rows, playbooks, scanner
# self-attest, and the split assignment.
_ALLOWED_NESTED_KEYS = frozenset(
    {
        "metric",
        "baseline",
        "candidate",
        "n",
        "baseline_mean",
        "candidate_mean",
        "delta",
        "wins",
        "losses",
        "ties",
        "content_scan",
        "path_allowlist",
        "train",
        "holdout",
    }
)

# Under these parents the immediate child keys are free identifier *names* (e.g.
# the metric name in ``metrics.<name>``); each such value must itself be a mapping
# so a scalar raw sink (``metrics.pr_title: "..."``) cannot masquerade as a name.
_DYNAMIC_NAME_PARENTS = frozenset({"metrics"})
_DYNAMIC_NAME_RE = re.compile(r"[a-z][a-z0-9_]*\Z")


@dataclass(frozen=True)
class ScanViolation:
    path: str
    reason: str

    def render(self) -> str:
        return f"{self.path}: {self.reason}"


def _rel(path: str | Path, repo_root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        p = p.relative_to(repo_root)
    return p.as_posix()


def is_allowed_agent_eval_path(rel_path: str) -> bool:
    return any(pattern.match(rel_path) for pattern in _ALLOWED_PATH_PATTERNS)


def _is_code_path(rel_path: str) -> bool:
    return any(pattern.match(rel_path) for pattern in _CODE_PATH_PATTERNS)


def _scan_values(rel_path: str, text: str) -> list[ScanViolation]:
    out: list[ScanViolation] = []
    for label, pattern in _FORBIDDEN_VALUE_PATTERNS:
        if pattern.search(text):
            out.append(ScanViolation(rel_path, f"forbidden {label}"))
    return out


def _scan_python(rel_path: str, text: str) -> list[ScanViolation]:
    violations: list[ScanViolation] = []
    try:
        tree = ast.parse(text, filename=rel_path)
    except SyntaxError as exc:
        return violations + [ScanViolation(rel_path, f"python syntax error: {exc.msg}")]

    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            if name and any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in _FORBIDDEN_IMPORT_PREFIXES):
                violations.append(ScanViolation(rel_path, f"forbidden repo back-edge import: {name}"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if len(value) > 2000:
                violations.append(ScanViolation(rel_path, "oversized string literal could hide raw text"))
    return violations


def _scan_json_keys(rel_path: str, value: Any, *, trail: str = "$") -> list[ScanViolation]:
    violations: list[ScanViolation] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_s = str(key)
            if key_s in _FORBIDDEN_DATA_KEYS:
                violations.append(ScanViolation(rel_path, f"forbidden data key {trail}.{key_s}"))
            violations.extend(_scan_json_keys(rel_path, child, trail=f"{trail}.{key_s}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            violations.extend(_scan_json_keys(rel_path, child, trail=f"{trail}[{idx}]"))
    elif isinstance(value, str):
        if len(value) > _MAX_DATA_STRING_LEN:
            violations.append(
                ScanViolation(
                    rel_path,
                    f"oversized data string at {trail} ({len(value)} chars) could hide raw text",
                )
            )
        violations.extend(_scan_values(rel_path, value))
    return violations


def _scan_artifact_keys(
    rel_path: str,
    value: Any,
    top_allowed: frozenset[str],
    kind: str,
    *,
    trail: str = "$",
    parent_key: str | None = None,
) -> list[ScanViolation]:
    """Fail closed on unknown keys at every depth of a committable data artifact.

    Top-level keys must be in ``top_allowed``; nested keys must be in
    ``top_allowed`` or ``_ALLOWED_NESTED_KEYS``. Children of a dynamic-name parent
    (``metrics``) are free identifier names but must each be a mapping, so a scalar
    raw sink cannot ride in as a fake metric name.
    """

    violations: list[ScanViolation] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_s = str(key)
            child_trail = f"{trail}.{key_s}"
            if parent_key in _DYNAMIC_NAME_PARENTS:
                if not _DYNAMIC_NAME_RE.match(key_s):
                    violations.append(ScanViolation(rel_path, f"non-identifier key under {parent_key}: {child_trail}"))
                if not isinstance(child, Mapping):
                    violations.append(ScanViolation(rel_path, f"{parent_key} entry must be a mapping: {child_trail}"))
            elif key_s not in top_allowed and key_s not in _ALLOWED_NESTED_KEYS:
                violations.append(ScanViolation(rel_path, f"unknown {kind} key not in schema: {child_trail}"))
            violations.extend(
                _scan_artifact_keys(rel_path, child, top_allowed, kind, trail=child_trail, parent_key=key_s)
            )
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            violations.extend(
                _scan_artifact_keys(rel_path, child, top_allowed, kind, trail=f"{trail}[{idx}]", parent_key=parent_key)
            )
    return violations


def _yaml_error_summary(exc: yaml.YAMLError) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__


def _scan_yaml(rel_path: str, text: str) -> list[ScanViolation]:
    """Validate a committed YAML data artifact structurally.

    The whole-text value-pattern scan and the line-oriented forbidden-key check
    remain as dependency-free backstops, but the structural parse is what stops
    raw prose hidden under an innocuous, non-forbidden key (for example a long
    ``train_hint`` smuggling issue/PR text, or a diff marker whose start-of-line
    anchor only matches once the scalar value is extracted).
    """

    violations: list[ScanViolation] = []
    violations.extend(_scan_values(rel_path, text))
    if _FORBIDDEN_KEY_RE.search(text):
        violations.append(ScanViolation(rel_path, "forbidden raw/private data key in text artifact"))
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        violations.append(ScanViolation(rel_path, f"unparseable YAML data artifact: {_yaml_error_summary(exc)}"))
        return violations
    if parsed is None:
        return violations
    if not isinstance(parsed, Mapping):
        # A list/scalar document would otherwise skip the positive key allowlist,
        # so wrapping unknown keys in a sequence could bypass the schema gate.
        violations.append(ScanViolation(rel_path, "committable YAML artifact must be a mapping"))
        violations.extend(_scan_json_keys(rel_path, parsed))
        return violations
    if rel_path == "agent-evals/splits.yaml":
        violations.extend(_scan_artifact_keys(rel_path, parsed, _ALLOWED_SPLIT_KEYS, "split"))
    elif rel_path.endswith("/task.yaml"):
        violations.extend(_scan_artifact_keys(rel_path, parsed, _ALLOWED_TASK_KEYS, "task"))
    violations.extend(_scan_json_keys(rel_path, parsed))
    return violations


def validate_agent_eval_file(rel_path: str, text: str) -> list[ScanViolation]:
    """Validate one staged agent-evals file by repo-relative path and content."""

    violations: list[ScanViolation] = []
    if not is_allowed_agent_eval_path(rel_path):
        violations.append(ScanViolation(rel_path, "path is outside the PR2 committable allowlist"))
        return violations

    # README is the curated surface-definition document. It necessarily names
    # raw-sink classes (run logs, patches, reviewer inputs) while explaining the
    # boundary, so data-artifact token checks would be false positives here.
    if rel_path == "agent-evals/README.md":
        return violations

    if _is_code_path(rel_path):
        return _scan_python(rel_path, text)

    if rel_path.endswith(".aggregate.json"):
        violations.extend(_scan_values(rel_path, text))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            violations.append(ScanViolation(rel_path, f"invalid aggregate JSON: {exc.msg}"))
        else:
            if not isinstance(parsed, dict):
                violations.append(ScanViolation(rel_path, "aggregate report must be a JSON object"))
            violations.extend(_scan_artifact_keys(rel_path, parsed, _ALLOWED_REPORT_KEYS, "report"))
            violations.extend(_scan_json_keys(rel_path, parsed))
        return violations

    if rel_path.endswith((".yaml", ".yml")):
        return _scan_yaml(rel_path, text)

    # Remaining committable surface: curated Markdown (playbooks). These are
    # operator prose, so only value-pattern and forbidden-key text checks apply;
    # a structural parse or size cap would false-positive on legitimate long prose.
    violations.extend(_scan_values(rel_path, text))
    if _FORBIDDEN_KEY_RE.search(text):
        violations.append(ScanViolation(rel_path, "forbidden raw/private data key in text artifact"))
    return violations


def _git_staged_agent_eval_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "-z", "--name-only", "--diff-filter=ACMR", "--", "agent-evals/"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    return [item.decode("utf-8", errors="surrogateescape") for item in proc.stdout.split(b"\0") if item]


def _read_staged_text(repo_root: Path, rel_path: str) -> str:
    proc = subprocess.run(
        ["git", "show", f":{rel_path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"could not read staged content for {rel_path}: {proc.stderr.decode('utf-8', errors='replace')}")
    return proc.stdout.decode("utf-8", errors="replace")


def scan_staged(repo_root: Path) -> list[ScanViolation]:
    violations: list[ScanViolation] = []
    for rel_path in _git_staged_agent_eval_files(repo_root):
        violations.extend(validate_agent_eval_file(rel_path, _read_staged_text(repo_root, rel_path)))
    return violations


def scan_worktree_paths(repo_root: Path, paths: Iterable[str | Path]) -> list[ScanViolation]:
    violations: list[ScanViolation] = []
    for path in paths:
        rel_path = _rel(path, repo_root)
        text = (repo_root / rel_path).read_text(encoding="utf-8")
        violations.extend(validate_agent_eval_file(rel_path, text))
    return violations


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_aggregate_report(path: Path, report: Mapping[str, Any]) -> None:
    """Write a sorted aggregate report after validating serialized content."""

    text = json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    rel_path = path.as_posix()
    violations = validate_agent_eval_file(rel_path, text)
    if violations:
        rendered = "\n".join(v.render() for v in violations)
        raise ValueError(f"aggregate report failed scanner:\n{rendered}")
    path.write_text(text, encoding="utf-8")


def _render_cli_violations(violations: Sequence[ScanViolation]) -> str:
    if not violations:
        return "agent-evals content scanner: OK"
    lines = ["agent-evals content scanner: blocked non-aggregate/private content"]
    lines.extend(f"  - {violation.render()}" for violation in violations)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-staged", action="store_true", help="validate staged agent-evals/ files")
    parser.add_argument("--check-paths", nargs="*", help="validate worktree paths")
    parser.add_argument("--repo-root", default=".", help="repository root")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    violations: list[ScanViolation] = []
    if args.check_staged:
        violations.extend(scan_staged(repo_root))
    if args.check_paths is not None:
        violations.extend(scan_worktree_paths(repo_root, args.check_paths))
    if not args.check_staged and args.check_paths is None:
        parser.error("choose --check-staged or --check-paths")

    print(_render_cli_violations(violations))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
